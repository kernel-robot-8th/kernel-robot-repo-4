"""SN-01 v13 orchestration; ROS, web and device implementations stay at the boundary."""

import math
import re
import time
import uuid

from .repository import encode
from .scenario_repository import ScenarioRepository


TERMINAL = {'COMPLETED', 'FAILED'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
NAVIGATION = {'MOVE_PICKUP': 'zone', 'LEAVE_PICKUP': 'leave',
              'MOVE_DROPOFF': 'zone', 'LEAVE_DROPOFF': 'leave', 'RETURN_HOME': 'home'}
WORK = {
    'PICKUP_EXIT': ('vision', 'path_exit'),
    'DOCK_PICKUP': ('vision', 'dock_check'),
    'CORRECT_PICKUP': ('navigation', 'dock_correct'),
    'MARKER': ('vision', 'marker'), 'PICK': ('pickup_arm', 'pick'),
    'LOAD': ('pickup_arm', 'load'), 'VERIFY_LOAD': ('vision', 'verify_load'),
    'PATH_EXIT': ('vision', 'path_exit'),
    'DOCK_DROPOFF': ('vision', 'dock_check'),
    'CORRECT_DROPOFF': ('navigation', 'dock_correct'),
    'QR': ('vision', 'qr'), 'PICK_DROPOFF': ('dropoff_arm', 'pick'),
    'UNLOAD': ('dropoff_arm', 'unload'),
    'VERIFY_UNLOAD': ('vision', 'verify_unload'),
    'RETURN_EXIT': ('vision', 'path_exit'),
}
NEXT = {
    'MOVE_PICKUP': 'PICKUP_EXIT', 'PICKUP_EXIT': 'DOCK_PICKUP', 'MARKER': 'PICK', 'PICK': 'LOAD',
    'LOAD': 'VERIFY_LOAD', 'VERIFY_LOAD': 'LEAVE_PICKUP',
    'LEAVE_PICKUP': 'MOVE_DROPOFF', 'MOVE_DROPOFF': 'PATH_EXIT',
    'PATH_EXIT': 'DOCK_DROPOFF', 'QR': 'PICK_DROPOFF',
    'PICK_DROPOFF': 'UNLOAD', 'UNLOAD': 'VERIFY_UNLOAD',
    'VERIFY_UNLOAD': 'CUSTOMER', 'LEAVE_DROPOFF': 'RETURN_HOME',
    'RETURN_HOME': 'RETURN_EXIT',
}


def identifier(value, name):
    """Bound identifiers before using them as persistent keys or device targets."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError(f'{name}: 영문·숫자·밑줄·하이픈 1~80자')
    return value


def finite(value):
    """Reject missing, boolean, NaN and infinite sensor values."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class ScenarioService:
    """One serialized scheduler owns order transitions, assignments and work dispatch."""

    def __init__(self, repository, fleet, gateway, routes, clock=time.monotonic,
                 max_retries=3, step_timeout_sec=300.0, customer_timeout_sec=120.0,
                 stale_sec=3.0, battery_min=20.0, departure_gap_sec=3.0,
                 dock_xy_m=0.01, dock_yaw_deg=15.0, allow_returns=False):
        self.store = ScenarioRepository(repository)
        self.fleet, self.gateway, self.routes, self.clock = fleet, gateway, routes, clock
        self.config = dict(max_retries=max_retries, step_timeout_sec=step_timeout_sec,
                           customer_timeout_sec=customer_timeout_sec, stale_sec=stale_sec,
                           battery_min=battery_min, departure_gap_sec=departure_gap_sec,
                           dock_xy_m=dock_xy_m, dock_yaw_deg=dock_yaw_deg)
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
        for order in self.store.orders():
            if order['state'] not in TERMINAL:
                order.update(state='UNKNOWN', detail='관제 재시작: 자동 재전송 금지',
                             request_id=None)
                self.store.save(order)

    def submit(self, payload):
        """Accept a stock reservation even when every eligible robot is busy."""
        if not isinstance(payload, dict) or set(payload) - {
                'order_id', 'sku', 'quantity', 'route', 'kind'}:
            raise ValueError('주문 필드 오류')
        data = {'kind': 'delivery', 'quantity': 1}
        data.update(payload)
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
        self.store.create(data, order)
        return self.store.get(data['order_id'])

    def telemetry(self, robot_id, status=None, battery=None):
        """Use receipt clocks for liveness; battery and status have separate freshness."""
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
        return all(self.clock() - health.get(key, -math.inf) <= self.config['stale_sec']
                   for key in ('status_at', 'battery_at'))

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
        """Never wait inside a callback; a tick issues at most one new step per order."""
        now = self.clock()
        for order in self.store.orders():
            if order['state'] in TERMINAL | BLOCKED:
                continue
            if order['robot_id'] and not self._fresh(order['robot_id']):
                self.interrupt(order['order_id'], 'UNKNOWN', '통신·배터리 상태 수신 만료')
                continue
            if not self.armed:
                continue
            status = self.health.get(order['robot_id'], {}).get('status', {})
            if order['robot_id'] and status.get('central_latched') is True:
                if (order.get('reset_pending')
                        and now < self.deadlines.get(order['order_id'], -math.inf)):
                    continue
                self.interrupt(order['order_id'], 'UNKNOWN', '로봇 로컬 정지 래치·복구 반향 미확인')
                continue
            if order.get('reset_pending'):
                self._save(order, reset_pending=False)
                self.deadlines.pop(order['order_id'], None)
            if order['state'] == 'WAITING':
                if now < self.next_departure:
                    continue
                robot = next((r for r in self.fleet.robots if self._available(r)), None)
                if robot is None:
                    continue
                self._save(order, robot_id=robot, state='RUNNING')
                self.next_departure = now + self.config['departure_gap_sec']
            if order['stage'] == 'CUSTOMER':
                deadline = self.deadlines.setdefault(
                    order['order_id'], now + self.config['customer_timeout_sec'])
                if now >= deadline:
                    self._alarm(order, 'CUSTOMER_TIMEOUT',
                                f"{self.config['customer_timeout_sec']:g}초 수령 무응답: 기록 후 복귀")
                    self._advance(order, 'LEAVE_DROPOFF', customer_timed_out=True)
                continue
            if order['request_id']:
                if now >= self.deadlines.get(order['order_id'], math.inf):
                    self.interrupt(order['order_id'], 'UNKNOWN', '단계 결과 시간 초과')
                    continue
                if order['stage'] in NAVIGATION:
                    row = self.fleet.repository.get(order['request_id'])
                    if row['state'] == 'SUCCEEDED':
                        self._success(order, {})
                    elif row['state'] in {'FAILED', 'UNKNOWN'}:
                        self.interrupt(order['order_id'], 'UNKNOWN', '주행 실패·결과 불명: 현장 확인')
                elif now >= self.deadlines.get(order['order_id'], math.inf):
                    self.interrupt(order['order_id'], 'UNKNOWN', '장치 결과 시간 초과')
                continue
            self._dispatch(order)

    def _dispatch(self, order):
        route, stage = self._route(order), order['stage']
        resources = []
        if stage == 'MOVE_PICKUP':
            # Reserve the complete station chain before departure. Otherwise opposite
            # routes can each hold one station and wait forever for the other's exit.
            resources = self._station(order, 'pickup') + self._station(order, 'dropoff')
        elif stage == 'MOVE_DROPOFF':
            resources = self._station(order, 'dropoff')
        if stage in NAVIGATION:
            resources += ['lane_' + route['lane']]
        if not self.store.acquire(order['order_id'], resources):
            return
        request_id = uuid.uuid4().hex
        self._save(order, request_id=request_id, attempt=order['attempt'] + 1)
        self.deadlines[order['order_id']] = self.clock() + self.config['step_timeout_sec']
        try:
            if stage in NAVIGATION:
                point = (route['pickup'] if stage == 'MOVE_PICKUP' else route['dropoff'])
                self.fleet.submit(dict(command_id=request_id, robot_id=order['robot_id'],
                                       operation=NAVIGATION[stage],
                                       points=[point] if stage.startswith('MOVE_') else [],
                                       timeout_sec=self.config['step_timeout_sec']))
            else:
                actor, action = WORK[stage]
                target = route.get(actor, actor)
                if order['kind'] == 'return' and stage == 'UNLOAD':
                    action = 'warehouse_store'
                self.gateway.work(dict(request_id=request_id, order_id=order['order_id'],
                                       robot_id=order['robot_id'], stage=stage, target=target,
                                       action=action, sku=order['sku'], quantity=order['quantity'],
                                       attempt=order['attempt'], route=route,
                                       timeout_sec=self.config['step_timeout_sec']))
        except Exception as error:
            self.interrupt(order['order_id'], 'UNKNOWN', '단계 전달 실패: ' + str(error))

    def result(self, result):
        """Correlate measured device results to this exact stage and retry attempt."""
        if not isinstance(result, dict):
            raise ValueError('장치 결과는 객체')
        order = self.store.get(identifier(result.get('order_id'), 'order_id'))
        if (not order or order['state'] != 'RUNNING' or order['stage'] not in WORK
                or not order['request_id'] or result.get('request_id') != order['request_id']
                or result.get('robot_id') != order['robot_id']
                or result.get('stage') != order['stage']):
            return False
        actor, _ = WORK[order['stage']]
        if result.get('source') != self._route(order).get(actor, actor):
            return False
        if (not self._fresh(order['robot_id'])
                or self.clock() >= self.deadlines.get(order['order_id'], math.inf)):
            self.interrupt(order['order_id'], 'UNKNOWN', '결과 수신 시 통신·유효시간 만료')
            return False
        if result.get('measured') is not True or result.get('finished') is not True:
            return False
        data = result.get('data', {})
        if not isinstance(data, dict) or not isinstance(result.get('success'), bool):
            raise ValueError('결과 success는 bool, data는 객체')
        if result['success'] is False:
            # Only confirmed finished failures may be retried. Unknown execution is held.
            if data.get('retry_safe') is not True:
                self.interrupt(order['order_id'], 'UNKNOWN', '재시도 안전성 미확인')
            else:
                retry_stage = {'VERIFY_LOAD': 'LOAD', 'VERIFY_UNLOAD': 'UNLOAD'}.get(order['stage'])
                self._retry(order, str(result.get('detail', '장치 단계 실패')), retry_stage)
            return True
        self._success(order, data)
        return True

    def _success(self, order, data):
        stage = order['stage']
        if stage.startswith('DOCK_'):
            if not all(finite(data.get(k)) for k in ('xy_m', 'yaw_deg')):
                return
            if (abs(data['xy_m']) > self.config['dock_xy_m']
                    or abs(data['yaw_deg']) > self.config['dock_yaw_deg']):
                self._retry(order, '정차 공차 초과', 'CORRECT_' + stage[5:])
            elif data.get('stopped') is True and data.get('base_hold') is True:
                self._advance(order, 'MARKER' if stage == 'DOCK_PICKUP' else 'QR')
            return
        if stage.startswith('CORRECT_'):
            self._advance(order, 'DOCK_' + stage[8:])
            return
        if stage in ('MARKER', 'QR'):
            if data.get('sku') != order['sku']:
                self.interrupt(order['order_id'], 'UNKNOWN', '상품 불일치: 자동 피킹 금지')
                return
        if stage == 'VERIFY_LOAD' and not (
                data.get('load_present') is True and data.get('arm_safe') is True):
            return
        if stage == 'VERIFY_UNLOAD' and not (
                data.get('placed') is True and data.get('arm_safe') is True
                and data.get('load_absent') is True):
            return
        if stage in ('PICKUP_EXIT', 'PATH_EXIT', 'RETURN_EXIT'):
            if data.get('clear') is not True:
                return
            self.store.release(order['order_id'], ['lane_' + self._route(order)['lane']])
        if stage == 'LEAVE_PICKUP':
            self.store.release(order['order_id'], self._station(order, 'pickup'))
        if stage == 'LEAVE_DROPOFF':
            self.store.release(order['order_id'], self._station(order, 'dropoff'))
        if stage == 'RETURN_EXIT':
            order['completed'].append(stage)
            mandatory = set(NEXT) | {'DOCK_PICKUP', 'DOCK_DROPOFF', 'RETURN_EXIT'}
            if not order['failure'] and not mandatory <= set(order['completed']):
                self.interrupt(order['order_id'], 'UNKNOWN', '필수 완료 단계 누락')
                return
            order.update(state='FAILED' if order['failure'] else 'COMPLETED',
                         request_id=None, detail=order['failure'] or '필수 작업과 HOME 복귀 완료',
                         updated_at=time.time())
            self.store.close_order(
                order, restock=order['kind'] == 'return' and not order['failure'])
            return
        next_stage = NEXT[stage]
        if stage == 'VERIFY_UNLOAD' and order['kind'] == 'return':
            next_stage = 'LEAVE_DROPOFF'
        self._advance(order, next_stage)

    def _advance(self, order, stage, **changes):
        if order['stage'] not in order['completed']:
            order['completed'].append(order['stage'])
        self.deadlines.pop(order['order_id'], None)
        self._save(order, stage=stage, request_id=None, attempt=0, **changes)
        if stage == 'CUSTOMER':
            self.deadlines[order['order_id']] = self.clock() + self.config['customer_timeout_sec']

    def _retry(self, order, detail, next_stage=None):
        stage = order['stage']
        budget = {'VERIFY_LOAD': 'LOAD', 'VERIFY_UNLOAD': 'UNLOAD'}.get(stage, stage)
        count = order['retries'].get(budget, 0)
        if count >= self.config['max_retries']:
            self._alarm(order, 'RETRIES_EXHAUSTED', detail)
            # Docking failure may return home only before cargo has been picked up.
            if stage == 'DOCK_PICKUP':
                self._save(order, stage='RETURN_HOME', failure=detail,
                           request_id=None, attempt=0)
            else:
                self.interrupt(order['order_id'], 'UNKNOWN', detail + ': 관리자 확인 필요')
            return
        order['retries'][budget] = count + 1
        self._save(order, stage=next_stage or stage, request_id=None)

    def _alarm(self, order, code, detail):
        self.store.event(dict(type='alarm', order_id=order['order_id'], robot_id=order['robot_id'],
                              code=code, detail=detail))

    def received(self, order_id):
        """Customer acknowledgement is separate from manipulation completion."""
        order = self.store.get(identifier(order_id, 'order_id'))
        if not order or order['state'] != 'RUNNING' or order['stage'] != 'CUSTOMER':
            raise ValueError('고객 수령 대기 중인 주문만 확인 가능')
        self._advance(order, 'LEAVE_DROPOFF', customer_received=True)
        return self.store.get(order_id)

    def interrupt(self, order_id, state, detail):
        """Invalidate the in-flight attempt before requesting software stops of base and arms."""
        if state not in BLOCKED:
            raise ValueError('지원하지 않는 중단 상태')
        order = self.store.get(order_id)
        if not order or order['state'] in TERMINAL:
            raise ValueError('진행 중인 주문이 없습니다')
        if order['state'] == state and order['detail'] == detail:
            return order
        previous_request = order['request_id']
        self._save(order, state=state, request_id=None, detail=detail)
        if previous_request and order['stage'] in NAVIGATION:
            self.fleet.quarantine(previous_request, detail)
        if order['robot_id']:
            self.store.hold(order['robot_id'], state)
        self._alarm(order, state, detail)
        if order['robot_id']:
            # Emergency stop holds zone tokens; normal stop may retreat into an arm workspace.
            try:
                self.gateway.halt(order['robot_id'], self._route(order), order['order_id'])
            except Exception as error:
                self._alarm(order, 'STOP_UNCONFIRMED', str(error))
        return self.store.get(order_id)

    def recover(self, order_id, operator, note, decision, evidence):
        """Explicit reconciliation replaces automatic resume after stop or network recovery."""
        identifier(operator, 'operator')
        order = self.store.get(identifier(order_id, 'order_id'))
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
            if not self.armed or (robot and not self._fresh(robot)):
                raise ValueError('가동 허용 및 최신 통신 상태 필요')
        if robot:
            self.gateway.release(robot, self._route(order))
        self.store.event(dict(type='recovery', order_id=order_id, operator=operator,
                              note=note, decision=decision, evidence=evidence))
        # Do not leave a stopped low-level command reserving the robot after reconciliation.
        for row in self.fleet.repository.db.execute(
                "SELECT command_id FROM commands WHERE robot_id=? AND state NOT IN "
                "('SUCCEEDED','FAILED')", (robot,)).fetchall():
            command_id = row[0]
            self.fleet.active.pop(command_id, None)
            self.fleet.traces.pop(command_id, None)
            self.fleet.repository.transition(command_id, 'FAILED', '시나리오 운영자 복구: ' + note)
        if decision == 'fail':
            order.update(state='FAILED', detail=note, request_id=None, updated_at=time.time())
            self.store.close_order(order)
        else:
            self._save(order, state='RUNNING' if robot else 'WAITING', request_id=None,
                       detail=note, reset_pending=bool(robot))
            self.deadlines[order_id] = self.clock() + self.config['stale_sec']
        if robot:
            self.store.clear_hold(robot)
        return self.store.get(order_id)
