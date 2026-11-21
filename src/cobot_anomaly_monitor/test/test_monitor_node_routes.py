"""
감시 노드의 경로 표(11-21 S5·G10)와 팔 노드 표·경고(S4·G2·P7) 시험.

monitor_node 는 rclpy 를 불러오므로 node_stub 이 ROS 모듈을 잠시 가짜로 바꿔 순수 부분만 부른다.
경로 표는 관제 origin/sakim ScenarioService._layout 결과와 그대로 맞춘다(시험에서만 관제 패키지를 import).
"""

import json
from pathlib import Path
import types

from harness import DEV_CONFIG, Stack
from node_stub import fake_node, load_monitor_node
import pytest
import yaml

SAKIM_CONFIG = (Path(__file__).resolve().parents[2]
                / 'cobot_navigation/cobot_fleet_control/config/scenario.yaml')
PEER_TARGETS = ['omx1', 'omx2', 'omx3']


@pytest.fixture
def node_module(monkeypatch):
    return load_monitor_node(monkeypatch)


def sakim_layout(config):
    from cobot_fleet_control.scenario import ScenarioService
    return ScenarioService._layout(config['routes'], config.get('shelf'),
                                   config.get('destinations'), config.get('customer_return'))[2]


@pytest.mark.parametrize('path', [DEV_CONFIG, SAKIM_CONFIG], ids=['monitor_dev', 'sakim'])
def test_route_table_matches_the_control_layout(node_module, path):
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    routes, problems = node_module.layout_routes(config)
    assert problems == [] and routes == sakim_layout(config)
    assert routes['col1__P22'] == {
        'pickup': 'ZB', 'pickup_arm': 'omx2', 'customer': 'P22', 'dropoff': 'ZC',
        'dropoff_arm': 'omx3', 'restock': 'ZA', 'restock_arm': 'omx1', 'lane': 'main'}
    assert routes['col2__P22'] == routes['col1__P22']


def test_route_table_with_a_dropoff_destination_matches_the_control(node_module):
    config = {'routes': {'r': {'pickup': 'ZA', 'dropoff': 'ZC', 'pickup_arm': 'omx1',
                               'dropoff_arm': 'omx3', 'lane': 'main'}},
              'shelf': {'rows': 2, 'columns': {3: {'pickup': 'ZB', 'pickup_arm': 'omx2'}}},
              'destinations': {'T1': {'dropoff': 'ZD', 'dropoff_arm': 'omx4', 'lane': 'side',
                                      'name': '창가'}}}
    routes, problems = node_module.layout_routes(config)
    assert problems == [] and routes == sakim_layout(config)
    assert routes['col3__T1'] == {'pickup': 'ZB', 'pickup_arm': 'omx2', 'dropoff': 'ZD',
                                  'dropoff_arm': 'omx4', 'lane': 'side'}


def test_route_table_without_seat_settings_is_the_routes(node_module):
    config = yaml.safe_load(DEV_CONFIG.read_text(encoding='utf-8'))
    plain = {'routes': config['routes']}
    assert node_module.layout_routes(plain) == (config['routes'], [])
    assert node_module.layout_routes({}) == ({}, [])


@pytest.mark.parametrize('change,expected_problem', [
    ({'customer_return': None}, 'customer_return'),
    ({'destinations': {'P22': {'point': 'P22'}}}, 'point, lane'),
    ({'routes': {'col1__P22': {'pickup': 'ZA'}}}, '겹침'),
    ({'shelf': {'rows': 4, 'columns': {1: {'pickup': 'ZB'}}}}, 'pickup_arm'),
    ({'destinations': ['P22']}, '형식 오류'),
])
def test_bad_seat_settings_are_skipped_not_fatal(node_module, change, expected_problem):
    """관제라면 거절할 설정이다. 감시 노드는 뜨되 그 경로만 빼고 문제를 알린다."""
    config = dict(yaml.safe_load(DEV_CONFIG.read_text(encoding='utf-8')), **change)
    routes, problems = node_module.layout_routes(config)
    assert problems and any(expected_problem in p for p in problems)
    assert 'wh_a_to_store' in routes or 'col1__P22' in routes
    if 'routes' not in change:
        assert 'col1__P22' not in routes


class Core:
    def __init__(self):
        self.arm_nodes = {}

    def set_arm_nodes(self, nodes):
        self.arm_nodes = dict(nodes)


def test_arm_nodes_follow_the_peer_publishers(node_module):
    peers = {'now': ['omx3_adapter']}
    node = fake_node(node_module, core=Core(), config={'peer_targets': PEER_TARGETS},
                     _foreign_publishers=lambda: ([], peers['now']))
    node._update_arm_nodes()
    assert node.core.arm_nodes == {'omx1': False, 'omx2': False, 'omx3': True}
    assert node.logger.lines == [('info', '팔 노드 없음: omx1, omx2')]
    node._update_arm_nodes()
    assert len(node.logger.lines) == 1  # 바뀌지 않으면 다시 쓰지 않는다
    peers['now'] = ['arm_adapter']
    node._update_arm_nodes()
    assert node.core.arm_nodes == {'omx1': True, 'omx2': True, 'omx3': True}
    assert node.logger.lines[-1] == ('info', '팔 노드 모두 보임')


@pytest.mark.parametrize('peers,yielded', [
    ([], set()), (['omx3_adapter'], set(PEER_TARGETS)), (['arm_adapter'], set(PEER_TARGETS))])
def test_yield_rule_is_unchanged(node_module, peers, yielded):
    """팀 팔 노드가 하나라도 보이면 팔 대상 전부를 양보한다(기존 규칙). 팔 단계에는 답하지 않는다."""
    adapter = types.SimpleNamespace(blocked='기동 검사 전', yielded=set())
    node = fake_node(node_module, adapter=adapter, config={'peer_targets': PEER_TARGETS},
                     _foreign_publishers=lambda: ([], peers))
    node._check_adapter()
    assert adapter.yielded == yielded and adapter.blocked == ''


class Message:
    def __init__(self, payload):
        self.data = json.dumps(payload, ensure_ascii=False)


class Adapter:
    def __init__(self):
        self.seen = []

    def on_request(self, request):
        self.seen.append(request['request_id'])
        return False


def arm_request(target='omx2', stage='PICK', rid='w1', order='o1'):
    return {'request_id': rid, 'order_id': order, 'robot_id': 'pinky1', 'stage': stage,
            'target': target, 'action': 'pick', 'route': {'pickup': 'ZB'}}


def test_arm_request_without_its_node_is_recorded_and_still_not_answered(node_module, tmp_path):
    from cobot_anomaly_monitor.monitor_store import MonitorStore
    store = MonitorStore(tmp_path / 'm.sqlite3')
    core, adapter = Core(), Adapter()
    node = fake_node(node_module, core=core, store=store, adapter=adapter)
    node._work_request(Message(arm_request(rid='w0')))  # 그래프를 읽기 전이면 모른다
    core.set_arm_nodes({'omx1': False, 'omx2': False, 'omx3': True})
    node._work_request(Message(arm_request(rid='w1')))
    node._work_request(Message(arm_request('omx3', 'ARRANGE', rid='w2')))
    node._work_request(Message(arm_request('vision', 'VERIFY_LOAD', rid='w3')))
    node._work_request(Message(arm_request('omx1', 'SAFETY', rid='w4')))  # 정지 보류 통지
    rows = store.wire_page('o1', 0)['events']
    assert [(r['kind'], r['request_id']) for r in rows] == [
        ('request', 'w0'), ('request', 'w1'), ('arm_node_missing', 'w1'),
        ('request', 'w2'), ('request', 'w3'), ('request', 'w4')]
    warning = rows[2]['payload']
    assert warning == {'code': 'ARM_NODE_MISSING', 'detail': '팔 노드 없음 (omx2_adapter 미발견)',
                       'target': 'omx2', 'stage': 'PICK', 'robot_id': 'pinky1'}
    assert adapter.seen == ['w0', 'w1', 'w2', 'w3', 'w4']  # 어댑터 판단(양보)은 그대로 거친다
    assert [line for line in node.logger.lines if line[0] == 'warning'] == [
        ('warning', '팔 노드 없음 (omx2_adapter 미발견) · PICK 요청 w1')]
    store.close()


def test_seat_order_record_gets_its_arms_from_the_route_table(node_module, tmp_path):
    """자리 주문 감시 기록에 상차 팔 omx2·정리 팔 omx3 이 남고 상차 구역 진입(2단계)도 잡힌다."""
    stack = Stack(tmp_path)
    try:
        before = stack.core._route({'route': 'col1__P22'})
        stack.core.routes, _ = node_module.layout_routes(stack.config)
        stack.scenario.store.set_stock('SHOE42', 10, 3, 1)
        stack.scenario.submit({'order_id': 'seat1', 'sku': 'SHOE42', 'destination': 'P22'})
        order = stack.until('PICK', 'seat1')
        row = stack.store.scenario('seat1')
        assert before == {} and row['route'] == 'col1__P22'
        assert (row['load_arm_id'], row['unload_arm_id']) == ('omx2', 'omx3')
        steps = [view[order['robot_id']]['step_seq'] for view in stack.history]
        assert 2 in steps and row['current_step_seq'] == 3
        actors = {t['step_seq']: t['actor_id'] for t in stack.store.tasks('seat1')}
        assert actors[3] == 'omx2'
        # 같은 경로 표로 판정 국면도 자리 주문이다(경로의 customer 칸).
        assert stack.core._route(order)['customer'] == 'P22'
    finally:
        stack.close()


def test_stub_modules_are_removed_after_use(monkeypatch):
    import sys

    import cobot_anomaly_monitor as package
    before = {name: sys.modules.get(name) for name in ('rclpy', 'std_msgs.msg', 'node_stub')}
    had = hasattr(package, 'monitor_node')
    module = load_monitor_node(monkeypatch)
    assert sys.modules['rclpy'].__name__ == 'rclpy' and module.layout_routes
    monkeypatch.undo()
    assert {name: sys.modules.get(name) for name in before} == before
    assert hasattr(package, 'monitor_node') == had
    assert ('cobot_anomaly_monitor.monitor_node' in sys.modules) == had


@pytest.mark.parametrize('path', [DEV_CONFIG, SAKIM_CONFIG], ids=['monitor_dev', 'sakim'])
def test_dock_tolerance_comes_from_the_scenario_config(node_module, path):
    """노드가 추적표 정차 공차를 ConsoleApi 에 넘긴다(재검토 should_fix, S10·G6)."""
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert node_module.dock_tolerance_of(config) == {
        'dock_xy_m': config['dock_xy_m'], 'dock_yaw_deg': config['dock_yaw_deg']}
    assert node_module.dock_tolerance_of({'routes': {}}) is None
    assert node_module.dock_tolerance_of({'dock_xy_m': 0.05}) == {'dock_xy_m': 0.05}


def test_node_passes_the_dock_tolerance_to_the_console(node_module):
    import inspect
    source = inspect.getsource(node_module.AnomalyMonitorNode.__init__)
    assert 'self.dock_tolerance = dock_tolerance_of(scenario)' in source
    assert 'dock_tolerance=self.dock_tolerance' in source
