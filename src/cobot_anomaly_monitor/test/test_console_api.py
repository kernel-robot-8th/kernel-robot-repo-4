"""콘솔 HTTP 시험. 허용 범위 밖 요청이 관제로 나가면 실패해야 한다."""

import json
from urllib import error, request

from cobot_anomaly_monitor.console_api import ConsoleApi, serve
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
import pytest


class Fixture:
    def __init__(self, path):
        self.store = MonitorStore(path / 'm.sqlite3')
        self.sent = []
        self.reply = {'status': 200, 'body': {'ok': True}}
        self.core = MonitorCore(self.store, {}, ['pinky1'], self._send, clock=lambda: 50.0)
        self.api = ConsoleApi(self.core, None, lambda job: job(), self.core.replies.get,
                              clock=lambda: 50.0, commands=True)

    def _send(self, payload):
        self.sent.append(payload)
        if self.reply:
            self.core.on_task_event(dict(self.reply, type='reply',
                                         request_id=payload['request_id']))

    def post(self, path, **body):
        return self.api.handle('POST', path, body)


@pytest.fixture
def fx(tmp_path):
    item = Fixture(tmp_path)
    yield item
    item.store.close()


@pytest.mark.parametrize('path,body', [
    ('control', {'type': 'arm', 'armed': True}), ('mode', {'mode': 'AUTO_HOLD'}),
    ('anomalies', {'vision_class': 'box_on_floor'}), ('work/r1', {'decision': 'approve'}),
])
def test_read_only_by_default_refuses_every_command(tmp_path, path, body):
    store = MonitorStore(tmp_path / 'r.sqlite3')
    sent = []
    core = MonitorCore(store, {}, ['pinky1'], sent.append)
    api = ConsoleApi(core, None, lambda job: job(), core.replies.get)
    assert api.handle('POST', '/api/fms/' + path, body)[0] == 403
    assert sent == [] and core.mode == 'OBSERVE_ONLY' and store.events() == []
    api.refresh()
    assert api.handle('GET', '/api/fms/live_state', None)[1]['commands_enabled'] is False
    store.close()


def test_read_only_still_allows_acknowledging_a_record(tmp_path):
    store = MonitorStore(tmp_path / 'r.sqlite3')
    core = MonitorCore(store, {}, [], lambda payload: None, clock=lambda: 1.0)
    core.on_vision_event({'event_id': 'e1', 'camera_id': 'c', 'vision_class': 'box_on_floor'})
    api = ConsoleApi(core, None, lambda job: job(), core.replies.get)
    assert api.handle('POST', '/api/fms/anomalies/e1',
                      {'ack_state': 'FALSE_ALARM', 'operator': 'kgh'})[0] == 200
    store.close()


def test_control_forwards_allowed_requests_and_returns_the_reply(fx):
    assert fx.post('/api/fms/control', type='arm', armed=True, source='test') == (
        200, {'ok': True})
    assert fx.sent[0]['type'] == 'arm' and fx.sent[0]['request_id']


@pytest.mark.parametrize('kind', ['raw', 'stop', 'manual', None])
def test_control_refuses_other_types(fx, kind):
    assert fx.post('/api/fms/control', type=kind)[0] == 400
    assert fx.sent == []


def test_order_gets_an_id(fx):
    fx.post('/api/fms/control', type='order', order={'sku': 'SHOE42', 'route': 'wh_a_to_store'})
    assert fx.sent[0]['order']['order_id'].startswith('scn_')


def test_no_reply_is_reported_not_hidden(fx):
    fx.reply = None
    status, body = fx.post('/api/fms/control', type='arm', armed=True)
    assert status == 504 and '관제 응답 없음' in body['detail']


def test_mode_rejects_unknown_values(fx):
    assert fx.post('/api/fms/mode', mode='AUTO_HOLD') == (200, {'mode': 'AUTO_HOLD'})
    assert fx.post('/api/fms/mode', mode='OFF')[0] == 400
    assert fx.core.mode == 'AUTO_HOLD'


def test_mock_event_is_judged_and_can_be_turned_off(fx):
    status, row = fx.post('/api/fms/anomalies', vision_class='box_on_floor', map_x=0.0, map_y=0.0)
    assert status == 200 and row['judgment'] == 'LANE_OBSTACLE'
    assert row['camera_id'] == 'console_mock'
    assert fx.post('/api/fms/anomalies', vision_class='box_on_tray')[0] == 400
    fx.api.allow_mock = False
    assert fx.post('/api/fms/anomalies', vision_class='box_on_floor')[0] == 403


def test_acknowledge(fx):
    _, row = fx.post('/api/fms/anomalies', vision_class='box_on_floor', map_x=0.0, map_y=0.0)
    path = '/api/fms/anomalies/' + row['event_id']
    assert fx.post(path, ack_state='OPEN', operator='kgh')[0] == 400
    assert fx.post(path, ack_state='FALSE_ALARM')[0] == 400
    status, row = fx.post(path, ack_state='FALSE_ALARM', operator='kgh', note='그림자')
    assert status == 200 and row['ack_state'] == 'FALSE_ALARM' and row['resolved_by'] == 'kgh'
    assert fx.post('/api/fms/anomalies/none', ack_state='RESOLVED', operator='kgh')[0] == 404


def test_work_needs_the_adapter(fx):
    assert fx.post('/api/fms/work/r1', decision='approve', operator='kgh')[0] == 409


def test_unknown_paths(fx):
    assert fx.api.handle('GET', '/api/fms/ArmMode', None)[0] == 404
    assert fx.api.handle('GET', '/other', None)[0] == 404


def test_live_state_reads_the_cached_copy(fx):
    assert fx.api.handle('GET', '/api/fms/live_state', None) == (200, {})
    fx.api.refresh()
    status, body = fx.api.handle('GET', '/api/fms/live_state?t=1', None)
    assert status == 200 and body['mode'] == 'OBSERVE_ONLY' and body['robots'][0]['robot_id']
    assert body['adapter'] == {'enabled': False, 'blocked': ''}


@pytest.fixture
def server(fx):
    fx.api.refresh()
    # 실제 노드는 실행기 스레드에서 갱신한다. 여기서는 소켓 처리만 본다.
    fx.api.refresh = lambda: None
    item = serve(fx.api, '127.0.0.1', 0)
    yield f'http://127.0.0.1:{item.server_address[1]}'
    item.shutdown()
    item.server_close()


def call(url, data=None, content_type='application/json'):
    item = request.Request(url, data=data, headers={'Content-Type': content_type})
    try:
        with request.urlopen(item, timeout=3) as reply:
            return reply.status, json.loads(reply.read())
    except error.HTTPError as reply:
        return reply.code, json.loads(reply.read())


def test_http_get_and_post(server, fx):
    assert call(server + '/api/fms/live_state')[1]['mode'] == 'OBSERVE_ONLY'
    body = json.dumps({'mode': 'AUTO_HOLD'}).encode()
    assert call(server + '/api/fms/mode', body) == (200, {'mode': 'AUTO_HOLD'})


def test_http_refuses_form_posts(server, fx):
    status, _ = call(server + '/api/fms/mode', b'mode=AUTO_HOLD', 'text/plain')
    assert status == 415 and fx.core.mode == 'OBSERVE_ONLY'


def test_http_refuses_bad_and_large_bodies(server):
    assert call(server + '/api/fms/mode', b'{')[0] == 400
    assert call(server + '/api/fms/mode', b'[1]')[0] == 400
    assert call(server + '/api/fms/mode', b' ' * 16385)[0] == 413


def test_relay_observer_disallows_ack_and_control_even_if_requested(fx):
    api = ConsoleApi(fx.core, None, lambda job: job(), fx.core.replies.get, observation_only=True)
    api.refresh()
    assert api.handle('GET', '/api/fms/live_state', None)[0] == 200
    for route in ['control', 'work/r1', 'anomalies/e1', 'mode']:
        assert api.handle('POST', '/api/fms/' + route, {})[0] == 403
    assert fx.sent == []


def test_order_wire_history_readonly_pagination_and_isolation(fx):
    api = ConsoleApi(fx.core, None, lambda job: job(), None, observation_only=True)
    for seq in range(51):
        msg = dict(order_id='a', request_id=f'r{seq}', stage='PICK')
        fx.store.observe_work('request', msg, seq + .25)
    fx.store.observe_work('result', dict(order_id='b', request_id='other', stage='PICK'), 100)
    path = '/api/fms/orders/a/history'
    status, first = api.handle('GET', path, None)
    assert status == 200 and len(first['events']) == 50
    _, final = api.handle('GET', path + '?after=' + str(first['next_cursor']), None)
    assert final['next_cursor'] is None
    assert [(r['payload']['request_id'], r['at']) for r in final['events']] == [('r50', 50.25)]
    for bad in ['-1', 'x', str(2**63)]:
        assert api.handle('GET', path + '?after=' + bad, None)[0] == 400


def test_order_request_reply_history_survives_restart_and_is_not_work(fx):
    fx.post('/api/fms/control', type='order', order={'order_id': 'raw-order', 'sku': 'SHOE42'})
    reopened = MonitorStore(fx.store.db.execute('PRAGMA database_list').fetchone()[2])
    try:
        events = reopened.wire_page('raw-order', 0)['events']
        assert [e['kind'] for e in events] == ['control_request', 'control_reply']
        assert events[0]['request_id'] == events[1]['request_id']
        assert events[1]['payload']['rtt_ms'] == 0.0
        assert reopened.observed_work('raw-order') == ([], [])
    finally:
        reopened.close()
