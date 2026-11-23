"""중단과 현장 확인 복구. 통신 복구만으로 물리 작업을 재개하지 않는다."""

import time

from .control_release import require_stopped

from .scenario_contracts import (ARM_STAGES, BLOCKED, HAND_DONE, identifier, NAVIGATION,
                                 operator_or_default, optional_text, RESUME_STAGES, RETRY_FROM,
                                 TERMINAL)


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
    reset_id = service.gateway.release(robot) if latched else None
    runtime = service.trees.pop(order_id, None)
    if runtime:
        runtime.cancel()
    if restoring:
        order.update(state='RUNNING', stage='MOVE_PICKUP', request_id=None, attempt=0,
                     detail='수동 상차 확인 접수: 재기동 후 상차 구역 재확인',
                     manual_load_pending=confirmation, reset_pending=latched,
                     reset_request_id=reset_id)
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
                 operator_completed=list(pickup_stages), operator_load_confirmation=confirmation,
                 reset_request_id=reset_id)
    order.pop('manual_load_pending', None)
    service._save(order)
    service.store.event(dict(type='operator_load_confirmed', order_id=order_id,
                             robot_id=robot, confirmation=confirmation))
    service.deadlines.pop(order_id, None)
    if latched:
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    service.store.clear_hold(robot)
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
    if not order or order['state'] not in BLOCKED:
        raise ValueError('중단된 주문만 복구 가능')
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError('evidence는 객체')
    if decision not in ('resume', 'done', 'fail'):
        raise ValueError('decision: resume, done 또는 fail')
    robot = order['robot_id']
    if robot:
        require_stopped(service, robot)
    if decision == 'fail' and service.store.resources(order_id):
        required = ('arms_safe', 'cargo_reconciled', 'resources_clear')
        if not evidence or any(evidence.get(key) is not True for key in required):
            raise ValueError('취소 전 팔 퇴피·화물 정리·작업장과 통로 이탈 확인 필요 '
                             '(arms_safe, cargo_reconciled, resources_clear)')
    stage = order['stage']
    checkpoint = None
    if decision in ('resume', 'done'):
        checkpoint = _checkpoint(order, stage, decision, evidence)
        if not service.armed or (robot and not service._fresh(robot)):
            raise ValueError('가동 허용 및 최신 통신 상태 필요')
    if robot:
        if decision == 'fail':
            service.releases.request(robot, note, service._route(order))
        else:
            order['reset_request_id'] = service.gateway.release(robot, service._route(order))
            if not isinstance(order['reset_request_id'], str) or not order['reset_request_id']:
                raise RuntimeError('정지 해제 명령 ID 누락: 주문 보류 유지')
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
        # 배정 전에는 어떤 장치에도 보낼 수 없으므로 예약분을 확실히 반환할 수 있다.
        service.store.close_order(order, restock=order['kind'] == 'delivery' and robot is None)
    else:
        _apply_checkpoint(service, order, stage, checkpoint, decision)
        service._save(order, state='RUNNING' if robot else 'WAITING', request_id=None,
                      detail=note, reset_pending=bool(robot))
        service.deadlines[order_id] = service.clock() + service.config['stale_sec']
    if robot and decision != 'fail':
        service.store.clear_hold(robot)
    return service.store.get(order_id)


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
    from .scenario_tree import CUSTOMER_STAGES, STAGES
    stages = CUSTOMER_STAGES if 'customer' in service._route(order) else STAGES
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
