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

"""고객 게이트웨이 HTTP 처리를 ROS 없이 가짜 fleet_control 로 본다."""

import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cobot_gui import customer_gateway_utils as gw
import pytest

CATALOG = Path(__file__).resolve().parents[1] / 'config' / 'customer_catalog.yaml'
SHOE = 'SHOE_RUN_WHITE_260'
SOLD_OUT = 'SHOE_SANDAL_BEIGE_240'


class FakeFleet:
    """cobot_fleet_control 의 요청·응답과 스냅숏을 흉내 낸다 (그 패키지 README 의 '고객 주문 화면용 요청')."""

    def __init__(self):
        self.orders = {}
        self.calls = []
        self.down = False
        self.stock = {SHOE: 3, SOLD_OUT: 0}
        self.places = {'BENCH_1': {'name': '고객 벤치 1'}}

    def available(self, sku):
        return self.stock.get(sku, 0)

    def destinations(self):
        return self.places

    def get_order(self, order_id):
        return self.orders.get(order_id)

    def request(self, payload):
        self.calls.append(payload)
        if self.down:
            return None
        if payload['type'] == 'order':
            data = payload['order']
            if self.stock.get(data['sku'], 0) < data['quantity']:
                return {'status': 400, 'body': {'detail': '재고 부족: 주문 거절'}}
            self.stock[data['sku']] -= data['quantity']
            order = dict(data, state='WAITING', stage='MOVE_PICKUP', detail='',
                         customer_received=False, customer_timed_out=False,
                         customer_declined=False)
            self.orders[data['order_id']] = order
            return {'status': 202, 'body': order}
        order = self.orders[payload['order_id']]
        if order['state'] != 'RUNNING' or order['stage'] != 'CUSTOMER':
            return {'status': 400, 'body': {'detail': '고객 수령 대기 중인 주문만 확인 가능'}}
        flag = 'customer_received' if payload['type'] == 'received' else 'customer_declined'
        order.update({flag: True, 'stage': 'LEAVE_DROPOFF'})
        return {'status': 200, 'body': order}

    def move(self, order_id, **changes):
        self.orders[order_id].update(changes)


@pytest.fixture
def api():
    fleet = FakeFleet()
    return gw.CustomerApi(gw.load_catalog(str(CATALOG)), fleet), fleet


def _order(api_obj, session='s1', key='k1', loc='BENCH_1', sku=SHOE):
    return api_obj.handle('POST', '/orders', {}, {
        'sku': sku, 'loc': loc, 'client_key': key, 'session': session})


def _status(api_obj, order_id='cust-k1', session='s1'):
    return api_obj.handle('GET', '/orders/' + order_id, {'session': [session]}, {})


def _decide(api_obj, decision, order_id='cust-k1', session='s1'):
    return api_obj.handle('POST', '/orders/{}/decision'.format(order_id), {},
                          {'session': session, 'decision': decision})


def test_catalog_has_location_and_stock(api):
    api_obj, _ = api
    status, body = api_obj.handle('GET', '/catalog', {'loc': ['BENCH_1']}, {})
    assert status == 200
    assert body['location'] == {'id': 'BENCH_1', 'name': '고객 벤치 1'}
    stock = {item['sku']: item['available'] for item in body['items']}
    assert stock[SOLD_OUT] == 0
    assert stock[SHOE] == 3


def test_catalog_unknown_location_is_null(api):
    api_obj, fleet = api
    assert api_obj.handle('GET', '/catalog', {'loc': ['X']}, {})[1]['location'] is None
    # 스냅숏을 아직 못 받았으면 자리를 모른다.
    fleet.places = None
    assert api_obj.handle('GET', '/catalog', {'loc': ['BENCH_1']}, {})[1]['location'] is None


def test_order_goes_to_fleet_with_destination(api):
    api_obj, fleet = api
    assert _order(api_obj) == (200, {'order_id': 'cust-k1', 'view': 'preparing'})
    assert fleet.calls == [{'type': 'order', 'order': {
        'order_id': 'cust-k1', 'sku': SHOE, 'quantity': 1, 'destination': 'BENCH_1'}}]
    assert _status(api_obj)[1] == {
        'order_id': 'cust-k1', 'sku': SHOE, 'stage': 'RECEIVED', 'view': 'preparing',
        'failure_reason': ''}


def test_purchase_and_decline_map_to_fleet_requests(api):
    api_obj, fleet = api
    _order(api_obj)
    # 도착 전 결정은 fleet_control 이 거절한다.
    status, body = _decide(api_obj, 'PAID')
    assert (status, body['error'], body['stage']) == (409, 'WRONG_STAGE', 'RECEIVED')
    fleet.move('cust-k1', state='RUNNING', stage='CUSTOMER')
    assert _status(api_obj)[1]['view'] == 'arrived'
    status, body = _decide(api_obj, 'CANCEL')
    assert (status, body['view'], body['stage']) == (200, 'cancelled', 'CANCELLED')
    assert fleet.calls[-1] == {'type': 'declined', 'order_id': 'cust-k1'}

    _order(api_obj, key='k2')
    fleet.move('cust-k2', state='RUNNING', stage='CUSTOMER')
    status, body = _decide(api_obj, 'PAID', order_id='cust-k2')
    assert (status, body['view']) == (200, 'paid')
    assert fleet.calls[-1] == {'type': 'received', 'order_id': 'cust-k2'}
    assert _decide(api_obj, 'MAYBE', order_id='cust-k2') == (400, {'error': 'BAD_DECISION'})


def test_out_of_stock_does_not_create_order(api):
    api_obj, fleet = api
    assert _order(api_obj, sku=SOLD_OUT) == (
        200, {'order_id': 'cust-k1', 'view': 'out_of_stock'})
    assert fleet.calls == []
    # 스냅숏이 오래돼 재고를 모를 때는 fleet_control 의 거절로 품절을 안다.
    fleet.available = lambda sku: None
    assert _order(api_obj, sku=SOLD_OUT, key='k2')[1]['view'] == 'out_of_stock'
    assert _status(api_obj, 'cust-k2')[0] == 404


def test_fleet_rejection_is_409_with_detail(api):
    api_obj, fleet = api
    fleet.request = lambda payload: {'status': 400, 'body': {'detail': '선반 3열의 상차 구역 미등록'}}
    status, body = _order(api_obj)
    assert (status, body) == (409, {'error': 'ORDER_REJECTED',
                                    'detail': '선반 3열의 상차 구역 미등록'})


def test_other_session_cannot_see_or_decide(api):
    api_obj, fleet = api
    _order(api_obj)
    fleet.move('cust-k1', state='RUNNING', stage='CUSTOMER')
    assert _status(api_obj, session='s2')[0] == 404
    assert _decide(api_obj, 'PAID', session='s2')[0] == 404
    assert len(fleet.calls) == 1


@pytest.mark.parametrize('kwargs,error', [
    ({'loc': 'NOWHERE'}, 'UNKNOWN_LOCATION'),
    ({'sku': 'NOPE'}, 'UNKNOWN_SKU'),
    ({'key': 'has space'}, 'BAD_REQUEST'),
    ({'key': 'dot.key'}, 'BAD_REQUEST'),
    ({'session': ''}, 'BAD_REQUEST'),
])
def test_bad_order_is_rejected(api, kwargs, error):
    api_obj, fleet = api
    status, body = _order(api_obj, **kwargs)
    assert (status, body['error']) == (400, error)
    assert fleet.calls == []


def test_fleet_down_is_503(api):
    api_obj, fleet = api
    fleet.down = True
    assert _order(api_obj) == (503, {'error': 'CONTROL_CENTER_UNAVAILABLE'})
    fleet.down = False
    fleet.places = None
    assert _order(api_obj, key='k2') == (503, {'error': 'CONTROL_CENTER_UNAVAILABLE'})


@pytest.mark.parametrize('order,expected', [
    (None, ('', 'preparing')),
    ({'state': 'WAITING', 'stage': 'MOVE_PICKUP'}, ('RECEIVED', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'MOVE_PICKUP'}, ('ASSIGNED', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'PICK'}, ('LOADING', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'CORRECT_PICKUP'}, ('LOADING', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'MOVE_DROPOFF'}, ('IN_TRANSIT', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'VERIFY_UNLOAD'}, ('IN_TRANSIT', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'CUSTOMER'}, ('UNLOADING', 'arrived')),
    # 정지·현장 확인 중에는 결정을 받을 수 없으므로 도착 화면을 띄우지 않는다.
    ({'state': 'ESTOP', 'stage': 'CUSTOMER'}, ('IN_TRANSIT', 'preparing')),
    ({'state': 'UNKNOWN', 'stage': 'LOAD'}, ('LOADING', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'RETURN_HOME', 'customer_received': True},
     ('HANDOVER_CONFIRMED', 'paid')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT', 'customer_received': True},
     ('HANDOVER_CONFIRMED', 'paid')),
    ({'state': 'RUNNING', 'stage': 'LEAVE_DROPOFF', 'customer_declined': True},
     ('CANCELLED', 'cancelled')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT', 'customer_timed_out': True},
     ('CANCELLED', 'cancelled')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT'}, ('CANCELLED', 'cancelled')),
    ({'state': 'FAILED', 'stage': 'DOCK_PICKUP', 'customer_received': True},
     ('FAILED', 'failed')),
])
def test_order_progress(order, expected):
    assert gw.order_progress(order) == expected


def test_failed_order_shows_reason(api):
    api_obj, fleet = api
    _order(api_obj)
    fleet.move('cust-k1', state='FAILED', detail='정차 공차 초과')
    body = _status(api_obj)[1]
    assert (body['view'], body['failure_reason']) == ('failed', '정차 공차 초과')


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
        data = json.dumps({'sku': SHOE, 'loc': 'BENCH_1',
                           'client_key': 'k1', 'session': 's1'}).encode()
        request = Request(base + '/api/customer/orders', data=data, method='POST',
                          headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            assert json.loads(response.read())['order_id'] == 'cust-k1'
        with urlopen(base + '/api/customer/orders/cust-k1?session=s1') as response:
            assert json.loads(response.read())['view'] == 'preparing'
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/index.html')
        assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/customer/orders', data=b'[', method='POST'))
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('text', [
    'items:\n  - {sku: A, name: a, price: 1}\n  - {sku: A, name: b}\n',
    'items:\n  - {sku: "A B", name: a, price: 1}\n',
])
def test_catalog_validation(tmp_path, text):
    path = tmp_path / 'c.yaml'
    path.write_text(text)
    with pytest.raises(ValueError):
        gw.load_catalog(str(path))


def test_catalog_with_locations_is_refused(tmp_path):
    path = tmp_path / 'c.yaml'
    path.write_text('locations:\n  BENCH_1: {name: x}\nitems: []\n')
    with pytest.raises(ValueError, match='destinations'):
        gw.load_catalog(str(path))
