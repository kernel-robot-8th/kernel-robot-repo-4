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
관제 백엔드(fleet_api_utils.py, fleet_api_app.py)를 ROS 없이 검사한다.

fastapi·httpx 가 필요하다 (.venv, CLAUDE.md §5). 없으면 skip 하지 않고 import 에서 실패한다.
"""

import json
import os
import threading

from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import (
    LayerError, load_map, load_map_layers, MapError, SnapshotStore, TaskStore)
from fastapi.testclient import TestClient
import pytest

MAP_YAML = 'image: test.pgm\nresolution: 0.01\norigin: [-1.5, -1.6, 0]\nnegate: 0\n'
# 3x2 P5 PGM. 헤더에 주석 줄이 있어도 읽어야 한다.
MAP_PGM = b'P5\n# comment\n3 2\n255\n' + bytes([0, 128, 255, 255, 128, 0])


def write_map(tmp_path, yaml_text=MAP_YAML, pgm=MAP_PGM):
    (tmp_path / 'test.pgm').write_bytes(pgm)
    path = tmp_path / 'test.yaml'
    path.write_text(yaml_text, encoding='utf-8')
    return str(path)


SNAPSHOT = {
    'time': 100.0,
    'robots': {
        'pinky1': {'online': True, 'state': 'MOVING', 'battery_percent': 87.0},
        'pinky2': {'online': False, 'never_seen': True, 'state': None},
    },
    'zones': {'A': 'free'},
}


class FakeClock:
    """시험에서 시각을 직접 정한다."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_store(stale_sec=3.0):
    clock = FakeClock()
    return SnapshotStore(stale_sec, clock=clock), clock


def test_store_empty():
    store, _ = make_store()
    assert store.get() == (0, None)
    assert store.health() == {'source_online': False, 'source_age': None}


def test_store_rejects_bad_input_and_keeps_previous():
    store, _ = make_store()
    assert store.put(json.dumps(SNAPSHOT)) is True
    for bad in ['', 'not json', '[1, 2]', None]:
        assert store.put(bad) is False
    seq, snapshot = store.get()
    assert seq == 1
    assert snapshot['zones'] == {'A': 'free'}


def test_store_stale_boundary():
    store, clock = make_store(stale_sec=3.0)
    clock.now = 10.0
    store.put(json.dumps(SNAPSHOT))
    clock.now = 13.0
    assert store.health()['source_online'] is True
    clock.now = 13.01
    assert store.health() == {'source_online': False, 'source_age': 3.01}


def test_store_wait_newer():
    store, _ = make_store()
    assert store.wait_newer(0, 0.01) is False
    timer = threading.Timer(0.05, store.put, args=[json.dumps(SNAPSHOT)])
    timer.start()
    assert store.wait_newer(0, 2.0) is True
    timer.join()


def test_api_before_first_snapshot():
    store, _ = make_store()
    client = TestClient(create_app(store))
    assert client.get('/api/health').json() == {
        'ok': True, 'domain_id': None, 'read_only': True, 'source_online': False,
        'source_age': None, 'task_manager_online': False}
    assert client.get('/api/fleet').status_code == 503
    assert client.get('/api/robots').status_code == 503


def test_api_health_reports_domain():
    store, _ = make_store()
    client = TestClient(create_app(store, domain_id=101))
    assert client.get('/api/health').json()['domain_id'] == 101


def test_api_routes():
    store, clock = make_store()
    store.put(json.dumps(SNAPSHOT))
    clock.now = 0.5
    client = TestClient(create_app(store))

    fleet = client.get('/api/fleet').json()
    assert fleet['source_online'] is True
    assert fleet['source_age'] == 0.5
    assert fleet['robots']['pinky1']['state'] == 'MOVING'

    robots = client.get('/api/robots').json()
    assert [r['robot_id'] for r in robots] == ['pinky1', 'pinky2']

    pinky1 = client.get('/api/robots/pinky1')
    assert pinky1.status_code == 200
    assert pinky1.json()['battery_percent'] == 87.0
    assert client.get('/api/robots/pinky9').status_code == 404


def test_api_without_task_manager_is_read_only():
    # 작업 노드를 넘기지 않으면 명령 경로는 503 이고 아무것도 발행하지 않는다.
    store, _ = make_store()
    client = TestClient(create_app(store))
    body = {'client_request_id': 'r1', 'robot_id': 'pinky1', 'operation': 'home'}
    assert client.post('/api/tasks', json=body).status_code == 503
    assert client.post('/api/robots/pinky1/stop', json={}).status_code == 503
    assert client.get('/api/tasks').status_code == 503
    assert client.get('/api/health').json()['task_manager_online'] is False


def test_load_map(tmp_path):
    info, data = load_map(write_map(tmp_path))
    assert info == {'image_width': 3, 'image_height': 2, 'resolution': 0.01,
                    'origin': [-1.5, -1.6, 0.0]}
    assert data == MAP_PGM


def test_load_map_errors(tmp_path):
    with pytest.raises(MapError):
        load_map(str(tmp_path / 'missing.yaml'))
    with pytest.raises(MapError):
        load_map(write_map(tmp_path, pgm=b'P2\n3 2\n255\n0 0 0 0 0 0'))
    with pytest.raises(MapError):
        load_map(write_map(tmp_path, yaml_text='resolution: 0.01\n'))


def test_map_routes(tmp_path):
    store, _ = make_store()
    without = TestClient(create_app(store))
    assert without.get('/api/map/info').status_code == 404
    assert without.get('/api/map/image').status_code == 404

    client = TestClient(create_app(store, load_map(write_map(tmp_path))))
    assert client.get('/api/map/info').json()['image_width'] == 3
    image = client.get('/api/map/image')
    assert image.status_code == 200
    assert image.content == MAP_PGM


def test_web_dir_is_served_without_hiding_api(tmp_path):
    (tmp_path / 'index.html').write_text('<title>관제</title>', encoding='utf-8')
    store, _ = make_store()
    client = TestClient(create_app(store, web_dir=str(tmp_path)))
    assert '관제' in client.get('/').text
    assert client.get('/api/health').json()['ok'] is True
    assert client.post('/api/fleet').status_code == 405


def test_installed_web_files_exist():
    # 화면 파일이 패키지 소스에 있는지 본다 (setup.py data_files 가 web/* 를 설치한다).
    web = os.path.join(os.path.dirname(__file__), '..', 'web')
    for name in ('index.html', 'style.css', 'core.js', 'cards.js', 'events.js',
                 'commands.js', 'tasks.js', 'map.js', 'raw.js', 'main.js'):
        assert os.path.isfile(os.path.join(web, name)), name


def test_websocket_sends_latest_then_pushes_new():
    store, _ = make_store()
    store.put(json.dumps(SNAPSHOT))
    client = TestClient(create_app(store))
    with client.websocket_connect('/ws/fleet') as ws:
        first = ws.receive_json()
        assert first['robots']['pinky1']['state'] == 'MOVING'
        updated = dict(SNAPSHOT, zones={'A': 'occupied_by:pinky1'})
        store.put(json.dumps(updated))
        assert ws.receive_json()['zones'] == {'A': 'occupied_by:pinky1'}


ZONE_PARAMS = """zone_manager_node:
  ros__parameters:
    robot_ids: ["pinky1", "pinky2"]
    zone_names: ["A", "B"]
    zone_A:
      queue_anchor: [0.15, 0.5, 0.0]
      queue_back_dir: [0.0, -2.0]
    zone_B:
      queue_anchor: [0.15, 0.5, 0.0]
      queue_back_dir: [0.0, -1.0]
    queue_spacing: 0.30
    queue_max: 3
"""


def robot_yaml(robot, home, zb=(0.6, -0.15, -1.5), p2=(0.45, -0.6)):
    return f"""{robot}_patrol:
  ros__parameters:
    home_name: {home}
    zone_points:
      A: [ZA]
      B: [ZB]
    points:
      I1: [0.0, 0.0, 0.0]
      I2: [0.0, -0.2]
      ZA: [0.6, 0.5, -1.5]
      ZB: {list(zb)}
      ZA_EXIT: [0.45, 0.2, -1.5]
      P10: [0.17, -0.6, 0.0]
      P2: {list(p2)}
      P1: [0.17, -0.6, 0.0]
      P36: [0.0, 0.0, 0.0]
"""


def write_layers(tmp_path, zb2=(0.6, -0.15, -1.5), p2_2=(0.45, -0.6)):
    (tmp_path / 'pinky1.yaml').write_text(robot_yaml('pinky1', 'I1'), encoding='utf-8')
    (tmp_path / 'pinky2.yaml').write_text(robot_yaml('pinky2', 'I2', zb2, p2_2),
                                          encoding='utf-8')
    path = tmp_path / 'zone_params.yaml'
    path.write_text(ZONE_PARAMS, encoding='utf-8')
    return str(tmp_path), str(path)


def test_load_map_layers(tmp_path):
    layers = load_map_layers(*write_layers(tmp_path))
    assert layers['warnings'] == []
    zone_a = layers['zones']['A']
    assert zone_a['points'] == {'ZA': [0.6, 0.5, -1.5]}
    assert zone_a['exit'] == {'name': 'ZA_EXIT', 'pose': [0.45, 0.2, -1.5]}
    # back_dir 는 단위벡터로 바꾼 뒤 간격을 곱한다 (zone_manager 와 같은 식).
    assert zone_a['queue'] == [[0.15, 0.5, 0.0], [0.15, 0.2, 0.0], [0.15, -0.1, 0.0]]
    assert layers['zones']['B']['exit'] is None
    assert layers['homes'] == {'pinky1': {'name': 'I1', 'pose': [0.0, 0.0, 0.0]},
                               'pinky2': {'name': 'I2', 'pose': [0.0, -0.2, 0.0]}}
    # 일반 지점: P 만, 번호 순서, (0, 0, 0) 예비값은 빼고 개수만. 홈 I1 (0, 0, 0) 은 남는다.
    assert list(layers['points']) == ['P1', 'P2', 'P10']
    assert layers['points']['P2'] == [0.45, -0.6, 0.0]
    assert layers['hidden_points'] == 1
    json.dumps(layers)


def test_load_map_layers_warns_on_point_mismatch(tmp_path):
    layers = load_map_layers(*write_layers(tmp_path, p2_2=(0.5, -0.6)))
    assert layers['warnings'] == ['일반 지점 좌표가 pinky1 와 pinky2 에서 다름']


def test_load_map_layers_warns_on_mismatch_and_missing_robot(tmp_path):
    points_dir, zone_params = write_layers(tmp_path, zb2=(0.7, -0.15, -1.5))
    layers = load_map_layers(points_dir, zone_params)
    assert layers['warnings'] == ['구역 B 좌표가 pinky1 와 pinky2 에서 다름']
    os.remove(os.path.join(points_dir, 'pinky2.yaml'))
    layers = load_map_layers(points_dir, zone_params)
    assert 'pinky2' not in layers['homes']
    assert any('pinky2.yaml' in w for w in layers['warnings'])


def test_load_map_layers_errors(tmp_path):
    points_dir, zone_params = write_layers(tmp_path)
    with pytest.raises(LayerError):
        load_map_layers(points_dir, str(tmp_path / 'missing.yaml'))
    with pytest.raises(LayerError):
        load_map_layers(str(tmp_path / 'nowhere'), zone_params)


def test_map_layers_route(tmp_path):
    store, _ = make_store()
    assert TestClient(create_app(store)).get('/api/map/layers').status_code == 404
    layers = load_map_layers(*write_layers(tmp_path))
    client = TestClient(create_app(store, layers=layers))
    assert client.get('/api/map/layers').json()['zones']['A']['points']['ZA'] == [0.6, 0.5, -1.5]


def test_store_numbers_events_and_filters():
    store, _ = make_store()
    store.put(json.dumps(dict(SNAPSHOT, events=[
        {'robot': 'pinky1', 'kind': 'state', 'text': 'a'},
        {'robot': None, 'kind': 'zone', 'text': 'b'}, 'broken'])))
    store.put(json.dumps(dict(SNAPSHOT, events=[{'robot': 'pinky2', 'text': 'c'}])))
    # 스냅샷에는 그 주기의 새 이벤트만 번호가 붙어 남는다.
    assert store.get()[1]['events'] == [{'robot': 'pinky2', 'text': 'c', 'id': 3}]
    assert [e['id'] for e in store.events()] == [1, 2, 3]
    assert [e['text'] for e in store.events(after=1)] == ['b', 'c']
    assert [e['text'] for e in store.events(robot='pinky1')] == ['a']
    assert [e['id'] for e in store.events(limit=1)] == [3]
    store.put(json.dumps(SNAPSHOT))
    assert store.get()[1]['events'] == []


def test_store_events_max():
    store = SnapshotStore(3.0, events_max=2)
    store.put(json.dumps(dict(SNAPSHOT, events=[{'text': t} for t in 'abc'])))
    assert [e['text'] for e in store.events()] == ['b', 'c']


def test_events_route():
    store, _ = make_store()
    store.put(json.dumps(dict(SNAPSHOT, events=[{'robot': 'pinky1', 'text': 'a'},
                                                {'robot': 'pinky2', 'text': 'b'}])))
    client = TestClient(create_app(store))
    assert [e['id'] for e in client.get('/api/events').json()] == [1, 2]
    assert client.get('/api/events', params={'after': 1}).json()[0]['text'] == 'b'
    assert client.get('/api/events', params={'robot': 'pinky1'}).json()[0]['text'] == 'a'
    assert client.get('/api/events', params={'limit': 0}).status_code == 422


# ---------- 명령 (TaskStore, /api/tasks) ----------

TASK = {'task_id': 't-1', 'robot_id': 'pinky1', 'operation': 'goto', 'points': ['P1'],
        'command': 'goto:P1', 'spec': 'v1', 'state': 'SENT', 'detail': '',
        'created_at': 10.0, 'updated_at': 10.0, 'history': []}


def make_task_store():
    clock = FakeClock()
    return TaskStore(3.0, 0.5, clock=clock), clock


def fake_task_manager(tasks, status, body):
    """요청을 받으면 곧바로 정해진 응답을 돌려주는 task_manager 대역. 받은 요청을 모은다."""
    sent = []

    def publish(text):
        request = json.loads(text)
        sent.append(request)
        reply = {'type': 'reply', 'request_id': request['request_id'],
                 'status': status, 'body': body}
        threading.Thread(target=tasks.put_event, args=(json.dumps(reply),)).start()
    return publish, sent


def test_task_store_snapshot_and_changes():
    tasks, clock = make_task_store()
    assert tasks.online() is False
    assert tasks.put_snapshot('not json') is False
    assert tasks.put_snapshot(json.dumps({'tasks': [TASK]})) is True
    assert tasks.online() is True
    seq = tasks.seq()
    assert tasks.changes_since(0) == (seq, [TASK])
    # 같은 값은 변화가 아니다
    tasks.put_snapshot(json.dumps({'tasks': [TASK]}))
    assert tasks.seq() == seq
    running = dict(TASK, state='RUNNING')
    assert tasks.put_event(json.dumps({'type': 'task', 'task': running}))
    assert tasks.changes_since(seq) == (seq + 1, [running])
    assert tasks.tasks(state='RUNNING') == [running]
    assert tasks.tasks(robot_id='pinky2') == []
    clock.now = 3.5
    assert tasks.online() is False


def test_task_store_request_times_out_without_reply():
    tasks, _ = make_task_store()
    assert tasks.request({'type': 'create'}, lambda text: None) is None


def test_api_create_task_passes_through():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    publish, sent = fake_task_manager(tasks, 202, TASK)
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/tasks', json={'client_request_id': 'r1', 'robot_id': 'pinky1',
                                          'operation': 'goto', 'points': ['P1']})
    assert res.status_code == 202
    assert res.json()['task_id'] == 't-1'
    assert sent[0]['type'] == 'create' and sent[0]['points'] == ['P1']
    assert client.get('/api/health').json()['task_manager_online'] is True


def test_api_rejected_task_returns_reason_and_task():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    rejected = dict(TASK, state='REJECTED', detail="unknown point: ['P99']")
    publish, _ = fake_task_manager(tasks, 400, rejected)
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/tasks', json={'client_request_id': 'r1', 'robot_id': 'pinky1',
                                          'operation': 'goto', 'points': ['P99']})
    assert res.status_code == 400
    assert res.json()['detail'] == "unknown point: ['P99']"
    assert res.json()['task']['state'] == 'REJECTED'


def test_api_stop_and_resolve_and_list():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': [TASK]}))
    publish, sent = fake_task_manager(tasks, 202, {'robot_id': 'pinky1', 'operation': 'stop'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    assert client.post('/api/robots/pinky1/stop', json={'emergency': True}).status_code == 202
    assert sent[0] == dict(sent[0], type='stop', robot_id='pinky1', emergency=True)
    client.post('/api/tasks/t-1/resolve', json={'note': '확인'})
    assert sent[1]['type'] == 'resolve' and sent[1]['task_id'] == 't-1'
    assert [t['task_id'] for t in client.get('/api/tasks').json()] == ['t-1']
    assert client.get('/api/tasks/t-1').json()['command'] == 'goto:P1'
    assert client.get('/api/tasks/t-9').status_code == 404


def test_api_raw_cmd_passes_through_and_health_flag():
    store, _ = make_store()
    tasks, clock = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    publish, sent = fake_task_manager(tasks, 202, {'robot_id': 'pinky1', 'command': 'home'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    # 작업 노드가 allow_raw_cmd 를 알리지 않으면 수동 명령 칸을 숨긴다
    assert client.get('/api/health').json()['raw_cmd_enabled'] is False
    tasks.put_snapshot(json.dumps({'tasks': [], 'allow_raw_cmd': True}))
    assert client.get('/api/health').json()['raw_cmd_enabled'] is True
    res = client.post('/api/robots/pinky1/raw_cmd',
                      json={'client_request_id': 'r1', 'command': 'home'})
    assert res.status_code == 202
    assert sent[0] == dict(sent[0], type='raw', robot_id='pinky1', command='home')
    # 작업 노드가 끊기면 켜져 있어도 숨긴다
    clock.now = 3.5
    assert client.get('/api/health').json()['raw_cmd_enabled'] is False


def test_api_arm_passes_through_and_health_flag():
    store, _ = make_store()
    tasks, clock = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    publish, sent = fake_task_manager(tasks, 200, {'armed': True, 'changed': True})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    # 작업 노드가 armed 를 알리지 않으면 잠김으로 본다
    assert client.get('/api/health').json()['commands_armed'] is False
    res = client.post('/api/commands/arm', json={'client_request_id': 'a1', 'armed': True})
    assert res.status_code == 200 and res.json()['armed'] is True
    assert sent[0] == dict(sent[0], type='arm', armed=True, client_request_id='a1')
    assert sent[0]['source'] == 'testclient'
    tasks.put_snapshot(json.dumps({'tasks': [], 'armed': True}))
    assert client.get('/api/health').json()['commands_armed'] is True
    # 작업 노드가 끊기면 허용으로 보이지 않는다
    clock.now = 3.5
    assert client.get('/api/health').json()['commands_armed'] is False


def test_api_locked_create_returns_423():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    publish, _ = fake_task_manager(tasks, 423, {'detail': '작업 명령 꺼짐'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/tasks', json={'client_request_id': 'r1', 'robot_id': 'pinky1',
                                          'operation': 'home'})
    assert res.status_code == 423 and res.json()['detail'] == '작업 명령 꺼짐'


def test_api_read_only_backend_lists_tasks_but_refuses_commands():
    # 개발용(fleet_api_dev): 작업 목록은 보이지만 명령은 하나도 넘기지 않는다.
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': [TASK], 'armed': True}))
    client = TestClient(create_app(store, tasks=tasks, publish_request=None))
    health = client.get('/api/health').json()
    assert health['read_only'] is True and health['task_manager_online'] is True
    assert [t['task_id'] for t in client.get('/api/tasks').json()] == ['t-1']
    for url, body in (('/api/tasks', {'client_request_id': 'r1', 'robot_id': 'pinky1',
                                      'operation': 'home'}),
                      ('/api/commands/arm', {'armed': False}),
                      ('/api/robots/pinky1/stop', {'emergency': True}),
                      ('/api/robots/pinky1/raw_cmd', {'command': 'home'}),
                      ('/api/tasks/t-1/resolve', {})):
        res = client.post(url, json=body)
        assert res.status_code == 503 and '읽기 전용' in res.json()['detail'], url
    publish, _ = fake_task_manager(tasks, 200, {})
    full = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    assert full.get('/api/health').json()['read_only'] is False


def test_api_task_manager_offline_is_503():
    store, _ = make_store()
    tasks, _ = make_task_store()
    publish, sent = fake_task_manager(tasks, 202, TASK)
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    body = {'client_request_id': 'r1', 'robot_id': 'pinky1', 'operation': 'home'}
    assert client.post('/api/tasks', json=body).status_code == 503
    assert sent == []


def test_websocket_tasks_sends_list_then_changes():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': [TASK]}))
    client = TestClient(create_app(store, tasks=tasks, publish_request=lambda text: None))
    with client.websocket_connect('/ws/tasks') as ws:
        assert ws.receive_json() == {'type': 'tasks', 'tasks': [TASK]}
        done = dict(TASK, state='SUCCEEDED')
        tasks.put_event(json.dumps({'type': 'task', 'task': done}))
        assert ws.receive_json() == {'type': 'task', 'task': done}
