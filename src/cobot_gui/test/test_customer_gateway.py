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
        self.armed = True
        self.places = {'BENCH_1': {'name': '고객 벤치 1'}}

    def available(self, sku):
        return self.stock.get(sku, 0)

    def accepting(self):
        return self.armed

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
    # 스냅숏을 아직 못 받았으면 '모르는 자리' 가 아니라 관제 연결 대기다 (화면이 다시 묻는다).
    fleet.places = None
    assert api_obj.handle('GET', '/catalog', {'loc': ['BENCH_1']}, {}) == (
        503, {'error': 'CONTROL_CENTER_UNAVAILABLE'})


def test_order_goes_to_fleet_with_destination(api):
    api_obj, fleet = api
    assert _order(api_obj) == (200, {'order_id': 'cust-k1', 'view': 'preparing'})
    assert fleet.calls == [{'type': 'order', 'order': {
        'order_id': 'cust-k1', 'sku': SHOE, 'quantity': 1, 'destination': 'BENCH_1'}}]
    assert _status(api_obj)[1] == {
        'order_id': 'cust-k1', 'sku': SHOE, 'stage': 'RECEIVED', 'view': 'preparing',
        'failure_reason': '', 'paused': False, 'accepting': True}
    fleet.armed = False
    assert _status(api_obj)[1]['accepting'] is False


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
    ({'state': 'ESTOP', 'stage': 'CUSTOMER', 'robot_id': 'pinky1'}, ('UNLOADING', 'preparing')),
    ({'state': 'UNKNOWN', 'stage': 'LOAD', 'robot_id': 'pinky1'}, ('LOADING', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'LEAVE_PICKUP'}, ('LOADING', 'preparing')),
    ({'state': 'RUNNING', 'stage': 'MOVE_CUSTOMER'}, ('IN_TRANSIT', 'preparing')),
    # 관제 재시작으로 멈춘 배정 전 주문은 아직 접수 단계다.
    ({'state': 'UNKNOWN', 'stage': 'MOVE_PICKUP', 'robot_id': None}, ('RECEIVED', 'preparing')),
    # 직원 취소: 집기 전(홈 복귀·종결), 집기 뒤(이동·반납·종결), 접수 취소, 직접 처리.
    ({'state': 'RUNNING', 'stage': 'RETURN_HOME', 'failure': '직원 취소',
      'operator_cancelled': True, 'cancel_requested': {'stage': 'MOVE_PICKUP'}},
     ('CANCELLED', 'store_cancelled')),
    ({'state': 'FAILED', 'stage': 'RETURN_EXIT', 'failure': '직원 취소',
      'operator_cancelled': True}, ('CANCELLED', 'store_cancelled')),
    ({'state': 'RUNNING', 'stage': 'CUSTOMER', 'cancel_requested': {'stage': 'CUSTOMER'}},
     ('CANCELLED', 'store_cancelled')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT', 'customer_declined': True,
      'cancel_requested': {'stage': 'PICK'}}, ('CANCELLED', 'store_cancelled')),
    ({'state': 'FAILED', 'stage': 'LOAD', 'operator_restocked': True},
     ('CANCELLED', 'store_cancelled')),
    # 취소한 주문의 반납이 실패하면 관리화면처럼 처리 못 함이다.
    ({'state': 'FAILED', 'stage': 'RESTOCK', 'customer_declined': True,
      'cancel_requested': {'stage': 'PICK'}}, ('FAILED', 'failed')),
    # 피킹 전 실패로 홈에 돌아가는 중이다.
    ({'state': 'RUNNING', 'stage': 'RETURN_HOME', 'failure': '정차 공차 초과'},
     ('FAILED', 'failed')),
    ({'state': 'RUNNING', 'stage': 'RETURN_HOME', 'customer_received': True},
     ('HANDOVER_CONFIRMED', 'paid')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT', 'customer_received': True},
     ('HANDOVER_CONFIRMED', 'paid')),
    ({'state': 'RUNNING', 'stage': 'LEAVE_DROPOFF', 'customer_declined': True},
     ('CANCELLED', 'cancelled')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT', 'customer_timed_out': True},
     ('CANCELLED', 'timed_out')),
    ({'state': 'COMPLETED', 'stage': 'RETURN_EXIT'}, ('CANCELLED', 'cancelled')),
    ({'state': 'FAILED', 'stage': 'DOCK_PICKUP', 'customer_received': True},
     ('HANDOVER_CONFIRMED', 'paid')),
])
def test_order_progress(order, expected):
    assert gw.order_progress(order) == expected


def test_paused_order_comes_back_when_resumed(api):
    api_obj, fleet = api
    _order(api_obj)
    fleet.move('cust-k1', state='ESTOP', stage='CUSTOMER', robot_id='pinky1')
    body = _status(api_obj)[1]
    assert (body['view'], body['paused']) == ('preparing', True)
    fleet.move('cust-k1', state='RUNNING')
    body = _status(api_obj)[1]
    assert (body['view'], body['paused']) == ('arrived', False)
    # 이미 끝난 화면(구매 완료)에는 멈춤을 알리지 않는다.
    fleet.move('cust-k1', state='ESTOP', stage='RETURN_HOME', customer_received=True)
    body = _status(api_obj)[1]
    assert (body['view'], body['paused']) == ('paid', False)


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


def test_static_serves_symlinked_install(tmp_path):
    """Symlink 설치(colcon --symlink-install)처럼 파일이 build/ 를 가리켜도 내보낸다."""
    build = tmp_path / 'build'
    root = tmp_path / 'install'
    (build / 'assets').mkdir(parents=True)
    (root / 'assets').mkdir(parents=True)
    for name in ('customer.html', 'index.html', 'assets/a.js'):
        (build / name).write_text(name)
        (root / name).symlink_to(build / name)
    assert gw.resolve_static(str(root), '/') == str(root / 'customer.html')
    assert gw.resolve_static(str(root), '/assets/a.js') == str(root / 'assets' / 'a.js')
    # 바로가기여도 관제 화면과 '..' 탈출은 그대로 막는다.
    assert gw.resolve_static(str(root), '/index.html') is None
    assert gw.resolve_static(str(root), '/assets/../index.html') is None
    assert gw.resolve_static(str(root), '/assets/../../build/index.html') is None


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
