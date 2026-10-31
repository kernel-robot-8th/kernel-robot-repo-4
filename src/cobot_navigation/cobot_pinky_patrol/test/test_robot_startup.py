"""실제 로봇 없이 순차 기동·준비 검사·실패 정리·지도 경로를 검증한다."""

import re
from types import SimpleNamespace

from cobot_pinky_patrol import robot_startup as module
import pytest


def map_files(tmp_path):
    """로봇 HOME과 설치된 워크스페이스의 최소 파일을 만든다."""
    workspace = tmp_path / 'ws'
    (workspace / 'install').mkdir(parents=True)
    (workspace / 'install/setup.bash').write_text('')
    (tmp_path / 'cobot_map_v9.yaml').write_text('image: cobot_map_v9.pgm\n')
    (tmp_path / 'cobot_map_v9.pgm').write_bytes(b'P5\n1 1\n255\n\x00')
    return workspace


def test_map_expands_on_robot_and_relative_image_is_checked(tmp_path, monkeypatch):
    """SSH 접속 계정의 HOME을 사용하고 지도 이미지도 확인한다."""
    workspace = map_files(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path))
    assert module.validate_files(workspace, '~/cobot_map_v9.yaml') == (
        workspace, tmp_path / 'cobot_map_v9.yaml')
    (tmp_path / 'cobot_map_v9.pgm').unlink()
    with pytest.raises(ValueError, match='이미지'):
        module.validate_files(workspace, '~/cobot_map_v9.yaml')


def test_commands_use_real_vendor_launches_and_patrol_workspace_map(tmp_path):
    """사용자가 지정한 두 launch와 지도 인자를 그대로 사용한다."""
    commands = module.startup_commands('pinky2', tmp_path / 'cobot_map_v9.yaml')
    assert commands[0] == ['ros2', 'launch', 'pinky_bringup', 'bringup_robot.launch.xml']
    assert commands[1] == ['ros2', 'launch', 'pinky_navigation', 'bringup_launch.xml',
                           f'map:={tmp_path / "cobot_map_v9.yaml"}']
    assert commands[2][-2:] == ['robot_id:=pinky2', 'site:=lab']


def test_map_symlink_uses_the_same_image_directory_as_nav2(tmp_path):
    """홈의 지도 링크도 Nav2에 전달하는 실제 YAML과 같은 기준으로 검사한다."""
    workspace = map_files(tmp_path)
    maps = tmp_path / 'maps'
    maps.mkdir()
    (maps / 'actual.yaml').write_text('image: actual.pgm\n')
    (maps / 'actual.pgm').write_bytes(b'P5\n1 1\n255\n\x00')
    link = tmp_path / 'linked.yaml'
    link.symlink_to(maps / 'actual.yaml')
    assert module.validate_files(workspace, link)[1] == maps / 'actual.yaml'


def test_readiness_distinguishes_inactive_zero_servers_and_wrong_robot():
    """프로세스가 존재해도 비활성 Nav2와 다른 로봇은 준비로 판정하지 않는다."""
    checks = module.readiness_checks('pinky2', ['/scan', '/odom', '/tf'])
    assert checks[0][0][0] == ['ros2', 'topic', 'echo', '--once', '/scan']
    assert re.search(checks[1][0][1], 'active [3]\n')
    assert not re.search(checks[1][0][1], 'inactive [2]\n')
    assert not re.search(checks[1][2][1], 'Action servers: 0\n')
    assert re.search(checks[1][2][1], 'Action servers: 1\n')
    assert not re.search(checks[2][0][1], 'pinky1\n')


@pytest.mark.parametrize('fail_stage', [None, 2])
def test_stage_order_and_failure_cleanup(monkeypatch, capsys, fail_stage):
    """준비 검사 후 다음 단계로 진행하고 실패하면 소유한 단계만 역순 정리한다."""
    started, checked, stopped = [], [], []

    class Process:
        """실제 OS 프로세스를 시작하지 않는 테스트 포트."""

        def __init__(self, command, **kwargs):
            started.append(command)
            self.pid = len(started)
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.returncode = 0

    monkeypatch.setattr(module.subprocess, 'Popen', Process)
    monkeypatch.setattr(module.os, 'killpg', lambda pid, sig: stopped.append(pid))
    runner = module.RobotStartup(delay=0)

    def wait_ready(checks):
        checked.append(len(started))
        if len(started) == fail_stage:
            raise TimeoutError('not ready')

    def finish(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, 'wait_ready', wait_ready)
    monkeypatch.setattr(module.time, 'sleep', finish)
    with pytest.raises(TimeoutError if fail_stage else KeyboardInterrupt):
        runner.run('pinky1', [['driver'], ['nav2'], ['patrol']], [[], [], []])
    count = fail_stage or 3
    assert checked == list(range(1, count + 1))
    assert stopped == list(range(count, 0, -1))
    assert (module.READY_PREFIX in capsys.readouterr().out) is (fail_stage is None)


def test_minimum_delay_and_timeout_are_bounded(monkeypatch):
    """고정 간격을 지키고 준비되지 않은 단계에서 제한 시간 후 멈춘다."""
    clock, calls = [0.0], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep',
                        lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    runner = module.RobotStartup(delay=0.3, timeout=1)
    monkeypatch.setattr(runner, 'probe', lambda *args: calls.append(clock[0]) or False)
    with pytest.raises(TimeoutError):
        runner.wait_ready([(['probe'], None)])
    assert calls and min(calls) >= 0.3
    assert clock[0] <= 1.3


def test_probe_timeout_is_not_ready(monkeypatch):
    """응답 없는 ROS CLI가 기동 전체를 영구 블로킹하지 않는다."""
    def timed_out(*args, **kwargs):
        raise module.subprocess.TimeoutExpired('probe', 1)

    monkeypatch.setattr(module.subprocess, 'run', timed_out)
    assert not module.RobotStartup().probe(['probe'], None, 1)


def test_missing_map_does_not_start_any_process(tmp_path, monkeypatch):
    """사전 검사에 실패하면 드라이버도 실행하지 않는다."""
    calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit):
        module.main(['--robot-id', 'pinky1', '--domain-id', '10',
                     '--workspace', str(tmp_path), '--map', str(tmp_path / 'missing.yaml')])
    assert calls == []


def test_missing_vendor_workspace_is_reported_before_start(monkeypatch):
    """Nav2 패키지가 없으면 준비 대기 대신 underlay 설정 오류를 알린다."""
    calls = []

    def query(command, **kwargs):
        calls.append(command[-1])
        return SimpleNamespace(returncode=int(command[-1] == 'pinky_navigation'))

    monkeypatch.setattr(module.subprocess, 'run', query)
    with pytest.raises(ValueError, match='underlay_setups'):
        module.validate_ros_packages()
    assert calls == ['pinky_bringup', 'pinky_navigation']


def test_robot_startup_lock_rejects_duplicate_instance(tmp_path, monkeypatch):
    """동일 로봇 기동기의 중복 실행을 막고 종료 후 다시 허용한다."""
    pytest.importorskip('fcntl')
    monkeypatch.setenv('HOME', str(tmp_path))
    with module.startup_lock('pinky1'):
        with pytest.raises(RuntimeError):
            with module.startup_lock('pinky1'):
                pytest.fail('duplicate startup')
    with module.startup_lock('pinky1'):
        pass
