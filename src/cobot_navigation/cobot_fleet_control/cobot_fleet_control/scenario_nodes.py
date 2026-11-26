"""전체 업무 BT의 비동기 실행 노드와 안전·재시도 제어 노드."""

import math

import py_trees

from .scenario_contracts import (ARRANGE_STAGES, BEFORE_PICK_STAGES, BLOCKED, finite,
                                 is_customer_route, LEAVE_SIDE, skips_arrange, TERMINAL)


Status = py_trees.common.Status


class SafetyGate(py_trees.decorators.Decorator):
    """
    매번 안전 조건을 검사한다. 작업 명령(주문 받기)을 끈 동안에도 트리는 돈다.

    꺼짐은 새 장치 명령만 막는다. 이미 보낸 명령의 결과와 고객 결제·회수 입력은 계속 반영해야
    다시 켤 때 끝난 주행을 시간 초과로 보거나 고객 입력을 잃지 않는다 (2026-11-26).
    """

    def __init__(self, context, child):
        super().__init__('안전 감시·가동 허용', child)
        self.ctx = context

    def update(self):
        return self.decorated.status

    def tick(self):
        ctx, service = self.ctx, self.ctx.service
        order = ctx.order
        permit = True
        if order['state'] in TERMINAL | BLOCKED:
            self.status, permit = Status.FAILURE, False
        elif not service._fresh(order['robot_id']):
            ctx.interrupt('통신·배터리 상태 수신 만료')
            self.status, permit = Status.FAILURE, False
        else:
            status = service.health[order['robot_id']]['status']
            latched = status.get('central_latched')
            reset_unconfirmed = order.get('reset_pending') and (
                latched is not False or status.get('busy') is not False
                or (order.get('reset_request_id')
                    and status.get('control_reset_id') != order['reset_request_id']))
            if latched is True or reset_unconfirmed:
                if (order.get('reset_pending')
                        and service.clock() < service.deadlines.get(order['order_id'], -math.inf)):
                    self.feedback_message = '로봇 정지 잠금 해제 응답 대기'
                    self.status, permit = Status.RUNNING, False
                else:
                    ctx.interrupt('로봇 로컬 정지 래치·복구 반향 미확인')
                    self.status, permit = Status.FAILURE, False
            elif order.get('reset_pending'):
                ctx.save(reset_pending=False)
                service.deadlines.pop(order['order_id'], None)
        if permit:
            if service.armed:
                self.feedback_message = '최신 상태·가동 허용 확인'
            else:
                # 이번 순회에서만 명령 전달을 막는다. ScenarioRuntime.tick 이 매번 다시 정한다.
                ctx.allow_dispatch = False
                self.feedback_message = '작업 명령 꺼짐: 새 명령 없이 결과만 반영'
            for node in self.decorated.tick():
                yield node
            self.status = self.decorated.status
        yield self


class SafeRetry(py_trees.decorators.Decorator):
    """노드가 안전한 확정 실패로 기록한 경우에만 하위 작업을 다음 갱신에서 재시도한다."""

    def __init__(self, context, name, child):
        super().__init__(name, child)
        self.ctx = context

    def update(self):
        if not self.ctx.running:
            return Status.FAILURE
        if self.decorated.status == Status.FAILURE:
            if self.ctx.order['failure']:
                return Status.FAILURE
            self.feedback_message = '안전 실패: 영속 재시도 예산 확인 후 재실행'
            return Status.RUNNING
        return self.decorated.status


class Step(py_trees.behaviour.Behaviour):
    """명령 전달과 결과 대기를 한 번씩 진행하며 콜백 안에서 대기하지 않는다."""

    def __init__(self, context, stage, name):
        super().__init__(name)
        self.ctx, self.stage = context, stage

    def update(self):
        ctx = self.ctx
        if self.stage in ctx.skip_stages:
            self.feedback_message = '현장 확인 복구 체크포인트 이전 단계'
            return Status.SUCCESS
        if not ctx.running:
            return Status.FAILURE
        if ctx.order.get('cancel_requested') and not (
                ctx.order['stage'] == self.stage and ctx.order['request_id']):
            # 이미 보낸 명령은 끝까지 기다리고, 아직 안 보낸 명령 앞에서만 길을 바꾼다.
            if self.stage == 'MOVE_CUSTOMER':
                self.feedback_message = '직원 취소: 고객 자리를 건너뛰고 반납'
                return Status.SUCCESS
            if self.stage in ARRANGE_STAGES and skips_arrange(ctx.order):
                self.feedback_message = '직원 취소: 열지 않은 상자라 정리를 건너뜀'
                return Status.SUCCESS
            # 사람이 실었다고 확인한 주문(manual_load_pending)은 집기 전이어도 신발이 로봇 위에 있다.
            if (self.stage in BEFORE_PICK_STAGES and not ctx.order.get('pick_started')
                    and not ctx.order.get('manual_load_pending')):
                # 피킹 전 실패와 같은 안전 복귀 분기로 보낸다.
                ctx.save(failure='직원 취소: 상품을 집기 전이라 홈 복귀', operator_cancelled=True,
                         request_id=None, attempt=0)
                return Status.FAILURE
        ctx.enter(self.stage)
        if not ctx.order['request_id']:
            ctx.dispatch(self.stage)
            self.feedback_message = ('명령 결과 대기' if ctx.order['request_id']
                                     else '자원 또는 타이머의 명령 전달 대기')
            return Status.RUNNING if ctx.running else Status.FAILURE
        # 결과를 먼저 본다. 갱신이 늦어 기한 뒤에 확인한 성공도 이미 끝난 일이다.
        # 장치 결과는 receive() 가 받을 때 기한을 이미 검사했다.
        status = self.poll()
        if (status == Status.RUNNING and ctx.service.clock()
                >= ctx.service.deadlines.get(ctx.order['order_id'], math.inf)):
            ctx.interrupt('단계 결과 시간 초과')
            return Status.FAILURE
        return status

    def poll(self):
        raise NotImplementedError


class NavigationStep(Step):
    """하위 주행 BT가 동일 명령의 실제 종료를 확인했는지 조회한다."""

    def poll(self):
        ctx = self.ctx
        row = ctx.service.fleet.repository.get(ctx.order['request_id'])
        if row['state'] == 'SUCCEEDED':
            side = LEAVE_SIDE.get(self.stage)
            if side:
                ctx.service.store.release(
                    ctx.order['order_id'], ctx.service._station(ctx.order, side))
            ctx.complete(self.stage)
            self.feedback_message = '주행 종료 확인'
            return Status.SUCCESS
        if row['state'] in {'FAILED', 'UNKNOWN'}:
            ctx.interrupt('주행 실패·결과 불명: 현장 확인')
            return Status.FAILURE
        return Status.RUNNING


class DeviceStep(Step):
    """현재 단계의 실측 최종 결과를 소비한다. 결과가 없으면 계속 실행 중으로 남는다."""

    def poll(self):
        ctx, result = self.ctx, self.ctx.pending
        if result is None:
            return Status.RUNNING
        ctx.pending = None
        data = result.get('data', {})
        if result['success'] is False:
            if data.get('retry_safe') is not True:
                ctx.interrupt('재시도 안전성 미확인')
            else:
                ctx.retry(self.stage, str(result.get('detail', '장치 단계 실패')))
            return Status.FAILURE
        if not self.accept(data):
            self.feedback_message = '완료 증거 부족: 추가 실측 결과 대기'
            return Status.RUNNING if ctx.running else Status.FAILURE
        ctx.complete(self.stage)
        self.feedback_message = '실측 완료 확인'
        return Status.SUCCESS

    def accept(self, data):
        return True


class MatchSku(DeviceStep):
    """인식 결과가 주문 상품과 다르면 피킹 전에 보류한다."""

    def accept(self, data):
        if data.get('sku') != self.ctx.order['sku']:
            self.ctx.interrupt('상품 불일치: 자동 피킹 금지')
            return False
        return True


class VerifyCargo(DeviceStep):
    """상하차 결과와 로봇팔 퇴피 증거를 함께 확인한다."""

    def accept(self, data):
        fields = (('load_present', 'arm_safe') if self.stage == 'VERIFY_LOAD'
                  else ('placed', 'arm_safe', 'load_absent'))
        return all(data.get(key) is True for key in fields)


class PathClear(DeviceStep):
    """후미 이탈이 실측되기 전까지 공유 통로 예약을 유지한다."""

    def accept(self, data):
        if data.get('clear') is not True:
            return False
        self.ctx.service.store.release(
            self.ctx.order['order_id'], ['lane_' + self.ctx.service._route(self.ctx.order)['lane']])
        return True


class MeasureDock(DeviceStep):
    """정차 공차와 실제 정지 증거를 읽고 보정 여부는 선택 노드가 결정하게 한다."""

    def accept(self, data):
        if not all(finite(data.get(key)) for key in ('xy_m', 'yaw_deg')):
            return False
        if self.within(data) and not (
                data.get('stopped') is True and data.get('base_hold') is True):
            return False
        self.ctx.dock_data[self.stage] = data
        return True

    def within(self, data):
        config = self.ctx.service.config
        return (abs(data['xy_m']) <= config['dock_xy_m']
                and abs(data['yaw_deg']) <= config['dock_yaw_deg'])


class DockTolerance(py_trees.behaviour.Behaviour):
    """측정값이 공차를 벗어나면 정밀 보정 하위 트리로 분기한다."""

    def __init__(self, measurement):
        super().__init__('정차 공차 확인')
        self.measurement = measurement

    def update(self):
        step = self.measurement
        if step.stage in step.ctx.skip_stages:
            return Status.SUCCESS
        return (Status.SUCCESS if step.within(step.ctx.dock_data[step.stage])
                else Status.FAILURE)


class CorrectionBudget(py_trees.behaviour.Behaviour):
    """정차 재보정 횟수를 기록하고 피킹 전 예산 소진만 안전 복귀 분기로 보낸다."""

    def __init__(self, context, stage):
        super().__init__('정차 재보정 예산 확인')
        self.ctx, self.stage = context, stage

    def update(self):
        if not self.ctx.running or self.ctx.order['failure']:
            return Status.FAILURE
        return (Status.SUCCESS if self.ctx.retry(self.stage, '정차 공차 초과')
                else Status.FAILURE)


class CustomerReceipt(py_trees.behaviour.Behaviour):
    """수령 입력 또는 제한 시간까지 비동기로 기다린 뒤 복귀를 허용한다."""

    def __init__(self, context):
        super().__init__('고객 수령 확인·제한 시간')
        self.ctx = context

    def update(self):
        ctx = self.ctx
        if 'CUSTOMER' in ctx.skip_stages or ctx.order['kind'] == 'return':
            self.feedback_message = '회수 주문 또는 복구 체크포인트: 수령 대기 생략'
            return Status.SUCCESS
        if ctx.order.get('cancel_requested'):
            ctx.service._alarm(ctx.order, 'ORDER_CANCELLED',
                               '직원 취소: 반환 구역 → 복귀' if skips_arrange(ctx.order)
                               else '직원 취소: 정리 구역 → 반환 구역 → 복귀')
            ctx.save(customer_declined=True)
            if ctx.order['stage'] == 'CUSTOMER':
                ctx.complete('CUSTOMER')
            return Status.SUCCESS
        ctx.enter('CUSTOMER')
        customer = is_customer_route(ctx.service._route(ctx.order))
        if ctx.customer_received:
            ctx.save(customer_received=True)
        elif ctx.customer_declined:
            if customer:
                # 고객 자리 주문: 핑키 위 신발을 ZC 에서 정리하고 ZA 선반에 반환한 뒤 복귀한다.
                ctx.service._alarm(ctx.order, 'CUSTOMER_DECLINED',
                                   '고객 회수 요청: 정리 구역 → 반환 구역 → 복귀')
            else:
                # 새 물리 동작 없이 시간 초과와 같은 복귀 경로를 쓴다.
                ctx.service._alarm(ctx.order, 'CUSTOMER_DECLINED', '고객 구매 취소: 기록 후 복귀')
            ctx.save(customer_declined=True)
        elif ctx.service.clock() >= ctx.service.deadlines[ctx.order['order_id']]:
            limit = f"{ctx.service.config['customer_timeout_sec']:g}초"
            ctx.service._alarm(
                ctx.order, 'CUSTOMER_TIMEOUT',
                f'{limit} 결제·회수 무응답: 신발을 실은 채 HOME 복귀, 운영자 재고 확인 필요'
                if customer else f'{limit} 수령 무응답: 기록 후 복귀')
            ctx.save(customer_timed_out=True)
        else:
            return Status.RUNNING
        ctx.complete('CUSTOMER')
        return Status.SUCCESS


class CustomerDeclined(py_trees.behaviour.Behaviour):
    """
    고객 회수 여부 조건. declined=True 는 회수한 주문, False 는 결제·시간 초과 주문에서만 성공한다.

    회수 분기가 도중에 실패해도 '바로 복귀' 쪽으로 새지 않게 두 조건을 따로 둔다.
    """

    def __init__(self, context, declined=True):
        super().__init__('고객 회수 요청 확인' if declined else '결제·시간 초과: 바로 복귀')
        self.ctx, self.declined = context, declined

    def update(self):
        return (Status.SUCCESS if bool(self.ctx.order.get('customer_declined')) == self.declined
                else Status.FAILURE)


class FinishOrder(py_trees.behaviour.Behaviour):
    """트리의 끝에서 필수 단계와 자원 정리를 확인하고 주문을 종결한다."""

    def __init__(self, context, mandatory):
        super().__init__('필수 단계 확인·주문 종결')
        # mandatory: 단계 집합, 또는 주문을 받아 집합을 돌려주는 함수 (분기마다 필수 단계가 다를 때)
        self.ctx, self.mandatory = context, mandatory

    def update(self):
        mandatory = (self.mandatory(self.ctx.order) if callable(self.mandatory)
                     else self.mandatory)
        return Status.SUCCESS if self.ctx.finish(mandatory) else Status.FAILURE
