# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
경로(여러 지점을 섞은 연결 주행): 나누기와 차례로 보내기 (ROS 없음).

순찰 노드는 한 번에 명령 하나만 받는다 (goto 는 일반 지점·자기 홈 여러 개, zone 은 구역 지점 1개).
그래서 P1 → ZA1 → P3 → 홈 같은 경로는 관제가 구간으로 나눠 앞 구간이 성공하면 다음 구간을 보낸다.
이어지는 일반 지점은 goto 하나로 묶고, 구역 지점은 하나씩 zone 으로 보낸다.
구역을 잡은 채 다음 구간을 받으면 순찰 노드가 먼저 구역을 나간다 (patrol_controller.submit).

보내기는 작업 노드(fleet_control_node)의 일반 작업 요청(/api/tasks 와 같은 create)을 쓴다.
구간 i 의 client_request_id 는 '<경로 id>-<i>' 로 고정이라, 응답을 못 받아 다시 보내도 작업이 두 번 생기지 않는다.
"""

import threading
import time
import uuid

# 작업 노드 작업 상태 (fleet_control). 성공이면 다음 구간, 실패 묶음이면 경로를 멈춘다.
TASK_DONE = 'SUCCEEDED'
TASK_FAILED = {'FAILED', 'STOPPED', 'REJECTED', 'UNKNOWN'}
# 경로 상태
RUNNING = 'RUNNING'
SUCCEEDED = 'SUCCEEDED'
FAILED = 'FAILED'
CANCELED = 'CANCELED'
FINISHED = {SUCCEEDED, FAILED, CANCELED}
# 작업이 안 만들어진 거절 중 잠깐 기다리면 풀릴 수 있는 것 (409 로봇 상태가 아직 작업 중, 503 응답 없음·수신 지연).
# 그 밖(400·404·423 작업 명령 꺼짐 등)과 기록된 거절(REJECTED 작업)은 바로 경로를 멈춘다.
RETRY_STATUS = {409, 503}
ROUTE_POINTS_MAX = 20


class RouteError(ValueError):
    """경로를 만들 수 없음 (HTTP 상태와 함께)."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def split_route(points, layers, robot_id):
    """
    지점 이름 목록을 구간 [{'operation', 'points'}] 으로 나눈다.

    layers 는 load_map_layers() 결과다. 구역 지점(zones.*.points, 출구 제외)은 zone 구간 하나씩,
    일반 지점(points)과 이 로봇의 홈(homes[robot_id])은 이어지는 것끼리 goto 구간 하나로 묶는다.
    모르는 지점·다른 로봇의 홈·구역 출구는 RouteError(400). 최종 검사는 작업 노드·순찰 노드가 다시 한다.
    """
    if layers is None:
        raise RouteError(503, '구역·지점 설정이 없어 경로를 나눌 수 없음 (points_dir, zone_params)')
    if not isinstance(points, list) or any(not isinstance(p, str) for p in points):
        raise RouteError(400, 'points 는 지점 이름 목록')
    names = [p.strip().upper() for p in points if p.strip()]
    if len(names) < 1:
        raise RouteError(400, '지점을 하나 이상 고르세요')
    if len(names) > ROUTE_POINTS_MAX:
        raise RouteError(400, f'지점은 {ROUTE_POINTS_MAX}개까지')
    zone_points = {n for zone in (layers.get('zones') or {}).values()
                   for n in (zone.get('points') or {})}
    home = ((layers.get('homes') or {}).get(robot_id) or {}).get('name')
    general = set(layers.get('points') or {}) | ({home} if home else set())
    legs = []
    for name in names:
        if name in zone_points:
            legs.append({'operation': 'zone', 'points': [name]})
        elif name in general:
            if legs and legs[-1]['operation'] == 'goto':
                legs[-1]['points'].append(name)
            else:
                legs.append({'operation': 'goto', 'points': [name]})
        else:
            raise RouteError(400, f'경로에 쓸 수 없는 지점: {name}')
    return legs


def leg_text(leg):
    """구간 한 줄 (화면·기록용, 예: goto:P1,P2)."""
    return f"{leg['operation']}:{','.join(leg['points'])}"


# 이벤트 로그용 말 (화면 카드 버튼과 같은 말)
OP_WORD = {'goto': '이동', 'zone': '구역'}


def leg_words(leg):
    """이벤트 로그용 구간 글 (예: 이동 P1→P2)."""
    return f"{OP_WORD.get(leg['operation'], leg['operation'])} {'→'.join(leg['points'])}"


class RouteRunner:
    """
    로봇마다 경로 하나를 들고, step() 마다 구간을 보내거나 결과를 본다.

    submit(payload) 는 작업 노드에 create 요청을 내고 (상태, 본문) 또는 응답이 없으면 None 을 돌려준다.
    task_of(task_id) 는 작업 노드 작업 목록의 작업 (없으면 None) 이다.
    submit 은 응답을 기다리며 막히므로 ROS 콜백 스레드가 아닌 따로 된 스레드(start)나 시험에서 부른다.
    retry_sec: 작업이 안 만들어진 일시 거절(RETRY_STATUS)을 다시 보내 보는 시간 [s].
    on_event(events) 는 경로 시작·구간 성공·끝을 이벤트 로그에 넣는 함수다 (SnapshotStore.add_events).
    이벤트 모양은 fleet_status 이벤트와 같다 {'time', 'robot', 'kind': 'route', 'level', 'text', 'data'}.
    """

    def __init__(self, submit, task_of, retry_sec=8.0, keep=20, clock=time.monotonic,
                 on_event=None):
        self.submit = submit
        self.on_event = on_event
        self._outbox = []
        self.task_of = task_of
        self.retry_sec = float(retry_sec)
        self.keep = int(keep)
        self.clock = clock
        self._lock = threading.Lock()
        self._routes = {}
        self._done = []
        self._seq = 0
        self._thread = None
        self._stop = threading.Event()

    # ---------- 웹 서버 스레드 ----------

    def create(self, robot_id, legs, names, client_request_id=None):
        """경로를 등록한다. 이 로봇에 진행 중인 경로가 있으면 RouteError(409)."""
        with self._lock:
            current = self._routes.get(robot_id)
            if current is not None and current['state'] == RUNNING:
                raise RouteError(409, f"진행 중인 경로가 있음: {current['route_id']}")
            self._seq += 1
            now = time.time()
            route = {
                'route_id': f'route_{uuid.uuid4().hex[:12]}', 'robot_id': robot_id,
                'client_request_id': client_request_id,
                'points': list(names), 'legs': [dict(leg, task_id=None, state='WAITING')
                                                for leg in legs],
                'index': 0, 'state': RUNNING, 'detail': '', 'created_at': now,
                'updated_at': now, '_retry_until': None, '_sending': False}
            self._routes[robot_id] = route
            plan = ' → '.join(leg_words(leg) for leg in route['legs'])
            self._event(route, 'info', f"시작 ({len(route['legs'])}구간): {plan}")
            result = self._public(route)
        self._flush()
        return result

    def cancel(self, robot_id=None, detail='운영자 정지'):
        """그 로봇(None 이면 모두)의 진행 중 경로를 멈춘다. 이미 보낸 구간은 정지 명령이 따로 멈춘다."""
        with self._lock:
            targets = [robot_id] if robot_id is not None else list(self._routes)
            stopped = []
            for robot in targets:
                route = self._routes.get(robot)
                if route is not None and route['state'] == RUNNING:
                    self._finish(route, CANCELED, detail)
                    stopped.append(route['route_id'])
        self._flush()
        return stopped

    def routes(self):
        """로봇별 마지막 경로 (끝난 것 포함) 와 최근 끝난 경로 목록."""
        with self._lock:
            return {'robots': {r: self._public(v) for r, v in self._routes.items()},
                    'recent': [self._public(v) for v in self._done]}

    def route(self, robot_id):
        with self._lock:
            route = self._routes.get(robot_id)
            return self._public(route) if route else None

    def kick(self, robot_id):
        """그 로봇 경로를 지금 한 걸음 (웹 요청에서 첫 구간을 바로 보내 결과를 돌려주려고)."""
        self._step_robot(robot_id)
        return self.route(robot_id)

    # ---------- 진행 ----------

    def step(self):
        """진행 중인 경로마다 한 걸음. submit 은 lock 밖에서 부른다."""
        with self._lock:
            pending = [r['robot_id'] for r in self._routes.values() if r['state'] == RUNNING]
        for robot_id in pending:
            self._step_robot(robot_id)

    def _step_robot(self, robot_id):
        try:
            self._step_robot_once(robot_id)
        finally:
            self._flush()

    def _step_robot_once(self, robot_id):
        with self._lock:
            route = self._routes.get(robot_id)
            # 웹 요청(첫 구간 바로 보내기)과 스레드가 같은 구간을 겹쳐 보내지 않게 한다.
            if route is None or route['state'] != RUNNING or route['_sending']:
                return
            leg = route['legs'][route['index']]
            task_id = leg['task_id']
            index = route['index']
            route['_sending'] = task_id is None
        if task_id is not None:
            self._check(route, leg, task_id)
            return
        payload = {'type': 'create', 'robot_id': robot_id,
                   'client_request_id': f"{route['route_id']}-{index}",
                   'operation': leg['operation'], 'points': list(leg['points'])}
        try:
            result = self.submit(payload)
        except Exception as error:  # noqa: B902 (보내기 실패도 응답 없음처럼 다시 보내 본다)
            result = (503, {'detail': f'보내기 실패: {error}'})
        with self._lock:
            route['_sending'] = False
            # 보내는 동안 정지로 취소됐으면 결과만 적고 다음으로 가지 않는다.
            if route['state'] != RUNNING or route['index'] != index:
                body = result[1] if result and isinstance(result[1], dict) else {}
                if body.get('task_id'):
                    leg['task_id'] = body['task_id']
                return
            self._after_submit(route, leg, result)

    def _after_submit(self, route, leg, result):
        status, body = result if result is not None else (503, {'detail': '작업 노드 응답 없음'})
        body = body if isinstance(body, dict) else {}
        if status is not None and status < 400 and body.get('task_id'):
            leg['task_id'] = body['task_id']
            leg['state'] = body.get('state') or 'SENT'
            route['_retry_until'] = None
            self._touch(route, f'{route["index"] + 1}/{len(route["legs"])} {leg_text(leg)} 보냄')
            return
        detail = body.get('detail') or f'작업 노드 거절 ({status})'
        if 'task_id' in body or status not in RETRY_STATUS:
            leg['state'] = 'REJECTED'
            self._finish(route, FAILED, f'{leg_text(leg)} 거절: {detail}')
            return
        now = self.clock()
        if route['_retry_until'] is None:
            route['_retry_until'] = now + self.retry_sec
        if now >= route['_retry_until']:
            leg['state'] = 'REJECTED'
            self._finish(route, FAILED, f'{leg_text(leg)} 거절: {detail}')
        else:
            self._touch(route, f'{leg_text(leg)} 다시 보낼 준비: {detail}')

    def _check(self, route, leg, task_id):
        task = self.task_of(task_id)
        if task is None:
            return
        state = task.get('state')
        with self._lock:
            if route['state'] != RUNNING or leg['task_id'] != task_id:
                return
            if leg['state'] != state:
                leg['state'] = state
                self._touch(route, route['detail'])
            if state == TASK_DONE:
                route['index'] += 1
                if route['index'] >= len(route['legs']):
                    self._finish(route, SUCCEEDED, '경로 완료')
                else:
                    self._touch(route, f'{leg_text(leg)} 성공')
                    self._event(route, 'info',
                                f"{route['index']}/{len(route['legs'])} 성공: {leg_words(leg)}")
            elif state in TASK_FAILED:
                detail = task.get('detail') or state
                self._finish(route, FAILED, f'{leg_text(leg)} {state}: {detail}')

    # ---------- 내부 (lock 안) ----------

    def _touch(self, route, detail):
        route['detail'] = detail
        route['updated_at'] = time.time()

    def _finish(self, route, state, detail):
        route['state'] = state
        self._touch(route, detail)
        total = len(route['legs'])
        if state == SUCCEEDED:
            self._event(route, 'info', f'완료 ({total}구간)')
        else:
            # 몇 번째 구간에서 멈췄는지와 이유. 취소(정지)는 주황, 실패·거절은 빨강.
            where = f"{min(route['index'] + 1, total)}/{total}"
            word = '취소' if state == CANCELED else '중단'
            self._event(route, 'warn' if state == CANCELED else 'bad',
                        f'{word} ({where}): {detail}')
        self._done.insert(0, route)
        del self._done[self.keep:]

    def _event(self, route, level, text):
        self._outbox.append({
            'time': time.time(), 'robot': route['robot_id'], 'kind': 'route', 'level': level,
            'text': f'경로 {text}',
            'data': {'route_id': route['route_id'], 'index': route['index'],
                     'total': len(route['legs']), 'state': route['state']}})

    def _flush(self):
        """쌓인 이벤트를 lock 밖에서 넘긴다 (on_event 가 다른 lock 을 잡으므로)."""
        with self._lock:
            events, self._outbox = self._outbox, []
        if events and self.on_event is not None:
            self.on_event(events)

    @staticmethod
    def _public(route):
        if route is None:
            return None
        result = {k: v for k, v in route.items() if not k.startswith('_')}
        result['legs'] = [dict(leg) for leg in route['legs']]
        return result

    # ---------- 스레드 ----------

    def start(self, period_sec=0.5):
        """step() 을 period_sec 마다 부르는 스레드를 띄운다 (ROS executor 를 막지 않게 따로)."""
        if self._thread is not None:
            return

        def loop():
            while not self._stop.wait(period_sec):
                self.step()

        self._thread = threading.Thread(target=loop, name='route_runner', daemon=True)
        self._thread.start()

    def shutdown(self, timeout=2.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
