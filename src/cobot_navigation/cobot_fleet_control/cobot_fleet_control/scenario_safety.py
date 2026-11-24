"""중단과 현장 확인 복구. 통신 복구만으로 물리 작업을 재개하지 않는다."""

import time

from .control_release import require_stopped

from .scenario_contracts import (ARM_STAGES, BLOCKED, CANCEL_STAGES, HAND_DONE, identifier,
                                 is_customer_route, NAVIGATION, operator_name, operator_or_default,
                                 optional_text, order_stages, PICKUP_STAGES, RESUME_STAGES,
                                 RETRY_FROM, TERMINAL)


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
        service.releases.cancel(order['robot_id'])
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
    operator = operator_name(operator)
    order = service.store.get(identifier(order_id, 'order_id'))
    if not order:
        raise ValueError('없는 주문')
    _check_load_evidence(order, note, evidence)
    if order.get('operator_load_confirmation'):
        return order
    if order.get('manual_load_pending') and order['stage'] == 'MOVE_PICKUP':
        return order
    restoring, latched = _check_load_ready(service, order)
    robot = order['robot_id']
    confirmation = dict(operator=operator, note=note.strip(), evidence=dict(evidence),
                        confirmed_at=time.time(), previous_stage=order['stage'],
                        previous_state=order['state'], previous_request_id=order['request_id'])
    reset_id = service.gateway.release(robot) if latched else None
    runtime = service.trees.pop(order_id, None)
    if runtime:
        runtime.cancel()
    order.update(state='RUNNING', request_id=None, attempt=0,
                 reset_pending=latched, reset_request_id=reset_id)
    if restoring:
        event = 'operator_load_confirmation_pending'
        order.update(stage='MOVE_PICKUP', detail='수동 상차 확인 접수: 재기동 후 상차 구역 재확인',
                     manual_load_pending=confirmation)
    else:
        event = 'operator_load_confirmed'
        order.update(stage='LEAVE_PICKUP', detail='운영자 수동 상차 확인: ' + note.strip(),
                     operator_completed=list(PICKUP_STAGES),
                     operator_load_confirmation=confirmation)
        order.pop('manual_load_pending', None)
    service._save(order)
    service.store.event(dict(type=event, order_id=order_id,
                             robot_id=robot, confirmation=confirmation))
    service.deadlines.pop(order_id, None)
    if latched:
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    service.store.clear_hold(robot)
    return service.store.get(order_id)


def _check_load_evidence(order, note, evidence):
    """운영자가 주문 상품의 실제 적재와 안전을 모두 확인했는지 본다."""
    if not isinstance(note, str) or not note.strip():
        raise ValueError('수동 상차 확인 근거 note 필요')
    required = ('load_present', 'arm_safe', 'pickup_path_clear')
    if (not isinstance(evidence, dict)
            or any(evidence.get(key) is not True for key in required)
            or evidence.get('sku') != order['sku']):
        raise ValueError('주문 SKU·실제 적재·팔 퇴피·진입 통로 이탈 확인 필요')


def _check_load_ready(service, order):
    """수동 상차를 받을 수 있는 주문·로봇·예약인지 보고 (재기동 복구 여부, 정지 래치)를 돌려준다."""
    if (order['state'] not in {'RUNNING', 'UNKNOWN'}
            or order['stage'] not in set(PICKUP_STAGES) | {'CORRECT_PICKUP'}
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
    # 고객 자리 주문은 상차장만 예약한다 (회수 구역은 갈 때 잡음). MOVE_PICKUP 예약과 같아야 한다.
    sides = ('pickup',) if is_customer_route(service._route(order)) else ('pickup', 'dropoff')
    needed = {name for side in sides for name in service._station(order, side)}
    if not needed <= set(service.store.resources(order['order_id'])):
        raise ValueError('주문의 상하차 작업장·팔 예약 확인 필요')
    latched = status.get('central_latched')
    if not isinstance(latched, bool):
        raise ValueError('로봇 정지 래치 상태 확인 필요')
    return restoring, latched


def request_cancel(service, order_id, operator, note, evidence, source=''):
    """
    진행 중 고객 자리 주문의 직원 취소. 로봇을 세우지 않고 지금 명령을 마친 뒤 홈 복귀나 선반 반납으로 바꾼다.

    실제 길은 트리(scenario_nodes)가 다음 명령 앞에서 고른다. 되돌릴 수 없다.
    """
    operator = operator_or_default(operator)
    note = optional_text(note, '취소 note', '화면에서 주문 취소')
    order = service.store.get(identifier(order_id, 'order_id'))
    if not order:
        raise ValueError('없는 주문')
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError('evidence는 객체')
    if order['state'] in TERMINAL:
        raise ValueError('이미 끝난 주문')
    if order.get('cancel_requested'):
        return order
    if order['state'] != 'RUNNING' or not order['robot_id']:
        raise ValueError('진행 중인 주문만 취소 가능 (멈춘 주문·배정 전 주문은 주문 복구의 취소)')
    if order['kind'] != 'delivery' or not is_customer_route(service._route(order)):
        raise ValueError('고객 자리 주문만 자동 반납 취소 가능')
    runtime = service.trees.get(order_id)
    decided = runtime and (runtime.context.customer_received or runtime.context.customer_declined)
    if (order['stage'] not in CANCEL_STAGES or order['failure'] or order['customer_received']
            or order['customer_timed_out'] or order.get('customer_declined') or decided):
        raise ValueError('이미 구매·반납·복귀 중인 주문은 취소할 수 없음')
    if order['stage'] == 'CUSTOMER' and (evidence or {}).get('shoe_on_robot') is not True:
        raise ValueError('고객 응대 중 취소: 신발이 로봇 위에 있는지 확인 필요 (shoe_on_robot)')
    request = {'operator': operator, 'note': note, 'source': source, 'stage': order['stage'],
               'evidence': evidence, 'requested_at': time.time()}
    service._save(order, cancel_requested=request)
    service.store.event({'type': 'operator_cancel', 'order_id': order_id,
                         'robot_id': order['robot_id'], 'request': request})
    if runtime and order['stage'] == 'CUSTOMER':
        runtime.settle()
    return service.store.get(order_id)


# 운영자·메모는 선택. 자원을 예약한 주문의 취소에는 실제 정리 확인이 필요하다.
def recover(service, order_id, operator, note, decision, evidence, source=''):
    """
    정지·통신 복구 후에는 자동 재개하지 않고 운영자의 결정을 받는다.

    resume: 이동 단계는 이어서 가기, 팔 단계는 다시 하기(팔 퇴피·물건 제자리 확인).
    done: 하차·정리·선반 반환 팔 단계를 사람이 처리함으로 적고 다음 단계로. fail: 주문 취소.
    """
    operator = operator_or_default(operator)
    note = optional_text(note, '복구 note', '화면에서 현장 확인 후 복구')
    order = service.store.get(identifier(order_id, 'order_id'))
    # 로봇 배정 전 주문은 움직인 장치가 없어 멈추지 않고도 취소할 수 있다.
    unassigned = (decision == 'fail' and bool(order) and not order['robot_id']
                  and order['state'] in BLOCKED | {'WAITING'})
    if not order or (order['state'] not in BLOCKED and not unassigned):
        raise ValueError('중단된 주문만 복구 가능 (취소는 로봇 배정 전 주문도 가능)')
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError('evidence는 객체')
    if decision not in ('resume', 'done', 'fail'):
        raise ValueError('decision: resume, done 또는 fail')
    robot = order['robot_id']
    if robot:
        require_stopped(service, robot)
    on_shelf = False
    if decision == 'fail':
        on_shelf = not unassigned and _item_on_shelf(service, order, evidence)
        _check_cancel_evidence(service, order_id, evidence, on_shelf)
    stage = order['stage']
    checkpoint = None
    if decision in ('resume', 'done'):
        checkpoint = _checkpoint(order, stage, decision, evidence)
        if not service.armed or (robot and not service._fresh(robot)):
            raise ValueError('가동 허용 및 최신 통신 상태 필요')
    if robot:
        _request_release(service, order, decision, note)
    service.store.event(dict(type='recovery', order_id=order_id, operator=operator,
                             note=note, decision=decision, evidence=evidence, source=source,
                             stage=stage, checkpoint=checkpoint))
    # 현장 확인을 마친 뒤 정지된 하위 명령이 로봇 예약을 계속 잡고 있지 않도록 한다.
    if decision != 'fail':
        for command_id in service.fleet.repository.active_commands(robot):
            service.fleet.forget(command_id)
            service.fleet.repository.transition(command_id, 'FAILED', '시나리오 운영자 복구: ' + note)
    service.trees.pop(order_id, None)
    if decision == 'fail':
        order.update(state='FAILED', detail=note, request_id=None, updated_at=time.time())
        if unassigned:
            order['operator_cancelled'] = True  # 화면이 처리 실패와 구분하는 데 쓴다
        if on_shelf:
            order['operator_restocked'] = True
        # 배정 전이거나 집기 전에 취소한 주문, 사람이 선반에 돌려놓은 주문은 예약분을 반환한다.
        service.store.close_order(order, restock=order['kind'] == 'delivery' and (
            robot is None or on_shelf or bool(order.get('operator_cancelled'))))
    else:
        _apply_checkpoint(service, order, stage, checkpoint, decision)
        service._save(order, state='RUNNING' if robot else 'WAITING', request_id=None,
                      detail=note, reset_pending=bool(robot))
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    if robot and decision != 'fail':
        service.store.clear_hold(robot)
    return service.store.get(order_id)


def _item_on_shelf(service, order, evidence):
    """사람이 신발을 원래 선반 칸에 돌려놓았다고 확인했는지. 확인했으면 예약 재고를 돌려준다."""
    value = (evidence or {}).get('item_on_shelf', False)
    if not isinstance(value, bool):
        raise ValueError('item_on_shelf는 true 또는 false')
    if not value:
        return False
    if (order['kind'] != 'delivery' or order['customer_received']
            or not is_customer_route(service._route(order))):
        raise ValueError('구매 전 고객 자리 주문만 선반에 돌려놓을 수 있음 (item_on_shelf)')
    return True


def _check_cancel_evidence(service, order_id, evidence, required=False):
    """자원을 예약했거나 재고를 돌려놓는 주문은 실제 정리를 확인해야 취소한다."""
    if not required and not service.store.resources(order_id):
        return
    keys = ('arms_safe', 'cargo_reconciled', 'resources_clear')
    if not evidence or any(evidence.get(key) is not True for key in keys):
        raise ValueError('취소 전 팔 퇴피·화물 정리·작업장과 통로 이탈 확인 필요 '
                         '(arms_safe, cargo_reconciled, resources_clear)')


def _request_release(service, order, decision, note):
    """취소는 로봇 보류 해제를, 재개는 이 주문의 정지 해제를 요청한다."""
    robot, route = order['robot_id'], service._route(order)
    if decision == 'fail':
        service.releases.request(robot, note, route)
        return
    order['reset_request_id'] = service.gateway.release(robot, route)
    if not isinstance(order['reset_request_id'], str) or not order['reset_request_id']:
        raise RuntimeError('정지 해제 명령 ID 누락: 주문 보류 유지')


def _checkpoint(order, stage, decision, evidence):
    """이어서 가기·다시·사람이 처리함이 되는 단계인지 보고 다시 시작할 단계를 돌려준다."""
    evidence = evidence or {}
    if decision == 'resume' and stage in RESUME_STAGES:
        return stage
    if decision == 'resume' and stage in ARM_STAGES:
        # 팔이 움직인 뒤라 사람이 팔 퇴피와 물건을 처음 자리에 돌려놓은 것을 확인해야 다시 한다.
        if evidence.get('arms_safe') is not True or evidence.get('item_ready') is not True:
            raise ValueError('팔 단계 다시 하기: 팔 퇴피·물건 제자리 확인 필요 '
                             '(arms_safe, item_ready)')
        return RETRY_FROM.get(stage, stage)
    if decision == 'done' and stage in HAND_DONE:
        if evidence.get('arms_safe') is not True or evidence.get('item_placed') is not True:
            raise ValueError('사람이 처리함: 팔 퇴피·물건 놓음 확인 필요 (arms_safe, item_placed)')
        return HAND_DONE[stage]
    if decision == 'done':
        raise ValueError('사람이 처리함은 하차·정리·선반 반환 팔 단계에서만 (상차는 수동 상차 확인)')
    raise ValueError('물리 작업 중단은 fail로 종결 후 새 주문: 임의 재피킹 금지')


def _apply_checkpoint(service, order, stage, checkpoint, decision):
    """다시: 시작 단계부터 완료 기록·재시도 횟수를 지운다. 사람이 처리함: 건너뛴 단계를 사람 완료로."""
    if decision == 'resume' and stage in RESUME_STAGES:
        return
    stages = order_stages(service._route(order))
    if decision == 'resume':
        redo = set(stages[stages.index(checkpoint):stages.index(stage) + 1])
        order['completed'] = [s for s in order['completed'] if s not in redo]
        for name in redo:
            order['retries'].pop(name, None)
    else:
        done = stages[stages.index(stage):stages.index(checkpoint)]
        order['operator_completed'] = list(dict.fromkeys(
            list(order.get('operator_completed', [])) + list(done)))
    order.update(stage=checkpoint, attempt=0)
