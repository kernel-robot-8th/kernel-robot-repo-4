# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
관제 백엔드 노드: /control_center/fleet_status 를 받아 웹 API(HTTP·WebSocket)로 내보낸다.

로봇 토픽에는 발행하지 않는다. 상세 화면 직접 조종도 /control_center/teleop_cmd 로 teleop_node 에 넘기고,
cmd_vel 은 그 노드가 낸다. 구독하는 로봇 토픽은 카메라 영상(sensor_msgs/CompressedImage)뿐이다.
영상은 커서 fleet_status JSON 에 싣지 않고, 받은 JPEG 를 풀지 않은 채 웹으로 바로 넘긴다.
그 밖에 받는 것은 fleet_status_node 가 낸 스냅샷과 작업 노드(cobot_fleet_control 의 fleet_control_node)의
작업 목록·응답이다. 명령은 /control_center/task_request 로 작업 노드에 넘길 뿐이고,
로봇 명령 토픽에 내는 것은 작업 노드다. 로봇팔 켜기·끄기·정지도 같은 방식으로
/control_center/arm_request 를 로봇팔 명령 노드(arm_command_node)에 넘기고, ArmCommand 는 그 노드가 낸다.
rclpy 는 백그라운드 스레드에서, uvicorn 은 메인 스레드에서 돈다. uvicorn 이 Ctrl+C 를 받아
웹 서버를 먼저 닫고, 그 뒤 ROS 를 정리한다.
"""

import contextlib
import json
import os
import socket
import threading
import time

from ament_index_python.packages import get_package_share_directory
from cobot_control_center.cctv_relay import CctvRelay
from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import (
    ArmStore, CameraStore, LayerError, load_map, load_map_layers, MapError, SnapshotStore,
    TaskStore)
from cobot_control_center.net_status_utils import (
    collect_network, HostStore, local_info, NetAlertTracker, NetStore, network_alerts)
from cobot_control_center.route_utils import RouteRunner
from cobot_control_center.site_arms_utils import load_site_arms
from cobot_control_center.teleop_utils import TeleopStore
from cobot_control_center.waypoint_utils import WaypointStore
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
import uvicorn


class FleetApiNode(Node):
    """fleet_status 스냅샷을 SnapshotStore 에 넣는다. 웹 서버 설정은 파라미터로 받는다."""

    def __init__(self):
        super().__init__('fleet_api_node')
        self.declare_parameter('host', '127.0.0.1')
        self.declare_parameter('port', 8080)
        self.declare_parameter('source_stale_sec', 3.0)
        self.declare_parameter('map_yaml', '')
        self.declare_parameter('web_dir', '')
        self.declare_parameter('points_dir', '')
        self.declare_parameter('site', 'lab')
        self.declare_parameter('zone_params', '')
        self.declare_parameter('events_max', 500)
        self.declare_parameter('task_stale_sec', 3.0)
        self.declare_parameter('reply_timeout_sec', 2.0)
        self.declare_parameter('arm_stale_sec', 3.0)
        self.declare_parameter('arm_reply_timeout_sec', 10.0)
        self.declare_parameter('arm_events_max', 300)
        self.declare_parameter('camera_robots', ['pinky1', 'pinky2', 'pinky3'])
        self.declare_parameter('camera_topic_format', '/{robot}/camera/image_raw/compressed')
        # 개발용(fleet_api_dev.launch.xml): 실물을 보면서 화면을 고칠 때 명령이 나가지 않게 한다.
        self.declare_parameter('read_only', False)
        self.read_only = bool(self.get_parameter('read_only').value)
        self.host = self.get_parameter('host').value
        self.port = int(self.get_parameter('port').value)
        self.store = SnapshotStore(self.get_parameter('source_stale_sec').value,
                                   events_max=self.get_parameter('events_max').value)
        self.map_data = self._load_map(self.get_parameter('map_yaml').value)
        self.layers = self._load_layers(self.get_parameter('points_dir').value,
                                        self.get_parameter('zone_params').value,
                                        self.get_parameter('site').value)
        self.web_dir = (self.get_parameter('web_dir').value
                        or os.path.join(get_package_share_directory('cobot_control_center'),
                                        'web'))
        self.create_subscription(String, '/control_center/fleet_status', self._on_fleet, 10)

        # 작업 노드(fleet_control_node)와 같은 QoS. 목록은 transient_local 이라 늦게 켜져도 마지막 값을 받는다.
        self.tasks = TaskStore(self.get_parameter('task_stale_sec').value,
                               self.get_parameter('reply_timeout_sec').value)
        command_qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        # 읽기 전용이면 요청 발행자를 아예 만들지 않는다 (작업 목록·이벤트는 그대로 받는다).
        self.request_pub = None if self.read_only else self.create_publisher(
            String, '/control_center/task_request', command_qos)
        self.create_subscription(String, '/control_center/task_events', self._on_task_event,
                                 command_qos)
        self.create_subscription(
            String, '/control_center/tasks', self._on_tasks,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))

        # 로봇팔 명령 노드(arm_command_node). 상태 모음은 transient_local 이라 늦게 켜져도 마지막 값을 받는다.
        self.arms = ArmStore(self.get_parameter('arm_stale_sec').value,
                             self.get_parameter('arm_reply_timeout_sec').value,
                             events_max=self.get_parameter('arm_events_max').value)
        self.arm_request_pub = None if self.read_only else self.create_publisher(
            String, '/control_center/arm_request', command_qos)
        self.create_subscription(String, '/control_center/arm_events', self._on_arm_event,
                                 command_qos)
        self.create_subscription(
            String, '/control_center/arms', self._on_arms,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        # 경로(여러 지점 연결 주행): 앞 구간이 끝나면 다음 구간을 작업 노드에 낸다.
        # 요청 응답을 기다리며 막히므로 ROS executor 가 아닌 따로 된 스레드에서 돈다 (main 에서 start).
        self.declare_parameter('route_retry_sec', 8.0)
        self.declare_parameter('route_period_sec', 0.5)
        self.routes = None if self.read_only else RouteRunner(
            lambda payload: self.tasks.request(payload, self.publish_request), self.tasks.task,
            retry_sec=self.get_parameter('route_retry_sec').value,
            on_event=self.store.add_events)
        # 상세 화면 직접 조종 (teleop_node). 읽기 전용이면 입력 발행자를 만들지 않는다.
        self.declare_parameter('teleop_stale_sec', 2.0)
        self.teleop = TeleopStore(self.get_parameter('teleop_stale_sec').value)
        self.teleop_pub = None if self.read_only else self.create_publisher(
            String, '/control_center/teleop_cmd', command_qos)
        self.create_subscription(
            String, '/control_center/teleop_state', self._on_teleop,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        # 관제 웨이포인트·묶음 (관제 PC 파일). 비우면 ~/.ros/cobot_control_center/waypoints_<site>_d<도메인>.json
        # 도메인을 이름에 넣어 가짜 핑키(101)·시뮬(140)에서 저장한 점이 실물(100) 파일에 섞이지 않게 한다.
        self.declare_parameter('waypoints_file', '')
        self.declare_parameter('zone_keepout_m', 0.0)   # 0 = 검사 안 함
        self.declare_parameter('wall_warn_m', 0.15)
        site = self.get_parameter('site').value
        path = (self.get_parameter('waypoints_file').value
                or f'~/.ros/cobot_control_center/waypoints_{site}'
                   f'_d{self.context.get_domain_id()}.json')
        self.waypoints = WaypointStore(path, site, self.layers,
                                       self.get_parameter('zone_keepout_m').value,
                                       map_data=self.map_data,
                                       wall_warn_m=self.get_parameter('wall_warn_m').value)
        if self.waypoints.load_error:
            self.get_logger().error(self.waypoints.load_error + ' (저장은 막음)')
        self.get_logger().info(
            f'웨이포인트: {self.waypoints.path} ({len(self.waypoints.poses())}개)')
        self.cameras = self._subscribe_cameras()
        self.cctv = self._setup_cctv()
        self.arm_videos = self._setup_arm_videos()
        self._setup_network()
        self.get_logger().info(
            f'fleet_api_node 시작: 화면 http://{self.host}:{self.port}/ '
            + ('(읽기 전용: 명령 경로 503, task_request 를 내지 않음)' if self.read_only
               else '(로봇 토픽에 발행하지 않음. 명령은 작업 노드 fleet_control_node 로 넘김)'))

    def _subscribe_cameras(self):
        # 비전 시험 발행기(cobot_camera_topic_test)와 같은 QoS. 지난 프레임은 다시 받지 않고 최신 1장만 본다.
        # BEST_EFFORT 구독은 RELIABLE 발행자와도 연결된다.
        robots = [r for r in self.get_parameter('camera_robots').value if r]
        topic_format = self.get_parameter('camera_topic_format').value
        qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                         reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        cameras = CameraStore(robots)
        topics = []
        for robot in robots:
            topic = topic_format.format(robot=robot)
            self.create_subscription(
                CompressedImage, topic,
                lambda msg, robot=robot: cameras.put(robot, msg.data), qos)
            topics.append(topic)
        self.get_logger().info(f'카메라 구독: {", ".join(topics) or "없음"}')
        return cameras

    def _setup_cctv(self):
        # 현장영상(천장 CCTV): 유선망 장치의 MJPEG 을 받아 /api/cctv 로 다시 낸다. 주소가 비면 끈다.
        self.declare_parameter('cctv_url', '')
        self.declare_parameter('cctv_idle_sec', 10.0)
        self.declare_parameter('cctv_reconnect_sec', 2.0)
        self.declare_parameter('cctv_timeout_sec', 5.0)
        url = self.get_parameter('cctv_url').value
        if not url:
            self.get_logger().info('현장영상: 끔 (cctv_url 비어 있음)')
            return None
        self.get_logger().info(f'현장영상: {url} (보는 사람이 있을 때만 연결)')
        return CctvRelay(url,
                         idle_sec=float(self.get_parameter('cctv_idle_sec').value),
                         reconnect_sec=float(self.get_parameter('cctv_reconnect_sec').value),
                         timeout_sec=float(self.get_parameter('cctv_timeout_sec').value))

    def _setup_arm_videos(self):
        # 팔 카메라: 팔 실행기(omx_fleet cam_preview)의 MJPEG 을 받아 /api/arms/<팔>/camera/<역할> 로 다시 낸다.
        # 주소는 현장 팔 배치(site_arms.yaml) 의 video. 보는 사람이 있을 때만 붙으므로 미리 만들어도 부담이 없다.
        # 연결 시간 값은 현장영상(cctv_*)과 같은 것을 쓴다.
        self.declare_parameter('site_arms_file', '')
        self.declare_parameter('arm_video_roles', ['top', 'wrist'])
        path = self.get_parameter('site_arms_file').value
        if not path:
            self.get_logger().info('팔 카메라: 끔 (site_arms_file 비어 있음)')
            return {}
        try:
            site = load_site_arms(path)
        except ValueError as error:
            self.get_logger().error(f'팔 카메라: 현장 팔 배치를 읽지 못함 ({path}): {error}')
            return {}
        roles = [r for r in self.get_parameter('arm_video_roles').value if r]
        timing = {key: float(self.get_parameter(f'cctv_{key}').value)
                  for key in ('idle_sec', 'reconnect_sec', 'timeout_sec')}
        videos = {}
        for arm_id, info in site.items():
            if info['video']:
                videos[arm_id] = {role: CctvRelay(f'{info["video"]}/{role}', **timing)
                                  for role in roles}
        self.get_logger().info(
            '팔 카메라: ' + (', '.join(f'{a}={site[a]["video"]}' for a in videos) or '주소 없음')
            + ' (보는 사람이 있을 때만 연결)')
        return videos

    def _setup_network(self):
        # 네트워크 화면(#/network): 측정 노드(net_status_node) 값 + 이 PC 의 DDS·노드 목록.
        # 노드 목록은 그래프 조회라 웹 요청마다 하지 않고 ROS 스레드에서 2초마다 새로 둔다.
        self.declare_parameter('net_stale_sec', 3.0)
        self.declare_parameter('network_robots', ['pinky1', 'pinky2', 'pinky3'])
        self.declare_parameter('network_arms', ['omx_1', 'omx_2', 'omx_3'])
        self.declare_parameter('net_status_topic', '/control_center/net_status')
        self.declare_parameter('net_check_topic', '/control_center/net_check')
        # Station PC 에서 도는 노드 이름 (팔 노드 arm_station.launch.xml 의 omx1_adapter 등).
        # ROS 그래프는 노드가 어느 PC 에 있는지 모르므로 이름으로 고른다.
        self.declare_parameter('station_node_patterns', ['omx*_adapter'])
        self.station_patterns = [p for p in self.get_parameter('station_node_patterns').value
                                 if p]
        # 영상 분석·이상 감지 경로 노드 (천장 카메라 YOLO → MQTT → 수신기 → anomaly_monitor)
        self.declare_parameter('vision_node_patterns', ['mqtt_zone_evidence', 'anomaly_monitor'])
        self.vision_patterns = [p for p in self.get_parameter('vision_node_patterns').value if p]
        # YOLO 는 ROS 를 쓰지 않아 어느 PC 에서 도는지 관제가 모른다. 화면에 적을 글자.
        self.declare_parameter('vision_pc_label', '')
        self.vision_label = self.get_parameter('vision_pc_label').value or None
        # 자세히 확인 요청. 로봇 명령이 아니라 측정 노드가 10초 동안 촘촘히 재게 할 뿐이라 읽기 전용에서도 둔다.
        self.net_check_pub = self.create_publisher(
            String, self.get_parameter('net_check_topic').value,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        self.net = NetStore(self.get_parameter('net_stale_sec').value)
        # 다른 PC 의 상태 보고 (host_status_node, Station PC 등). PC 마다 host 로 나눈다.
        self.declare_parameter('host_status_topic', '/control_center/host_status')
        self.declare_parameter('host_stale_sec', 10.0)
        self.hosts = HostStore(self.get_parameter('host_stale_sec').value)
        self.create_subscription(
            String, self.get_parameter('host_status_topic').value, self._on_host,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        self.network_ids = ([r for r in self.get_parameter('network_robots').value if r],
                            [a for a in self.get_parameter('network_arms').value if a])
        self.create_subscription(
            String, self.get_parameter('net_status_topic').value, self._on_net,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self._local = None
        self._refresh_local()
        self.create_timer(2.0, self._refresh_local)
        # 네트워크·PC 경고가 생기고 풀릴 때 이벤트 로그에 남긴다 (네트워크 화면을 안 열어도 남게).
        self._alerts = NetAlertTracker()
        self.create_timer(2.0, self._track_net_alerts)

    def _track_net_alerts(self):
        view = collect_network(self.store, self.tasks, self.arms, self.net, self.hosts,
                               self._local, self.context.get_domain_id(), self.network_ids,
                               cctv=self.cctv, vision_label=self.vision_label)
        events = self._alerts.update(network_alerts(view), time.time())
        if events:
            self.store.add_events(events)

    def _refresh_local(self):
        names = [name for name, _ in self.get_node_names_and_namespaces()]
        self._local = local_info(rclpy.get_rmw_implementation_identifier(),
                                 self.context.get_domain_id(), os.environ, names,
                                 self.station_patterns, self.vision_patterns,
                                 socket.gethostname())

    def local_network(self):
        """웹 서버 스레드에서 부른다. 마지막으로 새로 둔 이 PC 정보 (dict 를 통째로 바꾸므로 잠금 없음)."""
        return self._local

    def request_net_check(self, source):
        """웹 서버 스레드에서 부른다. 측정 노드에 자세히 확인을 요청한다."""
        self.net_check_pub.publish(String(data=json.dumps({'source': source})))

    def _on_host(self, msg):
        if not self.hosts.put(msg.data):
            self.get_logger().warning('PC 상태 보고(host_status)를 읽지 못함')

    def _on_net(self, msg):
        if not self.net.put(msg.data):
            self.get_logger().warning('네트워크 측정값(net_status)을 읽지 못함')

    def _load_map(self, path):
        # 지도가 없어도 카드·구역 화면은 쓸 수 있으므로 경고만 하고 계속한다.
        if not path:
            self.get_logger().warning('map_yaml 이 비어 있음: 지도 없이 시작')
            return None
        try:
            info, _ = data = load_map(path)
        except MapError as error:
            self.get_logger().warning(f'{error}: 지도 없이 시작')
            return None
        self.get_logger().info(f'지도: {path} ({info["image_width"]}x{info["image_height"]}, '
                               f'{info["resolution"]} m/px)')
        return data

    def _load_layers(self, points_dir, zone_params, site):
        # 구역 표시는 덧그림이라 없어도 화면은 쓸 수 있다. 경고만 하고 계속한다.
        if not points_dir or not zone_params:
            self.get_logger().warning('points_dir·zone_params 가 비어 있음: 구역 표시 없이 시작')
            return None
        try:
            layers = load_map_layers(points_dir, zone_params, site)
        except LayerError as error:
            self.get_logger().warning(f'{error}: 구역 표시 없이 시작')
            return None
        for warning in layers['warnings']:
            self.get_logger().warning(f'구역 설정: {warning}')
        self.get_logger().info(f'구역 표시: {", ".join(layers["zones"]) or "없음"} '
                               f'(홈 {len(layers["homes"])}개, 일반 지점 {len(layers["points"])}개, '
                               f'예비값 {layers["hidden_points"]}개 숨김)')
        return layers

    def _on_fleet(self, msg):
        if not self.store.put(msg.data):
            self.get_logger().warning('fleet_status 를 읽지 못함 (JSON 객체가 아님)')

    def _on_tasks(self, msg):
        if not self.tasks.put_snapshot(msg.data):
            self.get_logger().warning('작업 목록(/control_center/tasks)을 읽지 못함')
            return
        # 주문 단계 변화는 핑키 이벤트 기록에 함께 남긴다 (/api/events·WebSocket 에 그대로 보임).
        self.store.add_events(self.tasks.take_events())

    def _on_task_event(self, msg):
        if not self.tasks.put_event(msg.data):
            self.get_logger().warning('작업 이벤트(/control_center/task_events)를 읽지 못함')

    def _on_arms(self, msg):
        if not self.arms.put_snapshot(msg.data):
            self.get_logger().warning('로봇팔 상태(/control_center/arms)를 읽지 못함')

    def _on_arm_event(self, msg):
        if not self.arms.put_event(msg.data):
            self.get_logger().warning('로봇팔 응답(/control_center/arm_events)을 읽지 못함')

    def publish_request(self, text):
        """웹 서버 스레드에서 부른다. 요청 JSON 을 작업 노드에 넘긴다."""
        self.request_pub.publish(String(data=text))

    def _on_teleop(self, msg):
        if not self.teleop.put_state(msg.data):
            self.get_logger().warning('조종 노드 상태(/control_center/teleop_state)를 읽지 못함')

    def publish_teleop(self, text):
        """웹 서버 스레드에서 부른다. 조종 입력 JSON 을 teleop_node 에 넘긴다."""
        self.teleop_pub.publish(String(data=text))

    def publish_arm_request(self, text):
        """웹 서버 스레드에서 부른다. 요청 JSON 을 로봇팔 명령 노드에 넘긴다."""
        self.arm_request_pub.publish(String(data=text))


def main(args=None):
    # Ctrl+C 는 uvicorn 이 받아 서버를 닫게 하고, rclpy 의 신호 처리기는 쓰지 않는다.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = FleetApiNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    if node.routes is not None:
        node.routes.start(float(node.get_parameter('route_period_sec').value))
    try:
        # 시작·종료 이벤트를 쓰지 않는다. lifespan 을 켜 두면 uvicorn 이 종료 뒤 Ctrl+C 를 다시
        # 일으킬 때 남은 lifespan 작업이 CancelledError 트레이스백을 남긴다.
        app = create_app(node.store, node.map_data, node.web_dir,
                         node.context.get_domain_id(), node.layers,
                         node.tasks, None if node.read_only else node.publish_request,
                         node.cameras, node.arms,
                         None if node.read_only else node.publish_arm_request,
                         net=node.net, local_network=node.local_network,
                         network_ids=node.network_ids,
                         request_net_check=node.request_net_check, hosts=node.hosts,
                         routes=node.routes, teleop=node.teleop,
                         publish_teleop=None if node.read_only else node.publish_teleop,
                         waypoints=node.waypoints, cctv=node.cctv,
                         vision_label=node.vision_label, arm_videos=node.arm_videos)
        uvicorn.run(app, host=node.host, port=node.port,
                    log_level='info', lifespan='off')
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        with contextlib.suppress(KeyboardInterrupt):
            if node.routes is not None:
                node.routes.shutdown()
            if node.cctv is not None:
                node.cctv.shutdown()
            for roles in node.arm_videos.values():
                for relay in roles.values():
                    relay.shutdown()
            executor.shutdown()
            node.destroy_node()
            rclpy.try_shutdown()
            spinner.join(timeout=2.0)
