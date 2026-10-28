"""pinky_patrol_node_pinky{1,2,3} 의 대기열 진입 흐름 테스트.

- Nav2 / 실로봇 없이 가짜 navigator 를 쓰고, 매니저는 실제 zone_manager_node 를 띄운다.
- ROS_DOMAIN_ID=77 + ROS_LOCALHOST_ONLY=1 이 아니면 통합 테스트는 건너뜀 (실제 관제 도메인 보호).
- 이 PC 에는 pinky_interfaces(로봇 전용)가 없으므로 SetLed 를 스텁으로 대체한다.
"""
import importlib
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
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

MODS = {1: 'cobot_pinky_patrol.pinky_patrol_node_pinky1',
        2: 'cobot_pinky_patrol.pinky_patrol_node_pinky2',
        3: 'cobot_pinky_patrol.pinky_patrol_node_pinky3'}


def load_raw(n):
    """config/pinkyN.yaml 의 ros__parameters 원본."""
    prm = yaml.safe_load((PKG / f'config/pinky{n}.yaml').read_text(encoding='utf-8'))
    return prm['pinky_patrol_node']['ros__parameters']


def load_cfg(n):
    """config/pinkyN.yaml 의 (points, home_name, zone_names, zone_points). 노드가 읽는 값과 같은 파서를 쓴다."""
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
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    # R3 이후 WAYPOINTS 는 좌표가 아닌 지점 이름 리스트 (되살릴 때 이 비교를 이름 기준으로 맞춘다)
    assert cls.WAYPOINTS[cls.ZONE_ENTRY_INDEX] == cls.ZONE_ENTRY_NAME
    assert cls.WAYPOINTS[cls.ZONE_EXIT_INDEX] == cls.ZONE_EXIT_NAME


@pytest.mark.parametrize('n', [1, 2, 3])
def test_no_hardcoded_queue_coordinates(n):
    """로봇 코드에는 슬롯 좌표가 없다: points 에 RED*/WAIT*/QUEUE* 항목이 없어야 한다 (슬롯은 매니저가 줌)."""
    pts = load_cfg(n)[0]
    extra = [k for k in pts if k.startswith(('RED', 'WAIT', 'QUEUE'))]
    assert extra == []
    src = Path(importlib.import_module(MODS[n]).__file__).read_text(encoding='utf-8')
    assert 'zone_gate_client import' not in src.replace('zone_gate_client', '')


@pytest.mark.parametrize('n', [1, 2, 3])
def test_no_coordinates_left_in_node_code(n):
    """좌표·구역 정보는 YAML 로 옮겼으므로 노드에 POINTS/HOME_NAME/ZONE_POINTS 등 상수가 남아 있으면 안 된다."""
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    for name in ('POINTS', 'HOME_NAME', 'ZONE_POINTS', 'ZONE_ENTRY_NAME', 'ZONE_EXIT_NAME',
                 'STOP_EXIT_NAME', 'GOTO_ALLOWED'):
        assert not hasattr(cls, name), name


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
    node._load_points = types.MethodType(cls.__dict__['_load_points'], node)
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
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    assert _fake_node(cls, _params_from_yaml(n))._load_points() == load_cfg(n)


@pytest.mark.parametrize('n', [1, 2, 3])
def test_optional_general_points_p3_to_p10(n):
    """P3~P10 은 YAML 에 있는 것만 로드되고 goto 허용에 들어간다. P11 은 읽지 않는다."""
    from cobot_pinky_patrol.patrol_points_utils import general_names
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    base = _params_from_yaml(n)
    pts, *_ = _fake_node(cls, base)._load_points()
    assert general_names(pts) == [f'P{i}' for i in range(1, 11)]  # YAML 에 P1~P10 이 모두 있다
    assert 'P3' in pts and 'P10' in pts
    for i in range(3, 11):                                       # 선택 지점은 빼도 시작된다
        base = {k: v for k, v in base.items() if k != f'points.P{i}'}
    pts, *_ = _fake_node(cls, base)._load_points()
    assert general_names(pts) == ['P1', 'P2']
    more = dict(base, **{'points.P3': [1.0, 2.0, 0.5], 'points.P10': [3.0, 4.0]})
    pts, *_ = _fake_node(cls, more)._load_points()
    assert pts['P3'] == (1.0, 2.0, 0.5) and pts['P10'] == (3.0, 4.0)
    assert general_names(pts) == ['P1', 'P2', 'P3', 'P10']
    over = dict(more, **{'points.P11': [9.0, 9.0]})
    pts, *_ = _fake_node(cls, over)._load_points()
    assert 'P11' not in pts                                      # 최대 P10
    with pytest.raises(Exception, match='소수점'):
        _fake_node(cls, dict(base, **{'points.P3': [0, 0]}))._load_points()


@pytest.mark.parametrize('n', [1, 2, 3])
def test_load_points_refuses_missing_and_bad_values(n):
    from cobot_pinky_patrol.patrol_points_utils import PointsConfigError
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
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


# ==============================================================================
# 통합: 실제 매니저 + 가짜 navigator
# ==============================================================================
@pytest.fixture(scope='module')
def env():
    if not ISOLATED:
        pytest.skip('ROS_DOMAIN_ID=77 + ROS_LOCALHOST_ONLY=1 에서만 실행')
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from nav2_simple_commander.robot_navigator import TaskResult
    from cobot_zone_traffic_control.zone_gate_client import ZoneGateClient

    mgr = subprocess.Popen(
        [sys.executable, '-m', 'cobot_zone_traffic_control.zone_manager_node',
         '--ros-args', '--params-file', str(ZONE_PKG / 'config/zone_params.yaml')],
        cwd=str(ZONE_PKG), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rclpy.init()

    class FakeNavigator(Node):
        """Nav2 대신: goal 을 기록하고 travel 초 뒤에 성공 처리. cancelTask 는 즉시 CANCELED."""
        _n = 0

        def __init__(self, travel=0.3):
            FakeNavigator._n += 1
            super().__init__(f'fake_nav_{FakeNavigator._n}')
            self.travel, self.goals = travel, []
            self.fail_all = False
            self._active, self._cancelled, self._done_at = False, False, 0.0

        def goToPose(self, pose):
            p = pose.pose
            yaw = 2.0 * __import__('math').atan2(p.orientation.z, p.orientation.w)
            self.goals.append((round(p.position.x, 3), round(p.position.y, 3), round(yaw, 2)))
            self._active, self._cancelled = True, False
            self._done_at = time.time() + self.travel

        def isTaskComplete(self):
            rclpy.spin_once(self, timeout_sec=0.05)     # 실제 BasicNavigator 처럼 자신을 spin
            if not self._active:
                return True
            if self._cancelled or time.time() >= self._done_at:
                self._active = False
                return True
            return False

        def cancelTask(self):
            self._cancelled = True

        def getResult(self):
            if self._cancelled:
                return TaskResult.CANCELED
            return TaskResult.FAILED if self.fail_all else TaskResult.SUCCEEDED

        def getFeedback(self):
            return None

        def waitUntilNav2Active(self):
            pass

    other = Node('other_clients')                        # 점유자/다른 대기자 역할 + 상태 감시
    ex = SingleThreadedExecutor()
    ex.add_node(other)
    status = {'A': None, 'B': None, 'C': None}       # 구역별 점유 상태 ("free" | "occupied_by:<id>")

    def on_status(m):
        zone, _, state = m.data.partition(':')     # 메시지 형식: "<구역>:free" / "<구역>:occupied_by:<id>"
        status[zone] = state

    other.create_subscription(String, '/zone_manager/status', on_status, 10)

    def pump(cond, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            ex.spin_once(timeout_sec=0.05)
            if cond():
                return True
        return False

    # 매니저 준비 대기 (빈 구역이면 request 에 grant 가 온다)
    warm = ZoneGateClient(other, 'warm')
    warm.reset('A')
    tok = warm.send_request()
    ok, end = False, time.time() + 10
    while time.time() < end and not ok:
        warm.resend_if_due()
        ex.spin_once(timeout_sec=0.05)
        ok = warm.granted(tok)
    assert ok, 'zone_manager_node 가 응답하지 않음'
    warm.notify_exit()
    pump(lambda: status['A'] == 'free', 3.0)

    ns = types.SimpleNamespace(rclpy=rclpy, other=other, pump=pump, status=status,
                               Gate=ZoneGateClient, Nav=FakeNavigator)
    yield ns
    mgr.terminate()
    mgr.wait(timeout=5)
    other.destroy_node()
    rclpy.shutdown()


def make_robot(env, n, robot_id, travel=0.3):
    """v3 순찰 노드 클래스에서 필요한 메서드/상수만 가져와 Node 생성 없이 쓰는 로봇 객체."""
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    nav = env.Nav(travel=travel)
    r = types.SimpleNamespace(navigator=nav, robot_id=robot_id, statuses=[], _stop_requested=False,
                              _emergency_requested=False, _running=True, notified=[],
                              _held_zone=None, _idle_deadline=None, _last_point=None,
                              idle_return_sec=1.0, _thread=None)
    r.gate = env.Gate(nav, robot_id)
    # WAYPOINTS / ZONE_*_INDEX / _run_patrol 은 v1.1.0 순회 중단(R1)으로 주석 처리되어 없다.
    for name in ('NAV_RETRIES',):
        setattr(r, name, getattr(cls, name))
    # 좌표/홈/구역은 노드가 파라미터로 받는 YAML 과 같은 값
    r.points, r.home_name, r.zone_names, r.zone_points = load_cfg(n)
    r.zone_allowed = {p for ms in r.zone_points.values() for p in ms}
    from cobot_pinky_patrol.patrol_points_utils import general_names
    r.goto_allowed = (set(general_names(r.points)) | {r.home_name}) - r.zone_allowed
    for name in ('_queue_and_enter', '_start_goal', '_cancel_goal', '_record_pose', '_abort_entry',
                 'make_pose', 'get_current_pose', '_run_goto', '_run_zone', '_run_leave',
                 '_run_idle_return', '_exit_held_zone', '_arm_idle', '_idle_tick', '_finish_task',
                 '_prepare_nav', '_start_task', '_navigate', '_leave_zone', '_wait_interruptible',
                 '_retreat_after_stop', '_end_state'):
        setattr(r, name, types.MethodType(cls.__dict__[name], r))
    r.get_logger = nav.get_logger
    r.publish_status = lambda state, idx, detail='': r.statuses.append((state, detail))
    r.start_blink = lambda *a, **k: None
    r.stop_blink = lambda: None
    r.set_drive_led = lambda: None
    r.set_idle_led = lambda: None
    r.save_last_pose = lambda *a: None
    r._init_pose_once = lambda: None
    r._running = False   # _start_task / 테스트가 필요할 때 세운다
    return r


def run_in_thread(fn, *args):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault('r', fn(*args)), daemon=True)
    t.start()
    return t, out


def occupy(env, rid='pinky1', zone='A'):
    """다른 로봇이 구역 ``zone`` 을 점유한 상황을 만든다 (반환: 게이트)."""
    g = env.Gate(env.other, rid)
    g.reset(zone)
    tok = g.send_request()
    assert env.pump(lambda: g.granted(tok))
    return g


def states(r):
    return [s for s, _ in r.statuses]


_POINTS = load_cfg(1)[0]
EXIT = tuple(_POINTS['ZA_EXIT'])     # 구역 A 락 반납 출구


def _slot(k):
    """zone_params.yaml 의 앵커/후방 벡터/간격으로 슬롯 k 를 계산 (매니저가 발행하는 값과 같은 규칙)."""
    from cobot_zone_traffic_control.zone_manager_node import normalize_dir, slot_pose
    prm = manager_params()
    x, y, yaw = slot_pose(k, prm['zone_A']['queue_anchor'], normalize_dir(prm['zone_A']['queue_back_dir']),
                          prm['queue_spacing'])
    return (round(x, 3), round(y, 3), round(yaw, 2))   # FakeNavigator 가 기록하는 형식과 동일


SLOT0 = _slot(0)
SLOT1 = _slot(1)


def test_empty_zone_grant_does_not_wait_at_anchor(env):
    r = make_robot(env, 1, 'pinky2')
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: not t.is_alive())
    assert out['r'] is True
    assert not r.navigator.goals                          # 빈 구역: 슬롯·앵커로 가지 않고 응답(허가)을 기다렸다 곧바로 반환
    assert 'QUEUEING' not in states(r)
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free')


def test_waits_in_slot_then_enters(env):
    occ = occupy(env)
    r = make_robot(env, 1, 'pinky2')
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: 'QUEUEING' in states(r))
    assert env.pump(lambda: SLOT0 in r.navigator.goals)  # 슬롯 좌표는 매니저가 준 값
    time.sleep(0.8)
    assert t.is_alive()                                  # 허가 전에는 문으로 들어가지 않음
    n_before = len(r.navigator.goals)
    occ.notify_exit()
    assert env.pump(lambda: not t.is_alive(), 10)
    assert out['r'] is True
    assert r.navigator.goals[-1] == SLOT0                # 허가 후 앵커 이동 없음 (이미 슬롯 0 에 있음)
    assert len(r.navigator.goals) == n_before            # 허가 후 새 goal 없음
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free')


def test_slot_reassign_cancels_and_moves_forward(env):
    occ = occupy(env)
    front = env.Gate(env.other, 'pinky4')
    front.reset('A')
    front.send_request()
    assert env.pump(lambda: front.current_slot is not None)      # k=0
    r = make_robot(env, 1, 'pinky2')
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: SLOT1 in r.navigator.goals)          # 뒤 로봇은 k=1
    front.cancel_entry()                                         # 앞 대기자 포기 -> 한 칸 전진
    assert env.pump(lambda: r.navigator.goals[-1] == SLOT0, 8)
    r._stop_requested = True
    assert env.pump(lambda: not t.is_alive())
    assert out['r'] is False
    occ.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free')


def test_stop_while_queued_cancels_entry(env):
    occ = occupy(env)
    r = make_robot(env, 1, 'pinky2')
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: SLOT0 in r.navigator.goals)
    time.sleep(0.5)
    r._stop_requested = True
    assert env.pump(lambda: not t.is_alive())
    assert out['r'] is False and states(r)[-1] == 'STOPPED'
    occ.notify_exit()                                    # 취소했으므로 아무에게도 허가가 가면 안 됨
    assert env.pump(lambda: env.status['A'] == 'free', 4)


@pytest.mark.parametrize('n', [1, 2])
def test_stop_command_callback_does_not_cancel_from_callback_thread(env, n):
    """stop 명령 콜백은 플래그만 세운다. 콜백에서 navigator.cancelTask() 를 부르면 실기에서
    'Executor is already spinning' 으로 노드가 죽었다 (T4, 2026-10-14)."""
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    r = make_robot(env, n, f'pinky{n}')
    r._cmd_cb = types.MethodType(cls.__dict__['_cmd_cb'], r)
    calls = []
    r.navigator.cancelTask = lambda: calls.append('cancel')
    r._running = True
    r._cmd_cb(types.SimpleNamespace(data='stop'))
    assert r._stop_requested is True
    assert calls == []


def test_grant_received_while_traveling_to_slot(env):
    occ = occupy(env)
    r = make_robot(env, 1, 'pinky2', travel=2.0)         # 느린 이동: 도착 전에 허가가 온다
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: SLOT0 in r.navigator.goals)
    occ.notify_exit()                                    # 슬롯에 도착하기 전에 점유자 이탈
    assert env.pump(lambda: not t.is_alive(), 12)
    assert out['r'] is True
    assert r.navigator.goals[0] == SLOT0                 # 응답 전에는 제자리 대기, 첫 이동은 슬롯
    assert r.navigator.goals[-1] == SLOT0                # 허가 후 슬롯 goal 만 취소, 앵커로 가지 않음
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free')


def test_queue_full_gives_up_without_holding(env):
    occ = occupy(env)
    fillers = [env.Gate(env.other, f'pinky{i}') for i in (4, 5, 6)]   # queue_max=3
    for g in fillers:
        g.reset('A')
        g.send_request()
    assert env.pump(lambda: all(g.current_slot is not None for g in fillers))
    r = make_robot(env, 1, 'pinky2')
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: not t.is_alive())
    assert out['r'] is False
    assert r.statuses[-1] == ('FAILED', 'queue_full')
    for g in fillers:
        g.cancel_entry()
    env.pump(lambda: False, 0.5)                         # 취소가 먼저 반영돼야 함 (게시자가 달라 순서 비보장)
    occ.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_grant_returns_immediately_without_going_to_anchor(env):
    """슬롯 1 에서 기다리다 허가를 받으면 앵커/슬롯 0 을 거치지 않고 바로 반환한다 (호출자가 목적지로 직행)."""
    occ = occupy(env)
    front = env.Gate(env.other, 'pinky4')
    front.reset('A')
    front.send_request()
    assert env.pump(lambda: front.current_slot is not None)      # 앞 대기자 k=0
    r = make_robot(env, 1, 'pinky2', travel=0.3)
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    assert env.pump(lambda: SLOT1 in r.navigator.goals)          # 뒤 로봇 k=1
    occ.notify_exit()                                            # 허가는 앞 대기자(pinky4)에게
    front.notify_exit()                                          # 앞 대기자도 통과 -> pinky2 에게 허가
    assert env.pump(lambda: not t.is_alive(), 12)
    assert out['r'] is True
    n_end = len(r.navigator.goals)
    env.pump(lambda: False, 0.8)
    assert len(r.navigator.goals) == n_end                       # 반환 뒤 앵커 등 새 goal 이 나가지 않음
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free', 4)


@pytest.mark.skip(reason='R1: v1.1.0 순회(_run_patrol) 주석 처리 -- 되살릴 때 skip 제거')
def test_pinky2_start_path_uses_corrected_indexes(env):
    """pinky2 start 경로: 구역 A ENTRY 에서 진입 절차 -> ZB -> ... -> 구역 EXIT 에서 락 반납 -> I2."""
    r = make_robot(env, 2, 'pinky2')
    t, out = run_in_thread(r._run_patrol)
    assert env.pump(lambda: not t.is_alive(), 15)
    g = r.navigator.goals
    assert len(g) == 5, g
    assert g[3] == EXIT and g[3][2] == pytest.approx(3.14, abs=0.01)
    assert states(r)[-1] == 'DONE'
    assert env.pump(lambda: env.status['A'] == 'free', 4)   # ZONE_EXIT(3번) 도착 때 notify_exit


@pytest.mark.skip(reason='R1: v1.1.0 순회(_run_patrol) 주석 처리 -- 되살릴 때 skip 제거')
def test_pinky1_start_path_waits_in_queue(env):
    occ = occupy(env)
    r = make_robot(env, 1, 'pinky1x')
    t, out = run_in_thread(r._run_patrol)
    assert env.pump(lambda: 'QUEUEING' in states(r), 10)
    assert SLOT0 in r.navigator.goals
    occ.notify_exit()
    assert env.pump(lambda: not t.is_alive(), 20)
    assert states(r)[-1] == 'DONE'
    assert env.pump(lambda: env.status['A'] == 'free', 4)


# ------------------------------------------------------------------------------
# stop / emergency_stop (T4 후속, 2026-10-14)
# ------------------------------------------------------------------------------
def _goal(wp):
    """POINTS 튜플 -> FakeNavigator.goals 에 기록되는 (x, y, yaw) 형태."""
    return (round(wp[0], 3), round(wp[1], 3), round(wp[2] if len(wp) > 2 else 0.0, 2))


def _stop_in_zone(env, emergency):
    r = make_robot(env, 2, 'pinky2', travel=1.0)
    t, out = run_in_thread(r._run_zone, 'ZA')   # start 대신 zone 경로(ZA = 구역 A 안)로 같은 stop 경로를 검증
    p2 = _goal(r.points['ZA'])
    assert env.pump(lambda: p2 in r.navigator.goals)       # 허가받고 구역 안(ZA)으로 가는 중
    assert env.status['A'] == 'occupied_by:pinky2'
    r._emergency_requested = emergency
    r._stop_requested = True
    return r, t


def test_stop_in_zone_retreats_to_zone_exit_and_returns_token(env):
    r, t = _stop_in_zone(env, emergency=False)
    assert env.pump(lambda: not t.is_alive(), 12)
    assert r.navigator.goals[-1] == _goal(r.points['ZA_EXIT'])
    assert 'RETREATING' in states(r) and states(r)[-1] == 'STOPPED'
    assert env.pump(lambda: env.status['A'] == 'free', 4)    # 토큰 반납됨
    assert r._held_zone is None


def test_emergency_stop_in_zone_keeps_token_and_position(env):
    r, t = _stop_in_zone(env, emergency=True)
    assert env.pump(lambda: not t.is_alive(), 12)
    assert _goal(r.points['ZA_EXIT']) not in r.navigator.goals
    assert 'RETREATING' not in states(r)
    assert not env.pump(lambda: env.status['A'] == 'free', 2.0)   # 락 유지 (max_hold_sec 뒤에만 해제)
    assert r._held_zone is None          # 노드는 구역을 쥔 것으로 기억하지 않아 다음 zone 이 토큰을 다시 요청한다
    r.gate.notify_exit()                                   # 정리
    assert env.pump(lambda: env.status['A'] == 'free', 4)


@pytest.mark.parametrize('n', [1, 2, 3])
def test_cmd_cb_emergency_stop_sets_both_flags(env, n):
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    r = make_robot(env, n, f'pinky{n}')
    r._cmd_cb = types.MethodType(cls.__dict__['_cmd_cb'], r)
    r._running = True
    r._cmd_cb(types.SimpleNamespace(data='emergency_stop'))
    assert r._stop_requested and r._emergency_requested
    r._stop_requested = r._emergency_requested = False
    r._cmd_cb(types.SimpleNamespace(data='stop'))
    assert r._stop_requested and not r._emergency_requested


@pytest.mark.parametrize('n', [1, 2, 3])
def test_start_is_disabled_and_reports_failed(env, n):
    """R1: start 는 작업을 시작하지 않고 FAILED(start disabled) 로 응답한다."""
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    r = make_robot(env, n, f'pinky{n}')
    r._cmd_cb = types.MethodType(cls.__dict__['_cmd_cb'], r)
    r._running = False
    r._thread = None
    r._cmd_cb(types.SimpleNamespace(data='start'))
    assert r.statuses == [('FAILED', 'start disabled')]
    assert r._running is False and r._thread is None


# ------------------------------------------------------------------------------
# 위험구역 2개 (구역마다 토큰·대기열이 따로)
# ------------------------------------------------------------------------------
def test_other_zone_occupant_does_not_block(env):
    """구역 A 가 점유 중이어도 구역 C 지점(ZC)으로는 대기 없이 갈 수 있다."""
    occ = occupy(env, 'pinky1', 'A')
    r = make_robot(env, 2, 'pinky2')
    t, out = run_in_thread(r._run_zone, 'ZC')
    assert env.pump(lambda: not t.is_alive(), 15)
    assert 'DONE' in states(r) and r._held_zone == 'C'
    assert 'QUEUEING' not in states(r) and 'WAITING_ZONE' not in states(r)
    assert env.status['A'] == 'occupied_by:pinky1'            # A 의 점유는 그대로
    assert env.pump(lambda: env.status['C'] == 'occupied_by:pinky2', 4)   # C 토큰은 도착 후에도 유지
    r.gate.notify_exit()                                       # 정리 (leave 대신 직접 반납)
    assert env.pump(lambda: env.status['C'] == 'free', 4)
    occ.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_route_across_zones_releases_first_zone_before_second(env):
    """명령 zone ZA(구역 A) 다음 zone ZB(구역 B): A EXIT 에서 A 토큰을 반납한 뒤에 B 를 요청한다 (동시에 두 토큰을 쥐지 않음)."""
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZA')
    assert r._held_zone == 'A' and env.status['A'] == 'occupied_by:pinky2'
    r._start_task(r._run_zone, 'ZB')
    p3 = _goal(r.points['ZB'])
    assert env.pump(lambda: p3 in r.navigator.goals, 15)      # B 구역 안으로 가는 중
    assert env.status['A'] == 'free'                          # 이때 A 는 이미 반납됨
    assert env.pump(lambda: env.status['B'] == 'occupied_by:pinky2', 4)
    assert env.pump(lambda: not r._running, 15)
    g = r.navigator.goals
    # ZA -> A 출구 -> ZB 순서 (자리값 좌표가 겹칠 수 있으므로 앞 목표 "이후"에서 다음 목표를 찾는다)
    pos = -1
    for n in ('ZA', 'ZA_EXIT', 'ZB'):
        assert _goal(r.points[n]) in g[pos + 1:], (n, g)
        pos = g.index(_goal(r.points[n]), pos + 1)
    assert r._held_zone == 'B' and _goal(r.points[r.home_name]) not in g[pos + 1:]
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['B'] == 'free', 4)


def test_stop_in_zone_b_retreats_to_zone_b_exit(env):
    """stop 후퇴는 현재 구역의 EXIT 로 간다 (구역 B 에 있으면 ZB_EXIT)."""
    r = make_robot(env, 2, 'pinky2', travel=1.0)
    t, out = run_in_thread(r._run_zone, 'ZB')
    p3 = _goal(r.points['ZB'])
    assert env.pump(lambda: p3 in r.navigator.goals)
    assert env.status['B'] == 'occupied_by:pinky2'
    r._stop_requested = True
    assert env.pump(lambda: not t.is_alive(), 12)
    assert r.navigator.goals[-1] == _goal(r.points['ZB_EXIT'])
    assert env.pump(lambda: env.status['B'] == 'free', 4)


def test_stop_in_zone_c_retreats_to_zone_c_exit(env):
    """구역 C(ZC)에서 stop 하면 ZC_EXIT 로 후퇴해 C 토큰을 반납한다."""
    r = make_robot(env, 2, 'pinky2', travel=1.0)
    t, out = run_in_thread(r._run_zone, 'ZC')
    p4 = _goal(r.points['ZC'])
    assert env.pump(lambda: p4 in r.navigator.goals)
    assert env.status['C'] == 'occupied_by:pinky2'
    r._stop_requested = True
    assert env.pump(lambda: not t.is_alive(), 12)
    assert r.navigator.goals[-1] == _goal(r.points['ZC_EXIT'])
    assert env.pump(lambda: env.status['C'] == 'free', 4)


def test_three_zones_do_not_block_each_other(env):
    """A, B 가 점유 중이어도 구역 C 지점(ZC)으로는 대기 없이 간다 (구역마다 토큰이 따로)."""
    occ_a = occupy(env, 'pinky1', 'A')
    occ_b = occupy(env, 'pinky3', 'B')
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZC')
    assert r._held_zone == 'C' and 'QUEUEING' not in states(r)
    assert env.pump(lambda: env.status['C'] == 'occupied_by:pinky2', 4)
    r.gate.notify_exit()
    occ_a.notify_exit()
    occ_b.notify_exit()
    assert env.pump(lambda: all(env.status[z] == 'free' for z in 'ABC'), 6)


def test_queue_slots_extend_toward_negative_y():
    """구역 A·B·C 의 대기줄은 y 감소 방향(queue_back_dir [0,-1])으로 늘어난다 (+y 는 맵 밖이라 Nav2 가 거부)."""
    from cobot_zone_traffic_control.zone_manager_node import normalize_dir, slot_pose
    prm = manager_params()
    for z, anchor in (('A', (0.15, 0.5)), ('B', (0.15, 0.5)), ('C', (-0.2, 0.45))):
        d = normalize_dir(prm[f'zone_{z}']['queue_back_dir'])
        x0, y0, _ = slot_pose(0, prm[f'zone_{z}']['queue_anchor'], d, prm['queue_spacing'])
        x1, y1, _ = slot_pose(1, prm[f'zone_{z}']['queue_anchor'], d, prm['queue_spacing'])
        assert (x0, y0) == pytest.approx(anchor)
        assert x1 == pytest.approx(x0) and y1 == pytest.approx(y0 - prm['queue_spacing'])


def _cmd(env, n, data, held=None):
    """_cmd_cb 만 단독으로 시험한다 (작업 스레드를 띄우지 않는 거부 경로 전용)."""
    cls = importlib.import_module(MODS[n]).PinkyPatrolNode
    r = make_robot(env, n, f'pinky{n}')
    r._cmd_cb = types.MethodType(cls.__dict__['_cmd_cb'], r)
    r._held_zone = held
    r._cmd_cb(types.SimpleNamespace(data=data))
    return r


@pytest.mark.parametrize('n', [1, 2, 3])
@pytest.mark.parametrize('data, detail', [
    ('goto:ZA_EXIT', 'not allowed'),  # EXIT 는 직접 이동 불가
    ('goto:ZA', 'use zone'),  # 구역 지점은 zone 으로만
    ('goto:P1,ZB', 'use zone'),
    ('zone:P1', 'zone needs one zone point'),  # 구역 밖 지점
    ('zone:ZA,ZB', 'zone needs one zone point'),  # 한 번에 1개
    ('zone:', 'no point given'),
    ('goto:', 'no point given'),
    ('zone:P99', 'unknown point'),
    ('goto:P11', 'unknown point'),  # P10 을 넘는 지점
])
def test_cmd_cb_rejects_wrong_command_without_starting(env, n, data, detail):
    r = _cmd(env, n, data)
    assert r.statuses[-1][0] == 'FAILED' and detail in r.statuses[-1][1], r.statuses
    assert not r._running and r._thread is None


@pytest.mark.parametrize('n', [1, 2, 3])
def test_cmd_cb_leave_without_zone_fails(env, n):
    r = _cmd(env, n, 'leave')
    assert r.statuses == [('FAILED', 'no zone held')]
    assert not r._running and r._thread is None


# ------------------------------------------------------------------------------
# 독립 이동 / zone / leave / 유휴 복귀 (PRD patrol_independent_move_prd)
# ------------------------------------------------------------------------------
def run_task(env, r, fn, *args, timeout=15):
    """_start_task 로 작업을 시작해 끝날 때까지 기다린다 (명령 1개를 처리한 것과 같다)."""
    r._start_task(fn, *args)
    assert env.pump(lambda: not r._running, timeout), states(r)


def test_goto_does_not_return_home_and_idle_timer_returns(env):
    """명령 goto 는 도착 후 홈으로 가지 않고, idle_return_sec 뒤에만 홈으로 복귀한다."""
    r = make_robot(env, 2, 'pinky2')               # 홈 I2
    r.idle_return_sec = 0.6
    home, p1 = _goal(r.points[r.home_name]), _goal(r.points['P1'])
    assert home != p1
    run_task(env, r, r._run_goto, ['P1'])
    assert r.navigator.goals == [p1]                   # 홈으로 안 감
    assert r.statuses[-1] == ('IDLE_WAIT', '0.6') and r._idle_deadline is not None
    assert env.pump(lambda: (r._idle_tick(), r.statuses[-1] == ('DONE', 'returned home'))[1], 10)
    assert r.navigator.goals[-1] == home and r._idle_deadline is None
    assert 'RETURNING' in states(r)


def test_new_command_cancels_idle_timer(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 5
    run_task(env, r, r._run_goto, ['P1'])
    assert r._idle_deadline is not None
    r._start_task(r._run_goto, ['P1'])
    assert r._idle_deadline is None                    # 새 명령 수락 즉시 타이머 취소
    assert env.pump(lambda: not r._running, 10)


def test_idle_return_disabled_when_zero(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_goto, ['P1'])
    assert r._idle_deadline is None and 'IDLE_WAIT' not in states(r)
    r._idle_tick()
    assert not r._running


def test_no_idle_timer_when_already_home_and_no_zone(env):
    r = make_robot(env, 2, 'pinky2')
    run_task(env, r, r._run_goto, [r.home_name])
    assert r._idle_deadline is None


def test_zone_keeps_token_and_does_not_go_home(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZA')
    assert r._held_zone == 'A' and ('HOLDING_ZONE', 'A') in r.statuses
    assert env.pump(lambda: env.status['A'] == 'occupied_by:pinky2', 4)
    assert r.navigator.goals[-1] == _goal(r.points['ZA'])         # 홈 복귀 없음
    # 같은 구역 zone 재명령: 토큰 재요청 없이 바로 이동 (ENTRY 를 거치지 않는다)
    n = len(r.navigator.goals)
    run_task(env, r, r._run_zone, 'ZA')
    assert r.navigator.goals[n:] == [_goal(r.points['ZA'])]
    assert env.status['A'] == 'occupied_by:pinky2'
    run_task(env, r, r._run_leave)                                # 정리
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_leave_goes_to_exit_returns_token_and_stays(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZA')
    run_task(env, r, r._run_leave)
    assert r.navigator.goals[-1] == _goal(r.points['ZA_EXIT']) and r._held_zone is None
    assert r.statuses[-1] == ('DONE', 'left zone')
    assert env.pump(lambda: env.status['A'] == 'free', 4)
    assert _goal(r.points[r.home_name]) not in r.navigator.goals[-1:]


def test_goto_after_zone_exits_zone_first(env):
    """구역 안에서 goto 를 받으면 EXIT 도착 -> 반납 -> 그다음 이동 순서."""
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZA')
    run_task(env, r, r._run_goto, ['P1'])
    g = r.navigator.goals
    assert g[-2:] == [_goal(r.points['ZA_EXIT']), _goal(r.points['P1'])], g
    assert r._held_zone is None
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_idle_expiry_in_zone_exits_returns_token_then_home(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0.6
    run_task(env, r, r._run_zone, 'ZA')
    assert ('IDLE_WAIT', '0.6') in r.statuses
    assert env.pump(lambda: (r._idle_tick(), r.statuses[-1] == ('DONE', 'returned home'))[1], 12)
    g = r.navigator.goals
    assert g[-2:] == [_goal(r.points['ZA_EXIT']), _goal(r.points[r.home_name])], g
    assert r._held_zone is None
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_home_command_exits_zone_then_goes_home(env):
    """home 명령: 구역 안이면 EXIT 반납 후 홈으로 간다 (유휴 복귀와 같은 절차를 즉시 실행)."""
    r = make_robot(env, 2, 'pinky2')
    run_task(env, r, r._run_zone, 'ZA')
    assert r._held_zone == 'A'
    r._cmd_cb = types.MethodType(importlib.import_module(MODS[2]).PinkyPatrolNode.__dict__['_cmd_cb'], r)
    r._cmd_cb(types.SimpleNamespace(data='home'))
    assert env.pump(lambda: not r._running, 15), states(r)
    assert r.statuses[-1] == ('DONE', 'returned home')
    assert r.navigator.goals[-2:] == [_goal(r.points['ZA_EXIT']), _goal(r.points[r.home_name])]
    assert r._held_zone is None
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_home_command_at_home_does_not_move_and_busy_is_ignored(env):
    """이미 홈이면 이동 없이 DONE, 작업 중이면 home 을 무시한다."""
    r = make_robot(env, 2, 'pinky2')
    r._cmd_cb = types.MethodType(importlib.import_module(MODS[2]).PinkyPatrolNode.__dict__['_cmd_cb'], r)
    r._last_point = r.home_name
    r._cmd_cb(types.SimpleNamespace(data='home'))
    assert env.pump(lambda: not r._running, 10), states(r)
    assert r.statuses[-1] == ('DONE', 'returned home') and not r.navigator.goals
    r._running = True                                   # 작업 중
    n = len(r.statuses)
    r._cmd_cb(types.SimpleNamespace(data='home'))
    assert len(r.statuses) == n and r._thread is not None


def test_client_build_command_home():
    """클라이언트: home 은 포인트 없이 'home' 으로 전송하고 포인트를 주면 거부한다."""
    sys.path.insert(0, str(PKG.parent / 'cobot_pinky_patrol_cmd'))
    from pinky_control_client import build_command
    assert build_command('home', []) == ('home', None)
    assert build_command('home', ['P1'])[0] is None
    assert build_command('leave', []) == ('leave', None)


def test_leave_failure_keeps_token_and_can_retry(env):
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    run_task(env, r, r._run_zone, 'ZA')
    r.navigator.fail_all = True                       # EXIT 에 도착하지 못함
    run_task(env, r, r._run_leave, timeout=20)
    assert r._held_zone == 'A' and r.statuses[-1][0] == 'FAILED'
    assert not env.pump(lambda: env.status['A'] == 'free', 1.5)    # 도착 전에는 반납하지 않는다
    r.navigator.fail_all = False
    run_task(env, r, r._run_leave)                    # 다시 leave 하면 반납
    assert r._held_zone is None
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_zone_does_not_start_before_grant(env):
    """구역 점유 중이면 grant 전에는 구역 지점(ZA)으로 출발하지 않고 슬롯에서 기다린다."""
    occ = occupy(env, 'pinky1', 'A')
    r = make_robot(env, 2, 'pinky2')
    r.idle_return_sec = 0
    r._start_task(r._run_zone, 'ZA')
    p2 = _goal(r.points['ZA'])
    assert env.pump(lambda: 'QUEUEING' in states(r), 10)
    assert p2 not in r.navigator.goals
    occ.notify_exit()
    assert env.pump(lambda: not r._running, 15)
    assert r.navigator.goals[-1] == p2 and r._held_zone == 'A'
    r.gate.notify_exit()
    assert env.pump(lambda: env.status['A'] == 'free', 4)


def test_waits_in_place_until_manager_responds(env):
    """매니저 응답(허가/슬롯)이 오기 전에는 앵커 쪽으로 먼저 출발하지 않고 제자리에서 기다린다."""
    r = make_robot(env, 1, 'pinky2')
    r.gate.send_request = lambda: None                   # 요청이 나가지 않아 매니저 응답이 없는 상황
    r.gate.resend_if_due = lambda: None
    t, out = run_in_thread(r._queue_and_enter, 0, 'ZB', 'A')
    env.pump(lambda: False, 1.0)
    assert not r.navigator.goals and t.is_alive()        # 이동 명령 없이 대기 중
    r._stop_requested = True                             # stop 으로 빠져나온다
    assert env.pump(lambda: not t.is_alive(), 5)
    assert out['r'] is False
