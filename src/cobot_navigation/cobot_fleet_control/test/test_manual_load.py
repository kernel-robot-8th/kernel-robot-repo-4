"""수동 상차는 센서 결과 위조 없이 현장 확인과 실제 구역 이탈로 재개한다."""

import json

import pytest

from test_scenario import Environment


@pytest.fixture
def env(tmp_path):
    """상차장 도착이 끝난 정지 로봇과 실제 SQLite를 준비한다."""
    instance = Environment(tmp_path / 'manual.sqlite3')
    instance.scenario.store.set_stock('SHOE42', 2)
    instance.order()
    instance.until('PICKUP_EXIT')
    instance.scenario.telemetry('pinky1', dict(
        state='HOLDING_ZONE', held_zone='A', busy=False,
        central_controlled=True, central_latched=False))
    yield instance
    instance.repo.close()


def request():
    """운영자가 확인한 사실을 센서 측정값과 구분해 전달한다."""
    return {'type': 'confirm_loaded', 'request_id': 'manual1', 'order_id': 'order1',
            'operator': 'operator1', 'note': '상품 적재·팔 퇴피·통로 이탈을 현장에서 확인',
            'evidence': {'sku': 'SHOE42', 'load_present': True,
                         'arm_safe': True, 'pickup_path_clear': True}}


def test_manual_load_keeps_real_exit_and_does_not_repeat_pick_or_load(env):
    """이전 상차 요청을 무효화하고 실제 leave 명령을 다음 타이머에서 한 번 보낸다."""
    old_request = env.current()['request_id']
    reply = env.api.handle(request())
    assert reply['status'] == 200
    order = env.current()
    assert order['stage'] == 'LEAVE_PICKUP' and order['request_id'] is None
    assert order['completed'] == ['MOVE_PICKUP']
    assert 'VERIFY_LOAD' in order['operator_completed']
    assert not env.scenario.result(dict(
        order_id='order1', robot_id='pinky1', stage='PICKUP_EXIT', request_id=old_request,
        source='vision', measured=True, finished=True, success=True, data={'clear': True}))
    env.tick()
    env.fleet.tick()
    assert env.gateway.sent[-1][1]['command'] == 'leave'
    assert not any(w['stage'] in {'PICK', 'LOAD', 'VERIFY_LOAD'} for w in env.gateway.work_sent)
    assert 'station_ZA' in env.scenario.store.resources('order1')
    assert env.api.handle(request())['status'] == 200
    events = [json.loads(row[0]) for row in env.repo.db.execute('SELECT payload FROM outbox')]
    assert len([event for event in events if event['type'] == 'operator_load_confirmed']) == 1


@pytest.mark.parametrize('key,value', [('sku', 'OTHER'), ('load_present', False),
                                     ('arm_safe', False), ('pickup_path_clear', False)])
def test_missing_or_wrong_operator_evidence_cannot_advance(env, key, value):
    """상품과 모든 현장 확인 값이 일치해야 수동 상차를 반영한다."""
    payload = request()
    payload['evidence'][key] = value
    assert env.api.handle(payload)['status'] == 400
    assert env.current()['stage'] == 'PICKUP_EXIT'


def test_timeout_recovery_waits_for_stop_latch_release_echo(env):
    """시간 초과 주문도 복구하지만 정지 래치 해제 반향 전에는 이동하지 않는다."""
    env.scenario.interrupt('order1', 'UNKNOWN', '단계 결과 시간 초과')
    status = dict(state='STOPPED', held_zone='A', busy=False,
                  central_controlled=True, central_latched=True)
    env.scenario.telemetry('pinky1', status)
    assert env.api.handle(request())['status'] == 200
    sent = len(env.gateway.sent)
    env.scenario.tick()
    env.fleet.tick()
    assert len(env.gateway.sent) == sent
    status['central_latched'] = False
    env.scenario.telemetry('pinky1', status)
    env.scenario.tick()
    env.fleet.tick()
    assert env.gateway.sent[-1][1]['command'] == 'leave'


def test_busy_or_stale_robot_cannot_confirm_load(env):
    """물리 동작 중이거나 통신이 만료되면 확인 결과를 적용하지 않는다."""
    env.scenario.health['pinky1']['status']['busy'] = True
    assert env.api.handle(request())['status'] == 400
    env.scenario.health['pinky1']['status']['busy'] = False
    env.now += 4
    assert env.api.handle(request())['status'] == 400


def test_restart_reacquires_pickup_zone_before_consuming_manual_confirmation(env):
    """재기동으로 구역 기억이 사라지면 같은 주문으로 구역을 재확인하고 이탈한다."""
    env.scenario.interrupt('order1', 'UNKNOWN', '관제 재시작')
    env.scenario.telemetry('pinky1', dict(state='IDLE', busy=False, held_zone=None,
                                       central_controlled=True, central_latched=False))
    assert env.api.handle(request())['status'] == 200
    assert env.current()['stage'] == 'MOVE_PICKUP'
    assert env.current()['manual_load_pending']['evidence']['load_present'] is True
    env.scenario.tick()
    env.fleet.tick()
    command_id = env.current()['request_id']
    assert env.gateway.sent[-1][1]['command'] == 'zone:ZA'
    env.scenario.telemetry('pinky1', dict(state='HOLDING_ZONE', busy=False, held_zone='A',
                                       central_controlled=True, central_latched=False))
    env.fleet.on_status('pinky1', dict(command_id=command_id, state='DONE', task_finished=True))
    env.fleet.tick()
    env.scenario.tick()
    assert env.current()['stage'] == 'LEAVE_PICKUP'
    assert 'manual_load_pending' not in env.current()
