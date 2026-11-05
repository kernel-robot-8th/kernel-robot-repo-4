"""ROS JSON boundary compatible with the control-center web task API."""

import json
import time

from .scenario import identifier


class ControlAPI:
    """Keep HTTP, MQTT, camera streams and UI out of the execution service."""

    def __init__(self, scenario, fleet, gateway):
        self.scenario, self.fleet, self.gateway = scenario, fleet, gateway

    def handle(self, request):
        """Echo the web request ID; invalid inputs never publish movement."""
        if not isinstance(request, dict):
            raise ValueError('요청은 JSON 객체')
        kind = request.get('type')
        reply = dict(type='reply', request_id=request.get('request_id'))
        try:
            body = self._request(kind, request)
            reply.update(status=200 if kind in {'arm', 'received', 'inventory', 'resolve'} else 202,
                         body=body)
        except (ValueError, TypeError, RuntimeError) as error:
            reply.update(status=400, body={'detail': str(error)})
        return reply

    def _request(self, kind, request):
        scenario = self.scenario
        if kind == 'arm':
            armed = request.get('armed')
            if not isinstance(armed, bool):
                raise ValueError('armed는 bool')
            changed = scenario.armed != armed
            scenario.store.event(dict(type='operator_arm', armed=armed,
                                      source=request.get('source', '')))
            scenario.armed = armed
            return dict(armed=armed, changed=changed)
        if kind == 'inventory':
            sku = identifier(request.get('sku'), 'sku')
            quantity = request.get('available')
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError('available은 0 이상 정수: 예약분 제외 가용 재고')
            scenario.store.set_stock(sku, quantity)
            return dict(sku=sku, available=quantity)
        if kind == 'order':
            return scenario.submit(request.get('order'))
        if kind == 'received':
            return scenario.received(identifier(request.get('order_id'), 'order_id'))
        if kind == 'resolve':
            return scenario.recover(request.get('order_id'), request.get('operator'),
                                    request.get('note'), request.get('decision'),
                                    request.get('evidence'))
        if kind in {'pause', 'estop', 'stop', 'manual'}:
            robot = request.get('robot_id')
            if robot is not None and robot not in self.fleet.robots:
                raise ValueError('등록되지 않은 로봇')
            targets = [robot] if robot else list(self.fleet.robots)
            for target in targets:
                scenario.store.hold(target, kind.upper())
                for row in list(self.fleet.repository.db.execute(
                        "SELECT command_id FROM commands WHERE robot_id=? "
                        "AND state IN ('ACCEPTED','RUNNING')", (target,))):
                    self.fleet.quarantine(row[0], '운영자 ' + kind)
            scenario.armed = False
            orders = [o for o in scenario.store.orders()
                      if o['robot_id'] in targets and o['state'] not in {'COMPLETED', 'FAILED'}]
            for order in orders:
                state = {'pause': 'PAUSED', 'manual': 'MANUAL'}.get(kind, 'ESTOP')
                scenario.interrupt(order['order_id'], state,
                                   '운영자 ' + kind)
            for target in targets:
                if not any(o['robot_id'] == target for o in orders):
                    self.gateway.halt(target, {'all_arms': True} if robot is None else {}, '')
            return dict(armed=False, robots=targets, software_stop=True,
                        detail='하드웨어 비상정지와 별도: 정지 결과 확인 필요')
        if kind == 'release_control':
            robot = request.get('robot_id')
            latched = scenario.health.get(robot, {}).get('status', {}).get('central_latched')
            if (robot not in self.fleet.robots
                    or (robot not in scenario.store.holds() and not latched)):
                raise ValueError('제어권이 보류된 등록 로봇 필요')
            if any(o['robot_id'] == robot and o['state'] not in {'COMPLETED', 'FAILED'}
                   for o in scenario.store.orders()):
                raise ValueError('주문 resolve를 먼저 수행하세요')
            evidence = request.get('evidence')
            if not isinstance(evidence, dict) or any(evidence.get(k) is not True for k in (
                    'base_stopped', 'arms_safe', 'cargo_reconciled', 'resources_clear')):
                raise ValueError('정지·팔·화물·구역 증거 필요')
            identifier(request.get('operator'), 'operator')
            if not isinstance(request.get('note'), str) or not request['note'].strip():
                raise ValueError('제어권 반환 확인 근거 note 필요')
            scenario.store.event(dict(type='release_control', request=request))
            self.gateway.release(robot)
            for row in list(self.fleet.repository.db.execute(
                    "SELECT command_id FROM commands WHERE robot_id=? AND state='UNKNOWN'",
                    (robot,))):
                self.fleet.repository.transition(row[0], 'FAILED', request['note'])
            scenario.store.clear_hold(robot)
            return dict(robot_id=robot, released=True)
        if kind == 'create':
            if not scenario.armed:
                raise ValueError('작업 명령 꺼짐')
            robot = request.get('robot_id')
            crid = identifier(request.get('client_request_id'), 'client_request_id')
            payload = dict(command_id=crid, robot_id=robot, operation=request.get('operation'),
                           points=request.get('points', []))
            existing = self.fleet.repository.get(crid)
            if not existing and not scenario._available(
                    robot, allow_holding=payload['operation'] in {'home', 'leave'}):
                raise ValueError('최신 상태·배터리·중앙 제어 모드 또는 예약 확인 필요')
            return self._task(self.fleet.submit(payload))
        if kind == 'raw':
            raise ValueError('직접 문자열 명령 제거: 추적 가능한 create 또는 order 사용')
        raise ValueError('알 수 없는 요청 type')

    @staticmethod
    def _task(row):
        payload = json.loads(row['payload'])
        command = payload['operation']
        if payload['points']:
            command += ':' + ','.join(payload['points'])
        return dict(task_id=row['command_id'], client_request_id=row['command_id'],
                    robot_id=row['robot_id'], operation=payload['operation'],
                    points=payload['points'], command=command, state=row['state'],
                    detail=row['detail'], spec='v1', created_at=row['created_at'],
                    updated_at=row['updated_at'])

    def snapshot(self, limit=50):
        """Supply the web task-list envelope plus scenario snapshots."""
        rows = self.fleet.repository.db.execute(
            'SELECT * FROM commands ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
        return dict(time=time.time(), armed=self.scenario.armed, allow_raw_cmd=False,
                    robots=list(self.fleet.robots), spec={r: 'v1' for r in self.fleet.robots},
                    tasks=[self._task(dict(row)) for row in rows],
                    orders=self.scenario.store.orders(), holds=self.scenario.store.holds())
