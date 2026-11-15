"""ROS 설치 없이 실행할 수 있는 실제 ROS 어댑터의 회귀 검사."""

import ast
import json
from pathlib import Path
import threading
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def definitions(path, names, method=None):
    """제품 코드의 정의는 그대로 두고 ROS 가져오기만 제외해 컴파일한다."""
    module = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in module.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
             and n.name in names]
    if method:
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == method[0])
        nodes.append(next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                          and n.name == method[1]))
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')


def test_expired_zone_owner_is_retained_and_next_robot_cannot_enter():
    """시간 초과 정책을 복제하지 않고 실제 시간 초과 콜백을 시험한다."""
    path = ROOT / 'cobot_zone_traffic_control/cobot_zone_traffic_control/zone_manager_node.py'
    namespace = {'time': SimpleNamespace(time=lambda: 1000.0)}
    exec(definitions(path, {'ZoneQueue', 'ZoneState'},
                     ('ZoneManagerNode', '_check_timeout')), namespace)
    queue = namespace['ZoneQueue'](queue_max=3, stale_sec=5.0)
    queue.request('pinky1', 'owner', 0.0)
    queue.request('pinky2', 'waiting', 1000.0)
    zone = namespace['ZoneState']('A', queue, (0, 0, 0), (0, -1))
    released, warnings = [], []
    node = SimpleNamespace(
        _lock=threading.Lock(), zones={'A': zone}, max_hold_sec=240.0, advance_delay=1.0,
        get_logger=lambda: SimpleNamespace(warn=warnings.append),
        _after_release=lambda *args: released.append(args), _sync_slots_locked=lambda z: None)
    namespace['_check_timeout'](node)
    assert queue.occupant == 'pinky1'
    assert queue.request('pinky2', 'waiting', 1001.0) == ('queued',)
    assert released == []
    assert warnings


def test_patrol_heartbeat_cannot_replay_terminal_result():
    """생존 상태 발행으로 이전 명령이나 무관한 명령이 완료 처리되지 않아야 한다."""
    path = ROOT / 'cobot_pinky_patrol/cobot_pinky_patrol/pinky_patrol_node.py'
    namespace = {'time': SimpleNamespace(time=lambda: 1000.0), 'json': json,
                 'String': lambda **kwargs: SimpleNamespace(**kwargs)}
    exec(definitions(path, set(), ('PinkyPatrolNode', '_heartbeat')), namespace)
    sent = []
    node = SimpleNamespace(
        _last_status=dict(state='DONE', task_finished=True, command_id='old', boot_id='boot1'),
        controller=SimpleNamespace(command_id=None, held_zone='A', arrived_zone=None, busy=False),
        config={'central_controlled': True},
        central_guard=SimpleNamespace(expired=lambda busy=False: False, latched=False),
        status_pub=SimpleNamespace(publish=sent.append))
    namespace['_heartbeat'](node)
    status = json.loads(sent[0].data)
    assert status['task_finished'] is False
    assert status['command_id'] is None
    assert status['held_zone'] == 'A' and status['boot_id'] == 'boot1'
    assert status['arrived_zone'] is None


def test_command_path_check_blocks_duplicate_senders_but_not_watchers():
    """들여다보는(echo) 구독자는 막지 않고, 보내는 쪽이 둘이면 막는다 (2026-11-09)."""
    path = ROOT / 'cobot_fleet_control/cobot_fleet_control/fleet_control_node.py'
    namespace = {}
    exec(definitions(path, set(), ('FleetControlNode', 'ready')), namespace)
    ready = namespace['ready']

    def node(robot_subs=1, cmd_pubs=1, request_subs=1, tasks_pubs=1):
        counts = {'/pinky1/patrol_cmd': cmd_pubs, 'tasks': tasks_pubs}
        return SimpleNamespace(
            publishers_by_robot={'pinky1': SimpleNamespace(
                get_subscription_count=lambda: robot_subs)},
            config={'request_topic': 'requests', 'tasks_topic': 'tasks'},
            count_publishers=lambda topic: counts[topic],
            count_subscribers=lambda topic: request_subs)

    assert ready(node(), 'pinky1')
    assert ready(node(robot_subs=2), 'pinky1')          # ros2 topic echo 가 붙어도 보낸다
    assert not ready(node(robot_subs=0), 'pinky1')      # 로봇(브릿지) 연결이 없으면 안 보낸다
    assert not ready(node(cmd_pubs=2), 'pinky1')        # 명령을 보내는 쪽이 둘
    assert not ready(node(request_subs=2), 'pinky1')    # 요청을 받는 관제가 둘
    assert not ready(node(tasks_pubs=2), 'pinky1')
