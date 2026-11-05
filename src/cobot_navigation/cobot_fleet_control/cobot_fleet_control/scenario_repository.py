"""Scenario state, inventory reservations and resource ownership in the fleet journal."""

import json
import time

from .repository import encode


class ScenarioRepository:
    """Use the existing single-process SQLite lock and transactional event journal."""

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
        """Return acceptance order for deterministic FIFO scheduling."""
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT snapshot FROM scenario_orders ORDER BY rowid')]

    def get(self, order_id):
        """Read a detached snapshot."""
        row = self.db.execute('SELECT snapshot FROM scenario_orders WHERE order_id=?',
                              (order_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def stock(self, sku):
        """Unknown inventory is unavailable, never an implicit positive stock."""
        row = self.db.execute('SELECT available FROM scenario_stock WHERE sku=?',
                              (sku,)).fetchone()
        return row[0] if row else 0

    def holds(self):
        """Persistent operator latches also protect robots without an active order."""
        return dict(self.db.execute('SELECT robot_id, reason FROM scenario_holds'))

    def hold(self, robot_id, reason):
        """A restart or arm toggle cannot clear a stop or manual-control latch."""
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO scenario_holds VALUES (?,?)',
                            (robot_id, reason))

    def clear_hold(self, robot_id):
        """Called only after explicit operator reconciliation."""
        with self.db:
            self.db.execute('DELETE FROM scenario_holds WHERE robot_id=?', (robot_id,))

    def set_stock(self, sku, quantity):
        """Set free stock, independently of already reserved quantities."""
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO scenario_stock VALUES (?,?)',
                            (sku, quantity))
            self._event({'type': 'inventory', 'sku': sku, 'available': quantity})

    def create(self, payload, snapshot):
        """Reserve stock and accept the order atomically, before any physical command."""
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
        """Commit a state change together with its notification."""
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
        """Append alarms and operator audit records without overwriting history."""
        with self.db:
            self._event(event)

    def acquire(self, order_id, names):
        """Acquire all requested resources atomically, with no partial acquisition."""
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
        """Only the owner may release explicitly cleared resources."""
        with self.db:
            for name in names:
                self.db.execute('DELETE FROM scenario_resources WHERE name=? AND order_id=?',
                                (name, order_id))

    def resources(self, order_id):
        """Show retained leases during faults and recovery."""
        return [r[0] for r in self.db.execute(
            'SELECT name FROM scenario_resources WHERE order_id=? ORDER BY name', (order_id,))]

    def close_order(self, snapshot, restock=False):
        """Release resources only after physical clearance has been established."""
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
