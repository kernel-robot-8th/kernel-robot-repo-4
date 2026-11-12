"""중계 장비의 기록·판정 노드. patrol_cmd는 발행하지 않고 관제 요청 토픽만 쓴다."""

from concurrent.futures import Future
import json
import math
import os
from pathlib import Path
import queue
import time

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, qos_profile_sensor_data, QoSProfile
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import String
import yaml

from .console_api import ConsoleApi, serve
from .manual_adapter import ManualAdapter
from .monitor_core import camera_allowed, MonitorCore
from .monitor_store import MonitorStore

REPLY_WAIT_SEC = 3.0
ADAPTER_CHECK_SEC = 2.0


def load_points(path):
    """순찰 지점 파일에서 좌표만 읽는다."""
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    return data['pinky_patrol_node']['ros__parameters']['points']


def yaw_of(orientation):
    """쿼터니언에서 평면 방향을 구한다."""
    return math.atan2(2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
                      1.0 - 2.0 * (orientation.y ** 2 + orientation.z ** 2))


class AnomalyMonitorNode(Node):
    """저장소는 실행기 스레드에서만 만지고 HTTP 스레드는 작업 큐로 넘긴다."""

    def __init__(self):
        super().__init__('anomaly_monitor')
        share = Path(get_package_share_directory('cobot_anomaly_monitor'))
        patrol = Path(get_package_share_directory('cobot_pinky_patrol'))
        defaults = {
            'robot_ids': ['pinky1', 'pinky2', 'pinky3'],
            'db_path': '~/.cobot/anomaly_monitor.sqlite3',
            'scenario_config': str(share / 'config/scenario_relay_dev.yaml'),
            'site_config': str(patrol / 'config/sites/lab.yaml'),
            'cctv_control_mode': 'OBSERVE_ONLY',
            'console_host': '127.0.0.1', 'console_port': 8083,
            'manual_adapter': True,
            'manual_targets': ['vision', 'navigation', 'omx1', 'omx2', 'omx3'],
            'allow_mock_events': True,
            'console_commands': False,
            'camera_policy': 'field',
            'event_topic': '/anomaly_monitor/vision_event',
            'request_topic': '/control_center/task_request',
            'events_topic': '/control_center/task_events',
            'tasks_topic': '/control_center/tasks',
            'work_request_topic': '/fleet/work_request',
            'work_result_topic': '/fleet/work_result',
            'heartbeat_topic': '/fleet/heartbeat',
            'zone_status_topic': '/zone_manager/status',
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        self.config = config
        camera_allowed('', config['camera_policy'])
        routes = yaml.safe_load(
            Path(config['scenario_config']).read_text(encoding='utf-8'))['routes']
        self.store = MonitorStore(config['db_path'])
        self.request_pub = self.create_publisher(String, config['request_topic'], 50)
        self.points = load_points(config['site_config'])
        self.core = MonitorCore(self.store, routes, config['robot_ids'], self._send_request,
                                config['cctv_control_mode'], points=self.points)
        self.core.ros = {'domain_id': os.environ.get('ROS_DOMAIN_ID', '0'),
                         'rmw': get_rmw_implementation_identifier()}
        self.adapter = self._create_adapter() if config['manual_adapter'] else None
        self.jobs = queue.Queue()
        self.console = ConsoleApi(self.core, self.adapter, self._run, self._wait_reply,
                                  config['allow_mock_events'],
                                  commands=config['console_commands'])
        for robot in config['robot_ids']:
            self.create_subscription(String, f'/{robot}/patrol_status',
                                     lambda m, r=robot: self._status(r, m), 10)
            # 브리지가 맞춘 QoS와 상관없이 받도록 best effort로 구독한다.
            self.create_subscription(PoseWithCovarianceStamped, f'/{robot}/amcl_pose',
                                     lambda m, r=robot: self._pose(r, m),
                                     qos_profile_sensor_data)
            self.create_subscription(Odometry, f'/{robot}/odom',
                                     lambda m, r=robot: self._odom(r, m),
                                     qos_profile_sensor_data)
        self.create_subscription(
            String, config['tasks_topic'], self._tasks,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(String, config['events_topic'], self._task_event, 50)
        self.create_subscription(String, config['event_topic'], self._vision, 50)
        self.create_subscription(String, config['zone_status_topic'],
                                 lambda m: self.core.on_zone_status(m.data), 10)
        self.create_timer(0.02, self._drain)
        self.create_timer(1.0, self._refresh)
        self.console.refresh()
        self.server = serve(self.console, config['console_host'], config['console_port'])
        self.get_logger().info(
            f'이상 감지 기록 시작: {self.core.mode}, 콘솔 '
            f"{config['console_host']}:{config['console_port']}")

    def _create_adapter(self):
        config = self.config
        self.result_pub = self.create_publisher(String, config['work_result_topic'], 50)
        adapter = ManualAdapter(self.store, self._publish_result, config['manual_targets'],
                                self.points, self.core._robot_view)
        adapter.blocked = '기동 검사 전'
        self.create_subscription(String, config['heartbeat_topic'], self._heartbeat, 10)
        self.create_subscription(String, config['work_request_topic'], self._work_request, 50)
        self.adapter_check = self.create_timer(ADAPTER_CHECK_SEC, self._check_adapter)
        return adapter

    def _check_adapter(self):
        """다른 어댑터와 함께 돌면 같은 요청에 답이 둘 나가므로 답하지 않는다."""
        self.adapter_check.cancel()
        count = self.count_publishers(self.config['work_result_topic'])
        self.adapter.blocked = f'work_result 발행자 {count}개' if count > 1 else ''
        if self.adapter.blocked:
            self.get_logger().error('수동 어댑터 꺼짐: ' + self.adapter.blocked)

    def _send_request(self, payload):
        self.request_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _publish_result(self, result):
        self.result_pub.publish(String(data=json.dumps(result, ensure_ascii=False)))

    def _run(self, job):
        """HTTP 스레드의 작업을 실행기 스레드에서 돌리고 결과를 기다린다."""
        future = Future()
        self.jobs.put((job, future))
        return future.result(timeout=REPLY_WAIT_SEC)

    def _drain(self):
        while True:
            try:
                job, future = self.jobs.get_nowait()
            except queue.Empty:
                return
            try:
                future.set_result(job())
            except Exception as error:
                future.set_exception(error)

    def _wait_reply(self, request_id):
        deadline = time.monotonic() + REPLY_WAIT_SEC
        while time.monotonic() < deadline:
            reply = self.core.replies.get(request_id)
            if reply is not None:
                return reply
            time.sleep(0.02)
        return None

    def _link(self, topic):
        return {'publishers': self.count_publishers(topic),
                'subscribers': self.count_subscribers(topic)}

    def _read_graph(self):
        """토픽 연결 수와 scan 발행 QoS를 읽는다. 데이터를 구독하지 않는다."""
        robots = {}
        for robot in self.config['robot_ids']:
            scan = f'/{robot}/scan'
            robots[robot] = {name: self._link(f'/{robot}/{name}')
                             for name in ('patrol_cmd', 'patrol_status', 'amcl_pose', 'odom')}
            robots[robot]['scan'] = dict(self._link(scan), reliability=sorted({
                info.qos_profile.reliability.name
                for info in self.get_publishers_info_by_topic(scan)}))
        return {'request': self._link(self.config['request_topic']),
                'tasks': self._link(self.config['tasks_topic']), 'robots': robots}

    def _refresh(self):
        self.core.graph = self._read_graph()
        self.core.flush()
        self.console.refresh()

    def _decode(self, message, label):
        try:
            data = json.loads(message.data)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self.get_logger().warning(f'{label} 무시: JSON 객체 아님')
            return None
        return data

    def _status(self, robot, message):
        status = self._decode(message, '순찰 상태')
        if status is not None:
            self.core.on_status(robot, status)

    def _pose(self, robot, message):
        pose = message.pose.pose
        self.core.on_pose(robot, pose.position.x, pose.position.y, yaw_of(pose.orientation))

    def _odom(self, robot, message):
        linear = message.twist.twist.linear
        self.core.on_speed(robot, math.hypot(linear.x, linear.y))

    def _tasks(self, message):
        snapshot = self._decode(message, '관제 스냅샷')
        if snapshot is not None:
            self.core.on_tasks(snapshot)

    def _task_event(self, message):
        event = self._decode(message, '관제 이벤트')
        if event is not None:
            self.core.on_task_event(event)

    def _vision(self, message):
        event = self._decode(message, '이상 이벤트')
        if event is None:
            return
        if not camera_allowed(event.get('camera_id', ''), self.config['camera_policy']):
            self.get_logger().warning(f"이상 이벤트 거절: 카메라 {event.get('camera_id')}")
            return
        try:
            row = self.core.on_vision_event(event)
            self.get_logger().info(f"판정 {row['judgment']} 조치 {row['control_action']}")
        except ValueError as error:
            self.get_logger().warning(f'이상 이벤트 무시: {error}')

    def _heartbeat(self, message):
        heartbeat = self._decode(message, '관제 심박')
        if heartbeat is not None:
            self.adapter.on_heartbeat(heartbeat)

    def _work_request(self, message):
        request = self._decode(message, '작업 요청')
        if request is not None:
            self.adapter.on_request(request)

    def destroy_node(self):
        """HTTP를 먼저 멈춘 뒤 저장소를 닫는다."""
        try:
            self.server.shutdown()
        except KeyboardInterrupt:
            # Ctrl-C는 터미널과 launch에서 두 번 온다.
            pass
        finally:
            self.store.close()
        return super().destroy_node()


def main(args=None):
    """기록 노드를 시작한다."""
    rclpy.init(args=args)
    node = AnomalyMonitorNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
