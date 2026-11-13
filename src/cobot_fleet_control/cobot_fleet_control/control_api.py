"""feature/control-center의 HTTP·WebSocket 백엔드가 사용하는 ROS 요청 계약."""

import json
import math
import time
import uuid

from .contracts import Command
from .scenario_contracts import identifier, operator_or_default, optional_text

RAW_CMD_MAX_LEN = 200   # 개발용 수동 명령 최대 길이 [글자]


def manual_load_request(value):
    """주문에 묶인 파라미터 값을 검증하고 수동 확인 요청으로 변환한다."""
    if not isinstance(value, str) or len(value.encode('utf-8')) > 8192:
        raise ValueError('manual_load_confirmation은 8 KiB 이하 JSON 문자열')
    if not value:
        return None
    data = json.loads(value)
    allowed = {'order_id', 'operator', 'note', 'evidence', 'request_id'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('수동 상차 파라미터 필드 오류')
    for key in ('order_id', 'operator'):
        identifier(data.get(key), key)
    if not isinstance(data.get('note'), str) or not data['note'].strip():
        raise ValueError('실제 확인 근거 note 필요')
    evidence = data.get('evidence')
    if (not isinstance(evidence, dict)
            or any(evidence.get(key) is not True for key in (
                'load_present', 'arm_safe', 'pickup_path_clear'))):
        raise ValueError('적재·팔 퇴피·후미 이탈 확인값 true 필요')
    identifier(evidence.get('sku'), 'sku')
    data.setdefault('request_id', 'loaded-' + uuid.uuid4().hex)
    identifier(data['request_id'], 'request_id')
    return dict(data, type='confirm_loaded')


def initial_pose_fields(x, y, yaw, xy_var, yaw_var):
    """지도(map) 프레임의 (x, y, yaw) 를 initialpose 메시지 값으로 바꾼다 (ROS 없이 시험하려고 분리)."""
    values = [float(v) for v in (x, y, yaw, xy_var, yaw_var)]
    if not all(math.isfinite(v) for v in values) or values[3] <= 0 or values[4] <= 0:
        raise ValueError('초기 위치·분산은 유한한 수, 분산은 0 보다 커야 합니다')
    x, y, yaw, xy_var, yaw_var = values
    covariance = [0.0] * 36   # 6x6 행렬 (x, y, z, roll, pitch, yaw) 행 우선
    covariance[0] = covariance[7] = xy_var
    covariance[35] = yaw_var
    return dict(x=x, y=y, qz=math.sin(yaw / 2), qw=math.cos(yaw / 2), covariance=covariance)


class ApiError(ValueError):
    """웹 백엔드가 그대로 전달할 HTTP 상태와 오류 본문."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


MANUAL_POSE_NAME = '좌표'   # 지도에서 찍은 초기위치의 지점 이름 (기록·응답용)


def manual_pose(value):
    """요청의 pose {x, y, yaw} 를 (x, y, yaw) 로 바꾼다. 없으면 None, 잘못되면 ApiError(400)."""
    if value is None:
        return None
    try:
        if not isinstance(value, dict):
            raise TypeError
        pose = tuple(float(value[key]) for key in ('x', 'y', 'yaw'))
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, 'pose 는 {x, y, yaw} 숫자여야 합니다') from None
    if not all(math.isfinite(v) for v in pose):
        raise ApiError(400, 'pose 는 유한한 수여야 합니다')
    return pose


class ControlAPI:
    """웹 서버는 control-center에 두고 실행·복구 정책만 처리한다."""

    def __init__(self, scenario, fleet, gateway, point_rules=None, allow_raw_cmd=False):
        self.scenario, self.fleet, self.gateway = scenario, fleet, gateway
        self.point_rules = point_rules
        # 개발용 수동 명령. 가짜 핑키·가제보 설정에서만 켠다 (실물 기본 꺼짐).
        self.allow_raw_cmd = bool(allow_raw_cmd)

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
        if kind == 'confirm_loaded':
            return 200, scenario.confirm_loaded(
                request.get('order_id'), request.get('operator'),
                request.get('note'), request.get('evidence'))
        if kind == 'resolve':
            return 200, scenario.recover(request.get('order_id'), request.get('operator'),
                                         request.get('note'), request.get('decision'),
                                         request.get('evidence'), request.get('source', ''))
        if kind in {'pause', 'estop', 'stop', 'manual'}:
            return 202, self._stop(kind, request)
        if kind == 'release_control':
            return 200, self._release_control(request)
        if kind == 'raw':
            return 202, self._raw(request)
        if kind == 'initial_pose':
            return 202, self._initial_pose(request)
        raise ValueError('알 수 없는 요청 type')

    def _initial_pose(self, request):
        """운영자가 확인한 자리로 AMCL 위치를 다시 잡는다. pose 가 없으면 홈, 있으면 그 좌표."""
        # 로봇을 움직이지 않는 명령이라 '작업 명령 켜기'는 요구하지 않는다. 로봇을 켜자마자 쓰는
        # 단계이고, 정지 잠금·보류 중 복구에서도 위치를 다시 잡을 수 있어야 한다.
        # 대신 멈춰 있는 것(busy=false)을 확인한다. 움직이는 중에 위치를 바꾸면 경로가 튄다.
        scenario = self.scenario
        robot = request.get('robot_id')
        if not isinstance(robot, str) or robot not in self.fleet.robots:
            raise ApiError(404, '등록되지 않은 로봇')
        manual = manual_pose(request.get('pose'))
        if manual is None and self.point_rules is None:
            raise ApiError(503, '순찰 지점 설정(patrol_config_dir)이 없어 홈 좌표를 모릅니다')
        if self._orders_for(robot):
            raise ApiError(409, '진행 중인 주문이 있는 로봇: 주문을 먼저 끝내거나 복구하세요')
        if self.fleet.repository.db.execute(
                "SELECT 1 FROM commands WHERE robot_id=? AND state IN ('ACCEPTED','RUNNING')",
                (robot,)).fetchone():
            raise ApiError(409, '진행 중인 작업이 있는 로봇: 정지한 뒤 다시 누르세요')
        if not scenario._fresh(robot):
            raise ApiError(503, '로봇 상태 또는 배터리 수신이 오래됐습니다')
        status = scenario.health.get(robot, {}).get('status', {})
        if status.get('busy') is not False:
            raise ApiError(409, '로봇이 멈춰 있는지 확인되지 않음 (busy=false 필요)')
        if manual is None:
            mode = 'home'
            name, x, y, yaw = self.point_rules.home(robot)
        else:
            # 지도에서 찍은 좌표. 지도 범위 검사는 지도를 가진 웹 백엔드(fleet_api)가 먼저 한다.
            mode = 'manual'
            name = MANUAL_POSE_NAME
            x, y, yaw = manual
        scenario.store.event(dict(type='operator_initial_pose', robot_id=robot, mode=mode,
                                  point=name, x=x, y=y, yaw=yaw,
                                  source=request.get('source', '')))
        self.gateway.set_initial_pose(robot, x, y, yaw)
        return dict(robot_id=robot, mode=mode, point=name, x=x, y=y, yaw=yaw,
                    topic=f'/{robot}/initialpose',
                    client_request_id=request.get('client_request_id'))

    def _raw(self, request):
        """개발용 1회성 문자열 명령. 기록·결과 추적 없이 세션 봉투만 붙여 로봇에 보낸다."""
        if not self.allow_raw_cmd:
            raise ApiError(403, '직접 문자열 명령 꺼짐: 추적 가능한 작업 요청을 사용하세요')
        scenario = self.scenario
        if not scenario.armed:
            raise ApiError(423, '작업 명령 꺼짐: 화면에서 작업 명령을 켜세요')
        robot = request.get('robot_id')
        if not isinstance(robot, str) or robot not in self.fleet.robots:
            raise ApiError(404, '등록되지 않은 로봇')
        text = request.get('command')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('빈 명령')
        text = text.strip()
        if '\n' in text or '\r' in text or len(text) > RAW_CMD_MAX_LEN:
            raise ValueError(f'명령은 한 줄, {RAW_CMD_MAX_LEN}자 이하')
        if (self._orders_for(robot) or self.fleet.repository.busy(robot)
                or robot in scenario.store.holds()):
            raise ApiError(409, '진행 중이거나 결과를 모르는 작업·보류: 정지·복구 확인 필요')
        ready = getattr(self.gateway, 'ready', None)
        if ready is not None and not ready(robot):
            raise ApiError(503, '명령 실행기 중복 또는 로봇 명령 연결 미확인')
        raw_id = 'raw_' + uuid.uuid4().hex
        scenario.store.event({'type': 'operator_raw', 'robot_id': robot, 'raw_id': raw_id,
                              'command': text, 'source': request.get('source', '')})
        self.gateway.send(robot, {'command_id': raw_id, 'command': text})
        return {'robot_id': robot, 'command': text, 'raw_id': raw_id, 'spec': 'v1',
                'topic': f'/{robot}/patrol_cmd', 'msg_type': 'std_msgs/msg/String',
                'client_request_id': request.get('client_request_id'),
                'warning': '작업 관리를 거치지 않는 1회성 직접 명령: 검사·결과 추적 없음'}

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
        if not scenario._available(robot, manual=True):
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
        has_orders = {target: bool(self._orders_for(target)) for target in targets}
        if kind == 'stop' and robot is not None and not has_orders[robot]:
            return self._plain_stop(robot, request)
        stopped_tasks = {}
        for target in targets:
            rows = self.fleet.repository.active_commands(target)
            if rows:
                stopped_tasks[target] = rows[0]
            elif kind == 'stop' and not has_orders[target]:
                # 대기 중 내린 정지 요청도 기존 화면에서 확인하고 해제할 수 있어야 한다.
                stop_id = 'stop_' + uuid.uuid4().hex
                self.fleet.repository.create(Command(stop_id, target, 'emergency_stop'))
                self.fleet.repository.transition(stop_id, 'UNKNOWN', '정지 요청: 현장 정지 확인 필요')
                stopped_tasks[target] = stop_id
            scenario.store.hold(target, kind.upper())
            for command_id in rows:
                self.fleet.quarantine(command_id, '운영자 ' + kind)
        # 로봇을 지정한 정지는 그 로봇만 보류(hold)한다. 다른 로봇은 계속 일한다.
        # 로봇 지정 없는 전체 정지(전체 비상정지)만 작업 명령 전체를 끈다.
        if robot is None:
            scenario.armed = False
        orders = [o for o in scenario.store.orders()
                  if o['robot_id'] in targets and o['state'] not in {'COMPLETED', 'FAILED'}]
        for order in orders:
            state = {'pause': 'PAUSED', 'manual': 'MANUAL'}.get(kind, 'ESTOP')
            scenario.interrupt(order['order_id'], state, '운영자 ' + kind)
        for target in targets:
            if not any(o['robot_id'] == target for o in orders):
                self.gateway.halt(target, {'all_arms': True} if robot is None else {}, '')
        return dict(armed=scenario.armed, robot_id=robot, robots=targets,
                    operation='emergency_stop',
                    spec='v1', task_id=stopped_tasks.get(robot), software_stop=True,
                    client_request_id=request.get('client_request_id'),
                    warning='중앙 제어의 정지는 제자리 소프트 정지입니다. 현장 확인 후 해제하세요')

    def _plain_stop(self, robot, request):
        """일반 정지: 보류·결과 모름을 만들지 않고 로봇에 stop 만 보낸다."""
        # 진호 님 원래 순찰 노드 기준 (2026-11-09). 로봇은 멈추고 구역 안이면 물러나 토큰을
        # 풀며 잠그지 않는다. 이미 보낸 작업은 로봇의 STOPPED 결과로 끝나고, 아직 안 보낸
        # 작업은 여기서 취소한다. 주문이 걸린 로봇과 비상정지는 기존 보류 경로를 쓴다.
        rows = self.fleet.repository.active_commands(robot)
        self.fleet.cancel_pending(robot, '운영자 정지 (보내기 전 취소)')
        self.gateway.stop(robot)
        self.scenario.store.event(dict(type='operator_stop', robot_id=robot))
        return dict(armed=self.scenario.armed, robot_id=robot, robots=[robot],
                    operation='stop', spec='v1', task_id=rows[0] if rows else None,
                    software_stop=True, client_request_id=request.get('client_request_id'),
                    warning='일반 정지는 잠그지 않습니다. 구역 안이면 로봇이 물러납니다. '
                            '제자리에 세우려면 비상정지를 쓰세요')

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
        # 메모는 선택 (화면 확인 창 한 번, 2026-11-09). 없으면 기본 문구로 기록한다.
        note = optional_text(request.get('note'), 'note', '화면에서 현장 확인 후 해제')
        status = self.scenario.health.get(robot, {}).get('status', {})
        reasons = []
        if not self.scenario._fresh(robot):
            reasons.append('로봇 상태 또는 배터리 수신이 오래됐거나 없습니다')
        if status.get('busy') is not False:
            reasons.append('로봇 정지·취소 완료 미확인 (busy=false 필요)')
        # 구역 보유(held_zone)는 막지 않는다. 비상정지·통신 끊김으로 구역 안에서 잠긴 로봇은
        # 해제한 뒤 leave(또는 아무 명령, 로봇이 먼저 구역을 나감)로 빠져나온다.
        # 토큰은 그때까지 유지되어 다른 로봇이 들어오지 못한다.
        # 로봇 래치(central_latched)는 보지 않는다. 로봇이 재부팅하면 래치가 풀린 채 올라와
        # 해제가 영영 막히기 때문이다. 멈춤은 busy=false 로 확인하고, 해제 때 control_reset 을 보낸다.
        if reasons:
            raise ApiError(409, '해제 불가: ' + '; '.join(reasons))
        self.gateway.release(robot)
        repository.resolve_unknown(task_id, robot, 'control-center-ui', note)
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
        # 주문 없는(그냥 주행하는) 로봇의 복구는 화면 확인 창 한 번이면 된다 (보통 방식, 2026-11-09).
        # 운영자·메모·확인 항목은 선택: 주면 형식만 보고 기록, 없으면 기본값. 누가는 source(접속 IP).
        # 팔·화물 확인은 주문이 걸린 로봇만 해당하고, 그 로봇은 위에서 주문 복구로 보낸다.
        # TODO(시나리오): 신발매장 시나리오가 정해지면 멈춘 단계별 확인 항목과 주문 복구 띠를 붙인다
        #   (draft/safety_locks_review.md 8절).
        evidence = request.get('evidence')
        if evidence is not None and not isinstance(evidence, dict):
            raise ValueError('evidence는 객체')
        operator = operator_or_default(request.get('operator'))
        note = optional_text(request.get('note'), 'note', '화면에서 현장 확인 후 복구')
        scenario.store.event(dict(type='release_control', request=dict(
            request, operator=operator, note=note, source=request.get('source', ''))))
        self.gateway.release(robot)
        for row in list(self.fleet.repository.db.execute(
                "SELECT command_id FROM commands WHERE robot_id=? AND state='UNKNOWN'", (robot,))):
            self.fleet.repository.transition(row[0], 'FAILED', note)
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
        return dict(time=time.time(), armed=self.scenario.armed,
                    allow_raw_cmd=self.allow_raw_cmd,
                    robots=list(self.fleet.robots), spec={r: 'v1' for r in self.fleet.robots},
                    tasks=[self._task(dict(row)) for row in active + recent],
                    orders=self.scenario.store.orders(), holds=self.scenario.store.holds())
