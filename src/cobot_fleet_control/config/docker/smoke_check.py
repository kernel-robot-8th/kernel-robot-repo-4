"""Start the installed fleet and web in isolation, check HTTP/WS, then stop them."""

import base64
import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from ament_index_python.packages import get_package_share_directory

from cobot_fleet_control.control_center_web import build_plan
from cobot_fleet_control.web_profiles import export_profiles


def websocket_snapshot(port, path):
    """Check a real WebSocket upgrade and its initial JSON snapshot without extra packages."""
    def read_exact(stream, size):
        data = bytearray()
        while len(data) < size:
            part = stream.recv(size - len(data))
            if not part:
                raise RuntimeError('WebSocket closed before the snapshot')
            data.extend(part)
        return bytes(data)

    with socket.create_connection(('127.0.0.1', port), timeout=3) as stream:
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        stream.sendall((
            f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
            f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        ).encode('ascii'))
        header = bytearray()
        while not header.endswith(b'\r\n\r\n'):
            header.extend(read_exact(stream, 1))
            if len(header) > 16384:
                raise RuntimeError('WebSocket response headers are too large')
        lines = header.decode('ascii').split('\r\n')
        expected = base64.b64encode(hashlib.sha1(
            (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')
        ).digest()).decode('ascii')
        headers = {name.lower(): value.strip() for name, value in (
            line.split(':', 1) for line in lines[1:] if ':' in line)}
        if ' 101 ' not in lines[0] or headers.get('sec-websocket-accept') != expected:
            raise RuntimeError(f'{path}: WebSocket upgrade failed: {lines[0]}')
        first, second = read_exact(stream, 2)
        if first != 0x81 or second & 0x80:
            raise RuntimeError(f'{path}: expected an unmasked, complete text snapshot')
        size = second & 0x7f
        if size == 126:
            size = struct.unpack('!H', read_exact(stream, 2))[0]
        elif size == 127:
            size = struct.unpack('!Q', read_exact(stream, 8))[0]
        if size > 1024 * 1024:
            raise RuntimeError('WebSocket snapshot exceeds 1 MiB')
        return json.loads(read_exact(stream, size))


def main():
    """Run only with explicit localhost discovery on the isolated test domain."""
    if (os.environ.get('ROS_DOMAIN_ID') != '77'
            or os.environ.get('ROS_LOCALHOST_ONLY') != '1'
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        raise RuntimeError('smoke requires domain 77 and localhost-only discovery')
    root = Path('/opt/cobot_ws/src')
    port = 8080
    processes, logs = [], []
    with tempfile.TemporaryDirectory(prefix='cobot-smoke-') as scratch:
        profiles = Path(scratch) / 'profiles'
        plan, config_dir, robots = build_plan(
            root, get_package_share_directory('cobot_control_center'), profiles, port=port)
        export_profiles(config_dir, 'lab', robots, profiles)
        plan[0] = ('fleet', [
            'ros2', 'run', 'cobot_fleet_control', 'fleet_control_node', '--ros-args',
            '--params-file', str(root / 'cobot_fleet_control/config/fleet_control.yaml'),
            '-p', f'db_path:={scratch}/fleet.sqlite3',
            '-p', f'patrol_config_dir:={config_dir}',
        ])
        try:
            for name, command in plan:
                log = (Path(scratch) / f'{name}.log').open('w+')
                logs.append(log)
                processes.append(subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
            base = f'http://127.0.0.1:{port}'
            deadline, health = time.monotonic() + 30, None
            while time.monotonic() < deadline:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError('A smoke-check service exited early')
                try:
                    with urlopen(base + '/api/health', timeout=1) as response:
                        health = json.load(response)
                    if health.get('controller_online') and health.get('source_online'):
                        break
                except OSError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError(f'Services did not become ready: {health}')
            if health.get('commands_armed') is not False or health.get('domain_id') != 77:
                raise RuntimeError(f'Unexpected startup state: {health}')
            checks = {}
            for path in ('/', '/api/map/info', '/api/map/layers', '/api/tasks'):
                with urlopen(base + path, timeout=3) as response:
                    checks[path] = response.status
            fleet = websocket_snapshot(port, '/ws/fleet')
            tasks = websocket_snapshot(port, '/ws/tasks')
            if not fleet or tasks.get('type') != 'tasks':
                raise RuntimeError('Missing initial fleet or tasks WebSocket snapshot')
            result = {'health': health, 'http': checks,
                      'websocket': {'/ws/fleet': 101, '/ws/tasks': 101}}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception:
            for log in logs:
                log.flush()
                log.seek(0)
                print(f'--- {Path(log.name).name} ---\n{log.read()[-8000:]}', flush=True)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            for log in logs:
                log.close()


if __name__ == '__main__':
    main()
