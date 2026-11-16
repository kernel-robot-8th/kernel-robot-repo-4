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
가짜 LED 서버: 순찰 노드의 /set_led 요청을 받아 응답만 한다.

순찰 노드는 /set_led 가 없으면 실물 pinky_led 의 led_server 를 직접 띄우려 하고,
매번 10초씩 기다린다. 시뮬에는 LED 장치가 없으므로 이 노드가 서비스를 대신 연다.
마지막 색은 로그(DEBUG)로만 남긴다. 깜박임마다 요청이 와서 INFO 로 찍으면 로그가 넘친다.
"""

from pinky_interfaces.srv import SetLed
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class FakeLedNode(Node):
    """/set_led 서비스를 열고 모든 요청에 성공으로 답한다."""

    def __init__(self):
        super().__init__('fake_led_node')
        self.last = None
        self.create_service(SetLed, 'set_led', self._on_set_led)

    def _on_set_led(self, request, response):
        color = (request.command, request.r, request.g, request.b)
        if color != self.last:
            self.get_logger().debug(f'LED {color}')
            self.last = color
        response.success = True
        response.message = 'sim'
        return response


def main(args=None):
    rclpy.init(args=args)
    node = FakeLedNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
