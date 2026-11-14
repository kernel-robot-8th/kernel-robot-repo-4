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
fms_core 의 주문 부분 (보조 A 고객 주문). 관제 PC 에서 돈다.

- 서비스 서버: /control_center/submit_order (SubmitOrder),
               /control_center/customer_decision (CustomerDecision)
- 발행: /control_center/orders (OrderStatus), /control_center/inventory (InventoryState)
- DB: SQLite (order_db.py). 단계 규칙은 order_flow.py.

로봇에 명령을 보내지 않는다. 로봇 단계는 시뮬레이션으로 넘어간다 (order_flow.py 머리말).
"""

import os
import time

from builtin_interfaces.msg import Time
from cobot_control_center.order_db import OrderDb
from cobot_control_center.order_flow import (
    OrderFlowConfig, OrderService, parse_inventory, parse_pairs,
    REJECT_BAD_SIGNATURE, REJECT_LEDGER_UNAVAILABLE, RESULT_REJECTED, SignatureChecker)
from cobot_interfaces.msg import InventoryItem, InventoryState, OrderStatus
from cobot_interfaces.srv import CustomerDecision, SubmitOrder
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


class OrderManagerNode(Node):
    """주문 접수·고객 결정을 받고 주문 상태를 발행한다."""

    def __init__(self):
        """파라미터를 읽고 DB·서비스·발행자를 만든다."""
        super().__init__('order_manager')
        self.declare_parameter('db_path', '~/.ros/cobot_orders.sqlite3')
        self.declare_parameter('gateway_key_file', '')
        self.declare_parameter('locations', ['BENCH_1=WP_BENCH_DELIVERY'])
        self.declare_parameter('robot_ids', ['pinky_1'])
        self.declare_parameter('initial_inventory', [''])
        self.declare_parameter('sim_step_sec', 3.0)
        self.declare_parameter('tick_period_sec', 0.5)
        self.declare_parameter('orders_qos_depth', 50)
        self.declare_parameter('warehouse_waypoint', 'WP_LOAD_1')
        self.declare_parameter('repack_waypoint', 'WP_UNLOAD')
        self.declare_parameter('home_waypoint', 'WP_HOME_1')

        def param(name):
            return self.get_parameter(name).value

        db_path = os.path.expanduser(param('db_path'))
        if db_path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db = OrderDb(db_path)
        inventory = [item for item in param('initial_inventory') if item]
        if self._db.seed_inventory(parse_inventory(inventory)):
            self.get_logger().info('초기 재고 {}건을 넣었다'.format(len(inventory)))

        config = OrderFlowConfig(
            locations=parse_pairs(param('locations')),
            robot_ids=param('robot_ids'),
            step_sec=param('sim_step_sec'),
            warehouse_waypoint=param('warehouse_waypoint'),
            repack_waypoint=param('repack_waypoint'),
            home_waypoint=param('home_waypoint'))
        self._service = OrderService(self._db, config)

        key = b''
        key_file = os.path.expanduser(param('gateway_key_file'))
        if key_file:
            with open(key_file, 'rb') as stream:
                key = stream.read().strip()
        self._signature = SignatureChecker(key)
        if not self._signature.enabled:
            self.get_logger().warn('gateway_key_file 이 비어 서명을 검사하지 않는다 (개발 모드)')

        # 주문은 한 건씩 실린다. 늦게 붙은 구독자가 최근 주문을 받게 depth 를 둔다 (fms_interfaces §6).
        state_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=param('orders_qos_depth'),
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        inventory_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._orders_pub = self.create_publisher(
            OrderStatus, '/control_center/orders', state_qos)
        self._inventory_pub = self.create_publisher(
            InventoryState, '/control_center/inventory', inventory_qos)
        self.create_service(SubmitOrder, '/control_center/submit_order', self._on_submit)
        self.create_service(
            CustomerDecision, '/control_center/customer_decision', self._on_decision)
        self.create_timer(param('tick_period_sec'), self._on_tick)

        for order in self._service.list_orders():
            self._publish_order(order)
        self._publish_inventory()
        self.get_logger().info('주문 DB: {}'.format(db_path))

    def destroy_node(self):
        """DB 를 닫는다."""
        self._db.close()
        return super().destroy_node()

    def _on_submit(self, request, response):
        fields = (request.idempotency_key, request.sku, request.qty, request.table_id,
                  request.requester_role, request.requester_id)
        if not self._signature.check(fields, request.gw_nonce, request.gw_sig):
            response.result = RESULT_REJECTED
            response.reject_code = REJECT_BAD_SIGNATURE
            return response
        try:
            result = self._service.submit(
                time.time(), request.idempotency_key, request.sku, request.qty,
                request.table_id, request.requester_role, request.requester_id)
        except Exception as error:  # noqa: B902 - 원장 쓰기 실패는 거부로 알린다.
            self.get_logger().error('주문 DB 쓰기 실패: {}'.format(error))
            result = {'result': RESULT_REJECTED, 'reject_code': REJECT_LEDGER_UNAVAILABLE,
                      'order_id': '', 'duplicate': False}
        response.order_id = result['order_id']
        response.duplicate = result['duplicate']
        response.result = result['result']
        response.reject_code = result['reject_code']
        if result['order_id'] and not result['duplicate']:
            self.get_logger().info('주문 접수 {} ({}, {})'.format(
                result['order_id'], request.sku, request.table_id))
            self._publish_order(self._service.get_order(result['order_id']))
            self._publish_inventory()
        return response

    def _on_decision(self, request, response):
        fields = (request.order_id, request.decision, request.requester_id)
        if not self._signature.check(fields, request.gw_nonce, request.gw_sig):
            response.result = RESULT_REJECTED
            response.reject_code = REJECT_BAD_SIGNATURE
            return response
        try:
            result = self._service.decide(
                time.time(), request.order_id, request.decision, request.requester_id)
        except Exception as error:  # noqa: B902 - 원장 쓰기 실패는 거부로 알린다.
            self.get_logger().error('주문 DB 쓰기 실패: {}'.format(error))
            result = {'result': RESULT_REJECTED, 'reject_code': REJECT_LEDGER_UNAVAILABLE,
                      'stage': ''}
        response.result = result['result']
        response.reject_code = result['reject_code']
        response.stage = result['stage']
        if not result['reject_code']:
            self.get_logger().info('고객 결정 {} {}'.format(request.order_id, request.decision))
            self._publish_order(self._service.get_order(request.order_id))
            self._publish_inventory()
        return response

    def _on_tick(self):
        changed = self._service.tick(time.time())
        for order_id in changed:
            self._publish_order(self._service.get_order(order_id))
        if changed:
            self._publish_inventory()

    def _publish_order(self, order):
        msg = OrderStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.order_id = order['order_id']
        msg.sku = order['sku']
        msg.qty = order['qty']
        msg.table_id = order['table_id']
        msg.stage = order['stage']
        msg.stage_history = [stage for stage, _ in order['stage_history']]
        msg.stage_entered_at = [_to_time(at) for _, at in order['stage_history']]
        msg.failure_reason = order['failure_reason']
        msg.retry_count = order['retry_count']
        self._orders_pub.publish(msg)

    def _publish_inventory(self):
        msg = InventoryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        # 초기 재고는 YAML 파라미터에서 온다 (D19 전 초안).
        msg.source = InventoryState.SOURCE_MANUAL_YAML
        items = []
        for row in self._service.list_inventory():
            item = InventoryItem()
            item.sku = row['sku']
            item.location_id = row['location_id']
            item.qty_on_hand = row['qty_on_hand']
            item.qty_reserved = row['qty_reserved']
            items.append(item)
        msg.items = items
        self._inventory_pub.publish(msg)


def _to_time(seconds):
    stamp = Time()
    stamp.sec = int(seconds)
    stamp.nanosec = int((seconds - int(seconds)) * 1e9)
    return stamp


def main(args=None):
    """노드를 돌린다."""
    rclpy.init(args=args)
    node = OrderManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
