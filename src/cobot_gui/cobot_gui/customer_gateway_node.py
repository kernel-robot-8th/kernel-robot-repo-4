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
고객 게이트웨이 노드 (관제 PC). 고객 핸드폰에 주문 화면과 API 를 내보낸다.

- HTTP: 고객 화면(web/dist/customer.html)과 /api/customer/* (customer_gateway_utils.py)
- ROS: cobot_fleet_control 의 관제 토픽 (JSON 문자열, std_msgs/String)
    발행 /control_center/task_request  (type=order | received | declined)
    구독 /control_center/task_events   (같은 request_id 의 reply)
    구독 /control_center/tasks         (주문·재고·자리 스냅숏)
주문·재고 원장은 fleet_control 하나다. 이 노드는 저장하지 않고 로봇에 직접 명령하지 않는다.
"""

import json
import os
import threading
import time
import uuid

from ament_index_python.packages import get_package_share_directory
from cobot_gui.customer_gateway_utils import CustomerApi, load_catalog, make_server
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String


class CustomerGatewayNode(Node):
    """ROS 쪽 backend. HTTP 스레드가 이 객체의 함수를 부른다."""

    def __init__(self):
        """파라미터를 읽고 발행·구독·HTTP 서버를 만든다."""
        super().__init__('customer_gateway')
        share = get_package_share_directory('cobot_gui')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)
        self.declare_parameter('web_root', os.path.join(share, 'web', 'dist'))
        self.declare_parameter('catalog_file', os.path.join(share, 'config',
                                                            'customer_catalog.yaml'))
        self.declare_parameter('request_topic', '/control_center/task_request')
        self.declare_parameter('events_topic', '/control_center/task_events')
        self.declare_parameter('tasks_topic', '/control_center/tasks')
        self.declare_parameter('request_timeout_sec', 3.0)
        self.declare_parameter('snapshot_stale_sec', 5.0)

        def param(name):
            return self.get_parameter(name).value

        self._timeout = float(param('request_timeout_sec'))
        self._stale = float(param('snapshot_stale_sec'))
        self._orders = {}
        self._stock = {}
        self._destinations = None
        self._snapshot_at = None
        self._waiting = {}
        self._lock = threading.Lock()
        group = ReentrantCallbackGroup()
        self._request_pub = self.create_publisher(String, param('request_topic'), 50)
        self.create_subscription(String, param('events_topic'), self._on_event, 50,
                                 callback_group=group)
        # fleet_control 이 depth 1, TRANSIENT_LOCAL 로 낸다. 늦게 붙어도 마지막 스냅숏을 받는다.
        self.create_subscription(
            String, param('tasks_topic'), self._on_snapshot,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
            callback_group=group)

        web_root = param('web_root')
        if not os.path.isfile(os.path.join(web_root, 'customer.html')):
            self.get_logger().warn('웹 빌드 필요: {} 에 customer.html 이 없다'.format(web_root))
        api = CustomerApi(load_catalog(param('catalog_file')), self)
        self._server = make_server(param('host'), int(param('port')), api, web_root,
                                   logger=self.get_logger().debug)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.get_logger().info('고객 화면: http://{}:{}/?loc=<위치 ID>'.format(
            param('host'), param('port')))

    def destroy_node(self):
        """HTTP 서버를 멈춘다."""
        self._server.shutdown()
        self._server.server_close()
        return super().destroy_node()

    # --- backend (HTTP 스레드에서 불린다) ---

    def available(self, sku):
        """주문할 수 있는 수량. 스냅숏이 없거나 오래됐으면 None. 재고에 없는 상품은 0."""
        with self._lock:
            if not self._fresh():
                return None
            return self._stock.get(sku, 0)

    def destinations(self):
        """자리 목록 {위치 ID: {'name'}}. 스냅숏을 한 번도 못 받았으면 None."""
        with self._lock:
            return self._destinations

    def get_order(self, order_id):
        """스냅숏에서 본 마지막 주문 상태. 없으면 None."""
        with self._lock:
            return self._orders.get(order_id)

    def request(self, payload):
        """
        fleet_control 에 요청 하나를 보내고 응답을 기다린다.

        :return: {'status', 'body'}. fleet_control 이 없거나 시간이 넘으면 None.
        """
        if self._request_pub.get_subscription_count() == 0:
            self.get_logger().warn('fleet_control 이 요청 토픽을 구독하지 않는다')
            return None
        request_id = 'cust-' + uuid.uuid4().hex
        slot = {'done': threading.Event(), 'reply': None}
        with self._lock:
            self._waiting[request_id] = slot
        try:
            self._request_pub.publish(String(data=json.dumps(
                dict(payload, request_id=request_id), ensure_ascii=False)))
            if not slot['done'].wait(self._timeout):
                self.get_logger().warn('fleet_control 응답 시간 초과 ({})'.format(
                    payload.get('type')))
                return None
        finally:
            with self._lock:
                self._waiting.pop(request_id, None)
        reply = slot['reply']
        order = reply.get('body')
        if reply.get('status') in (200, 202) and isinstance(order, dict) and 'order_id' in order:
            # 다음 스냅숏(1초 주기)을 기다리지 않고 방금 받은 주문 상태를 쓴다.
            with self._lock:
                self._orders[order['order_id']] = order
        return {'status': reply.get('status'), 'body': order}

    # --- 내부 ---

    def _fresh(self):
        return (self._snapshot_at is not None
                and time.monotonic() - self._snapshot_at <= self._stale)

    def _decode(self, message):
        try:
            data = json.loads(message.data)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _on_event(self, message):
        data = self._decode(message)
        if not data or data.get('type') != 'reply':
            return
        with self._lock:
            slot = self._waiting.get(data.get('request_id'))
        if slot is not None:
            slot['reply'] = data
            slot['done'].set()

    def _on_snapshot(self, message):
        data = self._decode(message)
        if data is None:
            return
        orders = {order['order_id']: order for order in data.get('orders') or []
                  if isinstance(order, dict) and 'order_id' in order}
        stock = {item['sku']: int(item['available']) for item in data.get('stock') or []
                 if isinstance(item, dict) and 'sku' in item and 'available' in item}
        with self._lock:
            self._orders = orders
            self._stock = stock
            self._destinations = dict(data.get('destinations') or {})
            self._snapshot_at = time.monotonic()


def main(args=None):
    """노드를 돌린다. 응답을 HTTP 스레드가 기다리므로 다중 스레드 실행기를 쓴다."""
    rclpy.init(args=args)
    node = CustomerGatewayNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
