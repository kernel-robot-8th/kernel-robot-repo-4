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

"""고객 게이트웨이 HTTP 처리를 ROS 없이 가짜 backend 로 본다."""

import hashlib
import hmac
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cobot_gui import customer_gateway_utils as gw
import pytest

CATALOG = Path(__file__).resolve().parents[1] / 'config' / 'customer_catalog.yaml'
LAYOUT = (Path(__file__).resolve().parents[2] / 'cobot_bringup' / 'config'
          / 'store_layout.yaml')


class FakeBackend:
    """fms_core 대신 쓰는 가짜."""

    def __init__(self):
        self.orders = {}
        self.calls = []
        self.down = False

    def available(self, sku):
        return 0 if sku == 'SHOE_SANDAL_BEIGE_240' else 3

    def get_order(self, order_id):
        return self.orders.get(order_id)

    def submit_order(self, fields):
        self.calls.append(('submit', fields))
        if self.down:
            return None
        order_id = 'ORD-{:05d}'.format(len(self.orders) + 1)
        self.orders[order_id] = {'order_id': order_id, 'sku': fields['sku'],
                                 'stage': 'RECEIVED', 'failure_reason': ''}
        return {'result': 'ACCEPTED', 'reject_code': '', 'order_id': order_id,
                'duplicate': False}

    def decide(self, fields):
        self.calls.append(('decide', fields))
        order = self.orders[fields['order_id']]
        if order['stage'] != 'UNLOADING':
            return {'result': 'REJECTED', 'reject_code': 'WRONG_STAGE', 'stage': order['stage']}
        order['stage'] = 'HANDOVER_CONFIRMED' if fields['decision'] == 'PAID' else 'CANCELLED'
        return {'result': 'ACCEPTED', 'reject_code': '', 'stage': order['stage']}


@pytest.fixture
def api():
    backend = FakeBackend()
    return gw.CustomerApi(gw.load_catalog(str(CATALOG), str(LAYOUT)), backend), backend


def _order(api_obj, session='s1', key='k1', loc='BENCH_1', sku='SHOE_RUN_WHITE_260'):
    return api_obj.handle('POST', '/orders', {}, {
        'sku': sku, 'loc': loc, 'client_key': key, 'session': session})


def test_catalog_has_location_and_stock(api):
    api_obj, _ = api
    status, body = api_obj.handle('GET', '/catalog', {'loc': ['BENCH_1']}, {})
    assert status == 200
    assert body['location'] == {'id': 'BENCH_1', 'name': '고객 벤치 1'}
    stock = {item['sku']: item['available'] for item in body['items']}
    assert stock['SHOE_SANDAL_BEIGE_240'] == 0
    assert stock['SHOE_RUN_WHITE_260'] == 3


def test_catalog_unknown_location_is_null(api):
    api_obj, _ = api
    assert api_obj.handle('GET', '/catalog', {'loc': ['X']}, {})[1]['location'] is None


def test_order_flow_through_api(api):
    api_obj, backend = api
    status, body = _order(api_obj)
    assert (status, body) == (200, {'order_id': 'ORD-00001', 'view': 'preparing'})
    assert backend.calls[0][1] == {
        'idempotency_key': 'cust-k1', 'sku': 'SHOE_RUN_WHITE_260', 'qty': 1,
        'table_id': 'BENCH_1', 'requester_role': 'customer', 'requester_id': 's1'}
    status, body = api_obj.handle('GET', '/orders/ORD-00001', {'session': ['s1']}, {})
    assert body['view'] == 'preparing'
    # 도착 전 결정은 fms_core 가 거부한다.
    status, body = api_obj.handle('POST', '/orders/ORD-00001/decision', {},
                                  {'session': 's1', 'decision': 'PAID'})
    assert (status, body['error']) == (409, 'WRONG_STAGE')
    backend.orders['ORD-00001']['stage'] = 'UNLOADING'
    assert api_obj.handle('GET', '/orders/ORD-00001', {'session': ['s1']}, {})[1]['view'] == (
        'arrived')
    status, body = api_obj.handle('POST', '/orders/ORD-00001/decision', {},
                                  {'session': 's1', 'decision': 'CANCEL'})
    assert (status, body['view']) == (200, 'cancelled')


def test_other_session_cannot_see_or_decide(api):
    api_obj, backend = api
    _order(api_obj)
    backend.orders['ORD-00001']['stage'] = 'UNLOADING'
    assert api_obj.handle('GET', '/orders/ORD-00001', {'session': ['s2']}, {})[0] == 404
    assert api_obj.handle('POST', '/orders/ORD-00001/decision', {},
                          {'session': 's2', 'decision': 'PAID'})[0] == 404


@pytest.mark.parametrize('kwargs,error', [
    ({'loc': 'NOWHERE'}, 'UNKNOWN_LOCATION'),
    ({'sku': 'NOPE'}, 'UNKNOWN_SKU'),
    ({'key': 'has space'}, 'BAD_REQUEST'),
])
def test_bad_order_is_rejected(api, kwargs, error):
    api_obj, backend = api
    status, body = _order(api_obj, **kwargs)
    assert (status, body['error']) == (400, error)
    assert backend.calls == []


def test_control_center_down_is_503(api):
    api_obj, backend = api
    backend.down = True
    assert _order(api_obj)[0] == 503


@pytest.mark.parametrize('stage,failure,view', [
    ('', '', 'preparing'), ('IN_TRANSIT', '', 'preparing'), ('UNLOADING', '', 'arrived'),
    ('COMPLETED', '', 'paid'), ('CANCELLED', '', 'cancelled'), ('FAILED', 'X', 'failed'),
    ('RECEIVED', 'INVENTORY_UNAVAILABLE', 'out_of_stock'),
])
def test_stage_to_view(stage, failure, view):
    assert gw.stage_to_view(stage, failure) == view


def test_signature_matches_control_center_formula():
    # cobot_control_center/order_flow.py 와 같은 식: 필드를 '\n' 으로 이은 HMAC-SHA256.
    expected = hmac.new(b'k', b'a\nb\n1\nn', hashlib.sha256).hexdigest()
    assert gw.gateway_signature(b'k', ['a', 'b', 1, 'n']) == expected
    assert gw.sign_request(b'', ['a']) == ('', '')
    nonce, sig = gw.sign_request(b'k', ['a'])
    assert sig == gw.gateway_signature(b'k', ['a', nonce])


def test_static_serves_only_customer_files(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'customer.html').write_text('c')
    (tmp_path / 'index.html').write_text('dashboard')
    (tmp_path / 'assets' / 'a.js').write_text('x')
    assert gw.resolve_static(str(tmp_path), '/').endswith('customer.html')
    assert gw.resolve_static(str(tmp_path), '/assets/a.js').endswith('a.js')
    assert gw.resolve_static(str(tmp_path), '/index.html') is None
    assert gw.resolve_static(str(tmp_path), '/assets/../index.html') is None
    assert gw.resolve_static(str(tmp_path), '/assets/missing.js') is None


def test_http_server_end_to_end(tmp_path, api):
    api_obj, _ = api
    (tmp_path / 'customer.html').write_text('<html>shop</html>')
    server = gw.make_server('127.0.0.1', 0, api_obj, str(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:{}'.format(server.server_address[1])
    try:
        with urlopen(base + '/?loc=BENCH_1') as response:
            assert response.read() == b'<html>shop</html>'
        data = json.dumps({'sku': 'SHOE_RUN_WHITE_260', 'loc': 'BENCH_1',
                           'client_key': 'k1', 'session': 's1'}).encode()
        request = Request(base + '/api/customer/orders', data=data, method='POST',
                          headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            assert json.loads(response.read())['order_id'] == 'ORD-00001'
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/index.html')
        assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/customer/orders', data=b'[', method='POST'))
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_catalog_validation(tmp_path):
    path = tmp_path / 'c.yaml'
    path.write_text('items:\n  - {sku: A, name: a, price: 1}\n  - {sku: A, name: b}\n')
    with pytest.raises(ValueError):
        gw.load_catalog(str(path), str(LAYOUT))


def test_catalog_with_locations_is_refused(tmp_path):
    path = tmp_path / 'c.yaml'
    path.write_text('locations:\n  BENCH_1: {name: x}\nitems: []\n')
    with pytest.raises(ValueError, match='store_layout.yaml'):
        gw.load_catalog(str(path), str(LAYOUT))


def test_locations_come_from_store_layout(tmp_path):
    assert gw.load_locations(str(LAYOUT))['BENCH_1'] == {'name': '고객 벤치 1'}
    bad = tmp_path / 'layout.yaml'
    bad.write_text('locations:\n  BENCH_1: {name: x}\n')
    with pytest.raises(ValueError, match='waypoint'):
        gw.load_locations(str(bad))
