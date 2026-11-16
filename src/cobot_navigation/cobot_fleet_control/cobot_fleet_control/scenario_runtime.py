"""주문별 BT 실행 문맥. 장치 결과·예약·영속 기록을 트리 노드에 제공한다."""

import math
import time
import uuid

from .bt_visualization import ScenarioTreeTrace
from .scenario_contracts import BLOCKED, NAVIGATION, TERMINAL, WORK
from .scenario_tree import build_scenario_tree


class ScenarioContext:
    """주문마다 분리된 실행 문맥으로 다른 로봇의 결과와 상태가 섞이지 않게 한다."""

    def __init__(self, service, order):
        self.service, self.order = service, order
        self.resume_stage = order['stage']
        self.allow_dispatch = True
        self.pending = None
        self.customer_received = False
        self.customer_declined = False
        self.dock_data = {}

    @property
    def running(self):
        return self.order['state'] == 'RUNNING'

    def save(self, **changes):
        """현재 노드의 상태와 웹 통지 이벤트를 함께 영속 저장한다."""
        self.service._save(self.order, **changes)

    def enter(self, stage):
        """진행 단계는 다음 BT 노드가 선택될 때 갱신한다."""
        if self.order['stage'] != stage:
            self.save(stage=stage, request_id=None, attempt=0)
        if stage == 'CUSTOMER':
            self.service.deadlines.setdefault(
                self.order['order_id'], self.service.clock()
                + self.service.config['customer_timeout_sec'])

    def complete(self, stage):
        """완료 기록은 복구와 최종 무결성 확인에 사용하며 트리 순서를 대신하지 않는다."""
        if stage not in self.order['completed']:
            self.order['completed'].append(stage)
        self.service.deadlines.pop(self.order['order_id'], None)
        self.save(request_id=None, attempt=0)

    def interrupt(self, detail):
        """결과가 불명확하면 다음 분기로 넘어가지 않고 현장 확인 상태로 보류한다."""
        self.service.interrupt(self.order['order_id'], 'UNKNOWN', detail)
        self.order = self.service.store.get(self.order['order_id'])

    def dispatch(self, stage):
        """예약을 모두 확보한 뒤 요청 하나만 전달한다. 콜백에서는 호출하지 않는다."""
        if not self.allow_dispatch:
            return
        service, order = self.service, self.order
        route = service._route(order)
        resources = []
        if stage == 'MOVE_PICKUP':
            # 반대 방향 주문이 작업장을 하나씩 잡고 서로 기다리는 교착을 방지한다.
            resources = service._station(order, 'pickup') + service._station(order, 'dropoff')
        elif stage == 'MOVE_DROPOFF':
            resources = service._station(order, 'dropoff')
        if stage in NAVIGATION:
            resources += ['lane_' + route['lane']]
        if not service.store.acquire(order['order_id'], resources):
            return
        request_id = uuid.uuid4().hex
        self.save(request_id=request_id, attempt=order['attempt'] + 1)
        service.deadlines[order['order_id']] = (
            service.clock() + service.config['step_timeout_sec'])
        try:
            if stage in NAVIGATION:
                point = route['pickup'] if stage == 'MOVE_PICKUP' else route['dropoff']
                service.fleet.submit(dict(
                    command_id=request_id, robot_id=order['robot_id'],
                    operation=NAVIGATION[stage],
                    points=[point] if stage.startswith('MOVE_') else [],
                    timeout_sec=service.config['step_timeout_sec']))
            else:
                actor, action = WORK[stage]
                if order['kind'] == 'return' and stage == 'UNLOAD':
                    action = 'warehouse_store'
                work = dict(
                    request_id=request_id, order_id=order['order_id'], robot_id=order['robot_id'],
                    stage=stage, target=route.get(actor, actor), action=action,
                    sku=order['sku'], quantity=order['quantity'], attempt=order['attempt'],
                    route=route, timeout_sec=service.config['step_timeout_sec'])
                if order.get('shelf_row') is not None:
                    # 선반 칸을 아는 주문만 팔이 집을 행·열을 함께 받는다.
                    work.update(shelf_row=order['shelf_row'], shelf_col=order['shelf_col'])
                service.gateway.work(work)
        except Exception as error:
            self.interrupt('단계 전달 실패: ' + str(error))

    def retry(self, stage, detail):
        """확정된 안전 실패만 공유 예산으로 재시도한다. 동작 불명 상태는 대상이 아니다."""
        budget = {'VERIFY_LOAD': 'LOAD', 'VERIFY_UNLOAD': 'UNLOAD'}.get(stage, stage)
        count = self.order['retries'].get(budget, 0)
        if count >= self.service.config['max_retries']:
            self.service._alarm(self.order, 'RETRIES_EXHAUSTED', detail)
            if stage == 'DOCK_PICKUP':
                # 피킹 이전의 정차 실패만 안전 복귀 분기로 넘긴다.
                self.save(failure=detail, request_id=None, attempt=0)
            else:
                self.interrupt(detail + ': 관리자 확인 필요')
            return False
        self.order['retries'][budget] = count + 1
        self.pending = None
        self.service.deadlines.pop(self.order['order_id'], None)
        self.save(request_id=None)
        return True

    def finish(self, mandatory):
        """필수 작업 완료와 실제 후미 이탈을 확인한 뒤 주문과 자원 예약을 닫는다."""
        order = self.order
        confirmed = set(order['completed']) | set(order.get('operator_completed', []))
        if not order['failure'] and not mandatory <= confirmed:
            self.interrupt('필수 완료 단계 누락')
            return False
        order.update(state='FAILED' if order['failure'] else 'COMPLETED', request_id=None,
                     detail=order['failure'] or '필수 작업과 HOME 복귀 완료', updated_at=time.time())
        self.service.store.close_order(
            order, restock=order['kind'] == 'return' and not order['failure'])
        if (order.get('customer_declined') and order['kind'] == 'delivery'
                and not order['failure']):
            self.service.collect_declined(order)
        return True


class ScenarioRuntime:
    """실제 py_trees 트리와 관측기를 소유하며 결과 콜백에서 새 명령을 보내지 않는다."""

    def __init__(self, service, order):
        self.context = ScenarioContext(service, order)
        self.tree = build_scenario_tree(self.context)
        self.trace = ScenarioTreeTrace(self.tree, service.store.repository, order['order_id'])
        self.in_tick = False
        self.cancelled = False
        self.trace.capture(order, 'created')

    def tick(self, allow_dispatch=True):
        """명령은 타이머에서만 전달하고 결과 처리 중에는 상태 전이만 허용한다."""
        ctx = self.context
        ctx.order = ctx.service.store.get(ctx.order['order_id'])
        ctx.allow_dispatch = allow_dispatch
        self.in_tick = True
        try:
            self.tree.tick()
        except Exception as error:
            if ctx.order['state'] not in TERMINAL | BLOCKED:
                ctx.interrupt('시나리오 BT 실행 예외: ' + str(error))
        finally:
            self.in_tick = False
            if self.cancelled:
                ctx.order = ctx.service.store.get(ctx.order['order_id'])
                self.trace.capture(ctx.order, 'interrupt_requested')
                self.tree.interrupt()
                self.tree.root.stop(self.tree.root.status.INVALID)
            ctx.order = ctx.service.store.get(ctx.order['order_id'])
            self.trace.capture(ctx.order, 'interrupted' if self.cancelled else 'tick')

    def cancel(self):
        """외부 정지 시 트리를 무효화한다. 실행 도중에는 현재 순회가 끝난 뒤 처리한다."""
        self.cancelled = True
        self.context.pending = None
        if not self.in_tick:
            self.trace.visitor.visited.clear()
            self.tree.root.stop(self.tree.root.status.INVALID)
            order = self.context.service.store.get(self.context.order['order_id'])
            self.trace.capture(order, 'interrupted')

    def settle(self):
        """재시도 분기를 정리하되 결과 콜백에서 장치 명령은 전달하지 않는다."""
        for _ in range(2):
            self.tick(allow_dispatch=False)
            if not self.context.running or self.cancelled:
                break

    def receive(self, result):
        """현재 주문·단계·시도·로봇·출처와 일치하는 실측 최종 결과만 받아들인다."""
        ctx, service = self.context, self.context.service
        order = service.store.get(ctx.order['order_id'])
        if (order['state'] != 'RUNNING' or order['stage'] not in WORK
                or not order['request_id'] or result.get('request_id') != order['request_id']
                or result.get('robot_id') != order['robot_id']
                or result.get('stage') != order['stage']):
            return False
        actor, _ = WORK[order['stage']]
        if result.get('source') != service._route(order).get(actor, actor):
            return False
        if (not service._fresh(order['robot_id'])
                or service.clock() >= service.deadlines.get(order['order_id'], math.inf)):
            ctx.order = order
            ctx.interrupt('결과 수신 시 통신·유효시간 만료')
            return False
        if result.get('measured') is not True or result.get('finished') is not True:
            return False
        if (not isinstance(result.get('data', {}), dict)
                or not isinstance(result.get('success'), bool)):
            raise ValueError('결과 success는 bool, data는 객체')
        ctx.pending = result
        self.settle()
        return True
