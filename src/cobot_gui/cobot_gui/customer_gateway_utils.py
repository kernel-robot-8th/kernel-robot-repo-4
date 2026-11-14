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
고객 게이트웨이의 HTTP 처리 (관제 PC, 보조 A 고객 주문).

ROS 없이 돈다. ROS 쪽(요청 발행, 상태 구독)은 backend 로 넣는다 (customer_gateway_node.py).
고객 핸드폰 -> HTTP -> 이 모듈 -> backend -> fleet_control 순서다. 핸드폰은 ROS 에 닿지 않는다.
주문·재고 원장은 cobot_fleet_control 하나다. 이 모듈은 주문을 저장하지 않는다.
API 설명: src/cobot_gui/docs/customer_app.md
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import re
import threading
from urllib.parse import parse_qs, urlparse

import yaml

API_PREFIX = '/api/customer'
CUSTOMER_PAGE = 'customer.html'
# 고객 핸드폰이 Wi-Fi 로 붙는 포트다. 관제 PC 에서 돌지만 고객 화면만 내보낸다.
# 관제 화면(index.html)은 이 포트로 열리지 않아야 한다.
STATIC_DIRS = ('assets', 'customer')
MAX_BODY_BYTES = 4096

VIEW_PREPARING = 'preparing'
VIEW_ARRIVED = 'arrived'
VIEW_PAID = 'paid'
VIEW_CANCELLED = 'cancelled'
VIEW_FAILED = 'failed'
VIEW_OUT_OF_STOCK = 'out_of_stock'

# fleet_control 의 상차 구역 안 단계 (scenario_tree.STAGES 의 PICKUP_EXIT ~ VERIFY_LOAD 와 보정).
_PICKUP_STAGES = frozenset((
    'PICKUP_EXIT', 'DOCK_PICKUP', 'CORRECT_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD'))
# 고객 결정 -> fleet_control 요청 type
_DECISION_REQUEST = {'PAID': 'received', 'CANCEL': 'declined'}
# fleet_control 이 재고가 없을 때 돌려주는 거절 문구의 앞부분 (scenario_repository.create).
_OUT_OF_STOCK_DETAIL = '재고 부족'

_ID_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
# fleet_control 의 식별자 규칙(scenario_contracts.identifier)에 맞춘다. 'cust-' 를 붙여도 80자 안이다.
_FLEET_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
_CLIENT_KEY_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_ORDER_PATH_RE = re.compile(r'^/orders/([A-Za-z0-9_-]{1,80})(/decision)?$')


def order_progress(order):
    """
    fleet_control 주문 상태를 고객 화면의 (단계, 화면 상태)로 바꾼다.

    단계 이름은 고객 화면의 진행 표시(RECEIVED~UNLOADING)에 맞춘다.
    order 가 None 이면 접수는 됐지만 상태 스냅숏이 아직 오지 않은 것이다.
    """
    if order is None:
        return '', VIEW_PREPARING
    state, stage = order.get('state', ''), order.get('stage', '')
    if state == 'FAILED':
        return 'FAILED', VIEW_FAILED
    if order.get('customer_received'):
        return 'HANDOVER_CONFIRMED', VIEW_PAID
    if order.get('customer_declined') or order.get('customer_timed_out'):
        return 'CANCELLED', VIEW_CANCELLED
    if state == 'COMPLETED':
        # 수령 확인 없이 끝난 주문(운영자 복구 등)을 구매 완료로 보이지 않는다.
        return 'CANCELLED', VIEW_CANCELLED
    if stage == 'CUSTOMER' and state == 'RUNNING':
        return 'UNLOADING', VIEW_ARRIVED
    if state == 'WAITING':
        return 'RECEIVED', VIEW_PREPARING
    if stage == 'MOVE_PICKUP':
        return 'ASSIGNED', VIEW_PREPARING
    if stage in _PICKUP_STAGES:
        return 'LOADING', VIEW_PREPARING
    return 'IN_TRANSIT', VIEW_PREPARING


def load_catalog(path):
    """신발 목록 YAML 을 읽고 검사한다. 자리 목록은 fleet_control 이 알려 준다."""
    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}
    if 'locations' in data:
        raise ValueError('자리 목록은 cobot_fleet_control/config/scenario.yaml 의 destinations 로 '
                         '옮겼다. {} 에서 locations 를 지운다'.format(path))
    items = data.get('items') or []
    errors = []
    skus = set()
    for index, item in enumerate(items):
        for key in ('sku', 'name', 'price'):
            if key not in item:
                errors.append('items[{}] 에 {} 가 없다'.format(index, key))
        if not _FLEET_ID_RE.match(str(item.get('sku', ''))):
            errors.append('sku 형식이 아니다 (영문·숫자·밑줄·하이픈): {!r}'.format(item.get('sku')))
        if item.get('sku') in skus:
            errors.append('sku 가 겹친다: {}'.format(item.get('sku')))
        skus.add(item.get('sku'))
    if errors:
        raise ValueError('; '.join(errors))
    return {'items': items}


class CustomerApi:
    """
    고객 API.

    backend 는 fleet_control 과의 연결이다 (customer_gateway_node.py):
      - request(payload): /control_center/task_request 요청. {'status', 'body'} 또는 None(응답 없음)
      - get_order(order_id): 스냅숏의 주문 dict 또는 None
      - available(sku): 주문할 수 있는 수량 또는 None(모름)
      - destinations(): {자리 ID: {'name'}} 또는 None(스냅숏을 아직 못 받음)
    """

    def __init__(self, catalog, backend):
        """catalog: load_catalog() 결과."""
        self._catalog = catalog
        self._backend = backend
        self._owners = {}
        self._lock = threading.Lock()

    def handle(self, method, path, query, body):
        """
        요청 하나를 처리한다.

        :return: (HTTP 상태 코드, JSON 으로 바꿀 dict)
        """
        if path == '/catalog' and method == 'GET':
            return self._catalog_view(query.get('loc', [''])[0])
        if path == '/orders' and method == 'POST':
            return self._submit(body)
        match = _ORDER_PATH_RE.match(path)
        if match and method == 'GET' and not match.group(2):
            return self._status(match.group(1), query.get('session', [''])[0])
        if match and method == 'POST' and match.group(2):
            return self._decide(match.group(1), body)
        return 404, {'error': 'NOT_FOUND'}

    def _location(self, loc):
        info = (self._backend.destinations() or {}).get(loc)
        if info is None:
            return None
        return {'id': loc, 'name': str(info.get('name') or loc)}

    def _catalog_view(self, loc):
        items = []
        for item in self._catalog['items']:
            available = self._backend.available(item['sku'])
            items.append({
                'sku': item['sku'],
                'name': item['name'],
                'brand': item.get('brand', ''),
                'size': item.get('size', ''),
                'color': item.get('color', ''),
                'price': int(item['price']),
                'image': item.get('image', ''),
                # None 은 재고를 아직 못 받았다는 뜻이다. 화면은 주문을 막지 않는다.
                'available': available,
            })
        return 200, {'location': self._location(loc), 'items': items}

    def _submit(self, body):
        sku = str(body.get('sku', ''))
        loc = str(body.get('loc', ''))
        client_key = str(body.get('client_key', ''))
        session = str(body.get('session', ''))
        if not any(item['sku'] == sku for item in self._catalog['items']):
            return 400, {'error': 'UNKNOWN_SKU'}
        if self._backend.destinations() is None:
            return 503, {'error': 'CONTROL_CENTER_UNAVAILABLE'}
        if self._location(loc) is None:
            return 400, {'error': 'UNKNOWN_LOCATION'}
        if not _CLIENT_KEY_RE.match(client_key) or not _ID_RE.match(session):
            return 400, {'error': 'BAD_REQUEST'}
        # 주문 버튼 한 번 = client_key 하나. 같은 order_id 의 재전송은 fleet_control 이 같은 주문으로 돌려준다.
        order_id = 'cust-{}'.format(client_key)
        if self._backend.available(sku) == 0:
            return 200, {'order_id': order_id, 'view': VIEW_OUT_OF_STOCK}
        reply = self._backend.request({'type': 'order', 'order': {
            'order_id': order_id, 'sku': sku, 'quantity': 1, 'destination': loc}})
        if reply is None:
            return 503, {'error': 'CONTROL_CENTER_UNAVAILABLE'}
        if reply['status'] not in (200, 202):
            detail = _detail(reply)
            if detail.startswith(_OUT_OF_STOCK_DETAIL):
                return 200, {'order_id': order_id, 'view': VIEW_OUT_OF_STOCK}
            return 409, {'error': 'ORDER_REJECTED', 'detail': detail}
        with self._lock:
            self._owners.setdefault(order_id, session)
        return 200, {'order_id': order_id, 'view': order_progress(reply['body'])[1]}

    def _owned(self, order_id, session):
        with self._lock:
            owner = self._owners.get(order_id)
        return owner is not None and owner == session

    def _state(self, order_id, order):
        stage, view = order_progress(order)
        order = order or {}
        return {
            'order_id': order_id,
            'sku': order.get('sku', ''),
            'stage': stage,
            'view': view,
            'failure_reason': order.get('detail', '') if view == VIEW_FAILED else '',
        }

    def _status(self, order_id, session):
        if not self._owned(order_id, session):
            return 404, {'error': 'UNKNOWN_ORDER'}
        return 200, self._state(order_id, self._backend.get_order(order_id))

    def _decide(self, order_id, body):
        session = str(body.get('session', ''))
        decision = str(body.get('decision', ''))
        if not self._owned(order_id, session):
            return 404, {'error': 'UNKNOWN_ORDER'}
        if decision not in _DECISION_REQUEST:
            return 400, {'error': 'BAD_DECISION'}
        reply = self._backend.request({
            'type': _DECISION_REQUEST[decision], 'order_id': order_id})
        if reply is None:
            return 503, {'error': 'CONTROL_CENTER_UNAVAILABLE'}
        if reply['status'] != 200:
            # fleet_control 은 고객 수령 대기(CUSTOMER) 단계에서만 결정을 받는다.
            stage = order_progress(self._backend.get_order(order_id))[0]
            return 409, {'error': 'WRONG_STAGE', 'stage': stage, 'detail': _detail(reply)}
        return 200, self._state(order_id, reply['body'])


def _detail(reply):
    body = reply.get('body')
    return str(body.get('detail', '')) if isinstance(body, dict) else ''


def resolve_static(web_root, path):
    """URL 경로를 web_root 안의 파일로 바꾼다. 내보내지 않는 파일이면 None."""
    if path in ('/', '/' + CUSTOMER_PAGE):
        rel = CUSTOMER_PAGE
    else:
        rel = path.lstrip('/')
        if rel.split('/', 1)[0] not in STATIC_DIRS:
            return None
    root = os.path.realpath(web_root)
    full = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
        return None
    # '..' 로 허용 폴더 밖(관제 화면 등)을 가리키는 경로를 막는다.
    final = os.path.relpath(full, root).replace(os.sep, '/')
    if final != CUSTOMER_PAGE and final.split('/', 1)[0] not in STATIC_DIRS:
        return None
    return full


def make_handler(api, web_root, logger=None):
    """HTTP 서버(ThreadingHTTPServer)에 넣을 요청 처리 클래스를 만든다."""

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CobotCustomerGateway/0.1'

        def do_GET(self):  # noqa: N802 - http.server 이름 규칙
            self._dispatch('GET')

        def do_POST(self):  # noqa: N802 - http.server 이름 규칙
            self._dispatch('POST')

        def log_message(self, fmt, *args):
            if logger is not None:
                logger('{} {}'.format(self.address_string(), fmt % args))

        def _dispatch(self, method):
            url = urlparse(self.path)
            if url.path.startswith(API_PREFIX + '/') or url.path == API_PREFIX:
                self._api(method, url)
            elif method == 'GET':
                self._static(url.path)
            else:
                self._json(405, {'error': 'METHOD_NOT_ALLOWED'})

        def _api(self, method, url):
            body = {}
            if method == 'POST':
                length = int(self.headers.get('Content-Length') or 0)
                if length > MAX_BODY_BYTES:
                    self._json(413, {'error': 'TOO_LARGE'})
                    return
                try:
                    body = json.loads(self.rfile.read(length) or b'{}')
                except ValueError:
                    self._json(400, {'error': 'BAD_JSON'})
                    return
                if not isinstance(body, dict):
                    self._json(400, {'error': 'BAD_JSON'})
                    return
            status, payload = api.handle(
                method, url.path[len(API_PREFIX):] or '/', parse_qs(url.query), body)
            self._json(status, payload)

        def _static(self, path):
            full = resolve_static(web_root, path)
            if full is None:
                if path in ('/', '/' + CUSTOMER_PAGE):
                    self._text(503, '웹 빌드 필요: cobot_gui/web 에서 npm run build')
                else:
                    self._text(404, 'not found')
                return
            with open(full, 'rb') as stream:
                data = stream.read()
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            cache = 'no-cache' if full.endswith('.html') else 'public, max-age=3600'
            self.send_header('Cache-Control', cache)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _text(self, status, text):
            data = text.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def make_server(host, port, api, web_root, logger=None):
    """HTTP 서버를 만든다. serve_forever() 는 부르는 쪽이 한다."""
    return ThreadingHTTPServer((host, port), make_handler(api, web_root, logger))
