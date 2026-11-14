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
주문·재고·결제·이력을 SQLite 에 둔다 (고객 주문, 보조 A).

ROS 없이 돈다. 스키마와 단계 설명은 src/cobot_control_center/docs/order_flow.md.
노드가 재시작해도 주문이 남아야 해서 파일 DB 를 쓴다. 시험은 ':memory:' 를 쓴다.
"""

import json
import sqlite3
import threading

# 2: 재고 위치를 선반 (행, 열)로 바꾸고 주문에 칸·열 웨이포인트를 남긴다.
SCHEMA_VERSION = 2

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory (
        sku TEXT PRIMARY KEY,
        shelf_row INTEGER NOT NULL CHECK (shelf_row >= 1),
        shelf_col INTEGER NOT NULL CHECK (shelf_col >= 1),
        qty_on_hand INTEGER NOT NULL CHECK (qty_on_hand >= 0),
        qty_reserved INTEGER NOT NULL DEFAULT 0 CHECK (qty_reserved >= 0),
        UNIQUE (shelf_row, shelf_col)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        sku TEXT NOT NULL,
        qty INTEGER NOT NULL,
        table_id TEXT NOT NULL,
        waypoint_id TEXT NOT NULL DEFAULT '',
        requester_role TEXT NOT NULL DEFAULT '',
        requester_id TEXT NOT NULL DEFAULT '',
        robot_id TEXT NOT NULL DEFAULT '',
        shelf_row INTEGER,
        shelf_col INTEGER,
        load_waypoint_id TEXT NOT NULL DEFAULT '',
        stage TEXT NOT NULL,
        stage_history TEXT NOT NULL DEFAULT '[]',
        failure_reason TEXT NOT NULL DEFAULT '',
        retry_count INTEGER NOT NULL DEFAULT 0,
        reserved INTEGER NOT NULL DEFAULT 0,
        robot_step TEXT NOT NULL DEFAULT '',
        next_step_at REAL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
        status TEXT NOT NULL,
        decided_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        at REAL NOT NULL,
        kind TEXT NOT NULL,
        value TEXT NOT NULL,
        actor_id TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT ''
    )
    """,
)

_ORDER_COLUMNS = (
    'order_id', 'idempotency_key', 'sku', 'qty', 'table_id', 'waypoint_id',
    'requester_role', 'requester_id', 'robot_id', 'shelf_row', 'shelf_col',
    'load_waypoint_id', 'stage', 'stage_history',
    'failure_reason', 'retry_count', 'reserved', 'robot_step', 'next_step_at',
    'created_at', 'updated_at',
)


class OrderDb:
    """SQLite 연결 하나를 감싼다. ROS 콜백 스레드가 여럿이라 잠금을 둔다."""

    def __init__(self, path):
        """DB 를 열고 표를 만든다. path 가 ':memory:' 이면 메모리 DB."""
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute('PRAGMA foreign_keys = ON')
        if path != ':memory:':
            # 쓰다가 전원이 꺼져도 DB 가 깨지지 않게 한다.
            self._conn.execute('PRAGMA journal_mode = WAL')
        self._check_schema_version(path)
        with self.transaction():
            for statement in _SCHEMA:
                self._conn.execute(statement)
            self._conn.execute(
                'INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)',
                ('schema_version', str(SCHEMA_VERSION)))

    def _check_schema_version(self, path):
        # CREATE TABLE IF NOT EXISTS 는 옛 표를 그대로 둔다. 옛 DB 를 조용히 쓰지 않게 막는다.
        has_meta = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone()
        if not has_meta:
            return
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is not None and row[0] != str(SCHEMA_VERSION):
            self._conn.close()
            raise RuntimeError(
                '주문 DB 스키마 v{} 는 지금 코드(v{})와 맞지 않는다. '
                '{} 를 지우고 다시 시작한다 (주문이 사라지고 재고를 다시 채운다).'.format(
                    row[0], SCHEMA_VERSION, path))

    def close(self):
        """연결을 닫는다."""
        with self._lock:
            self._conn.close()

    def transaction(self):
        """트랜잭션을 연다. with 블록 안의 쓰기를 한 번에 반영한다."""
        return _Transaction(self._conn, self._lock)

    # --- 재고 ---

    def seed_inventory(self, items):
        """재고가 비어 있을 때만 초기 재고를 넣는다. items: [(sku, shelf_row, shelf_col, qty)]."""
        with self.transaction():
            count = self._conn.execute('SELECT COUNT(*) FROM inventory').fetchone()[0]
            if count:
                return False
            self._conn.executemany(
                'INSERT INTO inventory (sku, shelf_row, shelf_col, qty_on_hand) '
                'VALUES (?, ?, ?, ?)',
                items)
            return True

    def list_inventory(self):
        """재고 전체를 sku 순으로 돌려준다."""
        with self._lock:
            rows = self._conn.execute('SELECT * FROM inventory ORDER BY sku').fetchall()
        return [dict(row) for row in rows]

    def get_inventory(self, sku):
        """SKU 한 개의 재고. 없으면 None."""
        with self._lock:
            row = self._conn.execute('SELECT * FROM inventory WHERE sku = ?', (sku,)).fetchone()
        return dict(row) if row else None

    def change_inventory(self, sku, on_hand_delta=0, reserved_delta=0):
        """재고 수량을 바꾼다. 음수가 되면 sqlite3.IntegrityError."""
        self._conn.execute(
            'UPDATE inventory SET qty_on_hand = qty_on_hand + ?, '
            'qty_reserved = qty_reserved + ? WHERE sku = ?',
            (on_hand_delta, reserved_delta, sku))

    # --- 주문 ---

    def insert_order(self, order):
        """주문 한 건을 넣는다. order 는 _ORDER_COLUMNS 를 키로 가진 dict."""
        row = dict(order)
        row['stage_history'] = json.dumps(row.get('stage_history', []))
        columns = [c for c in _ORDER_COLUMNS if c in row]
        self._conn.execute(
            'INSERT INTO orders ({}) VALUES ({})'.format(
                ', '.join(columns), ', '.join('?' for _ in columns)),
            [row[c] for c in columns])

    def update_order(self, order_id, **values):
        """주문 한 건의 칸을 바꾼다."""
        if 'stage_history' in values:
            values['stage_history'] = json.dumps(values['stage_history'])
        unknown = set(values) - set(_ORDER_COLUMNS)
        if unknown:
            raise ValueError('없는 칸: {}'.format(sorted(unknown)))
        columns = sorted(values)
        self._conn.execute(
            'UPDATE orders SET {} WHERE order_id = ?'.format(
                ', '.join('{} = ?'.format(c) for c in columns)),
            [values[c] for c in columns] + [order_id])

    def get_order(self, order_id):
        """주문 한 건. 없으면 None."""
        with self._lock:
            row = self._conn.execute(
                'SELECT * FROM orders WHERE order_id = ?', (order_id,)).fetchone()
        return _order_dict(row)

    def find_order_by_key(self, idempotency_key):
        """멱등 키로 주문을 찾는다. 없으면 None."""
        with self._lock:
            row = self._conn.execute(
                'SELECT * FROM orders WHERE idempotency_key = ?', (idempotency_key,)).fetchone()
        return _order_dict(row)

    def list_orders(self):
        """주문 전체를 만든 순서로 돌려준다."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT * FROM orders ORDER BY created_at, order_id').fetchall()
        return [_order_dict(row) for row in rows]

    def orders_due(self, now):
        """next_step_at 이 지난 주문 (시뮬레이션 진행 대상)."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT * FROM orders WHERE next_step_at IS NOT NULL AND next_step_at <= ? '
                'ORDER BY next_step_at, order_id', (now,)).fetchall()
        return [_order_dict(row) for row in rows]

    def count_orders(self):
        """주문 수 (주문 ID 번호용)."""
        with self._lock:
            return self._conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]

    # --- 결제·이력 ---

    def upsert_payment(self, order_id, status, decided_at):
        """결제 상태를 쓴다 (가짜 결제)."""
        self._conn.execute(
            'INSERT INTO payments (order_id, status, decided_at) VALUES (?, ?, ?) '
            'ON CONFLICT(order_id) DO UPDATE SET status = excluded.status, '
            'decided_at = excluded.decided_at',
            (order_id, status, decided_at))

    def get_payment(self, order_id):
        """결제 한 건. 없으면 None."""
        with self._lock:
            row = self._conn.execute(
                'SELECT * FROM payments WHERE order_id = ?', (order_id,)).fetchone()
        return dict(row) if row else None

    def add_event(self, order_id, at, kind, value, actor_id='', detail=''):
        """이력 한 줄을 남긴다. 고치거나 지우는 함수는 두지 않는다."""
        self._conn.execute(
            'INSERT INTO order_events (order_id, at, kind, value, actor_id, detail) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (order_id, at, kind, value, actor_id, detail))

    def list_events(self, order_id):
        """주문 한 건의 이력을 순서대로 돌려준다."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT * FROM order_events WHERE order_id = ? ORDER BY event_id',
                (order_id,)).fetchall()
        return [dict(row) for row in rows]


class _Transaction:
    """BEGIN IMMEDIATE ~ COMMIT. 예외가 나면 ROLLBACK."""

    def __init__(self, conn, lock):
        self._conn = conn
        self._lock = lock
        self._depth = 0

    def __enter__(self):
        self._lock.acquire()
        if not self._conn.in_transaction:
            self._conn.execute('BEGIN IMMEDIATE')
            self._depth = 1
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._depth:
                if exc_type is None:
                    self._conn.execute('COMMIT')
                else:
                    self._conn.execute('ROLLBACK')
        finally:
            self._lock.release()
        return False


def _order_dict(row):
    if row is None:
        return None
    order = dict(row)
    order['stage_history'] = json.loads(order['stage_history'])
    return order
