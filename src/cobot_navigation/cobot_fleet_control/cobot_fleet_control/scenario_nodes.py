"""전체 업무 BT의 비동기 실행 노드와 안전·재시도 제어 노드."""

import math

import py_trees

from .scenario_contracts import BLOCKED, TERMINAL, finite


Status = py_trees.common.Status


class SafetyGate(py_trees.decorators.Decorator):
    """매번 안전 조건을 검사하되 가동 허용을 끈 동안 완료된 하위 트리의 기억은 보존한다."""

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
        elif not service.armed:
            self.feedback_message = '작업 명령 꺼짐: 실행 위치 유지'
            self.status, permit = Status.RUNNING, False
        else:
            latched = service.health[order['robot_id']]['status'].get('central_latched')
            if latched is True:
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
            self.feedback_message = '최신 상태·가동 허용 확인'
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
        ctx.enter(self.stage)
        if not ctx.order['request_id']:
            ctx.dispatch(self.stage)
            self.feedback_message = ('명령 결과 대기' if ctx.order['request_id']
                                     else '자원 또는 타이머의 명령 전달 대기')
            return Status.RUNNING if ctx.running else Status.FAILURE
        if ctx.service.clock() >= ctx.service.deadlines.get(ctx.order['order_id'], math.inf):
            ctx.interrupt('단계 결과 시간 초과')
            return Status.FAILURE
        return self.poll()

    def poll(self):
        raise NotImplementedError


class NavigationStep(Step):
    """하위 주행 BT가 동일 명령의 실제 종료를 확인했는지 조회한다."""

    def poll(self):
        ctx = self.ctx
        row = ctx.service.fleet.repository.get(ctx.order['request_id'])
        if row['state'] == 'SUCCEEDED':
            side = {'LEAVE_PICKUP': 'pickup', 'LEAVE_DROPOFF': 'dropoff'}.get(self.stage)
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
        ctx.enter('CUSTOMER')
        if ctx.customer_received:
            ctx.save(customer_received=True)
        elif ctx.service.clock() >= ctx.service.deadlines[ctx.order['order_id']]:
            ctx.service._alarm(ctx.order, 'CUSTOMER_TIMEOUT',
                               f"{ctx.service.config['customer_timeout_sec']:g}초 수령 무응답: 기록 후 복귀")
            ctx.save(customer_timed_out=True)
        else:
            return Status.RUNNING
        ctx.complete('CUSTOMER')
        return Status.SUCCESS


class FinishOrder(py_trees.behaviour.Behaviour):
    """트리의 끝에서 필수 단계와 자원 정리를 확인하고 주문을 종결한다."""

    def __init__(self, context, mandatory):
        super().__init__('필수 단계 확인·주문 종결')
        self.ctx, self.mandatory = context, mandatory

    def update(self):
        return Status.SUCCESS if self.ctx.finish(self.mandatory) else Status.FAILURE
