"""고객 주문 화면용 확장: 선반 칸으로 경로를 고르고 구매 취소를 기록한다."""

import json
from pathlib import Path
import sqlite3

from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.scenario import ScenarioService
from cobot_fleet_control.scenario_repository import ScenarioRepository
from cobot_fleet_control.service import FleetService

import pytest

from test_scenario import Environment, ROUTES

import yaml


SHELF = {'rows': 3, 'columns': {1: dict(pickup='ZA', pickup_arm='omx1'),
                                2: dict(pickup='ZB', pickup_arm='omx1')}}
DESTINATIONS = {'BENCH_1': dict(name='고객 벤치 1', dropoff='ZC', dropoff_arm='omx2',
                                lane='main')}


class ShelfEnvironment(Environment):
    """선반·자리 설정을 켠 관제. 회수 허용 여부는 시험마다 고른다."""

    allow_returns = True

    def open(self):
        self.repo = SqliteRepository(self.path)
        self.fleet = FleetService(self.repo, self.gateway, ['pinky1', 'pinky2'], lambda: self.now)
        self.scenario = ScenarioService(
            self.repo, self.fleet, self.gateway, ROUTES, clock=lambda: self.now,
            allow_returns=self.allow_returns, shelf=SHELF, destinations=DESTINATIONS)
        self.api = ControlAPI(self.scenario, self.fleet, self.gateway)
        self.healthy()

    def order(self, order_id='order1', **changes):
        data = dict(order_id=order_id, sku='SHOE42', destination='BENCH_1')
        data.update(changes)
        return self.scenario.submit(data)

    def request(self, **request):
        return self.api.handle(dict(request, request_id='r1'))

    def events(self):
        return [json.loads(row['payload']) for row in self.repo.pending(1000)]


@pytest.fixture
def env(tmp_path):
    e = ShelfEnvironment(tmp_path / 'fleet.sqlite3')
    e.scenario.store.set_stock('SHOE42', 10, 2, 2)
    yield e
    e.repo.close()


def test_destination_order_uses_shelf_column_zone_and_tells_arm_the_slot(env):
    order = env.order()
    assert (order['route'], order['shelf_row'], order['shelf_col']) == ('col2__BENCH_1', 2, 2)
    assert env.stock('SHOE42') == 9
    env.until('CUSTOMER')
    assert [p['command'] for _, p in env.gateway.sent][:3] == ['zone:ZB', 'leave', 'zone:ZC']
    pick = next(w for w in env.gateway.work_sent if w['stage'] == 'PICK')
    assert (pick['target'], pick['shelf_row'], pick['shelf_col']) == ('omx1', 2, 2)
    unload = next(w for w in env.gateway.work_sent if w['stage'] == 'UNLOAD')
    assert unload['target'] == 'omx2'


def test_route_orders_are_unchanged_and_carry_no_slot(env):
    order = env.scenario.submit(dict(order_id='plain', sku='SHOE42', route='lab'))
    assert 'shelf_row' not in order and 'request' not in order
    env.tick()
    env.tick()
    assert all('shelf_row' not in w for w in env.gateway.work_sent)


def test_same_destination_request_is_idempotent_even_after_slot_moves(env):
    first = env.order()
    env.scenario.store.set_stock('SHOE42', 9, 1, 1)
    again = env.order()
    assert again['route'] == first['route'] == 'col2__BENCH_1'
    assert env.stock('SHOE42') == 9
    with pytest.raises(ValueError, match='같은 order_id에 다른 주문'):
        env.order(quantity=2)


@pytest.mark.parametrize('stock,changes,message', [
    (('SHOE42', 10, 2, 3), {}, '3열의 상차 구역 미등록'),
    (('NOSLOT', 5), {'sku': 'NOSLOT'}, '선반 칸 미등록'),
    (('SHOE42', 10), {'destination': 'NOWHERE'}, '등록되지 않은 고객 자리'),
    (('SHOE42', 10), {'route': 'lab'}, '함께 쓸 수 없습니다'),
    (('SHOE42', 10), {'destination': 'bad id'}, 'destination'),
])
def test_unroutable_destination_orders_are_rejected_before_reserving_stock(
        env, stock, changes, message):
    env.scenario.store.set_stock(*stock)
    before = env.stock(changes.get('sku', 'SHOE42'))
    with pytest.raises(ValueError, match=message):
        env.order(**changes)
    assert env.stock(changes.get('sku', 'SHOE42')) == before
    assert env.scenario.store.orders() == []


def test_declined_records_returns_home_and_collects_with_return_order(env):
    env.order()
    env.until('CUSTOMER')
    reply = env.request(type='declined', order_id='order1')
    assert reply['status'] == 200 and reply['body']['customer_declined'] is True
    assert env.current()['stage'] == 'LEAVE_DROPOFF'
    assert not env.current()['customer_received']
    for _ in range(15):
        env.step()
    assert env.current()['state'] == 'COMPLETED'
    assert any(e.get('code') == 'CUSTOMER_DECLINED' for e in env.events())
    # 자리에 남은 상품은 기존 회수 주문이 되가져와야 재고가 돌아온다.
    assert env.stock('SHOE42') == 9
    collect = env.current('order1-return')
    assert (collect['kind'], collect['route'], collect['state']) == (
        'return', 'col2__BENCH_1', 'WAITING')


def test_declined_without_returns_leaves_alarm_for_operator(tmp_path):
    ShelfEnvironment.allow_returns = False
    try:
        env = ShelfEnvironment(tmp_path / 'fleet.sqlite3')
    finally:
        ShelfEnvironment.allow_returns = True
    env.scenario.store.set_stock('SHOE42', 10, 1, 1)
    env.order()
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    for _ in range(15):
        env.step()
    assert env.current()['state'] == 'COMPLETED'
    assert env.current('order1-return') is None
    assert any(e.get('code') == 'DECLINED_ITEM_LEFT' for e in env.events())
    assert env.stock('SHOE42') == 9
    env.repo.close()


def test_declined_only_while_waiting_for_customer(env):
    env.order()
    env.tick()
    reply = env.request(type='declined', order_id='order1')
    assert reply['status'] == 400
    assert env.request(type='declined', order_id='missing')['status'] == 400
    env.until('CUSTOMER')
    env.scenario.received('order1')
    assert env.request(type='declined', order_id='order1')['status'] == 400
    assert not env.current().get('customer_declined')


def test_inventory_request_sets_slot_and_snapshot_lists_stock_and_destinations(env):
    reply = env.request(type='inventory', sku='BOOT', available=2, shelf_row=1, shelf_col=1)
    assert reply == dict(type='reply', request_id='r1', status=200,
                         body=dict(sku='BOOT', available=2, shelf_row=1, shelf_col=1))
    # 칸을 생략한 수량 변경은 기존 칸을 유지한다.
    assert env.request(type='inventory', sku='BOOT', available=5)['body'] == dict(
        sku='BOOT', available=5)
    snapshot = env.api.snapshot()
    assert snapshot['stock'] == [
        dict(sku='BOOT', available=5, shelf_row=1, shelf_col=1),
        dict(sku='SHOE42', available=10, shelf_row=2, shelf_col=2)]
    assert snapshot['destinations'] == {'BENCH_1': {'name': '고객 벤치 1'}}


@pytest.mark.parametrize('slot', [
    dict(shelf_row=1), dict(shelf_col=1), dict(shelf_row=0, shelf_col=1),
    dict(shelf_row=4, shelf_col=1), dict(shelf_row=True, shelf_col=1),
    dict(shelf_row=2, shelf_col=2),
])
def test_bad_or_occupied_slot_is_rejected_without_changing_stock(env, slot):
    reply = env.request(type='inventory', sku='BOOT', available=2, **slot)
    assert reply['status'] == 400
    assert env.stock('BOOT') == 0


def test_existing_ledger_gains_slot_columns_without_losing_stock(tmp_path):
    path = str(tmp_path / 'old.sqlite3')
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE scenario_stock (sku TEXT PRIMARY KEY, '
               'available INTEGER NOT NULL CHECK(available >= 0))')
    db.execute("INSERT INTO scenario_stock VALUES ('SHOE42', 7)")
    db.commit()
    db.close()
    repo = SqliteRepository(path)
    store = ScenarioRepository(repo)
    assert store.stock() == [dict(sku='SHOE42', available=7, shelf_row=None, shelf_col=None)]
    assert store.location('SHOE42') is None
    store.set_stock('SHOE42', 7, 1, 2)
    assert store.location('SHOE42') == (1, 2)
    repo.close()


@pytest.mark.parametrize('shelf,destinations', [
    ({'rows': 0, 'columns': {}}, {}),
    ({'rows': 3, 'columns': {'one': dict(pickup='ZA', pickup_arm='omx1')}}, {}),
    ({'rows': 3, 'columns': {1: dict(pickup='ZA')}}, {}),
    (SHELF, {'BENCH_1': dict(dropoff='ZC', dropoff_arm='omx2')}),
    (SHELF, {'BENCH_1': dict(dropoff='ZA', dropoff_arm='omx2', lane='main')}),
    (SHELF, {'BENCH_1': dict(dropoff='ZC', dropoff_arm='omx1', lane='main')}),
])
def test_invalid_shelf_or_destination_config_is_refused(tmp_path, shelf, destinations):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    fleet = FleetService(repo, None, ['pinky1'])
    with pytest.raises(ValueError):
        ScenarioService(repo, fleet, None, ROUTES, shelf=shelf, destinations=destinations)
    repo.close()


def test_packaged_scenario_config_builds_shelf_routes(tmp_path):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / 'config/scenario.yaml').read_text('utf-8'))
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    scenario = ScenarioService(repo, FleetService(repo, None, ['pinky1']), None, **config)
    assert scenario.routes['col1__BENCH_1'] == dict(
        pickup='ZA', pickup_arm='omx1', dropoff='ZC', dropoff_arm='omx2', lane='main')
    assert scenario.routes['col2__BENCH_1']['pickup'] == 'ZB'
    assert 'col3__BENCH_1' not in scenario.routes
    assert scenario.routes['lab_delivery']['pickup'] == 'ZA'
    repo.close()
