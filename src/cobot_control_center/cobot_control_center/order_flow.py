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
고객 주문의 단계 진행 규칙 (보조 A, D14 초안).

ROS 없이 돈다. 시각은 밖에서 넣는다(초). 노드는 order_manager_node.py.

지금은 팔·주행과 연결되지 않았다. 그래서 로봇이 하는 단계는 step_sec 마다 저절로 넘어간다
(시뮬레이션). 실제 연동 때는 tick() 의 시간 진행 대신 CompletionEvidence·HandoverTask 결과로
같은 전이 함수(_advance)를 부르면 된다.

주문 단계 (OrderStatus.STAGE_*):
  RECEIVED -> ASSIGNED -> LOADING -> IN_TRANSIT -> UNLOADING(고객 앞 도착, 결정 대기)
  UNLOADING + PAID   -> HANDOVER_CONFIRMED -> RETURNING -> COMPLETED
  UNLOADING + CANCEL -> CANCELLED (고객 쪽 끝)
      그 뒤 로봇 단계(robot_step): TO_REPACK -> REPACKING -> TO_WAREHOUSE -> 끝

신발 위치는 선반 (행, 열)이다. 핑키는 열 앞 웨이포인트로 가고, 팔은 행 높이에서 집는다.
열 -> 웨이포인트는 매장 배치 파일(store_layout.py)에 있다.
"""

import hashlib
import hmac

STAGE_RECEIVED = 'RECEIVED'
STAGE_ASSIGNED = 'ASSIGNED'
STAGE_LOADING = 'LOADING'
STAGE_IN_TRANSIT = 'IN_TRANSIT'
STAGE_UNLOADING = 'UNLOADING'
STAGE_HANDOVER_CONFIRMED = 'HANDOVER_CONFIRMED'
STAGE_RETURNING = 'RETURNING'
STAGE_COMPLETED = 'COMPLETED'
STAGE_FAILED = 'FAILED'
STAGE_CANCELLED = 'CANCELLED'

# 시간이 지나면 저절로 넘어가는 단계 (시뮬레이션). UNLOADING 은 고객 결정을 기다린다.
AUTO_NEXT = {
    STAGE_RECEIVED: STAGE_ASSIGNED,
    STAGE_ASSIGNED: STAGE_LOADING,
    STAGE_LOADING: STAGE_IN_TRANSIT,
    STAGE_IN_TRANSIT: STAGE_UNLOADING,
    STAGE_HANDOVER_CONFIRMED: STAGE_RETURNING,
    STAGE_RETURNING: STAGE_COMPLETED,
}

# 취소 뒤 로봇 단계. 신발은 핑키 위에 그대로 두고 그 신발의 선반 열 앞으로 돌아간다
# (선반에 다시 꽂는 동작은 아직 없다).
ROBOT_STEP_TO_REPACK = 'TO_REPACK'
ROBOT_STEP_REPACKING = 'REPACKING'
ROBOT_STEP_TO_WAREHOUSE = 'TO_WAREHOUSE'
ROBOT_STEP_DONE = 'DONE'
ROBOT_STEPS_AFTER_CANCEL = (
    ROBOT_STEP_TO_REPACK, ROBOT_STEP_REPACKING, ROBOT_STEP_TO_WAREHOUSE, ROBOT_STEP_DONE)

DECISION_PAID = 'PAID'
DECISION_CANCEL = 'CANCEL'

RESULT_ACCEPTED = 'ACCEPTED'
RESULT_REJECTED = 'REJECTED'

REJECT_BAD_SIGNATURE = 'BAD_SIGNATURE'
REJECT_ROLE_FORBIDDEN = 'ROLE_FORBIDDEN'
REJECT_INVENTORY_UNAVAILABLE = 'INVENTORY_UNAVAILABLE'
REJECT_LEDGER_UNAVAILABLE = 'LEDGER_UNAVAILABLE'
REJECT_UNKNOWN_ORDER = 'UNKNOWN_ORDER'
REJECT_WRONG_STAGE = 'WRONG_STAGE'
REJECT_BAD_DECISION = 'BAD_DECISION'

FAILURE_UNKNOWN_TABLE = 'UNKNOWN_TABLE'
# 재고 칸의 열이 매장 배치에 없다 (배치 파일을 바꾼 뒤 DB 를 다시 만들지 않은 경우).
FAILURE_UNKNOWN_SHELF = 'UNKNOWN_SHELF'
FAILURE_BAD_REQUEST = 'BAD_REQUEST'

ALLOWED_ROLES = ('customer', 'staff', 'operator')

PAYMENT_PAID = 'PAID'
PAYMENT_CANCELLED = 'CANCELLED'


class OrderFlowConfig:
    """단계 진행에 쓰는 값. 노드가 파라미터에서 채운다."""

    def __init__(self, layout, robot_ids, step_sec, repack_waypoint, home_waypoint):
        """layout: StoreLayout (자리·선반 배치). robot_ids: 배정 후보(돌아가며 고른다)."""
        self.layout = layout
        self.locations = layout.location_waypoints()
        self.robot_ids = list(robot_ids)
        self.step_sec = float(step_sec)
        self.repack_waypoint = repack_waypoint
        self.home_waypoint = home_waypoint


class OrderService:
    """주문 접수·고객 결정·시간 진행. 바뀐 주문 ID 를 돌려줘서 노드가 발행하게 한다."""

    def __init__(self, db, config):
        """db: OrderDb, config: OrderFlowConfig."""
        self._db = db
        self._config = config

    # --- 주문 접수 (SubmitOrder) ---

    def submit(self, now, idempotency_key, sku, qty, table_id,
               requester_role='customer', requester_id=''):
        """
        주문을 받는다.

        :return: dict(result, reject_code, order_id, duplicate)
        """
        if requester_role not in ALLOWED_ROLES:
            return _submit_result(RESULT_REJECTED, REJECT_ROLE_FORBIDDEN)
        if not idempotency_key or not sku or qty <= 0:
            return _submit_result(RESULT_REJECTED, FAILURE_BAD_REQUEST)
        with self._db.transaction():
            found = self._db.find_order_by_key(idempotency_key)
            if found:
                return _submit_result(
                    RESULT_ACCEPTED, found['failure_reason'] if found['failure_reason'] in (
                        REJECT_INVENTORY_UNAVAILABLE,) else '',
                    found['order_id'], duplicate=True)

            order_id = 'ORD-{:05d}'.format(self._db.count_orders() + 1)
            waypoint_id = self._config.locations.get(table_id, '')
            order = {
                'order_id': order_id,
                'idempotency_key': idempotency_key,
                'sku': sku,
                'qty': int(qty),
                'table_id': table_id,
                'waypoint_id': waypoint_id,
                'requester_role': requester_role,
                'requester_id': requester_id,
                'stage': STAGE_RECEIVED,
                'stage_history': [[STAGE_RECEIVED, now]],
                'created_at': now,
                'updated_at': now,
            }
            item = self._db.get_inventory(sku)
            if item is not None:
                order.update(shelf_row=item['shelf_row'], shelf_col=item['shelf_col'],
                             load_waypoint_id=self._config.layout.column_waypoint(
                                 item['shelf_col']))
            reject_code = ''
            failure = ''
            if not waypoint_id:
                # 모르는 자리의 주문은 받아 두되 실패로 둔다 (SubmitOrder 에 거부 코드가 없다).
                failure = FAILURE_UNKNOWN_TABLE
            elif item is not None and not order['load_waypoint_id']:
                failure = FAILURE_UNKNOWN_SHELF
            if failure:
                order.update(stage=STAGE_FAILED, failure_reason=failure,
                             stage_history=[[STAGE_RECEIVED, now], [STAGE_FAILED, now]])
            elif self._reserve(sku, qty):
                order.update(reserved=1, next_step_at=now + self._config.step_sec)
            else:
                # SR-02: 가점유에 실패하면 접수하되 배정하지 않는다.
                reject_code = REJECT_INVENTORY_UNAVAILABLE
                order['failure_reason'] = REJECT_INVENTORY_UNAVAILABLE
            self._db.insert_order(order)
            self._db.add_event(order_id, now, 'stage', order['stage'], requester_id,
                               'table_id={} sku={} qty={}'.format(table_id, sku, qty))
            if order['stage'] == STAGE_FAILED:
                self._db.add_event(order_id, now, 'stage', STAGE_FAILED, '',
                                   order['failure_reason'])
        return _submit_result(RESULT_ACCEPTED, reject_code, order_id)

    # --- 고객 결정 (CustomerDecision) ---

    def decide(self, now, order_id, decision, requester_id=''):
        """
        고객이 구매(가짜 결제 완료) 또는 취소를 고른다.

        :return: dict(result, reject_code, stage)
        """
        if decision not in (DECISION_PAID, DECISION_CANCEL):
            return _decision_result(RESULT_REJECTED, REJECT_BAD_DECISION, '')
        with self._db.transaction():
            order = self._db.get_order(order_id)
            if order is None:
                return _decision_result(RESULT_REJECTED, REJECT_UNKNOWN_ORDER, '')
            if order['stage'] != STAGE_UNLOADING:
                return _decision_result(RESULT_REJECTED, REJECT_WRONG_STAGE, order['stage'])
            if decision == DECISION_PAID:
                self._db.upsert_payment(order_id, PAYMENT_PAID, now)
                self._db.add_event(order_id, now, 'payment', PAYMENT_PAID, requester_id,
                                   'fake payment')
                # 팔린 신발은 재고에서 빠진다.
                self._db.change_inventory(order['sku'], -order['qty'], -order['qty'])
                self._db.update_order(order_id, reserved=0)
                stage = self._set_stage(order, now, STAGE_HANDOVER_CONFIRMED, requester_id)
                self._db.update_order(order_id, robot_step='',
                                      next_step_at=now + self._config.step_sec)
            else:
                self._db.upsert_payment(order_id, PAYMENT_CANCELLED, now)
                stage = self._set_stage(order, now, STAGE_CANCELLED, requester_id)
                self._db.update_order(order_id, robot_step=ROBOT_STEP_TO_REPACK,
                                      next_step_at=now + self._config.step_sec)
                self._db.add_event(order_id, now, 'robot', ROBOT_STEP_TO_REPACK, '',
                                   'goto {}'.format(self._config.repack_waypoint))
        return _decision_result(RESULT_ACCEPTED, '', stage)

    # --- 시간 진행 (시뮬레이션) ---

    def tick(self, now):
        """next_step_at 이 지난 주문을 한 단계씩 넘긴다. 바뀐 주문 ID 목록을 돌려준다."""
        changed = []
        for order in self._db.orders_due(now):
            with self._db.transaction():
                if order['stage'] == STAGE_CANCELLED:
                    self._advance_robot_step(order, now)
                else:
                    self._advance(order, now)
            changed.append(order['order_id'])
        return changed

    def _advance(self, order, now):
        nxt = AUTO_NEXT.get(order['stage'])
        if nxt is None:
            self._db.update_order(order['order_id'], next_step_at=None)
            return
        extra = {}
        if nxt == STAGE_ASSIGNED and self._config.robot_ids:
            robot_id = self._config.robot_ids[
                (int(order['order_id'].split('-')[-1]) - 1) % len(self._config.robot_ids)]
            extra['robot_id'] = robot_id
            self._db.add_event(order['order_id'], now, 'robot', 'ASSIGNED', '', robot_id)
        if nxt == STAGE_LOADING:
            self._db.add_event(order['order_id'], now, 'robot', 'LOADING', '',
                               'goto {} pick row {} col {}'.format(
                                   order['load_waypoint_id'], order['shelf_row'],
                                   order['shelf_col']))
        self._set_stage(order, now, nxt, '')
        waits = nxt in (STAGE_UNLOADING, STAGE_COMPLETED)
        self._db.update_order(
            order['order_id'],
            next_step_at=None if waits else now + self._config.step_sec, **extra)

    def _advance_robot_step(self, order, now):
        steps = ROBOT_STEPS_AFTER_CANCEL
        index = steps.index(order['robot_step']) if order['robot_step'] in steps else -1
        nxt = steps[min(index + 1, len(steps) - 1)]
        detail = {
            ROBOT_STEP_REPACKING: 'HandoverTask REPACK at {}'.format(
                self._config.repack_waypoint),
            ROBOT_STEP_TO_WAREHOUSE: 'goto {}'.format(order['load_waypoint_id']),
            ROBOT_STEP_DONE: 'shoe stays on robot at shelf row {} col {}'.format(
                order['shelf_row'], order['shelf_col']),
        }.get(nxt, '')
        self._db.add_event(order['order_id'], now, 'robot', nxt, '', detail)
        values = {'robot_step': nxt, 'updated_at': now,
                  'next_step_at': None if nxt == ROBOT_STEP_DONE else now + self._config.step_sec}
        if nxt == ROBOT_STEP_DONE and order['reserved']:
            # 신발이 선반 열 앞에 돌아왔다. 가점유만 푼다 (선반 복귀 동작은 아직 없다, 초안).
            self._db.change_inventory(order['sku'], 0, -order['qty'])
            values['reserved'] = 0
        self._db.update_order(order['order_id'], **values)

    # --- 읽기 ---

    def get_order(self, order_id):
        """주문 한 건 (dict). 없으면 None."""
        return self._db.get_order(order_id)

    def list_orders(self):
        """주문 전체."""
        return self._db.list_orders()

    def list_inventory(self):
        """재고 전체."""
        return self._db.list_inventory()

    # --- 내부 ---

    def _reserve(self, sku, qty):
        item = self._db.get_inventory(sku)
        if item is None or item['qty_on_hand'] - item['qty_reserved'] < qty:
            return False
        self._db.change_inventory(sku, 0, qty)
        return True

    def _set_stage(self, order, now, stage, actor_id):
        history = list(order['stage_history']) + [[stage, now]]
        self._db.update_order(order['order_id'], stage=stage, stage_history=history,
                              updated_at=now)
        self._db.add_event(order['order_id'], now, 'stage', stage, actor_id)
        order['stage'] = stage
        order['stage_history'] = history
        return stage


def parse_inventory(items, layout=None):
    """
    ['SKU:행:열:수량', ...] 를 [(sku, row, col, qty)] 로 바꾼다.

    layout(StoreLayout)을 주면 선반에 없는 칸과 한 칸에 두 SKU 를 거부한다.
    """
    result = []
    slots = {}
    for item in items:
        parts = [p.strip() for p in item.split(':')]
        try:
            if len(parts) != 4 or not parts[0]:
                raise ValueError
            sku, row, col, qty = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            raise ValueError('"SKU:행:열:수량" 형식이 아니다: {!r}'.format(item)) from None
        if layout is not None and not layout.has_slot(row, col):
            raise ValueError('선반에 없는 칸이다 ({}행 {}열): {!r}'.format(row, col, item))
        if (row, col) in slots:
            raise ValueError('{}행 {}열에 SKU 가 둘이다: {} , {}'.format(
                row, col, slots[(row, col)], sku))
        slots[(row, col)] = sku
        result.append((sku, row, col, qty))
    return result


def slot_label(row, col):
    """InventoryItem.location_id 에 넣는 칸 이름. 예: 2행 3열 -> 'R2C3'."""
    return 'R{}C{}'.format(row, col)


def gateway_signature(key, fields):
    """
    게이트웨이 서명 HMAC-SHA256 (16진수).

    fields 를 줄바꿈 문자로 이어 서명한다. 순서는 docs/order_flow.md 의 '서명' 절.
    cobot_gui 의 customer_gateway_utils.gateway_signature 와 같은 식이어야 한다.
    """
    text = '\n'.join(str(f) for f in fields).encode('utf-8')
    return hmac.new(key, text, hashlib.sha256).hexdigest()


class SignatureChecker:
    """서명과 nonce 재사용을 본다. key 가 비어 있으면 검사하지 않는다 (개발 모드)."""

    def __init__(self, key, max_nonces=10000):
        """key: bytes. 비면 개발 모드."""
        self._key = key
        self._max = max_nonces
        self._seen = {}

    @property
    def enabled(self):
        """서명을 검사하는가."""
        return bool(self._key)

    def check(self, fields, nonce, sig):
        """서명이 맞고 nonce 를 처음 보면 True."""
        if not self._key:
            return True
        if not nonce or not sig:
            return False
        expected = gateway_signature(self._key, list(fields) + [nonce])
        if not hmac.compare_digest(expected, sig):
            return False
        if nonce in self._seen:
            return False
        self._seen[nonce] = True
        if len(self._seen) > self._max:
            self._seen.pop(next(iter(self._seen)))
        return True


def _submit_result(result, reject_code, order_id='', duplicate=False):
    return {'result': result, 'reject_code': reject_code,
            'order_id': order_id, 'duplicate': duplicate}


def _decision_result(result, reject_code, stage):
    return {'result': result, 'reject_code': reject_code, 'stage': stage}
