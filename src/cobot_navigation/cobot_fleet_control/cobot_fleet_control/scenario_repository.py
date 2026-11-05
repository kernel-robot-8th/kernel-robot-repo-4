"""관제 원장에 시나리오 상태·재고 예약·자원 소유 관계를 기록한다."""

import json
import time

from .repository import encode


class ScenarioRepository:
    """기존 단일 프로세스의 SQLite 잠금과 트랜잭션 이벤트 원장을 사용한다."""

    def __init__(self, repository):
        self.repository = repository
        self.db = repository.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS scenario_orders (
                order_id TEXT PRIMARY KEY, payload TEXT NOT NULL, snapshot TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenario_stock (
                sku TEXT PRIMARY KEY, available INTEGER NOT NULL CHECK(available >= 0)
            );
            CREATE TABLE IF NOT EXISTS scenario_resources (
                name TEXT PRIMARY KEY, order_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenario_holds (
                robot_id TEXT PRIMARY KEY, reason TEXT NOT NULL
            );
        ''')

    def orders(self):
        """접수 순서를 반환해 선입선출 배정 순서를 일정하게 유지한다."""
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT snapshot FROM scenario_orders ORDER BY rowid')]

    def get(self, order_id):
        """저장 객체와 분리된 상태 사본을 읽는다."""
        row = self.db.execute('SELECT snapshot FROM scenario_orders WHERE order_id=?',
                              (order_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def stock(self, sku):
        """확인되지 않은 재고는 사용 불가로 처리하며 재고가 있다고 추정하지 않는다."""
        row = self.db.execute('SELECT available FROM scenario_stock WHERE sku=?',
                              (sku,)).fetchone()
        return row[0] if row else 0

    def holds(self):
        """운영자의 보류 상태를 영속 저장해 진행 중인 주문이 없는 로봇도 보호한다."""
        return dict(self.db.execute('SELECT robot_id, reason FROM scenario_holds'))

    def hold(self, robot_id, reason):
        """재시작이나 작업 명령 허용 전환으로 정지·수동 제어 보류를 해제하지 않는다."""
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO scenario_holds VALUES (?,?)',
                            (robot_id, reason))

    def clear_hold(self, robot_id):
        """운영자가 현장 상태를 명시적으로 확인한 뒤에만 호출한다."""
        with self.db:
            self.db.execute('DELETE FROM scenario_holds WHERE robot_id=?', (robot_id,))

    def set_stock(self, sku, quantity):
        """이미 예약된 수량과 별개로 가용 재고를 설정한다."""
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO scenario_stock VALUES (?,?)',
                            (sku, quantity))
            self._event({'type': 'inventory', 'sku': sku, 'available': quantity})

    def create(self, payload, snapshot):
        """실물 명령을 내리기 전에 재고 예약과 주문 접수를 하나의 트랜잭션으로 처리한다."""
        with self.db:
            if payload['kind'] == 'delivery':
                cursor = self.db.execute(
                    'UPDATE scenario_stock SET available=available-? '
                    'WHERE sku=? AND available>=?',
                    (payload['quantity'], payload['sku'], payload['quantity']))
                if cursor.rowcount != 1:
                    raise ValueError('재고 부족: 주문 거절')
            self.db.execute('INSERT INTO scenario_orders VALUES (?,?,?)',
                            (payload['order_id'], encode(payload), encode(snapshot)))
            self._event({'type': 'scenario', 'order': snapshot})

    def save(self, snapshot):
        """상태 변경과 해당 알림을 같은 트랜잭션에 저장한다."""
        with self.db:
            self.db.execute('UPDATE scenario_orders SET snapshot=? WHERE order_id=?',
                            (encode(snapshot), snapshot['order_id']))
            self._event({'type': 'scenario', 'order': snapshot})

    def _event(self, event):
        event = dict(event, recorded_at=time.time())
        cursor = self.db.execute('INSERT INTO outbox(payload) VALUES (?)', (encode(event),))
        event['event_id'] = cursor.lastrowid
        self.db.execute('UPDATE outbox SET payload=? WHERE event_id=?',
                        (encode(event), cursor.lastrowid))

    def event(self, event):
        """기존 이력을 덮어쓰지 않고 경보와 운영자 감사 기록을 추가한다."""
        with self.db:
            self._event(event)

    def acquire(self, order_id, names):
        """요청한 자원을 하나의 트랜잭션으로 모두 확보하며 일부만 확보하지 않는다."""
        with self.db:
            for name in names:
                row = self.db.execute('SELECT order_id FROM scenario_resources WHERE name=?',
                                      (name,)).fetchone()
                if row and row[0] != order_id:
                    return False
            for name in names:
                self.db.execute('INSERT OR IGNORE INTO scenario_resources VALUES (?,?)',
                                (name, order_id))
        return True

    def release(self, order_id, names):
        """이탈이 명시적으로 확인된 자원만 소유자가 반납할 수 있다."""
        with self.db:
            for name in names:
                self.db.execute('DELETE FROM scenario_resources WHERE name=? AND order_id=?',
                                (name, order_id))

    def resources(self, order_id):
        """장애·복구 중에도 유지되는 자원 예약을 조회한다."""
        return [r[0] for r in self.db.execute(
            'SELECT name FROM scenario_resources WHERE order_id=? ORDER BY name', (order_id,))]

    def close_order(self, snapshot, restock=False):
        """실제 작업 영역에서 벗어났음을 확인한 뒤에만 자원을 반납한다."""
        with self.db:
            if restock:
                self.db.execute('INSERT INTO scenario_stock VALUES (?,?) '
                                'ON CONFLICT(sku) DO UPDATE '
                                'SET available=available+excluded.available',
                                (snapshot['sku'], snapshot['quantity']))
            self.db.execute('DELETE FROM scenario_resources WHERE order_id=?',
                            (snapshot['order_id'],))
            self.db.execute('UPDATE scenario_orders SET snapshot=? WHERE order_id=?',
                            (encode(snapshot), snapshot['order_id']))
            self._event({'type': 'scenario', 'order': snapshot})
