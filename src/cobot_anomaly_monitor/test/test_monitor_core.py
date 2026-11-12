"""기록 시험. 스냅샷이 빠지거나 재시작해도 이력이 틀리면 실패해야 한다."""

from cobot_anomaly_monitor.monitor_core import camera_allowed, clean_event, MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
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
