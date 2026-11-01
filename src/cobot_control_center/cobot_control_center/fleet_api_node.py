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

로봇 토픽은 구독하지도 발행하지도 않는다. 받는 것은 fleet_status_node 가 낸 스냅샷 하나다.
rclpy 는 백그라운드 스레드에서, uvicorn 은 메인 스레드에서 돈다. uvicorn 이 Ctrl+C 를 받아
웹 서버를 먼저 닫고, 그 뒤 ROS 를 정리한다.
"""

import contextlib
import os
import threading

from ament_index_python.packages import get_package_share_directory
from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import (
    LayerError, load_map, load_map_layers, MapError, SnapshotStore)
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
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
        self.declare_parameter('zone_params', '')
        self.host = self.get_parameter('host').value
        self.port = int(self.get_parameter('port').value)
        self.store = SnapshotStore(self.get_parameter('source_stale_sec').value)
        self.map_data = self._load_map(self.get_parameter('map_yaml').value)
        self.layers = self._load_layers(self.get_parameter('points_dir').value,
                                        self.get_parameter('zone_params').value)
        self.web_dir = (self.get_parameter('web_dir').value
                        or os.path.join(get_package_share_directory('cobot_control_center'),
                                        'web'))
        self.create_subscription(String, '/control_center/fleet_status', self._on_fleet, 10)
        self.get_logger().info(
            f'fleet_api_node 시작: 화면 http://{self.host}:{self.port}/ '
            f'(읽기 전용, 로봇 토픽에 발행하지 않음)')

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

    def _load_layers(self, points_dir, zone_params):
        # 구역 표시는 덧그림이라 없어도 화면은 쓸 수 있다. 경고만 하고 계속한다.
        if not points_dir or not zone_params:
            self.get_logger().warning('points_dir·zone_params 가 비어 있음: 구역 표시 없이 시작')
            return None
        try:
            layers = load_map_layers(points_dir, zone_params)
        except LayerError as error:
            self.get_logger().warning(f'{error}: 구역 표시 없이 시작')
            return None
        for warning in layers['warnings']:
            self.get_logger().warning(f'구역 설정: {warning}')
        self.get_logger().info(f'구역 표시: {", ".join(layers["zones"]) or "없음"} '
                               f'(홈 {len(layers["homes"])}개)')
        return layers

    def _on_fleet(self, msg):
        if not self.store.put(msg.data):
            self.get_logger().warning('fleet_status 를 읽지 못함 (JSON 객체가 아님)')


def main(args=None):
    # Ctrl+C 는 uvicorn 이 받아 서버를 닫게 하고, rclpy 의 신호 처리기는 쓰지 않는다.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = FleetApiNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    try:
        # 시작·종료 이벤트를 쓰지 않는다. lifespan 을 켜 두면 uvicorn 이 종료 뒤 Ctrl+C 를 다시
        # 일으킬 때 남은 lifespan 작업이 CancelledError 트레이스백을 남긴다.
        app = create_app(node.store, node.map_data, node.web_dir,
                         node.context.get_domain_id(), node.layers)
        uvicorn.run(app, host=node.host, port=node.port,
                    log_level='info', lifespan='off')
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        with contextlib.suppress(KeyboardInterrupt):
            executor.shutdown()
            node.destroy_node()
            rclpy.try_shutdown()
            spinner.join(timeout=2.0)
