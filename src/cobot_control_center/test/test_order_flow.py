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

from cobot_control_center import order_flow as flow
from cobot_control_center.order_db import OrderDb
import pytest

STEP = 3.0


@pytest.fixture
def service():
    db = OrderDb(':memory:')
    db.seed_inventory([('SHOE_A', 'RACK_A', 2), ('SHOE_B', 'RACK_B', 0)])
    config = flow.OrderFlowConfig(
        locations={'BENCH_1': 'WP_BENCH_DELIVERY'}, robot_ids=['pinky_1', 'pinky_2'],
        step_sec=STEP, warehouse_waypoint='WP_LOAD_1', repack_waypoint='WP_UNLOAD',
        home_waypoint='WP_HOME_1')
    yield flow.OrderService(db, config), db
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
        'sku': 'SHOE_A', 'location_id': 'RACK_A', 'qty_on_hand': 1, 'qty_reserved': 0}
    _run_until(svc, 'ORD-00001', now, flow.STAGE_COMPLETED)
    assert svc.get_order('ORD-00001')['next_step_at'] is None


def test_cancel_repacks_and_returns_to_warehouse(service):
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


def test_bad_role_is_rejected(service):
    svc, _ = service
    assert svc.submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1', 'robot')['reject_code'] == (
        'ROLE_FORBIDDEN')


def test_orders_survive_reopen(tmp_path):
    path = str(tmp_path / 'orders.sqlite3')
    db = OrderDb(path)
    db.seed_inventory([('SHOE_A', 'RACK_A', 1)])
    config = flow.OrderFlowConfig({'BENCH_1': 'WP_X'}, ['pinky_1'], STEP, 'A', 'B', 'C')
    flow.OrderService(db, config).submit(0.0, 'k1', 'SHOE_A', 1, 'BENCH_1')
    db.close()
    db = OrderDb(path)
    assert db.get_order('ORD-00001')['sku'] == 'SHOE_A'
    assert db.seed_inventory([('SHOE_A', 'RACK_A', 9)]) is False
    db.close()


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


def test_parse_helpers():
    assert flow.parse_pairs(['BENCH_1=WP_A', ' T2 = WP_B ']) == {'BENCH_1': 'WP_A', 'T2': 'WP_B'}
    assert flow.parse_inventory(['S:R:3']) == [('S', 'R', 3)]
    with pytest.raises(ValueError):
        flow.parse_pairs(['oops'])
    with pytest.raises(ValueError):
        flow.parse_inventory(['S:R'])
