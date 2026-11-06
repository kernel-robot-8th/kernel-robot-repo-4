"""중단과 현장 확인 복구. 통신 복구만으로 물리 작업을 재개하지 않는다."""

import time

from .scenario_contracts import BLOCKED, NAVIGATION, TERMINAL, identifier


def interrupt(service, order_id, state, detail):
    """진행 중인 시도의 결과를 무효화한 뒤 이동 로봇과 로봇팔에 소프트웨어 정지를 요청한다."""
    if state not in BLOCKED:
        raise ValueError('지원하지 않는 중단 상태')
    order = service.store.get(order_id)
    if not order or order['state'] in TERMINAL:
        raise ValueError('진행 중인 주문이 없습니다')
    if order['state'] == state and order['detail'] == detail:
        return order
    runtime = service.trees.get(order_id)
    previous_request = order['request_id']
    service._save(order, state=state, request_id=None, detail=detail)
    if runtime:
        runtime.cancel()
    if previous_request and order['stage'] in NAVIGATION:
        service.fleet.quarantine(previous_request, detail)
    if order['robot_id']:
        service.store.hold(order['robot_id'], state)
    service._alarm(order, state, detail)
    if order['robot_id']:
        # 비상정지는 구역 토큰을 유지한다. 일반 정지는 로봇팔 작업 영역으로 후퇴할 수 있다.
        try:
            service.gateway.halt(order['robot_id'], service._route(order), order['order_id'])
        except Exception as error:
            service._alarm(order, 'STOP_UNCONFIRMED', str(error))
    return service.store.get(order_id)


def recover(service, order_id, operator, note, decision, evidence):
    """정지·통신 복구 후에는 자동 재개하지 않고 현장 상태를 명시적으로 확인한다."""
    identifier(operator, 'operator')
    order = service.store.get(identifier(order_id, 'order_id'))
    if not order or order['state'] not in BLOCKED:
        raise ValueError('중단된 주문만 복구 가능')
    required = {'base_stopped', 'arms_safe', 'cargo_reconciled', 'resources_clear'}
    if not isinstance(evidence, dict) or any(evidence.get(k) is not True for k in required):
        raise ValueError('정지·팔 퇴피·화물·통로/작업구역 확인이 필요합니다')
    if not isinstance(note, str) or not note.strip():
        raise ValueError('복구 확인 근거 note 필요')
    if decision not in ('resume', 'fail'):
        raise ValueError('decision: resume 또는 fail')
    robot = order['robot_id']
    if decision == 'resume':
        if order['stage'] not in {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER'}:
            raise ValueError('물리 작업 중단은 fail로 종결 후 새 주문: 임의 재피킹 금지')
        if not service.armed or (robot and not service._fresh(robot)):
            raise ValueError('가동 허용 및 최신 통신 상태 필요')
    if robot:
        service.gateway.release(robot, service._route(order))
    service.store.event(dict(type='recovery', order_id=order_id, operator=operator,
                             note=note, decision=decision, evidence=evidence))
    # 현장 확인을 마친 뒤 정지된 하위 명령이 로봇 예약을 계속 잡고 있지 않도록 한다.
    for row in service.fleet.repository.db.execute(
            "SELECT command_id FROM commands WHERE robot_id=? AND state NOT IN "
            "('SUCCEEDED','FAILED')", (robot,)).fetchall():
        command_id = row[0]
        service.fleet.active.pop(command_id, None)
        service.fleet.traces.pop(command_id, None)
        service.fleet.repository.transition(command_id, 'FAILED', '시나리오 운영자 복구: ' + note)
    service.trees.pop(order_id, None)
    if decision == 'fail':
        order.update(state='FAILED', detail=note, request_id=None, updated_at=time.time())
        service.store.close_order(order)
    else:
        service._save(order, state='RUNNING' if robot else 'WAITING', request_id=None,
                      detail=note, reset_pending=bool(robot))
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    if robot:
        service.store.clear_hold(robot)
    return service.store.get(order_id)
