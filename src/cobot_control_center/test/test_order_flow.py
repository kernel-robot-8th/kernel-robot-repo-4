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

"""고객 주문 단계 규칙과 SQLite 저장을 ROS 없이 본다."""

from pathlib import Path
import sqlite3

from cobot_control_center import order_db
from cobot_control_center import order_flow as flow
from cobot_control_center.order_db import OrderDb
from cobot_control_center.store_layout import load_store_layout, parse_store_layout
import pytest

STEP = 3.0
LAYOUT_FILE = (Path(__file__).resolve().parents[2] / 'cobot_bringup' / 'config'
               / 'store_layout.yaml')


def _layout():
    return parse_store_layout({
        'shelf': {'rows': 3, 'columns': {1: 'WP_SHELF_C1', 2: 'WP_SHELF_C2', 3: 'WP_SHELF_C3'}},
        'locations': {'BENCH_1': {'name': '벤치', 'waypoint': 'WP_BENCH_DELIVERY'}},
    })


def _config(layout=None):
    return flow.OrderFlowConfig(
        layout=layout or _layout(), robot_ids=['pinky_1', 'pinky_2'], step_sec=STEP,
        repack_waypoint='WP_UNLOAD', home_waypoint='WP_HOME_1')


@pytest.fixture
def service():
    db = OrderDb(':memory:')
    db.seed_inventory([('SHOE_A', 2, 3, 2), ('SHOE_B', 1, 1, 0)])
    yield flow.OrderService(db, _config()), db
    db.close()


def _run_until(svc, order_id, now, stage):
    for _ in range(20):
        if svc.get_order(order_id)['stage'] == stage:
            return now
        now += STEP
        svc.tick(now)
    raise AssertionError('{} 에 닿지 못했다'.format(stage))


def test_submit_reserves_and_reaches_unloading(service):
    svc, db = service
    result = svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1', 'customer', 'phone-1')
    assert result == {'result': 'ACCEPTED', 'reject_code': '', 'order_id': 'ORD-00001',
                      'duplicate': False}
    assert db.get_inventory('SHOE_A')['qty_reserved'] == 1
    now = _run_until(svc, 'ORD-00001', 0.0, flow.STAGE_UNLOADING)
    order = svc.get_order('ORD-00001')
    assert [s for s, _ in order['stage_history']] == [
        'RECEIVED', 'ASSIGNED', 'LOADING', 'IN_TRANSIT', 'UNLOADING']
    assert order['robot_id'] == 'pinky_1'
    assert order['waypoint_id'] == 'WP_BENCH_DELIVERY'
    # 신발이 있는 칸과 그 열 앞 웨이포인트를 주문에 남긴다.
    assert (order['shelf_row'], order['shelf_col']) == (2, 3)
    assert order['load_waypoint_id'] == 'WP_SHELF_C3'
    loading = [e['detail'] for e in db.list_events('ORD-00001')
               if e['kind'] == 'robot' and e['value'] == 'LOADING']
    assert loading == ['goto WP_SHELF_C3 pick row 2 col 3']
    # 고객이 정할 때까지 더 넘어가지 않는다.
    svc.tick(now + 100)
    assert svc.get_order('ORD-00001')['stage'] == flow.STAGE_UNLOADING


def test_same_key_returns_same_order(service):
    svc, db = service
    first = svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    again = svc.submit(1.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    assert again['order_id'] == first['order_id']
    assert again['duplicate'] is True
    assert db.get_inventory('SHOE_A')['qty_reserved'] == 1


def test_paid_sells_shoe_and_completes(service):
    svc, db = service
    svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    now = _run_until(svc, 'ORD-00001', 0.0, flow.STAGE_UNLOADING)
    result = svc.decide(now, 'ORD-00001', 'PAID', 'phone-1')
    assert result == {'result': 'ACCEPTED', 'reject_code': '', 'stage': 'HANDOVER_CONFIRMED'}
    assert db.get_payment('ORD-00001')['status'] == 'PAID'
    assert db.get_inventory('SHOE_A') == {
        'sku': 'SHOE_A', 'shelf_row': 2, 'shelf_col': 3, 'qty_on_hand': 1, 'qty_reserved': 0}
    _run_until(svc, 'ORD-00001', now, flow.STAGE_COMPLETED)
    assert svc.get_order('ORD-00001')['next_step_at'] is None


def test_cancel_repacks_and_returns_to_shelf_column(service):
    svc, db = service
    svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    now = _run_until(svc, 'ORD-00001', 0.0, flow.STAGE_UNLOADING)
    assert svc.decide(now, 'ORD-00001', 'CANCEL')['stage'] == 'CANCELLED'
    assert db.get_payment('ORD-00001')['status'] == 'CANCELLED'
    for _ in range(5):
        now += STEP
        svc.tick(now)
    order = svc.get_order('ORD-00001')
    assert order['stage'] == flow.STAGE_CANCELLED
    assert order['robot_step'] == flow.ROBOT_STEP_DONE
    robot = [e['value'] for e in db.list_events('ORD-00001') if e['kind'] == 'robot']
    assert robot[-4:] == ['TO_REPACK', 'REPACKING', 'TO_WAREHOUSE', 'DONE']
    to_warehouse = [e['detail'] for e in db.list_events('ORD-00001')
                    if e['kind'] == 'robot' and e['value'] == 'TO_WAREHOUSE']
    assert to_warehouse == ['goto WP_SHELF_C3']
    # 신발은 팔리지 않았다. 창고에 돌아온 뒤 가점유만 풀린다.
    assert db.get_inventory('SHOE_A')['qty_on_hand'] == 2
    assert db.get_inventory('SHOE_A')['qty_reserved'] == 0


@pytest.mark.parametrize('decision,code', [('PAID', 'WRONG_STAGE'), ('MAYBE', 'BAD_DECISION')])
def test_decision_rejected_before_arrival(service, decision, code):
    svc, _ = service
    svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    assert svc.decide(1.0, 'ORD-00001', decision)['reject_code'] == code


def test_unknown_order_is_rejected(service):
    svc, _ = service
    assert svc.decide(0.0, 'ORD-99999', 'PAID')['reject_code'] == 'UNKNOWN_ORDER'


def test_no_stock_is_accepted_but_not_assigned(service):
    svc, _ = service
    result = svc.submit(0.0, 'k1', 'SHOE_B', 1, 'BENCH_1')
    assert result['result'] == 'ACCEPTED'
    assert result['reject_code'] == 'INVENTORY_UNAVAILABLE'
    svc.tick(100.0)
    assert svc.get_order(result['order_id'])['stage'] == flow.STAGE_RECEIVED


def test_unknown_table_fails(service):
    svc, _ = service
    result = svc.submit(0.0, 'k1', 'SHOE_A', 1, 'NOWHERE')
    order = svc.get_order(result['order_id'])
    assert order['stage'] == flow.STAGE_FAILED
    assert order['failure_reason'] == 'UNKNOWN_TABLE'


def test_shelf_column_missing_from_layout_fails():
    db = OrderDb(':memory:')
    db.seed_inventory([('SHOE_A', 1, 9, 1)])
    svc = flow.OrderService(db, _config())
    order = svc.get_order(svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')['order_id'])
    assert order['stage'] == flow.STAGE_FAILED
    assert order['failure_reason'] == flow.FAILURE_UNKNOWN_SHELF
    assert db.get_inventory('SHOE_A')['qty_reserved'] == 0
    db.close()


def test_one_sku_per_slot():
    db = OrderDb(':memory:')
    with pytest.raises(sqlite3.IntegrityError):
        db.seed_inventory([('SHOE_A', 1, 1, 1), ('SHOE_B', 1, 1, 1)])
    db.close()


def test_bad_role_is_rejected(service):
    svc, _ = service
    assert svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1', 'robot')['reject_code'] == (
        'ROLE_FORBIDDEN')


def test_orders_survive_reopen(tmp_path):
    path = str(tmp_path / 'orders.sqlite3')
    db = OrderDb(path)
    db.seed_inventory([('SHOE_A', 1, 1, 1)])
    flow.OrderService(db, _config()).submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    db.close()
    db = OrderDb(path)
    assert db.get_order('ORD-00001')['sku'] == 'SHOE_A'
    assert db.seed_inventory([('SHOE_A', 1, 1, 9)]) is False
    db.close()


def test_old_schema_db_is_refused(tmp_path):
    path = str(tmp_path / 'orders.sqlite3')
    OrderDb(path).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match='지우고 다시 시작'):
        OrderDb(path)
    assert order_db.SCHEMA_VERSION == 2


def test_signature_checker():
    key = b'secret'
    fields = ('ORD-00001', 'PAID', 'phone-1')
    checker = flow.SignatureChecker(key)
    sig = flow.gateway_signature(key, list(fields) + ['n1'])
    assert checker.check(fields, 'n1', sig)
    assert not checker.check(fields, 'n1', sig)  # nonce 재사용
    assert not checker.check(fields, 'n2', sig)  # 다른 nonce 는 다른 서명
    assert not checker.check(fields, '', '')
    assert flow.SignatureChecker(b'').check(fields, '', '')


def test_parse_inventory():
    layout = _layout()
    assert flow.parse_inventory([' S : 2 : 3 : 4 '], layout) == [('S', 2, 3, 4)]
    for bad in (['S:1:1'], ['S:A:1:1'], [':1:1:1']):
        with pytest.raises(ValueError):
            flow.parse_inventory(bad, layout)
    with pytest.raises(ValueError, match='선반에 없는 칸'):
        flow.parse_inventory(['S:4:1:1'], layout)
    with pytest.raises(ValueError, match='선반에 없는 칸'):
        flow.parse_inventory(['S:1:4:1'], layout)
    with pytest.raises(ValueError, match='SKU 가 둘'):
        flow.parse_inventory(['S:1:1:1', 'T:1:1:1'], layout)
    assert flow.slot_label(2, 3) == 'R2C3'


def test_store_layout_file():
    layout = load_store_layout(str(LAYOUT_FILE))
    assert layout.rows == 3
    assert sorted(layout.columns) == [1, 2, 3]
    assert layout.has_slot(3, 3) and not layout.has_slot(4, 1) and not layout.has_slot(1, 4)
    assert layout.location_waypoints()['BENCH_1'] == 'WP_BENCH_DELIVERY'


@pytest.mark.parametrize('data', [
    {'shelf': {'rows': 0, 'columns': {1: 'WP_A'}}},
    {'shelf': {'rows': 3, 'columns': {}}},
    {'shelf': {'rows': 3, 'columns': {'one': 'WP_A'}}},
    {'shelf': {'rows': 3, 'columns': {1: ''}}},
    {'shelf': {'rows': 3, 'columns': {1: 'WP_A'}}, 'locations': {'B 1': {'waypoint': 'W'}}},
    {'shelf': {'rows': 3, 'columns': {1: 'WP_A'}}, 'locations': {'B1': {'name': 'x'}}},
])
def test_store_layout_validation(data):
    with pytest.raises(ValueError):
        parse_store_layout(data)
