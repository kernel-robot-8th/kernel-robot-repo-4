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

from cobot_control_center.fleet_status_utils import FleetState, yaw_from_quaternion
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
        robots = list(self.get_parameter('robots').value)
        stale = self.get_parameter('stale_timeout_sec').value
        period = self.get_parameter('publish_period_sec').value

        self.fleet = FleetState(robots, stale)
        self._last_online = {name: False for name in robots}
        self._last_state = {name: None for name in robots}

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
                               time.time())

    def _on_battery(self, robot, msg):
        self.fleet.update_battery(robot, msg.data, time.time())

    def _on_zone(self, msg):
        if not self.fleet.update_zone(msg.data):
            self.get_logger().warning(f'zone_manager/status 를 읽지 못함: {msg.data!r}')

    def _publish(self):
        now = time.time()
        snapshot = self.fleet.snapshot(now)
        for name, robot in snapshot['robots'].items():
            if robot['online'] != self._last_online[name]:
                self._last_online[name] = robot['online']
                self.get_logger().info(f'{name}: {"online" if robot["online"] else "offline"}')
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
