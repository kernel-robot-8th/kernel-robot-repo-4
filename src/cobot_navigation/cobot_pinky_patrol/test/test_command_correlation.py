"""실제 ROS 통신 없이 관제 ID가 작업 스레드 종료까지 유지되는지 확인한다."""

import importlib
import json
from pathlib import Path
import sys
import threading
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cobot_zone_traffic_control'))
if 'pinky_interfaces' not in sys.modules:
    stub = types.ModuleType('pinky_interfaces')
    stub.srv = types.ModuleType('pinky_interfaces.srv')
    stub.srv.SetLed = type('SetLed', (), {})
    sys.modules['pinky_interfaces'] = stub
    sys.modules['pinky_interfaces.srv'] = stub.srv


@pytest.fixture
def node():
    """하드웨어·DDS 없이 상태 발행과 작업 스레드만 사용한다."""
    cls = importlib.import_module('cobot_pinky_patrol.pinky_patrol_node').PinkyPatrolNode
    value = object.__new__(cls)
    value._command_context = threading.local()
    value._incoming_command_id = None
    value._running = False
    value.states = []
    value.status_pub = types.SimpleNamespace(
        publish=lambda message: value.states.append(json.loads(message.data)))
    value.get_logger = lambda: types.SimpleNamespace(
        error=lambda *_: None, warning=lambda *_: None)
    return value


def test_final_result_is_after_cleanup_with_same_id(node):
    """중간 DONE과 최종 응답을 구분하고 작업 ID는 메인 스레드와 분리한다."""
    def task():
        node.publish_status('DONE', -1, 'arrived')
        assert node._running
        assert node.states[-1]['task_finished'] is False

    node._incoming_command_id = 'job1'
    node._start_task(task)
    node._thread.join(timeout=2)
    assert not node._running
    assert node.states[-1]['command_id'] == 'job1'
    assert node.states[-1]['task_finished'] is True
    assert node.states[-1]['state'] == 'DONE'


def test_task_exception_has_final_correlated_failure(node):
    """스레드 예외가 무응답으로 남지 않는다."""
    def fail():
        raise RuntimeError('test failure')

    node._incoming_command_id = 'job1'
    node._start_task(fail)
    node._thread.join(timeout=2)
    assert node.states[-1]['state'] == 'FAILED'
    assert node.states[-1]['task_finished'] is True
    assert node.states[-1]['command_id'] == 'job1'


def test_busy_rejection_does_not_replace_active_context(node):
    """뒤늦은 다른 명령 거절은 원래 작업 ID에 영향을 주지 않는다."""
    node._running = True
    node._cmd_cb(types.SimpleNamespace(data=json.dumps(
        {'command_id': 'job2', 'command': 'goto:P1'})))
    assert node.states[-1]['command_id'] == 'job2'
    assert node.states[-1]['detail'] == 'robot busy'
    assert node.states[-1]['task_finished'] is True
    assert node._command_context.command_id is None
