"""TC-SCN-01~07. 팀 ScenarioService·ControlAPI를 그대로 돌리며 기록과 조치를 확인한다."""

import json

from harness import POINTS, Stack
import pytest

EVIDENCE = {'base_stopped': True, 'arms_safe': True, 'cargo_reconciled': True,
            'resources_clear': True}
ZA = POINTS['ZA'][:2]


@pytest.fixture
def stack(tmp_path):
    item = Stack(tmp_path)
    yield item
    item.close()


def compact(values):
    return [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]


def resolve(stack, decision, order_id='order1'):
    return stack.control(type='resolve', order_id=order_id, operator='kgh', note='현장 확인',
                         decision=decision, evidence=EVIDENCE)


def test_tc_scn_01_full_order_records_seven_steps_and_cargo(stack):
    stack.order()
    for _ in range(300):
        stack.step()
        if stack.current()['state'] == 'COMPLETED':
            break
    stack.tick()
    assert stack.current()['state'] == 'COMPLETED'
    views = [v['pinky1'] for v in stack.history if v['pinky1']['order_id']]
    assert compact([v['step_seq'] for v in views if v['step_seq']]) == [1, 2, 3, 4, 5, 6, 7]
    assert compact([v['cargo_state'] for v in views]) == [
        'EMPTY', 'LOADING', 'LOADED', 'UNLOADING', 'EMPTY']
    tasks = stack.store.tasks('order1')
    assert [t['step_seq'] for t in tasks] == [1, 2, 3, 4, 5, 6, 7]
    assert all(t['task_state'] == 'SUCCEEDED' and t['finished_at'] for t in tasks)
    assert [t['actor_id'] for t in tasks] == ['pinky1', 'pinky1', 'omx1', 'pinky1', 'pinky1',
                                              'omx3', 'pinky1']
    mission = stack.store.scenario('order1')
    assert mission['mission_state'] == 'COMPLETED' and mission['current_step_seq'] == 7
    assert [p['command'] for _, p in stack.gateway.sent] == [
        'zone:ZA', 'leave', 'zone:ZC', 'leave', 'home']
    results = [json.loads(r['result_json']) for r in stack.store.works('APPROVED')]
    assert len(results) == 13
    assert all(r['data']['manual'] is True and r['data']['operator'] == 'kgh' for r in results)


def test_tc_scn_02_perched_while_loading_observe_only_records_and_keeps_going(stack):
    stack.order()
    stack.until('LOAD')
    stack.tick()
    row = stack.vision('box_perched_on_rim', ZA)
    assert row['judgment'] == 'LOAD_FAIL_PERCHED' and row['linked_robot_id'] == 'pinky1'
    assert row['robot_step_at_event'] == 'ARM_LOADING'
    assert row['robot_cargo_at_event'] == 'LOADING'
    assert row['control_action'] == 'OBSERVE_ONLY'
    assert stack.stop_requests() == []
    stack.until('LEAVE_PICKUP')


def test_tc_scn_02_perched_while_loading_auto_hold_pauses_once_and_blocks_departure(stack):
    stack.order()
    load = stack.until('LOAD')
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_perched_on_rim', ZA)
    stack.tick(5.0)
    again = stack.vision('box_perched_on_rim', ZA)
    assert again['event_id'] == first['event_id'] and again['repeat_count'] == 2
    assert [r['robot_id'] for r in stack.stop_requests()] == ['pinky1']
    assert stack.store.event(first['event_id'])['control_action'] == 'PAUSE_ACCEPTED'
    assert stack.current()['state'] == 'PAUSED' and stack.scenario.armed is False
    stack.adapter.approve(load['request_id'], 'kgh')
    for _ in range(30):
        stack.tick()
    order = stack.current()
    assert order['stage'] == 'LOAD' and 'VERIFY_LOAD' not in order['completed']
    mission = stack.store.scenario('order1')
    assert mission['mission_state'] == 'PAUSED'
    assert mission['hold_reason'].startswith('CCTV LOAD_FAIL_PERCHED')
    assert stack.core.robots_view()['pinky1']['op_state'] == 'HOLD_ANOMALY'
    assert stack.store.tasks('order1')[2]['task_state'] == 'HOLD_ANOMALY'


def test_tc_scn_03_floor_box_matches_the_loaded_driver_not_the_idle_robot(stack):
    stack.order()
    order = stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    stack.core.on_pose('pinky2', 0.1, -1.0, 0.0)
    row = stack.vision('box_on_floor', (0.2, -1.0))
    assert row['judgment'] == 'TRANSIT_DROP'
    assert row['linked_robot_id'] == 'pinky1' and row['linked_mission_id'] == order['order_id']
    assert row['robot_step_at_event'] == 'TRANSIT_TO_STORE'
    assert row['robot_cargo_at_event'] == 'LOADED'
    assert json.loads(row['stop_targets_json']) == ['pinky1']


def test_drop_during_qr_pauses_the_docked_robot(stack):
    stack.order()
    stack.until('QR')
    stack.tick()
    assert stack.core.robots_view()['pinky1']['driving'] is False
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (POINTS['ZC'][0] + 0.2, POINTS['ZC'][1]))
    assert row['judgment'] == 'TRANSIT_DROP'
    assert [r['robot_id'] for r in stack.stop_requests()] == ['pinky1']
    stack.tick()
    assert stack.current()['state'] == 'PAUSED'


def test_tc_scn_04_observe_only_sends_nothing(stack):
    stack.order()
    stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    assert stack.vision('box_on_floor', (0.1, -1.0))['control_action'] == 'OBSERVE_ONLY'
    assert stack.requests == [] and stack.current()['state'] == 'RUNNING'


def test_tc_scn_04_driving_stage_resumes_after_arm(stack):
    stack.order()
    stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (0.1, -1.0))
    stack.tick()
    assert stack.current()['state'] == 'PAUSED'
    assert stack.live_mission()['recovery'] == 'resume'
    status, body = resolve(stack, 'resume')
    assert status == 400 and '가동 허용' in body['detail']
    assert stack.control(type='arm', armed=True, source='test')[0] == 200
    assert resolve(stack, 'resume')[0] == 200
    stack.tick()
    assert stack.current()['state'] == 'RUNNING'
    assert stack.store.scenario('order1')['hold_reason'] == ''
    assert stack.store.event(row['event_id'])['ack_state'] == 'RESOLVED'
    stack.until('PATH_EXIT')
    assert 'pinky1' in stack.gateway.releases


def test_tc_scn_04_loading_stage_only_fails(stack):
    stack.order()
    stack.until('LOAD')
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    assert stack.live_mission()['recovery'] == 'fail'
    stack.control(type='arm', armed=True, source='test')
    status, body = resolve(stack, 'resume')
    assert status == 400 and '재피킹' in body['detail']
    assert resolve(stack, 'fail')[0] == 200
    stack.tick()
    assert stack.store.scenario('order1')['mission_state'] == 'FAILED'
    assert stack.store.tasks('order1')[2]['task_state'] == 'FAILED'


def test_tc_scn_05_fail_keeps_the_zone_until_arm_and_leave(stack):
    stack.order()
    stack.until('LOAD')
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    assert resolve(stack, 'fail')[0] == 200
    stack.tick()
    assert stack.core.robots_view()['pinky1']['zone'] == 'ZONE_A'
    assert stack.status['pinky1']['held_zone'] == 'A'
    assert stack.control(type='create', robot_id='pinky1', operation='leave')[0] == 423
    assert stack.control(type='arm', armed=True, source='test')[0] == 200
    status, body = stack.control(type='create', robot_id='pinky1', operation='leave')
    assert status == 202
    stack.tick()
    assert stack.gateway.sent[-1][1]['command'] == 'leave'
    stack.status['pinky1'].update(state='IDLE_WAIT', held_zone=None, detail='')
    stack.fleet.on_status('pinky1', {'command_id': body['task_id'], 'state': 'DONE',
                                     'task_finished': True})
    stack.tick()
    assert stack.core.robots_view()['pinky1']['zone'] == 'HOME'


def test_console_refuses_other_create_operations(stack):
    assert stack.control(type='create', robot_id='pinky1', operation='raw')[0] == 400
    assert stack.requests == []


def test_debug_move_goes_through_fleet_control(stack):
    stack.tick()
    status, body = stack.control(type='create', robot_id='pinky2', operation='goto',
                                 points=['P1', 'P2'])
    assert status == 202 and body['command'] == 'goto:P1,P2'
    stack.tick()
    assert stack.gateway.sent[-1][0] == 'pinky2'
    assert stack.gateway.sent[-1][1]['command'] == 'goto:P1,P2'


def test_zone_then_leave_returns_the_token(stack):
    stack.tick()
    assert stack.control(type='create', robot_id='pinky1', operation='zone',
                         points=['ZA'])[0] == 202
    stack.tick()
    command = stack.gateway.sent[-1][1]
    stack.status['pinky1'].update(state='HOLDING_ZONE', held_zone='A', detail='ZA')
    stack.core.on_zone_status('A:occupied_by:pinky1')
    stack.fleet.on_status('pinky1', {'command_id': command['command_id'], 'state': 'DONE',
                                     'task_finished': True})
    stack.tick()
    assert stack.core.live()['zones'] == [{'zone': 'A', 'manager_known': True, 'manager': 'pinky1',
                                           'robot': 'pinky1', 'match': True}]
    assert stack.control(type='create', robot_id='pinky1', operation='leave')[0] == 202
    stack.tick()
    command = stack.gateway.sent[-1][1]
    stack.status['pinky1'].update(state='IDLE_WAIT', held_zone=None, detail='')
    stack.core.on_zone_status('A:free')
    stack.fleet.on_status('pinky1', {'command_id': command['command_id'], 'state': 'DONE',
                                     'task_finished': True})
    stack.tick()
    assert stack.core.live()['zones'][0]['manager'] is None
    assert stack.core.live()['zones'][0]['match'] is True


def test_full_estop_blocks_moves_until_control_is_released(stack):
    assert stack.control(type='estop')[0] == 202
    stack.tick()
    assert stack.scenario.armed is False
    assert sorted(stack.core.holds) == ['pinky1', 'pinky2', 'pinky3']
    assert sorted(stack.gateway.halts) == ['pinky1', 'pinky2', 'pinky3']
    assert stack.control(type='create', robot_id='pinky1', operation='home')[0] == 423
    assert stack.control(type='arm', armed=True, source='test')[0] == 200
    assert stack.control(type='create', robot_id='pinky1', operation='home')[0] == 409
    status, _ = stack.control(type='release_control', robot_id='pinky1', operator='kgh',
                              note='현장 확인', evidence=EVIDENCE)
    assert status == 200
    stack.tick()
    assert 'pinky1' not in stack.core.holds
    assert stack.control(type='create', robot_id='pinky1', operation='home')[0] == 202


def two_robots(stack):
    """pinky1은 상차 중, pinky2는 별도 경로로 구역 이동 중인 상태를 만든다."""
    stack.order()
    stack.until('LOAD')
    stack.order('order2', 'side')
    stack.wait(4)
    assert stack.current('order2')['robot_id'] == 'pinky2'
    stack.status['pinky2'].update(state='MOVING', detail='ZB')
    stack.tick()


def test_tc_scn_06_other_robot_finishes_its_move_and_waits_for_arm(stack):
    two_robots(stack)
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    assert stack.current()['state'] == 'PAUSED' and stack.scenario.armed is False
    assert stack.current('order2')['state'] == 'RUNNING'
    assert 'pinky2' not in stack.gateway.halts
    stack.arrive(stack.current('order2'))
    pending = len(stack.adapter.pending())
    for _ in range(20):
        stack.tick()
    assert stack.current('order2')['stage'] == 'MOVE_PICKUP'
    assert len(stack.adapter.pending()) == pending
    assert stack.control(type='arm', armed=True, source='test')[0] == 200
    for _ in range(3):
        stack.tick()
    assert stack.current('order2')['stage'] == 'PICKUP_EXIT'
    assert len(stack.adapter.pending()) == pending + 1


def test_tc_scn_06_transit_drop_pauses_every_stop_target(stack):
    stack.order()
    stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.order('order2', 'side')
    stack.wait(4)
    stack.status['pinky2'].update(state='QUEUEING', detail='slot0')
    stack.core.on_speed('pinky2', 0.0)
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    stack.core.on_pose('pinky2', 2.0, 2.0, 0.0)
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (0.1, -1.0))
    assert row['judgment'] == 'TRANSIT_DROP'
    assert sorted(r['robot_id'] for r in stack.stop_requests()) == ['pinky1', 'pinky2']
    stack.tick()
    assert stack.current()['state'] == stack.current('order2')['state'] == 'PAUSED'
    for mission in ('order1', 'order2'):
        assert stack.store.scenario(mission)['hold_reason'].startswith('CCTV TRANSIT_DROP')


def test_run_over_requests_estop(stack):
    stack.order()
    stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_run_over', (0.05, -1.0))
    assert row['judgment'] == 'RUN_OVER_COLLISION'
    assert [r['type'] for r in stack.stop_requests()] == ['estop']
    stack.tick()
    assert stack.current()['state'] == 'ESTOP'


def test_tc_scn_07_device_result_after_timeout_with_armed_off_goes_unknown(stack):
    two_robots(stack)
    stack.arrive(stack.current('order2'))
    stack.tick()
    stack.tick()
    work = stack.until('PICKUP_EXIT', 'order2')
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    assert stack.scenario.armed is False
    stack.wait(301)
    assert stack.current('order2')['state'] == 'RUNNING'
    stack.adapter.approve(work['request_id'], 'kgh')
    stack.tick()
    assert stack.current('order2')['state'] == 'UNKNOWN'
    assert 'pinky2' in stack.gateway.halts
    assert stack.store.scenario('order2')['mission_state'] == 'UNKNOWN'
    assert stack.core.robots_view()['pinky2']['op_state'] == 'PAUSED'
