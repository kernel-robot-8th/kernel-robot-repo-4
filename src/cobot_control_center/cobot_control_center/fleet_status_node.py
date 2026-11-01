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
읽기 전용 관제 노드: 로봇 상태를 모아 /control_center/fleet_status 로 내보낸다.

관제 PC(ROS_DOMAIN_ID=100)에서 domain_bridge 가 넘겨 준 토픽을 구독만 한다.
로봇 토픽(/pinkyN/*, /zone_manager/*)에는 발행하지 않으므로 로봇을 움직이지 않는다.
로직은 fleet_status_utils 에 있고, 이 파일은 구독·타이머만 둔다.
"""

import contextlib
import json
import time

from cobot_control_center.fleet_status_utils import FleetState, judge_infra, yaw_from_quaternion
from geometry_msgs.msg import PoseWithCovarianceStamped
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, String


class FleetStatusNode(Node):
    """로봇별 순찰 상태·위치·배터리와 구역 상태를 모아 주기적으로 발행한다."""

    def __init__(self):
        super().__init__('fleet_status_node')
        self.declare_parameter('robots', ['pinky1', 'pinky2', 'pinky3'])
        self.declare_parameter('stale_timeout_sec', 3.0)
        self.declare_parameter('publish_period_sec', 1.0)
        self.declare_parameter('control_domain_id', 100)
        self.declare_parameter('bridge_node_format', 'pinky_bridge_{robot}_only_{domain}')
        self.declare_parameter('mock_node_name', 'mock_pinky_node')
        self.declare_parameter('teach_max_std_xy', 0.05)
        self.declare_parameter('teach_max_std_yaw', 0.1)
        self.declare_parameter('battery_warn_percent', 20.0)
        self.declare_parameter('stuck_sec', 15.0)
        self.declare_parameter('stuck_distance_m', 0.05)
        self.declare_parameter('zone_hold_warn_sec', 200.0)
        robots = list(self.get_parameter('robots').value)
        stale = self.get_parameter('stale_timeout_sec').value
        period = self.get_parameter('publish_period_sec').value

        self.fleet = FleetState(robots, stale,
                                self.get_parameter('teach_max_std_xy').value,
                                self.get_parameter('teach_max_std_yaw').value,
                                self.get_parameter('battery_warn_percent').value,
                                self.get_parameter('stuck_sec').value,
                                self.get_parameter('stuck_distance_m').value,
                                self.get_parameter('zone_hold_warn_sec').value)
        self._last_online = {name: False for name in robots}
        self._last_state = {name: None for name in robots}

        # 기반 노드 확인용. 도메인은 환경 변수가 아니라 이 노드가 실제로 붙은 값을 쓴다.
        self._domain_id = self.context.get_domain_id()
        self._control_domain_id = self.get_parameter('control_domain_id').value
        self._mock_node_name = self.get_parameter('mock_node_name').value
        bridge_format = self.get_parameter('bridge_node_format').value
        self._bridge_names = {name: bridge_format.format(robot=name, domain=self._domain_id)
                              for name in robots}
        self._last_infra = None

        # zone_manager 와 같은 설정이어야 상태 메시지를 놓치지 않는다.
        reliable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                              history=HistoryPolicy.KEEP_LAST)
        for name in robots:
            self.create_subscription(
                String, f'/{name}/patrol_status',
                lambda msg, r=name: self._on_status(r, msg), reliable)
            # 위치·배터리는 best effort 로 받는다. 브릿지가 어떤 QoS 로 내보내도 연결된다.
            self.create_subscription(
                PoseWithCovarianceStamped, f'/{name}/amcl_pose',
                lambda msg, r=name: self._on_pose(r, msg), qos_profile_sensor_data)
            self.create_subscription(
                Float32, f'/{name}/battery/percent',
                lambda msg, r=name: self._on_battery(r, msg), qos_profile_sensor_data)
        self.create_subscription(String, '/zone_manager/status', self._on_zone, reliable)

        self.pub = self.create_publisher(String, '/control_center/fleet_status', 10)
        self.create_timer(period, self._publish)
        self.get_logger().info(
            f'fleet_status_node 시작 (robots={robots}, stale_timeout_sec={stale}, '
            f'publish_period_sec={period}). 구독만 하고 로봇 토픽에는 발행하지 않는다.')

    def _on_status(self, robot, msg):
        if not self.fleet.update_status(robot, msg.data, time.time()):
            self.get_logger().warning(f'{robot}: patrol_status 를 읽지 못함: {msg.data!r}')
            return
        state = self.fleet.robots[robot].status.get('state')
        if state != self._last_state[robot]:
            self._last_state[robot] = state
            self.get_logger().info(f'{robot}: state={state}')

    def _on_pose(self, robot, msg):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        self.fleet.update_pose(robot, p.x, p.y, yaw_from_quaternion(q.x, q.y, q.z, q.w),
                               time.time(), msg.pose.covariance)

    def _on_battery(self, robot, msg):
        self.fleet.update_battery(robot, msg.data, time.time())

    def _on_zone(self, msg):
        if not self.fleet.update_zone(msg.data, time.time()):
            self.get_logger().warning(f'zone_manager/status 를 읽지 못함: {msg.data!r}')

    def _check_infra(self):
        # 그래프 조회만 한다 (구독·발행 없음).
        infra = judge_infra(
            self._domain_id, self._control_domain_id,
            [name for name, _ in self.get_node_names_and_namespaces()],
            self._mock_node_name, self._bridge_names,
            self.count_publishers('/zone_manager/status'),
            {robot: [info.node_name
                     for info in self.get_publishers_info_by_topic(f'/{robot}/amcl_pose')]
             for robot in self._bridge_names})
        summary = (infra['mode'], infra['zone_manager']['state'],
                   tuple(b['state'] for b in infra['bridges'].values()))
        if summary != self._last_infra:
            self._last_infra = summary
            bridges = ', '.join(f'{r}={b["state"]}' for r, b in infra['bridges'].items())
            self.get_logger().info(
                f'기반 노드: domain={self._domain_id} mode={infra["mode"]} '
                f'zone_manager={infra["zone_manager"]["state"]}'
                f'({infra["zone_manager"]["count"]}) bridges: {bridges}')
        return infra

    def _publish(self):
        now = time.time()
        snapshot = self.fleet.snapshot(now)
        for name, robot in snapshot['robots'].items():
            if robot['online'] != self._last_online[name]:
                self._last_online[name] = robot['online']
                self.get_logger().info(f'{name}: {"online" if robot["online"] else "offline"}')
        # 이번 주기에 새로 생긴 이벤트만 싣는다. 쌓아 두는 것은 백엔드(fleet_api_node)가 한다.
        snapshot['events'] = self.fleet.collect_events(snapshot)
        for event in snapshot['events']:
            if event['kind'] in ('alert', 'clear', 'zone'):
                self.get_logger().info(f'{event["robot"] or "-"}: {event["text"]}')
        snapshot['infra'] = self._check_infra()
        self.pub.publish(String(data=json.dumps(snapshot, ensure_ascii=False)))


def main(args=None):
    rclpy.init(args=args)
    node = FleetStatusNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # launch 의 Ctrl+C 는 정리 도중 인터럽트가 한 번 더 올 수 있다. 끄는 중이므로 무시한다.
        with contextlib.suppress(KeyboardInterrupt):
            node.destroy_node()
            rclpy.try_shutdown()
