"""실제 SQLite와 주행 행동 트리를 사용해 시나리오 전체의 결정을 검증한다."""

import json
from pathlib import Path

from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.scenario import ScenarioService
from cobot_fleet_control.scenario_contracts import NAVIGATION
from cobot_fleet_control.service import FleetService

import pytest

import yaml


ROUTES = {'lab': dict(pickup='ZA', dropoff='ZB', pickup_arm='omx1',
                      dropoff_arm='omx2', lane='main')}


class Gateway:
    """하드웨어를 움직이지 않고 장치 요청과 소프트웨어 정지를 관찰한다."""

    def __init__(self):
        self.sent, self.work_sent, self.halts, self.stops = [], [], [], []

    def send(self, robot, payload):
        self.sent.append((robot, payload))

    def work(self, payload):
        self.work_sent.append(payload)

    def stop(self, robot):
        self.stops.append(robot)

    def halt(self, robot, route, order_id):
        self.halts.append((robot, order_id))

    def release(self, robot, route=None):
        pass


class Environment:
    """명시적 시계와 각각 갱신하는 배터리·로봇 상태 수신 시각을 사용한다."""

    def __init__(self, path):
        self.path, self.now = str(path), 0.0
        self.gateway = Gateway()
        self.open()
        self.scenario.armed = True

    def open(self):
        self.repo = SqliteRepository(self.path)
        self.fleet = FleetService(self.repo, self.gateway, ['pinky1', 'pinky2'], lambda: self.now)
        self.scenario = ScenarioService(self.repo, self.fleet, self.gateway, ROUTES,
                                        clock=lambda: self.now, allow_returns=True)
        self.api = ControlAPI(self.scenario, self.fleet, self.gateway)
        self.healthy()

    def healthy(self):
        for robot in self.fleet.robots:
            self.scenario.telemetry(robot, dict(state='IDLE', central_controlled=True), 80.0)

    def tick(self):
        self.healthy()
        self.fleet.tick()
        self.scenario.tick()

    def order(self, order_id='order1', **changes):
        data = dict(order_id=order_id, sku='SHOE42', route='lab')
        data.update(changes)
        return self.scenario.submit(data)

    def current(self, order_id='order1'):
        return self.scenario.store.get(order_id)

    def stock(self, sku):
        """재고 예약 검증에 필요한 값은 시험 도우미에서 직접 조회한다."""
        row = self.repo.db.execute(
            'SELECT available FROM scenario_stock WHERE sku=?', (sku,)).fetchone()
        return row[0] if row else 0

    def result(self, data=None, **changes):
        order = self.current()
        work = next(w for w in reversed(self.gateway.work_sent)
                    if w['request_id'] == order['request_id'])
        result = dict(request_id=work['request_id'], order_id=work['order_id'],
                      robot_id=work['robot_id'], stage=work['stage'], source=work['target'],
                      success=True, measured=True, finished=True, data=data or {})
        result.update(changes)
        self.scenario.result(result)
        return result

    def step(self):
        self.tick()
        order = self.current()
        if order['state'] != 'RUNNING':
            return
        if order['stage'] == 'CUSTOMER':
            self.scenario.received('order1')
        elif order['stage'] in NAVIGATION:
            self.fleet.tick()
            self.fleet.on_status(order['robot_id'], dict(
                command_id=order['request_id'], state='DONE', task_finished=True))
            self.fleet.tick()
            self.scenario.tick()
        else:
            self.result(dict(xy_m=0.005, yaw_deg=1.0, stopped=True, base_hold=True,
                             sku='SHOE42', arm_safe=True, load_present=True,
                             load_absent=True, placed=True, clear=True))

    def until(self, stage):
        for _ in range(80):
            if self.current()['stage'] == stage:
                self.tick()
                return
            self.step()
        pytest.fail('stage not reached: ' + stage)


@pytest.fixture
def env(tmp_path):
    e = Environment(tmp_path / 'fleet.sqlite3')
    e.scenario.store.set_stock('SHOE42', 10)
    yield e
    e.repo.close()


def test_delivery_requires_all_device_results_customer_and_home(env):
    env.order()
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    order = env.current()
    assert order['state'] == 'COMPLETED'
    assert order['customer_received'] and not order['customer_timed_out']
    assert {'VERIFY_LOAD', 'VERIFY_UNLOAD', 'RETURN_EXIT'} <= set(order['completed'])
    assert [p['command'] for _, p in env.gateway.sent] == [
        'zone:ZA', 'leave', 'zone:ZB', 'leave', 'home']
    assert not env.scenario.store.resources('order1')
    assert env.stock('SHOE42') == 9


@pytest.mark.parametrize('route,pickup', [('lab_delivery', 'ZA'), ('lab_delivery_zb', 'ZB')])
def test_configured_lab_routes_load_with_omx1_and_deliver_to_zc_with_omx2(env, route, pickup):
    """실제 배포 설정의 두 상차 경로가 ZC 하차와 올바른 팔 요청으로 끝나는지 검증한다."""
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / 'config/scenario.yaml').read_text())
    env.scenario = ScenarioService(env.repo, env.fleet, env.gateway,
                                   clock=lambda: env.now, **config)
    env.api = ControlAPI(env.scenario, env.fleet, env.gateway)
    env.scenario.armed = True
    env.order(route=route)
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    assert env.current()['state'] == 'COMPLETED'
    assert [payload['command'] for _, payload in env.gateway.sent] == [
        f'zone:{pickup}', 'leave', 'zone:ZC', 'leave', 'home']
    assert next(w['target'] for w in env.gateway.work_sent if w['stage'] == 'LOAD') == 'omx1'
    assert next(w['target'] for w in env.gateway.work_sent if w['stage'] == 'UNLOAD') == 'omx2'


def test_qos_duplicate_conflict_inventory_atomicity_and_no_available_robot(env):
    env.scenario.armed = False
    first = env.order(quantity=2)
    assert env.order(quantity=2) == first
    assert env.stock('SHOE42') == 8
    with pytest.raises(ValueError, match='다른 주문'):
        env.order(quantity=3)
    with pytest.raises(ValueError, match='재고 부족'):
        env.order('too_many', quantity=9)
    assert env.scenario.store.get('too_many') is None
    env.scenario.tick()
    assert env.current()['robot_id'] is None
    assert env.gateway.sent == []
    env.scenario.armed = True
    env.scenario.health.clear()
    env.scenario.tick()
    assert env.current()['state'] == 'WAITING'


def test_no_assignment_on_unknown_low_stale_battery_or_local_autonomy(env):
    env.order()
    for robot in env.fleet.robots:
        env.scenario.telemetry(robot, dict(state='IDLE', central_controlled=False), 80.0)
    env.scenario.tick()
    assert env.current()['robot_id'] is None
    env.healthy()
    for robot in env.fleet.robots:
        env.scenario.telemetry(robot, battery=2.0)
    env.scenario.tick()
    assert env.current()['robot_id'] is None
    env.healthy()
    env.now = 11.0
    for robot in env.fleet.robots:
        env.scenario.telemetry(robot, status=dict(state='IDLE', central_controlled=True))
    env.scenario.tick()
    assert env.current()['robot_id'] is None
    env.healthy()
    env.scenario.tick()
    assert env.current()['robot_id'] == 'pinky1'


def test_measured_correlated_results_only_and_sku_mismatch_blocks_pick(env):
    env.order()
    env.until('DOCK_PICKUP')
    stale = env.result(dict(xy_m=0, yaw_deg=0, stopped=True, base_hold=True), measured=False)
    assert env.current()['stage'] == 'DOCK_PICKUP'
    env.result(dict(xy_m=0, yaw_deg=0, stopped=True, base_hold=True), source='wrong_camera')
    assert env.current()['stage'] == 'DOCK_PICKUP'
    env.result(dict(xy_m=0, yaw_deg=0, stopped=True, base_hold=True))
    env.tick()
    assert not env.scenario.result(stale)
    env.result(dict(sku='WRONG_SHOE'))
    assert env.current()['state'] == 'UNKNOWN'
    assert env.gateway.halts
    assert not any(w['action'] == 'pick' for w in env.gateway.work_sent)
    assert env.scenario.store.resources('order1')


def test_dock_correction_requires_new_measurement_and_limits_three_retries(env):
    env.order()
    env.until('DOCK_PICKUP')
    for _ in range(3):
        env.result(dict(xy_m=0.5, yaw_deg=0, stopped=True, base_hold=True))
        assert env.current()['stage'] == 'CORRECT_PICKUP'
        env.tick()
        env.result()
        assert env.current()['stage'] == 'DOCK_PICKUP'
        env.tick()
    env.result(dict(xy_m=0.5, yaw_deg=0, stopped=True, base_hold=True))
    assert env.current()['stage'] == 'RETURN_HOME'
    assert env.current()['failure']
    for _ in range(10):
        env.step()
    assert env.current()['state'] == 'FAILED'
    assert not any(w['action'] == 'pick' for w in env.gateway.work_sent)


def test_qr_safe_retry_attempt_ids_and_unsafe_arm_retry_blocked(env):
    env.order()
    env.until('QR')
    old = env.result(dict(retry_safe=True), success=False)
    env.tick()
    assert env.current()['request_id'] != old['request_id']
    assert not env.scenario.result(old)
    env.result(dict(sku='SHOE42'))
    env.tick()
    env.result(success=False)
    assert env.current()['state'] == 'UNKNOWN'
    assert len([w for w in env.gateway.work_sent if w['stage'] == 'PICK_DROPOFF']) == 1


def test_customer_120_second_timeout_records_and_returns_without_claiming_receipt(env):
    env.order()
    env.until('CUSTOMER')
    env.now += 119.9
    env.tick()
    assert env.current()['stage'] == 'CUSTOMER'
    env.now += 0.1
    env.tick()
    assert env.current()['stage'] == 'LEAVE_DROPOFF'
    assert env.current()['customer_timed_out']
    assert not env.current()['customer_received']
    for _ in range(15):
        env.step()
    assert env.current()['state'] == 'COMPLETED'
    events = [json.loads(row['payload']) for row in env.repo.pending(1000)]
    assert any(e.get('code') == 'CUSTOMER_TIMEOUT' for e in events)


def test_departure_gap_and_station_arm_mutex(env):
    env.order()
    env.order('order2')
    env.tick()
    assert env.current('order2')['robot_id'] is None
    env.now = 3.0
    env.tick()
    assert env.current('order2')['robot_id'] == 'pinky2'
    assert env.current('order2')['request_id'] is None
    assert env.scenario.store.resources('order2') == []
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    env.tick()
    assert env.current('order2')['request_id'] is not None


def test_lane_lease_not_released_by_navigation_arrival_alone(env):
    env.order()
    env.until('PATH_EXIT')
    assert 'lane_main' in env.scenario.store.resources('order1')
    env.result(dict(clear=False))
    assert 'lane_main' in env.scenario.store.resources('order1')
    env.result(dict(clear=True))
    assert 'lane_main' not in env.scenario.store.resources('order1')


def test_link_loss_stops_and_recovery_does_not_accept_late_device_success(env):
    env.order()
    env.until('LOAD')
    last = env.gateway.work_sent[-1]
    env.now += 4.0
    env.scenario.tick()
    assert env.current()['state'] == 'UNKNOWN'
    assert env.gateway.halts[-1] == ('pinky1', 'order1')
    assert not env.scenario.result(dict(last, source=last['target'], success=True,
                                        measured=True, finished=True))
    env.healthy()
    env.tick()
    assert env.current()['state'] == 'UNKNOWN'
    evidence = dict(base_stopped=True, arms_safe=True, cargo_reconciled=True, resources_clear=True)
    with pytest.raises(ValueError, match='임의 재피킹'):
        env.scenario.recover('order1', 'operator', '현장 확인', 'resume', evidence)
    # 화면 확인 창 한 번: 운영자·메모·확인 항목 없이도 취소된다 (기본값으로 기록)
    with pytest.raises(ValueError, match='evidence'):
        env.scenario.recover('order1', None, None, 'fail', 'yes')
    env.scenario.recover('order1', None, None, 'fail', None, source='10.0.0.5')
    assert env.current()['state'] == 'FAILED'
    assert not env.scenario.store.resources('order1')


def test_restart_preserves_order_inventory_and_leases_without_redispatch(env):
    env.order()
    env.until('LOAD')
    sent = len(env.gateway.sent), len(env.gateway.work_sent)
    resources = env.scenario.store.resources('order1')
    env.repo.close()
    env.open()
    assert not env.scenario.armed
    env.scenario.armed = True
    env.tick()
    assert env.current()['state'] == 'UNKNOWN'
    assert env.scenario.store.resources('order1') == resources
    assert env.stock('SHOE42') == 9
    assert (len(env.gateway.sent), len(env.gateway.work_sent)) == sent


def test_arm_and_raw_manual_web_contract_and_latched_stop_without_order(env):
    reply = env.api.handle(dict(type='estop', request_id='web-1', robot_id='pinky1'))
    assert reply['request_id'] == 'web-1' and reply['status'] == 202
    # 로봇 하나의 정지는 그 로봇만 보류하고 작업 명령은 켜 둔다
    assert env.scenario.armed and reply['body']['armed'] is True
    env.order()
    env.tick()
    assert env.current()['robot_id'] == 'pinky2'
    assert env.api.handle(dict(type='raw', command='goto:P1'))['status'] == 403
    assert env.api.snapshot()['holds']['pinky1'] == 'ESTOP'
    # 주문 없는 로봇의 복구는 로봇만 지정하면 된다 (확인 창 한 번, 운영자·메모·확인 항목은 선택)
    assert env.api.handle(dict(type='release_control', robot_id='pinky1'))['status'] == 200
    assert 'pinky1' not in env.api.snapshot()['holds']
    # 보류·래치가 없으면 복구할 것이 없다
    assert env.api.handle(dict(type='release_control', robot_id='pinky1'))['status'] == 400


def test_release_control_optional_fields_are_still_checked(env):
    env.api.handle(dict(type='estop', robot_id='pinky1'))
    bad = [dict(operator='이름 공백'), dict(note=3), dict(evidence='yes')]
    for extra in bad:
        reply = env.api.handle(dict(type='release_control', robot_id='pinky1', **extra))
        assert reply['status'] == 400, extra
    reply = env.api.handle(dict(type='release_control', robot_id='pinky1', source='10.0.0.5'))
    assert reply['status'] == 200


def test_raw_command_only_when_allowed_and_sent_in_session_envelope(env):
    def raw(command='goto:P1', robot='pinky1'):
        return env.api.handle({'type': 'raw', 'robot_id': robot, 'command': command})

    assert raw()['status'] == 403
    env.api = ControlAPI(env.scenario, env.fleet, env.gateway, allow_raw_cmd=True)
    assert env.api.snapshot()['allow_raw_cmd'] is True
    reply = raw('  goto:P1 ')
    assert reply['status'] == 202
    body = reply['body']
    assert body['command'] == 'goto:P1' and body['raw_id'].startswith('raw_')
    assert body['topic'] == '/pinky1/patrol_cmd' and body['spec'] == 'v1'
    # gateway.send 가 세션·순번·TTL 봉투를 붙인다. 여기서는 command_id·command 만 넘긴다
    assert env.gateway.sent[-1] == ('pinky1', {'command_id': body['raw_id'],
                                               'command': 'goto:P1'})
    assert raw(robot='pinky9')['status'] == 404
    assert raw('')['status'] == 400
    assert raw('goto:P1\nstop')['status'] == 400
    assert raw('x' * 201)['status'] == 400
    env.api.handle({'type': 'estop', 'robot_id': 'pinky1'})
    # 정지 뒤 보류된 로봇에는 보내지 않는다 (작업 명령은 켜진 채)
    assert env.scenario.armed and raw()['status'] == 409
    sent = len(env.gateway.sent)
    assert raw(robot='pinky2')['status'] == 202 and len(env.gateway.sent) == sent + 1
    # 전체 비상정지(로봇 지정 없음)는 작업 명령 전체를 끈다
    reply = env.api.handle({'type': 'estop'})
    assert reply['body']['armed'] is False and not env.scenario.armed
    assert raw(robot='pinky2')['status'] == 423


def test_manual_task_matches_existing_web_display_fields(env):
    reply = env.api.handle(dict(
        type='create', request_id='web1', client_request_id='manual1',
        robot_id='pinky1', operation='goto', points=['P1']))
    assert reply['status'] == 202
    task = reply['body']
    assert task['command'] == 'goto:P1'
    assert task['task_id'] == 'manual1' and task['created_at'] > 0
    assert task['updated_at'] >= task['created_at']


def test_optional_return_uses_explicit_reverse_route_store_and_replenishes_once(env):
    env.order(kind='return')
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    assert env.current()['state'] == 'COMPLETED'
    assert [p['command'] for _, p in env.gateway.sent][:3] == ['zone:ZB', 'leave', 'zone:ZA']
    assert any(w['action'] == 'warehouse_store' for w in env.gateway.work_sent)
    assert env.stock('SHOE42') == 11
    env.order(kind='return')
    env.tick()
    assert env.stock('SHOE42') == 11


@pytest.mark.parametrize('changes', [
    {'order_id': []}, {'sku': ''}, {'route': 'missing'}, {'quantity': True},
    {'quantity': 0}, {'kind': []}, {'extra': 1},
])
def test_invalid_orders_do_not_reserve_stock(env, changes):
    with pytest.raises(ValueError):
        env.order(**changes)
    assert env.stock('SHOE42') == 10


def test_pause_before_first_bt_tick_prevents_queued_movement(env):
    env.order()
    env.scenario.tick()  # 주행을 등록한 단계이며 아직 로봇에 전달된 명령은 없다.
    assert env.gateway.sent == []
    env.api.handle(dict(type='pause', robot_id='pinky1'))
    env.fleet.tick()
    assert env.gateway.sent == []
    assert env.current()['state'] == 'PAUSED'
    assert env.gateway.halts


def test_device_timeout_quarantines_attempt_before_late_success(env):
    env.order()
    env.until('MARKER')
    request = env.gateway.work_sent[-1]
    env.now += 301
    env.healthy()
    late = dict(request_id=request['request_id'], order_id='order1', robot_id='pinky1',
                stage='MARKER', source='vision', success=True, measured=True, finished=True,
                data={'sku': 'SHOE42'})
    assert not env.scenario.result(late)
    assert env.current()['state'] == 'UNKNOWN'
    assert not any(w['action'] == 'pick' for w in env.gateway.work_sent)


def test_robot_boot_change_invalidates_current_stage(env):
    env.scenario.telemetry('pinky1', dict(state='IDLE', central_controlled=True, boot_id='boot1'))
    env.order()
    env.scenario.tick()
    env.scenario.telemetry('pinky1', dict(state='IDLE', central_controlled=True, boot_id='boot2'))
    assert env.current()['state'] == 'UNKNOWN'
    env.fleet.tick()
    assert env.gateway.sent == []


def test_operator_recovery_cannot_resume_until_robot_reset_is_echoed(env):
    env.order()
    env.scenario.tick()
    env.scenario.interrupt('order1', 'PAUSED', 'operator pause')
    env.scenario.armed = True
    env.scenario.telemetry('pinky1', dict(
        state='IDLE', central_controlled=True, central_latched=True))
    proof = dict(base_stopped=True, arms_safe=True, cargo_reconciled=True, resources_clear=True)
    env.scenario.recover('order1', 'operator', '현장 확인', 'resume', proof)
    env.scenario.tick()
    assert env.current()['request_id'] is None
    env.scenario.telemetry('pinky1', dict(
        state='IDLE', central_controlled=True, central_latched=False))
    env.scenario.tick()
    assert env.current()['request_id'] is not None


def test_pickup_approach_keeps_lane_until_actual_tail_exit(env):
    env.order()
    env.until('PICKUP_EXIT')
    assert 'lane_main' in env.scenario.store.resources('order1')
    env.result(dict(clear=False))
    assert env.current()['stage'] == 'PICKUP_EXIT'
    env.result(dict(clear=True))
    assert 'lane_main' not in env.scenario.store.resources('order1')


def test_opposite_orders_cannot_deadlock_by_holding_each_others_station(env):
    env.order()
    env.order('return_order', kind='return')
    env.tick()
    env.now = 3
    env.tick()
    assert set(env.scenario.store.resources('order1')) >= {
        'station_ZA', 'station_ZB', 'arm_omx1', 'arm_omx2'}
    assert env.scenario.store.resources('return_order') == []
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    env.tick()
    assert env.current('return_order')['request_id']


def test_loaded_robot_waits_before_leaving_if_shared_lane_is_owned(env):
    env.order()
    env.until('VERIFY_LOAD')
    env.result(dict(load_present=True, arm_safe=True))
    assert env.scenario.store.acquire('other_route', ['lane_main'])
    env.tick()
    assert env.current()['stage'] == 'LEAVE_PICKUP'
    assert env.current()['request_id'] is None
    env.scenario.store.release('other_route', ['lane_main'])
    env.tick()
    assert env.current()['request_id']


def test_safe_unload_verification_failure_retries_action_with_shared_budget(env):
    env.order()
    env.until('VERIFY_UNLOAD')
    env.result(dict(retry_safe=True), success=False)
    assert env.current()['stage'] == 'UNLOAD'
    assert env.current()['retries']['UNLOAD'] == 1
    env.tick()
    assert env.gateway.work_sent[-1]['action'] == 'unload'
    for _ in range(3):
        env.result(dict(retry_safe=True), success=False)
        if env.current()['state'] == 'UNKNOWN':
            break
        env.tick()
    assert env.current()['state'] == 'UNKNOWN'
    assert len([w for w in env.gateway.work_sent if w['action'] == 'unload']) == 4
