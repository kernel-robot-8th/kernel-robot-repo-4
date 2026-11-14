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
고객 게이트웨이의 HTTP 처리 (sub PC, 보조 A 고객 주문).

ROS 없이 돈다. ROS 쪽(서비스 호출, 주문 구독)은 backend 로 넣는다 (customer_gateway_node.py).
고객 핸드폰 -> HTTP -> 이 모듈 -> backend -> fms_core 순서다. 핸드폰은 ROS 에 닿지 않는다.
API 설명: src/cobot_gui/docs/customer_app.md
"""

import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import re
import secrets
import threading
from urllib.parse import parse_qs, urlparse

import yaml

API_PREFIX = '/api/customer'
CUSTOMER_PAGE = 'customer.html'
# sub PC 는 고객 화면만 내보낸다. 관제 화면(index.html)은 내보내지 않는다.
STATIC_DIRS = ('assets', 'customer')
MAX_BODY_BYTES = 4096

VIEW_PREPARING = 'preparing'
VIEW_ARRIVED = 'arrived'
VIEW_PAID = 'paid'
VIEW_CANCELLED = 'cancelled'
VIEW_FAILED = 'failed'
VIEW_OUT_OF_STOCK = 'out_of_stock'

_STAGE_VIEW = {
    '': VIEW_PREPARING,
    'RECEIVED': VIEW_PREPARING,
    'ASSIGNED': VIEW_PREPARING,
    'LOADING': VIEW_PREPARING,
    'IN_TRANSIT': VIEW_PREPARING,
    'UNLOADING': VIEW_ARRIVED,
    'HANDOVER_CONFIRMED': VIEW_PAID,
    'RETURNING': VIEW_PAID,
    'COMPLETED': VIEW_PAID,
    'CANCELLED': VIEW_CANCELLED,
    'FAILED': VIEW_FAILED,
}

_ID_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
_ORDER_PATH_RE = re.compile(r'^/orders/([A-Za-z0-9_.:-]{1,64})(/decision)?$')


def stage_to_view(stage, failure_reason=''):
    """주문 단계를 고객 화면 상태로 바꾼다."""
    if failure_reason == 'INVENTORY_UNAVAILABLE' and stage in ('', 'RECEIVED'):
        return VIEW_OUT_OF_STOCK
    return _STAGE_VIEW.get(stage, VIEW_PREPARING)


def gateway_signature(key, fields):
    """
    게이트웨이 서명 HMAC-SHA256 (16진수).

    cobot_control_center 의 order_flow.gateway_signature 와 같은 식이다 (코드는 나눠 쓰지 않는다).
    """
    text = '\n'.join(str(f) for f in fields).encode('utf-8')
    return hmac.new(key, text, hashlib.sha256).hexdigest()


def sign_request(key, fields):
    """(nonce, sig) 를 만든다. key 가 비면 ('', '') (개발 모드)."""
    if not key:
        return '', ''
    nonce = secrets.token_hex(16)
    return nonce, gateway_signature(key, list(fields) + [nonce])


def load_catalog(path):
    """신발 목록과 자리 목록 YAML 을 읽고 검사한다."""
    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}
    locations = data.get('locations') or {}
    items = data.get('items') or []
    errors = []
    skus = set()
    for index, item in enumerate(items):
        for key in ('sku', 'name', 'price'):
            if key not in item:
                errors.append('items[{}] 에 {} 가 없다'.format(index, key))
        if item.get('sku') in skus:
            errors.append('sku 가 겹친다: {}'.format(item.get('sku')))
        skus.add(item.get('sku'))
    for loc in locations:
        if not _ID_RE.match(str(loc)):
            errors.append('위치 ID 형식이 아니다: {!r}'.format(loc))
    if errors:
        raise ValueError('; '.join(errors))
    return {'locations': locations, 'items': items}


class CustomerApi:
    """고객 API. backend 는 submit_order·decide·get_order·available 를 가진다."""

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
        info = self._catalog['locations'].get(loc)
        if info is None:
            return None
        name = info.get('name', loc) if isinstance(info, dict) else str(info)
        return {'id': loc, 'name': name}

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
        if self._location(loc) is None:
            return 400, {'error': 'UNKNOWN_LOCATION'}
        if not _ID_RE.match(client_key) or not _ID_RE.match(session):
            return 400, {'error': 'BAD_REQUEST'}
        result = self._backend.submit_order({
            'idempotency_key': 'cust-{}'.format(client_key),
            'sku': sku,
            'qty': 1,
            'table_id': loc,
            'requester_role': 'customer',
            'requester_id': session,
        })
        if result is None:
            return 503, {'error': 'CONTROL_CENTER_UNAVAILABLE'}
        if result['result'] != 'ACCEPTED':
            return 409, {'error': result['reject_code'] or 'REJECTED'}
        order_id = result['order_id']
        with self._lock:
            self._owners.setdefault(order_id, session)
        view = VIEW_OUT_OF_STOCK if result['reject_code'] == 'INVENTORY_UNAVAILABLE' else (
            VIEW_PREPARING)
        return 200, {'order_id': order_id, 'view': view}

    def _owned(self, order_id, session):
        with self._lock:
            owner = self._owners.get(order_id)
        return owner is not None and owner == session

    def _status(self, order_id, session):
        if not self._owned(order_id, session):
            return 404, {'error': 'UNKNOWN_ORDER'}
        order = self._backend.get_order(order_id) or {}
        stage = order.get('stage', '')
        failure = order.get('failure_reason', '')
        return 200, {
            'order_id': order_id,
            'sku': order.get('sku', ''),
            'stage': stage,
            'view': stage_to_view(stage, failure),
            'failure_reason': failure,
        }

    def _decide(self, order_id, body):
        session = str(body.get('session', ''))
        decision = str(body.get('decision', ''))
        if not self._owned(order_id, session):
            return 404, {'error': 'UNKNOWN_ORDER'}
        if decision not in ('PAID', 'CANCEL'):
            return 400, {'error': 'BAD_DECISION'}
        result = self._backend.decide({
            'order_id': order_id, 'decision': decision, 'requester_id': session})
        if result is None:
            return 503, {'error': 'CONTROL_CENTER_UNAVAILABLE'}
        if result['result'] != 'ACCEPTED':
            return 409, {'error': result['reject_code'] or 'REJECTED', 'stage': result['stage']}
        return 200, {'order_id': order_id, 'stage': result['stage'],
                     'view': stage_to_view(result['stage'])}


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
