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


def time_out(env):
    env.order()
    env.until('CUSTOMER')
    env.now += TIMEOUT
    return env.finish()


def test_timed_out_robot_is_held_and_next_order_goes_to_another_robot(env):
    order = time_out(env)
    assert order['state'] == 'COMPLETED' and order['robot_id'] == 'pinky1'
    assert env.scenario.store.holds() == {'pinky1': 'CARGO_ONBOARD'}
    assert 'CARGO_ONBOARD' in env.alarms()
    env.order('order2')
    env.now += 10
    env.tick()
    assert env.current('order2')['robot_id'] == 'pinky2'


def test_next_order_waits_until_cargo_hold_is_released(env):
    time_out(env)
    env.scenario.store.hold('pinky2', 'STOP')  # 남은 로봇이 없을 때
    env.order('order2')
    env.now += 10
    env.tick()
    assert env.current('order2')['state'] == 'WAITING'
    assert env.api.handle({'type': 'release_control', 'robot_id': 'pinky1'})['status'] == 202
    env.tick()
    assert 'pinky1' in env.scenario.store.holds()  # 로봇 응답 전에는 풀리지 않는다
    env.scenario.telemetry('pinky1', {
        'state': 'IDLE', 'central_controlled': True, 'busy': False, 'central_latched': False,
        'control_reset_id': 'reset-1'}, 80.0)
    assert 'pinky1' not in env.scenario.store.holds()
    env.tick()
    assert env.current('order2')['robot_id'] == 'pinky1'


def test_cargo_hold_survives_restart(env):
    time_out(env)
    env.repo.close()
    env.open()
    assert env.scenario.store.holds() == {'pinky1': 'CARGO_ONBOARD'}


@pytest.mark.parametrize('decision', ['received', 'declined'])
def test_decided_order_does_not_hold_robot(env, decision):
    env.order()
    env.until('CUSTOMER')
    env.api.handle({'type': decision, 'order_id': 'order1', 'request_id': 'r1'})
    assert env.finish()['state'] == 'COMPLETED'
    assert env.scenario.store.holds() == {}


def cancel(env, order_id='order1', **changes):
    return env.api.handle({'type': 'resolve', 'order_id': order_id, 'decision': 'fail',
                           'operator': 'kim', 'source': '10.0.0.5', **changes})


def test_cancel_waiting_order_returns_stock_and_never_departs(env):
    env.scenario.armed = False
    env.order(quantity=2)
    assert env.stock('SHOE42') == 8
    assert cancel(env)['status'] == 200
    order = env.current()
    assert order['state'] == 'FAILED' and order['operator_cancelled'] is True
    assert env.stock('SHOE42') == 10
    assert env.scenario.store.resources('order1') == [] and env.scenario.store.holds() == {}
    events = [json.loads(row['payload']) for row in env.repo.pending(1000)]
    recovery = next(e for e in events if e.get('type') == 'recovery')
    assert recovery['operator'] == 'kim' and recovery['source'] == '10.0.0.5'
    # 두 번 취소해도 재고는 한 번만, 다시 켜거나 가동해도 출발하지 않는다.
    assert cancel(env)['status'] == 400 and env.stock('SHOE42') == 10
    env.repo.close()
    env.open()
    env.scenario.armed = True
    for _ in range(3):
        env.now += 10
        env.tick()
    assert env.current()['state'] == 'FAILED' and env.current()['robot_id'] is None
    assert env.commands() == [] and env.works() == []


def test_cancel_records_korean_operator_name(env):
    env.scenario.armed = False
    env.order()
    assert cancel(env, operator='  김 지혜 ')['status'] == 200
    events = [json.loads(row['payload']) for row in env.repo.pending(1000)]
    assert next(e for e in events if e.get('type') == 'recovery')['operator'] == '김 지혜'
    assert cancel(env, '주문')['status'] == 400  # 주문 ID 는 그대로 영문 식별자만


def test_cancel_waiting_order_works_while_robots_are_offline(env):
    env.now += 60  # 로봇 상태가 모두 오래됨
    env.order()
    env.scenario.tick()
    assert env.current()['state'] == 'WAITING'
    assert cancel(env)['status'] == 200 and env.stock('SHOE42') == 10


def test_cancel_one_waiting_order_keeps_the_next_one(env):
    env.scenario.armed = False
    env.order()
    env.order('order2')
    assert cancel(env)['status'] == 200
    env.scenario.armed = True
    env.tick()
    assert env.current('order2')['robot_id'] == 'pinky1'
    assert env.stock('SHOE42') == 9


def test_cancel_after_restart_is_marked_as_cancelled(env):
    env.scenario.armed = False
    env.order()
    env.repo.close()
    env.open()
    assert env.current()['state'] == 'UNKNOWN'
    assert cancel(env)['status'] == 200
    assert env.current()['operator_cancelled'] is True and env.stock('SHOE42') == 10


def test_waiting_order_accepts_only_cancel_and_assigned_order_is_refused(env):
    env.scenario.armed = False
    env.order()
    for decision in ('resume', 'done'):
        assert cancel(env, decision=decision)['status'] == 400
    assert env.current()['state'] == 'WAITING' and env.stock('SHOE42') == 9
    env.scenario.armed = True
    env.tick()
    assert env.current()['state'] == 'RUNNING'
    assert cancel(env)['status'] == 400
    assert env.current()['state'] == 'RUNNING' and env.stock('SHOE42') == 9
    assert cancel(env, 'nothing')['status'] == 400


CANCEL_OK = {'arms_safe': True, 'cargo_reconciled': True, 'resources_clear': True}


def stop_robot(env, robot='pinky1'):
    return env.api.handle({'type': 'stop', 'robot_id': robot})


def stopped_status(env, **changes):
    status = {'state': 'STOPPED', 'busy': False, 'central_controlled': True,
              'central_latched': True, 'boot_id': 'boot1', **changes}
    env.scenario.telemetry('pinky1', status, 80.0)


@pytest.mark.parametrize('stage', ['MOVE_PICKUP', 'PICK', 'MOVE_CUSTOMER', 'CUSTOMER'])
def test_stop_then_cancel_running_order_needs_site_check(env, stage):
    env.order()
    env.until(stage)
    assert stop_robot(env)['status'] == 202
    order = env.current()
    assert order['state'] == 'ESTOP' and order['stage'] == stage
    assert env.scenario.store.holds() == {'pinky1': 'ESTOP'}
    stopped_status(env, busy=True)
    assert cancel(env, evidence=CANCEL_OK)['status'] == 400  # 아직 안 멈춤
    stopped_status(env)
    if env.scenario.store.resources('order1'):
        assert cancel(env)['status'] == 400  # 현장 확인 없음
    assert env.current()['state'] == 'ESTOP'
    assert cancel(env, evidence=CANCEL_OK)['status'] == 200
    assert env.current()['state'] == 'FAILED' and not env.current().get('operator_cancelled')
    assert env.scenario.store.resources('order1') == [] and env.stock('SHOE42') == 9
    assert 'pinky1' in env.scenario.store.holds()
    stopped_status(env, central_latched=False, control_reset_id='reset-1')
    assert env.scenario.store.holds() == {}


def test_stopped_order_is_not_cancelled_while_status_is_stale(env):
    env.order()
    env.until('MOVE_CUSTOMER')
    stop_robot(env)
    stopped_status(env)
    env.now += 60
    assert cancel(env, evidence=CANCEL_OK)['status'] == 400
    assert env.current()['state'] == 'ESTOP'


def test_stop_one_robot_keeps_the_other_order_and_ignores_late_arm_result(env):
    env.order()
    env.until('PICK')
    late = env.current()
    work = next(w for w in env.gateway.work_sent if w['request_id'] == late['request_id'])
    env.order('order2')
    env.now += 10
    env.tick()
    assert env.current('order2')['robot_id'] == 'pinky2'
    stop_robot(env)
    assert not env.scenario.result({
        'request_id': work['request_id'], 'order_id': 'order1', 'robot_id': 'pinky1',
        'stage': 'PICK', 'source': work['target'], 'success': True, 'measured': True,
        'finished': True, 'data': dict(DEVICE_OK)})
    env.tick()
    assert env.current()['state'] == 'ESTOP'
    assert env.current('order2')['state'] == 'RUNNING' and env.scenario.armed is True
    assert 'pinky2' not in env.scenario.store.holds()


def request_cancel(env, order_id='order1', **changes):
    return env.api.handle({'type': 'cancel', 'order_id': order_id, 'operator': '김지혜',
                           'source': '10.0.0.5', **changes})


def sent_out(env):
    """트리를 돌려 지금 단계의 명령까지 보낸다."""
    env.tick()
    assert env.current()['request_id'], env.current()['stage']


def arm_works(env):
    return [s for s, _, _ in env.works() if s in ('PICK', 'LOAD', 'ARRANGE', 'RESTOCK')]


RETURN_COMMANDS = ['zone:ZC', 'leave', 'zone:ZA', 'leave', 'home']
SHELF_COMMANDS = ['zone:ZA', 'leave', 'home']  # 열지 않은 상자: 정리(ZC)를 건너뛴다


@pytest.mark.parametrize('stage', ['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER'])
def test_cancel_before_pick_finishes_the_step_then_goes_home_with_stock(env, stage):
    env.order(quantity=2)
    env.until(stage)
    sent_out(env)
    before = env.current()['request_id']
    reply = request_cancel(env)
    assert reply['status'] == 202 and reply['body']['cancel_requested']['stage'] == stage
    env.tick()
    assert env.current()['request_id'] == before and env.stock('SHOE42') == 8  # 하던 것을 마친다
    order = env.finish()
    assert order['state'] == 'FAILED' and order['operator_cancelled'] is True
    assert env.commands() == ['zone:ZB', 'home'] and arm_works(env) == []
    assert env.stock('SHOE42') == 10
    assert env.scenario.store.resources('order1') == [] and env.scenario.store.holds() == {}


def test_cancel_before_any_command_never_visits_the_pickup_zone(env):
    env.order()
    env.scenario.store.acquire('other', ['station_ZB'])  # 상차장이 차서 출발하지 못함
    env.tick()
    assert env.current()['state'] == 'RUNNING' and env.current()['request_id'] is None
    assert request_cancel(env)['status'] == 202
    assert env.finish()['state'] == 'FAILED'
    assert env.commands() == ['home'] and env.stock('SHOE42') == 10
    assert env.scenario.store.resources('other') == ['station_ZB']


def test_cancel_during_dock_correction_goes_home(env):
    env.order()
    env.until('DOCK_PICKUP')
    env.result({**DEVICE_OK, 'xy_m': 0.5})
    env.tick()
    assert env.current()['stage'] == 'CORRECT_PICKUP'
    assert request_cancel(env)['status'] == 202
    order = env.finish()
    assert order['state'] == 'FAILED' and order['operator_cancelled'] is True
    assert env.commands() == ['zone:ZB', 'home'] and env.stock('SHOE42') == 10


@pytest.mark.parametrize('stage', ['PICK', 'LOAD', 'VERIFY_LOAD', 'LEAVE_PICKUP'])
def test_cancel_after_pick_started_skips_the_seat_and_restocks(env, stage):
    env.order(quantity=2)
    env.until(stage)
    sent_out(env)
    assert request_cancel(env)['status'] == 202
    order = env.finish()
    assert order['state'] == 'COMPLETED' and order['customer_declined'] is True
    assert env.commands() == ['zone:ZB', 'leave'] + SHELF_COMMANDS
    assert arm_works(env) == ['PICK', 'LOAD', 'RESTOCK']
    assert not {'MOVE_CUSTOMER', 'CUSTOMER'} & set(order['completed'])
    assert 'ORDER_CANCELLED' in env.alarms() and not order.get('operator_cancelled')
    assert env.stock('SHOE42') == 10 and env.scenario.store.resources('order1') == []
    assert env.scenario.store.holds() == {}


def test_cancel_while_driving_to_the_seat_returns_without_waiting(env):
    env.order()
    env.until('MOVE_CUSTOMER')
    sent_out(env)
    assert request_cancel(env)['status'] == 202
    env.tick()
    assert env.commands() == ['zone:ZB', 'leave', 'goto:P22']
    order = env.finish()
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert env.commands()[3:] == SHELF_COMMANDS


def test_cancel_at_the_seat_needs_the_shoe_on_the_robot(env):
    env.order()
    env.until('CUSTOMER')
    for evidence in (None, {}, {'shoe_on_robot': False}, {'shoe_on_robot': 'yes'}, 'yes'):
        assert request_cancel(env, evidence=evidence)['status'] == 400
    assert not env.current().get('cancel_requested')
    assert request_cancel(env, evidence={'shoe_on_robot': True})['status'] == 202
    for kind in ('received', 'declined'):  # 취소가 먼저면 고객 입력은 거절
        reply = env.api.handle({'type': kind, 'order_id': 'order1', 'request_id': kind})
        assert reply['status'] == 400
    order = env.finish()
    assert order['state'] == 'COMPLETED' and not order['customer_received']
    assert env.commands()[3:] == RETURN_COMMANDS and env.stock('SHOE42') == 10


def test_cancel_at_the_seat_beats_later_payment_while_disarmed(env):
    env.order()
    env.until('CUSTOMER')
    env.scenario.armed = False
    sent = len(env.gateway.sent)
    assert request_cancel(env, evidence={'shoe_on_robot': True})['status'] == 202
    # 꺼져 있어도 취소는 바로 반영해 정리 구역 쪽으로 넘어가지만, 새 주행 명령은 보내지 않는다.
    assert env.current()['stage'] == 'MOVE_ARRANGE' and not env.current()['request_id']
    env.tick()
    assert len(env.gateway.sent) == sent
    assert env.api.handle({'type': 'received', 'order_id': 'order1'})['status'] == 400
    env.scenario.armed = True
    assert env.finish()['state'] == 'COMPLETED' and env.stock('SHOE42') == 10


@pytest.mark.parametrize('armed', [True, False])
def test_payment_first_refuses_cancel(env, armed):
    env.order()
    env.until('CUSTOMER')
    env.scenario.armed = armed
    assert env.api.handle({'type': 'received', 'order_id': 'order1'})['status'] == 200
    assert request_cancel(env, evidence={'shoe_on_robot': True})['status'] == 400
    env.scenario.armed = True
    order = env.finish()
    assert order['customer_received'] and env.stock('SHOE42') == 9
    assert request_cancel(env)['status'] == 400  # 이미 끝남


def test_cancel_is_refused_when_not_running_or_already_returning(env):
    assert request_cancel(env, 'nothing')['status'] == 400
    env.scenario.armed = False
    env.order()
    assert request_cancel(env)['status'] == 400  # 배정 전은 주문 복구의 취소
    env.scenario.armed = True
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    assert request_cancel(env)['status'] == 400
    stop_robot(env)
    assert request_cancel(env)['status'] == 400  # 멈춘 주문
    assert not env.current().get('cancel_requested')


def test_cancel_is_recorded_once(env):
    env.order()
    env.until('PICK')
    assert request_cancel(env)['status'] == 202
    assert request_cancel(env, operator='other')['status'] == 202
    assert env.current()['cancel_requested']['operator'] == '김지혜'
    events = [json.loads(row['payload']) for row in env.repo.pending(1000)]
    cancels = [e for e in events if e.get('type') == 'operator_cancel']
    assert len(cancels) == 1 and cancels[0]['request']['source'] == '10.0.0.5'


def test_cancel_keeps_the_other_order_running(env):
    env.order()
    env.until('PICK')
    env.order('order2')
    env.now += 10
    env.tick()
    assert request_cancel(env)['status'] == 202
    assert env.current('order2')['robot_id'] == 'pinky2'
    assert not env.current('order2').get('cancel_requested')
    env.finish()
    assert env.current('order2')['state'] == 'RUNNING' and env.stock('SHOE42') == 9


def test_failed_pick_after_cancel_is_held_and_not_restocked(env):
    env.order()
    env.until('PICK')
    sent_out(env)
    request_cancel(env)
    env.result(success=False, data={'arm_safe': False}, detail='모름')
    assert env.current()['state'] == 'UNKNOWN' and env.stock('SHOE42') == 9
    stopped_status(env, boot_id=None)
    env.scenario.recover('order1', None, None, 'resume', SITE_OK)
    echo_reset(env)
    order = env.finish()  # 다시 집어도 홈 길로 새지 않고 실은 뒤 반납한다
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert arm_works(env) == ['PICK', 'PICK', 'LOAD', 'RESTOCK']
    assert env.commands() == ['zone:ZB', 'leave'] + SHELF_COMMANDS


def test_safe_retry_of_pick_after_cancel_still_loads_then_restocks(env):
    env.order()
    env.until('PICK')
    sent_out(env)
    request_cancel(env)
    env.result(success=False, data={'retry_safe': True}, detail='다시')
    order = env.finish()
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert arm_works(env) == ['PICK', 'PICK', 'LOAD', 'RESTOCK']


def test_cancel_survives_restart_and_waits_for_operator_resume(env):
    env.order()
    env.until('MOVE_CUSTOMER')
    request_cancel(env)
    env.repo.close()
    env.open()
    env.scenario.armed = True
    commands = env.commands()
    env.tick()
    assert env.current()['state'] == 'UNKNOWN' and env.commands() == commands
    stopped_status(env, boot_id=None)
    env.scenario.recover('order1', None, None, 'resume', None)
    echo_reset(env)
    order = env.finish()
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert env.commands()[len(commands):] == SHELF_COMMANDS  # 고객 자리로 다시 가지 않는다


def test_cancel_before_pick_then_stop_and_resume_goes_home(env):
    env.order()
    env.until('MOVE_PICKUP')
    sent_out(env)
    request_cancel(env)
    stop_robot(env)
    stopped_status(env, boot_id=None)
    env.scenario.recover('order1', None, None, 'resume', None)
    echo_reset(env)
    order = env.finish()
    assert order['state'] == 'FAILED' and order['operator_cancelled'] is True
    assert env.commands()[-1] == 'home' and env.stock('SHOE42') == 10


def test_cancelled_before_pick_returns_stock_even_if_the_way_home_is_aborted(env):
    env.order()
    env.until('MARKER')
    sent_out(env)
    request_cancel(env)
    env.result(dict(DEVICE_OK))
    env.tick()
    assert env.current()['stage'] == 'RETURN_HOME'
    stop_robot(env)
    stopped_status(env)
    assert cancel(env, evidence=CANCEL_OK)['status'] == 200
    assert env.current()['state'] == 'FAILED' and env.stock('SHOE42') == 10


def test_manual_load_after_cancel_is_returned_to_the_shelf(env):
    stop_in_pickup(env)
    assert request_cancel(env)['status'] == 202
    assert confirm_loaded(env)['status'] == 200
    order = env.finish()
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert env.commands() == ['zone:ZB', 'leave'] + SHELF_COMMANDS


def test_cancel_while_manual_load_is_pending_never_goes_home_with_the_shoe(env):
    env.order()
    env.until('MARKER')
    env.scenario.interrupt('order1', 'UNKNOWN', '관제 재시작')
    stopped_status(env, state='IDLE', central_latched=False)
    assert confirm_loaded(env)['status'] == 200
    assert env.current()['manual_load_pending']
    assert request_cancel(env)['status'] == 202
    env.tick()
    assert env.current()['stage'] == 'MOVE_PICKUP' and not env.current()['failure']
    assert env.commands()[-1] == 'zone:ZB' and 'home' not in env.commands()
    assert env.stock('SHOE42') == 9


def test_confirmed_manual_load_then_cancel_is_returned_to_the_shelf(env):
    stop_in_pickup(env)
    assert confirm_loaded(env)['status'] == 200
    assert request_cancel(env)['status'] == 202
    assert env.finish()['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert env.commands() == ['zone:ZB', 'leave'] + SHELF_COMMANDS


def test_cancel_before_the_seat_never_touches_zc(env):
    env.order()
    env.scenario.store.acquire('other', ['station_ZC', 'arm_omx3'])  # ZC 가 막혀 있어도 간다
    env.until('LEAVE_PICKUP')
    request_cancel(env)
    order = env.finish()
    assert order['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert not {'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE'} & set(order['completed'])
    assert 'omx3' not in {target for _, target, _ in env.works()}
    assert set(env.scenario.store.resources('other')) == {'station_ZC', 'arm_omx3'}


def test_cancel_waits_for_a_busy_shelf_station(env):
    env.order()
    env.scenario.store.acquire('other', ['station_ZA'])
    env.until('LEAVE_PICKUP')
    request_cancel(env)
    for _ in range(4):
        env.step() if env.current()['stage'] == 'LEAVE_PICKUP' else env.tick()
    assert env.current()['stage'] == 'MOVE_RESTOCK' and env.current()['request_id'] is None
    assert env.commands() == ['zone:ZB', 'leave']
    env.scenario.store.release('other', ['station_ZA'])
    assert env.finish()['state'] == 'COMPLETED' and env.stock('SHOE42') == 10


def test_cancel_at_the_seat_still_arranges_the_opened_box(env):
    env.order()
    env.until('CUSTOMER')
    request_cancel(env, evidence={'shoe_on_robot': True})
    assert env.finish()['state'] == 'COMPLETED'
    assert arm_works(env) == ['PICK', 'LOAD', 'ARRANGE', 'RESTOCK']


@pytest.mark.parametrize('stage', ['MOVE_RESTOCK', 'RETURN_HOME'])
def test_stop_and_resume_on_the_way_back_skips_zc(env, stage):
    env.order()
    env.until('MOVE_CUSTOMER')
    request_cancel(env)
    env.until(stage)
    stop_robot(env)
    stopped_status(env, boot_id=None)
    env.scenario.recover('order1', None, None, 'resume', None)
    echo_reset(env)
    assert env.finish()['state'] == 'COMPLETED' and env.stock('SHOE42') == 10
    assert 'zone:ZC' not in env.commands()


def test_failed_restock_after_cancel_is_held_without_stock(env):
    env.order()
    env.until('PICK')
    sent_out(env)
    request_cancel(env)
    env.until('RESTOCK')
    sent_out(env)
    env.result(success=False, data={'arm_safe': False}, detail='모름')
    assert env.current()['state'] == 'UNKNOWN' and env.stock('SHOE42') == 9
    env.tick()
    assert 'home' not in env.commands()


SHELF_OK = {**CANCEL_OK, 'item_on_shelf': True}


@pytest.mark.parametrize('on_shelf', [True, False])
@pytest.mark.parametrize('stage', ['MOVE_PICKUP', 'PICK', 'MOVE_CUSTOMER', 'CUSTOMER'])
def test_hand_cancel_returns_stock_only_when_the_shoe_is_back_on_the_shelf(env, stage, on_shelf):
    env.order(quantity=2)
    env.until(stage)
    stop_robot(env)
    stopped_status(env)
    evidence = {**CANCEL_OK, 'item_on_shelf': on_shelf}
    assert cancel(env, evidence=evidence)['status'] == 200
    order = env.current()
    assert order['state'] == 'FAILED' and bool(order.get('operator_restocked')) is on_shelf
    stock = 10 if on_shelf else 8
    assert env.stock('SHOE42') == stock and not order.get('operator_cancelled')
    events = [json.loads(row['payload']) for row in env.repo.pending(1000)]
    recovery = next(e for e in events if e.get('type') == 'recovery')
    assert recovery['evidence'] == evidence and recovery['operator'] == 'kim'
    assert cancel(env, evidence=evidence)['status'] == 400  # 두 번 돌려놓지 않는다
    env.repo.close()
    env.open()
    assert env.stock('SHOE42') == stock


@pytest.mark.parametrize('stage', ['MOVE_ARRANGE', 'ARRANGE', 'RESTOCK', 'LEAVE_RESTOCK'])
def test_hand_cancel_during_return_can_restock_once(env, stage):
    env.order()
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    env.until(stage)
    stop_robot(env)
    stopped_status(env)
    assert cancel(env, evidence=SHELF_OK)['status'] == 200
    assert env.stock('SHOE42') == 10


def test_hand_cancel_after_timeout_can_restock(env):
    env.order()
    env.until('CUSTOMER')
    env.now += TIMEOUT
    env.tick()
    assert env.current()['customer_timed_out'] and env.current()['stage'] == 'RETURN_HOME'
    stop_robot(env)
    stopped_status(env)
    assert cancel(env, evidence=SHELF_OK)['status'] == 200 and env.stock('SHOE42') == 10


def test_hand_cancel_never_restocks_a_purchased_shoe(env):
    env.order()
    env.until('CUSTOMER')
    env.scenario.received('order1')
    env.until('RETURN_HOME')
    stop_robot(env)
    stopped_status(env)
    releases = len(env.gateway.releases)
    assert cancel(env, evidence=SHELF_OK)['status'] == 400
    assert env.current()['state'] == 'ESTOP' and len(env.gateway.releases) == releases
    assert cancel(env, evidence=CANCEL_OK)['status'] == 200 and env.stock('SHOE42') == 9


def test_hand_cancel_restock_needs_every_site_check(env):
    env.order()
    env.until('MOVE_CUSTOMER')
    stop_robot(env)
    stopped_status(env)
    for value in ('yes', 1, None, [True]):
        assert cancel(env, evidence={**CANCEL_OK, 'item_on_shelf': value})['status'] == 400
    for key in CANCEL_OK:
        assert cancel(env, evidence={**SHELF_OK, key: False})['status'] == 400
    env.scenario.store.release('order1', env.scenario.store.resources('order1'))
    assert cancel(env, evidence={'item_on_shelf': True})['status'] == 400  # 예약이 없어도 확인
    assert env.current()['state'] == 'ESTOP' and env.stock('SHOE42') == 9
    stopped_status(env, busy=True)
    assert cancel(env, evidence=SHELF_OK)['status'] == 400


def test_hand_cancel_replaces_a_requested_return(env):
    env.order()
    env.until('PICK')
    sent_out(env)
    request_cancel(env)
    stop_robot(env)
    stopped_status(env)
    assert cancel(env, evidence=SHELF_OK)['status'] == 200
    assert env.current()['operator_restocked'] is True and env.stock('SHOE42') == 10
    env.tick()
    assert 'zone:ZC' not in env.commands() and 'home' not in env.commands()


def test_shelf_check_does_not_double_the_automatic_stock_return(env):
    env.scenario.armed = False
    env.order()
    assert cancel(env, evidence=SHELF_OK)['status'] == 200  # 배정 전
    assert env.stock('SHOE42') == 10 and not env.current().get('operator_restocked')
    env.scenario.armed = True
    env.order('order2')
    env.tick()
    request_cancel(env, 'order2')
    for _ in range(3):  # 상차장 도착 → 집기 전 취소로 홈 복귀
        env.tick()
        order = env.current('order2')
        if order['stage'] == 'RETURN_HOME':
            break
        env.fleet.on_status(order['robot_id'], {
            'command_id': order['request_id'], 'state': 'DONE', 'task_finished': True})
    order = env.current('order2')
    assert order['operator_cancelled'] is True
    stop_robot(env, order['robot_id'])
    stopped_status(env)
    assert cancel(env, 'order2', evidence=SHELF_OK)['status'] == 200
    assert env.stock('SHOE42') == 10


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


SITE_OK = dict(arms_safe=True, item_ready=True)
HAND_OK = dict(arms_safe=True, item_placed=True)


def fail_arrange(env):
    """신발 정리에서 팔이 움직인 뒤 성공 판단이 안 나온 실패 (retry_safe 없음) → 현장 확인 보류."""
    env.order()
    env.until('CUSTOMER')
    env.scenario.declined('order1')
    for _ in range(20):
        if env.current()['stage'] == 'ARRANGE' and env.current()['request_id']:
            break
        env.step()
    failed = env.result(success=False, data={'arm_safe': True, 'end_reason': 'timeout'},
                        detail='성공 판단 안 나옴 (end_reason=timeout)')
    assert env.current()['state'] == 'UNKNOWN'
    return failed


def echo_reset(env):
    """로봇이 정지 해제를 반향했다고 알린다 (이어서 가기·다시·사람이 처리함 공통)."""
    env.scenario.telemetry('pinky1', dict(
        state='IDLE', busy=False, central_controlled=True, central_latched=False,
        control_reset_id=env.current()['reset_request_id']), 80.0)
    env.scenario.tick()


def arranges(env):
    return [w for w in env.works() if w[0] == 'ARRANGE']


def test_failed_arrange_needs_site_check_then_retries_the_same_arm_step(env):
    failed = fail_arrange(env)
    with pytest.raises(ValueError, match='물건 제자리'):
        env.scenario.recover('order1', None, None, 'resume', {'arms_safe': True})
    env.scenario.recover('order1', None, None, 'resume', SITE_OK)
    assert env.current()['state'] == 'RUNNING' and env.current()['stage'] == 'ARRANGE'
    # 정지 해제는 로봇과 경로 팔(release_hold) 모두에 보낸다.
    assert env.gateway.releases[-1][0] == 'pinky1'
    echo_reset(env)
    assert len(arranges(env)) == 2
    # 앞 시도의 늦은 결과는 새 시도의 결과로 받지 않는다.
    assert not env.scenario.result(dict(failed, success=True, data=dict(DEVICE_OK)))
    assert env.current()['stage'] == 'ARRANGE'
    order = env.finish()
    assert order['state'] == 'COMPLETED' and 'ARRANGE' in order['completed']
    assert env.stock('SHOE42') == 10


def test_failed_arrange_done_by_hand_goes_on_to_leave_the_zone(env):
    fail_arrange(env)
    with pytest.raises(ValueError, match='물건 놓음'):
        env.scenario.recover('order1', None, None, 'done', {'arms_safe': True})
    env.scenario.recover('order1', 'jihye', '손으로 정리함', 'done', HAND_OK)
    order = env.current()
    assert order['stage'] == 'LEAVE_ARRANGE' and 'ARRANGE' in order['operator_completed']
    echo_reset(env)
    order = env.finish()
    assert order['state'] == 'COMPLETED' and len(arranges(env)) == 1
    assert env.commands()[3:] == ['zone:ZC', 'leave', 'zone:ZA', 'leave', 'home']


def stop_in_pickup(env):
    """상차 구역 안에서 멈춘 로봇 상태를 만든다."""
    env.order()
    env.until('MARKER')
    env.scenario.telemetry('pinky1', {
        'state': 'HOLDING_ZONE', 'held_zone': 'B', 'busy': False,
        'central_controlled': True, 'central_latched': False})


def confirm_loaded(env):
    return env.api.handle({
        'type': 'confirm_loaded', 'request_id': 'manual1', 'order_id': 'order1',
        'operator': 'operator1', 'note': '현장에서 적재 확인',
        'evidence': {'sku': 'SHOE42', 'load_present': True,
                     'arm_safe': True, 'pickup_path_clear': True}})


def test_manual_load_is_accepted_with_only_the_pickup_station_reserved(env):
    """고객 자리 주문은 상차장만 예약하므로 그것만으로 수동 상차 확인을 받는다."""
    stop_in_pickup(env)
    assert set(env.scenario.store.resources('order1')) == {'arm_omx2', 'station_ZB'}
    assert confirm_loaded(env)['status'] == 200
    order = env.current()
    assert order['stage'] == 'LEAVE_PICKUP' and 'VERIFY_LOAD' in order['operator_completed']
    env.until('CUSTOMER')
    assert env.commands()[-1] == 'goto:P22'
    assert not any(stage in {'PICK', 'LOAD', 'VERIFY_LOAD'} for stage, _, _ in env.works())


def test_manual_load_is_refused_without_the_pickup_station(env):
    """상차장 예약이 없으면 고객 자리 주문도 거절한다."""
    stop_in_pickup(env)
    env.scenario.store.release('order1', ['station_ZB'])
    assert confirm_loaded(env)['status'] == 400
    assert env.current()['stage'] == 'MARKER'


def nav_done(env):
    """지금 주행 명령이 로봇에서 끝났다고 알린다 (관제 트리는 아직 돌리지 않는다)."""
    order = env.current()
    env.fleet.tick()
    env.fleet.on_status(order['robot_id'], {
        'command_id': order['request_id'], 'state': 'DONE', 'task_finished': True})
    env.fleet.tick()


def test_disarmed_keeps_reading_results_but_sends_no_new_command(env):
    """주문 받기를 멈춰도 끝난 주행은 반영하고, 다음 명령은 다시 켤 때만 보낸다."""
    env.order()
    env.tick()
    assert env.current()['stage'] == 'MOVE_PICKUP' and env.current()['request_id']
    env.scenario.armed = False
    nav_done(env)
    sent, works = len(env.gateway.sent), len(env.works())
    for _ in range(3):
        env.now += TIMEOUT
        env.tick()
    order = env.current()
    assert order['state'] == 'RUNNING' and 'MOVE_PICKUP' in order['completed']
    assert order['stage'] == 'PICKUP_EXIT' and not order['request_id']
    assert (len(env.gateway.sent), len(env.works())) == (sent, works)
    env.scenario.armed = True
    env.tick()
    assert env.current()['request_id'] and env.works()[-1][0] == 'PICKUP_EXIT'


def test_payment_while_disarmed_is_recorded_at_once(env):
    """멈춘 동안 고객이 결제해도 바로 기록돼, 뒤이은 정지·복구로 잃지 않는다."""
    env.order()
    env.until('CUSTOMER')
    env.scenario.armed = False
    assert env.api.handle({'type': 'received', 'order_id': 'order1'})['status'] == 200
    order = env.current()
    assert order['customer_received'] and 'CUSTOMER' in order['completed']
    assert order['stage'] == 'RETURN_HOME' and not order['request_id']
    env.scenario.armed = True
    order = env.finish()
    assert order['state'] == 'COMPLETED' and not order['customer_timed_out']
    assert env.stock('SHOE42') == 9


def test_navigation_success_seen_after_the_deadline_is_accepted(env):
    """관제 갱신이 늦어 기한 뒤에 본 주행 성공은 시간 초과가 아니라 완료다."""
    env.order()
    env.tick()
    nav_done(env)
    env.now += TIMEOUT + 1
    env.tick()
    order = env.current()
    assert order['state'] == 'RUNNING' and 'MOVE_PICKUP' in order['completed']


def test_navigation_still_running_after_the_deadline_times_out(env):
    """기한이 지나도 끝나지 않은 주행은 그대로 시간 초과로 멈춘다."""
    env.order()
    env.tick()
    env.now += TIMEOUT + 1
    env.tick()
    assert env.current()['state'] == 'UNKNOWN'
    assert env.current()['detail'] == '단계 결과 시간 초과'


def exhaust_dock_pickup(env):
    """상차 정차를 매번 허용 오차 밖으로 답해 재시도를 모두 쓰게 한다."""
    far = {'xy_m': 0.5, 'yaw_deg': 0, 'stopped': True, 'base_hold': True}
    for _ in range(env.scenario.config['max_retries'] + 1):
        env.result(far)
        env.tick()
        if env.current()['failure']:
            return
        env.result()
        env.tick()
    pytest.fail('dock retries did not run out')


def test_dock_failure_before_pick_returns_the_reserved_stock(env):
    env.order()
    assert env.stock('SHOE42') == 9
    env.until('DOCK_PICKUP')
    exhaust_dock_pickup(env)
    final = env.finish()
    assert final['state'] == 'FAILED' and final['stock_on_shelf']
    assert not any(w['action'] == 'pick' for w in env.gateway.work_sent)
    # 팔이 손대지 않아 신발은 선반에 그대로 있다.
    assert env.stock('SHOE42') == 10


def test_dock_failure_after_a_manual_load_keeps_the_stock_reserved(env):
    env.order()
    env.until('DOCK_PICKUP')
    # 사람이 실었다고 확인했으면 신발은 로봇 위에 있다.
    env.scenario._save(env.current(), manual_load_pending=True)
    exhaust_dock_pickup(env)
    final = env.finish()
    assert final['state'] == 'FAILED' and not final.get('stock_on_shelf')
    assert env.stock('SHOE42') == 9


def test_dock_failure_stopped_on_the_way_home_still_returns_the_stock(env):
    env.order()
    env.until('DOCK_PICKUP')
    exhaust_dock_pickup(env)
    env.until('RETURN_HOME')
    env.api.handle({'type': 'estop', 'robot_id': 'pinky1', 'request_id': 'r1'})
    env.tick()
    env.scenario.recover('order1', None, None, 'fail', {
        'arms_safe': True, 'cargo_reconciled': True, 'resources_clear': True})
    assert env.current()['state'] == 'FAILED'
    assert env.stock('SHOE42') == 10
