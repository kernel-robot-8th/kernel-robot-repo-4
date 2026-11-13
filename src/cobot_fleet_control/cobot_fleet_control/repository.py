"""SQLite 실행 원장: 업무 상태와 ROS 통지 이벤트를 같은 트랜잭션에 기록한다."""

import fcntl
import json
import sqlite3
import time


def encode(value):
    """동일 명령 재수신 비교를 위해 키 순서를 고정한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class SqliteRepository:
    """단일 관제 프로세스용 영속 저장소. 여러 서버 실행은 별도 리더 선출이 필요하다."""

    def __init__(self, path):
        self.lock = open(path + '.lock', 'a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lock.close()
            raise RuntimeError('관제 DB 사용 중: fleet 서버를 먼저 종료하세요') from error
        try:
            self.db = sqlite3.connect(path)
        except Exception:
            self.lock.close()
            raise
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL,
                created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS command_confirmation (
                command_id TEXT PRIMARY KEY
            );
        """)
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(commands)')}
        for column in ('created_at', 'updated_at'):
            if column not in columns:
                self.db.execute(f'ALTER TABLE commands ADD COLUMN {column} REAL NOT NULL DEFAULT 0')
        self.db.commit()

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

    def active_commands(self, robot_id):
        """끝나지 않은(보냄 전·진행·결과 모름) 작업 ID, 최신순."""
        return [row[0] for row in self.db.execute(
            "SELECT command_id FROM commands WHERE robot_id=? "
            "AND state IN ('ACCEPTED','RUNNING','UNKNOWN') ORDER BY rowid DESC", (robot_id,))]

    def require_confirmation(self, command_id):
        """운영자 정지 뒤에는 지연 종료 패킷만으로 해제 버튼이 사라지지 않게 한다."""
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO command_confirmation VALUES (?)', (command_id,))

    def confirmation_required(self, command_id):
        """재시작 뒤에도 현장 확인이 필요한 작업을 구분한다."""
        return self.db.execute('SELECT 1 FROM command_confirmation WHERE command_id=?',
                               (command_id,)).fetchone() is not None

    def create(self, command):
        """접수 내역이 디스크에 기록된 후에만 BT 실행을 허용한다."""
        with self.db:
            now = time.time()
            self.db.execute('INSERT INTO commands '
                            '(command_id,robot_id,payload,state,detail,created_at,updated_at) '
                            'VALUES (?,?,?,?,?,?,?)',
                            (command.command_id, command.robot_id,
                             encode(command.payload()), 'ACCEPTED', '', now, now))
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
            self.db.execute('UPDATE commands SET state=?, detail=?, updated_at=? '
                            'WHERE command_id=?',
                            (state, detail, time.time(), command_id))
            self._event(command_id, state, detail)

    def resolve_unknown(self, command_id, robot_id, operator, reason):
        """현장 정지 확인 후 불명 작업 하나를 실패 확정하고 예약을 해제한다."""
        detail = f'운영자 확인 해제 ({operator}): {reason}'
        with self.db:
            row = self.get(command_id)
            if row is None:
                raise ValueError('해당 command_id가 없습니다')
            if row['robot_id'] != robot_id:
                raise ValueError('robot_id가 기존 작업과 일치하지 않습니다')
            if row['state'] != 'UNKNOWN':
                raise ValueError('UNKNOWN 상태의 작업만 수동 해제할 수 있습니다')
            self.db.execute('UPDATE commands SET state=?, detail=?, updated_at=? '
                            'WHERE command_id=?',
                            ('FAILED', detail, time.time(), command_id))
            self._event(command_id, 'FAILED', detail)
        return self.get(command_id)

    def pending(self, limit=100):
        """아직 ROS 발행 처리하지 않은 이벤트를 순서대로 반환한다."""
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM outbox WHERE acknowledged=0 ORDER BY event_id LIMIT ?', (limit,))]

    def acknowledge(self, event_id):
        """ROS 발행 처리 여부를 기록한다. 원격 수신 보장은 아니다."""
        with self.db:
            self.db.execute('UPDATE outbox SET acknowledged=1 WHERE event_id=?', (event_id,))

    def recover(self):
        """재시작 시 물리 동작 여부를 모르므로 자동으로 다시 명령하지 않는다."""
        rows = self.db.execute('SELECT command_id FROM commands WHERE state IN '
                               "('ACCEPTED','RUNNING')").fetchall()
        for row in rows:
            self.transition(row['command_id'], 'UNKNOWN', '서버 재시작: 현장 확인 필요')

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
        self.lock.close()
