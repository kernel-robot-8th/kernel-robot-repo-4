"""관제에서 SSH 세션과 로컬 관제 서비스를 묶는 순차 기동기."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import subprocess
import time

import yaml


READY_PREFIX = 'COBOT_ROBOT_READY '
CONTROL_COMMANDS = {
    'bridge': ['ros2', 'launch', 'cobot_domain_bridge', 'bridges.launch.xml'],
    'zone-manager': ['ros2', 'launch', 'cobot_zone_traffic_control', 'zone_manager.launch.xml'],
    'fleet': ['ros2', 'launch', 'cobot_fleet_control', 'fleet_control.launch.xml'],
}
DEFAULTS = {
    'workspace': '/ws/kernel-robot-repo-4', 'ros_setup': '/opt/ros/jazzy/setup.bash',
    'map': '~/cobot_map_v9.yaml', 'site': 'lab', 'underlay_setups': [],
    'stage_delay_sec': 5.0, 'stage_timeout_sec': 90.0,
    'readiness_topics': ['/scan', '/odom', '/tf'], 'environment': {}, 'ssh_port': 22,
}


@dataclass
class RobotConfig:
    """한 로봇의 SSH 접속과 원격 기동 파라미터."""

    robot_id: str
    host: str
    user: str
    domain_id: int
    settings: dict

    def remote_command(self):
        """원격 셸에서 setup을 읽고 로봇 HOME을 쓰는 기동기를 실행한다."""
        cfg = self.settings
        sources = [cfg['ros_setup'], *cfg['underlay_setups'],
                   cfg['workspace'].rstrip('/') + '/install/setup.bash']
        commands = ['set -e', *['source ' + shlex.quote(path) for path in sources]]
        environment = dict(cfg['environment'], ROS_DOMAIN_ID=str(self.domain_id),
                           PYTHONUNBUFFERED='1')
        commands.extend('export ' + name + '=' + shlex.quote(value)
                        for name, value in environment.items())
        commands.append('cd -- ' + shlex.quote(cfg['workspace']))
        argv = ['ros2', 'run', 'cobot_pinky_patrol', 'robot_startup',
                '--robot-id', self.robot_id, '--domain-id', str(self.domain_id),
                '--workspace', cfg['workspace'], '--map', cfg['map'], '--site', cfg['site'],
                '--stage-delay', str(cfg['stage_delay_sec']),
                '--stage-timeout', str(cfg['stage_timeout_sec'])]
        for topic in cfg['readiness_topics']:
            argv += ['--topic', topic]
        commands.append('exec ' + shlex.join(argv))
        return shlex.join(['bash', '-c', '\n'.join(commands)])

    def ssh_command(self):
        """비대화식 SSH와 TTY를 사용해 계정·호스트 키 확인 및 세션 종료를 명확히 한다."""
        return ['ssh', '-tt', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5',
                '-o', 'ServerAliveCountMax=3', '-p', str(self.settings['ssh_port']),
                f'{self.user or "SSH_USER"}@{self.host}', self.remote_command()]


def _number(value, name, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum):
        raise ValueError(f'{name}은 {minimum} 이상의 유한한 숫자여야 합니다')


def load_config(path, selected=()):
    """실행 전 전체 설정을 검사한다. SSH 계정 공란은 미리보기에서만 허용한다."""
    document = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict) or set(document) - {'defaults', 'robots', 'robot_delay_sec'}:
        raise ValueError('기동 설정의 최상위 키는 defaults, robots, robot_delay_sec입니다')
    defaults, raw_robots = document.get('defaults', {}), document.get('robots')
    if not isinstance(defaults, dict) or set(defaults) - set(DEFAULTS):
        raise ValueError('알 수 없는 defaults 설정')
    if not isinstance(raw_robots, dict) or not raw_robots:
        raise ValueError('robots 설정이 필요합니다')
    robot_delay = document.get('robot_delay_sec', 3.0)
    _number(robot_delay, 'robot_delay_sec')
    if set(selected) - set(raw_robots):
        raise ValueError(f'등록되지 않은 로봇: {set(selected) - set(raw_robots)}')
    robots = []
    for robot_id, raw in raw_robots.items():
        if selected and robot_id not in selected:
            continue
        if (not isinstance(robot_id, str)
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', robot_id)
                or not isinstance(raw, dict)
                or set(raw) - (set(DEFAULTS) | {'host', 'ssh_user', 'domain_id'})):
            raise ValueError('로봇 설정 또는 robot_id 형식 오류')
        host, user, domain = raw.get('host'), raw.get('ssh_user', ''), raw.get('domain_id')
        if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host):
            raise ValueError(f'{robot_id}: SSH host 형식 오류')
        if not isinstance(user, str) or (user and not re.fullmatch(r'[A-Za-z_][\w.-]*', user)):
            raise ValueError(f'{robot_id}: SSH 계정 형식 오류')
        if isinstance(domain, bool) or not isinstance(domain, int) or not 0 <= domain <= 232:
            raise ValueError(f'{robot_id}: domain_id 범위는 0~232입니다')
        cfg = dict(DEFAULTS, **defaults)
        cfg.update({name: value for name, value in raw.items() if name in DEFAULTS})
        for name in ('workspace', 'ros_setup'):
            if not isinstance(cfg[name], str) or not cfg[name].startswith('/'):
                raise ValueError(f'{robot_id}: {name}은 로봇의 절대 경로여야 합니다')
        if not isinstance(cfg['map'], str) or not cfg['map'].startswith(('/', '~/')):
            raise ValueError('map은 로봇의 절대 경로 또는 ~/ 경로여야 합니다')
        if not isinstance(cfg['site'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', cfg['site']):
            raise ValueError('site 형식 오류')
        underlays, topics, environment = (
            cfg['underlay_setups'], cfg['readiness_topics'], cfg['environment'])
        if not isinstance(underlays, list) or any(
                not isinstance(p, str) or not p.startswith('/') for p in underlays):
            raise ValueError('underlay_setups는 로봇의 절대 setup 경로 목록이어야 합니다')
        if not isinstance(topics, list) or not topics or any(
                not isinstance(t, str) or not re.fullmatch(r'/[A-Za-z0-9_/]+', t) for t in topics):
            raise ValueError('readiness_topics는 비어 있지 않은 ROS 토픽 목록이어야 합니다')
        allowed_env = {'RMW_IMPLEMENTATION', 'CYCLONEDDS_URI', 'ROS_AUTOMATIC_DISCOVERY_RANGE',
                       'ROS_LOCALHOST_ONLY'}
        if (not isinstance(environment, dict) or set(environment) - allowed_env
                or any(not isinstance(v, str) for v in environment.values())):
            raise ValueError('environment에는 문자열 DDS 설정만 지정할 수 있습니다')
        port = cfg['ssh_port']
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('ssh_port 범위: 1~65535')
        _number(cfg['stage_delay_sec'], 'stage_delay_sec')
        _number(cfg['stage_timeout_sec'], 'stage_timeout_sec', minimum=1)
        if cfg['stage_timeout_sec'] <= cfg['stage_delay_sec']:
            raise ValueError('stage_timeout_sec은 stage_delay_sec보다 커야 합니다')
        robots.append(RobotConfig(robot_id, host, user, domain, cfg))
    if len({r.host for r in robots}) != len(robots):
        raise ValueError('같은 호스트를 여러 로봇으로 중복 기동할 수 없습니다')
    if len({r.domain_id for r in robots}) != len(robots):
        raise ValueError('각 로봇의 domain_id가 달라야 합니다')
    return robots, robot_delay


@contextmanager
def startup_lock():
    """이 관제 계정에서 통합 기동기를 중복 실행하지 않는다."""
    import fcntl

    directory = Path.home() / '.cache/cobot'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'fleet-startup.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('이미 통합 기동기가 실행 중입니다') from error
        yield


class FleetStartup:
    """SSH 로그를 전달하고 로봇 준비를 확인한 뒤 다음 로봇을 기동한다."""

    def __init__(self):
        """기동 프로세스와 비동기 로그·준비 상태 수집기를 초기화한다."""
        self.processes = []
        self.selector = selectors.DefaultSelector()
        self.buffers = {}
        self.ready = set()

    def start(self, name, command, environment=None):
        """이 기동기가 소유한 프로세스만 새 세션으로 시작한다."""
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True, env=environment)
        self.processes.append((name, process))
        self.buffers[name] = b''
        self.selector.register(process.stdout, selectors.EVENT_READ, name)

    def pump(self, timeout=0.2):
        """부분 로그도 블로킹 없이 읽고 연결된 로봇의 준비 마커만 인정한다."""
        for key, _ in self.selector.select(timeout):
            name = key.data
            chunk = os.read(key.fd, 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            lines = (self.buffers[name] + chunk).split(b'\n')
            self.buffers[name] = lines.pop()
            if len(self.buffers[name]) > 65536:
                lines.append(self.buffers[name])
                self.buffers[name] = b''
            for raw in lines:
                line = raw.decode('utf-8', errors='replace').strip()
                print(f'[{name}] {line}', flush=True)
                if line.startswith(READY_PREFIX):
                    try:
                        if json.loads(line[len(READY_PREFIX):]).get('robot_id') == name:
                            self.ready.add(name)
                    except (ValueError, AttributeError):
                        pass
        for name, process in self.processes:
            if process.poll() is not None:
                raise RuntimeError(f'{name} 프로세스/SSH 연결 종료: {process.returncode}')

    def wait(self, seconds, robot_id=None):
        """기동·대기 중에도 기존 로봇의 연결과 프로세스 종료를 감시한다."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pump()
            if robot_id in self.ready:
                return
        if robot_id:
            raise TimeoutError(f'{robot_id} 준비 시간 초과')

    def run(self, robots, delay, local_services=True):
        """브릿지·매니저 → 로봇 순차 준비 → 업무 관제 서버 순서로 실행한다."""
        environment = dict(os.environ, ROS_DOMAIN_ID='100')
        try:
            if local_services:
                for name in ('bridge', 'zone-manager'):
                    self.start(name, CONTROL_COMMANDS[name], environment)
            for index, robot in enumerate(robots):
                if index:
                    self.wait(delay)
                self.start(robot.robot_id, robot.ssh_command())
                self.wait(3 * robot.settings['stage_timeout_sec'] + 30, robot.robot_id)
            if local_services:
                self.start('fleet', CONTROL_COMMANDS['fleet'], environment)
            print('전체 로봇 기동 검사 완료. SSH 세션을 유지합니다.', flush=True)
            while True:
                self.pump()
        finally:
            self.close()

    def close(self):
        """업무 관제·원격 세션·로컬 서비스를 역순 종료한다."""
        self.selector.close()
        for _, process in reversed(self.processes):
            for sig, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 3), (signal.SIGKILL, 1)):
                if process.poll() is not None:
                    break
                try:
                    os.killpg(process.pid, sig)
                    process.wait(timeout=grace)
                    break
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.stdout:
                process.stdout.close()


def main(args=None):
    """기본은 명령 미리보기. --execute를 지정해야 SSH와 ROS 프로세스를 실행한다."""
    parser = argparse.ArgumentParser(description='관제·로봇 순차 기동')
    parser.add_argument('--config', required=True)
    parser.add_argument('--robot', action='append', default=[])
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--robots-only', action='store_true')
    options = parser.parse_args(args)
    try:
        robots, delay = load_config(options.config, options.robot)
        if options.execute:
            missing = [r.robot_id for r in robots if not r.user]
            if missing:
                raise ValueError(f'SSH 계정을 먼저 지정하세요: {missing}')
            if os.name != 'posix':
                raise ValueError('실제 기동은 Linux 관제 환경에서 실행하세요')
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    if not options.execute:
        if not options.robots_only:
            print('관제: 브릿지·zone_manager → 모든 로봇 준비 후 fleet_control')
        for robot in robots:
            print(f'\n{robot.robot_id}: {robot.host}, domain={robot.domain_id}')
            print(shlex.join(robot.ssh_command()))
        print(f'\n로봇 간 추가 간격: {delay:g}초. 미리보기 완료; 실제 접속하지 않았습니다.')
        return

    def stop(signum, frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        with startup_lock():
            FleetStartup().run(robots, delay, not options.robots_only)
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f'통합 기동 실패: {error}\n')


if __name__ == '__main__':
    main()
