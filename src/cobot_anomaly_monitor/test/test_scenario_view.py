"""관제 단계(경로 주문 21단계·고객 자리 주문 단계)와 7단계 대응, 적재 상태 계산 시험."""

from cobot_anomaly_monitor.judgment import judge
from cobot_anomaly_monitor.scenario_view import (
    cargo_of, CUSTOMER_SEAT_STEP, done_stages, driving_of, hold_op_state, is_customer_order,
    leaves_residual,
    NAVIGATION_STAGES, op_state_of, outcome_of, phase_of, queue_wait_of, RESUMABLE_STAGES,
    STAGE_STEP, step_of, ZONE_ENTRY_STAGES, zone_of)
import pytest

ROUTE = {'pickup': 'ZA', 'dropoff': 'ZC'}
# 관제 origin/sakim 1b0cb08 이 shelf·customer_return·destinations 로 만드는 col1__P22 경로와 같은 모양.
SEAT_ROUTE = {'pickup': 'ZB', 'pickup_arm': 'omx2', 'customer': 'P22', 'dropoff': 'ZC',
              'dropoff_arm': 'omx3', 'restock': 'ZA', 'restock_arm': 'omx1', 'lane': 'main'}
SEAT_BEFORE_CUSTOMER = ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD',
                        'VERIFY_LOAD', 'LEAVE_PICKUP', 'MOVE_CUSTOMER']


def order(stage, completed=(), **extra):
    return dict({'stage': stage, 'completed': list(completed)}, **extra)


def test_every_team_stage_has_a_step():
    # 경로 주문 19단계 + 조건부 보정 2 + 고객 자리 주문에만 있는 7단계
    assert len(STAGE_STEP) == 28
    assert set(STAGE_STEP.values()) == {1, 2, 3, 4, 5, 6, 7}


def test_resumable_stages_are_control_resume_stages():
    """관제 sakim 1b0cb08 RESUME_STAGES 와 같아야 중계 웹이 재개 버튼을 맞게 보인다."""
    assert set(RESUMABLE_STAGES) == {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER',
                                     'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'MOVE_RESTOCK'}
    assert len(RESUMABLE_STAGES) == len(set(RESUMABLE_STAGES))


def test_tables_follow_control_scenario_when_importable():
    """팀 패키지를 import 할 수 있으면 관제 단계·재개·이동 지점 표와 직접 대조한다."""
    contracts = pytest.importorskip('cobot_fleet_control.scenario_contracts')
    assert set(RESUMABLE_STAGES) == set(contracts.RESUME_STAGES)
    assert NAVIGATION_STAGES == set(contracts.NAVIGATION)
    # 구역 진입(zone 명령) 이동 단계만 진입 판정을 한다. 칸 이름은 관제 MOVE_POINT 와 같다.
    zone_moves = {s for s, op in contracts.NAVIGATION.items() if op == 'zone'}
    assert set(ZONE_ENTRY_STAGES) == zone_moves
    assert all(contracts.MOVE_POINT[s] == side for s, side in ZONE_ENTRY_STAGES.items())
    assert {s for s in contracts.WORK if s.startswith('CORRECT_')} <= set(STAGE_STEP)
    tree = pytest.importorskip('cobot_fleet_control.scenario_tree')
    assert set(tree.STAGES) | set(tree.CUSTOMER_STAGES) <= set(STAGE_STEP)


@pytest.mark.parametrize('stage,detail,step', [
    ('MOVE_PICKUP', 'slot0', 1), ('MOVE_PICKUP', 'ZA', 2), ('MARKER', '', 2), ('LOAD', '', 3),
    ('LEAVE_PICKUP', 'ZA_EXIT', 4), ('MOVE_DROPOFF', 'slot1', 4), ('MOVE_DROPOFF', 'ZC', 5),
    ('QR', '', 5), ('CUSTOMER', '', 6), ('RETURN_EXIT', '', 7),
])
def test_step_of(stage, detail, step):
    assert step_of(order(stage), {'detail': detail}, ROUTE) == step


@pytest.mark.parametrize('stage,detail,step', [
    ('MOVE_PICKUP', 'ZB', 2), ('VERIFY_LOAD', '', 3), ('MOVE_CUSTOMER', 'P22', 4),
    ('CUSTOMER', 'P22', 4), ('MOVE_ARRANGE', 'slot1', 4), ('MOVE_ARRANGE', 'ZC', 5),
    ('ARRANGE', '', 6), ('LEAVE_ARRANGE', 'ZC_EXIT', 4), ('MOVE_RESTOCK', 'ZA', 5),
    ('RESTOCK', '', 6), ('LEAVE_RESTOCK', 'ZA_EXIT', 7), ('RETURN_HOME', '', 7),
])
def test_step_of_customer_seat_order(stage, detail, step):
    completed = SEAT_BEFORE_CUSTOMER if stage not in SEAT_BEFORE_CUSTOMER else ()
    assert step_of(order(stage, completed), {'detail': detail}, SEAT_ROUTE) == step


def test_customer_seat_is_not_arm_unloading_even_without_route():
    """감시 경로 표에 col*__P22 가 없어 route 가 비어도 MOVE_CUSTOMER 를 지난 CUSTOMER 는 운송 단계다."""
    seat = order('CUSTOMER', SEAT_BEFORE_CUSTOMER)
    assert step_of(seat, None, {}) == CUSTOMER_SEAT_STEP == 4
    # 경로 주문 CUSTOMER(하차 팔이 내려놓은 뒤)는 그대로 하역 단계다.
    route_order = order('CUSTOMER', ['MOVE_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD'])
    assert step_of(route_order, None, {}) == 6


def test_step_without_status_stays_on_earlier_step():
    assert step_of(order('MOVE_PICKUP'), None, ROUTE) == 1


@pytest.mark.parametrize('stage,completed,cargo', [
    # omx2 E 모델은 pick 이 상자를 꺼내 핑키에 올리기까지 한다. PICK 도 상차 중이다(P1).
    ('PICK', ['PICKUP_EXIT'], 'LOADING'),
    ('LOAD', ['PICK'], 'LOADING'),
    ('VERIFY_LOAD', ['PICK', 'LOAD'], 'LOADING'),
    ('LEAVE_PICKUP', ['VERIFY_LOAD'], 'LOADED'),
    ('DOCK_DROPOFF', ['VERIFY_LOAD'], 'LOADED'),
    ('UNLOAD', ['VERIFY_LOAD'], 'UNLOADING'),
    ('CUSTOMER', ['VERIFY_LOAD', 'VERIFY_UNLOAD'], 'EMPTY'),
])
def test_cargo_of(stage, completed, cargo):
    assert cargo_of(order(stage, completed)) == cargo


@pytest.mark.parametrize('stage,completed,flags,cargo', [
    ('CUSTOMER', SEAT_BEFORE_CUSTOMER, {}, 'LOADED'),
    # 결제: 고객이 꺼내지만 빈 트레이를 확인한 센서가 없다. 비었다고 단정하지 않는다(D2).
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_received': True},
     'EMPTY_UNVERIFIED'),
    # 시간 초과: 신발을 실은 채 복귀한다.
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_timed_out': True}, 'LOADED'),
    # 회수: ZC 정리 뒤 핑키 위에 다시 올린다. ZA 반환 중에는 UNLOADING, 끝나면 EMPTY_UNVERIFIED(D2).
    ('ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE'],
     {'customer_declined': True}, 'LOADED'),
    ('RESTOCK', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE',
                                        'MOVE_RESTOCK'], {'customer_declined': True}, 'UNLOADING'),
    ('LEAVE_RESTOCK', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE',
                                              'LEAVE_ARRANGE', 'MOVE_RESTOCK', 'RESTOCK'],
     {'customer_declined': True}, 'EMPTY_UNVERIFIED'),
])
def test_cargo_of_customer_seat_order(stage, completed, flags, cargo):
    assert cargo_of(order(stage, completed, **flags)) == cargo


@pytest.mark.parametrize('extra,cargo', [
    # 운영자 수동 상차 확인: 관제는 VERIFY_LOAD 를 operator_completed 에만 넣는다(sakim scenario_safety).
    ({'operator_completed': ['PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD',
                             'VERIFY_LOAD']}, 'LOADED'),
    # 재기동 복원: 상자를 실은 채 MOVE_PICKUP 으로 다시 간다.
    ({'manual_load_pending': {'operator': 'kgh'}}, 'LOADED'),
    ({}, 'EMPTY'),
])
def test_cargo_of_operator_load_confirmation(extra, cargo):
    stage = 'LEAVE_PICKUP' if 'operator_completed' in extra else 'MOVE_PICKUP'
    assert cargo_of(order(stage, ['MOVE_PICKUP'], **extra)) == cargo


def test_outcome_and_residual_rules():
    seat_done = SEAT_BEFORE_CUSTOMER + ['CUSTOMER']
    paid = order('RETURN_HOME', seat_done, customer_received=True)
    declined = order('MOVE_ARRANGE', seat_done, customer_declined=True)
    timeout = order('RETURN_HOME', seat_done, customer_timed_out=True)
    route_paid = order('LEAVE_DROPOFF', ['VERIFY_UNLOAD', 'CUSTOMER'], customer_received=True)
    assert [outcome_of(o, {}) for o in (paid, declined, timeout, route_paid)] == [
        'PAID', 'DECLINED', 'TIMEOUT', 'RECEIVED']
    assert outcome_of(order('CUSTOMER', SEAT_BEFORE_CUSTOMER), {}) == ''
    # 신발을 실은 채 끝나는 것은 자리 주문 시간 초과뿐이다. 경로 주문 시간 초과는 하차 뒤라 비어 있다.
    assert leaves_residual(timeout, {}) and not leaves_residual(paid, {})
    route_timeout = order('LEAVE_DROPOFF', ['VERIFY_UNLOAD', 'CUSTOMER'], customer_timed_out=True)
    assert not leaves_residual(route_timeout, {})
    # 잔류 화물은 운영자 확인으로만 지운다. 뒤 주문으로 지우는 규칙(clears_residual)은 없앴다(11-21 재검토).


@pytest.mark.parametrize('extra', [
    {'operator_completed': None}, {'completed': None},
    {'completed': None, 'operator_completed': None}, {'operator_completed': {'VERIFY_LOAD': 1}},
    {'completed': 5}, {'completed': [['MARKER'], 'PICK']},
])
def test_null_or_odd_completed_lists_do_not_raise(extra):
    """관제 스냅샷 콜백에서 터지지 않게 목록이 아닌 값은 빈 것으로 본다."""
    odd = dict(order('LEAVE_PICKUP', []), **extra)
    assert done_stages(odd) <= {'PICK'}
    assert cargo_of(odd) == 'EMPTY'
    assert is_customer_order(odd, {}) is False
    assert is_customer_order(dict(odd, stage=['MOVE_CUSTOMER']), {}) is False


@pytest.mark.parametrize('reason,op_state', [
    ('ESTOP', 'ESTOP'), ('STOP', 'ESTOP'), ('PAUSE', 'PAUSED'), ('PAUSED', 'PAUSED'),
    ('MANUAL', 'MANUAL'), ('UNKNOWN', 'UNKNOWN'), ('LINK_LOST', 'LINK_LOST'),
    ('RESET_UNCONFIRMED', 'RESET_UNCONFIRMED'), ('', 'PAUSED'), ('NEW_REASON', 'PAUSED'),
    ({'reason': 'ESTOP'}, 'PAUSED'), (['ESTOP'], 'PAUSED'), (None, 'PAUSED'), (5, 'PAUSED'),
])
def test_hold_op_state(reason, op_state):
    assert hold_op_state(reason) == op_state


@pytest.mark.parametrize('stage,completed,extra,driving,phase', [
    ('PICK', ['MARKER'], {}, False, 'PICK'),
    ('LOAD', ['PICK'], {}, False, 'LOADING'),
    ('QR', ['VERIFY_LOAD'], {}, False, 'TRANSIT'),
    ('UNLOAD', ['VERIFY_LOAD'], {}, False, 'UNLOADING'),
    ('RESTOCK', ['VERIFY_LOAD'], {}, False, 'UNLOADING'),
    ('ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {}, False, 'ARRANGE'),
    ('LEAVE_ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'ARRANGE'], {}, True, 'TRANSIT'),
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_timed_out': True}, False,
     'TRANSIT'),
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_received': True}, True,
     'RESIDUAL'),
    ('RETURN_HOME', ['VERIFY_UNLOAD'], {}, True, None),
    ('MOVE_PICKUP', [], {}, True, None),
    # 경로 주문 CUSTOMER 는 하차 뒤라 옛 하역 단계(6) 그대로다.
    ('CUSTOMER', ['MOVE_DROPOFF', 'VERIFY_UNLOAD'], {}, False, 'UNLOADING'),
])
def test_phase_of(stage, completed, extra, driving, phase):
    item = order(stage, completed, **extra)
    assert phase_of(item, None, {}, cargo_of(item), driving) == phase


def test_paused_drive_with_cargo_stays_transit():
    """잔류 화물을 실은 채 받은 다음 주문의 MOVE_PICKUP 은 정지로 잠깐 서도 운송이다(분류가 흔들리지 않게)."""
    item = order('MOVE_PICKUP')
    assert phase_of(item, {'detail': 'ZB'}, ROUTE, 'LOADED', False) == 'TRANSIT'
    assert phase_of(order('MARKER', ['MOVE_PICKUP']), None, ROUTE, 'LOADED', False) == 'RESIDUAL'


def test_phase_without_order_follows_cargo():
    assert phase_of(None, None, {}, 'LOADED', False) == 'RESIDUAL'
    assert phase_of(None, None, {}, 'LOADED', True) == 'TRANSIT'
    assert phase_of(None, None, {}, 'EMPTY', True) is None


def _robot(seat_order, step, driving=False, status=None, route=None):
    cargo = cargo_of(seat_order)
    return {'pinky1': {'order_id': 'seat1', 'stage': seat_order['stage'], 'step_seq': step,
                       'cargo_state': cargo,
                       'phase': phase_of(seat_order, status, route or {}, cargo, driving),
                       'pose_x': 0.0, 'pose_y': 0.0, 'driving': driving, 'queue_wait': False}}


def _floor_box(distance, name='box_on_floor'):
    return {'event_id': 'e1', 'camera_id': 'ceil_cam', 'vision_class': name,
            'confidence': 0.9, 'map_x': distance, 'map_y': 0.0}


def _verdict(seat_order, step, distance, name='box_on_floor', **extra):
    result = judge(_floor_box(distance, name), _robot(seat_order, step, **extra))
    return result['judgment'], result['stop_scope'], result['linked_robot_id']


def test_seat_steps_change_drop_classification_as_documented():
    """
    자리 주문 단계별 사고 분류. 표시 단계는 앞으로만 가지만 판정은 지금 단계·적재로 고른다.

    - 고객 자리 CUSTOMER 는 고객 인계 국면이다. 범위는 11-20 전(하역 단계 6, 로봇 한 대)과 같다(D1).
    - MOVE_ARRANGE 주행 중 낙하는 TRANSIT_DROP 이다.
    - ARRANGE 는 정리(다시 올림)라 ARRANGE_FAIL, RESTOCK 은 하역(UNLOAD_FAIL)이다. 범위는 로봇 한 대다.
    - 결제 뒤에는 비었는지 모른다. 바닥 상자는 로봇을 지목하되 전체 정지 그대로다(D2).
    """
    waiting = order('CUSTOMER', SEAT_BEFORE_CUSTOMER)
    step = step_of(waiting, None, {})
    assert _verdict(waiting, step, 0.3) == ('CUSTOMER_HANDOVER_DROP', 'ROBOT', 'pinky1')
    assert _verdict(waiting, step, 0.52) == ('LANE_OBSTACLE', 'ALL', None)
    assert _verdict(waiting, step, 0.05, 'box_perched_on_rim') == (
        'CUSTOMER_HANDOVER_PERCHED', 'ROBOT', 'pinky1')
    moving = order('MOVE_ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], customer_declined=True)
    step = max(step, step_of(moving, {'detail': 'ZC'}, SEAT_ROUTE))
    assert step == 5
    assert _verdict(moving, step, 0.3, driving=True)[:2] == ('TRANSIT_DROP', 'ALL')
    arranging = order('ARRANGE', moving['completed'] + ['MOVE_ARRANGE'], customer_declined=True)
    step = max(step, step_of(arranging, None, SEAT_ROUTE))
    assert _verdict(arranging, step, 0.3) == ('ARRANGE_FAIL', 'ROBOT', 'pinky1')
    paid = order('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], customer_received=True)
    assert _verdict(paid, 7, 0.3, driving=True) == ('RESIDUAL_DROP', 'ALL', 'pinky1')
    assert _verdict(paid, 7, 0.05, 'box_perched_on_rim', driving=True) == (
        'RESIDUAL_PERCHED', 'ROBOT', 'pinky1')


def test_queueing_counts_as_driving_and_waits_only_when_still():
    status = {'state': 'QUEUEING'}
    assert driving_of(status)
    assert queue_wait_of(status, 0.0) and not queue_wait_of(status, 0.2)
    assert not queue_wait_of(status, None)
    assert not queue_wait_of({'state': 'MOVING'}, 0.0)


def test_zone_and_op_state():
    assert zone_of({'held_zone': 'A'}, True) == 'ZONE_A'
    assert zone_of({'state': 'MOVING'}, True) == 'LANE'
    assert zone_of({'state': 'IDLE'}, False) == 'HOME'
    assert op_state_of(None, False) == 'OFFLINE'
    assert op_state_of({'state': 'QUEUEING'}, True) == 'WAITING_QUEUE'
    assert op_state_of({'state': 'HOLDING_ZONE', 'held_zone': 'A'}, True) == 'WAIT_ARM'
    assert op_state_of({'state': 'MOVING', 'central_latched': True}, True) == 'HOLD_ANOMALY'
