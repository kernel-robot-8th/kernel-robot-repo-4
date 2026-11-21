"""
ROS 없이 monitor_node 의 순수 부분을 시험하려고 rclpy·메시지 모듈을 잠시 가짜로 바꿔 불러온다.

monkeypatch 로 바꾸므로 시험이 끝나면 sys.modules 와 패키지 속성이 원래대로 돌아간다.
노드 메서드는 가짜 self(SimpleNamespace)로 부른다. 실제 DDS 왕복은 test_judge_node·test_ros_roundtrip 이 맡는다.
"""

import functools
import importlib
import sys
import types

MODULE = 'cobot_anomaly_monitor.monitor_node'


class _Stub:
    def __init__(self, *args, **kwargs):
        pass


STUBS = {
    'ament_index_python': {},
    'ament_index_python.packages': {'get_package_share_directory': lambda name: name},
    'geometry_msgs': {}, 'geometry_msgs.msg': {'PoseWithCovarianceStamped': _Stub},
    'nav_msgs': {}, 'nav_msgs.msg': {'Odometry': _Stub},
    'rclpy': {'init': lambda **kw: None, 'try_shutdown': lambda: None},
    'rclpy.executors': {'ExternalShutdownException': Exception,
                        'SingleThreadedExecutor': _Stub},
    'rclpy.node': {'Node': _Stub},
    'rclpy.qos': {'DurabilityPolicy': _Stub, 'qos_profile_sensor_data': None,
                  'QoSProfile': _Stub},
    'rclpy.utilities': {'get_rmw_implementation_identifier': lambda: 'stub'},
    'std_msgs': {}, 'std_msgs.msg': {'Float32': _Stub, 'String': _Stub},
}


def load_monitor_node(monkeypatch):
    """가짜 ROS 모듈로 monitor_node 를 새로 불러온다."""
    import cobot_anomaly_monitor as package
    for name, attrs in STUBS.items():
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    # 원래 상태(없음 또는 실제 모듈)를 기록해 두고 비운 뒤 새로 불러온다.
    monkeypatch.setitem(sys.modules, MODULE, None)
    monkeypatch.setattr(package, 'monitor_node', None, raising=False)
    del sys.modules[MODULE]
    delattr(package, 'monitor_node')
    return importlib.import_module(MODULE)


class Logger:
    def __init__(self):
        self.lines = []

    def info(self, text):
        self.lines.append(('info', text))

    def warning(self, text):
        self.lines.append(('warning', text))

    def error(self, text):
        self.lines.append(('error', text))


def fake_node(module, **attrs):
    """노드 메서드를 가짜 self 에 묶는다. attrs 로 core·store·config 등을 넣는다."""
    logger = Logger()
    node = types.SimpleNamespace(get_logger=lambda: logger, logger=logger, **attrs)
    cls = module.AnomalyMonitorNode
    for name in ('_decode', '_warn_arm_node', '_work_request', '_update_arm_nodes',
                 '_check_adapter'):
        setattr(node, name, functools.partial(getattr(cls, name), node))
    return node
