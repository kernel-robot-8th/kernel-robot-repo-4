"""전체 시나리오의 실행 순서와 분기를 실제 행동 트리로 조립한다."""

import py_trees

from .scenario_contracts import (
    ARRANGE_STAGES, CUSTOMER_RETURN_STAGES, CUSTOMER_STAGES, is_customer_route, LABELS,
    order_stages, skips_arrange, STAGES,
)
from .scenario_nodes import (
    CorrectionBudget, CustomerDeclined, CustomerReceipt, DeviceStep, DockTolerance, FinishOrder,
    MatchSku, MeasureDock, NavigationStep, PathClear, SafeRetry, SafetyGate, VerifyCargo,
)


def customer_mandatory(order):
    """고객 자리 주문의 필수 완료 단계. 회수한 주문만 정리·반환 단계가 필수다."""
    stages = set(CUSTOMER_STAGES)
    if order.get('cancel_requested'):
        # 직원 취소는 고객 자리에 들르지 않았거나 고객을 기다리지 않았을 수 있다.
        stages -= {'MOVE_CUSTOMER', 'CUSTOMER'}
        if skips_arrange(order):
            stages -= ARRANGE_STAGES
    return stages if order.get('customer_declined') else stages - CUSTOMER_RETURN_STAGES


def sequence(name, children):
    """완료한 자식을 기억해 다음 갱신에서 물리 명령을 다시 실행하지 않는다."""
    return py_trees.composites.Sequence(name, memory=True, children=children)


class FailureRoute(py_trees.behaviour.Behaviour):
    """피킹 전 정차 실패로 승인된 복귀와 정상 업무 분기를 구분한다."""

    def __init__(self, context, failed):
        super().__init__('피킹 전 실패 복귀 승인' if failed else '정상 업무 진행')
        self.ctx, self.failed = context, failed

    def update(self):
        return (py_trees.common.Status.SUCCESS
                if bool(self.ctx.order['failure']) == self.failed
                else py_trees.common.Status.FAILURE)


def build_scenario_tree(ctx):
    """조건·선택·순차·재시도 노드가 전체 업무 순서를 직접 결정한다."""
    # 복구는 운영자가 승인한 이동·수령 체크포인트에서만 이 함수를 다시 호출한다.
    route = ctx.service._route(ctx.order)
    customer = is_customer_route(route)
    stages = order_stages(route)
    ctx.skip_stages = set(stages[:stages.index(ctx.resume_stage)])

    def nav(stage):
        return NavigationStep(ctx, stage, LABELS[stage])

    def device(stage, cls=DeviceStep):
        return SafeRetry(ctx, LABELS[stage] + ' 안전 재시도', cls(ctx, stage, LABELS[stage]))

    def dock(side):
        stage = 'DOCK_' + side
        measured = MeasureDock(ctx, stage, LABELS[stage])
        branches = py_trees.composites.Selector('정차 확인 또는 보정', memory=True, children=[
            sequence('정차 측정·공차 판정', [
                SafeRetry(ctx, '정차 실측 안전 재시도', measured), DockTolerance(measured)]),
            sequence('재보정 후 다시 측정', [
                CorrectionBudget(ctx, stage), device('CORRECT_' + side),
                py_trees.behaviours.Failure('보정 후 새 정차 실측 필요')]),
        ])
        return SafeRetry(ctx, '상차 정차 반복' if side == 'PICKUP' else '하차 정차 반복', branches)

    def cargo(action, verify):
        return SafeRetry(ctx, LABELS[action] + '·검증 공유 재시도', sequence(
            LABELS[action] + '와 실측 검증', [
                DeviceStep(ctx, action, LABELS[action]), VerifyCargo(ctx, verify, LABELS[verify])]))

    def pickup():
        return sequence('상차', [
            nav('MOVE_PICKUP'), device('PICKUP_EXIT', PathClear), dock('PICKUP'),
            device('MARKER', MatchSku), device('PICK'), cargo('LOAD', 'VERIFY_LOAD')])

    if customer:
        # 고객 자리에는 팔이 없다. 고객이 핑키에서 직접 꺼내고 그 자리에서 결제한다.
        normal = sequence('고객 자리 주문 전체 업무', [
            FailureRoute(ctx, False),
            pickup(),
            sequence('고객 자리 이동', [nav('LEAVE_PICKUP'), nav('MOVE_CUSTOMER')]),
            CustomerReceipt(ctx),
            py_trees.composites.Selector('결제·시간 초과 또는 회수', memory=True, children=[
                sequence('회수 정리·선반 반환', [
                    CustomerDeclined(ctx),
                    nav('MOVE_ARRANGE'), device('ARRANGE'), nav('LEAVE_ARRANGE'),
                    nav('MOVE_RESTOCK'), device('RESTOCK'), nav('LEAVE_RESTOCK')]),
                CustomerDeclined(ctx, declined=False),
            ]),
            sequence('복귀', [nav('RETURN_HOME'), device('RETURN_EXIT', PathClear)]),
            FinishOrder(ctx, customer_mandatory),
        ])
    else:
        normal = sequence('배송·회수 전체 업무', [
            FailureRoute(ctx, False),
            pickup(),
            sequence('작업장 간 이동', [
                nav('LEAVE_PICKUP'), nav('MOVE_DROPOFF'), device('PATH_EXIT', PathClear)]),
            sequence('하차', [
                dock('DROPOFF'), device('QR', MatchSku), device('PICK_DROPOFF'),
                cargo('UNLOAD', 'VERIFY_UNLOAD')]),
            CustomerReceipt(ctx),
            sequence('복귀', [
                nav('LEAVE_DROPOFF'), nav('RETURN_HOME'), device('RETURN_EXIT', PathClear)]),
            FinishOrder(ctx, set(STAGES) - {'CUSTOMER'}),
        ])
    safe_return = sequence('피킹 전 실패 후 안전 복귀', [
        FailureRoute(ctx, True), nav('RETURN_HOME'), device('RETURN_EXIT', PathClear),
        FinishOrder(ctx, set()),
    ])
    mission = py_trees.composites.Selector(
        '정상 업무 또는 승인된 실패 복귀', memory=True, children=[normal, safe_return])
    return py_trees.trees.BehaviourTree(SafetyGate(ctx, mission))
