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

"""상세 화면 직접 조종 (teleop_utils.py, fleet_api_app.py 의 /ws/teleop) 을 ROS 없이 검사한다."""

import json
import threading

from cobot_control_center.fleet_api_app import (
    create_app, WS_TELEOP_ENDED, WS_TELEOP_REFUSED, WS_TELEOP_TAKEN)
from cobot_control_center.fleet_api_utils import SnapshotStore, TaskStore
from cobot_control_center.teleop_utils import (
    active_task, scale_cmd, teleop_block_reason, TeleopGate, TeleopStore)
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

IDLE = {'online': True, 'state': 'IDLE', 'extra': {}}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# ---------- 순수 로직 ----------

@pytest.mark.parametrize('vx, wz, expected', [
    (1, -1, (0.15, -0.6)),
    (0.5, 0, (0.075, 0.0)),
    (5, -9, (0.15, -0.6)),            # 범위 밖은 자른다
    ('1', None, (0.0, 0.0)),          # 숫자가 아니면 0
    (float('nan'), float('inf'), (0.0, 0.0)),
    (True, False, (0.0, 0.0)),        # bool 은 숫자로 보지 않는다
])
def test_scale_cmd(vx, wz, expected):
    assert scale_cmd(vx, wz, 0.15, 0.6) == pytest.approx(expected)


def test_block_reason_order():
    assert teleop_block_reason(None, True) == '등록되지 않은 로봇'
    assert teleop_block_reason(dict(IDLE, online=False), True) == '연결 끊김'
    assert '작업 명령 꺼짐' in teleop_block_reason(IDLE, False)
    latched = dict(IDLE, extra={'central_latched': True})
    assert '정지 잠금' in teleop_block_reason(latched, True)
    assert '정지 잠금' in teleop_block_reason(IDLE, True, held='estop')
    assert teleop_block_reason(IDLE, True, route={'route_id': 'r1'}) == '경로 진행 중 r1'
    assert teleop_block_reason(IDLE, True, task={'task_id': 't1'}) == '작업 중 t1'
    assert teleop_block_reason(IDLE, True, order={'order_id': 'o1'}) == '주문 진행 중 o1'
    assert teleop_block_reason(dict(IDLE, state='MOVING'), True) == '로봇 작업 중 (MOVING)'
    assert teleop_block_reason(IDLE, True) == ''


def test_active_task_includes_unknown_only_for_that_robot():
    tasks = [{'task_id': 'a', 'robot_id': 'pinky2', 'state': 'RUNNING'},
             {'task_id': 'b', 'robot_id': 'pinky1', 'state': 'SUCCEEDED'},
             {'task_id': 'c', 'robot_id': 'pinky1', 'state': 'UNKNOWN'}]
    assert active_task(tasks, 'pinky1')['task_id'] == 'c'
    assert active_task(tasks[:2], 'pinky1') is None


def make_gate():
    return TeleopGate(['pinky1', 'pinky2'], 0.2, 1.0, timeout_sec=0.3, stop_repeat=3)


def test_gate_publishes_then_stops_after_timeout():
    gate = make_gate()
    assert gate.feed({'robot_id': 'pinky1', 'session': 's1', 'vx': 1, 'wz': 0.5}, 0.0) == ''
    assert gate.tick(0.1) == [('pinky1', 0.2, 0.5)]
    assert gate.active() == {'pinky1': 's1'}
    # 입력이 0.3초 넘게 없으면 0 을 stop_repeat 번 내고 끝낸다
    assert gate.tick(0.35) == [('pinky1', 0.0, 0.0)]
    assert gate.active() == {}
    assert gate.state()['ended'] == {'s1': '입력 끊김'}
    assert gate.tick(0.4) == [('pinky1', 0.0, 0.0)]
    assert gate.tick(0.5) == [('pinky1', 0.0, 0.0)]
    assert gate.tick(0.6) == []
    # 끝난 세션의 늦은 입력은 받지 않는다 (다시 움직이지 않게)
    assert '끝난 세션' in gate.feed({'robot_id': 'pinky1', 'session': 's1', 'vx': 1}, 0.7)
    assert gate.tick(0.8) == []


def test_gate_one_session_per_robot_and_stop():
    gate = make_gate()
    gate.feed({'robot_id': 'pinky1', 'session': 's1', 'vx': 0, 'wz': 0}, 0.0)
    assert gate.feed({'robot_id': 'pinky1', 'session': 's2', 'vx': 1}, 0.0) == '다른 세션이 조종 중'
    assert gate.feed({'robot_id': 'pinky9', 'session': 's3'}, 0.0).startswith('모르는 로봇')
    assert gate.feed({'robot_id': 'pinky2', 'vx': 1}, 0.0) == '세션 없음'
    assert gate.feed('not a dict', 0.0) == '형식 오류'
    assert gate.feed({'robot_id': 'pinky1', 'session': 's1', 'stop': True}, 0.1) == ''
    assert gate.state()['ended']['s1'] == '운영자 끝냄'
    assert gate.tick(0.2) == [('pinky1', 0.0, 0.0)]
    # 끝난 뒤에는 새 세션이 잡을 수 있다
    assert gate.feed({'robot_id': 'pinky1', 'session': 's2', 'vx': 1}, 0.2) == ''


def test_gate_block_and_end_all():
    gate = make_gate()
    assert gate.block('pinky1', '작업 중 t1') is False
    gate.feed({'robot_id': 'pinky1', 'session': 's1', 'vx': 1}, 0.0)
    gate.feed({'robot_id': 'pinky2', 'session': 's2', 'wz': -1}, 0.0)
    assert gate.block('pinky1', '작업 중 t1') is True
    assert gate.state()['ended']['s1'] == '작업 중 t1'
    gate.end_all('관제 노드 종료')
    assert sorted(gate.tick(0.1)) == [('pinky1', 0.0, 0.0), ('pinky2', 0.0, 0.0)]


def test_teleop_store_claim_release_and_health():
    clock = FakeClock()
    store = TeleopStore(2.0, clock=clock)
    assert store.health() == {'teleop_online': False, 'teleop': [], 'teleop_limits': None}
    assert store.put_state('nope') is False
    assert store.put_state(json.dumps({'active': {}, 'ended': {'x': '입력 끊김'},
                                       'max_linear': 0.15, 'max_angular': 0.6}))
    assert store.online() is True and store.ended('x') == '입력 끊김'
    assert store.claim('pinky1', 'a') is True
    assert store.claim('pinky1', 'b') is False
    assert store.health()['teleop'] == ['pinky1']
    assert store.health()['teleop_limits'] == {'max_linear': 0.15, 'max_angular': 0.6}
    store.release('pinky1', 'b')            # 남의 세션은 풀지 않는다
    assert store.session('pinky1') == 'a'
    store.release('pinky1', 'a')
    assert store.sessions() == {}
    clock.now = 2.5
    assert store.online() is False


# ---------- API (/ws/teleop) ----------

class Rig:
    """작업 노드·조종 노드 대역을 붙인 시험용 앱."""

    def __init__(self, robot=IDLE, armed=True, tasks=(), teleop_online=True):
        self.store = SnapshotStore(3.0, clock=FakeClock())
        self.store.put(json.dumps({'time': 1.0, 'robots': {'pinky1': robot}, 'zones': {}}))
        self.tasks = TaskStore(3.0, 0.5, clock=FakeClock())
        self.tasks.put_snapshot(json.dumps({'tasks': list(tasks), 'armed': armed}))
        self.teleop = TeleopStore(2.0, clock=FakeClock())
        if teleop_online:
            self.set_state({})
        self.sent = []
        self.requests = []
        self.client = TestClient(create_app(
            self.store, tasks=self.tasks, publish_request=self.controller,
            teleop=self.teleop, publish_teleop=lambda text: self.sent.append(json.loads(text))))

    def set_state(self, ended):
        self.teleop.put_state(json.dumps({'active': {}, 'ended': ended,
                                          'max_linear': 0.15, 'max_angular': 0.6}))

    def controller(self, text):
        request = json.loads(text)
        self.requests.append(request)
        reply = {'type': 'reply', 'request_id': request['request_id'], 'status': 202,
                 'body': {'robot_id': 'pinky1'}}
        threading.Thread(target=self.tasks.put_event, args=(json.dumps(reply),)).start()


def refused(rig, url='/ws/teleop/pinky1'):
    with rig.client.websocket_connect(url) as ws:
        message = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert message['type'] == 'refused'
    return message['detail'], closed.value.code


def test_ws_teleop_refuses_when_blocked():
    assert refused(Rig(armed=False)) == (
        "작업 명령 꺼짐 (화면 위 '작업 명령 켜기' 먼저)", WS_TELEOP_REFUSED)
    assert refused(Rig(robot=dict(IDLE, state='MOVING')))[0] == '로봇 작업 중 (MOVING)'
    busy = Rig(tasks=[{'task_id': 't1', 'robot_id': 'pinky1', 'state': 'RUNNING'}])
    assert refused(busy)[0] == '작업 중 t1'
    assert refused(Rig(teleop_online=False))[0].startswith('조종 노드 응답 없음')
    assert refused(Rig(), '/ws/teleop/pinky9')[0] == '등록되지 않은 로봇'


def test_ws_teleop_read_only_refuses():
    rig = Rig()
    client = TestClient(create_app(rig.store, tasks=rig.tasks, publish_request=None,
                                   teleop=rig.teleop, publish_teleop=None))
    with client.websocket_connect('/ws/teleop/pinky1') as ws:
        assert '읽기 전용' in ws.receive_json()['detail']


def test_ws_teleop_forwards_input_blocks_commands_and_stops_on_close():
    rig = Rig()
    with rig.client.websocket_connect('/ws/teleop/pinky1') as ws:
        started = ws.receive_json()
        assert started['type'] == 'started'
        assert started['limits'] == {'max_linear': 0.15, 'max_angular': 0.6}
        session = started['session']
        ws.send_json({'vx': 0.5, 'wz': -1})
        # 다른 화면은 같은 로봇을 잡지 못한다
        assert refused(rig) == ('다른 화면에서 조종 중', WS_TELEOP_TAKEN)
        assert rig.client.get('/api/health').json()['teleop'] == ['pinky1']
        # 조종 중에는 작업·경로·초기위치·수동 명령을 받지 않는다
        for url, body in (('/api/tasks', {'robot_id': 'pinky1', 'operation': 'home'}),
                          ('/api/routes', {'robot_id': 'pinky1', 'points': ['P1']}),
                          ('/api/robots/pinky1/initial_pose', {}),
                          ('/api/robots/pinky1/raw_cmd', {'command': 'home'})):
            res = rig.client.post(url, json=body)
            assert res.status_code == 409 and '직접 조종 중' in res.json()['detail'], url
        assert rig.requests == []
    # 화면이 닫히면 stop 을 보내고 로봇을 놓는다
    assert rig.sent[0] == {'robot_id': 'pinky1', 'session': session, 'vx': 0, 'wz': 0}
    assert {'robot_id': 'pinky1', 'session': session, 'vx': 0.5, 'wz': -1} in rig.sent
    assert rig.sent[-1] == {'robot_id': 'pinky1', 'session': session, 'stop': True}
    assert rig.teleop.sessions() == {}


def test_ws_teleop_closes_when_node_ends_session():
    rig = Rig()
    with rig.client.websocket_connect('/ws/teleop/pinky1') as ws:
        session = ws.receive_json()['session']
        rig.set_state({session: '작업 중 t9'})
        assert ws.receive_json() == {'type': 'ended', 'detail': '작업 중 t9'}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == WS_TELEOP_ENDED


def test_stop_ends_teleop_first():
    rig = Rig()
    with rig.client.websocket_connect('/ws/teleop/pinky1') as ws:
        session = ws.receive_json()['session']
        res = rig.client.post('/api/robots/pinky1/stop', json={'emergency': True})
        assert res.status_code == 202
        assert {'robot_id': 'pinky1', 'session': session, 'stop': True} in rig.sent
        assert rig.requests[0]['type'] == 'estop'
