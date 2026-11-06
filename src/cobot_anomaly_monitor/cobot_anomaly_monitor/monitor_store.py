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
    stop_targets_json TEXT NOT NULL DEFAULT '[]', alarm_text TEXT NOT NULL DEFAULT '',
    control_action TEXT NOT NULL, control_detail TEXT NOT NULL DEFAULT '',
    ack_state TEXT NOT NULL DEFAULT 'UNREAD', resolved_by TEXT NOT NULL DEFAULT '',
    resolved_note TEXT NOT NULL DEFAULT '', resolved_at REAL
);
CREATE TABLE IF NOT EXISTS manual_work (
    request_id TEXT PRIMARY KEY, state TEXT NOT NULL, request_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""


class MonitorStore:
    """실행기 스레드 하나에서만 쓰는 기록 저장소."""

    def __init__(self, path):
        path = str(Path(path).expanduser())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

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

    def set_hold_reason(self, mission_id, reason):
        """CCTV 정지 사유를 남긴다. 관제 주문 상태는 PAUSED 그대로다."""
        self._write('UPDATE scenarios SET hold_reason=? WHERE mission_id=?', reason, mission_id)

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

    def set_ack(self, event_id, state, operator, note, at):
        """운영자 확인 결과를 남긴다."""
        self._write('UPDATE cctv_anomaly_events SET ack_state=?, resolved_by=?, resolved_note=?, '
                    'resolved_at=? WHERE event_id=?', state, operator, note, at, event_id)

    def work(self, request_id):
        """수동 작업 요청 한 건을 읽는다."""
        rows = self._rows('SELECT * FROM manual_work WHERE request_id=?', request_id)
        return rows[0] if rows else None

    def works(self, state):
        """상태가 같은 수동 작업 요청을 접수 순서로 읽는다."""
        return self._rows('SELECT * FROM manual_work WHERE state=? ORDER BY created_at', state)

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
