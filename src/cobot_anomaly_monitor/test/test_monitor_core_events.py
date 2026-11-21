"""관제 경보·운영자 조치 기록, 보류 사유 표시, 재판정, DB 호환 시험(11-21)."""

import json
import sqlite3

from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
import pytest

ROUTES = {'wh': {'pickup': 'ZA', 'dropoff': 'ZC', 'pickup_arm': 'omx1', 'dropoff_arm': 'omx3',
                 'lane': 'main'}}
SEAT_DONE = ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD',
             'LEAVE_PICKUP', 'MOVE_CUSTOMER']


def order(stage, state='RUNNING', completed=(), robot='pinky1', order_id='o1', **extra):
    return dict({'order_id': order_id, 'route': 'wh', 'kind': 'delivery', 'sku': 'S',
                 'quantity': 1, 'robot_id': robot, 'stage': stage, 'state': state,
                 'completed': list(completed), 'detail': '', 'created_at': 1.0}, **extra)


@pytest.fixture
def store(tmp_path):
    item = MonitorStore(tmp_path / 'm.sqlite3')
    yield item
    item.close()


def clocked(store, robots=('pinky1',), mode='OBSERVE_ONLY'):
    now, sent = [10.0], []
    core = MonitorCore(store, ROUTES, list(robots), sent.append, mode, clock=lambda: now[0])
    return core, now, sent


def feed(core, *orders, holds=None):
    core.on_tasks({'armed': True, 'holds': holds or {}, 'orders': list(orders)})


def alarm(code, order_id='o1', robot='pinky1', event_id=1, detail='', at=10.0):
    return {'type': 'alarm', 'order_id': order_id, 'robot_id': robot, 'code': code,
            'detail': detail, 'event_id': event_id, 'recorded_at': at}


# G3·M3 관제 경보 ------------------------------------------------------------------------


def test_alarms_are_stored_shown_live_and_on_the_scenario(store):
    core, now, _ = clocked(store)
    feed(core, order('RETURN_HOME', completed=SEAT_DONE + ['CUSTOMER'], customer_timed_out=True))
    core.on_task_event(alarm('CUSTOMER_TIMEOUT', detail='300초 결제·회수 무응답'))
    core.on_task_event(alarm('CUSTOMER_TIMEOUT', detail='300초 결제·회수 무응답'))  # 재발행
    rows = core.alarms('o1')
    assert len(rows) == 1 and rows[0]['code'] == 'CUSTOMER_TIMEOUT'
    assert rows[0]['payload']['detail'] == '300초 결제·회수 무응답'
    assert core.live()['alarms'][0]['code'] == 'CUSTOMER_TIMEOUT'
    mission = store.scenario('o1')
    assert (mission['last_alarm_code'], mission['outcome']) == ('CUSTOMER_TIMEOUT', 'TIMEOUT')
    # 주문 이력(수신 원문)에도 보인다.
    kinds = [e['kind'] for e in store.wire_page('o1', 0)['events']]
    assert kinds == ['control_event']
    assert core.alarms() == core.alarms('o1') and core.alarms('other') == []


def test_alarm_before_the_first_snapshot_reaches_the_scenario_row(store):
    core, now, _ = clocked(store)
    core.on_task_event(alarm('ESTOP', detail='운영자 estop'))
    feed(core, order('MOVE_PICKUP', 'ESTOP'))
    assert store.scenario('o1')['last_alarm_code'] == 'ESTOP'
    assert store.scenario('o1')['last_alarm_detail'] == '운영자 estop'


def test_operator_events_are_stored_and_other_events_are_not(store):
    core, now, _ = clocked(store)
    events = [
        {'type': 'recovery', 'order_id': 'o1', 'operator': 'kgh', 'note': '현장 확인',
         'decision': 'fail', 'evidence': {'cargo_reconciled': True}, 'event_id': 2},
        {'type': 'operator_load_confirmed', 'order_id': 'o1', 'robot_id': 'pinky1',
         'confirmation': {'operator': 'kgh'}, 'event_id': 3},
        {'type': 'operator_load_confirmation_pending', 'order_id': 'o1', 'robot_id': 'pinky1',
         'event_id': 4},
        {'type': 'control_release_requested', 'robot_id': 'pinky1', 'reset_id': 'r1',
         'event_id': 5},
        {'type': 'control_released', 'robot_id': 'pinky1', 'event_id': 6},
        {'type': 'control_release_unconfirmed', 'robot_id': 'pinky1', 'event_id': 7},
        {'type': 'scenario', 'order': order('MOVE_PICKUP'), 'event_id': 8},
        {'type': 'inventory', 'sku': 'S', 'available': 3, 'event_id': 9},
    ]
    for item in events:
        core.on_task_event(item)
    stored = store.control_events()
    assert sorted(row['type'] for row in stored) == sorted(e['type'] for e in events[:6])
    recovery = next(row for row in stored if row['type'] == 'recovery')
    assert recovery['detail'] == '현장 확인' and recovery['order_id'] == 'o1'


def test_stop_unconfirmed_is_shown_on_the_robot_until_release(store):
    core, now, _ = clocked(store)
    core.on_status('pinky1', {'state': 'STOPPED'})
    feed(core, order('PICK', 'UNKNOWN'), holds={'pinky1': 'UNKNOWN'})
    core.on_task_event(alarm('STOP_UNCONFIRMED', detail='halt 발행 실패', event_id=11))
    view = core.robots_view()['pinky1']
    assert view['stop_unconfirmed']['detail'] == 'halt 발행 실패'
    # 재시작 뒤에도 기록에서 되살린다.
    again, _, _ = clocked(store)
    assert again.robots_view()['pinky1']['stop_unconfirmed']['order_id'] == 'o1'
    core.on_task_event({'type': 'control_released', 'robot_id': 'pinky1', 'event_id': 12,
                        'recorded_at': 11.0})
    assert core.robots_view()['pinky1']['stop_unconfirmed'] is None
    assert clocked(store)[0].robots_view()['pinky1']['stop_unconfirmed'] is None


def test_arm_nodes_are_shown_live(store):
    core, now, _ = clocked(store)
    assert core.live()['arm_nodes'] == {}
    core.set_arm_nodes({'omx2': False, 'omx3': 1})
    assert core.live()['arm_nodes'] == {'omx2': False, 'omx3': True}


# G4 보류 사유 ---------------------------------------------------------------------------


@pytest.mark.parametrize('holds,state,op_state', [
    ({'pinky1': 'ESTOP'}, 'ESTOP', 'ESTOP'),
    ({'pinky1': 'MANUAL'}, 'MANUAL', 'MANUAL'),
    ({'pinky1': 'UNKNOWN'}, 'UNKNOWN', 'UNKNOWN'),
    ({}, 'UNKNOWN', 'UNKNOWN'),
    ({'pinky1': 'PAUSED'}, 'PAUSED', 'PAUSED'),
    ({'pinky1': 'LINK_LOST'}, 'UNKNOWN', 'LINK_LOST'),
    ({'pinky1': 'RESET_UNCONFIRMED'}, 'RUNNING', 'RESET_UNCONFIRMED'),
    ({'pinky1': 'SOMETHING_NEW'}, 'RUNNING', 'PAUSED'),
])
def test_hold_reason_is_shown_as_the_robot_state(store, holds, state, op_state):
    core, now, _ = clocked(store)
    core.on_status('pinky1', {'state': 'STOPPED'})
    feed(core, order('PICK', state), holds=holds)
    view = core.robots_view()['pinky1']
    assert view['op_state'] == op_state and view['order_state'] == state
    assert view['hold_reason'] == holds.get('pinky1', '')


def test_hold_without_an_order_keeps_its_reason(store):
    core, now, _ = clocked(store)
    core.on_status('pinky1', {'state': 'IDLE'})
    feed(core, holds={'pinky1': 'RESET_UNCONFIRMED'})
    assert core.robots_view()['pinky1']['op_state'] == 'RESET_UNCONFIRMED'


def test_cctv_hold_reason_still_wins(store):
    core, now, _ = clocked(store)
    core.on_status('pinky1', {'state': 'STOPPED'})
    feed(core, order('LOAD'))
    store.set_hold_reason('o1', 'CCTV LOAD_FAIL_PERCHED e1')
    feed(core, order('LOAD', 'PAUSED'), holds={'pinky1': 'PAUSED'})
    assert core.robots_view()['pinky1']['op_state'] == 'HOLD_ANOMALY'


@pytest.mark.parametrize('age', [3.5, 10.0])
def test_stale_status_is_link_lost_but_keeps_the_last_driving(store, age):
    """통신이 끊겨도 로봇이 선 것은 아니다. 판정 입력은 11-20 전처럼 마지막 상태를 쓴다(D3)."""
    core, now, sent = clocked(store, mode='AUTO_HOLD')
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'P3'})
    feed(core, order('LEAVE_PICKUP', completed=['VERIFY_LOAD']))
    view = core.robots_view()['pinky1']
    assert (view['driving'], view['link_stale']) == (True, False)
    now[0] = 10.0 + age
    view = core.robots_view()['pinky1']
    assert (view['op_state'], view['link_stale'], view['status_age_sec']) == (
        'LINK_LOST', True, age)
    assert view['driving'] is True and view['phase'] == 'TRANSIT'
    # 마지막으로 MOVING 이던 로봇 옆 밟힘은 예전처럼 충돌 전체 정지다.
    row = core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_run_over',
                                'map_x': 0.05, 'map_y': 0.0})
    assert (row['judgment'], row['recommended_action'], row['stop_scope']) == (
        'RUN_OVER_COLLISION', 'ESTOP', 'ALL')
    assert [(r['type'], r.get('robot_id')) for r in sent] == [('estop', None)]


def test_stale_queue_wait_keeps_the_last_value(store):
    core, now, _ = clocked(store)
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_speed('pinky1', 0.0)
    core.on_status('pinky1', {'state': 'QUEUEING', 'detail': 'slot0'})
    feed(core, order('MOVE_PICKUP'))
    now[0] = 20.0
    view = core.robots_view()['pinky1']
    assert (view['queue_wait'], view['driving'], view['op_state']) == (True, True, 'LINK_LOST')
    # 대기 슬롯에 서 있던 로봇은 예전처럼 밟은 로봇으로 지목하지 않는다.
    row = core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_run_over',
                                'map_x': 0.05, 'map_y': 0.0})
    assert row['judgment'] == 'IGNORED'


def test_seat_customer_wait_is_wait_customer_not_idle(store):
    core, now, _ = clocked(store)
    core.on_status('pinky1', {'state': 'IDLE_WAIT', 'detail': 'P22'})
    feed(core, order('CUSTOMER', completed=SEAT_DONE))
    assert core.robots_view()['pinky1']['op_state'] == 'WAIT_CUSTOMER'
    # 경로 주문 CUSTOMER 는 그대로다(하차 구역에서 구역 토큰을 든 채).
    core.on_status('pinky1', {'state': 'HOLDING_ZONE', 'held_zone': 'C'})
    feed(core, order('CUSTOMER', completed=['MOVE_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD']))
    assert core.robots_view()['pinky1']['op_state'] == 'WAIT_ARM'


# 재판정 ---------------------------------------------------------------------------------


def test_arrange_drop_becomes_a_lane_stop_when_the_robot_drives_off(store):
    core, now, sent = clocked(store, mode='AUTO_HOLD')
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_status('pinky1', {'state': 'HOLDING_ZONE', 'held_zone': 'C'})
    arranging = order('ARRANGE', completed=SEAT_DONE + ['CUSTOMER', 'MOVE_ARRANGE'],
                      customer_declined=True)
    feed(core, arranging)
    event = {'camera_id': 'c', 'vision_class': 'box_on_floor', 'map_x': 0.3, 'map_y': 0.0}
    first = core.on_vision_event(dict(event, event_id='e1', detected_at=10.0))
    assert (first['judgment'], first['stop_scope']) == ('ARRANGE_FAIL', 'ROBOT')
    assert [r.get('robot_id') for r in sent] == ['pinky1']
    now[0] = 12.0
    core.on_status('pinky1', {'state': 'LEAVING_ZONE', 'detail': 'EXIT'})
    feed(core, order('LEAVE_ARRANGE', completed=arranging['completed'] + ['ARRANGE'],
                     customer_declined=True))
    again = core.on_vision_event(dict(event, event_id='e2', detected_at=12.0))
    assert again['event_id'] == 'e1'
    assert (again['judgment'], again['stop_scope']) == ('TRANSIT_DROP', 'ALL')
    assert again['judgment_history'] == 'ARRANGE_FAIL'
    assert again['robot_phase_at_event'] == 'LEAVE_ARRANGE|TRANSIT|LOADED'
    # 범위가 넓어졌으니 전체 정지를 새로 요청한다.
    assert [r.get('robot_id') for r in sent] == ['pinky1', None]
    assert again['control_action'] == 'PAUSE_SENT' and again['hold_seen'] == 0


# DB 호환 --------------------------------------------------------------------------------

OLD_SCENARIOS = """CREATE TABLE scenarios (
    mission_id TEXT PRIMARY KEY, route TEXT NOT NULL, kind TEXT NOT NULL,
    sku TEXT NOT NULL, quantity INTEGER NOT NULL, robot_id TEXT,
    load_arm_id TEXT NOT NULL DEFAULT '', unload_arm_id TEXT NOT NULL DEFAULT '',
    current_step_seq INTEGER NOT NULL DEFAULT 0,
    current_step_code TEXT NOT NULL DEFAULT 'NONE',
    current_stage TEXT NOT NULL DEFAULT '', cargo_state TEXT NOT NULL DEFAULT 'EMPTY',
    mission_state TEXT NOT NULL, hold_reason TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE cctv_anomaly_events (
    event_id TEXT PRIMARY KEY, detected_at REAL NOT NULL, last_seen REAL NOT NULL,
    repeat_count INTEGER NOT NULL DEFAULT 1, camera_id TEXT NOT NULL,
    vision_class TEXT NOT NULL, confidence REAL NOT NULL, bbox_json TEXT NOT NULL DEFAULT '[]',
    map_x REAL, map_y REAL, zone_id TEXT NOT NULL DEFAULT '',
    linked_robot_id TEXT, linked_mission_id TEXT,
    robot_step_at_event TEXT NOT NULL DEFAULT 'NONE',
    robot_cargo_at_event TEXT NOT NULL DEFAULT 'UNKNOWN',
    judgment TEXT NOT NULL, recommended_action TEXT NOT NULL,
    stop_scope TEXT NOT NULL DEFAULT 'ROBOT',
    stop_targets_json TEXT NOT NULL DEFAULT '[]', alarm_text TEXT NOT NULL DEFAULT '',
    control_action TEXT NOT NULL, control_detail TEXT NOT NULL DEFAULT '',
    ack_state TEXT NOT NULL DEFAULT 'UNREAD', resolved_by TEXT NOT NULL DEFAULT '',
    resolved_note TEXT NOT NULL DEFAULT '', resolved_at REAL,
    hold_seen INTEGER NOT NULL DEFAULT 0
);
INSERT INTO scenarios (mission_id, route, kind, sku, quantity, mission_state, created_at,
                       updated_at) VALUES ('old1', 'wh', 'delivery', 'S', 1, 'COMPLETED', 1, 1);
INSERT INTO cctv_anomaly_events (event_id, detected_at, last_seen, camera_id, vision_class,
    confidence, map_x, map_y, judgment, recommended_action, stop_scope, control_action)
    VALUES ('old_e', 1.0, 1.0, 'c', 'box_on_floor', 0.9, 0.3, 0.0, 'LANE_OBSTACLE', 'PAUSE',
            'ALL', 'OBSERVE_ONLY');
"""


def test_field_db_from_before_opens_and_gains_the_new_columns(tmp_path):
    path = tmp_path / 'field.sqlite3'
    db = sqlite3.connect(path)
    db.executescript(OLD_SCENARIOS)
    db.close()
    store = MonitorStore(path)
    columns = {row[1] for row in store.db.execute('PRAGMA table_info(scenarios)')}
    assert {'outcome', 'last_alarm_code', 'last_alarm_detail'} <= columns
    columns = {row[1] for row in store.db.execute('PRAGMA table_info(cctv_anomaly_events)')}
    assert {'robot_phase_at_event', 'judgment_history'} <= columns
    assert store.scenario('old1')['outcome'] == ''
    assert store.event('old_e')['judgment_history'] == ''
    # 옛 사건도 재감지로 다시 판정된다(국면 칸이 비어 있어도).
    now = [1.0]
    core = MonitorCore(store, ROUTES, ['pinky1'], lambda p: None, clock=lambda: now[0])
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_speed('pinky1', 0.0)  # 옛 사건(1.0) 때부터 그 자리에 서 있던 로봇만 새로 잇는다
    core.on_status('pinky1', {'state': 'HOLDING_ZONE', 'held_zone': 'A'})
    now[0] = 5.0
    feed(core, order('LOAD', completed=['PICK']))
    row = core.on_vision_event({'event_id': 'new_e', 'camera_id': 'c', 'vision_class':
                                'box_on_floor', 'map_x': 0.3, 'map_y': 0.0, 'detected_at': 5.0})
    assert row['event_id'] == 'old_e' and row['judgment'] == 'LOAD_FAIL_DROP'
    assert row['stop_scope'] == 'ALL' and row['judgment_history'] == 'LANE_OBSTACLE'
    assert json.loads(row['stop_targets_json']) == ['pinky1']
    store.close()
    MonitorStore(path).close()  # 두 번째 열기도 문제없다
