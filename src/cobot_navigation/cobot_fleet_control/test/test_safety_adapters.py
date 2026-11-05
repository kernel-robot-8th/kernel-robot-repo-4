"""Actual ROS adapter regression checks runnable without a ROS installation."""

import ast
import json
from pathlib import Path
import threading
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def definitions(path, names, method=None):
    """Compile unchanged production definitions with only their ROS imports omitted."""
    module = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in module.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
             and n.name in names]
    if method:
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == method[0])
        nodes.append(next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                          and n.name == method[1]))
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')


def test_expired_zone_owner_is_retained_and_next_robot_cannot_enter():
    """Exercise the real timeout callback, not a duplicated timeout policy."""
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
    """A liveness publication must not complete an old or unrelated command."""
    path = ROOT / 'cobot_pinky_patrol/cobot_pinky_patrol/pinky_patrol_node.py'
    namespace = {'time': SimpleNamespace(time=lambda: 1000.0), 'json': json,
                 'String': lambda **kwargs: SimpleNamespace(**kwargs)}
    exec(definitions(path, set(), ('PinkyPatrolNode', '_heartbeat')), namespace)
    sent = []
    node = SimpleNamespace(
        _last_status=dict(state='DONE', task_finished=True, command_id='old', boot_id='boot1'),
        controller=SimpleNamespace(command_id=None, held_zone='A'),
        config={'central_controlled': True},
        central_guard=SimpleNamespace(expired=lambda: False, latched=False),
        status_pub=SimpleNamespace(publish=sent.append))
    namespace['_heartbeat'](node)
    status = json.loads(sent[0].data)
    assert status['task_finished'] is False
    assert status['command_id'] is None
    assert status['held_zone'] == 'A' and status['boot_id'] == 'boot1'
