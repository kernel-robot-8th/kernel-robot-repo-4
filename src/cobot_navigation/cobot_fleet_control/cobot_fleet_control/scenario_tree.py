"""전체 시나리오의 실행 순서와 분기를 실제 행동 트리로 조립한다."""

import py_trees

from .scenario_nodes import (
    CorrectionBudget, CustomerDeclined, CustomerReceipt, DeviceStep, DockTolerance, FinishOrder,
    MatchSku, MeasureDock, NavigationStep, PathClear, SafeRetry, SafetyGate, VerifyCargo,
)


STAGES = (
    'MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD',
    'LEAVE_PICKUP', 'MOVE_DROPOFF', 'PATH_EXIT', 'DOCK_DROPOFF', 'QR', 'PICK_DROPOFF',
    'UNLOAD', 'VERIFY_UNLOAD', 'CUSTOMER', 'LEAVE_DROPOFF', 'RETURN_HOME', 'RETURN_EXIT',
)
LABELS = {
    'MOVE_PICKUP': '상차 작업장 이동', 'PICKUP_EXIT': '상차 진입 후미 이탈 확인',
    'DOCK_PICKUP': '상차 정차 실측', 'CORRECT_PICKUP': '상차 정밀 위치 보정',
    'MARKER': '상차 마커·상품 확인', 'PICK': '상차 상품 피킹', 'LOAD': '로봇에 상차',
    'VERIFY_LOAD': '적재·로봇팔 퇴피 확인', 'LEAVE_PICKUP': '상차 구역 이탈',
    'MOVE_DROPOFF': '하차 작업장 이동', 'PATH_EXIT': '하차 진입 후미 이탈 확인',
    'DOCK_DROPOFF': '하차 정차 실측', 'CORRECT_DROPOFF': '하차 정밀 위치 보정',
    'QR': '하차 QR·상품 확인', 'PICK_DROPOFF': '하차 상품 피킹', 'UNLOAD': '목적지에 하차',
    'VERIFY_UNLOAD': '배치·빈 적재함·로봇팔 퇴피 확인', 'LEAVE_DROPOFF': '하차 구역 이탈',
    'RETURN_HOME': 'HOME 복귀', 'RETURN_EXIT': '복귀 후미 이탈 확인',
    'MOVE_CUSTOMER': '고객 자리 이동', 'MOVE_ARRANGE': '회수 정리 구역 이동',
    'ARRANGE': '회수 신발 정리', 'LEAVE_ARRANGE': '회수 정리 구역 이탈',
    'MOVE_RESTOCK': '선반 반환 구역 이동', 'RESTOCK': '신발 선반 반환',
    'LEAVE_RESTOCK': '선반 반환 구역 이탈',
}
# 고객 자리(지점) 주문: ZB 상차 → 고객 자리 → 결제면 복귀, 회수면 ZC 정리 → ZA 선반 반환 → 복귀.
# 순서는 복구 체크포인트(resume_stage) 이전 단계를 건너뛰는 데 쓴다.
CUSTOMER_STAGES = (
    'MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD',
    'LEAVE_PICKUP', 'MOVE_CUSTOMER', 'CUSTOMER',
    'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE', 'MOVE_RESTOCK', 'RESTOCK', 'LEAVE_RESTOCK',
    'RETURN_HOME', 'RETURN_EXIT',
)
CUSTOMER_RETURN_STAGES = frozenset(CUSTOMER_STAGES[CUSTOMER_STAGES.index('MOVE_ARRANGE'):
                                                   CUSTOMER_STAGES.index('RETURN_HOME')])


def customer_mandatory(order):
    """고객 자리 주문의 필수 완료 단계. 회수한 주문만 정리·반환 단계가 필수다."""
    stages = set(CUSTOMER_STAGES)
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
    customer = 'customer' in ctx.service._route(ctx.order)
    order_stages = CUSTOMER_STAGES if customer else STAGES
    ctx.skip_stages = set(order_stages[:order_stages.index(ctx.resume_stage)])

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
