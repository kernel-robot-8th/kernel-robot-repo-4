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
관제 작업 관리 (ROS 없는 순수 로직): 명령 검증, 작업 상태 추적, 작업 기록(SQLite).

TaskManager 는 받은 값(요청, 로봇 상태)으로 상태를 바꾸고, 노드가 할 일(로봇에 보낼 명령)을
돌려준다. 토픽을 직접 다루지 않아 ROS 없이 시험할 수 있다.

규칙 (draft/control_api_spec.md)
- 기록이 먼저, 발행은 나중이다. ACCEPTED 를 커밋한 뒤에만 명령을 돌려준다.
- 결과를 모르는(UNKNOWN) 작업이 있는 로봇에는 보내지 않는다. 실제로는 움직이고 있을 수 있다.
- 켤 때 끝나지 않은 작업은 UNKNOWN 으로 바꾸고 다시 보내지 않는다.
"""

import datetime
import json
import os
import sqlite3
import time
import uuid

from cobot_control_center.fleet_api_utils import _ros_params

OPERATIONS = ('goto', 'zone', 'leave', 'home')
STOP_OPERATIONS = ('stop', 'emergency_stop')
ACTIVE_STATES = ('ACCEPTED', 'SENT', 'RUNNING')
RESOLVE_RESULTS = ('SUCCEEDED', 'FAILED', 'STOPPED')
# 로봇 끝 상태 → 작업 끝 상태
FINAL_STATES = {'DONE': 'SUCCEEDED', 'FAILED': 'FAILED', 'STOPPED': 'STOPPED'}
# 로봇이 이 상태면 관제가 보낸 작업이 없어도 바쁘다 (예: 스스로 시작한 유휴 복귀).
BUSY_ROBOT_STATES = frozenset({'STARTING', 'MOVING', 'QUEUEING', 'WAITING_ZONE', 'ARRIVED',
                               'LEAVING_ZONE', 'RETREATING', 'RETURNING', 'RETRY'})
# 로봇이 스스로 시작한 유휴 복귀의 STARTING detail. 관제 작업의 시작으로 보지 않는다.
IDLE_RETURN_DETAIL = 'idle return'
RESTART_DETAIL = '관제 재시작: 현장 확인 필요'
SPEC_MODES = ('auto', 'v1', 'v2')


class TaskError(Exception):
    """요청을 처리하지 못함. status 는 HTTP 상태 코드로 그대로 쓴다."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ---------------------------------------------------------------------------
# 지점 규칙 (순찰 노드 _cmd_cb 와 같은 검사 + 미실측 지점 거절)
# ---------------------------------------------------------------------------

def load_robot_points(points_dir, robots):
    """
    로봇별 지점 규칙. <points_dir>/<robot>.yaml 을 읽기만 한다.

    {robot: {'points': 모든 지점, 'zone': 구역 지점, 'goto': goto 허용, 'placeholder': 미실측 P}}.
    goto 허용 = 일반 지점(P*) + 자기 홈 - 구역 지점 (순찰 노드의 goto_allowed 와 같다).
    (0, 0, 0) 인 P 지점은 미실측 예비값이라 goto 에서 뺀다. 로봇은 받지만 원점으로 간다.
    """
    rules = {}
    for robot in robots:
        params = _ros_params(os.path.join(points_dir, f'{robot}.yaml'))
        points = {str(k): [float(v) for v in value]
                  for k, value in (params.get('points') or {}).items()}
        zone = {str(n) for names in (params.get('zone_points') or {}).values()
                for n in names or []}
        general = {n for n in points if n.startswith('P') and n[1:].isdigit()}
        placeholder = {n for n in general if all(v == 0.0 for v in points[n])}
        home = str(params.get('home_name', ''))
        goto = ((general - placeholder) | ({home} if home in points else set())) - zone
        rules[robot] = {'points': set(points), 'zone': zone, 'goto': goto,
                        'placeholder': placeholder, 'home': home}
    return rules


def check_points(rule, operation, points):
    """지점이 맞으면 None, 틀리면 이유 문구 (로봇 FAILED detail 과 같은 모양)."""
    if operation in ('leave', 'home'):
        return f'{operation} takes no point' if points else None
    if not points:
        return 'no point given'
    if rule is None:
        return None
    unknown = [n for n in points if n not in rule['points']]
    if unknown:
        return f'unknown point: {unknown}'
    if operation == 'goto':
        in_zone = [n for n in points if n in rule['zone']]
        if in_zone:
            return f'use zone: {in_zone}'
        unmeasured = [n for n in points if n in rule['placeholder']]
        if unmeasured:
            return f'unmeasured point: {unmeasured}'
        denied = [n for n in points if n not in rule['goto']]
        if denied:
            return f'not allowed: {denied}'
        return None
    if len(points) != 1 or points[0] not in rule['zone']:
        return f'zone needs one zone point: {list(points)}'
    return None


def normalize_points(raw):
    """지점 목록을 대문자 이름 리스트로. 리스트가 아니면 TaskError(400)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise TaskError(400, 'points 는 문자열 목록이어야 함')
    return [p.strip().upper() for p in raw if p.strip()]


def v1_command(operation, points):
    """v1 patrol_cmd 문자열. 예: ('goto', ['P1', 'P2']) -> 'goto:P1,P2'."""
    return operation + (':' + ','.join(points) if points else '')


# ---------------------------------------------------------------------------
# 작업 기록 (SQLite)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    client_request_id TEXT UNIQUE,
    robot_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    points_json TEXT NOT NULL,
    command TEXT NOT NULL,
    spec TEXT NOT NULL,
    state TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    robot_id TEXT,
    task_id TEXT,
    type TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_task ON events(task_id);
"""

TASK_COLUMNS = ('task_id', 'client_request_id', 'robot_id', 'operation', 'points_json',
                'command', 'spec', 'state', 'detail', 'created_at', 'updated_at')


class TaskDB:
    """tasks(작업 하나 = 한 줄, 상태를 덮어씀)·events(추가만) 두 표."""

    def __init__(self, path, clock=time.time):
        if path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.clock = clock
        # 노드는 콜백을 한 스레드에서만 돌리지만, 만든 스레드와 쓰는 스레드가 다를 수 있다.
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def _event(self, robot_id, task_id, kind, detail):
        self.conn.execute(
            'INSERT INTO events(at, robot_id, task_id, type, detail_json) VALUES (?, ?, ?, ?, ?)',
            (self.clock(), robot_id, task_id, kind, json.dumps(detail, ensure_ascii=False)))

    def next_task_id(self):
        """t-YYYYMMDD-NNNN. 하루 안에서 순번이 오른다."""
        day = datetime.datetime.fromtimestamp(self.clock()).strftime('%Y%m%d')
        prefix = f't-{day}-'
        row = self.conn.execute(
            'SELECT task_id FROM tasks WHERE task_id LIKE ? ORDER BY task_id DESC LIMIT 1',
            (prefix + '%',)).fetchone()
        seq = int(row['task_id'][len(prefix):]) + 1 if row else 1
        return f'{prefix}{seq:04d}'

    def insert(self, task):
        """작업 한 줄과 첫 상태 이벤트를 한 트랜잭션으로 적는다."""
        with self.conn:
            self.conn.execute('BEGIN')
            self.conn.execute(
                f'INSERT INTO tasks({", ".join(TASK_COLUMNS)}) '
                f'VALUES ({", ".join("?" * len(TASK_COLUMNS))})',
                tuple(task[c] for c in TASK_COLUMNS))
            self._event(task['robot_id'], task['task_id'], 'state',
                        {'state': task['state'], 'detail': task['detail']})

    def set_state(self, task_id, state, detail, extra=None):
        """상태를 바꾸고 이벤트를 남긴다 (한 트랜잭션). 바뀐 작업을 돌려준다."""
        now = self.clock()
        with self.conn:
            self.conn.execute('BEGIN')
            self.conn.execute('UPDATE tasks SET state=?, detail=?, updated_at=? WHERE task_id=?',
                              (state, detail, now, task_id))
            robot = self.conn.execute('SELECT robot_id FROM tasks WHERE task_id=?',
                                      (task_id,)).fetchone()['robot_id']
            self._event(robot, task_id, 'state', {'state': state, 'detail': detail,
                                                  **(extra or {})})
        return self.get(task_id)

    def set_detail(self, task_id, detail):
        """진행 중 detail(지금 지점 등)만 바꾼다. 상태 변화가 아니라 이벤트는 남기지 않는다."""
        self.conn.execute('UPDATE tasks SET detail=?, updated_at=? WHERE task_id=?',
                          (detail, self.clock(), task_id))
        return self.get(task_id)

    def add_event(self, robot_id, task_id, kind, detail):
        with self.conn:
            self.conn.execute('BEGIN')
            self._event(robot_id, task_id, kind, detail)

    def _task(self, row):
        task = {c: row[c] for c in TASK_COLUMNS if c != 'points_json'}
        task['points'] = json.loads(row['points_json'])
        task['history'] = [
            {'at': e['at'], **json.loads(e['detail_json'])}
            for e in self.conn.execute(
                "SELECT at, detail_json FROM events WHERE task_id=? AND type='state' ORDER BY id",
                (task['task_id'],))]
        return task

    def get(self, task_id):
        row = self.conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        return self._task(row) if row else None

    def by_client_request(self, client_request_id):
        row = self.conn.execute('SELECT * FROM tasks WHERE client_request_id=?',
                                (client_request_id,)).fetchone()
        return self._task(row) if row else None

    def recent(self, limit=50):
        rows = self.conn.execute('SELECT * FROM tasks ORDER BY created_at DESC, task_id DESC '
                                 'LIMIT ?', (int(limit),)).fetchall()
        return [self._task(r) for r in rows]

    def in_states(self, states):
        marks = ', '.join('?' * len(states))
        rows = self.conn.execute(
            f'SELECT * FROM tasks WHERE state IN ({marks}) ORDER BY created_at',
            tuple(states)).fetchall()
        return [self._task(r) for r in rows]

    def recover(self):
        """켤 때: 끝나지 않은 작업을 UNKNOWN 으로. 다시 보내지 않는다. 바꾼 작업 목록."""
        return [self.set_state(t['task_id'], 'UNKNOWN', RESTART_DETAIL)
                for t in self.in_states(ACTIVE_STATES)]

    def prune(self, retention_days):
        """retention_days 보다 오래된 events 를 지운다. tasks 는 양이 적어 남긴다."""
        if retention_days <= 0:
            return 0
        cutoff = self.clock() - retention_days * 86400.0
        with self.conn:
            self.conn.execute('BEGIN')
            return self.conn.execute('DELETE FROM events WHERE at < ?', (cutoff,)).rowcount


# ---------------------------------------------------------------------------
# 작업 관리
# ---------------------------------------------------------------------------

class TaskManager:
    """
    요청 검증·작업 상태 추적. 메서드는 (결과, 할 일 목록) 을 돌려준다.

    할 일: {'robot', 'spec': 'v1'|'v2', 'operation', 'points', 'task_id', 'command'}.
    노드는 spec 에 맞춰 /pinkyN/patrol_cmd(v1) 또는 /pinkyN/patrol_command(v2) 로 낸다.
    changed 에는 바뀐 작업이 쌓인다. 노드가 꺼내 task_events 로 알린다.
    """

    def __init__(self, db, robots, rules=None, ack_timeout_sec=3.0, task_timeout_sec=300.0,
                 fleet_stale_sec=3.0, spec_mode='auto', v2_fresh_sec=3.0,
                 clock=time.time):
        if spec_mode not in SPEC_MODES:
            raise ValueError(f'spec_mode 는 {SPEC_MODES} 중 하나: {spec_mode}')
        self.db = db
        self.robots = list(robots)
        self.rules = rules or {}
        self.ack_timeout_sec = float(ack_timeout_sec)
        self.task_timeout_sec = float(task_timeout_sec)
        self.fleet_stale_sec = float(fleet_stale_sec)
        self.spec_mode = spec_mode
        self.v2_fresh_sec = float(v2_fresh_sec)
        self.clock = clock
        self.fleet = None
        self.fleet_received = None
        self.v2_seen = {}
        self.sent_at = {}      # task_id -> SENT 시각 (응답 기다림 시작)
        self.running_at = {}   # task_id -> RUNNING 시각
        self.changed = []

    # ---------- 입력: 로봇 상태 ----------

    def update_fleet(self, snapshot):
        self.fleet = snapshot
        self.fleet_received = self.clock()

    def _robot_view(self, robot):
        if self.fleet is None or self.clock() - self.fleet_received > self.fleet_stale_sec:
            raise TaskError(503, 'fleet_status 를 받지 못함 (fleet_status_node 확인)')
        return (self.fleet.get('robots') or {}).get(robot) or {}

    def spec_for(self, robot):
        if self.spec_mode != 'auto':
            return self.spec_mode
        seen = self.v2_seen.get(robot)
        return 'v2' if seen is not None and self.clock() - seen <= self.v2_fresh_sec else 'v1'

    def _active(self, robot, spec=None):
        for task in self.db.in_states(ACTIVE_STATES):
            if task['robot_id'] == robot and (spec is None or task['spec'] == spec):
                return task
        return None

    def _set(self, task, state, detail, extra=None):
        changed = self.db.set_state(task['task_id'], state, detail, extra)
        if state == 'RUNNING':
            self.running_at[task['task_id']] = self.clock()
        if state not in ACTIVE_STATES:
            self.sent_at.pop(task['task_id'], None)
            self.running_at.pop(task['task_id'], None)
        self.changed.append(changed)
        return changed

    def _detail(self, task, detail):
        if detail is not None and detail != task['detail']:
            self.changed.append(self.db.set_detail(task['task_id'], str(detail)))

    def on_v1_status(self, robot, status):
        """v1 patrol_status (dict). 작업 ID 가 없어 그 로봇의 진행 중 v1 작업 것으로 본다."""
        task = self._active(robot, 'v1')
        if task is None or task['state'] == 'ACCEPTED':
            return
        state, detail = status.get('state'), str(status.get('detail') or '')
        if state in FINAL_STATES:
            # SENT 에서 바로 오는 FAILED 는 로봇의 검증 실패, DONE 은 '이미 홈'.
            self._set(task, FINAL_STATES[state], detail, {'robot_state': state})
        elif task['state'] == 'SENT':
            # STARTING 을 놓쳐도 움직이기 시작한 상태가 오면 시작으로 본다. 유휴 복귀는 빼고.
            if state in BUSY_ROBOT_STATES and not (
                    state == 'STARTING' and detail == IDLE_RETURN_DETAIL):
                self._set(task, 'RUNNING', detail, {'robot_state': state})
        else:
            self._detail(task, f'{state} {detail}'.strip())

    def on_v2_state(self, robot, state):
        """v2 PatrolState (dict). task_id 가 같은 것만 그 작업에 붙인다."""
        self.v2_seen[robot] = self.clock()
        task = self._active(robot, 'v2')
        if task is None or task['task_id'] != state.get('task_id'):
            return
        name, detail = state.get('state'), str(state.get('detail') or '')
        if name in FINAL_STATES and (state.get('task_finished') or name == 'STOPPED'):
            # STOPPED 는 구역 후퇴 중에도 이미 멈춘 작업이다.
            self._set(task, FINAL_STATES[name], detail, {'robot_state': name})
        elif task['state'] == 'SENT':
            self._set(task, 'RUNNING', detail, {'robot_state': name})
        else:
            self._detail(task, f'{name} {detail}'.strip())

    def on_v2_ack(self, robot, ack):
        """v2 PatrolCommandAck (dict). 거절이면 REJECTED (이유는 로봇 문구 그대로)."""
        self.v2_seen[robot] = self.clock()
        task = self._active(robot, 'v2')
        if task is None or task['task_id'] != ack.get('task_id'):
            if ack.get('task_id'):
                self.db.add_event(robot, ack.get('task_id'), 'ack', ack)
            return
        if not ack.get('accepted'):
            self._set(task, 'REJECTED', f'robot: {ack.get("reason", "")}', {'ack': ack})
        elif task['state'] == 'SENT':
            self._set(task, 'RUNNING', task['detail'], {'ack': ack})

    # ---------- 입력: 관제 요청 ----------

    def create(self, request):
        """작업 만들기. (HTTP 상태, 작업) 와 할 일 목록. 처리 못 하면 TaskError."""
        crid = request.get('client_request_id')
        if not isinstance(crid, str) or not crid.strip():
            raise TaskError(400, 'client_request_id 가 필요함')
        robot = request.get('robot_id')
        operation = request.get('operation')
        points = normalize_points(request.get('points'))
        existing = self.db.by_client_request(crid)
        if existing is not None:
            if (existing['robot_id'], existing['operation'], existing['points']) != (
                    robot, operation, points):
                raise TaskError(409, '같은 client_request_id 에 다른 내용')
            return (200, existing), []
        if robot not in self.robots:
            raise TaskError(404, f'등록되지 않은 로봇: {robot}')
        if operation not in OPERATIONS:
            raise TaskError(400, f'operation 은 {list(OPERATIONS)} 중 하나: {operation}')

        status, reason = self._check(robot, operation, points)
        now = self.clock()
        spec = self.spec_for(robot)
        task = {'task_id': self.db.next_task_id(), 'client_request_id': crid,
                'robot_id': robot, 'operation': operation,
                'points_json': json.dumps(points), 'command': v1_command(operation, points),
                'spec': spec, 'state': 'ACCEPTED' if reason is None else 'REJECTED',
                'detail': reason or '', 'created_at': now, 'updated_at': now}
        self.db.insert(task)
        stored = self.db.get(task['task_id'])
        self.changed.append(stored)
        if reason is not None:
            return (status, stored), []
        # 기록이 먼저: ACCEPTED 를 커밋한 뒤에 SENT 로 바꾸고 할 일을 돌려준다.
        sent = self._set(stored, 'SENT', '')
        self.sent_at[sent['task_id']] = self.clock()
        action = {'robot': robot, 'spec': spec, 'operation': operation, 'points': points,
                  'task_id': sent['task_id'], 'command': sent['command']}
        return (202, sent), [action]

    def _check(self, robot, operation, points):
        """보내도 되는지. (HTTP 상태, 거절 이유) 또는 (None, None)."""
        reason = check_points(self.rules.get(robot), operation, points)
        if reason is not None:
            return 400, reason
        unknown = [t['task_id'] for t in self.db.in_states(('UNKNOWN',))
                   if t['robot_id'] == robot]
        if unknown:
            return 409, f'결과를 모르는 작업이 있음 (현장 확인 후 해제): {unknown}'
        active = self._active(robot)
        if active is not None:
            return 409, f'진행 중인 작업이 있음: {active["task_id"]}'
        view = self._robot_view(robot)
        if not view.get('online'):
            return 503, f'{robot} 연결 끊김'
        if view.get('state') in BUSY_ROBOT_STATES:
            return 409, f'{robot} 작업 중: {view.get("state")} {view.get("detail") or ""}'.strip()
        return None, None

    def stop(self, request):
        """정지. 바쁨과 상관없이 항상 보낸다. 작업 행을 만들지 않고 사건으로만 남긴다."""
        robot = request.get('robot_id')
        if robot not in self.robots:
            raise TaskError(404, f'등록되지 않은 로봇: {robot}')
        operation = 'emergency_stop' if request.get('emergency') else 'stop'
        spec = self.spec_for(robot)
        stop_id = f's-{uuid.uuid4().hex[:12]}'
        active = self._active(robot)
        result = {'robot_id': robot, 'operation': operation, 'spec': spec, 'stop_id': stop_id,
                  'task_id': active['task_id'] if active else None,
                  'client_request_id': request.get('client_request_id'),
                  'warning': ('비상정지: 구역 토큰을 쥔 채로 멈춤 (zone_manager 가 max_hold_sec 뒤 해제)'
                              if operation == 'emergency_stop' else '')}
        self.db.add_event(robot, result['task_id'], 'operator_stop', result)
        action = {'robot': robot, 'spec': spec, 'operation': operation, 'points': [],
                  'task_id': stop_id, 'command': operation}
        return (202, result), [action]

    def resolve(self, request):
        """UNKNOWN 작업을 사람이 확인하고 끝낸다. 기록은 지우지 않는다."""
        task = self.db.get(str(request.get('task_id')))
        if task is None:
            raise TaskError(404, f'없는 작업: {request.get("task_id")}')
        if task['state'] != 'UNKNOWN':
            raise TaskError(409, f'UNKNOWN 작업만 해제할 수 있음 (지금 {task["state"]})')
        result = request.get('result', 'FAILED')
        if result not in RESOLVE_RESULTS:
            raise TaskError(400, f'result 는 {list(RESOLVE_RESULTS)} 중 하나')
        note = str(request.get('note') or '')
        self.db.add_event(task['robot_id'], task['task_id'], 'resolve',
                          {'state': result, 'detail': f'해제: {note}'.strip(),
                           'client_request_id': request.get('client_request_id')})
        return (200, self._set(task, result, f'해제: {note}'.strip(),
                               {'resolved': True})), []

    # ---------- 시간 ----------

    def tick(self):
        """응답 없는 작업을 UNKNOWN 으로. 실제로는 움직이고 있을 수 있기 때문이다."""
        now = self.clock()
        for task in self.db.in_states(('SENT', 'RUNNING')):
            if task['state'] == 'SENT':
                start = self.sent_at.setdefault(task['task_id'], now)
                if now - start > self.ack_timeout_sec:
                    self._set(task, 'UNKNOWN',
                              f'응답 없음 ({self.ack_timeout_sec:g} s): 로봇이 무시했거나 끊김')
            else:
                start = self.running_at.setdefault(task['task_id'], now)
                if now - start > self.task_timeout_sec:
                    self._set(task, 'UNKNOWN', f'시간 초과 ({self.task_timeout_sec:g} s)')

    def take_changed(self):
        changed, self.changed = self.changed, []
        return changed

    def snapshot(self, limit=50):
        """백엔드가 캐시할 작업 목록."""
        return {'time': self.clock(), 'robots': self.robots,
                'spec': {r: self.spec_for(r) for r in self.robots},
                'tasks': self.db.recent(limit)}
