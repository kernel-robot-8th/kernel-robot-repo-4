"""21단계와 7단계 대응, 적재 상태 계산 시험."""

from cobot_anomaly_monitor.scenario_view import (
    cargo_of, driving_of, op_state_of, queue_wait_of, STAGE_STEP, step_of, zone_of)
import pytest

ROUTE = {'pickup': 'ZA', 'dropoff': 'ZC'}


def order(stage, completed=()):
    return {'stage': stage, 'completed': list(completed)}


def test_every_team_stage_has_a_step():
    assert len(STAGE_STEP) == 21
    assert set(STAGE_STEP.values()) == {1, 2, 3, 4, 5, 6, 7}


@pytest.mark.parametrize('stage,detail,step', [
    ('MOVE_PICKUP', 'slot0', 1), ('MOVE_PICKUP', 'ZA', 2), ('MARKER', '', 2), ('LOAD', '', 3),
    ('LEAVE_PICKUP', 'ZA_EXIT', 4), ('MOVE_DROPOFF', 'slot1', 4), ('MOVE_DROPOFF', 'ZC', 5),
    ('QR', '', 5), ('CUSTOMER', '', 6), ('RETURN_EXIT', '', 7),
])
def test_step_of(stage, detail, step):
    assert step_of(order(stage), {'detail': detail}, ROUTE) == step


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
