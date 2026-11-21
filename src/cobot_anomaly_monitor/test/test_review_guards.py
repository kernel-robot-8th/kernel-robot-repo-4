"""
11-21 수정 재검토 지적 시험: 범위 좁힘 두 가지와 이상한 입력에 터지는 콜백.

- 걸침 AMBIGUOUS: 화물로 잇는 로봇이 늘어도 11-20 전 기준판(404d7ab)이 세우던 로봇을 빼지 않는다.
- 순찰 상태 끊김: 판정 입력 driving·queue_wait 은 마지막 상태 그대로다(밟힘 충돌이 무시로 바뀌지 않음).
- 작업 요청 단계·대상이 문자열이 아니어도, 관제 holds·operator_completed 가 이상해도 예외를 내지 않는다.
- 지목 로봇이 없던 사건은 그 자리에 서 있던 로봇에만 새로 잇는다(지나가는 로봇 오지목 방지).
"""

import json

from cobot_anomaly_monitor.console_api import ConsoleApi
from cobot_anomaly_monitor.judgment import judge, rejudge
from cobot_anomaly_monitor.manual_adapter import known_stage, ManualAdapter, UNKNOWN_STAGE_REASON
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
from harness import Stack
import pytest

ROUTES = {
    'col1__P22': {'pickup': 'ZB', 'pickup_arm': 'omx2', 'customer': 'P22', 'dropoff': 'ZC',
                  'dropoff_arm': 'omx3', 'restock': 'ZA', 'restock_arm': 'omx1', 'lane': 'main'},
    'lab_delivery_zb': {'pickup': 'ZB', 'dropoff': 'ZC', 'pickup_arm': 'omx2',
                        'dropoff_arm': 'omx3', 'lane': 'main'}}
LOADED_DONE = ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD',
               'VERIFY_LOAD', 'LEAVE_PICKUP', 'MOVE_CUSTOMER']
ROBOTS = ['pinky1', 'pinky2', 'pinky3']


def seat(order_id, robot, stage, state='RUNNING', done=LOADED_DONE, **extra):
    return dict(order_id=order_id, robot_id=robot, route='col1__P22', kind='delivery', sku='S',
                quantity=1, stage=stage, state=state, completed=list(done), destination='P22',
                **extra)


def route_order(order_id, robot, stage, done):
    return {'order_id': order_id, 'robot_id': robot, 'route': 'lab_delivery_zb',
            'kind': 'delivery', 'sku': 'S', 'quantity': 1, 'stage': stage, 'state': 'RUNNING',
            'completed': list(done)}


class Clocked:
    def __init__(self, tmp_path, mode='OBSERVE_ONLY'):
        self.now, self.sent = [1000.0], []
        self.store = MonitorStore(tmp_path / 'm.sqlite3')
        self.core = MonitorCore(self.store, ROUTES, ROBOTS, self.sent.append, mode,
                                clock=lambda: self.now[0])

    def feed(self, orders, statuses, holds=None):
        for robot, status in statuses.items():
            self.core.on_status(robot, status)
        self.core.on_tasks({'armed': True, 'holds': holds or {}, 'tasks': [],
                            'orders': list(orders)})
        self.now[0] += 1.0

    def event(self, event_id, vision_class, xy, detected_at=None):
        return self.core.on_vision_event({
            'event_id': event_id, 'camera_id': 'c', 'vision_class': vision_class,
            'map_x': xy[0], 'map_y': xy[1],
            'detected_at': self.now[0] if detected_at is None else detected_at})


@pytest.fixture
def clocked(tmp_path):
    item = Clocked(tmp_path)
    yield item
    item.store.close()


# 1. 걸침 AMBIGUOUS 범위(재검토 must_fix 1) ------------------------------------------------

IDLE = {'state': 'IDLE', 'detail': ''}
RETURNING = {'state': 'RETURNING', 'detail': 'I2'}
O1_AT_CUSTOMER = seat('o1', 'pinky1', 'CUSTOMER')
O1_TIMED_OUT = seat('o1', 'pinky1', 'RETURN_EXIT', 'COMPLETED',
                    LOADED_DONE + ['CUSTOMER', 'RETURN_HOME', 'RETURN_EXIT'],
                    customer_timed_out=True)


@pytest.mark.parametrize('second', [
    # A: 시간 초과 복귀 중(신발 실음). 기준판 LOAD_FAIL_PERCHED pinky2 PAUSE/ROBOT.
    seat('o2', 'pinky2', 'RETURN_HOME', done=LOADED_DONE + ['CUSTOMER'], customer_timed_out=True),
    # B: 결제 뒤 복귀 중(EMPTY_UNVERIFIED). 기준판은 LOADED 로 봐 pinky2 PAUSE/ROBOT.
    seat('o2', 'pinky2', 'RETURN_HOME', done=LOADED_DONE + ['CUSTOMER'], customer_received=True),
], ids=['A_timeout_return', 'B_paid_return'])
def test_home_slot_with_leftover_cargo_never_drops_the_robot_the_baseline_paused(clocked, second):
    """HOME 슬롯 I1·I2 는 0.2 m 간격이다. 잔류 화물 로봇 옆을 지나는 로봇을 빼지 않는다."""
    clocked.feed([O1_AT_CUSTOMER], {'pinky1': IDLE})
    clocked.feed([O1_TIMED_OUT], {'pinky1': IDLE})
    clocked.feed([O1_TIMED_OUT, second], {'pinky1': IDLE, 'pinky2': RETURNING})
    clocked.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    clocked.core.on_pose('pinky2', 0.0, -0.25, 0.0)
    views = clocked.core.robots_view()
    assert views['pinky1']['residual_cargo']['order_id'] == 'o1'
    rim = judge({'vision_class': 'box_perched_on_rim', 'map_x': 0.0, 'map_y': -0.2}, views)
    assert (rim['judgment'], rim['recommended_action'], rim['stop_scope']) == (
        'AMBIGUOUS', 'PAUSE', 'ROBOT')
    assert 'pinky2' in rim['stop_targets'] and sorted(rim['stop_targets']) == ['pinky1', 'pinky2']
    floor = judge({'vision_class': 'box_on_floor', 'map_x': 0.0, 'map_y': -0.2}, views)
    assert (floor['judgment'], floor['recommended_action'], floor['stop_scope']) == (
        'AMBIGUOUS', 'PAUSE', 'ALL')


def test_pick_robot_beside_a_passing_loaded_robot_keeps_pausing_the_loaded_one(clocked):
    """C: ZB PICK 로봇 옆 0.5 m 를 실린 로봇이 지난다. 기준판 TRANSIT_PERCHED pinky2 PAUSE/ROBOT."""
    picking = route_order('o1', 'pinky1', 'PICK',
                          ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER'])
    passing = route_order('o2', 'pinky2', 'MOVE_DROPOFF', LOADED_DONE[:8])
    clocked.feed([picking, passing], {'pinky1': {'state': 'HOLDING_ZONE', 'held_zone': 'B'},
                                      'pinky2': {'state': 'MOVING', 'detail': 'ZC'}})
    clocked.core.on_pose('pinky1', 0.6, -0.15, 0.0)
    clocked.core.on_pose('pinky2', 0.6, -0.65, 0.0)
    views = clocked.core.robots_view()
    rim = judge({'vision_class': 'box_perched_on_rim', 'map_x': 0.6, 'map_y': -0.45}, views)
    assert (rim['judgment'], rim['recommended_action'], rim['stop_scope']) == (
        'AMBIGUOUS', 'PAUSE', 'ROBOT')
    assert sorted(rim['stop_targets']) == ['pinky1', 'pinky2']


def test_pick_and_passing_loaded_robot_in_the_sakim_flow_pause_both_robots(tmp_path):
    """관제(sakim) 흐름으로 C 를 만든다. AUTO_HOLD 에서 두 로봇 각각 pause, armed 는 켜 둔다."""
    stack = Stack(tmp_path)
    try:
        stack.order()
        stack.until('MOVE_DROPOFF')
        stack.move('pinky1', 'MOVING', 'P5')
        stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
        stack.order('order2', 'side')
        stack.until('PICK', 'order2')
        stack.tick()
        stack.core.on_pose('pinky2', 0.4, -1.0, 0.0)
        views = stack.core.robots_view()
        assert (views['pinky2']['phase'], views['pinky2']['cargo_state']) == ('PICK', 'LOADING')
        assert views['pinky1']['cargo_state'] == 'LOADED'
        stack.core.set_mode('AUTO_HOLD')
        row = stack.vision('box_perched_on_rim', (0.2, -1.0))
        assert (row['judgment'], row['stop_scope']) == ('AMBIGUOUS', 'ROBOT')
        assert sorted((r['type'], r.get('robot_id')) for r in stack.stop_requests()) == [
            ('pause', 'pinky1'), ('pause', 'pinky2')]
        stack.tick()
        assert stack.scenario.armed is True and sorted(stack.core.holds) == ['pinky1', 'pinky2']
    finally:
        stack.close()


# 2. 이상한 관제 스냅샷(재검토 must_fix 4) -------------------------------------------------


@pytest.mark.parametrize('snapshot,op_state', [
    ({'holds': ['pinky1']}, 'PAUSED'),
    ({'holds': {'pinky1': {'reason': 'ESTOP'}}}, 'PAUSED'),
    ({'holds': {'pinky1': ['ESTOP']}}, 'PAUSED'),
    ({'holds': {'pinky1': 5}}, 'PAUSED'),
    ({'holds': {'pinky1': None}}, 'PAUSED'),
    ({'holds': {'pinky1': 'ESTOP'}}, 'ESTOP'),
], ids=['holds_list', 'reason_dict', 'reason_list', 'reason_int', 'reason_none', 'reason_str'])
def test_odd_holds_do_not_raise_in_the_snapshot_callback(clocked, snapshot, op_state):
    order = seat('o1', 'pinky1', 'CUSTOMER')
    clocked.core.on_status('pinky1', {'state': 'IDLE'})
    for _ in range(2):
        clocked.core.on_tasks(dict(snapshot, armed=True, orders=[order]))
    clocked.core.live()
    view = clocked.core.robots_view()['pinky1']
    assert view['op_state'] == op_state
    assert isinstance(view['hold_reason'], str)


@pytest.mark.parametrize('extra', [
    {'operator_completed': None}, {'completed': None}, {'operator_completed': {'x': 1}},
    {'completed': None, 'operator_completed': None, 'customer_timed_out': True,
     'stage': 'RETURN_EXIT', 'state': 'COMPLETED'},
])
def test_null_completed_lists_do_not_raise_in_the_snapshot_callback(clocked, extra):
    order = dict(seat('o1', 'pinky1', 'LEAVE_PICKUP'), **extra)
    clocked.core.on_status('pinky1', {'state': 'MOVING'})
    for _ in range(2):
        clocked.core.on_tasks({'armed': True, 'holds': {}, 'orders': [order]})
    clocked.core.live()
    assert clocked.core.robots_view()['pinky1']['cargo_state'] in ('EMPTY', 'LOADED')


# 3. 이상한 작업 요청(재검토 must_fix 3) ---------------------------------------------------


def adapter_on(store, sent, now):
    adapter = ManualAdapter(
        store, sent.append, ['vision', 'navigation', 'omx1', 'omx2', 'omx3'],
        {'ZB': [0.6, -0.15, -1.5], 'ZC': [-0.5, 0.3, 1.5]},
        lambda robot: {'pose_x': 0.6, 'pose_y': -0.15, 'pose_yaw': -1.5, 'speed_mps': 0.0},
        clock=lambda: now[0], auto_targets=['vision', 'navigation'])
    adapter.on_heartbeat({'session_id': 's1'})
    return adapter


def work_request(rid, seq, stage, target='vision', now=1000.0):
    return {'request_id': rid, 'order_id': 'o1', 'robot_id': 'pinky1', 'stage': stage,
            'target': target, 'action': 'x', 'sku': 'S', 'quantity': 1, 'attempt': 1,
            'route': ROUTES['lab_delivery_zb'], 'timeout_sec': 300.0, 'session_id': 's1',
            'seq': seq, 'issued_at': now, 'ttl_sec': 5.0}


@pytest.mark.parametrize('stage', [['MARKER'], {'a': 1}, 5, None],
                         ids=['list', 'dict', 'int', 'none'])
def test_non_string_stage_stays_pending_and_survives_a_restart(tmp_path, stage):
    path = tmp_path / 'm.sqlite3'
    store, sent, now = MonitorStore(path), [], [1000.0]
    adapter = adapter_on(store, sent, now)
    assert known_stage({'stage': stage}) is False
    assert adapter.on_request(work_request('r1', 1, stage)) is True
    assert store.work('r1')['state'] == 'PENDING' and sent == []
    now[0] += 1.0
    assert adapter.retry_auto() == []
    pending = adapter.pending()
    assert len(pending) == 1 and pending[0]['wait_reason'] == UNKNOWN_STAGE_REASON
    store.close()
    # 재시작: 같은 DB 로 어댑터를 다시 만들어도 pending()·retry_auto() 가 터지지 않는다.
    store, sent = MonitorStore(path), []
    again = adapter_on(store, sent, now)
    now[0] += 1.0
    assert again.retry_auto() == [] and sent == []
    assert [row['request_id'] for row in again.pending()] == ['r1']
    store.close()


@pytest.mark.parametrize('target', [['vision'], {'t': 'vision'}, 7, None])
def test_non_string_target_is_not_taken_and_does_not_raise(tmp_path, target):
    store, sent, now = MonitorStore(tmp_path / 'm.sqlite3'), [], [1000.0]
    adapter = adapter_on(store, sent, now)
    assert adapter.on_request(work_request('r1', 1, 'MARKER', target)) is False
    assert store.work('r1') is None and sent == []
    store.close()


def test_known_stage_answer_is_unchanged_next_to_a_bad_request(tmp_path):
    store, sent, now = MonitorStore(tmp_path / 'm.sqlite3'), [], [1000.0]
    adapter = adapter_on(store, sent, now)
    adapter.on_request(work_request('bad', 1, ['MARKER']))
    adapter.on_request(work_request('r2', 2, 'MARKER'))
    assert [r['request_id'] for r in sent] == ['r2'] and sent[0]['success'] is True
    store.close()


class Orders:
    """ConsoleApi 가 읽는 코어 자리. orders·arm_nodes·store 만 쓴다."""

    def __init__(self, store, orders, arm_nodes):
        self.store, self.orders, self.arm_nodes = store, orders, arm_nodes
        self.routes = ROUTES

    def _route(self, order):
        return dict(self.routes.get(order.get('route'), {}))


def test_console_arm_waits_and_recovery_options_skip_odd_values(tmp_path):
    store = MonitorStore(tmp_path / 'm.sqlite3')
    order = dict(route_order('o1', 'pinky1', ['PICK'], ['MOVE_PICKUP']), state='UNKNOWN',
                 request_id='w1')
    store.record_control('request', 'o1', 'w1', dict(work_request('w1', 1, 'PICK', ['omx2']),
                                                     wire_observed_at=1.0), 1.0)
    core = Orders(store, {'o1': order}, {'omx2': False})
    console = ConsoleApi(core, None, lambda job: job(), lambda rid: None)
    assert console._arm_waits() == []
    row = {'mission_id': 'o1', 'recovery': 'fail'}
    console._recovery_options(row)
    assert row['recovery_options'] == ['fail'] and row['recovery_note'] == ''
    store.close()


# 4. 지목 없던 사건에 새 로봇 잇기(재검토 should_fix M2) ----------------------------------


def loaded_driver(clocked, xy, speed=0.2):
    clocked.core.on_pose('pinky1', xy[0], xy[1], 0.0)
    clocked.core.on_speed('pinky1', speed)


def test_unlinked_events_are_not_pinned_on_a_loaded_robot_driving_past(tmp_path):
    clocked = Clocked(tmp_path, 'AUTO_HOLD')
    loaded = route_order('o1', 'pinky1', 'MOVE_DROPOFF', LOADED_DONE[:8])
    loaded_driver(clocked, (5.0, 5.0))
    clocked.feed([loaded], {'pinky1': {'state': 'MOVING', 'detail': 'ZC'}})
    rim = clocked.event('e1', 'box_perched_on_rim', (0.0, 0.0))
    floor = clocked.event('e2', 'box_on_floor', (1.0, 0.0))
    assert (rim['judgment'], floor['judgment']) == ('IGNORED', 'LANE_OBSTACLE')
    # 실린 로봇이 두 자리를 차례로 지나간다. 옛 사건을 그 로봇에 붙이지 않는다.
    for at, xy in ((1003.0, (0.05, 0.0)), (1005.0, (1.1, 0.0))):
        clocked.now[0] = at
        loaded_driver(clocked, xy)
        clocked.feed([loaded], {'pinky1': {'state': 'MOVING', 'detail': 'ZC'}})
        clocked.event(f'r{at}', 'box_perched_on_rim', (0.0, 0.0))
        clocked.event(f'f{at}', 'box_on_floor', (1.0, 0.0))
    rim, floor = clocked.store.event('e1'), clocked.store.event('e2')
    assert (rim['judgment'], rim['linked_robot_id'], rim['linked_mission_id']) == (
        'IGNORED', None, None)
    assert (floor['judgment'], floor['linked_robot_id'], floor['linked_mission_id']) == (
        'LANE_OBSTACLE', None, None)
    # 무시 사건이 그 로봇에 pause 를 부르지 않는다. 전체 정지 재요청(응답 없음)만 있다.
    assert [r.get('robot_id') for r in clocked.sent if r['type'] == 'pause'] == [None] * len(
        [r for r in clocked.sent if r['type'] == 'pause'])
    assert clocked.sent and all(r['client_request_id'] == 'cctv_e2' for r in clocked.sent)
    # 그 주문 복구로 무관한 장애물 사건이 닫히지 않는다.
    clocked.core.close_events('o1', 'kgh')
    assert clocked.store.event('e2')['ack_state'] == 'UNREAD'
    clocked.store.close()


def test_robot_that_parked_after_the_first_detection_is_not_adopted(clocked):
    loaded = route_order('o1', 'pinky1', 'DOCK_DROPOFF', LOADED_DONE[:8] + ['MOVE_DROPOFF'])
    loaded_driver(clocked, (5.0, 5.0))
    clocked.feed([loaded], {'pinky1': {'state': 'MOVING', 'detail': 'ZC'}})
    first = clocked.event('e1', 'box_perched_on_rim', (0.0, 0.0))
    assert first['judgment'] == 'IGNORED'
    clocked.now[0] += 2.0
    loaded_driver(clocked, (0.05, 0.0), speed=0.0)  # 감지 뒤에 와서 섰다
    clocked.feed([loaded], {'pinky1': {'state': 'HOLDING_ZONE', 'held_zone': 'C'}})
    for _ in range(3):
        clocked.now[0] += 5.0
        clocked.event(f'again{clocked.now[0]}', 'box_perched_on_rim', (0.0, 0.0))
    assert clocked.store.event('e1')['judgment'] == 'IGNORED'


def test_robot_standing_there_since_the_first_detection_is_adopted(clocked):
    marker = route_order('o1', 'pinky1', 'MARKER', ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP'])
    loaded_driver(clocked, (0.6, -0.15), speed=0.0)
    clocked.feed([marker], {'pinky1': {'state': 'HOLDING_ZONE', 'held_zone': 'B'}})
    first = clocked.event('e1', 'box_perched_on_rim', (0.65, -0.15))
    assert first['judgment'] == 'IGNORED'
    clocked.now[0] += 3.0
    clocked.feed([route_order('o1', 'pinky1', 'PICK', marker['completed'] + ['MARKER'])],
                 {'pinky1': {'state': 'HOLDING_ZONE', 'held_zone': 'B'}})
    again = clocked.event('e2', 'box_perched_on_rim', (0.65, -0.15))
    assert again['event_id'] == 'e1'
    assert (again['judgment'], again['linked_robot_id']) == ('LOAD_FAIL_PERCHED', 'pinky1')


def test_robot_named_in_the_first_ambiguous_judgment_is_adopted(clocked):
    """첫 감지 때 근처 로봇으로 적힌 로봇은 오도메트리가 없어도 잇는다."""
    a = route_order('o1', 'pinky1', 'LOAD', LOADED_DONE[:5])
    b = route_order('o2', 'pinky2', 'LOAD', LOADED_DONE[:5])
    clocked.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    clocked.core.on_pose('pinky2', 0.4, 0.0, 0.0)
    hold = {'state': 'HOLDING_ZONE', 'held_zone': 'B'}
    clocked.feed([a, b], {'pinky1': hold, 'pinky2': hold})
    first = clocked.event('e1', 'box_perched_on_rim', (0.2, 0.0))
    assert first['judgment'] == 'AMBIGUOUS'
    clocked.core.on_pose('pinky1', 3.0, 3.0, 0.0)
    clocked.feed([a, b], {'pinky1': hold, 'pinky2': hold})
    again = clocked.event('e2', 'box_perched_on_rim', (0.2, 0.0))
    assert (again['judgment'], again['linked_robot_id']) == ('LOAD_FAIL_PERCHED', 'pinky2')
    # 처음 대상(두 로봇)은 남는다. 정지 범위는 좁히지 않는다.
    assert sorted(json.loads(again['stop_targets_json'])) == ['pinky1', 'pinky2']


def test_rejudge_without_adopt_keeps_an_unlinked_event():
    opened = {'judgment': 'LANE_OBSTACLE', 'recommended_action': 'PAUSE', 'stop_scope': 'ALL',
              'linked_robot_id': None, 'stop_targets_json': '[]', 'robot_phase_at_event': ''}
    fresh = {'judgment': 'TRANSIT_DROP', 'recommended_action': 'PAUSE', 'stop_scope': 'ALL',
             'linked_robot_id': 'pinky1', 'linked_order_id': 'o1', 'stop_targets': ['pinky1'],
             'alarm_text': ''}
    assert rejudge(opened, fresh, 'X', adopt=False) is None
    assert rejudge(opened, fresh, 'X', adopt=True)['linked_robot_id'] == 'pinky1'


# 5. 잔류 화물 로봇의 경로 주문 수령(11-21 재검토 must_fix) ---------------------------------

ROUTE_RECEIPT_DONE = ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD',
                      'VERIFY_LOAD', 'LEAVE_PICKUP', 'MOVE_DROPOFF', 'PATH_EXIT', 'DOCK_DROPOFF',
                      'QR', 'PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD']


def test_route_receipt_on_a_robot_with_leftover_cargo_keeps_the_baseline_scope(clocked):
    """
    시간 초과로 잔류 화물이 남은 로봇이 경로 주문 수령(CUSTOMER)에 있으면 잔류 국면이다.

    11-20 전에는 하역 뒤 빈 로봇이라 바닥 상자가 LANE_OBSTACLE(PAUSE, ALL)였다.
    잔류 화물 때문에 하역(UNLOAD_FAIL, ROBOT)으로 보면 정지 범위가 좁아진다.
    """
    clocked.feed([O1_AT_CUSTOMER], {'pinky1': IDLE})
    clocked.feed([O1_TIMED_OUT], {'pinky1': IDLE})
    receipt = route_order('o2', 'pinky1', 'CUSTOMER', ROUTE_RECEIPT_DONE)
    clocked.feed([O1_TIMED_OUT, receipt], {'pinky1': IDLE})
    clocked.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    view = clocked.core.robots_view()['pinky1']
    assert view['residual_cargo']['order_id'] == 'o1' and view['phase'] == 'RESIDUAL'
    floor = judge({'vision_class': 'box_on_floor', 'map_x': 0.0, 'map_y': 0.2},
                  clocked.core.robots_view())
    assert floor['stop_scope'] == 'ALL' and floor['recommended_action'] == 'PAUSE'


def test_route_receipt_without_leftover_cargo_is_unchanged(clocked):
    clocked.feed([route_order('o2', 'pinky1', 'CUSTOMER', ROUTE_RECEIPT_DONE)], {'pinky1': IDLE})
    assert clocked.core.robots_view()['pinky1']['phase'] == 'UNLOADING'


@pytest.mark.parametrize('request_id', [['w1'], {'id': 'w1'}, 7])
def test_console_refresh_survives_odd_request_ids_while_an_arm_node_is_missing(
        tmp_path, request_id):
    """콘솔 갱신은 노드 타이머에서 돈다. omx2 노드가 없을 때 이상한 request_id 로 노드가 멈추면 안 된다."""
    store = MonitorStore(tmp_path / 'm.sqlite3')
    order = dict(route_order('o1', 'pinky1', 'PICK', ['MOVE_PICKUP']), request_id=request_id)
    core = Orders(store, {'o1': order}, {'omx2': False})
    core.live = lambda: {'missions': [{'mission_id': 'o1', 'recovery': None}]}
    console = ConsoleApi(core, None, lambda job: job(), lambda rid: None)
    console.refresh()
    assert console.cached['arm_waits'] == []
    store.close()
