"""관제 단계(경로 주문 21단계·고객 자리 주문 단계)와 7단계 대응, 적재 상태 계산 시험."""

from cobot_anomaly_monitor.judgment import judge
from cobot_anomaly_monitor.scenario_view import (
    cargo_of, CUSTOMER_SEAT_STEP, driving_of, op_state_of, queue_wait_of, RESUMABLE_STAGES,
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
    ('PICK', ['PICKUP_EXIT'], 'EMPTY'),
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
    # 결제: 고객이 꺼내지만 빈 트레이 실측 단계가 없어 LOADED 로 남긴다(11-20, 걸침 감지 유지).
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_received': True}, 'LOADED'),
    # 시간 초과: 신발을 실은 채 복귀한다.
    ('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], {'customer_timed_out': True}, 'LOADED'),
    # 회수: ZC 정리 뒤 핑키 위에 다시 올린다. ZA 반환 중에는 UNLOADING, 끝나도 실측이 없어 LOADED.
    ('ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE'],
     {'customer_declined': True}, 'LOADED'),
    ('RESTOCK', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE',
                                        'MOVE_RESTOCK'], {'customer_declined': True}, 'UNLOADING'),
    ('LEAVE_RESTOCK', SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE',
                                              'LEAVE_ARRANGE', 'MOVE_RESTOCK', 'RESTOCK'],
     {'customer_declined': True}, 'LOADED'),
])
def test_cargo_of_customer_seat_order(stage, completed, flags, cargo):
    assert cargo_of(order(stage, completed, **flags)) == cargo


def _robot(seat_order, step):
    return {'pinky1': {'order_id': 'seat1', 'step_seq': step, 'cargo_state': cargo_of(seat_order),
                       'pose_x': 0.0, 'pose_y': 0.0, 'driving': False, 'queue_wait': False}}


def _floor_box(distance):
    return {'event_id': 'e1', 'camera_id': 'ceil_cam', 'vision_class': 'box_on_floor',
            'confidence': 0.9, 'map_x': distance, 'map_y': 0.0}


def test_seat_steps_change_drop_classification_as_documented():
    """
    새 대응이 사고 분류에 주는 영향. 단계 번호는 앞으로만 가므로(monitor_core._step) 실제 순서대로 본다.

    - MOVE_ARRANGE 주행 중(4·5) 낙하는 TRANSIT_DROP 이다. 이전에는 CUSTOMER(6) 뒤라 하역 낙하였다.
    - 고객 자리 CUSTOMER(4)에서 핑키 옆 낙하도 TRANSIT_DROP(전체 정지)이다. P22 는 작업장이 아닌 주행 지점이다.
    - ARRANGE·RESTOCK(6) 근처 낙하는 그대로 UNLOAD_FAIL 이다.
    - 결제 뒤에는 적재가 비어 핑키를 지목하지 않는다.
    """
    waiting = order('CUSTOMER', SEAT_BEFORE_CUSTOMER)
    step = step_of(waiting, None, {})
    assert judge(_floor_box(0.3), _robot(waiting, step))['judgment'] == 'TRANSIT_DROP'
    moving = order('MOVE_ARRANGE', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], customer_declined=True)
    step = max(step, step_of(moving, {'detail': 'ZC'}, SEAT_ROUTE))
    assert step == 5
    assert judge(_floor_box(0.3), _robot(moving, step))['judgment'] == 'TRANSIT_DROP'
    arranging = order('ARRANGE', moving['completed'] + ['MOVE_ARRANGE'], customer_declined=True)
    step = max(step, step_of(arranging, None, SEAT_ROUTE))
    assert judge(_floor_box(0.3), _robot(arranging, step))['judgment'] == 'UNLOAD_FAIL'
    paid = order('RETURN_HOME', SEAT_BEFORE_CUSTOMER + ['CUSTOMER'], customer_received=True)
    result = judge(_floor_box(0.3), _robot(paid, 7))
    assert result['judgment'] == 'LANE_OBSTACLE' and result['linked_robot_id'] is None


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
