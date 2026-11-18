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
상세 화면 직접 조종 노드: /control_center/teleop_cmd 를 받아 /<robot>/cmd_vel 로 낸다.

이 패키지에서 로봇 속도 토픽에 발행하는 노드는 이것 하나다. 웹 서버(fleet_api_node)와 따로 돌아서
웹 서버가 멈추거나 브라우저가 끊겨도 timeout_sec 뒤 0 속도를 내고 세션을 끝낸다.
조종 중에 로봇이 끊기거나 작업·주문이 생기거나 정지 잠금·작업 명령 꺼짐이 되면 바로 끝낸다
(순찰 노드·Nav2 와 cmd_vel 이 겹치지 않게, teleop_utils.teleop_block_reason).
한계: 관제 PC 와 로봇 사이(브릿지·와이파이)가 끊기면 로봇에 마지막 속도가 남을 수 있다. 그건 로봇 쪽 일이다.
"""

import json
import time

from cobot_control_center.fleet_api_utils import active_orders
from cobot_control_center.teleop_utils import (
    active_task, json_dict, robot_order, teleop_block_reason, TeleopGate)
from geometry_msgs.msg import Twist
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String


class TeleopNode(Node):
    """화면 조종 입력을 cmd_vel 로 바꾸고, 입력이 끊기거나 막을 일이 생기면 세운다."""

    def __init__(self):
        super().__init__('teleop_node')
        self.declare_parameter('robots', ['pinky1', 'pinky2', 'pinky3'])
        self.declare_parameter('cmd_vel_format', '/{robot}/cmd_vel')
        self.declare_parameter('max_linear', 0.15)
        self.declare_parameter('max_angular', 0.6)
        self.declare_parameter('timeout_sec', 0.3)
        self.declare_parameter('rate_hz', 10.0)
        self.declare_parameter('stop_repeat', 5)
        self.declare_parameter('state_period_sec', 0.5)
        robots = [r for r in self.get_parameter('robots').value if r]
        self.gate = TeleopGate(robots,
                               self.get_parameter('max_linear').value,
                               self.get_parameter('max_angular').value,
                               self.get_parameter('timeout_sec').value,
                               self.get_parameter('stop_repeat').value)
        topic_format = self.get_parameter('cmd_vel_format').value
        self.cmd_pubs = {robot: self.create_publisher(Twist, topic_format.format(robot=robot), 10)
                         for robot in robots}
        reliable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.state_pub = self.create_publisher(String, '/control_center/teleop_state', latched)
        self.create_subscription(String, '/control_center/teleop_cmd', self._on_cmd, reliable)
        # 조종 중에도 막을 일을 계속 본다 (fleet_status·작업 목록은 fleet_api_node 와 같은 QoS).
        self._robots = {}
        self._tasks = {}
        self.create_subscription(String, '/control_center/fleet_status', self._on_fleet, 10)
        self.create_subscription(String, '/control_center/tasks', self._on_tasks, latched)
        self._last_state = None
        self.create_timer(1.0 / float(self.get_parameter('rate_hz').value), self._tick)
        self.create_timer(float(self.get_parameter('state_period_sec').value),
                          lambda: self._publish_state(force=True))
        self._publish_state(force=True)
        self.get_logger().info(
            f'teleop_node 시작: {", ".join(sorted(self.cmd_pubs))} '
            f'(최대 {self.gate.max_linear} m/s, {self.gate.max_angular} rad/s, '
            f'입력 {self.gate.timeout_sec}초 끊기면 정지)')

    def _on_cmd(self, msg):
        data = json_dict(msg.data)
        robot = data.get('robot_id') if data else None
        starting = robot is not None and robot not in self.gate.active() and not (
            data.get('stop'))
        if starting:
            # 시작은 API 가 검사했지만 그 사이 바뀌었을 수 있어 여기서도 본다.
            reason = self._block_reason(robot)
            if reason:
                self.gate.feed({'robot_id': robot, 'session': data.get('session'), 'stop': True},
                               time.monotonic())
                self._log_end(robot, reason)
                self._publish_state()
                return
        was_active = robot in self.gate.active()
        why = self.gate.feed(data, time.monotonic())
        if why:
            self.get_logger().debug(f'조종 입력 버림: {why}')
        elif starting:
            self.get_logger().info(f'{robot} 직접 조종 시작')
        elif was_active and robot not in self.gate.active():
            self.get_logger().info(f'{robot} 직접 조종 끝 (운영자 끝냄·화면 닫힘)')
        self._publish_state()

    def _on_fleet(self, msg):
        data = json_dict(msg.data)
        if data is not None and isinstance(data.get('robots'), dict):
            self._robots = data['robots']
            self._check_active()

    def _on_tasks(self, msg):
        data = json_dict(msg.data)
        if data is not None and isinstance(data.get('tasks'), list):
            self._tasks = data
            self._check_active()

    def _block_reason(self, robot):
        holds = self._tasks.get('holds')
        return teleop_block_reason(
            self._robots.get(robot), bool(self._tasks.get('armed')),
            task=active_task(self._tasks.get('tasks'), robot),
            order=robot_order(active_orders(self._tasks.get('orders')), robot),
            held=holds.get(robot) if isinstance(holds, dict) else None)

    def _check_active(self):
        for robot in list(self.gate.active()):
            reason = self._block_reason(robot)
            if reason and self.gate.block(robot, reason):
                self._log_end(robot, reason)
        self._publish_state()

    def _log_end(self, robot, reason):
        self.get_logger().warning(f'{robot} 직접 조종 끝냄: {reason}')

    def _tick(self):
        before = set(self.gate.active())
        for robot, linear, angular in self.gate.tick(time.monotonic()):
            msg = Twist()
            msg.linear.x = linear
            msg.angular.z = angular
            self.cmd_pubs[robot].publish(msg)
        for robot in before - set(self.gate.active()):
            self._log_end(robot, '입력 끊김')
        self._publish_state()

    def _publish_state(self, force=False):
        state = self.gate.state()
        if force or state != self._last_state:
            self._last_state = state
            self.state_pub.publish(String(data=json.dumps(state, ensure_ascii=False)))

    def stop_all(self):
        """종료 직전: 조종 중인 로봇에 0 속도를 낸다."""
        self.gate.end_all('관제 노드 종료')
        for robot, _, _ in self.gate.tick(time.monotonic()):
            self.cmd_pubs[robot].publish(Twist())


def main(args=None):
    # Ctrl+C 를 rclpy 가 먼저 받아 닫아 버리면 마지막 0 속도를 못 낸다. 그래서 신호 처리기를 쓰지 않는다.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = TeleopNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.stop_all()
        node.destroy_node()
        rclpy.try_shutdown()
