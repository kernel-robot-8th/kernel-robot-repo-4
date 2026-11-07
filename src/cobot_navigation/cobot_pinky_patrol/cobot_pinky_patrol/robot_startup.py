"""로봇에서 bringup·Nav2·패트롤을 순차 기동하고 시작한 프로세스를 관리한다."""

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import yaml


READY_PREFIX = 'COBOT_ROBOT_READY '


def startup_commands(robot_id, map_path, site='lab'):
    """장비에서 실제 사용하는 launch 명령을 구성한다."""
    return [
        ['ros2', 'launch', 'pinky_bringup', 'bringup_robot.launch.xml'],
        ['ros2', 'launch', 'pinky_navigation', 'bringup_launch.xml', f'map:={map_path}'],
        ['ros2', 'launch', 'cobot_pinky_patrol', 'patrol.launch.xml',
         f'robot_id:={robot_id}', f'site:={site}'],
    ]


def readiness_checks(robot_id, topics):
    """프로세스 시작과 ROS 준비 완료를 구분할 검사 목록을 만든다."""
    return [
        [(['ros2', 'topic', 'echo', '--once', topic], None) for topic in topics],
        [(['ros2', 'lifecycle', 'get', node], r'(?m)^active \[3\]\s*$')
         for node in ('/amcl', '/bt_navigator')]
        + [(['ros2', 'action', 'info', '/navigate_to_pose', '--count'],
            r'Action servers:\s*[1-9][0-9]*')],
        [(['ros2', 'param', 'get', '/pinky_patrol_node', 'robot_id', '--hide-type'],
          r'(?m)^' + re.escape(robot_id) + r'\s*$')],
    ]


def validate_files(workspace, map_path):
    """로봇의 HOME에서 지도를 해석하고 이미지·워크스페이스를 기동 전에 확인한다."""
    workspace, map_path = Path(workspace).expanduser(), Path(map_path).expanduser()
    setup = workspace / 'install/setup.bash'
    if not setup.is_file():
        raise ValueError(f'워크스페이스 setup이 없습니다: {setup}')
    if not map_path.is_file():
        raise ValueError(f'지도 YAML이 없습니다: {map_path}')
    map_path = map_path.resolve()
    document = yaml.safe_load(map_path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or not isinstance(document.get('image'), str):
        raise ValueError(f'지도 YAML의 image가 올바르지 않습니다: {map_path}')
    image_path = Path(document['image'])
    if not image_path.is_absolute():
        image_path = map_path.parent / image_path
    if not image_path.is_file():
        raise ValueError(f'지도 이미지가 없습니다: {image_path}')
    return workspace, map_path


def validate_ros_packages():
    """별도 vendor workspace가 필요한지 실제 프로세스 기동 전에 확인한다."""
    for package in ('pinky_bringup', 'pinky_navigation', 'cobot_pinky_patrol'):
        try:
            result = subprocess.run(
                ['ros2', 'pkg', 'prefix', package], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10, check=False)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f'ROS 패키지 조회 시간 초과: {package}') from error
        if result.returncode:
            raise ValueError(f'{package}를 찾을 수 없습니다. underlay_setups 설정을 확인하세요')


@contextmanager
def startup_lock(robot_id):
    """같은 로봇의 통합 기동기가 중복 실행되지 않게 한다."""
    import fcntl

    directory = Path.home() / '.cache/cobot'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'robot-startup-{robot_id}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('이미 이 로봇의 통합 기동기가 실행 중입니다') from error
        yield


class RobotStartup:
    """각 단계의 준비·시간 제한·종료를 담당하는 로봇 로컬 감독기."""

    def __init__(self, delay=5.0, timeout=90.0, probe_timeout=5.0):
        """단계 간격·시간 제한과 소유 프로세스 목록을 초기화한다."""
        self.delay, self.timeout, self.probe_timeout = delay, timeout, probe_timeout
        self.processes = []

    def check_alive(self):
        """먼저 기동한 단계가 종료되면 이후 기동을 중단한다."""
        for label, process in self.processes:
            if process.poll() is not None:
                raise RuntimeError(f'{label} 프로세스 종료: {process.returncode}')

    def probe(self, command, pattern, timeout):
        """CLI 한 건을 제한 시간 안에서 조회한다. 토픽 본문은 보관하지 않는다."""
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE if pattern else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0 and (
            pattern is None or re.search(pattern, result.stdout) is not None)

    def wait_ready(self, checks):
        """최소 간격을 둔 뒤 준비 검사를 통과한 단계만 다음으로 진행한다."""
        start = time.monotonic()
        pending = list(checks)
        while time.monotonic() - start < self.timeout:
            self.check_alive()
            if time.monotonic() - start < self.delay:
                time.sleep(0.1)
                continue
            if not pending:
                return
            command, pattern = pending[0]
            remaining = self.timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            if self.probe(command, pattern, min(self.probe_timeout, remaining)):
                pending.pop(0)
            else:
                time.sleep(0.2)
        raise TimeoutError(f'준비 시간 초과: {pending[0][0] if pending else "최소 간격"}')

    def run(self, robot_id, commands, checks):
        """준비 완료 표시 이후에도 프로세스를 감독하며 SSH 세션 수명을 유지한다."""
        try:
            for label, command, stage_checks in zip(
                    ('bringup', 'nav2', 'patrol'), commands, checks):
                print(f'[{robot_id}] {label} 시작', flush=True)
                process = subprocess.Popen(command, start_new_session=True)
                self.processes.append((label, process))
                self.wait_ready(stage_checks)
                print(f'[{robot_id}] {label} 준비 검사 통과', flush=True)
            self.check_alive()
            print(READY_PREFIX + json.dumps({'robot_id': robot_id}), flush=True)
            while True:
                self.check_alive()
                time.sleep(0.2)
        finally:
            self.close()

    def close(self):
        """이 기동기가 만든 프로세스 그룹만 역순으로 종료한다."""
        for _, process in reversed(self.processes):
            if process.poll() is not None:
                # launch 부모가 이미 종료된 경우에도 남은 자식 그룹을 정리한다.
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                continue
            for sig, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 3), (signal.SIGKILL, 1)):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    process.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue


def main(args=None):
    """관제 SSH 또는 로봇 터미널에서 실행하는 진입점."""
    parser = argparse.ArgumentParser(description='Pinky bringup → Nav2 → patrol 순차 기동')
    parser.add_argument('--robot-id', required=True)
    parser.add_argument('--domain-id', required=True, type=int)
    parser.add_argument('--workspace', default='/ws/kernel-robot-repo-4')
    parser.add_argument('--map', default='~/cobot_map_v9.yaml')
    parser.add_argument('--site', default='lab')
    parser.add_argument('--stage-delay', type=float, default=5.0)
    parser.add_argument('--stage-timeout', type=float, default=90.0)
    parser.add_argument('--topic', action='append', help='bringup 준비 확인 토픽; 반복 지정')
    options = parser.parse_args(args)
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', options.robot_id):
        parser.error('robot-id 형식 오류')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', options.site):
        parser.error('site 형식 오류')
    if not 0 <= options.domain_id <= 232:
        parser.error('domain-id 범위: 0~232')
    if (not math.isfinite(options.stage_delay) or options.stage_delay < 0
            or not math.isfinite(options.stage_timeout)
            or options.stage_timeout <= options.stage_delay):
        parser.error('stage-timeout은 유한한 양수이며 stage-delay보다 커야 합니다')
    if options.topic and any(not re.fullmatch(r'/[A-Za-z0-9_/]+', t) for t in options.topic):
        parser.error('topic은 절대 ROS 토픽 이름이어야 합니다')
    try:
        workspace, map_path = validate_files(options.workspace, options.map)
        validate_ros_packages()
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    os.environ['ROS_DOMAIN_ID'] = str(options.domain_id)
    os.environ['PYTHONUNBUFFERED'] = '1'
    os.chdir(workspace)

    def stop(signum, frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        with startup_lock(options.robot_id):
            RobotStartup(options.stage_delay, options.stage_timeout).run(
                options.robot_id, startup_commands(options.robot_id, map_path, options.site),
                readiness_checks(options.robot_id, options.topic or ['/scan', '/odom', '/tf']))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f'로봇 기동 실패: {error}\n')


if __name__ == '__main__':
    main()
