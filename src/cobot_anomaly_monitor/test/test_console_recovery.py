"""
콘솔 live·주문 창구의 11-21 보강 시험: 구매 취소(declined) 전달, 복구 길 안내, 팔 노드 없음, 경보.

복구 길 안내는 실제 관제(origin/sakim ScenarioService.confirm_loaded)가 받는지와 맞춰 본다.
"""

import json

from cobot_anomaly_monitor.console_api import (
    CONFIRM_LOADED_STAGES, ConsoleApi, SEAT_CONFIRM_NOTE)
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
from cobot_fleet_control.scenario_contracts import NAVIGATION
from harness import ROBOTS, Stack
from node_stub import fake_node, load_monitor_node
import pytest

EVIDENCE = {'sku': 'SHOE42', 'load_present': True, 'arm_safe': True, 'pickup_path_clear': True}
MISSING_OMX2 = '팔 노드 없음 (omx2_adapter 미발견)'
# 현장과 같은 팔 노드 상태: OMEN-11 omx3_adapter 만 떠 있고 omx2·omx1 서비스는 꺼져 있다.
FIELD_ARMS = {'omx1': False, 'omx2': False, 'omx3': True}


class Message:
    def __init__(self, payload):
        self.data = json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """
    현장처럼 작업 요청이 감시 노드의 _work_request(수신 기록·팔 노드 경고·어댑터)를 지나게 한다.

    경로 표는 감시 노드와 같이 layout_routes 로 만든다. 단계 제한 시간은 시험용으로 5초다.
    """
    module = load_monitor_node(monkeypatch)
    item = Stack(tmp_path)
    item.core.routes, _ = module.layout_routes(item.config)
    item.scenario.store.set_stock('SHOE42', 10, 3, 1)
    item.scenario.config['step_timeout_sec'] = 5.0
    item.scenario.config['customer_timeout_sec'] = 5.0
    node = fake_node(module, core=item.core, store=item.store, adapter=item.adapter)
    gateway = item.gateway

    def work(payload):
        target = payload['target']
        gateway.sequences[target] = gateway.sequences.get(target, 0) + 1
        node._work_request(Message(dict(payload, session_id='s1', seq=gateway.sequences[target],
                                        issued_at=item.wall(), ttl_sec=5.0)))

    gateway.work = work
    item.node = node
    yield item
    item.close()


def pump(stack):
    """관제 outbox(/control_center/task_events)를 감시에 넣는다."""
    for row in stack.repo.pending():
        stack.core.on_task_event(json.loads(row['payload']))
        stack.repo.acknowledge(row['event_id'])


def run_to(stack, order_id, done, limit=400):
    """주문을 done 까지 진행한다. CUSTOMER 에서는 아무 입력도 하지 않는다."""
    for _ in range(limit):
        stack.tick()
        order = stack.current(order_id)
        if done(order):
            return order
        if order['state'] == 'RUNNING' and order['request_id'] and order['stage'] != 'CUSTOMER':
            if order['stage'] in NAVIGATION:
                stack.drive(order)
            else:
                stack.approve(order)
    raise AssertionError('not reached: ' + order_id)


def at(stage):
    return lambda order: order['stage'] == stage and (order['request_id'] or stage == 'CUSTOMER')


def seat(stack, order_id='seat1'):
    return stack.scenario.submit({'order_id': order_id, 'sku': 'SHOE42', 'destination': 'P22'})


def mission(stack, order_id):
    stack.console.refresh()
    return next(m for m in stack.console.cached['missions'] if m['mission_id'] == order_id)


def stuck_at_pick(stack, order_id):
    """PICK 요청에 아무도 답하지 않아 관제 단계 제한 시간으로 UNKNOWN 이 된다."""
    order = run_to(stack, order_id, at('PICK'))
    for _ in range(8):
        stack.tick(1.0)
    order = stack.current(order_id)
    assert order['state'] == 'UNKNOWN' and order['stage'] == 'PICK', order
    return order


def confirm_loaded(stack, order_id):
    """관제에 직접 수동 상차 확인을 보낸다(콘솔은 이 type 을 전달하지 않는다)."""
    reply = stack.api.handle({'type': 'confirm_loaded', 'order_id': order_id, 'operator': 'kgh',
                              'note': '손으로 올림', 'evidence': EVIDENCE})
    return reply['status'], reply.get('body') or {}


def test_route_order_stuck_in_pickup_lists_confirm_loaded_and_the_control_accepts(stack):
    stack.order('route1', 'lab_delivery_zb')
    stuck_at_pick(stack, 'route1')
    row = mission(stack, 'route1')
    assert row['recovery'] == 'fail'
    assert row['recovery_options'] == ['fail', 'confirm_loaded'] and row['recovery_note'] == ''
    status, body = confirm_loaded(stack, 'route1')
    assert status == 200 and body['stage'] == 'LEAVE_PICKUP'
    stack.tick()
    assert mission(stack, 'route1')['recovery_options'] == []


def test_seat_order_stuck_in_pickup_does_not_list_confirm_loaded_and_the_control_refuses(stack):
    seat(stack)
    stuck_at_pick(stack, 'seat1')
    row = mission(stack, 'seat1')
    assert row['recovery_options'] == ['fail'] and row['recovery_note'] == SEAT_CONFIRM_NOTE
    status, body = confirm_loaded(stack, 'seat1')
    assert status == 400 and '예약' in body['detail']


def test_seat_order_is_recognised_even_without_the_seat_routes(stack):
    """경로 표에 자리 경로가 없던 옛 설정이어도 주문의 destination 으로 자리 주문을 안다."""
    seat(stack)
    stuck_at_pick(stack, 'seat1')
    stack.core.routes = dict(stack.routes)  # 시험 하네스 주행에는 경로가 필요해 멈춘 뒤에 바꾼다
    assert stack.core._route(stack.current('seat1')) == {}
    row = mission(stack, 'seat1')
    assert 'confirm_loaded' not in row['recovery_options']
    assert row['recovery_note'] == SEAT_CONFIRM_NOTE


def test_paused_route_order_does_not_list_confirm_loaded(stack):
    """관제는 RUNNING·UNKNOWN 주문만 수동 상차 확인을 받는다. PAUSED 는 거절한다."""
    stack.order('route1', 'lab_delivery_zb')
    order = run_to(stack, 'route1', at('PICK'))
    assert stack.control(type='pause', robot_id=order['robot_id'])[0] == 202
    stack.tick()
    assert stack.current('route1')['state'] == 'PAUSED'
    row = mission(stack, 'route1')
    assert row['recovery_options'] == ['fail'] and row['recovery_note'] == ''
    assert confirm_loaded(stack, 'route1')[0] == 400


def test_confirm_loaded_stages_are_the_control_pickup_stages():
    from cobot_fleet_control.scenario_tree import STAGES
    pickup = STAGES[STAGES.index('PICKUP_EXIT'):STAGES.index('VERIFY_LOAD') + 1]
    assert CONFIRM_LOADED_STAGES == set(pickup) | {'CORRECT_PICKUP'}


def test_resumable_blocked_order_lists_resume_and_fail(stack):
    stack.order('route1', 'lab_delivery_zb')
    order = run_to(stack, 'route1', lambda o: o['stage'] == 'MOVE_PICKUP' and o['request_id'])
    stack.control(type='pause', robot_id=order['robot_id'])
    stack.tick()
    row = mission(stack, 'route1')
    assert row['recovery'] == 'resume' and row['recovery_options'] == ['resume', 'fail']


def test_arm_request_without_its_node_shows_in_live_and_trace(stack):
    """현장처럼 omx3_adapter 만 있으면 omx2 PICK 에 아무도 답하지 않는다. 바로 보이게 한다."""
    stack.core.set_arm_nodes(FIELD_ARMS)
    stack.adapter.yielded = {'omx1', 'omx2', 'omx3'}  # 팀 팔 노드가 하나라도 있으면 전부 양보
    stack.order('route1', 'lab_delivery_zb')
    order = run_to(stack, 'route1', at('PICK'))
    stack.console.refresh()
    live = stack.console.cached
    assert live['arm_nodes'] == FIELD_ARMS and 'alarms' in live
    waits = [dict(w) for w in live['arm_waits']]
    assert isinstance(waits[0].pop('since'), float)  # 노드가 요청을 받은 벽시계 시각
    assert waits == [{
        'order_id': 'route1', 'robot_id': order['robot_id'], 'stage': 'PICK',
        'request_id': order['request_id'], 'target': 'omx2', 'detail': MISSING_OMX2}]
    assert stack.adapter.pending() == [] and stack.store.work(order['request_id']) is None
    status, body = stack.console.handle('GET', '/api/fms/orders/route1/trace', None)
    assert status == 200
    assert [(w['kind'], w['request_id'], w['detail']) for w in body['warnings']] == [
        ('arm_node_missing', order['request_id'], MISSING_OMX2)]
    pick = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
    assert pick['evidence_summary'].endswith(' · ' + MISSING_OMX2)
    assert pick['evidence_detail']['arm_node_missing'] == MISSING_OMX2
    others = [r for r in body['trace'] if r['stage_code'] != 'PICK']
    assert not any(MISSING_OMX2 in r['evidence_summary'] for r in others)
    # 노드가 다시 보이면 live 대기 목록에서 빠진다. 요청 때 남긴 경고는 결과가 올 때까지 행에 남는다.
    stack.core.set_arm_nodes(dict(FIELD_ARMS, omx2=True))
    stack.console.refresh()
    assert stack.console.cached['arm_waits'] == []
    body = stack.console.handle('GET', '/api/fms/orders/route1/trace', None)[1]
    pick = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
    assert MISSING_OMX2 in pick['evidence_summary']


def test_arm_node_lost_after_the_request_still_marks_the_current_row(stack):
    stack.core.set_arm_nodes({'omx1': True, 'omx2': True, 'omx3': True})
    stack.order('route1', 'lab_delivery_zb')
    run_to(stack, 'route1', at('PICK'))
    body = stack.console.handle('GET', '/api/fms/orders/route1/trace', None)[1]
    assert body['warnings'] == []
    pick = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
    assert MISSING_OMX2 not in pick['evidence_summary']
    stack.core.set_arm_nodes(FIELD_ARMS)
    body = stack.console.handle('GET', '/api/fms/orders/route1/trace', None)[1]
    pick = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
    assert pick['evidence_summary'].endswith(' · ' + MISSING_OMX2)
    stack.console.refresh()
    assert [w['target'] for w in stack.console.cached['arm_waits']] == ['omx2']


def test_answered_arm_request_is_not_marked(stack):
    stack.core.set_arm_nodes(FIELD_ARMS)
    stack.order('route1', 'lab_delivery_zb')
    order = run_to(stack, 'route1', at('PICK'))
    result = stack.adapter.approve(order['request_id'], 'kgh')  # 시험 환경의 수동 응답
    stack.store.observe_work('result', result, stack.wall())
    stack.console.refresh()
    assert stack.console.cached['arm_waits'] == []
    body = stack.console.handle('GET', '/api/fms/orders/route1/trace', None)[1]
    pick = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
    assert MISSING_OMX2 not in pick['evidence_summary']


def test_customer_timeout_alarm_is_in_the_order_trace_and_live(stack):
    seat(stack)
    run_to(stack, 'seat1', at('CUSTOMER'))
    for _ in range(7):
        stack.tick(1.0)
    pump(stack)
    assert stack.current('seat1')['customer_timed_out'] is True
    body = stack.console.handle('GET', '/api/fms/orders/seat1/trace', None)[1]
    assert [a['code'] for a in body['alarms']] == ['CUSTOMER_TIMEOUT']
    assert body['alarms'][0]['order_id'] == 'seat1'
    stack.console.refresh()
    assert 'CUSTOMER_TIMEOUT' in [a['code'] for a in stack.console.cached['alarms']]


def test_declined_is_forwarded_to_the_control(stack):
    seat(stack)
    run_to(stack, 'seat1', at('CUSTOMER'))
    status, body = stack.control(type='declined', order_id='seat1')
    assert status == 200 and body['customer_declined'] is True
    assert stack.requests[-1]['type'] == 'declined'
    order = run_to(stack, 'seat1', lambda o: o['stage'] == 'MOVE_ARRANGE')
    assert order['customer_declined'] is True


def test_declined_is_refused_when_the_console_is_read_only(tmp_path):
    store = MonitorStore(tmp_path / 'r.sqlite3')
    sent = []
    core = MonitorCore(store, {}, ROBOTS, sent.append)
    api = ConsoleApi(core, None, lambda job: job(), core.replies.get)
    assert api.handle('POST', '/api/fms/control', {'type': 'declined', 'order_id': 'o1'})[0] == 403
    observer = ConsoleApi(core, None, lambda job: job(), core.replies.get, commands=True,
                          observation_only=True)
    assert observer.handle('POST', '/api/fms/control',
                           {'type': 'declined', 'order_id': 'o1'})[0] == 403
    assert sent == []
    store.close()
