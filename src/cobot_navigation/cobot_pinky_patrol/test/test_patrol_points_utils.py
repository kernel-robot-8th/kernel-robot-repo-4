"""patrol_points_utils 단위 테스트 (ROS 불필요)."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_pinky_patrol.patrol_points_utils import (  # noqa: E402,I100,I101
    REQUIRED_POINTS, PointsConfigError, exit_name, general_names, optional_general_names,
    parse_point, parse_points,
    parse_zone_names, parse_zone_points, required_names, validate_points, validate_zones, zone_of)

ZONES = ('A', 'B')


def _full():
    names = list(required_names(ZONES)) + ['I1', 'ZA', 'ZB', 'ZC', 'ZD']   # 홈과 구역 지점은 YAML 이 이름을 정한다
    return {n: (0.0, 0.0) for n in names}


def test_parse_point_two_and_three_values():
    """[x, y] 와 [x, y, yaw] 모두 튜플로 변환한다."""
    assert parse_point('P1', [0.5, -1]) == (0.5, -1.0)
    assert parse_point('ZONE_EXIT', [0.5, -0.4, 3.14]) == (0.5, -0.4, 3.14)


@pytest.mark.parametrize('value', [[], [1.0], [1.0, 2.0, 3.0, 4.0]])
def test_parse_point_wrong_length(value):
    """길이가 2·3 이 아니면 키 이름과 함께 거부한다."""
    with pytest.raises(PointsConfigError, match='points.P1'):
        parse_point('P1', value)


@pytest.mark.parametrize('value', ['1.0, 2.0', 5, None])
def test_parse_point_not_a_list(value):
    """리스트가 아니면(문자열 포함) 거부한다."""
    with pytest.raises(PointsConfigError, match='리스트'):
        parse_point('P1', value)


@pytest.mark.parametrize('value', [['a', 1.0], [1.0, None], [True, 0.0]])
def test_parse_point_not_a_number(value):
    """숫자가 아닌 값(문자열, None, bool)은 거부한다."""
    with pytest.raises(PointsConfigError, match='숫자'):
        parse_point('P1', value)


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_parse_point_not_finite(bad):
    """NaN/inf 는 거부한다."""
    with pytest.raises(PointsConfigError, match='NaN/inf'):
        parse_point('P1', [0.0, bad])


def test_parse_points_converts_all():
    """딕셔너리 전체를 튜플로 변환한다."""
    assert parse_points({'A': [1, 2], 'B': (3.0, 4.0, 0.5)}) == {'A': (1.0, 2.0), 'B': (3.0, 4.0, 0.5)}


def test_validate_ok():
    """필수 지점과 홈이 모두 있으면 통과한다."""
    validate_points(_full(), required_names(ZONES), 'I1')


def test_validate_reports_all_missing_names_at_once():
    """누락된 지점 이름을 한 번에 모두 알려 준다."""
    pts = _full()
    del pts['ZB_EXIT'], pts['P2']
    with pytest.raises(PointsConfigError) as e:
        validate_points(pts, required_names(ZONES), 'P1')
    assert 'ZB_EXIT' in str(e.value) and 'P2' in str(e.value)


@pytest.mark.parametrize('home', ['', None, 'P99'])
def test_validate_home_missing_or_unknown(home):
    """home_name 이 비었거나 points 에 없으면 거부한다."""
    with pytest.raises(PointsConfigError, match='home_name'):
        validate_points(_full(), required_names(ZONES), home)


# ---------------- 위험구역 ----------------
def test_entry_exit_names_and_required_names():
    """구역별 ENTRY/EXIT 이름 규칙과 필수 이름 목록."""
    assert exit_name('A') == 'ZA_EXIT' and exit_name('B') == 'ZB_EXIT'
    names = required_names(('A', 'B'))
    assert set(REQUIRED_POINTS) <= set(names)
    assert {'ZA_EXIT', 'ZB_EXIT'} <= set(names)
    assert required_names(()) == list(REQUIRED_POINTS)


@pytest.mark.parametrize('bad', [[], None, 'A', ['A', 'A'], ['A:1'], [''], ['A B'], [1]])
def test_parse_zone_names_rejects(bad):
    """구역 이름은 비어 있지 않은 영문·숫자 목록이어야 하고 중복·':'·공백을 허용하지 않는다."""
    with pytest.raises(PointsConfigError, match='zone_names'):
        parse_zone_names(bad)


def test_parse_zone_names_ok():
    """정상 구역 이름은 튜플로 돌려준다."""
    assert parse_zone_names(['A', 'B']) == ('A', 'B')


def test_parse_zone_points():
    """구역별 지점 이름을 튜플로 바꾸고 리스트가 아니거나 문자열이 아닌 값은 거부한다."""
    assert parse_zone_points({'A': ['ZA', 'ZB'], 'B': ['ZC']}) == {'A': ('ZA', 'ZB'), 'B': ('ZC',)}
    with pytest.raises(PointsConfigError, match='zone_points.A'):
        parse_zone_points({'A': 'ZA'})
    with pytest.raises(PointsConfigError, match='zone_points.A'):
        parse_zone_points({'A': [3]})


def test_validate_zones_ok_and_zone_of():
    """정상 구역 설정은 통과하고 zone_of 가 소속 구역(구역 밖은 None)을 돌려준다."""
    zp = {'A': ('ZA', 'ZB'), 'B': ('ZC', 'ZD')}
    validate_zones(zp, _full(), 'I1')
    assert zone_of(zp, 'ZB') == 'A' and zone_of(zp, 'ZD') == 'B'
    assert zone_of(zp, 'P1') is None


def test_validate_zones_reports_every_problem():
    """소속 지점 없음·points 에 없는 지점·중복 소속·홈이 구역 안을 한꺼번에 알려 준다."""
    zp = {'A': ('ZA', 'P99'), 'B': ('ZA',), 'C': ()}
    with pytest.raises(PointsConfigError) as e:
        validate_zones(zp, _full(), 'ZA')
    msg = str(e.value)
    assert 'P99' in msg and '동시에 속' in msg and 'zone_points.C' in msg and 'home_name' in msg


def test_validate_zones_exit_cannot_be_zone_members():
    """출구(Z_EXIT) 지점은 구역 소속 지점으로 쓸 수 없다."""
    with pytest.raises(PointsConfigError, match='출구'):
        validate_zones({'A': ('ZA_EXIT',)}, _full(), 'I1')


def test_general_names():
    """일반 지점은 P1~P10 만, 번호순으로 돌려준다 (P11·구역·홈 이름은 제외)."""
    assert optional_general_names() == ['P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9', 'P10']
    pts = {'P10': 1, 'P2': 1, 'P1': 1, 'P11': 1, 'P0': 1, 'ZA': 1, 'I1': 1, 'ZA_EXIT': 1}
    assert general_names(pts) == ['P1', 'P2', 'P10']
