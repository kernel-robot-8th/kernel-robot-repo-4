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
고객 게이트웨이 노드 (sub PC). 고객 핸드폰에 주문 화면과 API 를 내보낸다.

- HTTP: 고객 화면(web/dist/customer.html)과 /api/customer/* (customer_gateway_utils.py)
- ROS: /control_center/submit_order, /control_center/customer_decision 호출,
       /control_center/orders, /control_center/inventory 구독
로봇에 직접 명령을 보내지 않는다. fms_core 에만 요청한다.
"""

import os
import threading

from ament_index_python.packages import get_package_share_directory
from cobot_gui.customer_gateway_utils import (
    CustomerApi, load_catalog, make_server, sign_request)
from cobot_interfaces.msg import InventoryState, OrderStatus
from cobot_interfaces.srv import CustomerDecision, SubmitOrder
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


class CustomerGatewayNode(Node):
    """ROS 쪽 backend. HTTP 스레드가 이 객체의 함수를 부른다."""

    def __init__(self):
        """파라미터를 읽고 서비스 클라이언트·구독·HTTP 서버를 만든다."""
        super().__init__('customer_gateway')
        share = get_package_share_directory('cobot_gui')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)
        self.declare_parameter('web_root', os.path.join(share, 'web', 'dist'))
        self.declare_parameter('catalog_file', os.path.join(share, 'config',
                                                            'customer_catalog.yaml'))
        self.declare_parameter('gateway_key_file', '')
        self.declare_parameter('service_timeout_sec', 3.0)
        self.declare_parameter('orders_qos_depth', 50)

        def param(name):
            return self.get_parameter(name).value

        self._timeout = float(param('service_timeout_sec'))
        self._key = b''
        key_file = os.path.expanduser(param('gateway_key_file'))
        if key_file:
            with open(key_file, 'rb') as stream:
                self._key = stream.read().strip()
        else:
            self.get_logger().warn('gateway_key_file 이 비어 서명 없이 보낸다 (개발 모드)')

        self._orders = {}
        self._inventory = {}
        self._lock = threading.Lock()
        group = ReentrantCallbackGroup()
        self._submit = self.create_client(
            SubmitOrder, '/control_center/submit_order', callback_group=group)
        self._decision = self.create_client(
            CustomerDecision, '/control_center/customer_decision', callback_group=group)
        orders_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=param('orders_qos_depth'),
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        inventory_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OrderStatus, '/control_center/orders', self._on_order,
                                 orders_qos, callback_group=group)
        self.create_subscription(InventoryState, '/control_center/inventory',
                                 self._on_inventory, inventory_qos, callback_group=group)

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
        """주문할 수 있는 수량. 재고를 아직 못 받았으면 None."""
        with self._lock:
            item = self._inventory.get(sku)
        if item is None:
            return None
        return max(0, item.qty_on_hand - item.qty_reserved)

    def get_order(self, order_id):
        """구독으로 받은 마지막 주문 상태. 없으면 None."""
        with self._lock:
            msg = self._orders.get(order_id)
        if msg is None:
            return None
        return {'order_id': msg.order_id, 'sku': msg.sku, 'stage': msg.stage,
                'failure_reason': msg.failure_reason}

    def submit_order(self, fields):
        """주문 접수 서비스(SubmitOrder)를 부른다. 관제가 없거나 시간이 넘으면 None."""
        request = SubmitOrder.Request()
        for name, value in fields.items():
            setattr(request, name, value)
        request.gw_nonce, request.gw_sig = sign_request(self._key, (
            request.idempotency_key, request.sku, request.qty, request.table_id,
            request.requester_role, request.requester_id))
        response = self._call(self._submit, request)
        if response is None:
            return None
        return {'result': response.result, 'reject_code': response.reject_code,
                'order_id': response.order_id, 'duplicate': response.duplicate}

    def decide(self, fields):
        """고객 결정 서비스(CustomerDecision)를 부른다. 관제가 없거나 시간이 넘으면 None."""
        request = CustomerDecision.Request()
        for name, value in fields.items():
            setattr(request, name, value)
        request.gw_nonce, request.gw_sig = sign_request(
            self._key, (request.order_id, request.decision, request.requester_id))
        response = self._call(self._decision, request)
        if response is None:
            return None
        return {'result': response.result, 'reject_code': response.reject_code,
                'stage': response.stage}

    # --- 내부 ---

    def _call(self, client, request):
        if not client.wait_for_service(timeout_sec=self._timeout):
            self.get_logger().warn('{} 이 응답하지 않는다'.format(client.srv_name))
            return None
        done = threading.Event()
        future = client.call_async(request)
        future.add_done_callback(lambda _: done.set())
        if not done.wait(self._timeout):
            future.cancel()
            self.get_logger().warn('{} 시간 초과'.format(client.srv_name))
            return None
        return future.result()

    def _on_order(self, msg):
        with self._lock:
            self._orders[msg.order_id] = msg

    def _on_inventory(self, msg):
        with self._lock:
            self._inventory = {item.sku: item for item in msg.items}


def main(args=None):
    """노드를 돌린다. 서비스 응답을 HTTP 스레드가 기다리므로 다중 스레드 실행기를 쓴다."""
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
