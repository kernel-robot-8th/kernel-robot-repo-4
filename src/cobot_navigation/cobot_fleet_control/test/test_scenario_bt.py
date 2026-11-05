"""전체 주문을 실제 BT로 실행하며 중단·재개·장치 결과가 순서를 우회하지 못하는지 검증한다."""

import json

from cobot_fleet_control.scenario_nodes import DeviceStep, NavigationStep
from cobot_fleet_control.scenario_tree import STAGES
import py_trees
import pytest

from test_scenario import Environment


@pytest.fixture
def env(tmp_path):
    """실제 원장을 쓰되 장치·시간만 대체한다."""
    environment = Environment(tmp_path / 'bt.sqlite3')
    environment.scenario.store.set_stock('SHOE42', 10)
    yield environment
    environment.repo.close()


def traces(environment):
    """주문별 전체 BT의 실제 관측 기록만 읽는다."""
    return [event for row in environment.repo.pending(10000)
            if (event := json.loads(row['payload']))['type'] == 'scenario_bt_snapshot']


def test_actual_tree_owns_navigation_cargo_customer_and_return(env):
    env.order()
    env.tick()
    tree = env.scenario.trees['order1'].tree
    assert isinstance(tree, py_trees.trees.BehaviourTree)
    nodes = list(tree.root.iterate())
    assert any(isinstance(node, DeviceStep) and node.stage == 'LOAD' for node in nodes)
    assert any(isinstance(node, NavigationStep) and node.stage == 'RETURN_HOME' for node in nodes)
    for _ in range(80):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    recorded = traces(env)
    visited = {node['stage'] for trace in recorded for node in trace['nodes']
               if node.get('stage') and node['visited']}
    assert set(STAGES) - {'CUSTOMER'} <= visited
    assert recorded[-1]['job_state'] == 'COMPLETED'
    assert next(node for node in recorded[-1]['nodes']
                if node['id'] == recorded[-1]['root_id'])['status'] == 'SUCCESS'
    assert len([work for work in env.gateway.work_sent if work['stage'] == 'LOAD']) == 1


def test_arm_toggle_preserves_tree_memory_without_replaying_physical_steps(env):
    env.order()
    env.until('VERIFY_LOAD')
    sent = len(env.gateway.sent), len(env.gateway.work_sent)
    runtime = env.scenario.trees['order1']
    env.scenario.armed = False
    for _ in range(3):
        env.tick()
    assert env.scenario.trees['order1'] is runtime
    assert (len(env.gateway.sent), len(env.gateway.work_sent)) == sent
    env.scenario.armed = True
    env.result(dict(load_present=True, arm_safe=True))
    env.tick()
    assert len([work for work in env.gateway.work_sent if work['stage'] == 'LOAD']) == 1
    assert env.current()['stage'] == 'LEAVE_PICKUP'


def test_result_callback_advances_tree_without_sending_next_device_command(env):
    env.order()
    env.until('MARKER')
    sent = len(env.gateway.work_sent)
    env.result(dict(sku='SHOE42'))
    assert env.current()['stage'] == 'PICK'
    assert len(env.gateway.work_sent) == sent
    env.tick()
    assert env.gateway.work_sent[-1]['stage'] == 'PICK'


def test_safe_verification_retry_revisits_action_subtree_with_new_attempt(env):
    env.order()
    env.until('VERIFY_LOAD')
    old = env.current()['request_id']
    env.result(dict(retry_safe=True), success=False)
    assert env.current()['stage'] == 'LOAD'
    env.tick()
    assert env.current()['request_id'] != old
    assert env.current()['retries']['LOAD'] == 1
    assert len([work for work in env.gateway.work_sent if work['stage'] == 'LOAD']) == 2


@pytest.mark.parametrize('stage', ['MOVE_DROPOFF', 'CUSTOMER', 'RETURN_HOME'])
def test_recovery_uses_approved_checkpoint_without_replaying_pickup(env, stage):
    env.order()
    env.until(stage)
    before = len([work for work in env.gateway.work_sent if work['stage'] == 'PICK'])
    env.scenario.interrupt('order1', 'PAUSED', '현장 일시정지')
    env.scenario.recover('order1', 'operator', '현장 정지·화물·자원 확인', 'resume', dict(
        base_stopped=True, arms_safe=True, cargo_reconciled=True, resources_clear=True))
    for _ in range(40):
        env.step()
        if env.current()['state'] == 'COMPLETED':
            break
    assert env.current()['state'] == 'COMPLETED'
    assert len([work for work in env.gateway.work_sent if work['stage'] == 'PICK']) == before


def test_stop_invalidates_full_tree_and_keeps_resources_visible(env):
    env.order()
    env.until('LOAD')
    sent = len(env.gateway.work_sent)
    env.scenario.interrupt('order1', 'ESTOP', '운영자 정지')
    trace = traces(env)[-1]
    assert trace['phase'] == 'interrupted' and trace['job_state'] == 'ESTOP'
    assert trace['resources']
    assert all(node['status'] == 'INVALID' for node in trace['nodes'])
    env.tick()
    assert len(env.gateway.work_sent) == sent


def test_exception_inside_tree_quarantines_order_instead_of_crashing_other_orders(env):
    env.order()
    env.tick()
    runtime = env.scenario.trees['order1']

    def broken_tick():
        raise RuntimeError('시험용 실행 오류')

    runtime.tree.tick = broken_tick
    env.scenario.tick()
    assert env.current()['state'] == 'UNKNOWN'
    assert env.gateway.halts[-1] == ('pinky1', 'order1')
    assert '시나리오 BT 실행 예외' in env.current()['detail']
