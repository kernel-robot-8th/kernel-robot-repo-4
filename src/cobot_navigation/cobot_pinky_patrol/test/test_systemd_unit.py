"""systemd 자동 기동 파일이 robot_startup 의 인자·종료 방식과 어긋나지 않는지 검증한다."""

import configparser
from pathlib import Path
import re

from cobot_pinky_patrol import robot_startup as module
import pytest


SYSTEMD = Path(__file__).resolve().parents[1] / 'config/systemd'
# RobotStartup.close() 의 단계별 대기(SIGINT 10 + SIGTERM 3 + SIGKILL 1 초) × 3단계.
WORST_CLOSE_SEC = 3 * (10 + 3 + 1)


def load_unit():
    """대소문자를 보존해 unit 파일을 읽는다."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(SYSTEMD / 'cobot-robot.service', encoding='utf-8')
    return parser


def env_values():
    """예시 환경 파일의 변수와 값을 모은다."""
    values = {}
    for line in (SYSTEMD / 'robot.env.example').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value
    return values


def env_keys():
    """예시 환경 파일의 변수 이름을 모은다."""
    return set(env_values())


def test_sourced_paths_are_absolute():
    # bash 가 따옴표 안에서 source 하므로 ~ 는 풀리지 않는다.
    values = env_values()
    assert values['WORKSPACE'].startswith('/')
    assert all(path.startswith('/') for path in values['UNDERLAY_SETUPS'].split())


def test_restart_only_on_failure_and_stop_gives_cleanup_time():
    unit = load_unit()
    service = unit['Service']
    assert service['Restart'] == 'on-failure'
    assert service['KillMode'] == 'mixed'
    assert service['KillSignal'] == 'SIGTERM'
    assert int(service['TimeoutStopSec']) > WORST_CLOSE_SEC
    assert service['EnvironmentFile'] == '/etc/cobot/robot.env'
    assert unit['Install']['WantedBy'] == 'multi-user.target'
    assert int(unit['Unit']['StartLimitBurst']) > 0


def test_exec_start_variables_exist_in_env_example():
    command = load_unit()['Service']['ExecStart']
    used = set(re.findall(r'\$\$\{([A-Z_]+)\}', command))
    assert used == env_keys()
    # $$ 없이 쓰면 systemd 가 먼저 빈 값으로 풀어 버린다.
    assert not re.search(r'(?<!\$)\$\{', command)


def test_exec_start_arguments_match_robot_startup(capsys):
    command = load_unit()['Service']['ExecStart']
    assert 'exec ros2 run cobot_pinky_patrol robot_startup' in command
    with pytest.raises(SystemExit):
        module.main(['--help'])
    help_text = capsys.readouterr().out
    for option in re.findall(r'(--[a-z-]+) "', command):
        assert option in help_text
