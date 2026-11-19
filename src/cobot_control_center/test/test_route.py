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

"""경로(route_utils.py, /api/routes)를 ROS 없이 검사한다."""

import json

from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import SnapshotStore, TaskStore
from cobot_control_center.route_utils import (
    CANCELED, FAILED, RouteError, RouteRunner, RUNNING, split_route, SUCCEEDED)
from fastapi.testclient import TestClient
import pytest

LAYERS = {
    'zones': {'A': {'points': {'ZA1': [1.0, 1.0, 0.0], 'ZA2': [1.2, 1.0, 0.0]},
                    'exit': {'name': 'ZA_EXIT', 'pose': [1.5, 1.0, 0.0]}},
              'B': {'points': {'ZB1': [2.0, 1.0, 0.0]}, 'exit': None}},
    'homes': {'pinky1': {'name': 'PINKY1_HOME', 'pose': [0.0, 0.0, 0.0]},
              'pinky2': {'name': 'PINKY2_HOME', 'pose': [0.1, 0.0, 0.0]}},
    'points': {'P1': [0.5, 0.5, 0.0], 'P2': [0.6, 0.5, 0.0], 'P3': [0.7, 0.5, 0.0]},
}


class FakeClock:
    """시험에서 시각을 직접 정한다."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeFleet:
    """작업 노드 대역: create 요청을 받아 작업을 만들고, 시험이 작업 상태를 바꾼다."""

    def __init__(self):
        self.sent = []
        self.tasks = {}
        self.replies = []   # 비어 있으면 202 로 받아 준다. (상태, 본문) 을 앞에서부터 꺼내 쓴다

    def submit(self, payload):
        self.sent.append(payload)
        if self.replies:
            return self.replies.pop(0)
        task_id = 't-' + payload['client_request_id']
        self.tasks[task_id] = {'task_id': task_id, 'state': 'SENT',
                               'operation': payload['operation'], 'points': payload['points']}
        return 202, dict(self.tasks[task_id])

    def finish(self, state='SUCCEEDED', detail=''):
        task = self.tasks['t-' + self.sent[-1]['client_request_id']]
        task.update(state=state, detail=detail)

    def task(self, task_id):
        return self.tasks.get(task_id)


def legs_of(points, robot='pinky1'):
    return [(leg['operation'], leg['points']) for leg in split_route(points, LAYERS, robot)]


def test_split_groups_general_points_and_splits_zone_points():
    assert legs_of(['p1', 'P2', 'ZA1', 'P3', 'PINKY1_HOME']) == [
        ('goto', ['P1', 'P2']), ('zone', ['ZA1']), ('goto', ['P3', 'PINKY1_HOME'])]
    # 구역 지점끼리 이어져도 하나씩 (순찰 노드 zone 은 지점 1개)
    assert legs_of(['ZA1', 'ZA2', 'ZB1']) == [
        ('zone', ['ZA1']), ('zone', ['ZA2']), ('zone', ['ZB1'])]


@pytest.mark.parametrize('points, status', [
    ([], 400), (['P9'], 400), (['ZA_EXIT'], 400), (['PINKY2_HOME'], 400), ('P1', 400),
    (['P1'] * 21, 400)])
def test_split_rejects_bad_points(points, status):
    with pytest.raises(RouteError) as error:
        split_route(points, LAYERS, 'pinky1')
    assert error.value.status == status


def test_split_without_layers_is_503():
    with pytest.raises(RouteError) as error:
        split_route(['P1'], None, 'pinky1')
    assert error.value.status == 503


def make_runner(fleet, clock=None):
    return RouteRunner(fleet.submit, fleet.task, retry_sec=5.0, clock=clock or FakeClock())


def test_runner_sends_next_leg_only_after_success():
    fleet = FakeFleet()
    runner = make_runner(fleet)
    names = ['P1', 'ZA1', 'P3']
    route = runner.create('pinky1', split_route(names, LAYERS, 'pinky1'), names)
    rid = route['route_id']
    runner.step()
    assert [s['client_request_id'] for s in fleet.sent] == [f'{rid}-0']
    assert fleet.sent[0]['operation'] == 'goto' and fleet.sent[0]['points'] == ['P1']
    runner.step()   # 아직 진행 중이면 다음 구간을 보내지 않는다
    assert len(fleet.sent) == 1
    fleet.finish()
    runner.step()   # 성공을 보고 다음 구간 차례로
    runner.step()
    assert fleet.sent[1]['operation'] == 'zone' and fleet.sent[1]['points'] == ['ZA1']
    fleet.finish()
    runner.step()
    runner.step()
    fleet.finish()
    runner.step()
    route = runner.route('pinky1')
    assert route['state'] == SUCCEEDED and route['index'] == 3
    assert [leg['state'] for leg in route['legs']] == ['SUCCEEDED'] * 3
    assert len(fleet.sent) == 3


def test_runner_stops_on_failed_leg():
    fleet = FakeFleet()
    runner = make_runner(fleet)
    runner.create('pinky1', split_route(['P1', 'ZA1'], LAYERS, 'pinky1'), ['P1', 'ZA1'])
    runner.step()
    fleet.finish('FAILED', 'nav2 aborted')
    runner.step()
    runner.step()
    route = runner.route('pinky1')
    assert route['state'] == FAILED and 'nav2 aborted' in route['detail']
    assert len(fleet.sent) == 1


def test_runner_retries_busy_then_fails_after_retry_window():
    fleet = FakeFleet()
    clock = FakeClock()
    runner = make_runner(fleet, clock)
    runner.create('pinky1', split_route(['P1'], LAYERS, 'pinky1'), ['P1'])
    fleet.replies = [(409, {'detail': '로봇 작업 중'}), None]
    runner.step()
    clock.now = 2.0
    runner.step()   # 응답 없음도 다시 보낸다
    assert runner.route('pinky1')['state'] == RUNNING
    clock.now = 3.0
    runner.step()   # 세 번째는 받아 준다 (같은 client_request_id)
    ids = {s['client_request_id'] for s in fleet.sent}
    assert len(fleet.sent) == 3 and len(ids) == 1
    assert runner.route('pinky1')['legs'][0]['task_id'] is not None

    runner.create('pinky2', split_route(['P1'], LAYERS, 'pinky2'), ['P1'])
    fleet.replies = [(409, {'detail': 'busy'})] * 3
    runner.step()
    clock.now = 9.0
    runner.step()
    assert runner.route('pinky2')['state'] == FAILED


def test_runner_fails_at_once_on_recorded_or_hard_rejection():
    for reply in [(409, {'task_id': 'x', 'detail': '등록되지 않은 지점'}),
                  (423, {'detail': '작업 명령 꺼짐'})]:
        fleet = FakeFleet()
        runner = make_runner(fleet)
        runner.create('pinky1', split_route(['P1'], LAYERS, 'pinky1'), ['P1'])
        fleet.replies = [reply]
        runner.step()
        assert runner.route('pinky1')['state'] == FAILED


def test_runner_cancel_and_one_route_per_robot():
    fleet = FakeFleet()
    runner = make_runner(fleet)
    legs = split_route(['P1', 'ZA1'], LAYERS, 'pinky1')
    runner.create('pinky1', legs, ['P1', 'ZA1'])
    with pytest.raises(RouteError) as error:
        runner.create('pinky1', legs, ['P1', 'ZA1'])
    assert error.value.status == 409
    runner.step()
    assert len(runner.cancel('pinky1')) == 1
    fleet.finish()
    runner.step()
    assert runner.route('pinky1')['state'] == CANCELED
    assert len(fleet.sent) == 1   # 취소 뒤 다음 구간을 보내지 않는다
    runner.create('pinky1', legs, ['P1', 'ZA1'])   # 끝났으면 새 경로를 받는다
    assert runner.routes()['recent'][0]['state'] == CANCELED


# ---------- /api/routes ----------

SNAPSHOT = {'time': 1.0, 'robots': {'pinky1': {'online': True, 'state': 'IDLE'}}, 'zones': {}}


def make_client(armed=True, reply_status=202):
    store = SnapshotStore(3.0)
    store.put(json.dumps(SNAPSHOT))
    tasks = TaskStore(3.0, 0.5)
    tasks.put_snapshot(json.dumps({'tasks': [], 'armed': armed}))
    sent = []

    def submit(payload):
        sent.append(payload)
        body = {'task_id': 't-' + payload['client_request_id'], 'state': 'SENT'}
        return reply_status, body if reply_status < 400 else {'detail': '거절'}

    runner = RouteRunner(submit, tasks.task)
    stops = []
    app = create_app(store, layers=LAYERS, tasks=tasks,
                     publish_request=lambda text: stops.append(json.loads(text)),
                     routes=runner)
    return TestClient(app), sent, runner


def test_api_route_sends_first_leg_and_reports_in_health():
    client, sent, _ = make_client()
    res = client.post('/api/routes', json={'robot_id': 'pinky1',
                                           'points': ['P1', 'ZA1', 'PINKY1_HOME']})
    assert res.status_code == 202
    body = res.json()
    assert [leg['operation'] for leg in body['legs']] == ['goto', 'zone', 'goto']
    assert len(sent) == 1 and sent[0]['type'] == 'create' and sent[0]['points'] == ['P1']
    assert client.get('/api/health').json()['routes']['pinky1']['state'] == RUNNING
    again = client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P2']})
    assert again.status_code == 409
    canceled = client.post('/api/routes/pinky1/cancel').json()['canceled']
    assert canceled == [body['route_id']]


def test_api_route_checks():
    client, _, _ = make_client(armed=False)
    assert client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P1']}
                       ).status_code == 423
    client, _, _ = make_client()
    assert client.post('/api/routes', json={'robot_id': 'nope', 'points': ['P1']}
                       ).status_code == 404
    assert client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P9']}
                       ).status_code == 400
    client, _, _ = make_client(reply_status=400)
    res = client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P1']})
    assert res.status_code == 409 and res.json()['route']['state'] == FAILED


def test_api_stop_cancels_route():
    client, _, runner = make_client()
    client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P1', 'ZA1']})
    # 작업 노드 대역이 없어 정지 응답은 503 이지만, 남은 경로는 그 전에 버린다.
    client.post('/api/robots/pinky1/stop', json={})
    assert runner.route('pinky1')['state'] == CANCELED


def test_read_only_backend_has_no_routes():
    store = SnapshotStore(3.0)
    client = TestClient(create_app(store, layers=LAYERS))
    assert client.post('/api/routes', json={'robot_id': 'pinky1', 'points': ['P1']}
                       ).status_code == 503
    assert client.get('/api/health').json()['routes'] == {}


def test_runner_logs_start_leg_success_and_end():
    fleet = FakeFleet()
    events = []
    runner = RouteRunner(fleet.submit, fleet.task, clock=FakeClock(), on_event=events.extend)
    names = ['P1', 'P2', 'ZA1', 'P3']
    runner.create('pinky1', split_route(names, LAYERS, 'pinky1'), names)
    for _ in range(3):
        runner.step()
        fleet.finish()
        runner.step()
    assert [e['text'] for e in events] == [
        '경로 시작 (3구간): 이동 P1→P2 → 구역 ZA1 → 이동 P3',
        '경로 1/3 성공: 이동 P1→P2',
        '경로 2/3 성공: 구역 ZA1',
        '경로 완료 (3구간)']
    assert {e['kind'] for e in events} == {'route'} and events[0]['robot'] == 'pinky1'

    events.clear()
    runner.create('pinky1', split_route(['P1', 'ZA1'], LAYERS, 'pinky1'), ['P1', 'ZA1'])
    runner.step()
    runner.cancel('pinky1')
    assert events[-1]['level'] == 'warn' and events[-1]['text'] == '경로 취소 (1/2): 운영자 정지'

    events.clear()
    runner.create('pinky2', split_route(['P1'], LAYERS, 'pinky2'), ['P1'])
    fleet.replies = [(423, {'detail': '작업 명령 꺼짐'})]
    runner.step()
    assert events[-1]['level'] == 'bad'
    assert events[-1]['text'] == '경로 중단 (1/1): goto:P1 거절: 작업 명령 꺼짐'
