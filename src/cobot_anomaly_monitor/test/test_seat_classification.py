"""
자리 주문·수동 상차 확인·같은 자리 재감지의 사고 분류 시험(11-21 갭 수정).

관제 origin/sakim 1b0cb08 ScenarioService(개발 yaml 의 shelf·destinations·customer_return)를 그대로 돌린다.
이 시험의 감시 경로 표에는 col1__P22 가 없다. 자리 경로 없이 단계로 자리 주문을 알아보는 대체 판단을 본다.
감시 노드는 layout_routes 로 col1__P22 를 만든다(그 경우는 test_monitor_node_routes 가 본다).
"""

import json

from cobot_anomaly_monitor.console_api import ConsoleApi
from cobot_anomaly_monitor.judgment import judge
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_fleet_control.scenario_contracts import NAVIGATION
from harness import POINTS, ROBOTS, Stack, ZONE
import pytest

# 이동 단계가 가는 경로 칸(관제 scenario_contracts.MOVE_POINT 와 같다).
MOVE_POINT = {'MOVE_PICKUP': 'pickup', 'MOVE_DROPOFF': 'dropoff', 'MOVE_CUSTOMER': 'customer',
              'MOVE_ARRANGE': 'dropoff', 'MOVE_RESTOCK': 'restock'}
P22 = (-0.2, -0.8, 0.0)  # 시험용 고객 자리 자세. 구역 지점과 0.6 m 넘게 떨어져 있다.
EVIDENCE = {'sku': 'SHOE42', 'load_present': True, 'arm_safe': True, 'pickup_path_clear': True}


@pytest.fixture
def stack(tmp_path):
    item = Stack(tmp_path)
    # 자리 주문은 상품의 선반 칸이 있어야 받는다(관제 _resolve_destination).
    item.scenario.store.set_stock('SHOE42', 10, 3, 1)
    yield item
    item.close()


def seat(stack, order_id='seat1'):
    return stack.scenario.submit({'order_id': order_id, 'sku': 'SHOE42', 'destination': 'P22'})


def pump(stack):
    """관제 outbox(/control_center/task_events 로 나가는 것)를 감시에 넣는다."""
    for row in stack.repo.pending():
        stack.core.on_task_event(json.loads(row['payload']))
        stack.repo.acknowledge(row['event_id'])


def start_drive(stack, order):
    """주행 단계를 시작만 한다(로봇이 달리는 중)."""
    robot, stage = order['robot_id'], order['stage']
    state = {'RETURN_HOME': 'RETURNING'}.get(stage, 'MOVING' if stage.startswith('MOVE_')
                                             else 'LEAVING_ZONE')
    stack.move(robot, state, 'EXIT')


def drive(stack, order):
    """주행 단계를 끝낸다. 구역이면 자세·구역 토큰을, 고객 자리면 시험 자세를 맞춘다."""
    robot, stage = order['robot_id'], order['stage']
    status = stack.status[robot]
    if stage in MOVE_POINT:
        point = stack.scenario.routes[order['route']][MOVE_POINT[stage]]
        stack.move(robot, 'MOVING', point)
        if point in ZONE:
            x, y, yaw = POINTS[point]
            stack.core.on_pose(robot, x + 0.01, y, yaw + 0.02)
            status.update(state='HOLDING_ZONE', held_zone=ZONE[point], detail=point)
        else:
            stack.core.on_pose(robot, *P22)
            status.update(state='IDLE_WAIT', held_zone=None, detail=point)
    elif stage == 'RETURN_HOME':
        stack.move(robot, 'RETURNING', 'EXIT')
        status.update(state='IDLE', held_zone=None, detail='')
    else:
        stack.move(robot, 'LEAVING_ZONE', 'EXIT')
        status.update(state='IDLE_WAIT', held_zone=None, detail='')
    stack.core.on_speed(robot, 0.0)
    stack.fleet.tick(allow_dispatch=True)
    stack.fleet.on_status(robot, {'command_id': order['request_id'], 'state': 'DONE',
                                  'task_finished': True})
    stack.fleet.tick(allow_dispatch=True)


def run_until(stack, order_id, done, customer=None, limit=600):
    """done(order) 가 참일 때까지 주문을 진행한다. CUSTOMER 에서는 customer 입력을 넣는다."""
    for _ in range(limit):
        stack.tick()
        order = stack.current(order_id)
        if done(order):
            return order
        if order['state'] != 'RUNNING':
            continue
        if order['stage'] == 'CUSTOMER':
            if customer:
                getattr(stack.scenario, customer)(order_id)
        elif order['request_id']:
            if order['stage'] in NAVIGATION:
                drive(stack, order)
            else:
                stack.approve(order)
    raise AssertionError('not reached: ' + order_id)


def at(stage):
    return lambda order: order['stage'] == stage and (order['request_id'] or stage == 'CUSTOMER')


def finished(order):
    return order['state'] in ('COMPLETED', 'FAILED')


def verdict(stack, vision_class, dx, robot='pinky1'):
    """지금 로봇 보기로 판정만 한다(기록하지 않음). (판정, 범위, 지목 로봇)."""
    views = stack.core.robots_view()
    view = views[robot]
    event = {'event_id': 'probe', 'camera_id': 'ceil_cam', 'vision_class': vision_class,
             'map_x': view['pose_x'] + dx, 'map_y': view['pose_y']}
    result = judge(event, views)
    return result['judgment'], result['stop_scope'], result['linked_robot_id']


def wait_customer_timeout(stack):
    # 관제 기한은 CUSTOMER 에 들어갈 때 config 로 정한다. 시험 시간을 줄이려 5초로 둔다(값만 다르다).
    stack.scenario.config['customer_timeout_sec'] = 5.0
    run_until(stack, 'seat1', at('CUSTOMER'))
    stack.wait(6)
    return stack.current('seat1')


# 자리 주문 시간 초과(G1·P2·S3·P4·G8) ------------------------------------------------------


def test_timeout_return_drive_is_transit_with_cargo(stack):
    seat(stack)
    order = wait_customer_timeout(stack)
    assert order['customer_timed_out'] and order['stage'] == 'RETURN_HOME'
    run_until(stack, 'seat1', at('RETURN_HOME'))
    start_drive(stack, stack.current('seat1'))
    stack.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    view = stack.core.robots_view()['pinky1']
    assert (view['step_seq'], view['cargo_state'], view['phase']) == (7, 'LOADED', 'TRANSIT')
    # 예전: 0.30 m 바닥은 진로 장애물(로봇 미지목), 걸침은 '[상차 불량]'. 범위는 그대로다.
    assert verdict(stack, 'box_on_floor', 0.3) == ('TRANSIT_DROP', 'ALL', 'pinky1')
    assert verdict(stack, 'box_perched_on_rim', 0.05) == ('TRANSIT_PERCHED', 'ROBOT', 'pinky1')


def test_timeout_leaves_residual_cargo_until_the_operator_clears_it(stack):
    seat(stack)
    wait_customer_timeout(stack)
    run_until(stack, 'seat1', finished)
    stack.tick()
    pump(stack)
    mission = stack.store.scenario('seat1')
    assert (mission['mission_state'], mission['outcome']) == ('COMPLETED', 'TIMEOUT')
    assert mission['cargo_state'] == 'LOADED' and mission['last_alarm_code'] == 'CUSTOMER_TIMEOUT'
    view = stack.core.robots_view()['pinky1']
    assert view['order_id'] is None and view['cargo_state'] == 'LOADED'
    assert view['residual_cargo']['order_id'] == 'seat1'
    assert view['residual_cargo']['ack_id'] == 'residual:pinky1'
    assert '잔류 화물 의심 (seat1)' in stack.core.live()['allocation']['pinky1']
    # 홈에 선 로봇 옆 감지도 그 로봇을 지목한다. 바닥 상자 범위는 예전과 같은 전체 정지다.
    stack.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    assert verdict(stack, 'box_perched_on_rim', 0.05) == ('RESIDUAL_PERCHED', 'ROBOT', 'pinky1')
    assert verdict(stack, 'box_on_floor', 0.3) == ('RESIDUAL_DROP', 'ALL', 'pinky1')
    # 재시작해도 남는다(DB).
    again = MonitorCore(stack.store, stack.routes, ROBOTS, stack._request, clock=stack.wall)
    again.on_tasks(stack.api.snapshot())
    assert again.robots_view()['pinky1']['residual_cargo']['order_id'] == 'seat1'
    # 관제는 화물 검사 없이 같은 로봇에 다음 주문을 준다. 출발 주행은 화물을 실은 운송이다.
    seat(stack, 'seat2')
    order = run_until(stack, 'seat2', at('MOVE_PICKUP'))
    assert order['robot_id'] == 'pinky1'
    start_drive(stack, order)
    view = stack.core.robots_view()['pinky1']
    assert (view['cargo_state'], view['phase']) == ('LOADED', 'TRANSIT')
    assert verdict(stack, 'box_perched_on_rim', 0.05)[0] == 'TRANSIT_PERCHED'
    # 뒤 주문이 결제돼도 상자 하나만 내린 것이다. 앞 주문 신발은 그대로일 수 있어 표시를 내리지 않는다.
    run_until(stack, 'seat2', finished, customer='received')
    stack.tick()
    assert stack.store.scenario('seat2')['outcome'] == 'PAID'
    view = stack.core.robots_view()['pinky1']
    assert view['residual_cargo']['order_id'] == 'seat1' and view['cargo_state'] == 'LOADED'
    assert stack.store.residuals()[0]['cleared_at'] is None
    # 운영자가 트레이를 비운 것을 확인해야 내린다.
    stack.core.acknowledge('residual:pinky1', 'RESOLVED', 'kgh', '트레이 비움')
    view = stack.core.robots_view()['pinky1']
    assert view['residual_cargo'] is None and view['cargo_state'] == 'EMPTY'
    assert stack.store.residuals()[0]['cleared_by'] == 'kgh'


@pytest.mark.parametrize('observation_only', [False, True])
def test_operator_clears_residual_cargo_through_the_existing_ack_route(stack, observation_only):
    seat(stack)
    wait_customer_timeout(stack)
    run_until(stack, 'seat1', finished)
    stack.tick()
    console = ConsoleApi(stack.core, stack.adapter, lambda job: job(), stack.core.replies.get,
                         clock=stack.wall, commands=False, observation_only=observation_only)
    path = '/api/fms/anomalies/residual:pinky1'
    status, body = console.handle('POST', path, {'ack_state': 'ACKNOWLEDGED', 'operator': 'kgh'})
    if observation_only:
        assert status == 403
        assert stack.core.robots_view()['pinky1']['residual_cargo'] is not None
        return
    assert status == 200 and body['residual_cargo']['acked_by'] == 'kgh'
    status, body = console.handle('POST', path, {'ack_state': 'RESOLVED', 'operator': 'kgh',
                                                 'note': '트레이 비움 확인'})
    assert status == 200 and body['residual_cargo'] is None
    assert stack.core.robots_view()['pinky1']['cargo_state'] == 'EMPTY'
    assert stack.store.residuals()[0]['clear_note'] == '트레이 비움 확인'
    assert console.handle('POST', path, {'ack_state': 'RESOLVED', 'operator': 'kgh'})[0] == 404


# 고객 인계(D1)·결제 뒤(D2) ------------------------------------------------------------------


def test_customer_handover_is_its_own_phase_with_robot_scope(stack):
    seat(stack)
    run_until(stack, 'seat1', at('CUSTOMER'))
    stack.tick()
    view = stack.core.robots_view()['pinky1']
    assert (view['step_seq'], view['phase'], view['op_state']) == (4, 'HANDOVER', 'WAIT_CUSTOMER')
    # 11-20 전과 같은 로봇 한 대 범위다(그때는 하역 단계 UNLOAD_FAIL). 0.45 m 밖은 진로 장애물 그대로.
    assert verdict(stack, 'box_on_floor', 0.3) == ('CUSTOMER_HANDOVER_DROP', 'ROBOT', 'pinky1')
    assert verdict(stack, 'box_on_floor', 0.52) == ('LANE_OBSTACLE', 'ALL', None)
    assert verdict(stack, 'box_perched_on_rim', 0.05) == (
        'CUSTOMER_HANDOVER_PERCHED', 'ROBOT', 'pinky1')
    stack.core.set_mode('AUTO_HOLD')
    lid = stack.vision('lid_detached', (P22[0] + 0.05, P22[1]))
    assert lid['judgment'] == 'CUSTOMER_HANDOVER_LID' and lid['recommended_action'] == 'NONE'
    assert stack.stop_requests() == []
    drop = stack.vision('box_on_floor', (P22[0] + 0.3, P22[1]))
    assert drop['judgment'] == 'CUSTOMER_HANDOVER_DROP'
    assert [(r['type'], r.get('robot_id')) for r in stack.stop_requests()] == [('pause', 'pinky1')]
    stack.tick()
    assert stack.scenario.armed is True and list(stack.scenario.store.holds()) == ['pinky1']


def test_paid_seat_order_returns_with_unverified_empty_tray(stack):
    seat(stack)
    run_until(stack, 'seat1', at('RETURN_HOME'), customer='received')
    start_drive(stack, stack.current('seat1'))
    stack.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    view = stack.core.robots_view()['pinky1']
    assert (view['cargo_state'], view['phase']) == ('EMPTY_UNVERIFIED', 'RESIDUAL')
    # 걸침은 잔류 의심(로봇 한 대), 바닥 상자는 로봇을 지목하되 범위는 예전 진로 장애물과 같다.
    assert verdict(stack, 'box_perched_on_rim', 0.05) == ('RESIDUAL_PERCHED', 'ROBOT', 'pinky1')
    assert verdict(stack, 'box_on_floor', 0.3) == ('RESIDUAL_DROP', 'ALL', 'pinky1')
    row = stack.vision('box_perched_on_rim', (0.05, 0.0))
    assert '[잔류 의심]' in row['alarm_text'] and '상차' not in row['alarm_text']
    run_until(stack, 'seat1', finished)
    stack.tick()
    mission = stack.store.scenario('seat1')
    assert (mission['outcome'], mission['cargo_state']) == ('PAID', 'EMPTY_UNVERIFIED')
    assert stack.core.robots_view()['pinky1']['residual_cargo'] is None


# 회수 갈래(S2·P3·P9) --------------------------------------------------------------------


def test_declined_branch_drives_as_transit_and_arrange_is_not_unloading(stack):
    seat(stack)
    run_until(stack, 'seat1', at('ARRANGE'), customer='declined')
    stack.tick()
    view = stack.core.robots_view()['pinky1']
    assert (view['step_seq'], view['phase'], view['cargo_state']) == (6, 'ARRANGE', 'LOADED')
    assert verdict(stack, 'box_on_floor', 0.3) == ('ARRANGE_FAIL', 'ROBOT', 'pinky1')
    row = stack.vision('box_perched_on_rim', (view['pose_x'] + 0.05, view['pose_y']))
    assert row['judgment'] == 'ARRANGE_FAIL'
    assert '정리' in row['alarm_text'] and '하역' not in row['alarm_text']
    for stage in ('LEAVE_ARRANGE', 'MOVE_RESTOCK'):
        start_drive(stack, run_until(stack, 'seat1', at(stage)))
        stack.core.on_pose('pinky1', 0.0, 0.0, 0.0)
        view = stack.core.robots_view()['pinky1']
        # 표시 단계는 6에 머물지만 판정은 화물을 실은 운송이다. 예전에는 UNLOAD_FAIL(로봇 한 대)이었다.
        assert (view['step_seq'], view['phase']) == (6, 'TRANSIT'), stage
        assert verdict(stack, 'box_on_floor', 0.3) == ('TRANSIT_DROP', 'ALL', 'pinky1')
        assert verdict(stack, 'box_on_floor', 0.55) == ('TRANSIT_DROP', 'ALL', 'pinky1')
        assert verdict(stack, 'box_perched_on_rim', 0.05)[0] == 'TRANSIT_PERCHED'
    run_until(stack, 'seat1', at('RESTOCK'))
    stack.tick()
    assert verdict(stack, 'box_on_floor', 0.3) == ('UNLOAD_FAIL', 'ROBOT', 'pinky1')
    start_drive(stack, run_until(stack, 'seat1', at('LEAVE_RESTOCK')))
    view = stack.core.robots_view()['pinky1']
    assert (view['cargo_state'], view['phase']) == ('EMPTY_UNVERIFIED', 'RESIDUAL')
    run_until(stack, 'seat1', finished)
    stack.tick()
    assert stack.store.scenario('seat1')['outcome'] == 'DECLINED'


# 수동 상차 확인(S1·G9·M1) -----------------------------------------------------------------


@pytest.mark.parametrize('stage', ['MARKER', 'PICK'])
def test_operator_load_confirmation_counts_as_loaded(stack, stage):
    stack.scenario.config['step_timeout_sec'] = 5.0  # 단계 결과 시간 초과까지만 줄인다
    stack.order(route='lab_delivery_zb')
    run_until(stack, 'order1', at(stage), limit=300)
    stack.wait(6)
    assert stack.current()['state'] == 'UNKNOWN'
    reply = stack.api.handle({'type': 'confirm_loaded', 'request_id': 'c1', 'order_id': 'order1',
                              'operator': 'kgh', 'note': '손으로 올림', 'evidence': EVIDENCE})
    assert reply['status'] == 200, reply
    order = stack.current()
    assert order['stage'] == 'LEAVE_PICKUP' and 'VERIFY_LOAD' not in order['completed']
    start_drive(stack, run_until(stack, 'order1', at('LEAVE_PICKUP')))
    stack.core.on_pose('pinky1', 0.0, 0.0, 0.0)
    view = stack.core.robots_view()['pinky1']
    assert (view['cargo_state'], view['phase']) == ('LOADED', 'TRANSIT')
    assert verdict(stack, 'box_on_floor', 0.3) == ('TRANSIT_DROP', 'ALL', 'pinky1')
    assert verdict(stack, 'box_perched_on_rim', 0.05)[0] == 'TRANSIT_PERCHED'
    tasks = {t['step_seq']: t['task_state'] for t in stack.store.tasks('order1')}
    # 운영자가 확인한 상차 단계는 건너뛴 것이 아니다.
    assert tasks[3] == 'SUCCEEDED'
    assert stack.store.scenario('order1')['cargo_state'] == 'LOADED'


# PICK 상차·같은 자리 재감지(P1·M2) --------------------------------------------------------


def test_pick_is_loading_and_drop_keeps_the_old_full_stop_scope(stack):
    stack.order(route='lab_delivery_zb')
    run_until(stack, 'order1', at('PICK'))
    stack.tick()
    view = stack.core.robots_view()['pinky1']
    assert (view['cargo_state'], view['phase']) == ('LOADING', 'PICK')
    assert verdict(stack, 'box_perched_on_rim', 0.05) == ('LOAD_FAIL_PERCHED', 'ROBOT', 'pinky1')
    # 11-20 전에는 진로 장애물(전체 정지)이었다. 로봇은 지목하되 범위는 좁히지 않는다(D3).
    assert verdict(stack, 'box_on_floor', 0.3) == ('LOAD_FAIL_DROP', 'ALL', 'pinky1')


def test_redetection_is_judged_again_when_the_robot_phase_changes(stack):
    stack.order(route='lab_delivery_zb')
    run_until(stack, 'order1', at('MARKER'))
    stack.tick()
    zb = POINTS['ZB'][:2]
    rim, floor = (zb[0] + 0.05, zb[1]), (zb[0] + 0.3, zb[1])
    e1, e2 = stack.vision('box_perched_on_rim', rim), stack.vision('box_on_floor', floor)
    assert (e1['judgment'], e2['judgment']) == ('IGNORED', 'LANE_OBSTACLE')
    run_until(stack, 'order1', at('PICK'))
    stack.tick()
    r1, r2 = stack.vision('box_perched_on_rim', rim), stack.vision('box_on_floor', floor)
    assert (r1['event_id'], r2['event_id']) == (e1['event_id'], e2['event_id'])
    assert (r1['judgment'], r1['linked_robot_id'], r1['stop_scope']) == (
        'LOAD_FAIL_PERCHED', 'pinky1', 'ROBOT')
    assert (r2['judgment'], r2['linked_robot_id'], r2['stop_scope']) == (
        'LOAD_FAIL_DROP', 'pinky1', 'ALL')
    assert r1['judgment_history'] == 'IGNORED' and r1['robot_cargo_at_event'] == 'LOADING'
    assert r1['control_action'] == 'OBSERVE_ONLY' and r1['repeat_count'] == 2
    # LOAD 는 로봇 한 대 범위지만 이미 넓힌 전체 정지는 좁히지 않는다.
    run_until(stack, 'order1', at('LOAD'))
    stack.tick()
    r2 = stack.vision('box_on_floor', floor)
    assert (r2['judgment'], r2['stop_scope']) == ('LOAD_FAIL_DROP', 'ALL')


def test_redetection_after_the_robot_left_keeps_the_first_judgment(stack):
    stack.order(route='lab_delivery_zb')
    run_until(stack, 'order1', at('UNLOAD'))
    stack.tick()
    zc = POINTS['ZC'][:2]
    first = stack.vision('box_on_floor', (zc[0] + 0.3, zc[1]))
    assert (first['judgment'], first['stop_scope']) == ('UNLOAD_FAIL', 'ROBOT')
    start_drive(stack, run_until(stack, 'order1', at('LEAVE_DROPOFF'), customer='received'))
    stack.core.on_pose('pinky1', zc[0] + 0.1, zc[1], 0.0)
    again = stack.vision('box_on_floor', (zc[0] + 0.3, zc[1]))
    # 빈 로봇은 지목하지 않는다. 다시 판정해도 낙하가 진로 장애물로 바뀌지 않는다.
    assert again['event_id'] == first['event_id']
    assert (again['judgment'], again['stop_scope']) == ('UNLOAD_FAIL', 'ROBOT')


def test_rejudge_that_widens_the_scope_sends_a_new_stop_in_auto_hold(stack):
    stack.order(route='lab_delivery_zb')
    run_until(stack, 'order1', at('MARKER'))
    stack.tick()
    stack.core.set_mode('AUTO_HOLD')
    zb = POINTS['ZB'][:2]
    rim = (zb[0] + 0.05, zb[1])
    first = stack.vision('box_perched_on_rim', rim)
    assert first['judgment'] == 'IGNORED' and stack.stop_requests() == []
    run_until(stack, 'order1', at('PICK'))
    stack.tick()
    again = stack.vision('box_perched_on_rim', rim)
    assert again['judgment'] == 'LOAD_FAIL_PERCHED' and again['control_action'] == 'PAUSE_ACCEPTED'
    assert [(r['type'], r.get('robot_id')) for r in stack.stop_requests()] == [('pause', 'pinky1')]
