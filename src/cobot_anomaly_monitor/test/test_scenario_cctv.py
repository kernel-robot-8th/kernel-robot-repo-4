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
    assert first['stop_scope'] == 'ROBOT'
    assert stack.store.event(first['event_id'])['control_action'] == 'PAUSE_ACCEPTED'
    # 로봇을 지정한 정지는 그 로봇만 보류한다. 작업 명령 스위치는 켜진 채다.
    assert stack.current()['state'] == 'PAUSED' and stack.scenario.armed is True
    assert list(stack.scenario.store.holds()) == ['pinky1']
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
    assert row['stop_scope'] == 'ALL' and json.loads(row['stop_targets_json']) == ['pinky1']


def test_drop_during_qr_pauses_the_docked_robot(stack):
    stack.order()
    stack.until('QR')
    stack.tick()
    assert stack.core.robots_view()['pinky1']['driving'] is False
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (POINTS['ZC'][0] + 0.2, POINTS['ZC'][1]))
    assert row['judgment'] == 'TRANSIT_DROP'
    assert [(r['type'], r.get('robot_id')) for r in stack.stop_requests()] == [('pause', None)]
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
    # 통로 낙하는 전체 정지다. 로봇 지정 없는 요청 한 건이 전 로봇 보류와 armed 끄기를 부른다.
    assert row['stop_scope'] == 'ALL'
    assert [(r['type'], 'robot_id' in r) for r in stack.stop_requests()] == [('pause', False)]
    assert stack.scenario.armed is False
    assert sorted(stack.core.holds) == ['pinky1', 'pinky2', 'pinky3']
    assert stack.current()['state'] == 'PAUSED'
    assert stack.live_mission()['recovery'] == 'resume'
    status, body = resolve(stack, 'resume')
    assert status == 400 and '가동 허용' in body['detail']
    # 가동 허용 켜기는 관제 웹에서만 한다. 이 콘솔은 거절하고 관제로 넘기지 않는다.
    sent = len(stack.requests)
    status, body = stack.control(type='arm', armed=True, source='test')
    assert status == 403 and '관제 웹' in body['detail']
    assert len(stack.requests) == sent and stack.scenario.armed is False
    assert fleet(stack, type='arm', armed=True) == 200
    assert resolve(stack, 'resume')[0] == 200
    stack.tick()
    assert stack.current()['state'] == 'RUNNING'
    assert stack.store.scenario('order1')['hold_reason'] == ''
    # 전체 정지 사건은 주문 하나의 복구로 닫히지 않는다. 확인만 남고 열려 있다.
    acked = stack.store.event(row['event_id'])
    assert (acked['ack_state'], acked['resolved_by']) == ('ACKNOWLEDGED', 'kgh')
    # 주문 복구는 그 주문의 로봇만 푼다. 주문 없는 로봇은 하나씩 제어권을 돌려받아야 한다.
    assert sorted(stack.core.holds) == ['pinky2', 'pinky3']
    assert stack.control(type='create', robot_id='pinky2', operation='home')[0] == 409
    for robot in ('pinky2', 'pinky3'):
        assert stack.control(type='release_control', robot_id=robot, operator='kgh',
                             note='현장 확인', evidence=EVIDENCE)[0] == 200
    stack.tick()
    assert stack.core.holds == {}
    # 전부 풀린 스냅샷에서 닫힌다. 복구한 사람과 메모는 남는다.
    closed = stack.store.event(row['event_id'])
    assert (closed['ack_state'], closed['resolved_by']) == ('RESOLVED', 'kgh')
    assert closed['resolved_note'].startswith('현장 확인 / ')
    assert stack.control(type='create', robot_id='pinky2', operation='home')[0] == 202
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
    status, body = resolve(stack, 'resume')
    assert status == 400 and '재피킹' in body['detail']
    assert resolve(stack, 'fail')[0] == 200
    stack.tick()
    assert stack.store.scenario('order1')['mission_state'] == 'FAILED'
    assert stack.store.tasks('order1')[2]['task_state'] == 'FAILED'


def test_tc_scn_05_fail_keeps_the_zone_until_leave(stack):
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
    # 로봇 지정 정지는 armed를 끄지 않는다. 종결 직후 바로 명령을 받는다.
    assert stack.scenario.armed is True and stack.core.holds == {}
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
    assert fleet(stack, type='arm', armed=True) == 200
    assert stack.control(type='create', robot_id='pinky1', operation='home')[0] == 409
    assert stack.status['pinky1']['central_latched'] is True
    status, _ = stack.control(type='release_control', robot_id='pinky1', operator='kgh',
                              note='현장 확인', evidence=EVIDENCE)
    assert status == 200
    stack.tick()
    assert 'pinky1' not in stack.core.holds
    assert stack.status['pinky1']['central_latched'] is False
    assert stack.status['pinky2']['central_latched'] is True
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


def test_tc_scn_06_other_robot_keeps_working_while_one_is_paused(stack):
    two_robots(stack)
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    assert stack.current()['state'] == 'PAUSED' and stack.scenario.armed is True
    assert list(stack.core.holds) == ['pinky1']
    assert stack.current('order2')['state'] == 'RUNNING'
    assert 'pinky2' not in stack.gateway.halts
    stack.arrive(stack.current('order2'))
    pending = len(stack.adapter.pending())
    for _ in range(3):
        stack.tick()
    # arm을 다시 켜지 않아도 다른 로봇의 주문은 다음 단계로 간다.
    assert stack.current('order2')['stage'] == 'PICKUP_EXIT'
    assert len(stack.adapter.pending()) == pending + 1
    assert stack.current()['state'] == 'PAUSED'


def test_tc_scn_06_transit_drop_pauses_every_robot(stack):
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
    assert json.loads(row['stop_targets_json']) == ['pinky1']
    assert [(r['type'], 'robot_id' in r) for r in stack.stop_requests()] == [('pause', False)]
    stack.tick()
    assert stack.scenario.armed is False
    assert sorted(stack.core.holds) == ['pinky1', 'pinky2', 'pinky3']
    assert stack.current()['state'] == stack.current('order2')['state'] == 'PAUSED'
    # 사유는 지목 로봇의 주문만이 아니라 진행 중인 주문 전부에 남는다.
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
    assert [(r['type'], 'robot_id' in r) for r in stack.stop_requests()] == [('estop', False)]
    stack.tick()
    assert stack.current()['state'] == 'ESTOP' and stack.scenario.armed is False
    assert stack.store.event(row['event_id'])['control_action'] == 'ESTOP_ACCEPTED'


def test_tc_scn_07_device_result_after_timeout_with_armed_off_goes_unknown(stack):
    two_robots(stack)
    stack.arrive(stack.current('order2'))
    stack.tick()
    stack.tick()
    work = stack.until('PICKUP_EXIT', 'order2')
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    # 턱 걸림은 그 로봇만 세운다. armed 꺼짐은 운영자 조작으로 따로 만든다.
    assert stack.scenario.armed is True
    assert stack.control(type='arm', armed=False, source='test')[0] == 200
    stack.wait(301)
    assert stack.current('order2')['state'] == 'RUNNING'
    stack.adapter.approve(work['request_id'], 'kgh')
    stack.tick()
    assert stack.current('order2')['state'] == 'UNKNOWN'
    assert 'pinky2' in stack.gateway.halts
    assert stack.store.scenario('order2')['mission_state'] == 'UNKNOWN'
    assert stack.core.robots_view()['pinky2']['op_state'] == 'PAUSED'


def loading(stack):
    stack.order()
    stack.until('LOAD')
    stack.tick()
    return ZA


def unloading(stack):
    stack.order()
    stack.until('UNLOAD')
    stack.tick()
    return POINTS['ZC'][:2]


def transit(stack):
    stack.order()
    stack.until('MOVE_DROPOFF')
    stack.move('pinky1', 'MOVING', 'P5')
    stack.core.on_pose('pinky1', 0.0, -1.0, 0.0)
    return (0.05, -1.0)


def far_from_transit(stack):
    transit(stack)
    return (2.0, 2.0)


def two_loaded(stack):
    """적재 로봇 둘이 바닥 상자 반경 안에 있는 상태를 자세로 만든다."""
    transit(stack)
    stack.order('order2', 'side')
    stack.until('LOAD', 'order2')
    stack.tick()
    stack.core.on_pose('pinky2', 0.4, -1.0, 0.0)
    return (0.2, -1.0)


# 장면, 감지 클래스, 판정, 요청 type, 요청의 robot_id(None은 전체 정지), 보류 로봇 수
SCOPE_TABLE = [
    (loading, 'box_perched_on_rim', 'LOAD_FAIL_PERCHED', 'pause', 'pinky1', 1),
    (loading, 'box_on_floor', 'LOAD_FAIL_DROP', 'pause', 'pinky1', 1),
    (unloading, 'box_perched_on_rim', 'UNLOAD_FAIL', 'pause', 'pinky1', 1),
    (unloading, 'box_on_floor', 'UNLOAD_FAIL', 'pause', 'pinky1', 1),
    (transit, 'box_perched_on_rim', 'TRANSIT_PERCHED', 'pause', 'pinky1', 1),
    (transit, 'box_on_floor', 'TRANSIT_DROP', 'pause', None, 3),
    (far_from_transit, 'box_on_floor', 'LANE_OBSTACLE', 'pause', None, 3),
    (two_loaded, 'box_on_floor', 'AMBIGUOUS', 'pause', None, 3),
    (transit, 'box_run_over', 'RUN_OVER_COLLISION', 'estop', None, 3),
]


@pytest.mark.parametrize('scene,vision_class,judgment,kind,robot,held', SCOPE_TABLE)
def test_stop_scope_per_judgment(stack, scene, vision_class, judgment, kind, robot, held):
    xy = scene(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision(vision_class, xy)
    assert row['judgment'] == judgment
    assert row['stop_scope'] == ('ROBOT' if robot else 'ALL')
    requests = stack.stop_requests()
    assert [r['type'] for r in requests] == [kind]
    # 전체 정지 요청에는 robot_id 키 자체가 없어야 한다. null로 보내지 않는다.
    assert requests[0].get('robot_id') == robot and ('robot_id' in requests[0]) is bool(robot)
    stack.tick()
    assert stack.scenario.armed is bool(robot)
    assert len(stack.core.holds) == held
    detail = json.loads(stack.store.event(row['event_id'])['control_detail'])
    assert list(detail) == [robot or 'ALL']
    assert detail[robot or 'ALL']['body']['armed'] is bool(robot)
    assert stack.store.event(row['event_id'])['control_action'] == kind.upper() + '_ACCEPTED'


@pytest.mark.parametrize('scene,vision_class,judgment', [
    (loading, 'lid_detached', 'LID_OPEN_ANOMALY'),
    (two_loaded, 'box_perched_on_rim', 'AMBIGUOUS'),
])
def test_judgments_without_action_send_nothing(stack, scene, vision_class, judgment):
    xy = scene(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision(vision_class, xy)
    assert row['judgment'] == judgment and row['stop_scope'] == 'ROBOT'
    assert row['control_action'] == 'NONE' and stack.stop_requests() == []
    assert stack.scenario.armed is True and stack.scenario.store.holds() == {}


def test_lane_obstacle_without_any_order_stops_everyone(stack):
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (0.0, 0.0))
    assert row['judgment'] == 'LANE_OBSTACLE' and row['linked_robot_id'] is None
    assert row['linked_mission_id'] is None and json.loads(row['stop_targets_json']) == []
    assert row['recommended_action'] == 'PAUSE' and row['stop_scope'] == 'ALL'
    assert row['control_action'] == 'PAUSE_ACCEPTED'
    request, = stack.stop_requests()
    assert request['type'] == 'pause' and 'robot_id' not in request
    assert request['client_request_id'] == 'cctv_' + row['event_id']
    stack.tick()
    assert stack.scenario.armed is False
    assert sorted(stack.core.holds) == ['pinky1', 'pinky2', 'pinky3']
    assert sorted(stack.gateway.halts) == ['pinky1', 'pinky2', 'pinky3']


def test_lane_obstacle_in_observe_only_records_and_sends_nothing(stack):
    stack.tick()
    row = stack.vision('box_on_floor', (0.0, 0.0))
    assert row['stop_scope'] == 'ALL' and row['control_action'] == 'OBSERVE_ONLY'
    assert stack.requests == [] and stack.scenario.armed is True


def test_same_obstacle_seen_again_does_not_stop_twice(stack):
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_on_floor', (0.0, 0.0))
    stack.tick(5.0)
    again = stack.vision('box_on_floor', (0.1, 0.0))
    assert again['event_id'] == first['event_id'] and again['repeat_count'] == 2
    assert len(stack.stop_requests()) == 1


def test_full_stop_recovery_order(stack):
    """전체 정지 복구 순서: arm 전 resume 400 → arm → resume 200 → release_control → 명령 202."""
    transit(stack)
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_on_floor', (0.05, -1.0))
    stack.tick()
    assert stack.scenario.armed is False
    assert stack.control(type='create', robot_id='pinky2', operation='home')[0] == 423
    assert resolve(stack, 'resume')[0] == 400
    assert stack.current()['state'] == 'PAUSED'
    assert stack.control(type='arm', armed=True, source='test')[0] == 403
    assert fleet(stack, type='arm', armed=True) == 200
    # arm만으로는 풀리지 않는다. 보류가 남아 있다.
    assert stack.control(type='create', robot_id='pinky2', operation='home')[0] == 409
    # 주문이 걸린 로봇은 release_control이 아니라 주문 복구로 푼다.
    assert stack.control(type='release_control', robot_id='pinky1', operator='kgh',
                         note='현장 확인', evidence=EVIDENCE)[0] == 409
    assert resolve(stack, 'resume')[0] == 200
    stack.tick()
    assert stack.current()['state'] == 'RUNNING' and 'pinky1' not in stack.core.holds
    assert stack.control(type='release_control', robot_id='pinky2', operator='kgh',
                         note='현장 확인', evidence=EVIDENCE)[0] == 200
    stack.tick()
    assert list(stack.core.holds) == ['pinky3']
    # 래치는 제어권을 돌려받은 로봇만 풀린다. 남은 로봇은 배정 대상이 아니다.
    assert stack.status['pinky2']['central_latched'] is False
    assert stack.status['pinky3']['central_latched'] is True
    assert 'central_latched' in stack.core.allocation_reasons('pinky3', stack.wall())
    assert stack.control(type='create', robot_id='pinky2', operation='home')[0] == 202
    assert stack.control(type='create', robot_id='pinky3', operation='home')[0] == 409


def fleet(stack, **request):
    """콘솔을 거치지 않고 관제에 바로 넣는다. 팀 관제 웹에서 복구하는 경우다."""
    return stack.api.handle(dict(request, request_id='direct'))['status']


def test_resolve_sent_straight_to_fleet_closes_the_robot_event(stack):
    xy = loading(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_perched_on_rim', xy)
    stack.tick()
    assert stack.store.event(row['event_id'])['hold_seen'] == 1
    assert fleet(stack, type='resolve', order_id='order1', decision='fail') == 200
    # 닫는 것은 다음 스냅샷이다. 그 전에는 열려 있다.
    assert stack.store.event(row['event_id'])['ack_state'] == 'UNREAD'
    stack.tick()
    closed = stack.store.event(row['event_id'])
    assert closed['ack_state'] == 'RESOLVED' and closed['resolved_by'] == 'fleet'
    assert closed['resolved_at'] == stack.wall() and closed['resolved_note']
    assert stack.store.open_events() == []


def test_resume_sent_straight_to_fleet_closes_the_robot_event(stack):
    xy = transit(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_perched_on_rim', xy)
    stack.tick()
    assert row['judgment'] == 'TRANSIT_PERCHED' and stack.current()['state'] == 'PAUSED'
    assert fleet(stack, type='resolve', order_id='order1', decision='resume') == 200
    stack.tick()
    assert stack.current()['state'] == 'RUNNING'
    assert stack.store.event(row['event_id'])['resolved_by'] == 'fleet'
    assert stack.store.scenario('order1')['hold_reason'] == ''


def test_full_stop_event_closes_only_after_everything_is_released(stack):
    xy = transit(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', xy)

    def state():
        stack.tick()
        return stack.store.event(row['event_id'])['ack_state']

    assert state() == 'UNREAD' and stack.store.event(row['event_id'])['hold_seen'] == 1
    assert fleet(stack, type='arm', armed=True) == 200
    assert state() == 'UNREAD'
    assert fleet(stack, type='resolve', order_id='order1', decision='resume') == 200
    assert state() == 'UNREAD'
    assert fleet(stack, type='release_control', robot_id='pinky2') == 200
    assert state() == 'UNREAD' and list(stack.core.holds) == ['pinky3']
    assert fleet(stack, type='release_control', robot_id='pinky3') == 200
    assert state() == 'RESOLVED'
    assert stack.store.event(row['event_id'])['resolved_by'] == 'fleet'


def test_full_stop_event_stays_open_while_armed_is_off(stack):
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (0.0, 0.0))
    stack.tick()
    for robot in ('pinky1', 'pinky2', 'pinky3'):
        assert fleet(stack, type='release_control', robot_id=robot) == 200
    stack.tick()
    assert stack.core.holds == {} and stack.scenario.armed is False
    assert stack.store.event(row['event_id'])['ack_state'] == 'UNREAD'
    assert fleet(stack, type='arm', armed=True) == 200
    stack.tick()
    assert stack.store.event(row['event_id'])['ack_state'] == 'RESOLVED'


def test_redetection_stops_again_only_after_the_event_is_closed(stack):
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_on_floor', (0.0, 0.0))
    # 열려 있는 동안 30초 안 재감지는 같은 사건에 묶이고 요청이 늘지 않는다.
    for _ in range(3):
        stack.tick(5.0)
        again = stack.vision('box_on_floor', (0.1, 0.0))
        assert again['event_id'] == first['event_id']
    assert again['repeat_count'] == 4 and len(stack.stop_requests()) == 1
    assert again['ack_state'] == 'UNREAD'
    for robot in ('pinky1', 'pinky2', 'pinky3'):
        assert fleet(stack, type='release_control', robot_id=robot) == 200
    assert fleet(stack, type='arm', armed=True) == 200
    stack.tick()
    assert stack.store.event(first['event_id'])['ack_state'] == 'RESOLVED'
    assert stack.scenario.armed is True and stack.core.holds == {}
    # 닫힌 뒤 같은 자리에 상자가 남아 있으면 새 사건으로 다시 멈춘다.
    second = stack.vision('box_on_floor', (0.1, 0.0))
    assert second['event_id'] != first['event_id'] and second['repeat_count'] == 1
    assert second['control_action'] == 'PAUSE_ACCEPTED'
    assert [('robot_id' in r) for r in stack.stop_requests()] == [False, False]
    stack.tick()
    assert stack.scenario.armed is False
    assert sorted(stack.core.holds) == ['pinky1', 'pinky2', 'pinky3']
    assert stack.store.event(second['event_id'])['ack_state'] == 'UNREAD'


@pytest.mark.parametrize('scene,vision_class', [
    (loading, 'box_perched_on_rim'), (transit, 'box_on_floor')])
def test_snapshot_taken_before_the_stop_does_not_close_the_event(stack, scene, vision_class):
    xy = scene(stack)
    stale = stack.api.snapshot()
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision(vision_class, xy)
    assert row['control_action'] == 'PAUSE_ACCEPTED'
    # 관제가 정지를 반영하기 전에 만든 스냅샷이 늦게 도착한 경우다.
    for _ in range(2):
        stack.core.on_tasks(stale)
    late = stack.store.event(row['event_id'])
    assert late['ack_state'] == 'UNREAD' and late['hold_seen'] == 0
    stack.tick()
    assert stack.store.event(row['event_id'])['hold_seen'] == 1
    assert stack.store.event(row['event_id'])['ack_state'] == 'UNREAD'


def test_observe_only_event_is_not_closed_by_snapshots(stack):
    xy = loading(stack)
    row = stack.vision('box_perched_on_rim', xy)
    assert stack.control(type='pause', robot_id='pinky1')[0] == 202
    stack.tick()
    assert fleet(stack, type='resolve', order_id='order1', decision='fail') == 200
    stack.tick()
    assert stack.store.event(row['event_id'])['ack_state'] == 'UNREAD'


def test_console_resolve_without_operator_is_refused_before_fleet(stack):
    xy = loading(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_perched_on_rim', xy)
    stack.tick()
    sent = len(stack.requests)
    for operator in (None, '', '  ', 7):
        status, body = stack.control(type='resolve', order_id='order1', decision='fail',
                                     operator=operator)
        assert status == 400 and 'operator' in body['detail']
    assert stack.control(type='resolve', order_id='order1', decision='fail')[0] == 400
    assert len(stack.requests) == sent
    stack.tick()
    assert stack.current()['state'] == 'PAUSED'
    assert stack.store.event(row['event_id'])['ack_state'] == 'UNREAD'
    assert resolve(stack, 'fail')[0] == 200
    assert stack.store.event(row['event_id'])['resolved_by'] == 'kgh'


@pytest.mark.parametrize('direct', [False, True])
def test_redetection_after_a_failed_order_stays_on_that_robot(stack, direct):
    """상차 낙하를 fail로 닫은 뒤 같은 상자가 다시 감지돼도 전체 정지로 번지지 않는다."""
    xy = loading(stack)
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_on_floor', xy)
    stack.tick()
    assert first['judgment'] == 'LOAD_FAIL_DROP' and first['stop_scope'] == 'ROBOT'
    if direct:
        assert fleet(stack, type='resolve', order_id='order1', decision='fail') == 200
    else:
        assert resolve(stack, 'fail')[0] == 200
    stack.tick()
    assert stack.store.event(first['event_id'])['ack_state'] == 'RESOLVED'
    assert stack.current()['state'] == 'FAILED'
    stack.tick(5.0)
    again = stack.vision('box_on_floor', xy)
    assert again['event_id'] != first['event_id']
    # 주문이 끝나 근처에 적재 로봇이 없다. 새로 판정하면 LANE_OBSTACLE(전체 정지)이 된다.
    assert (again['judgment'], again['stop_scope']) == ('LOAD_FAIL_DROP', 'ROBOT')
    assert again['linked_robot_id'] == 'pinky1' and first['event_id'] in again['alarm_text']
    assert [r.get('robot_id') for r in stack.stop_requests()] == ['pinky1', 'pinky1']
    stack.tick()
    assert stack.scenario.armed is True
    assert not {'pinky2', 'pinky3'} & set(stack.core.holds)


def test_redetection_long_after_the_close_is_judged_again(stack):
    xy = loading(stack)
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_on_floor', xy)
    stack.tick()
    assert resolve(stack, 'fail')[0] == 200
    stack.tick(301.0)
    again = stack.vision('box_on_floor', xy)
    assert (again['judgment'], again['stop_scope']) == ('LANE_OBSTACLE', 'ALL')


def test_full_stop_event_merges_redetection_after_a_long_gap(stack):
    """전체 정지가 걸린 동안은 감지가 30초 넘게 끊겼다 와도 새 사건·새 정지가 없다."""
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_on_floor', (0.0, 0.0))
    stack.tick(45.0)
    for robot in ('pinky1', 'pinky2'):  # 복구 도중
        assert fleet(stack, type='release_control', robot_id=robot) == 200
    stack.tick()
    again = stack.vision('box_on_floor', (0.1, 0.0))
    assert again['event_id'] == first['event_id'] and again['repeat_count'] == 2
    assert len(stack.stop_requests()) == 1
    assert list(stack.core.holds) == ['pinky3']


def test_pause_after_a_full_estop_is_not_sent_again(stack):
    """깔림 estop으로 전부 선 뒤 같은 상자의 바닥 감지가 pause로 estop을 덮지 않는다."""
    xy = transit(stack)
    stack.core.set_mode('AUTO_HOLD')
    stack.vision('box_run_over', xy)
    stack.tick()
    assert stack.current()['state'] == 'ESTOP'
    row = stack.vision('box_on_floor', xy)
    assert row['stop_scope'] == 'ALL' and row['control_action'] == 'PAUSE_ACCEPTED'
    assert '이미 전체 정지' in row['control_detail']
    assert [r['type'] for r in stack.stop_requests()] == ['estop']
    stack.tick()
    assert stack.current()['state'] == 'ESTOP'
    assert stack.store.event(row['event_id'])['hold_seen'] == 1


def test_full_stop_keeps_the_reason_already_written_on_an_order(stack):
    two_robots(stack)
    stack.core.set_mode('AUTO_HOLD')
    first = stack.vision('box_perched_on_rim', ZA)
    stack.tick()
    reason = stack.store.scenario('order1')['hold_reason']
    assert first['event_id'] in reason
    second = stack.vision('box_on_floor', (2.0, 2.0))
    assert second['stop_scope'] == 'ALL'
    assert stack.store.scenario('order1')['hold_reason'] == reason
    assert second['event_id'] in stack.store.scenario('order2')['hold_reason']


def test_console_resolve_of_a_robot_event_closes_it_at_once(stack):
    xy = transit(stack)
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_perched_on_rim', xy)
    stack.tick()
    assert resolve(stack, 'resume')[0] == 200
    closed = stack.store.event(row['event_id'])
    assert (closed['ack_state'], closed['resolved_by']) == ('RESOLVED', 'kgh')
    stack.tick()
    assert stack.store.event(row['event_id'])['resolved_note'] == '현장 확인'


def test_acknowledged_full_stop_keeps_the_operator_when_fleet_closes_it(stack):
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    row = stack.vision('box_on_floor', (0.0, 0.0))
    stack.tick()
    stack.core.acknowledge(row['event_id'], 'ACKNOWLEDGED', 'lee', '상자 치움')
    for robot in ('pinky1', 'pinky2', 'pinky3'):
        assert fleet(stack, type='release_control', robot_id=robot) == 200
    assert fleet(stack, type='arm', armed=True) == 200
    stack.tick()
    closed = stack.store.event(row['event_id'])
    assert (closed['ack_state'], closed['resolved_by']) == ('RESOLVED', 'lee')
    assert closed['resolved_note'] == '상자 치움 / 관제에서 재개됨(스냅샷으로 확인)'
