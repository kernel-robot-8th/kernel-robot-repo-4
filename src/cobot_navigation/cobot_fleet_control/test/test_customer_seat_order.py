"""고객 자리(지점) 주문: ZB 상차 → 고객 자리 → 결제·시간 초과면 복귀, 회수면 ZC 정리 → ZA 반환."""

import json

from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.scenario import ScenarioService
from cobot_fleet_control.scenario_contracts import NAVIGATION
from cobot_fleet_control.service import FleetService

import pytest

from test_scenario import Environment, ROUTES


SHELF = {'rows': 4, 'columns': {1: dict(pickup='ZB', pickup_arm='omx2'),
                                2: dict(pickup='ZB', pickup_arm='omx2')}}
RETURN = dict(arrange='ZC', arrange_arm='omx3', restock='ZA', restock_arm='omx1')
DESTINATIONS = {'P22': dict(name='P22 자리', point='P22', lane='main')}
TIMEOUT = 300.0
DEVICE_OK = dict(xy_m=0.005, yaw_deg=1.0, stopped=True, base_hold=True, sku='SHOE42',
                 arm_safe=True, load_present=True, load_absent=True, placed=True, clear=True)


class SeatEnvironment(Environment):
    """고객 자리 설정을 켠 관제. 고객 결정은 시험이 직접 넣는다 (자동 수령 없음)."""

    def open(self):
        self.repo = SqliteRepository(self.path)
        self.fleet = FleetService(self.repo, self.gateway, ['pinky1', 'pinky2'], lambda: self.now)
        self.scenario = ScenarioService(
            self.repo, self.fleet, self.gateway, ROUTES, clock=lambda: self.now,
            customer_timeout_sec=TIMEOUT, shelf=SHELF, destinations=DESTINATIONS,
            customer_return=RETURN)
        self.api = ControlAPI(self.scenario, self.fleet, self.gateway)
        self.healthy()

    def order(self, order_id='order1', **changes):
        data = dict(order_id=order_id, sku='SHOE42', destination='P22')
        data.update(changes)
        return self.scenario.submit(data)

    def step(self):
        """이동은 끝남, 장치는 성공으로 답한다. CUSTOMER 단계에서는 아무것도 하지 않는다."""
        self.tick()
        order = self.current()
        if order['state'] != 'RUNNING' or order['stage'] == 'CUSTOMER':
            return
        if order['stage'] in NAVIGATION:
            self.fleet.tick()
            self.fleet.on_status(order['robot_id'], dict(
                command_id=order['request_id'], state='DONE', task_finished=True))
            self.fleet.tick()
            self.scenario.tick()
        else:
            self.result(dict(DEVICE_OK))

    def finish(self):
        for _ in range(80):
            if self.current()['state'] != 'RUNNING':
                return self.current()
            self.step()
        pytest.fail('order did not finish: ' + self.current()['stage'])

    def commands(self):
        return [p['command'] for _, p in self.gateway.sent]

    def works(self):
        return [(w['stage'], w['target'], w['action']) for w in self.gateway.work_sent
                if w.get('stage') != 'SAFETY']

    def alarms(self):
        events = [json.loads(row['payload']) for row in self.repo.pending(1000)]
        return [e['code'] for e in events if e.get('type') == 'alarm']


@pytest.fixture
def env(tmp_path):
    e = SeatEnvironment(tmp_path / 'fleet.sqlite3')
    e.scenario.store.set_stock('SHOE42', 10, 3, 1)
    yield e
    e.repo.close()


def test_seat_order_loads_at_zb_and_drives_to_the_seat_point(env):
    order = env.order()
    assert order['route'] == 'col1__P22' and order['shelf_row'] == 3
    env.until('CUSTOMER')
    assert env.commands() == ['zone:ZB', 'leave', 'goto:P22']
    picks = [w for w in env.gateway.work_sent if w['stage'] == 'PICK']
    assert picks[0]['target'] == 'omx2' and picks[0]['shelf_row'] == 3
    # 고객 자리에는 하차 팔 단계가 없다.
    assert not {'PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD'} & {s for s, _, _ in env.works()}
    # 회수할지 모르므로 상차장만 잡고 정리·반환 구역은 잡지 않는다.
    assert not {'station_ZC', 'station_ZA'} & set(env.scenario.store.resources('order1'))


def test_paid_seat_order_returns_home_and_keeps_the_sale(env):
    env.order()
    env.until('CUSTOMER')
    reply = env.api.handle(dict(type='received', order_id='order1', request_id='r1'))
    assert reply['status'] == 200
    order = env.finish()
    assert order['state'] == 'COMPLETED' and order['customer_received']
    assert env.commands()[3:] == ['home']
    assert 'ARRANGE' not in {s for s, _, _ in env.works()}
    assert env.stock('SHOE42') == 9
    assert env.scenario.store.resources('order1') == []


def test_declined_seat_order_arranges_at_zc_restocks_at_za_then_goes_home(env):
    env.order()
    env.until('CUSTOMER')
    reply = env.api.handle(dict(type='declined', order_id='order1', request_id='r1'))
    assert reply['status'] == 200 and reply['body']['customer_declined'] is True
    order = env.finish()
    assert order['state'] == 'COMPLETED'
    assert env.commands()[3:] == ['zone:ZC', 'leave', 'zone:ZA', 'leave', 'home']
    assert ('ARRANGE', 'omx3', 'arrange_shoe') in env.works()
    assert ('RESTOCK', 'omx1', 'warehouse_store') in env.works()
    assert {'ARRANGE', 'RESTOCK', 'RETURN_HOME'} <= set(order['completed'])
    assert 'CUSTOMER_DECLINED' in env.alarms()
    # 선반에 다시 올린 뒤에만 재고가 돌아온다. 따로 회수 주문을 만들지 않는다.
    assert env.stock('SHOE42') == 10
    assert env.current('order1-return') is None
    assert env.scenario.store.resources('order1') == []


def test_seat_timeout_goes_home_with_the_shoe_after_five_minutes(env):
    env.order()
    env.until('CUSTOMER')
    env.now += TIMEOUT - 1
    env.tick()
    assert env.current()['stage'] == 'CUSTOMER'
    env.now += 1
    order = env.finish()
    assert order['state'] == 'COMPLETED' and order['customer_timed_out']
    assert not order['customer_received'] and not order.get('customer_declined')
    assert env.commands()[3:] == ['home']
    assert 'CUSTOMER_TIMEOUT' in env.alarms()
    assert env.stock('SHOE42') == 9  # 신발은 핑키 위에 있다: 운영자가 재고를 맞춘다


def test_unsafe_arrange_failure_holds_order_instead_of_going_home(env):
    env.order()
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    for _ in range(20):
        if env.current()['stage'] == 'ARRANGE' and env.current()['request_id']:
            break
        env.step()
    env.result(success=False, data={'arm_safe': False}, detail='hold')
    order = env.current()
    assert order['state'] == 'UNKNOWN'
    env.tick()
    assert 'home' not in env.commands()
    assert env.stock('SHOE42') == 9


def test_arrange_result_from_wrong_arm_is_ignored(env):
    env.order()
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    for _ in range(20):
        if env.current()['stage'] == 'ARRANGE' and env.current()['request_id']:
            break
        env.step()
    env.result(dict(DEVICE_OK), source='omx2')
    assert env.current()['stage'] == 'ARRANGE'
    assert 'ARRANGE' not in env.current()['completed']


@pytest.mark.parametrize('destinations,back,message', [
    (DESTINATIONS, None, 'customer_return'),
    (DESTINATIONS, dict(arrange='ZC', arrange_arm='omx3'), 'customer_return'),
    ({'P22': dict(point='P22')}, RETURN, 'point, lane'),
    (DESTINATIONS, dict(RETURN, restock='ZB'), '서로 달라야'),
    (DESTINATIONS, dict(RETURN, restock_arm='omx2'), '서로 다른'),
])
def test_bad_seat_config_is_refused(tmp_path, destinations, back, message):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    fleet = FleetService(repo, None, ['pinky1'])
    with pytest.raises(ValueError, match=message):
        ScenarioService(repo, fleet, None, ROUTES, shelf=SHELF, destinations=destinations,
                        customer_return=back)
    repo.close()


def test_seat_route_cannot_be_used_for_a_separate_return_order(env):
    env.scenario.allow_returns = True
    with pytest.raises(ValueError, match='회수 주문 불가'):
        env.scenario.submit(dict(order_id='back', sku='SHOE42', route='col1__P22',
                                 kind='return'))
