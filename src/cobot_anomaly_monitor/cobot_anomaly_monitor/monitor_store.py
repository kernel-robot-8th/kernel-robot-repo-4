"""이상 감지 기록 저장소. 관제 DB와 분리된 SQLite 파일에만 쓴다."""

import json
from pathlib import Path
import sqlite3

OPEN_ACKS = ('UNREAD', 'ACKNOWLEDGED')

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS scenarios (
    mission_id TEXT PRIMARY KEY, route TEXT NOT NULL, kind TEXT NOT NULL,
    sku TEXT NOT NULL, quantity INTEGER NOT NULL, robot_id TEXT,
    load_arm_id TEXT NOT NULL DEFAULT '', unload_arm_id TEXT NOT NULL DEFAULT '',
    current_step_seq INTEGER NOT NULL DEFAULT 0,
    current_step_code TEXT NOT NULL DEFAULT 'NONE',
    current_stage TEXT NOT NULL DEFAULT '', cargo_state TEXT NOT NULL DEFAULT 'EMPTY',
    mission_state TEXT NOT NULL, hold_reason TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_tasks (
    task_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, step_seq INTEGER NOT NULL,
    step_code TEXT NOT NULL, actor_id TEXT NOT NULL, expected_cargo_after TEXT NOT NULL,
    task_state TEXT NOT NULL, started_at REAL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS robot_live_state (
    robot_id TEXT PRIMARY KEY, op_state TEXT NOT NULL, cargo_state TEXT NOT NULL,
    current_zone TEXT NOT NULL, last_waypoint TEXT NOT NULL DEFAULT '',
    pose_x REAL, pose_y REAL, pose_yaw REAL, speed_mps REAL,
    active_mission_id TEXT, active_step_seq INTEGER NOT NULL DEFAULT 0,
    active_step_code TEXT NOT NULL DEFAULT 'NONE', updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cctv_anomaly_events (
    event_id TEXT PRIMARY KEY, detected_at REAL NOT NULL, last_seen REAL NOT NULL,
    repeat_count INTEGER NOT NULL DEFAULT 1, camera_id TEXT NOT NULL,
    vision_class TEXT NOT NULL, confidence REAL NOT NULL, bbox_json TEXT NOT NULL DEFAULT '[]',
    map_x REAL, map_y REAL, zone_id TEXT NOT NULL DEFAULT '',
    linked_robot_id TEXT, linked_mission_id TEXT,
    robot_step_at_event TEXT NOT NULL DEFAULT 'NONE',
    robot_cargo_at_event TEXT NOT NULL DEFAULT 'UNKNOWN',
    judgment TEXT NOT NULL, recommended_action TEXT NOT NULL,
    stop_scope TEXT NOT NULL DEFAULT 'ROBOT',
    stop_targets_json TEXT NOT NULL DEFAULT '[]', alarm_text TEXT NOT NULL DEFAULT '',
    control_action TEXT NOT NULL, control_detail TEXT NOT NULL DEFAULT '',
    ack_state TEXT NOT NULL DEFAULT 'UNREAD', resolved_by TEXT NOT NULL DEFAULT '',
    resolved_note TEXT NOT NULL DEFAULT '', resolved_at REAL,
    hold_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trace_orders (
    order_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_attempts (
    request_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, stage TEXT NOT NULL,
    robot_id TEXT, attempt INTEGER, first_seen REAL NOT NULL, task TEXT
);
CREATE INDEX IF NOT EXISTS trace_attempt_order ON trace_attempts(order_id, first_seen);
CREATE TABLE IF NOT EXISTS trace_robot_reports (
    robot_id TEXT NOT NULL, command_id TEXT NOT NULL, observation TEXT NOT NULL,
    PRIMARY KEY(robot_id, command_id)
);
CREATE TABLE IF NOT EXISTS trace_work_wire (
    order_id TEXT NOT NULL, request_id TEXT NOT NULL, kind TEXT NOT NULL,
    at REAL NOT NULL, payload TEXT NOT NULL, UNIQUE(order_id, request_id, kind, payload)
);
CREATE INDEX IF NOT EXISTS trace_wire_order ON trace_work_wire(order_id);
CREATE TABLE IF NOT EXISTS trace_terminal_resources (
    order_id TEXT PRIMARY KEY, recorded_at REAL NOT NULL, event_id INTEGER NOT NULL,
    job_state TEXT NOT NULL, resources TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_work (
    request_id TEXT PRIMARY KEY, state TEXT NOT NULL, request_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS manual_work_order ON manual_work(json_extract(request_json,'$.order_id'))
    WHERE json_valid(request_json);
"""
# 이미 만들어진 DB에는 CREATE TABLE IF NOT EXISTS로 열이 생기지 않는다. 시작 때 따로 더한다.
ADDED_COLUMNS = (
    ('cctv_anomaly_events', 'stop_scope', "TEXT NOT NULL DEFAULT 'ROBOT'"),
    ('cctv_anomaly_events', 'hold_seen', 'INTEGER NOT NULL DEFAULT 0'),
)


class MonitorStore:
    """실행기 스레드 하나에서만 쓰는 기록 저장소."""

    def __init__(self, path):
        path = str(Path(path).expanduser())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._add_columns()

    def _add_columns(self):
        for table, name, spec in ADDED_COLUMNS:
            if name in [row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')]:
                continue
            try:
                self._write(f'ALTER TABLE {table} ADD COLUMN {name} {spec}')
            except sqlite3.OperationalError as error:
                # 같은 파일을 여는 다른 프로세스가 확인과 추가 사이에 먼저 더한 경우다.
                if 'duplicate column name' not in str(error):
                    raise

    def close(self):
        """연결을 닫는다."""
        self.db.close()

    def _rows(self, query, *args):
        return [dict(row) for row in self.db.execute(query, args)]

    def _write(self, query, *args):
        with self.db:
            self.db.execute(query, args)

    def _upsert(self, table, key, row):
        names = ', '.join(row)
        marks = ', '.join('?' for _ in row)
        changes = ', '.join(f'{name}=excluded.{name}' for name in row if name != key)
        self._write(f'INSERT INTO {table} ({names}) VALUES ({marks}) '
                    f'ON CONFLICT({key}) DO UPDATE SET {changes}', *row.values())

    def scenario(self, mission_id):
        """시나리오 한 건을 읽는다."""
        rows = self._rows('SELECT * FROM scenarios WHERE mission_id=?', mission_id)
        return rows[0] if rows else None

    def scenarios(self, limit=50):
        """최근 시나리오를 새것부터 읽는다."""
        return self._rows('SELECT * FROM scenarios ORDER BY created_at DESC LIMIT ?', limit)

    def save_scenario(self, row):
        """주문 상태를 시나리오 표에 맞춘다."""
        self._upsert('scenarios', 'mission_id', row)

    def set_hold_reason(self, mission_id, reason, keep=False):
        """CCTV 정지 사유를 남긴다. 관제 주문 상태는 PAUSED 그대로다. keep이면 있던 사유를 둔다."""
        self._write('UPDATE scenarios SET hold_reason=? WHERE mission_id=?'
                    + (" AND hold_reason=''" if keep else ''), reason, mission_id)

    def tasks(self, mission_id):
        """시나리오의 단계 이력을 순서대로 읽는다."""
        return self._rows('SELECT * FROM scenario_tasks WHERE mission_id=? ORDER BY step_seq',
                          mission_id)

    def save_task(self, row):
        """단계 시작 기록을 남긴다."""
        self._upsert('scenario_tasks', 'task_id', row)

    def update_task(self, task_id, state, finished_at=None):
        """단계 상태를 바꾼다. 종료 시각은 한 번만 적는다."""
        self._write('UPDATE scenario_tasks SET task_state=?, '
                    'finished_at=COALESCE(finished_at, ?) WHERE task_id=?',
                    state, finished_at, task_id)

    def save_live(self, row):
        """로봇 상태 한 건을 갱신한다."""
        self._upsert('robot_live_state', 'robot_id', row)

    def live_states(self):
        """로봇 상태 전체를 읽는다."""
        return self._rows('SELECT * FROM robot_live_state ORDER BY robot_id')

    def event(self, event_id):
        """이상 이벤트 한 건을 읽는다."""
        rows = self._rows('SELECT * FROM cctv_anomaly_events WHERE event_id=?', event_id)
        return rows[0] if rows else None

    def events(self, limit=50):
        """최근 이상 이벤트를 새것부터 읽는다."""
        return self._rows(
            'SELECT * FROM cctv_anomaly_events ORDER BY detected_at DESC LIMIT ?', limit)

    def open_events(self):
        """아직 해결하지 않은 이벤트를 읽는다."""
        marks = ', '.join('?' for _ in OPEN_ACKS)
        return self._rows(
            f'SELECT * FROM cctv_anomaly_events WHERE ack_state IN ({marks})', *OPEN_ACKS)

    def open_stop_events(self, actions):
        """정지 요청이 나간 채 열려 있는 이벤트만 읽는다. 스냅샷마다 부르므로 범위를 좁힌다."""
        marks = [', '.join('?' for _ in group) for group in (OPEN_ACKS, actions)]
        return self._rows(
            f'SELECT * FROM cctv_anomaly_events WHERE ack_state IN ({marks[0]}) '
            f'AND control_action IN ({marks[1]})', *OPEN_ACKS, *actions)

    def resolved_since(self, since):
        """since 뒤에 RESOLVED로 닫힌 이벤트를 늦게 닫힌 것부터 읽는다."""
        return self._rows(
            "SELECT * FROM cctv_anomaly_events WHERE ack_state='RESOLVED' AND resolved_at>=? "
            'ORDER BY resolved_at DESC', since)

    def add_event(self, row):
        """판정을 기록한다."""
        self._upsert('cctv_anomaly_events', 'event_id', row)

    def touch_event(self, event_id, seen_at):
        """같은 물체의 재검출을 기존 이벤트에 합친다."""
        self._write('UPDATE cctv_anomaly_events SET last_seen=?, repeat_count=repeat_count+1 '
                    'WHERE event_id=?', seen_at, event_id)

    def set_control(self, event_id, action, detail):
        """조치와 그 결과를 남긴다."""
        self._write('UPDATE cctv_anomaly_events SET control_action=?, control_detail=? '
                    'WHERE event_id=?', action, json.dumps(detail, ensure_ascii=False), event_id)

    def mark_hold_seen(self, event_id):
        """정지가 관제 스냅샷에 반영된 것을 본 사건에 표시한다. 재시작 뒤에도 남는다."""
        self._write('UPDATE cctv_anomaly_events SET hold_seen=1 WHERE event_id=?', event_id)

    def set_ack(self, event_id, state, operator, note, at):
        """운영자 확인 결과를 남긴다."""
        self._write('UPDATE cctv_anomaly_events SET ack_state=?, resolved_by=?, resolved_note=?, '
                    'resolved_at=? WHERE event_id=?', state, operator, note, at, event_id)

    def close_recovered(self, event_id, operator, note, at):
        """관제에서 풀린 사건을 닫는다. 운영자가 먼저 남긴 이름과 메모는 지우지 않는다."""
        self._write(
            "UPDATE cctv_anomaly_events SET ack_state='RESOLVED', "
            "resolved_by=CASE WHEN resolved_by='' THEN ? ELSE resolved_by END, "
            "resolved_note=CASE WHEN resolved_note='' THEN ? "
            "ELSE resolved_note || ' / ' || ? END, resolved_at=? WHERE event_id=?",
            operator, note, note, at, event_id)

    def work(self, request_id):
        """수동 작업 요청 한 건을 읽는다."""
        rows = self._rows('SELECT * FROM manual_work WHERE request_id=?', request_id)
        return rows[0] if rows else None

    def works(self, state):
        """상태가 같은 수동 작업 요청을 접수 순서로 읽는다."""
        return self._rows('SELECT * FROM manual_work WHERE state=? ORDER BY created_at', state)

    def works_for_order(self, order_id):
        return self._rows(
            "SELECT * FROM manual_work WHERE json_valid(request_json) "
            "AND json_extract(request_json,'$.order_id')=? "
            "ORDER BY created_at, rowid", order_id)

    def order_work_history(self, order_id):
        history = []
        for row in self.works_for_order(order_id):
            item = dict(json.loads(row['request_json']), state=row['state'],
                        created_at=row['created_at'], updated_at=row['updated_at'],
                        result=json.loads(row['result_json']) if row['result_json'] else {})
            history.append(item)
        return history

    def observe_work(self, kind, message, at):
        if not all(isinstance(message.get(key), str) and message[key]
                   for key in ('order_id', 'request_id', 'stage')):
            return
        self._write('INSERT OR IGNORE INTO trace_work_wire VALUES (?,?,?,?,?)',
                    message['order_id'], message['request_id'], kind, at,
                    json.dumps(message, sort_keys=True, ensure_ascii=False))

    def record_control(self, kind, order_id, request_id, payload, at):
        self._write('INSERT OR IGNORE INTO trace_work_wire VALUES (?,?,?,?,?)',
                    order_id, request_id, kind, at, json.dumps(payload, ensure_ascii=False))

    def wire_page(self, order_id, after):
        """주문별 수신 원문을 rowid 커서 순으로 조회한다. 페이지당 최대 50건."""
        rows = self._rows(
            'SELECT rowid AS id, at, kind, request_id, payload FROM trace_work_wire '
            'WHERE order_id=? AND rowid>? ORDER BY rowid LIMIT 51', order_id, after)
        page = rows[:50]
        for row in page:
            row['payload'] = json.loads(row['payload'])
        return {'order_id': order_id, 'events': page,
                'next_cursor': page[-1]['id'] if len(rows) > 50 else None}

    def observed_work(self, order_id, known_requests=()):
        rows = self._rows("SELECT * FROM trace_work_wire WHERE order_id=? AND kind IN ('request','result') ORDER BY at,rowid", order_id)
        requests = {r['request_id']: dict(r) for r in known_requests}
        results = {}
        for row in rows:
            msg = json.loads(row['payload'])
            rid = row['request_id']
            if row['kind'] == 'request':
                request = requests.setdefault(rid, {})
                if 'wire_observed_at' not in request:
                    request.update(msg, wire_observed_at=row['at'])
                    request.setdefault('created_at', row['at'])
            else:
                results.setdefault(rid, []).append(dict(at=row['at'], payload=msg))
        for rid, request in requests.items():
            request['wire_results'] = results.pop(rid, [])
        return list(requests.values()), [event for group in results.values() for event in group]

    def record_terminal_resources(self, event):
        resources = event.get('resources')
        if (event.get('job_state') not in ('COMPLETED', 'FAILED')
                or not isinstance(event.get('order_id'), str)
                or type(event.get('event_id')) is not int
                or type(event.get('recorded_at')) not in (int, float)
                or not isinstance(resources, list) or not all(isinstance(r, str) for r in resources)):
            return
        self._write(
            'INSERT INTO trace_terminal_resources VALUES (?,?,?,?,?) ON CONFLICT(order_id) '
            'DO UPDATE SET recorded_at=excluded.recorded_at,event_id=excluded.event_id,'
            'job_state=excluded.job_state,resources=excluded.resources '
            'WHERE (excluded.recorded_at,excluded.event_id) > (recorded_at,event_id)',
            event['order_id'], event['recorded_at'], event['event_id'], event['job_state'],
            json.dumps(resources, ensure_ascii=False))

    def terminal_resources(self, order_id):
        rows = self._rows('SELECT * FROM trace_terminal_resources WHERE order_id=?', order_id)
        if rows:
            rows[0]['resources'] = json.loads(rows[0]['resources'])
            return rows[0]

    def record_trace_snapshot(self, orders, tasks, at, statuses, seen):
        with self.db:
            for order in orders:
                oid = order['order_id']
                self.db.execute(
                    'INSERT INTO trace_orders VALUES (?,?) ON CONFLICT(order_id) DO UPDATE '
                    'SET snapshot=excluded.snapshot WHERE snapshot!=excluded.snapshot',
                    (oid, json.dumps(order, ensure_ascii=False)))
                if order.get('request_id') and order.get('stage'):
                    self.db.execute(
                        'INSERT OR IGNORE INTO trace_attempts VALUES (?,?,?,?,?,?,NULL)',
                        (order['request_id'], oid, order['stage'], order.get('robot_id'),
                         order.get('attempt'), at))
            for task in tasks:
                # 구역/정지는 동시점의 관측이다. 명령 수신 확인으로 취급하지 않는다.
                robot = task.get('robot_id')
                sample = statuses.get(robot, {})
                ts = seen.get(robot, {}).get('patrol_status')
                saved = dict(task)
                if (ts is not None and 0 <= at - ts <= 3
                        and abs(ts - task.get('updated_at', 0)) <= 3):
                    saved['robot_at_observation'] = {
                        k: sample[k] for k in ('held_zone', 'arrived_zone', 'state', 'central_latched')
                        if k in sample}
                payload = json.dumps(saved, ensure_ascii=False)
                self.db.execute(
                    'UPDATE trace_attempts SET task=? WHERE request_id=? AND robot_id=? '
                    "AND task IS NOT ? AND (task IS NULL OR json_extract(task,'$.state') "
                    "NOT IN ('SUCCEEDED','FAILED','UNKNOWN') OR json_extract(task,'$.state') != ?)",
                    (payload, task.get('task_id'), robot, payload, task.get('state')))

    def record_robot_report(self, robot, status):
        cid = status.get('command_id')
        if not isinstance(cid, str) or not cid:
            return
        row = self.db.execute('SELECT observation FROM trace_robot_reports WHERE robot_id=? '
                              'AND command_id=?', (robot, cid)).fetchone()
        report = json.loads(row[0]) if row else {}
        for key in ('held_zone', 'arrived_zone'):
            if status.get(key):
                report[key] = status[key]
        if status.get('task_finished') is True:
            report.update(task_finished=True, terminal_state=status.get('state'))
        report['last_state'] = status.get('state')
        payload = json.dumps(report, ensure_ascii=False)
        if not row or payload != row[0]:
            self._write('INSERT OR REPLACE INTO trace_robot_reports VALUES (?,?,?)',
                        robot, cid, payload)

    def trace_order(self, order_id):
        row = self.db.execute('SELECT snapshot FROM trace_orders WHERE order_id=?',
                              (order_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def trace_attempts(self, order_id):
        return self._rows(
            'SELECT a.*, r.observation FROM trace_attempts a LEFT JOIN trace_robot_reports r '
            'ON r.robot_id=a.robot_id AND r.command_id=a.request_id '
            'WHERE a.order_id=? ORDER BY first_seen, a.rowid', order_id)

    def add_work(self, request_id, state, request, at):
        """요청 원문을 남긴다. 같은 request_id는 다시 받지 않는다."""
        self._write('INSERT OR IGNORE INTO manual_work (request_id, state, request_json, '
                    'created_at, updated_at) VALUES (?, ?, ?, ?, ?)', request_id, state,
                    json.dumps(request, ensure_ascii=False), at, at)

    def finish_work(self, request_id, state, result, at):
        """응답 원문을 남긴다. 관제 DB는 data를 저장하지 않는다."""
        self._write('UPDATE manual_work SET state=?, result_json=?, updated_at=? '
                    'WHERE request_id=?', state, json.dumps(result, ensure_ascii=False), at,
                    request_id)

    def claim_work(self, request_id, state, result, at):
        """발행 전에 결정권을 한 번만 확보한다. 저장된 결과를 재시작 때 재발행하지 않는다."""
        with self.db:
            changed = self.db.execute(
                "UPDATE manual_work SET state=?, result_json=?, updated_at=? "
                "WHERE request_id=? AND state='PENDING'",
                (state, json.dumps(result, ensure_ascii=False), at, request_id))
            return changed.rowcount == 1
