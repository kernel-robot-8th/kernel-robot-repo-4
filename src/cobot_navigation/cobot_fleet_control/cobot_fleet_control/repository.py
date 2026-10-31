"""SQLite 구현: 업무 상태와 MQTT 발행 대기 이벤트를 같은 트랜잭션에 기록한다."""

import json
import sqlite3
import time
from typing import Protocol


def encode(value):
    """동일 명령 재수신 비교를 위해 키 순서를 고정한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Repository(Protocol):
    """추후 서버 DB로 교체할 저장소 경계."""

    def get(self, command_id): ...
    def busy(self, robot_id): ...
    def create(self, command): ...
    def transition(self, command_id, state, detail=''): ...
    def pending(self, limit=100): ...
    def acknowledge(self, event_id): ...
    def recover(self): ...
    def record_status(self, robot_id, status): ...
    def record_bt_snapshot(self, snapshot): ...


class SqliteRepository:
    """단일 관제 프로세스용 영속 저장소. 여러 서버 실행은 별도 리더 선출이 필요하다."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS robot_status (
                robot_id TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0
            );
        """)

    def get(self, command_id):
        """명령 ID 단위 최신 상태 조회."""
        row = self.db.execute('SELECT * FROM commands WHERE command_id=?',
                              (command_id,)).fetchone()
        return dict(row) if row else None

    def busy(self, robot_id):
        """타임아웃·재시작 불명 상태도 점유를 유지해 중복 이동을 막는다."""
        return self.db.execute(
            'SELECT 1 FROM commands WHERE robot_id=? AND state NOT IN '
            "('SUCCEEDED','FAILED')", (robot_id,)).fetchone() is not None

    def create(self, command):
        """접수 내역이 디스크에 기록된 후에만 BT 실행을 허용한다."""
        with self.db:
            self.db.execute('INSERT INTO commands VALUES (?,?,?,?,?)',
                            (command.command_id, command.robot_id,
                             encode(command.payload()), 'ACCEPTED', ''))
            self._event(command.command_id, 'ACCEPTED', '')

    def _event(self, command_id, state, detail):
        row = self.get(command_id)
        event = {'command_id': command_id, 'robot_id': row['robot_id'],
                 'state': state, 'detail': detail, 'type': 'command_state',
                 'recorded_at': time.time()}
        cursor = self.db.execute('INSERT INTO outbox(payload) VALUES (?)', (encode(event),))
        event['event_id'] = cursor.lastrowid
        self.db.execute('UPDATE outbox SET payload=? WHERE event_id=?',
                        (encode(event), cursor.lastrowid))

    def transition(self, command_id, state, detail=''):
        """상태 변경과 외부 통지 예약은 함께 커밋한다."""
        row = self.get(command_id)
        if row['state'] == state and row['detail'] == detail:
            return
        with self.db:
            self.db.execute('UPDATE commands SET state=?, detail=? WHERE command_id=?',
                            (state, detail, command_id))
            self._event(command_id, state, detail)

    def pending(self, limit=100):
        """브로커 확인을 받지 못한 이벤트를 순서대로 재전송한다."""
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM outbox WHERE acknowledged=0 ORDER BY event_id LIMIT ?', (limit,))]

    def acknowledge(self, event_id):
        """MQTT PUBACK 수신 후에만 발행 완료로 기록한다."""
        with self.db:
            self.db.execute('UPDATE outbox SET acknowledged=1 WHERE event_id=?', (event_id,))

    def recover(self):
        """재시작 시 물리 동작 여부를 모르므로 자동으로 다시 명령하지 않는다."""
        rows = self.db.execute('SELECT command_id FROM commands WHERE state IN '
                               "('ACCEPTED','RUNNING')").fetchall()
        for row in rows:
            self.transition(row['command_id'], 'UNKNOWN', '서버 재시작: 현장 확인 필요')

    def record_status(self, robot_id, status):
        """실제 로봇 상태 원문과 서버 수신 시각을 보존해 UI가 데이터 출처를 알게 한다."""
        received_at = time.time()
        event = {'type': 'robot_status', 'robot_id': robot_id,
                 'status': status, 'recorded_at': received_at}
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO robot_status VALUES (?,?,?)',
                            (robot_id, encode(status), received_at))
            cursor = self.db.execute('INSERT INTO outbox(payload) VALUES (?)', (encode(event),))
            event['event_id'] = cursor.lastrowid
            self.db.execute('UPDATE outbox SET payload=? WHERE event_id=?',
                            (encode(event), cursor.lastrowid))

    def record_bt_snapshot(self, snapshot):
        """BT 상태 변경도 기존 영속 outbox를 통해 UI로 전달한다."""
        event = dict(snapshot)
        with self.db:
            cursor = self.db.execute('INSERT INTO outbox(payload) VALUES (?)', (encode(event),))
            event['event_id'] = cursor.lastrowid
            self.db.execute('UPDATE outbox SET payload=? WHERE event_id=?',
                            (encode(event), cursor.lastrowid))

    def close(self):
        """DB 연결 해제."""
        self.db.close()
