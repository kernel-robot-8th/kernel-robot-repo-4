"""주문 접수·배정과 주문별 전체 시나리오 BT의 수명을 관리한다."""

import math
import time

from .repository import encode
from .scenario_repository import ScenarioRepository
from .scenario_contracts import BLOCKED, TERMINAL, finite, identifier
from .scenario_runtime import ScenarioRuntime
from . import scenario_safety


class ScenarioService:
    """단일 스케줄러가 주문 상태 전이·배정·작업 전달을 순차 처리한다."""

    def __init__(self, repository, fleet, gateway, routes, clock=time.monotonic,
                 max_retries=3, step_timeout_sec=300.0, customer_timeout_sec=120.0,
                 stale_sec=3.0, battery_min=20.0, departure_gap_sec=3.0,
                 dock_xy_m=0.01, dock_yaw_deg=15.0, allow_returns=False, battery_stale_sec=10.0,
                 shelf=None, destinations=None):
        self.store = ScenarioRepository(repository)
        self.shelf, self.destinations, routes = self._layout(routes, shelf, destinations)
        self.fleet, self.gateway, self.routes, self.clock = fleet, gateway, routes, clock
        self.config = dict(max_retries=max_retries, step_timeout_sec=step_timeout_sec,
                           customer_timeout_sec=customer_timeout_sec, stale_sec=stale_sec,
                           battery_min=battery_min, departure_gap_sec=departure_gap_sec,
                           dock_xy_m=dock_xy_m, dock_yaw_deg=dock_yaw_deg,
                           battery_stale_sec=battery_stale_sec)
        if (isinstance(max_retries, bool) or not isinstance(max_retries, int)
                or not 0 <= max_retries <= 10):
            raise ValueError('max_retries: 0~10 정수')
        if any(not finite(v) or v <= 0 for k, v in self.config.items()
               if k != 'max_retries'):
            raise ValueError('시나리오 시간·임계값은 유한한 양수여야 합니다')
        for route in routes.values():
            if set(route) != {'pickup', 'dropoff', 'pickup_arm', 'dropoff_arm', 'lane'}:
                raise ValueError('route: pickup, dropoff, pickup_arm, dropoff_arm, lane 필요')
            for name, value in route.items():
                identifier(value, name)
            if route['pickup'] == route['dropoff']:
                raise ValueError('상차·하차 지점은 달라야 합니다')
            if route['pickup_arm'] == route['dropoff_arm']:
                raise ValueError('이 경로의 상차·하차 팔은 서로 다른 작업 구역을 사용해야 합니다')
        self.allow_returns = allow_returns
        self.armed = False
        self.health = {}
        self.next_departure = 0.0
        self.deadlines = {}
        self.trees = {}
        for order in self.store.orders():
            if order['state'] not in TERMINAL:
                order.update(state='UNKNOWN', detail='관제 재시작: 자동 재전송 금지',
                             request_id=None)
                self.store.save(order)

    @staticmethod
    def _layout(routes, shelf, destinations):
        """선반 열과 고객 자리 설정을 검증하고 (열, 자리) 조합마다 운송 경로를 만든다."""
        routes = dict(routes)
        shelf = dict(shelf or {})
        destinations = {key: dict(value) for key, value in (destinations or {}).items()}
        if not shelf and not destinations:
            return {}, {}, routes
        rows = shelf.get('rows')
        columns = shelf.get('columns') or {}
        if (set(shelf) - {'rows', 'columns'} or isinstance(rows, bool)
                or not isinstance(rows, int) or not 1 <= rows <= 100):
            raise ValueError('shelf: rows(1~100 정수)와 columns 필요')
        for column, pickup in columns.items():
            if (isinstance(column, bool) or not isinstance(column, int)
                    or not 1 <= column <= 100):
                raise ValueError('shelf.columns: 열 번호는 1~100 정수')
            if not isinstance(pickup, dict) or set(pickup) != {'pickup', 'pickup_arm'}:
                raise ValueError('shelf.columns: 열마다 pickup, pickup_arm 필요')
        for name, target in destinations.items():
            identifier(name, 'destination')
            if (not isinstance(target, dict)
                    or set(target) - {'name'} != {'dropoff', 'dropoff_arm', 'lane'}
                    or not isinstance(target.get('name', name), str)):
                raise ValueError('destinations: 자리마다 dropoff, dropoff_arm, lane 필요')
            for column, pickup in columns.items():
                route = f'col{column}__{name}'
                if route in routes:
                    raise ValueError('선반·자리 경로 이름이 routes와 겹칩니다: ' + route)
                routes[route] = dict(pickup, dropoff=target['dropoff'],
                                     dropoff_arm=target['dropoff_arm'], lane=target['lane'])
        return dict(rows=rows, columns=columns), destinations, routes

    def _resolve_destination(self, data):
        """고객 자리와 상품의 선반 칸으로 운송 경로를 정한다. 재고는 건드리지 않는다."""
        destination = identifier(data.get('destination'), 'destination')
        if 'route' in data:
            raise ValueError('route와 destination은 함께 쓸 수 없습니다')
        if destination not in self.destinations:
            raise ValueError('등록되지 않은 고객 자리')
        location = self.store.location(identifier(data.get('sku'), 'sku'))
        if location is None:
            raise ValueError('상품의 선반 칸 미등록: 재고에 shelf_row, shelf_col을 등록하세요')
        row, column = location
        if column not in self.shelf['columns']:
            raise ValueError(f'선반 {column}열의 상차 구역 미등록')
        return dict(data, route=f'col{column}__{destination}', shelf_row=row, shelf_col=column)

    def submit(self, payload):
        """조건에 맞는 로봇이 모두 작업 중이어도 재고 예약은 접수한다."""
        if not isinstance(payload, dict) or set(payload) - {
                'order_id', 'sku', 'quantity', 'route', 'kind', 'destination'}:
            raise ValueError('주문 필드 오류')
        data = {'kind': 'delivery', 'quantity': 1}
        data.update(payload)
        request = None
        if 'destination' in data:
            # 같은 요청의 재전송은 선반 칸이 그 사이 바뀌어도 같은 주문으로 돌려준다.
            previous = self.store.get(identifier(data.get('order_id'), 'order_id'))
            if previous and encode(previous.get('request')) == encode(data):
                return previous
            request, data = data, self._resolve_destination(data)
        for key in ('order_id', 'sku', 'route'):
            identifier(data.get(key), key)
        if data['route'] not in self.routes:
            raise ValueError('등록되지 않은 운송 경로')
        if data['kind'] not in ('delivery', 'return'):
            raise ValueError('kind: delivery 또는 return')
        if data['kind'] == 'return' and not self.allow_returns:
            raise ValueError('회수 적재 담당·경로 설정 후 allow_returns를 켜세요')
        if (isinstance(data['quantity'], bool) or not isinstance(data['quantity'], int)
                or not 1 <= data['quantity'] <= 100):
            raise ValueError('quantity: 1~100 정수')
        previous = self.store.get(data['order_id'])
        if previous:
            if encode(previous['input']) != encode(data):
                raise ValueError('같은 order_id에 다른 주문')
            return previous
        order = dict(data, input=data, state='WAITING', stage='MOVE_PICKUP', robot_id=None,
                     request_id=None, attempt=0, retries={}, completed=[], detail='',
                     customer_received=False, customer_timed_out=False,
                     failure=None, created_at=time.time(), updated_at=time.time())
        if request is not None:
            order.update(request=request, customer_declined=False)
        self.store.create(data, order)
        return self.store.get(data['order_id'])

    def telemetry(self, robot_id, status=None, battery=None):
        """수신 시각으로 연결 상태를 판단하고 배터리와 로봇 상태의 만료 시간을 구분한다."""
        if robot_id not in self.fleet.robots:
            raise ValueError('등록되지 않은 로봇')
        health = self.health.setdefault(robot_id, {})
        if status is not None:
            if not isinstance(status, dict):
                raise ValueError('status는 객체')
            previous_boot = health.get('status', {}).get('boot_id')
            if previous_boot and status.get('boot_id') != previous_boot:
                for order in self.store.orders():
                    if order['robot_id'] == robot_id and order['state'] not in TERMINAL | BLOCKED:
                        self.interrupt(order['order_id'], 'UNKNOWN', '로봇 재기동·세션 변경')
            health.update(status=status, status_at=self.clock())
        if battery is not None:
            if not finite(battery) or not 0 <= battery <= 100:
                raise ValueError('battery: 0~100 실측 퍼센트')
            health.update(battery=battery, battery_at=self.clock())

    def _fresh(self, robot):
        health = self.health.get(robot, {})
        limits = {'status_at': self.config['stale_sec'],
                  'battery_at': self.config['battery_stale_sec']}
        return all(self.clock() - health.get(key, -math.inf) <= limit
                   for key, limit in limits.items())

    def _available(self, robot, allow_holding=False):
        health = self.health.get(robot, {})
        status = health.get('status', {})
        allowed = {'IDLE', 'DONE'}
        if allow_holding:
            allowed |= {'HOLDING_ZONE', 'IDLE_WAIT'}
        reserved = any(o['robot_id'] == robot and o['state'] not in TERMINAL
                       for o in self.store.orders())
        return (robot not in self.store.holds()
                and not reserved and not self.fleet.repository.busy(robot) and self._fresh(robot)
                and health.get('battery', -1) >= self.config['battery_min']
                and status.get('state') in allowed
                and status.get('central_controlled') is True
                and status.get('central_latched') is not True
                and (allow_holding or not status.get('held_zone')))

    def _save(self, order, **changes):
        order.update(changes, updated_at=time.time())
        self.store.save(order)

    def _route(self, order):
        route = dict(self.routes[order['route']])
        if order['kind'] == 'return':
            for a, b in [('pickup', 'dropoff'), ('pickup_arm', 'dropoff_arm')]:
                route[a], route[b] = route[b], route[a]
        return route

    def _station(self, order, side):
        route = self._route(order)
        return ['station_' + route[side], 'arm_' + route[side + '_arm']]

    def tick(self):
        """접수 순서로 로봇을 배정하고 주문마다 독립적인 전체 시나리오 BT를 실행한다."""
        for order in self.store.orders():
            if order['state'] in TERMINAL | BLOCKED:
                self.trees.pop(order['order_id'], None)
                continue
            if order['state'] == 'WAITING':
                if not self.armed or self.clock() < self.next_departure:
                    continue
                robot = next((r for r in self.fleet.robots if self._available(r)), None)
                if robot is None:
                    continue
                self._save(order, robot_id=robot, state='RUNNING')
                self.next_departure = self.clock() + self.config['departure_gap_sec']
            runtime = self.trees.get(order['order_id'])
            if runtime is None:
                runtime = ScenarioRuntime(self, order)
                self.trees[order['order_id']] = runtime
            runtime.tick()
            latest = self.store.get(order['order_id'])
            pending = latest.get('manual_load_pending')
            status = self.health.get(latest['robot_id'], {}).get('status', {})
            if (pending and latest['state'] == 'RUNNING' and latest['stage'] == 'PICKUP_EXIT'
                    and status.get('held_zone') and status.get('busy') is False):
                try:
                    self.confirm_loaded(latest['order_id'], pending['operator'],
                                        pending['note'], pending['evidence'])
                except ValueError as error:
                    self.interrupt(latest['order_id'], 'UNKNOWN', '수동 상차 재확인 실패: ' + str(error))
            if self.store.get(order['order_id'])['state'] in TERMINAL | BLOCKED:
                self.trees.pop(order['order_id'], None)

    def result(self, result):
        """검증한 결과를 해당 주문의 실행 중인 BT 노드에만 전달한다."""
        if not isinstance(result, dict):
            raise ValueError('장치 결과는 객체')
        order_id = identifier(result.get('order_id'), 'order_id')
        runtime = self.trees.get(order_id)
        return runtime.receive(result) if runtime else False

    def _alarm(self, order, code, detail):
        self.store.event(dict(type='alarm', order_id=order['order_id'], robot_id=order['robot_id'],
                              code=code, detail=detail))

    def received(self, order_id):
        """고객 수령 입력을 대기 중인 BT에 전달한다."""
        order = self.store.get(identifier(order_id, 'order_id'))
        if not order or order['state'] != 'RUNNING' or order['stage'] != 'CUSTOMER':
            raise ValueError('고객 수령 대기 중인 주문만 확인 가능')
        runtime = self.trees.get(order_id)
        if runtime is None:
            raise ValueError('BT 복구와 로봇 상태 확인이 끝난 뒤 수령을 확인하세요')
        runtime.context.customer_received = True
        runtime.settle()
        return self.store.get(order_id)

    def declined(self, order_id):
        """고객이 구매하지 않기로 한 입력을 대기 중인 BT에 전달한다. 로봇은 그대로 복귀한다."""
        order = self.store.get(identifier(order_id, 'order_id'))
        if not order or order['state'] != 'RUNNING' or order['stage'] != 'CUSTOMER':
            raise ValueError('고객 수령 대기 중인 주문만 구매 취소 가능')
        runtime = self.trees.get(order_id)
        if runtime is None:
            raise ValueError('BT 복구와 로봇 상태 확인이 끝난 뒤 구매 취소를 확인하세요')
        runtime.context.customer_declined = True
        runtime.settle()
        return self.store.get(order_id)

    def collect_declined(self, order):
        """구매 취소로 자리에 남은 상품은 기존 회수 주문으로만 되가져온다."""
        if not self.allow_returns:
            self._alarm(order, 'DECLINED_ITEM_LEFT',
                        '구매 취소 상품이 고객 자리에 남음: 회수 꺼짐, 운영자 수거·재고 확인 필요')
            return None
        try:
            return self.submit(dict(order_id=order['order_id'] + '-return', sku=order['sku'],
                                    quantity=order['quantity'], route=order['route'],
                                    kind='return'))
        except ValueError as error:
            self._alarm(order, 'DECLINED_RETURN_REJECTED', '회수 주문 접수 실패: ' + str(error))
            return None

    def interrupt(self, order_id, state, detail):
        """실행 중인 트리를 무효화하고 장치 정지와 예약 보류를 요청한다."""
        return scenario_safety.interrupt(self, order_id, state, detail)

    def confirm_loaded(self, order_id, operator, note, evidence):
        """운영자가 직접 확인한 적재·팔 퇴피·통로 이탈로 상차 후 체크포인트를 연다."""
        return scenario_safety.confirm_loaded(self, order_id, operator, note, evidence)

    def recover(self, order_id, operator, note, decision, evidence):
        """현장 확인을 기록한 뒤 허용된 체크포인트에서만 새 트리를 구성한다."""
        return scenario_safety.recover(self, order_id, operator, note, decision, evidence)
