"""실제 서비스·SQLite·노드 콜백으로 장애 격리와 복구 경계를 검증한다."""

import json
from types import SimpleNamespace

import pytest

from cobot_fleet_control.repository import encode
from test_safety_adapters import ROOT, definitions
from test_scenario import Environment


@pytest.fixture
def env(tmp_path):
    value = Environment(tmp_path / 'review.sqlite3')
    value.scenario.store.set_stock('SHOE42', 10)
    yield value
    value.repo.close()


def status(env, robot='pinky1', **changes):
    data = dict(state='STOPPED', busy=False, central_controlled=True,
                central_latched=True, boot_id='boot1', held_zone=None)
    data.update(changes)
    env.scenario.telemetry(robot, data, 80.0)


def stopped_task(env):
    env.fleet.submit(dict(command_id='job1', robot_id='pinky1', operation='home'))
    env.fleet.tick()
    env.api.handle(dict(type='estop', robot_id='pinky1'))
    status(env)


def release(env):
    return env.api.handle(dict(type='release_control', robot_id='pinky1'))


def test_actual_node_tick_isolates_one_dispatch_failure(env):
    path = ROOT / 'cobot_fleet_control/cobot_fleet_control/fleet_control_node.py'
    namespace = {'json': json, 'encode': encode,
                 'String': lambda **kwargs: SimpleNamespace(**kwargs)}
    exec(definitions(path, set(), ('FleetControlNode', '_tick')), namespace)
    for i in (1, 2):
        env.fleet.submit(dict(command_id=f'job{i}', robot_id=f'pinky{i}', operation='home'))
    original = env.gateway.send

    def send(robot, payload):
        if robot == 'pinky1':
            raise RuntimeError('subscriber disappeared')
        original(robot, payload)

    env.gateway.send = send
    events = []
    node = SimpleNamespace(manual_load_inbox=[], service=env.fleet, scenario=env.scenario,
                           repository=env.repo, halt=env.gateway.halt, api=env.api,
                           events_pub=SimpleNamespace(publish=events.append))
    namespace['_tick'](node)
    assert env.repo.get('job1')['state'] == 'UNKNOWN'
    assert env.repo.confirmation_required('job1')
    assert env.repo.get('job2')['state'] == 'RUNNING'
    assert env.gateway.halts == [('pinky1', '')]
    assert 'pinky1' in env.scenario.store.holds()
    assert 'pinky2' not in env.scenario.store.holds()
    assert events
    env.fleet.on_status('pinky1', dict(command_id='job1', state='DONE', task_finished=True))
    assert env.repo.get('job1')['state'] == 'UNKNOWN'
    namespace['_tick'](node)
    assert len(env.gateway.sent) == 1


@pytest.mark.parametrize('unsafe', ['stale', 'busy', 'missing_evidence', 'false_evidence'])
def test_order_cancel_does_not_release_resources_before_cleanup(env, unsafe):
    env.order()
    env.until('LOAD')
    env.scenario.interrupt('order1', 'ESTOP', 'review stop')
    status(env, held_zone='ZA')
    resources = env.scenario.store.resources('order1')
    proof = dict(arms_safe=True, cargo_reconciled=True, resources_clear=True)
    if unsafe == 'stale':
        env.now += 20
    elif unsafe == 'busy':
        status(env, busy=True)
    elif unsafe == 'missing_evidence':
        proof = None
    else:
        proof['resources_clear'] = False
    reply = env.api.handle(dict(type='resolve', order_id='order1', decision='fail', evidence=proof))
    assert reply['status'] == 400
    assert env.current()['state'] == 'ESTOP'
    assert env.scenario.store.resources('order1') == resources
    assert not env.scenario.store.acquire('another_order', resources)
    assert env.gateway.releases == []
    assert 'pinky1' in env.scenario.store.holds()


def test_confirmed_cleanup_cancels_order_but_robot_waits_for_reset(env):
    env.order()
    env.until('LOAD')
    env.scenario.interrupt('order1', 'ESTOP', 'review stop')
    status(env)
    proof = dict(arms_safe=True, cargo_reconciled=True, resources_clear=True)
    reply = env.api.handle(dict(type='resolve', order_id='order1', decision='fail', evidence=proof))
    assert reply['status'] == 200
    assert env.current()['state'] == 'FAILED'
    assert not env.scenario.store.resources('order1')
    assert 'pinky1' in env.scenario.store.holds()
    assert env.stock('SHOE42') == 9  # Physical work was dispatched: never invent a stock return.
    status(env, central_latched=False, control_reset_id='reset-1')
    assert 'pinky1' not in env.scenario.store.holds()


def test_cancel_unassigned_order_returns_stock_once_even_after_restart(env):
    env.scenario.armed = False
    env.order(quantity=3)
    assert env.stock('SHOE42') == 7
    env.repo.close()
    env.open()
    request = dict(type='resolve', order_id='order1', decision='fail')
    assert env.api.handle(request)['status'] == 200
    assert env.stock('SHOE42') == 10
    assert not env.gateway.sent and not env.gateway.work_sent
    assert env.api.handle(request)['status'] == 400
    env.scenario.store.close_order(env.current(), restock=True)
    assert env.stock('SHOE42') == 10
    env.repo.close()
    env.open()
    assert env.stock('SHOE42') == 10


@pytest.mark.parametrize('unsafe', ['busy', 'missing_busy', 'stale', 'not_central'])
def test_release_rejects_unverified_stop_without_mutating_unknown(env, unsafe):
    stopped_task(env)
    if unsafe == 'stale':
        env.now += 20
    else:
        changes = ({'central_controlled': False} if unsafe == 'not_central'
                   else {'busy': True if unsafe == 'busy' else None})
        status(env, **changes)
    assert release(env)['status'] == 409
    assert env.gateway.releases == []
    assert env.repo.get('job1')['state'] == 'UNKNOWN'
    assert 'pinky1' in env.scenario.store.holds()


def test_release_waits_for_matching_echo_and_deduplicates_clicks(env):
    stopped_task(env)
    reply = release(env)
    assert reply['status'] == 202
    assert reply['body'] == dict(robot_id='pinky1', released=False, reset_pending=True)
    assert release(env)['status'] == 202
    assert len(env.gateway.releases) == 1
    # An ordinary heartbeat, old reset acknowledgement, or still-latched echo cannot unlock.
    for changes in [dict(central_latched=False),
                    dict(central_latched=False, control_reset_id='old'),
                    dict(control_reset_id='reset-1')]:
        status(env, **changes)
        assert env.repo.get('job1')['state'] == 'UNKNOWN'
        assert 'pinky1' in env.scenario.store.holds()
    status(env, central_latched=False, control_reset_id='reset-1')
    assert env.repo.get('job1')['state'] == 'FAILED'
    assert 'pinky1' not in env.scenario.store.holds()


@pytest.mark.parametrize('interrupt', ['timeout', 'stop', 'estop', 'robot_restart', 'server_restart'])
def test_late_reset_echo_cannot_clear_new_or_expired_hold(env, interrupt):
    stopped_task(env)
    assert release(env)['status'] == 202
    boot = 'boot1'
    if interrupt == 'timeout':
        env.now += 4
        env.scenario.tick()
    elif interrupt in ('stop', 'estop'):
        env.api.handle(dict(type=interrupt, robot_id='pinky1'))
    elif interrupt == 'robot_restart':
        boot = 'boot2'
        status(env, boot_id=boot)
    else:
        env.repo.close()
        env.open()
    status(env, boot_id=boot, central_latched=False, control_reset_id='reset-1')
    assert 'pinky1' in env.scenario.store.holds()
    assert env.repo.get('job1')['state'] == 'UNKNOWN'


def test_robot_reset_echo_comes_only_after_guard_acceptance():
    path = ROOT / 'cobot_pinky_patrol/cobot_pinky_patrol/pinky_patrol_node.py'
    namespace = {'json': json, 'time': SimpleNamespace(time=lambda: 100)}
    exec(definitions(path, set(), ('PinkyPatrolNode', '_cmd_cb')), namespace)
    emitted, rejected = [], []
    node = SimpleNamespace(
        config={'central_controlled': True}, controller=SimpleNamespace(busy=True),
        central_guard=SimpleNamespace(accept=lambda payload, reset: True),
        _emit=emitted.append, get_logger=lambda: SimpleNamespace(warning=rejected.append))
    message = SimpleNamespace(data=json.dumps(dict(command_id='reset1', command='control_reset')))
    namespace['_cmd_cb'](node, message)
    assert not emitted and rejected
    node.controller.busy = False
    node.central_guard.accept = lambda payload, reset: False
    namespace['_cmd_cb'](node, message)
    assert not emitted
    node.central_guard.accept = lambda payload, reset: True
    namespace['_cmd_cb'](node, message)
    assert emitted[0]['control_reset_id'] == 'reset1'
