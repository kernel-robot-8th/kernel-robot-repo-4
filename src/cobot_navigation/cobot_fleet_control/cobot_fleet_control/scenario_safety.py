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


def confirm_loaded(service, order_id, operator, note, evidence):
    """센서 결과를 생성하지 않고, 현장 확인을 기록한 뒤 실제 구역 이탈부터 재개한다."""
    from .scenario_tree import STAGES

    identifier(operator, 'operator')
    order = service.store.get(identifier(order_id, 'order_id'))
    if not order:
        raise ValueError('없는 주문')
    if not isinstance(note, str) or not note.strip():
        raise ValueError('수동 상차 확인 근거 note 필요')
    required = ('load_present', 'arm_safe', 'pickup_path_clear')
    if (not isinstance(evidence, dict)
            or any(evidence.get(key) is not True for key in required)
            or evidence.get('sku') != order['sku']):
        raise ValueError('주문 SKU·실제 적재·팔 퇴피·진입 통로 이탈 확인 필요')
    if order.get('operator_load_confirmation'):
        return order
    if order.get('manual_load_pending') and order['stage'] == 'MOVE_PICKUP':
        return order
    pickup_stages = STAGES[STAGES.index('PICKUP_EXIT'):STAGES.index('VERIFY_LOAD') + 1]
    if (order['state'] not in {'RUNNING', 'UNKNOWN'}
            or order['stage'] not in set(pickup_stages) | {'CORRECT_PICKUP'}
            or 'MOVE_PICKUP' not in order['completed'] or not order['robot_id']
            or order['failure']):
        raise ValueError('상차장 도착 완료 후 상차 검증 중인 주문만 수동 확인 가능')
    robot = order['robot_id']
    status = service.health.get(robot, {}).get('status', {})
    restoring = not status.get('held_zone') and status.get('state') in {'IDLE', 'DONE'}
    if (not service._fresh(robot) or status.get('busy') is not False
            or status.get('central_controlled') is not True
            or (not restoring and not status.get('held_zone'))
            or (not restoring and 'arrived_zone' in status
                and status['arrived_zone'] != status.get('held_zone'))
            or (not restoring and status.get('state') not in {
                'HOLDING_ZONE', 'IDLE_WAIT', 'STOPPED'})
            or service.fleet.repository.busy(robot)):
        raise ValueError('최신 통신·배터리·중앙 제어·구역 보유·정지 상태 확인 필요')
    reserved = set(service.store.resources(order_id))
    if not set(service._station(order, 'pickup') + service._station(order, 'dropoff')) <= (
            reserved):
        raise ValueError('주문의 상하차 작업장·팔 예약 확인 필요')
    latched = status.get('central_latched')
    if not isinstance(latched, bool):
        raise ValueError('로봇 정지 래치 상태 확인 필요')
    confirmation = dict(operator=operator, note=note.strip(), evidence=dict(evidence),
                        confirmed_at=time.time(), previous_stage=order['stage'],
                        previous_state=order['state'], previous_request_id=order['request_id'])
    if latched:
        service.gateway.release(robot)
    runtime = service.trees.pop(order_id, None)
    if runtime:
        runtime.cancel()
    if restoring:
        order.update(state='RUNNING', stage='MOVE_PICKUP', request_id=None, attempt=0,
                     detail='수동 상차 확인 접수: 재기동 후 상차 구역 재확인',
                     manual_load_pending=confirmation, reset_pending=latched)
        service._save(order)
        service.store.event(dict(type='operator_load_confirmation_pending', order_id=order_id,
                                 robot_id=robot, confirmation=confirmation))
        service.deadlines.pop(order_id, None)
        if latched:
            service.deadlines[order_id] = service.clock() + service.config['stale_sec']
        service.store.clear_hold(robot)
        return service.store.get(order_id)
    order.update(state='RUNNING', stage='LEAVE_PICKUP', request_id=None, attempt=0,
                 detail='운영자 수동 상차 확인: ' + note.strip(), reset_pending=latched,
                 operator_completed=list(pickup_stages), operator_load_confirmation=confirmation)
    order.pop('manual_load_pending', None)
    service._save(order)
    service.store.event(dict(type='operator_load_confirmed', order_id=order_id,
                             robot_id=robot, confirmation=confirmation))
    service.deadlines.pop(order_id, None)
    if latched:
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    service.store.clear_hold(robot)
    return service.store.get(order_id)


# 운영자·메모는 선택 (화면 확인 창, 2026-11-09 임시 일반형). 화면은 확인 창 뒤 확인 4가지를 함께 보낸다.
# TODO(시나리오): 단계와 상관없이 확인 4가지를 요구한다. 신발매장 시나리오가 정해지면 멈춘 단계(stage)별로
#   필요한 항목만 묻고, 취소 뒤 홈 복귀·하차 완료 표시를 정한다 (draft/safety_locks_review.md 8절).
def recover(service, order_id, operator, note, decision, evidence):
    """정지·통신 복구 후에는 자동 재개하지 않고 현장 상태를 명시적으로 확인한다."""
    operator = operator or 'control-center'
    identifier(operator, 'operator')
    if note is not None and not isinstance(note, str):
        raise ValueError('복구 note는 문자열')
    note = (note or '').strip() or '화면에서 현장 확인 후 복구'
    order = service.store.get(identifier(order_id, 'order_id'))
    if not order or order['state'] not in BLOCKED:
        raise ValueError('중단된 주문만 복구 가능')
    required = {'base_stopped', 'arms_safe', 'cargo_reconciled', 'resources_clear'}
    if not isinstance(evidence, dict) or any(evidence.get(k) is not True for k in required):
        raise ValueError('정지·팔 퇴피·화물·통로/작업구역 확인이 필요합니다')
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
