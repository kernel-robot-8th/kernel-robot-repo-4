"""공통 실행기와 로봇별 설정의 좌표 로딩 회귀 테스트.

- YAML·좌표 로딩의 기존 회귀 검증. 비동기 정책·실제 ROS 액션은 별도 테스트에서 검증한다.
- ROS_DOMAIN_ID=77 + ROS_LOCALHOST_ONLY=1 이 아니면 통합 테스트는 건너뜀 (실제 관제 도메인 보호).
- 이 PC 에는 pinky_interfaces(로봇 전용)가 없으므로 SetLed 를 스텁으로 대체한다.
"""
import ast
import importlib
import os
import sys
import types
from pathlib import Path

import pytest
from test_patrol_config import load_parameters
import yaml

HERE = Path(__file__).resolve().parent
PKG = HERE.parent                                   # cobot_pinky_patrol/
ZONE_PKG = PKG.parent / 'cobot_zone_traffic_control'  # cobot_zone_traffic_control/
for p in (str(PKG), str(ZONE_PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

# pinky_interfaces 스텁 (로봇에만 설치되어 있음)
if 'pinky_interfaces' not in sys.modules:
    _pi = types.ModuleType('pinky_interfaces')
    _srv = types.ModuleType('pinky_interfaces.srv')
    _srv.SetLed = type('SetLed', (), {})
    _pi.srv = _srv
    sys.modules['pinky_interfaces'] = _pi
    sys.modules['pinky_interfaces.srv'] = _srv

NODE_SOURCE = PKG / 'cobot_pinky_patrol/pinky_patrol_node.py'


def _patrol_class():
    """ROS가 있는 환경에서 실제 파라미터 선언·로딩 메서드를 검증한다."""
    pytest.importorskip('rclpy')
    return importlib.import_module('cobot_pinky_patrol.pinky_patrol_node').PinkyPatrolNode


def load_raw(n):
    """공통·현장·로봇 YAML을 합친 ros__parameters 원본."""
    return load_parameters(f'pinky{n}')


def load_cfg(n):
    """설정 계층의 좌표·홈·구역을 노드와 같은 파서로 읽는다."""
    from cobot_pinky_patrol.patrol_points_utils import parse_points, parse_zone_names, parse_zone_points
    prm = load_raw(n)
    pts = parse_points(prm['points'])
    # 다른 로봇의 홈(I<k>)은 참고용으로 YAML 에 같이 있어도 노드는 읽지 않는다
    pts = {k: v for k, v in pts.items() if not (k.startswith('I') and k != prm['home_name'])}
    return (pts, prm['home_name'],
            parse_zone_names(prm['zone_names']), parse_zone_points(prm['zone_points']))


def manager_params():
    prm = yaml.safe_load((ZONE_PKG / 'config/zone_params.yaml').read_text(encoding='utf-8'))
    return prm['zone_manager_node']['ros__parameters']


ISOLATED = (os.environ.get('ROS_DOMAIN_ID') == '77'
            and os.environ.get('ROS_LOCALHOST_ONLY') == '1')


# ==============================================================================
# 정적 검증 (ROS 불필요)
# ==============================================================================
@pytest.mark.skip(reason='R1: v1.1.0 순회(WAYPOINTS/ZONE_*_INDEX) 주석 처리 -- 되살릴 때 skip 제거')
@pytest.mark.parametrize('n', [1, 2])
def test_waypoint_indexes_match_door_names(n):
    """WAYPOINTS 순번(ZONE_*_INDEX)이 문 좌표(ZONE_*_NAME)와 일치해야 start 경로가 맞게 동작한다."""
    cls = _patrol_class()
    # R3 이후 WAYPOINTS 는 좌표가 아닌 지점 이름 리스트 (되살릴 때 이 비교를 이름 기준으로 맞춘다)
    assert cls.WAYPOINTS[cls.ZONE_ENTRY_INDEX] == cls.ZONE_ENTRY_NAME
    assert cls.WAYPOINTS[cls.ZONE_EXIT_INDEX] == cls.ZONE_EXIT_NAME


@pytest.mark.parametrize('n', [1, 2, 3])
def test_no_hardcoded_queue_coordinates(n):
    """로봇 코드에는 슬롯 좌표가 없다: points 에 RED*/WAIT*/QUEUE* 항목이 없어야 한다 (슬롯은 매니저가 줌)."""
    pts = load_cfg(n)[0]
    extra = [k for k in pts if k.startswith(('RED', 'WAIT', 'QUEUE'))]
    assert extra == []
    src = NODE_SOURCE.read_text(encoding='utf-8')
    assert 'zone_gate_client import' not in src.replace('zone_gate_client', '')


@pytest.mark.parametrize('n', [1, 2, 3])
def test_no_coordinates_left_in_node_code(n):
    """좌표·구역 정보는 YAML 로 옮겼으므로 노드에 POINTS/HOME_NAME/ZONE_POINTS 등 상수가 남아 있으면 안 된다."""
    tree = ast.parse(NODE_SOURCE.read_text(encoding='utf-8'))
    constants = {target.id for assignment in ast.walk(tree)
                 if isinstance(assignment, ast.Assign) for target in assignment.targets
                 if isinstance(target, ast.Name)}
    assert not constants.intersection({
        'POINTS', 'HOME_NAME', 'ZONE_POINTS', 'ZONE_ENTRY_NAME', 'ZONE_EXIT_NAME',
        'STOP_EXIT_NAME', 'GOTO_ALLOWED'})


@pytest.mark.parametrize('n', [1, 2, 3])
def test_zone_names_match_manager_and_no_wait_points(n):
    """구역 이름은 매니저 yaml 과 같고, 대기 앵커는 매니저에만 있다 (로봇 YAML 에 W<구역> 가 없다)."""
    pts, _, zone_names, _ = load_cfg(n)
    mgr = manager_params()
    assert sorted(mgr['zone_names']) == sorted(zone_names)
    for z in zone_names:
        assert f'W{z}' not in pts and f'ZONE_{z}_ENTRY' not in pts
        assert len(mgr[f'zone_{z}']['queue_anchor']) == 3


@pytest.mark.parametrize('n', [1, 2, 3])
def test_zone_settings_are_shared_by_all_robots(n):
    """구역 소속·EXIT 는 3대가 같다 (구역은 맵의 속성이지 로봇의 속성이 아니다)."""
    from cobot_pinky_patrol.patrol_points_utils import exit_name
    pts, _, zone_names, zone_points = load_cfg(n)
    for m in (1, 2, 3):
        pm, _, zm, zpm = load_cfg(m)
        assert zm == zone_names and zpm == zone_points
        for z in zone_names:
            assert pm[exit_name(z)] == pts[exit_name(z)]
    assert not [k for k in pts if k.startswith('RED')]
    assert zone_points == {'A': ('ZA',), 'B': ('ZB',), 'C': ('ZC',)}  # 확정 소속 (2026-10-27)
    assert pts['ZA_EXIT'] == (0.45, 0.2, -1.5)           # 구역 A 출구 (사용자 지정)
    assert pts['ZB_EXIT'] == (0.45, 0.45, -1.5) and pts['ZC_EXIT'] == (-0.2, -0.4, 1.5)


def test_manager_anchors_are_apart_from_zone_points():
    """대기 앵커가 그 구역 소속 지점과 같은 좌표면 대기자가 점유자 자리로 간다 -> 분리되어 있어야 한다.
    A·B 앵커는 (0.15, 0.5, 0.0) 으로 같고 C 는 (-0.2, 0.45, 1.5) 이다 (사용자 지정 2026-10-28)."""
    pts, _, _, zone_points = load_cfg(1)
    mgr = manager_params()
    assert mgr['zone_A']['queue_anchor'] == pytest.approx([0.15, 0.5, 0.0])
    assert mgr['zone_B']['queue_anchor'] == pytest.approx([0.15, 0.5, 0.0])
    assert mgr['zone_C']['queue_anchor'] == pytest.approx([-0.2, 0.45, 1.5])
    for zone, members in zone_points.items():
        for m in members:
            assert tuple(mgr[f'zone_{zone}']['queue_anchor'][:2]) != tuple(pts[m][:2]), (zone, m)


@pytest.mark.parametrize('n', [1, 2, 3])
def test_stop_exit_point_removed_and_entry_exit_not_goto(n):
    """ZONE_STOP_EXIT 는 구역 EXIT 로 합쳤고, ENTRY/EXIT 는 직접 goto 할 수 없다."""
    from cobot_pinky_patrol.patrol_points_utils import exit_name, general_names
    pts, _, zone_names, zone_points = load_cfg(n)
    assert 'ZONE_STOP_EXIT' not in pts and 'ZONE_ENTRY' not in pts and 'ZONE_EXIT' not in pts
    allowed = set(general_names(pts)) | {p for ms in zone_points.values() for p in ms}  # goto/zone 으로 갈 수 있는 지점
    for z in zone_names:
        assert exit_name(z) not in allowed


@pytest.mark.parametrize('n', [1, 2, 3])
def test_yaml_config_is_complete(n):
    """YAML 이 필수 지점·구역 ENTRY/EXIT·홈을 모두 갖고, goto 허용 지점이 전부 정의되어 있다."""
    from cobot_pinky_patrol.patrol_points_utils import (general_names, required_names, validate_points,
                                                         validate_zones)
    pts, home, zone_names, zone_points = load_cfg(n)
    validate_points(pts, required_names(zone_names), home)
    validate_zones(zone_points, pts, home)
    allowed = set(general_names(pts)) | {p for ms in zone_points.values() for p in ms}
    assert allowed <= set(pts)
    assert load_raw(n)['robot_id'] == f'pinky{n}'


def _fake_node(cls, params):
    """_load_points 만 시험하는 가짜 노드. params = {파라미터 이름: 값}, 없는 이름은 미설정(Uninitialized)."""
    from rclpy.exceptions import InvalidParameterTypeException, ParameterUninitializedException
    from rclpy.parameter import Parameter
    node = types.SimpleNamespace()

    def declare_parameter(name, ptype=None):
        if isinstance(params.get(name), list) and any(isinstance(v, int) and not isinstance(v, bool)
                                                       for v in params[name]):
            raise InvalidParameterTypeException(Parameter(name, value=params[name]), Parameter.Type.DOUBLE_ARRAY)

    def get_parameter(name):
        if name not in params:
            raise ParameterUninitializedException(name)
        return types.SimpleNamespace(value=params[name])

    node.declare_parameter = declare_parameter
    node.get_parameter = get_parameter
    node._load_points = types.MethodType(cls._load_points, node)
    return node


def _params_from_yaml(n):
    prm = load_raw(n)
    out = {f'points.{k}': v for k, v in prm['points'].items()}
    out.update({f'zone_points.{z}': list(v) for z, v in prm['zone_points'].items()})
    out['zone_names'] = list(prm['zone_names'])
    out['home_name'] = prm['home_name']
    return out


@pytest.mark.parametrize('n', [1, 2, 3])
def test_load_points_ok(n):
    cls = _patrol_class()
    assert _fake_node(cls, _params_from_yaml(n))._load_points() == load_cfg(n)


@pytest.mark.parametrize('n', [1, 2, 3])
def test_optional_general_points_p3_to_p50(n):
    """P3~P50 은 YAML 에 있는 것만 로드되고 goto 허용에 들어간다. P51 은 읽지 않는다."""
    from cobot_pinky_patrol.patrol_points_utils import general_names
    cls = _patrol_class()
    base = _params_from_yaml(n)
    pts, *_ = _fake_node(cls, base)._load_points()
    assert general_names(pts) == [f'P{i}' for i in range(1, 36)]
    assert 'P3' in pts and 'P10' in pts
    for i in range(3, 51):                                       # 선택 지점은 빼도 시작된다
        base = {k: v for k, v in base.items() if k != f'points.P{i}'}
    pts, *_ = _fake_node(cls, base)._load_points()
    assert general_names(pts) == ['P1', 'P2']
    more = dict(base, **{'points.P3': [1.0, 2.0, 0.5], 'points.P10': [3.0, 4.0],
                         'points.P50': [5.0, 6.0]})
    pts, *_ = _fake_node(cls, more)._load_points()
    assert pts['P3'] == (1.0, 2.0, 0.5) and pts['P10'] == (3.0, 4.0)
    assert pts['P50'] == (5.0, 6.0)
    assert general_names(pts) == ['P1', 'P2', 'P3', 'P10', 'P50']
    over = dict(more, **{'points.P51': [9.0, 9.0]})
    pts, *_ = _fake_node(cls, over)._load_points()
    assert 'P51' not in pts                                      # 최대 P50
    with pytest.raises(Exception, match='소수점'):
        _fake_node(cls, dict(base, **{'points.P3': [0, 0]}))._load_points()


@pytest.mark.parametrize('n', [1, 2, 3])
def test_load_points_refuses_missing_and_bad_values(n):
    from cobot_pinky_patrol.patrol_points_utils import PointsConfigError
    cls = _patrol_class()
    base = _params_from_yaml(n)
    # 1) YAML 없이 실행 (전부 미설정)
    with pytest.raises(PointsConfigError, match='zone_names'):
        _fake_node(cls, {})._load_points()
    # 구역 이름만 있고 좌표가 없는 경우 -> 필수 지점 누락을 한꺼번에 보고
    with pytest.raises(PointsConfigError, match='필수 지점'):
        _fake_node(cls, {k: v for k, v in base.items() if k.startswith(('zone_', 'home'))})._load_points()
    # 2) 지점 하나 누락 -> 메시지에 그 이름
    miss = dict(base)
    del miss['points.ZB']
    with pytest.raises(PointsConfigError, match='ZB'):
        _fake_node(cls, miss)._load_points()
    # 3) 길이 오류 / NaN
    bad = dict(base, **{'points.ZA': [1.0]})
    with pytest.raises(PointsConfigError, match='points.ZA'):
        _fake_node(cls, bad)._load_points()
    bad = dict(base, **{'points.ZA': [float('nan'), 0.0]})
    with pytest.raises(PointsConfigError, match='NaN'):
        _fake_node(cls, bad)._load_points()
    # 4) 정수 배열 (타입 불일치)
    bad = dict(base, **{'points.ZA': [0, 0]})
    with pytest.raises(PointsConfigError, match='소수점'):
        _fake_node(cls, bad)._load_points()
    # 5) home_name 누락 / 없는 지점
    nohome = {k: v for k, v in base.items() if k != 'home_name'}
    with pytest.raises(PointsConfigError, match='home_name'):
        _fake_node(cls, nohome)._load_points()
    with pytest.raises(PointsConfigError, match='P99'):     # 없는 홈 이름은 누락 지점으로 보고된다
        _fake_node(cls, dict(base, home_name='P99'))._load_points()
    # 6) 구역 설정 오류: 구역 ENTRY/EXIT 누락, 구역 소속 누락, 중복 소속, 홈이 구역 안, 잘못된 구역 이름
    miss = {k: v for k, v in base.items() if k != 'points.ZB_EXIT'}
    with pytest.raises(PointsConfigError, match='ZB_EXIT'):
        _fake_node(cls, miss)._load_points()
    miss = {k: v for k, v in base.items() if k != 'zone_points.B'}
    with pytest.raises(PointsConfigError, match='zone_points.B'):
        _fake_node(cls, miss)._load_points()
    with pytest.raises(PointsConfigError, match='동시에 속'):
        _fake_node(cls, dict(base, **{'zone_points.B': ['ZB', 'ZC']}))._load_points()
    with pytest.raises(PointsConfigError, match='구역 밖'):
        _fake_node(cls, dict(base, home_name='ZB'))._load_points()
    with pytest.raises(PointsConfigError, match='영문'):
        _fake_node(cls, dict(base, zone_names=['A', 'B:1']))._load_points()
