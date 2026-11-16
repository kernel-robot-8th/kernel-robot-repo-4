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
시뮬 도메인 감시 노드.

launch 가 넘긴 도메인 조합을 검사해 실물 도메인이면 오류를 남기고 끝난다.
launch 에서 on_exit="shutdown" 으로 띄우므로 이 노드가 끝나면 시뮬 전체가 내려간다.
(시뮬 노드들은 launch 의 eval 조건으로 먼저 막히고, 이 노드는 이유를 알려 주는 역할이다.)
"""

import os
import sys

from cobot_gazebo.sim_guard_utils import check_domains
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class SimGuardNode(Node):
    """시뮬 도메인을 검사하고, 통과하면 그대로 살아 있는다."""

    def __init__(self):
        super().__init__('sim_guard_node')
        self.declare_parameter('control_domain', -1)
        self.declare_parameter('robot_names', ['pinky1', 'pinky2', 'pinky3'])
        self.declare_parameter('robot_domains', [-1, -1, -1])
        names = list(self.get_parameter('robot_names').value)
        domains = list(self.get_parameter('robot_domains').value)
        if len(names) != len(domains):
            self.ok, self.message = False, f'robot_names {names} 와 robot_domains {domains} 개수가 다름'
            return
        self.ok, self.message = check_domains(
            int(self.get_parameter('control_domain').value), dict(zip(names, domains)),
            os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE', ''))


def main(args=None):
    rclpy.init(args=args)
    node = SimGuardNode()
    if not node.ok:
        node.get_logger().fatal(node.message)
        node.destroy_node()
        rclpy.try_shutdown()
        sys.exit(1)
    node.get_logger().info(node.message)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
