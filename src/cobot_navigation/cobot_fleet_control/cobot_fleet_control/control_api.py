"""feature/control-center의 HTTP·WebSocket 백엔드가 사용하는 ROS 요청 계약."""

import json
import time
import uuid

from .contracts import Command
from .scenario_contracts import identifier


class ApiError(ValueError):
    """웹 백엔드가 그대로 전달할 HTTP 상태와 오류 본문."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


class ControlAPI:
    """웹 서버는 control-center에 두고 실행·복구 정책만 처리한다."""

    def __init__(self, scenario, fleet, gateway, point_rules=None):
        self.scenario, self.fleet, self.gateway = scenario, fleet, gateway
        self.point_rules = point_rules

    def handle(self, request):
        """기존 웹의 TaskStore가 기다리는 request_id/status/body 응답 형식을 유지한다."""
        if not isinstance(request, dict):
            raise ValueError('요청은 JSON 객체')
        reply = dict(type='reply', request_id=request.get('request_id'))
        try:
            status, body = self._request(request.get('type'), request)
            reply.update(status=status, body=body)
        except ApiError as error:
            reply.update(status=error.status, body={'detail': str(error)})
        except (ValueError, TypeError) as error:
            reply.update(status=400, body={'detail': str(error)})
        except RuntimeError as error:
            reply.update(status=503, body={'detail': str(error)})
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
            return 200, dict(armed=armed, changed=changed, source=request.get('source', ''),
                             client_request_id=request.get('client_request_id'))
        if kind == 'create':
            return self._create(request)
        if kind == 'resolve' and request.get('task_id') is not None:
            return 200, self._resolve_task(request)
        if kind == 'inventory':
            sku = identifier(request.get('sku'), 'sku')
            quantity = request.get('available')
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError('available은 0 이상 정수: 예약분 제외 가용 재고')
            scenario.store.set_stock(sku, quantity)
            return 200, dict(sku=sku, available=quantity)
        if kind == 'order':
            return 202, scenario.submit(request.get('order'))
        if kind == 'received':
            return 200, scenario.received(identifier(request.get('order_id'), 'order_id'))
        if kind == 'resolve':
            return 200, scenario.recover(request.get('order_id'), request.get('operator'),
                                         request.get('note'), request.get('decision'),
                                         request.get('evidence'))
        if kind in {'pause', 'estop', 'stop', 'manual'}:
            return 202, self._stop(kind, request)
        if kind == 'release_control':
            return 200, self._release_control(request)
        if kind == 'raw':
            raise ApiError(403, '직접 문자열 명령 꺼짐: 추적 가능한 작업 요청을 사용하세요')
        raise ValueError('알 수 없는 요청 type')

    def _create(self, request):
        scenario, repository = self.scenario, self.fleet.repository
        if not scenario.armed:
            raise ApiError(423, '작업 명령 꺼짐: 화면에서 작업 명령을 켜세요')
        robot = request.get('robot_id')
        if not isinstance(robot, str) or robot not in self.fleet.robots:
            raise ApiError(404, '등록되지 않은 로봇')
        crid = identifier(request.get('client_request_id'), 'client_request_id')
        points = request.get('points', [])
        if not isinstance(points, list) or any(not isinstance(p, str) for p in points):
            raise ValueError('points는 문자열 목록')
        points = [p.strip().upper() for p in points if p.strip()]
        payload = dict(command_id=crid, robot_id=robot, operation=request.get('operation'),
                       points=points)
        command = Command.parse(payload, self.fleet.robots)
        previous = repository.get(crid)
        if previous:
            if json.loads(previous['payload']) != command.payload():
                raise ApiError(409, '같은 client_request_id에 다른 작업을 사용할 수 없습니다')
            return 200, self._task(previous)
        if self._orders_for(robot) or repository.busy(robot) or robot in scenario.store.holds():
            raise ApiError(409, '진행 중이거나 결과를 모르는 작업: 정지·복구 확인 필요')
        if not scenario._fresh(robot):
            raise ApiError(503, '로봇 상태 또는 배터리 수신이 오래됐습니다')
        if not scenario._available(robot, allow_holding=command.operation in {'home', 'leave'}):
            raise ApiError(409, '로봇 이동·배터리·중앙 제어 모드·정지 래치를 확인하세요')
        if self.point_rules is not None:
            self.point_rules.validate(robot, command.operation, command.points)
        ready = getattr(self.gateway, 'ready', None)
        if ready is not None and not ready(robot):
            raise ApiError(503, '명령 실행기 중복 또는 로봇 명령 연결 미확인')
        return 202, self._task(self.fleet.submit(payload))

    def _orders_for(self, robot):
        return [o for o in self.scenario.store.orders()
                if o['robot_id'] == robot and o['state'] not in {'COMPLETED', 'FAILED'}]

    def _stop(self, kind, request):
        scenario = self.scenario
        robot = request.get('robot_id')
        if robot is not None and (not isinstance(robot, str) or robot not in self.fleet.robots):
            raise ApiError(404, '등록되지 않은 로봇')
        targets = [robot] if robot else list(self.fleet.robots)
        stopped_tasks = {}
        for target in targets:
            rows = list(self.fleet.repository.db.execute(
                "SELECT command_id FROM commands WHERE robot_id=? "
                "AND state IN ('ACCEPTED','RUNNING','UNKNOWN') ORDER BY rowid DESC", (target,)))
            if rows:
                stopped_tasks[target] = rows[0][0]
            elif kind == 'stop' and not self._orders_for(target):
                # 대기 중 내린 정지 요청도 기존 화면에서 확인하고 해제할 수 있어야 한다.
                stop_id = 'stop_' + uuid.uuid4().hex
                self.fleet.repository.create(Command(stop_id, target, 'emergency_stop'))
                self.fleet.repository.transition(stop_id, 'UNKNOWN', '정지 요청: 현장 정지 확인 필요')
                stopped_tasks[target] = stop_id
            scenario.store.hold(target, kind.upper())
            for row in rows:
                self.fleet.quarantine(row[0], '운영자 ' + kind)
        scenario.armed = False
        orders = [o for o in scenario.store.orders()
                  if o['robot_id'] in targets and o['state'] not in {'COMPLETED', 'FAILED'}]
        for order in orders:
            state = {'pause': 'PAUSED', 'manual': 'MANUAL'}.get(kind, 'ESTOP')
            scenario.interrupt(order['order_id'], state, '운영자 ' + kind)
        for target in targets:
            if not any(o['robot_id'] == target for o in orders):
                self.gateway.halt(target, {'all_arms': True} if robot is None else {}, '')
        return dict(armed=False, robot_id=robot, robots=targets, operation='emergency_stop',
                    spec='v1', task_id=stopped_tasks.get(robot), software_stop=True,
                    client_request_id=request.get('client_request_id'),
                    warning='중앙 제어의 정지는 제자리 소프트 정지입니다. 현장 확인 후 해제하세요')

    def _resolve_task(self, request):
        task_id = identifier(request.get('task_id'), 'task_id')
        repository = self.fleet.repository
        row = repository.get(task_id)
        if row is None:
            raise ApiError(404, '없는 작업')
        if row['state'] != 'UNKNOWN':
            raise ApiError(409, 'UNKNOWN 작업만 해제할 수 있습니다')
        robot = row['robot_id']
        if self._orders_for(robot):
            raise ApiError(409, '시나리오 예약이 있습니다: 주문의 안전·화물 확인 복구가 필요합니다')
        if request.get('result', 'FAILED') != 'FAILED':
            raise ValueError('현장 확인 해제는 FAILED만 지원합니다')
        note = request.get('note')
        if not isinstance(note, str) or not note.strip():
            raise ValueError('현장 정지 확인 내용을 note에 적으세요')
        status = self.scenario.health.get(robot, {}).get('status', {})
        if (not self.scenario._fresh(robot) or status.get('busy') is not False
                or status.get('held_zone') or status.get('central_latched') is not True):
            raise ApiError(409, '최신 로봇 정지·취소 완료·구역 이탈 확인이 필요합니다')
        self.gateway.release(robot)
        repository.resolve_unknown(task_id, robot, 'control-center-ui', note.strip())
        self.scenario.store.clear_hold(robot)
        return self._task(repository.get(task_id))

    def _release_control(self, request):
        scenario = self.scenario
        robot = request.get('robot_id')
        latched = scenario.health.get(robot, {}).get('status', {}).get('central_latched')
        if (robot not in self.fleet.robots
                or (robot not in scenario.store.holds() and not latched)):
            raise ValueError('제어권이 보류된 등록 로봇 필요')
        if self._orders_for(robot):
            raise ApiError(409, '주문 resolve를 먼저 수행하세요')
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
                "SELECT command_id FROM commands WHERE robot_id=? AND state='UNKNOWN'", (robot,))):
            self.fleet.repository.transition(row[0], 'FAILED', request['note'])
        scenario.store.clear_hold(robot)
        return dict(robot_id=robot, released=True)

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
        """진행·UNKNOWN 작업은 최근 종료 작업 제한 때문에 웹 목록에서 사라지지 않는다."""
        active = list(self.fleet.repository.db.execute(
            "SELECT * FROM commands WHERE state NOT IN ('SUCCEEDED','FAILED') ORDER BY rowid DESC"))
        recent = list(self.fleet.repository.db.execute(
            "SELECT * FROM commands WHERE state IN ('SUCCEEDED','FAILED') "
            'ORDER BY rowid DESC LIMIT ?', (max(0, limit - len(active)),)))
        return dict(time=time.time(), armed=self.scenario.armed, allow_raw_cmd=False,
                    robots=list(self.fleet.robots), spec={r: 'v1' for r in self.fleet.robots},
                    tasks=[self._task(dict(row)) for row in active + recent],
                    orders=self.scenario.store.orders(), holds=self.scenario.store.holds())
