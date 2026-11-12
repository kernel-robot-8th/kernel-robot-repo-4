"""기록 시험. 스냅샷이 빠지거나 재시작해도 이력이 틀리면 실패해야 한다."""

import json
import sqlite3

from cobot_anomaly_monitor.monitor_core import camera_allowed, clean_event, MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore, SCHEMA
import pytest

ROUTES = {'wh': {'pickup': 'ZA', 'dropoff': 'ZC', 'pickup_arm': 'omx1', 'dropoff_arm': 'omx3',
                 'lane': 'main'}}


def order(stage, state='RUNNING', completed=(), robot='pinky1', kind='delivery'):
    return {'order_id': 'o1', 'route': 'wh', 'kind': kind, 'sku': 'S', 'quantity': 1,
            'robot_id': robot, 'stage': stage, 'state': state, 'completed': list(completed),
            'detail': '', 'created_at': 1.0}


@pytest.fixture
def store(tmp_path):
    item = MonitorStore(tmp_path / 'm.sqlite3')
    yield item
    item.close()


@pytest.fixture
def core(store):
    return MonitorCore(store, ROUTES, ['pinky1'], lambda payload: None, clock=lambda: 10.0)


def feed(core, item):
    core.on_tasks({'armed': True, 'holds': {}, 'orders': [item]})


def test_waiting_order_has_no_step(core, store):
    feed(core, order('MOVE_PICKUP', 'WAITING', robot=None))
    row = store.scenario('o1')
    assert row['current_step_seq'] == 0 and row['current_step_code'] == 'NONE'
    assert store.tasks('o1') == []


def test_steps_missed_between_snapshots_are_filled_in(core, store):
    feed(core, order('MOVE_PICKUP'))
    feed(core, order('PICK', completed=['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER']))
    assert [(t['step_seq'], t['task_state']) for t in store.tasks('o1')] == [
        (1, 'SUCCEEDED'), (2, 'SUCCEEDED'), (3, 'RUNNING')]


def test_safe_return_marks_the_failed_step_and_skipped_steps(core, store):
    done = ['MOVE_PICKUP', 'PICKUP_EXIT']
    feed(core, order('DOCK_PICKUP', completed=done))
    feed(core, dict(order('RETURN_HOME', completed=done), failure='정차 공차 초과'))
    assert [t['task_state'] for t in store.tasks('o1')] == [
        'SUCCEEDED', 'FAILED', 'SKIPPED', 'SKIPPED', 'SKIPPED', 'SKIPPED', 'RUNNING']
    assert store.scenario('o1')['cargo_state'] == 'EMPTY'


def test_step_does_not_go_back_when_status_lags(core, store):
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'ZA'})
    feed(core, order('MOVE_PICKUP'))
    assert store.scenario('o1')['current_step_seq'] == 2
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'P3'})
    feed(core, order('MOVE_PICKUP'))
    assert store.scenario('o1')['current_step_seq'] == 2


def test_return_order_swaps_the_zone_entry_target(core, store):
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'ZC'})
    feed(core, order('MOVE_PICKUP', kind='return'))
    assert store.scenario('o1')['current_step_seq'] == 2
    assert store.scenario('o1')['load_arm_id'] == 'omx3'


def test_restart_keeps_the_step_and_finished_rows(store):
    first = MonitorCore(store, ROUTES, ['pinky1'], lambda p: None, clock=lambda: 10.0)
    feed(first, order('LOAD', completed=['PICK']))
    feed(first, order('LEAVE_PICKUP', 'FAILED', completed=['PICK']))
    second = MonitorCore(store, ROUTES, ['pinky1'], lambda p: None, clock=lambda: 20.0)
    assert second.steps['o1'] == 4
    feed(second, order('LEAVE_PICKUP', 'FAILED', completed=['PICK']))
    assert store.scenario('o1')['updated_at'] == 10.0


def test_hold_reason_survives_a_late_running_snapshot(core, store):
    feed(core, order('LOAD'))
    store.set_hold_reason('o1', 'CCTV X e1')
    feed(core, order('LOAD'))
    assert store.scenario('o1')['hold_reason'] == 'CCTV X e1'
    feed(core, order('LOAD', 'PAUSED'))
    assert store.scenario('o1')['hold_reason'] == 'CCTV X e1'
    feed(core, order('MOVE_DROPOFF', 'RUNNING'))
    assert store.scenario('o1')['hold_reason'] == ''


def test_hold_without_cctv_reason_shows_paused(core):
    core.on_status('pinky1', {'state': 'IDLE'})
    core.on_tasks({'armed': False, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    assert core.robots_view()['pinky1']['op_state'] == 'PAUSED'


def test_live_state_table_follows_the_view(core, store):
    core.on_pose('pinky1', 1.0, 2.0, 0.5)
    core.on_speed('pinky1', 0.1)
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'P3'})
    feed(core, order('LEAVE_PICKUP', completed=['VERIFY_LOAD']))
    row = store.live_states()[0]
    assert (row['pose_x'], row['pose_yaw'], row['speed_mps']) == (1.0, 0.5, 0.1)
    assert row['cargo_state'] == 'LOADED' and row['active_step_code'] == 'TRANSIT_TO_STORE'
    assert row['op_state'] == 'MOVING' and row['last_waypoint'] == 'P3'


def test_same_event_id_is_recorded_once(core, store):
    event = {'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_on_floor', 'map_x': 0.0,
             'map_y': 0.0}
    core.on_vision_event(event)
    core.on_vision_event(event)
    assert len(store.events()) == 1 and store.events()[0]['repeat_count'] == 1


def test_resolved_event_no_longer_merges(core, store):
    event = {'camera_id': 'c', 'vision_class': 'box_on_floor', 'map_x': 0.0, 'map_y': 0.0}
    core.on_vision_event(dict(event, event_id='e1'))
    core.acknowledge('e1', 'RESOLVED', 'kgh')
    core.on_vision_event(dict(event, event_id='e2'))
    assert len(store.events()) == 2


def test_failed_stop_is_recorded(store):
    sent = []
    core = MonitorCore(store, ROUTES, ['pinky1'], sent.append, 'AUTO_HOLD', clock=lambda: 10.0)
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'P3'})
    feed(core, order('LEAVE_PICKUP', completed=['VERIFY_LOAD']))
    row = core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_on_floor',
                                'map_x': 0.1, 'map_y': 0.0})
    assert row['control_action'] == 'PAUSE_SENT'
    core.on_task_event({'type': 'reply', 'request_id': sent[0]['request_id'], 'status': 404,
                        'body': {'detail': '등록되지 않은 로봇'}})
    assert store.event('e1')['control_action'] == 'PAUSE_FAILED'


def full_stop(store, body, status=202):
    """주문 없이 바닥 상자를 넣어 전체 정지를 보내고 관제 응답을 돌려준다."""
    sent = []
    core = MonitorCore(store, ROUTES, ['pinky1'], sent.append, 'AUTO_HOLD', clock=lambda: 10.0)
    row = core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_on_floor',
                                'map_x': 0.1, 'map_y': 0.0})
    assert row['judgment'] == 'LANE_OBSTACLE' and row['control_action'] == 'PAUSE_SENT'
    assert len(sent) == 1 and sent[0]['type'] == 'pause' and 'robot_id' not in sent[0]
    core.on_task_event({'type': 'reply', 'request_id': sent[0]['request_id'], 'status': status,
                        'body': body})
    return store.event('e1')


def test_full_stop_reply_is_recorded_under_the_all_key(store):
    row = full_stop(store, {'armed': False, 'robot_id': None, 'robots': ['pinky1']})
    assert row['control_action'] == 'PAUSE_ACCEPTED'
    assert list(json.loads(row['control_detail'])) == ['ALL']


@pytest.mark.parametrize('body', [{'armed': True, 'robot_id': None}, {}, None])
def test_full_stop_accepted_without_armed_off_is_a_failure(store, body):
    assert full_stop(store, body)['control_action'] == 'PAUSE_FAILED'


def test_full_stop_refused_is_a_failure(store):
    assert full_stop(store, {'detail': 'x'}, 503)['control_action'] == 'PAUSE_FAILED'


def test_full_stop_writes_the_reason_on_every_active_order(store):
    sent = []
    core = MonitorCore(store, ROUTES, ['pinky1', 'pinky2'], sent.append, 'AUTO_HOLD',
                       clock=lambda: 10.0)
    core.on_tasks({'armed': True, 'holds': {}, 'orders': [
        order('MOVE_DROPOFF'), dict(order('MOVE_PICKUP', robot='pinky2'), order_id='o2'),
        dict(order('RETURN_HOME', 'COMPLETED', robot='pinky2'), order_id='o3')]})
    core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_on_floor',
                          'map_x': 5.0, 'map_y': 5.0})
    assert len(sent) == 1
    assert store.scenario('o1')['hold_reason'] == 'CCTV LANE_OBSTACLE e1'
    assert store.scenario('o2')['hold_reason'] == 'CCTV LANE_OBSTACLE e1'
    assert store.scenario('o3')['hold_reason'] == ''


def test_existing_db_gets_the_stop_scope_column(tmp_path):
    path = tmp_path / 'old.sqlite3'
    old_schema = SCHEMA.replace("    stop_scope TEXT NOT NULL DEFAULT 'ROBOT',\n", '').replace(
        ',\n    hold_seen INTEGER NOT NULL DEFAULT 0', '')
    assert 'stop_scope' not in old_schema and 'hold_seen' not in old_schema
    db = sqlite3.connect(path)
    db.executescript(old_schema)
    db.execute(
        'INSERT INTO cctv_anomaly_events (event_id, detected_at, last_seen, camera_id, '
        'vision_class, confidence, judgment, recommended_action, control_action) '
        "VALUES ('old', 1.0, 1.0, 'c', 'box_on_floor', 0.9, 'LANE_OBSTACLE', 'NONE', 'NONE')")
    db.commit()
    db.close()
    for _ in range(2):  # 두 번째 시작에서 다시 더하려다 실패하지 않아야 한다.
        store = MonitorStore(path)
        assert store.event('old')['stop_scope'] == 'ROBOT'
        assert store.event('old')['hold_seen'] == 0
        store.close()
    store = MonitorStore(path)
    core = MonitorCore(store, ROUTES, ['pinky1'], lambda payload: None, clock=lambda: 10.0)
    row = core.on_vision_event({'event_id': 'new', 'camera_id': 'c',
                                'vision_class': 'box_on_floor', 'map_x': 0.0, 'map_y': 0.0})
    assert row['stop_scope'] == 'ALL' and len(store.events()) == 2
    store.close()


def snapshot(state='RUNNING', armed=True, holds=()):
    return {'armed': armed, 'holds': dict.fromkeys(holds, 'PAUSE'),
            'orders': [order('LEAVE_PICKUP', state, completed=['VERIFY_LOAD'])]}


def stopped(store, vision_class='box_on_floor', status=202, body=None):
    """주행 중 로봇 옆 이벤트로 정지를 보내고 응답까지 받은 코어를 돌려준다."""
    sent = []
    core = MonitorCore(store, ROUTES, ['pinky1'], sent.append, 'AUTO_HOLD', clock=lambda: 10.0)
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'P3'})
    core.on_tasks(snapshot())
    core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': vision_class,
                          'map_x': 0.1, 'map_y': 0.0})
    core.on_task_event({'type': 'reply', 'request_id': sent[0]['request_id'], 'status': status,
                        'body': {'armed': 'robot_id' in sent[0]} if body is None else body})
    return core


def test_robot_event_closes_when_the_order_leaves_the_hold(store):
    core = stopped(store, 'box_perched_on_rim')
    assert store.event('e1')['stop_scope'] == 'ROBOT'
    core.on_tasks(snapshot())  # 정지 전 스냅샷이 늦게 온 경우
    assert store.event('e1')['ack_state'] == 'UNREAD' and store.event('e1')['hold_seen'] == 0
    core.on_tasks(snapshot('PAUSED', holds=['pinky1']))
    assert store.event('e1')['ack_state'] == 'UNREAD' and store.event('e1')['hold_seen'] == 1
    core.on_tasks(snapshot())
    row = store.event('e1')
    assert (row['ack_state'], row['resolved_by']) == ('RESOLVED', 'fleet')
    assert row['resolved_at'] == 10.0


@pytest.mark.parametrize('state', ['COMPLETED', 'FAILED'])
def test_robot_event_closes_when_the_order_ends(store, state):
    core = stopped(store, 'box_perched_on_rim')
    core.on_tasks(snapshot('ESTOP', holds=['pinky1']))
    core.on_tasks(snapshot(state))
    assert store.event('e1')['ack_state'] == 'RESOLVED'


def test_full_stop_event_needs_armed_on_no_holds_and_no_blocked_order(store):
    core = stopped(store)
    assert store.event('e1')['stop_scope'] == 'ALL'
    core.on_tasks(snapshot())  # 정지 전 스냅샷
    assert store.event('e1')['hold_seen'] == 0
    for item in (snapshot('PAUSED', False, ['pinky1']), snapshot('PAUSED', True, ['pinky1']),
                 snapshot('PAUSED', True), snapshot('RUNNING', True, ['pinky1']),
                 snapshot('RUNNING', False), dict(snapshot(), armed=None)):
        core.on_tasks(item)
        assert store.event('e1')['ack_state'] == 'UNREAD' and store.event('e1')['hold_seen'] == 1
    core.on_tasks(snapshot())
    assert store.event('e1')['ack_state'] == 'RESOLVED'
    assert store.event('e1')['resolved_by'] == 'fleet'


def test_event_closes_after_a_monitor_restart(store):
    stopped(store).on_tasks(snapshot('PAUSED', False, ['pinky1']))
    assert store.event('e1')['hold_seen'] == 1
    # 재시작한 코어는 메모리가 비어 있다. DB의 열린 사건과 스냅샷만으로 닫아야 한다.
    core = MonitorCore(store, ROUTES, ['pinky1'], lambda payload: None, clock=lambda: 20.0)
    core.on_tasks(snapshot('PAUSED', False, ['pinky1']))
    assert store.event('e1')['ack_state'] == 'UNREAD'
    core.on_tasks(snapshot())
    row = store.event('e1')
    assert (row['ack_state'], row['resolved_by']) == ('RESOLVED', 'fleet')
    assert row['resolved_at'] == 20.0


def test_restart_before_the_hold_was_seen_still_waits_for_it(store):
    stopped(store)
    core = MonitorCore(store, ROUTES, ['pinky1'], lambda payload: None, clock=lambda: 20.0)
    core.on_tasks(snapshot())
    assert store.event('e1')['ack_state'] == 'UNREAD'


def test_refused_stop_is_left_for_the_operator(store):
    core = stopped(store, status=503, body={'detail': 'x'})
    assert store.event('e1')['control_action'] == 'PAUSE_FAILED'
    core.on_tasks(snapshot('PAUSED', False, ['pinky1']))
    core.on_tasks(snapshot())
    assert store.event('e1')['ack_state'] == 'UNREAD'


def test_closed_event_lets_the_same_spot_stop_again(store):
    core = stopped(store)
    sent = []
    core.send = sent.append
    event = {'camera_id': 'c', 'vision_class': 'box_on_floor', 'map_x': 0.1, 'map_y': 0.0}
    core.on_tasks(snapshot('PAUSED', False, ['pinky1']))
    assert core.on_vision_event(dict(event, event_id='e2'))['event_id'] == 'e1' and sent == []
    core.on_tasks(snapshot())
    row = core.on_vision_event(dict(event, event_id='e3'))
    assert row['event_id'] == 'e3' and row['control_action'] == 'PAUSE_SENT'
    assert len(sent) == 1 and 'robot_id' not in sent[0]


def test_unknown_mode_is_refused(store):
    with pytest.raises(ValueError):
        MonitorCore(store, ROUTES, [], lambda p: None, 'OFF')


@pytest.mark.parametrize('raw', [None, [], {'event_id': 'e'},
                                 {'event_id': 'e', 'camera_id': 'c', 'vision_class': 1},
                                 {'event_id': 'e', 'camera_id': 'c', 'vision_class': 'x',
                                  'confidence': 'high'}])
def test_bad_events_are_refused(raw):
    with pytest.raises(ValueError):
        clean_event(raw, 1.0)


@pytest.mark.parametrize('xy', [(None, 1.0), (1.0, None), (float('nan'), 1.0), (True, 1.0)])
def test_half_or_invalid_position_becomes_no_position(xy):
    event = clean_event({'event_id': 'e', 'camera_id': 'c', 'vision_class': 'x', 'map_x': xy[0],
                         'map_y': xy[1]}, 1.0)
    assert event['map_x'] is None and event['map_y'] is None


def test_camera_policy_keeps_sim_events_off_the_field():
    assert camera_allowed('ceil_cam', 'field') and not camera_allowed('sim_ceil_cam', 'field')
    assert camera_allowed('sim_ceil_cam', 'sim') and not camera_allowed('ceil_cam', 'sim')
    with pytest.raises(ValueError):
        camera_allowed('ceil_cam', 'other')


EVENT = {'camera_id': 'c', 'vision_class': 'box_on_floor', 'map_x': 0.1, 'map_y': 0.0}


def clocked(store, mode='AUTO_HOLD', robots=('pinky1',)):
    """시각을 바꿀 수 있는 코어, 보낸 요청, 요청을 보낸 시각, 시계를 돌려준다."""
    now, sent, times = [10.0], [], []

    def send(payload):
        sent.append(payload)
        times.append(now[0])
    core = MonitorCore(store, ROUTES, list(robots), send, mode, clock=lambda: now[0])
    return core, sent, times, now


def redetect(core, now, at, **extra):
    now[0] = at
    return core.on_vision_event(dict(EVENT, event_id=f'e{at}', detected_at=at, **extra))


def test_stop_that_never_shows_up_is_sent_again_with_growing_gaps(store):
    core, sent, times, now = clocked(store)
    first = redetect(core, now, 10.0)
    for step in range(1, 60):  # 감지기는 5초마다 다시 낸다. 응답도 스냅샷도 오지 않는 경우다.
        assert redetect(core, now, 10.0 + 5 * step)['event_id'] == first['event_id']
    # 간격은 5초에서 두 배씩 늘고 60초에서 멈춘다.
    assert times == [10.0, 15.0, 25.0, 45.0, 85.0, 145.0, 205.0, 265.0]
    assert all('robot_id' not in item and item['type'] == 'pause' for item in sent)
    assert len(store.events()) == 1


def test_refused_stop_is_sent_again_and_stops_once_the_hold_is_seen(store):
    core, sent, times, now = clocked(store)
    redetect(core, now, 10.0)
    core.on_task_event({'type': 'reply', 'request_id': sent[0]['request_id'], 'status': 503,
                        'body': {'detail': 'x'}})
    assert store.event('e10.0')['control_action'] == 'PAUSE_FAILED'
    assert redetect(core, now, 12.0)['control_action'] == 'PAUSE_FAILED' and len(sent) == 1
    assert redetect(core, now, 15.0)['control_action'] == 'PAUSE_SENT' and len(sent) == 2
    core.on_task_event({'type': 'reply', 'request_id': sent[1]['request_id'], 'status': 202,
                        'body': {'armed': False}})
    assert store.event('e10.0')['control_action'] == 'PAUSE_ACCEPTED'
    core.on_tasks({'armed': False, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    assert store.event('e10.0')['hold_seen'] == 1
    for at in (60.0, 200.0, 400.0):
        redetect(core, now, at)
    assert len(sent) == 2 and len(store.events()) == 1


def test_restart_sends_an_unseen_stop_again_on_the_next_detection(store):
    core, sent, times, now = clocked(store)
    redetect(core, now, 10.0)
    again, sent_again, _, now = clocked(store)
    redetect(again, now, 12.0)
    assert len(sent_again) == 1 and store.event('e10.0')['repeat_count'] == 2


@pytest.mark.parametrize('scope', ['ALL', 'ROBOT'])
def test_observed_event_is_stopped_when_seen_again_in_auto_hold(store, scope):
    core, sent, times, now = clocked(store, 'OBSERVE_ONLY')
    extra = {}
    if scope == 'ROBOT':
        core.on_pose('pinky1', 0.0, 0.0, 0.0)
        core.on_tasks({'armed': True, 'holds': {}, 'orders': [order('LOAD')]})
        extra = {'vision_class': 'box_perched_on_rim'}
    first = redetect(core, now, 10.0, **extra)
    assert first['control_action'] == 'OBSERVE_ONLY' and first['stop_scope'] == scope
    redetect(core, now, 15.0, **extra)
    assert sent == []
    core.set_mode('AUTO_HOLD')
    assert sent == []  # 모드만 바꿔서는 보내지 않는다. 다시 감지돼야 한다.
    row = redetect(core, now, 20.0, **extra)
    assert row['event_id'] == first['event_id'] and row['control_action'] == 'PAUSE_SENT'
    assert [item.get('robot_id') for item in sent] == [None if scope == 'ALL' else 'pinky1']
    if scope == 'ROBOT':
        assert store.scenario('o1')['hold_reason'] == 'CCTV LOAD_FAIL_PERCHED e10.0'


def test_already_held_target_is_not_stopped_again(store):
    core, sent, times, now = clocked(store)
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_tasks({'armed': True, 'holds': {}, 'orders': [order('LOAD')]})
    redetect(core, now, 10.0, vision_class='box_perched_on_rim')
    # 주문이 스냅샷에서 빠져 정지 확인(hold_seen)은 못 했지만 대상은 서 있다.
    core.on_tasks({'armed': True, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    assert store.event('e10.0')['hold_seen'] == 0
    redetect(core, now, 20.0, vision_class='box_perched_on_rim')
    assert len(sent) == 1


def robot_stop(store):
    core = stopped(store, 'box_perched_on_rim')
    assert store.event('e1')['linked_mission_id'] == 'o1'
    return core


def test_robot_event_whose_order_vanished_stays_open_while_the_robot_is_held(store):
    core = robot_stop(store)
    core.on_tasks(snapshot('PAUSED', holds=['pinky1']))
    assert store.event('e1')['hold_seen'] == 1
    core.on_tasks({'armed': True, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    assert store.event('e1')['ack_state'] == 'UNREAD'
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    assert store.event('e1')['ack_state'] == 'RESOLVED'


def test_robot_event_is_not_confirmed_by_a_hold_when_its_order_is_gone(store):
    core = robot_stop(store)
    # 주문이 사라진 스냅샷의 보류는 이 사건의 정지인지 알 수 없다. 확인으로 치지 않는다.
    core.on_tasks({'armed': True, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    row = store.event('e1')
    assert (row['hold_seen'], row['ack_state']) == (0, 'UNREAD')


def test_robot_event_without_an_order_follows_the_target_hold(store):
    core, sent, times, now = clocked(store)
    core.on_pose('pinky1', 0.0, 0.0, 0.0)
    core.on_tasks({'armed': True, 'holds': {}, 'orders': [order('LOAD')]})
    redetect(core, now, 10.0, vision_class='box_perched_on_rim')
    store.db.execute('UPDATE cctv_anomaly_events SET linked_mission_id=NULL')
    core.on_task_event({'type': 'reply', 'request_id': sent[0]['request_id'], 'status': 202,
                        'body': {}})
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    assert store.event('e10.0')['ack_state'] == 'UNREAD'
    core.on_tasks({'armed': True, 'holds': {'pinky1': 'PAUSE'}, 'orders': []})
    assert store.event('e10.0')['hold_seen'] == 1
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    assert store.event('e10.0')['ack_state'] == 'RESOLVED'


def test_full_stop_is_not_confirmed_by_armed_off_alone_before_the_reply(store):
    core, sent, times, now = clocked(store, robots=('pinky1', 'pinky2'))
    redetect(core, now, 10.0)
    assert store.event('e10.0')['control_action'] == 'PAUSE_SENT'
    # 다른 사유로 armed가 꺼져 있고 한 대만 보류 중인 옛 스냅샷이다.
    core.on_tasks({'armed': False, 'holds': {'pinky2': 'PAUSE'}, 'orders': []})
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    row = store.event('e10.0')
    assert (row['hold_seen'], row['ack_state']) == (0, 'UNREAD')
    # 응답이 없어도 전 로봇 보류가 보이면 정지로 본다. 풀리면 닫는다.
    core.on_tasks({'armed': False, 'holds': {'pinky1': 'PAUSE', 'pinky2': 'PAUSE'}, 'orders': []})
    assert store.event('e10.0')['hold_seen'] == 1
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    assert store.event('e10.0')['ack_state'] == 'RESOLVED'


def test_recovery_check_reads_only_stop_events(store, monkeypatch):
    core, sent, times, now = clocked(store, 'OBSERVE_ONLY')
    for index in range(5):
        redetect(core, now, 10.0 + index, map_x=float(index))
    core.set_mode('AUTO_HOLD')
    redetect(core, now, 20.0, map_x=9.0)
    assert len(store.open_events()) == 6
    monkeypatch.setattr(store, 'open_events', None)  # 전체 목록을 읽으면 여기서 터진다.
    core.on_tasks({'armed': True, 'holds': {}, 'orders': []})
    assert [row['event_id'] for row in store.open_stop_events(('PAUSE_SENT',))] == ['e20.0']


def test_column_added_by_another_process_in_between_is_not_an_error(tmp_path, monkeypatch):
    path = tmp_path / 'old.sqlite3'
    db = sqlite3.connect(path)
    db.executescript(SCHEMA.replace(',\n    hold_seen INTEGER NOT NULL DEFAULT 0', ''))
    db.close()
    write = MonitorStore._write

    def raced(self, query, *args):
        if query.startswith('ALTER'):  # 확인과 추가 사이에 다른 프로세스가 먼저 더했다.
            other = sqlite3.connect(path)
            other.execute(query)
            other.commit()
            other.close()
        write(self, query, *args)
    monkeypatch.setattr(MonitorStore, '_write', raced)
    store = MonitorStore(path)
    assert 'hold_seen' in [row[1] for row in store.db.execute(
        'PRAGMA table_info(cctv_anomaly_events)')]
    store.close()


def test_other_schema_errors_still_stop_the_start(tmp_path, monkeypatch):
    path = tmp_path / 'old.sqlite3'
    db = sqlite3.connect(path)
    db.executescript(SCHEMA.replace(',\n    hold_seen INTEGER NOT NULL DEFAULT 0', ''))
    db.close()

    def broken(self, query, *args):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(MonitorStore, '_write', broken)
    with pytest.raises(sqlite3.OperationalError):
        MonitorStore(path)
