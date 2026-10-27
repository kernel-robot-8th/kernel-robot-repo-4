"""parse_command 단위 테스트 (ROS 불필요)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_pinky_patrol.patrol_points_utils import parse_command  # noqa: E402,I100,I101


def test_goto_single_and_multiple():
    """명령 goto 는 지점 이름을 순서대로 대문자 튜플로 돌려준다."""
    assert parse_command('goto:P1') == ('goto', ('P1',))
    assert parse_command('goto:P1,I2') == ('goto', ('P1', 'I2'))


def test_goto_accepts_commas_spaces_and_case():
    """쉼표/공백 혼합, 소문자 명령어·지점 모두 허용."""
    assert parse_command('GoTo: p1, i2 ,P2') == ('goto', ('P1', 'I2', 'P2'))
    assert parse_command('  goto:p1  i2 ') == ('goto', ('P1', 'I2'))


def test_zone_command():
    """명령 zone 은 kind 만 다르고 같은 방식으로 지점을 해석한다."""
    assert parse_command('zone:ZA') == ('zone', ('ZA',))
    assert parse_command('ZONE: za') == ('zone', ('ZA',))


def test_zone_with_many_points_is_returned_as_is():
    """1개 제한은 노드가 검사하므로 여기서는 그대로 돌려준다."""
    assert parse_command('zone:ZA,ZB') == ('zone', ('ZA', 'ZB'))


@pytest.mark.parametrize('raw, kind', [
    ('leave', 'leave'),
    ('stop', 'stop'),
    ('emergency_stop', 'emergency_stop'),
    ('start', 'start'),
    ('  STOP  ', 'stop'),
    ('Emergency_Stop', 'emergency_stop'),
])
def test_no_argument_commands(raw, kind):
    """인자 없는 명령은 대소문자·공백과 무관하게 인식하고 points 는 비어 있다."""
    assert parse_command(raw) == (kind, ())


def test_empty_arguments_are_kept_for_node_to_reject():
    """`goto:` / `zone:` 뒤가 비어도 kind 는 유지된다 (FAILED 응답은 노드 몫)."""
    assert parse_command('goto:') == ('goto', ())
    assert parse_command('zone:  , ') == ('zone', ())


@pytest.mark.parametrize('raw', [
    '', '   ', 'dance', 'go:P1', 'leave:P1', 'stop:now', 'gotoP1', 'goto P1', None, 123,
])
def test_unknown_commands(raw):
    """알 수 없는 명령·형식 오류·문자열이 아닌 값은 unknown."""
    assert parse_command(raw) == ('unknown', ())
