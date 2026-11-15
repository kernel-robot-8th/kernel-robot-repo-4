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
가짜 배터리: 실물 핑키처럼 /battery/percent·/battery/voltage(Float32)를 주기적으로 낸다.

관제(fleet_status_node)는 위치나 배터리가 stale_timeout_sec(8초) 동안 안 오면 offline 으로 본다.
실물은 배터리가 5초마다 와서 서 있어도 online 이지만, 시뮬은 서 있는 로봇이 amcl_pose 를 거의 내지
않아서 배터리가 없으면 '연결 끊김'으로 보인다. 값은 고정이다 (방전 흉내는 cobot_mock 이 한다).
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Float32


class FakeBatteryNode(Node):
    """고정된 배터리 잔량·전압을 period_sec 마다 발행한다."""

    def __init__(self):
        super().__init__('fake_battery_node')
        self.declare_parameter('period_sec', 5.0)
        self.declare_parameter('percent', 100.0)
        self.declare_parameter('voltage', 8.4)
        self.percent = float(self.get_parameter('percent').value)
        self.voltage = float(self.get_parameter('voltage').value)
        self.pub_percent = self.create_publisher(Float32, 'battery/percent', 10)
        self.pub_voltage = self.create_publisher(Float32, 'battery/voltage', 10)
        self.create_timer(float(self.get_parameter('period_sec').value), self._tick)
        self._tick()

    def _tick(self):
        self.pub_percent.publish(Float32(data=self.percent))
        self.pub_voltage.publish(Float32(data=self.voltage))


def main(args=None):
    rclpy.init(args=args)
    node = FakeBatteryNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
