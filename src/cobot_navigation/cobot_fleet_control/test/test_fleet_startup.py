"""SSH·ROS 접속 없이 원격 명령·미리보기·순차 기동 수명을 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
import shlex
import subprocess
import sys

from cobot_fleet_control import fleet_startup as module
import pytest
import yaml


CONFIG = Path(__file__).resolve().parents[1] / 'config/fleet_startup.yaml'


def write_config(tmp_path, change):
    """한 검증 항목만 바꾼 기동 설정을 만든다."""
    document = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    change(document)
    path = tmp_path / 'startup.yaml'
    path.write_text(yaml.safe_dump(document))
    return path


def test_supplied_ips_domains_workspace_and_remote_home():
    """사용자가 제공한 주소·워크스페이스와 기존 도메인을 보존한다."""
    robots, delay = module.load_config(CONFIG)
    assert [(r.robot_id, r.host, r.domain_id) for r in robots] == [
        ('pinky1', '192.168.45.21', 10), ('pinky2', '192.168.45.22', 20),
        ('pinky3', '192.168.45.23', 30)]
    assert delay == 3
    assert all(r.settings['workspace'] == '/ws/kernel-robot-repo-4' for r in robots)
    assert all(r.settings['map'] == '~/cobot_map_v9.yaml' for r in robots)
    assert all(not r.user for r in robots)


def test_preview_never_starts_ssh_or_local_services(monkeypatch, capsys):
    """기본 실행은 실제 프로세스를 하나도 시작하지 않는다."""
    def forbidden(*args, **kwargs):
        pytest.fail('preview started a process')

    monkeypatch.setattr(module.subprocess, 'Popen', forbidden)
    module.main(['--config', str(CONFIG)])
    output = capsys.readouterr().out
    assert '192.168.45.21' in output and '192.168.45.23' in output
    assert '/ws/kernel-robot-repo-4/install/setup.bash' in output
    assert '~/cobot_map_v9.yaml' in output


def test_missing_ssh_user_blocks_before_any_process(monkeypatch):
    """계정 정보가 없으면 --execute도 접속·로컬 서비스 기동 전에 실패한다."""
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: pytest.fail('started'))
    with pytest.raises(SystemExit) as error:
        module.main(['--config', str(CONFIG), '--execute'])
    assert error.value.code == 2


@pytest.mark.parametrize('change', [
    lambda d: d['robots']['pinky1'].update(host='-oProxyCommand=bad'),
    lambda d: d['robots']['pinky1'].update(ssh_user='user;bad'),
    lambda d: d['robots']['pinky1'].update(domain_id=True),
    lambda d: d['robots']['pinky1'].update(domain_id=20),
    lambda d: d['robots']['pinky1'].update(host='192.168.45.22'),
    lambda d: d['defaults'].update(stage_delay_sec=float('nan')),
    lambda d: d['defaults'].update(stage_timeout_sec=1, stage_delay_sec=2),
    lambda d: d['defaults'].update(workspace='relative'),
    lambda d: d['defaults'].update(readiness_topics=[]),
    lambda d: d['defaults'].update(underlay_setups=['~/vendor/install/setup.bash']),
    lambda d: d['defaults'].update(environment={'HOME': '/wrong-home'}),
    lambda d: d['defaults'].update(ssh_port=0),
])
def test_invalid_settings_are_rejected(tmp_path, change):
    """접속 주소·환경·대기 조건의 입력 오류를 실행 전에 검출한다."""
    with pytest.raises(ValueError):
        module.load_config(write_config(tmp_path, change))


def test_remote_shell_quotes_paths_and_does_not_expand_map_locally(tmp_path):
    """로봇 쪽 셸의 인자를 확인하며 문자열이 셸 명령으로 실행되지 않게 한다."""
    robots, _ = module.load_config(CONFIG, ['pinky1'])
    robot = robots[0]
    settings = deepcopy(robot.settings)
    workspace = tmp_path / "workspace ' with spaces"
    (workspace / 'install').mkdir(parents=True)
    (workspace / 'install/setup.bash').write_text('')
    ros_setup = tmp_path / 'ros setup.bash'
    ros_setup.write_text('')
    binary = tmp_path / 'bin'
    binary.mkdir()
    executable = binary / 'ros2'
    executable.write_text('#!/usr/bin/python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
    executable.chmod(0o755)
    marker = tmp_path / 'must-not-exist'
    map_argument = f'~/cobot_map_v9.yaml; touch {marker}'
    settings.update(workspace=str(workspace), ros_setup=str(ros_setup), map=map_argument)
    robot.settings = settings
    argv = shlex.split(robot.remote_command())
    result = subprocess.run(argv, env={'PATH': str(binary) + ':/usr/bin:/bin'},
                            capture_output=True, text=True, check=True)
    remote_argv = json.loads(result.stdout)
    assert remote_argv[remote_argv.index('--map') + 1] == map_argument
    assert not marker.exists()


def test_start_order_waits_for_each_robot_before_fleet(monkeypatch):
    """로봇별 준비를 확인한 뒤 다음 로봇과 최종 업무 서버를 실행한다."""
    robots, delay = module.load_config(CONFIG)
    runner, events = module.FleetStartup(), []
    monkeypatch.setattr(runner, 'start', lambda name, *args: events.append(('start', name)))
    monkeypatch.setattr(runner, 'wait', lambda seconds, robot_id=None:
                        events.append(('ready' if robot_id else 'delay', robot_id)))
    monkeypatch.setattr(runner, 'close', lambda: runner.selector.close())

    def finish():
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, 'pump', finish)
    with pytest.raises(KeyboardInterrupt):
        runner.run(robots, delay)
    assert events == [
        ('start', 'bridge'), ('start', 'zone-manager'),
        ('start', 'pinky1'), ('ready', 'pinky1'), ('delay', None),
        ('start', 'pinky2'), ('ready', 'pinky2'), ('delay', None),
        ('start', 'pinky3'), ('ready', 'pinky3'), ('start', 'fleet')]


@pytest.mark.parametrize('reported_id', ['pinky1', 'pinky2'])
def test_streamed_readiness_and_cleanup_without_ssh(reported_id):
    """로컬 가짜 프로세스로 마커 상관관계와 소유 프로세스 종료를 검증한다."""
    runner = module.FleetStartup()
    marker = module.READY_PREFIX + json.dumps({'robot_id': reported_id})
    fake = ['-u', '-c', f'import time; print({marker!r}, flush=True); time.sleep(30)']
    runner.start('pinky1', [sys.executable, *fake])
    try:
        if reported_id == 'pinky1':
            runner.wait(2, 'pinky1')
        else:
            with pytest.raises(TimeoutError):
                runner.wait(0.3, 'pinky1')
    finally:
        runner.close()
    assert runner.processes[0][1].poll() is not None


def test_controller_lock_rejects_duplicate_instance(tmp_path, monkeypatch):
    """동일 관제 계정에서 두 통합 기동기가 동시에 시작되지 않게 한다."""
    pytest.importorskip('fcntl')
    monkeypatch.setenv('HOME', str(tmp_path))
    with module.startup_lock():
        with pytest.raises(RuntimeError):
            with module.startup_lock():
                pytest.fail('duplicate startup')


def test_remote_exit_fails_startup_without_reporting_ready():
    """준비 마커 전에 종료된 SSH에 해당하는 프로세스를 준비로 간주하지 않는다."""
    runner = module.FleetStartup()
    runner.start('pinky1', [sys.executable, '-c', 'raise SystemExit(7)'])
    try:
        with pytest.raises(RuntimeError, match='pinky1'):
            runner.wait(2, 'pinky1')
        assert not runner.ready
    finally:
        runner.close()
