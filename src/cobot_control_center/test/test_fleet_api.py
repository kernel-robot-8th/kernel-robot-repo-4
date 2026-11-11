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
    active_orders, CameraStore, LayerError, load_confirmable, load_map, load_map_layers,
    load_robot_params, MapError, mjpeg_part, SnapshotStore,
    TaskStore)
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
        'source_age': None, 'controller_online': False, 'cameras': {}}
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


def test_api_without_controller_is_read_only():
    # 작업 노드를 넘기지 않으면 명령 경로는 503 이고 아무것도 발행하지 않는다.
    store, _ = make_store()
    client = TestClient(create_app(store))
    body = {'client_request_id': 'r1', 'robot_id': 'pinky1', 'operation': 'home'}
    assert client.post('/api/tasks', json=body).status_code == 503
    assert client.post('/api/robots/pinky1/stop', json={}).status_code == 503
    assert client.get('/api/tasks').status_code == 503
    assert client.get('/api/health').json()['controller_online'] is False


# 내용은 검사하지 않는다 (백엔드는 JPEG 를 풀지 않고 그대로 넘긴다).
JPEG = b'\xff\xd8fake-jpeg\xff\xd9'


def test_camera_store_put_latest_and_health():
    clock = FakeClock()
    cameras = CameraStore(['pinky1', 'pinky2'], clock=clock)
    assert cameras.robots() == ['pinky1', 'pinky2']
    assert cameras.latest('pinky1') is None
    assert cameras.health() == {'pinky1': {'age_sec': None, 'frames': 0},
                                'pinky2': {'age_sec': None, 'frames': 0}}
    # 설정에 없는 로봇·빈 프레임은 버린다.
    assert cameras.put('pinky9', JPEG) is False
    assert cameras.put('pinky1', b'') is False
    clock.now = 5.0
    assert cameras.put('pinky1', bytearray(JPEG)) is True
    clock.now = 7.5
    assert cameras.latest('pinky1') == (1, JPEG)
    assert cameras.health()['pinky1'] == {'age_sec': 2.5, 'frames': 1}
    assert cameras.health()['pinky2'] == {'age_sec': None, 'frames': 0}


def test_camera_store_wait_newer_is_per_robot():
    cameras = CameraStore(['pinky1', 'pinky2'])
    assert cameras.wait_newer('pinky1', 0, 0.01) is False
    cameras.put('pinky2', JPEG)
    # 다른 로봇 프레임으로는 깨지 않는다.
    assert cameras.wait_newer('pinky1', 0, 0.01) is False
    timer = threading.Timer(0.05, cameras.put, args=['pinky1', JPEG])
    timer.start()
    assert cameras.wait_newer('pinky1', 0, 2.0) is True
    timer.join()


def test_mjpeg_part():
    part = mjpeg_part(JPEG)
    assert part.startswith(b'--frame\r\nContent-Type: image/jpeg\r\n')
    assert f'Content-Length: {len(JPEG)}\r\n\r\n'.encode() in part
    assert part.endswith(JPEG + b'\r\n')


def test_camera_routes():
    store, _ = make_store()
    cameras = CameraStore(['pinky1'])
    client = TestClient(create_app(store, cameras=cameras))
    assert client.get('/api/health').json()['cameras'] == {
        'pinky1': {'age_sec': None, 'frames': 0}}
    # 받은 프레임이 없으면 404, 받으면 바이트 그대로.
    assert client.get('/api/robots/pinky1/camera.jpg').status_code == 404
    cameras.put('pinky1', JPEG)
    frame = client.get('/api/robots/pinky1/camera.jpg')
    assert frame.status_code == 200
    assert frame.headers['content-type'] == 'image/jpeg'
    assert frame.content == JPEG
    # 구독하지 않는 로봇, 카메라 없이 만든 앱은 404.
    assert client.get('/api/robots/pinky9/camera.jpg').status_code == 404
    assert client.get('/api/robots/pinky9/camera').status_code == 404
    without = TestClient(create_app(store))
    assert without.get('/api/robots/pinky1/camera').status_code == 404


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
    page = client.get('/')
    assert '관제' in page.text
    # 화면 파일은 브라우저가 매번 다시 확인한다 (고친 화면이 캐시에 가려지지 않게).
    assert page.headers['cache-control'] == 'no-cache'
    assert client.get('/api/health').json()['ok'] is True
    assert client.post('/api/fleet').status_code == 405


def test_installed_web_files_exist():
    # 화면 파일이 패키지 소스에 있는지 본다 (setup.py data_files 가 web/* 를 설치한다).
    web = os.path.join(os.path.dirname(__file__), '..', 'web')
    for name in ('index.html', 'style.css', 'core.js', 'cards.js', 'events.js',
                 'commands.js', 'tasks.js', 'release.js', 'map.js', 'raw.js', 'detail.js',
                 'main.js'):
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


def write_split_config(tmp_path):
    """순찰 설정의 나뉜 구조: common.yaml, sites/lab.yaml, robots/<robot>.yaml."""
    (tmp_path / 'sites').mkdir()
    (tmp_path / 'robots').mkdir()
    head = 'pinky_patrol_node:\n  ros__parameters:\n'
    (tmp_path / 'common.yaml').write_text(
        head + '    idle_return_sec: 120.0\n    home_name: X\n', encoding='utf-8')
    (tmp_path / 'sites' / 'lab.yaml').write_text(
        head + '    zone_points:\n      A: [ZA]\n    points:\n      I1: [0.0, 0.0, 0.0]\n'
        '      ZA: [0.6, 0.5, -1.5]\n      P1: [0.17, -0.6, 0.0]\n', encoding='utf-8')
    (tmp_path / 'robots' / 'pinky1.yaml').write_text(
        head + '    robot_id: pinky1\n    home_name: I1\n', encoding='utf-8')
    return str(tmp_path)


def test_load_robot_params_merges_split_files_in_launch_order(tmp_path):
    params = load_robot_params(write_split_config(tmp_path), 'pinky1')
    assert params['idle_return_sec'] == 120.0
    assert params['home_name'] == 'I1'   # 뒤 파일(로봇)이 공통 값을 덮어쓴다
    assert set(params['points']) == {'I1', 'ZA', 'P1'}


def test_load_robot_params_prefers_flat_profile(tmp_path):
    points_dir = write_split_config(tmp_path)
    (tmp_path / 'pinky1.yaml').write_text(robot_yaml('pinky1', 'I1'), encoding='utf-8')
    assert 'P10' in load_robot_params(points_dir, 'pinky1')['points']


def test_load_robot_params_reports_missing_split_file(tmp_path):
    points_dir = write_split_config(tmp_path)
    with pytest.raises(LayerError, match='pinky2.yaml'):
        load_robot_params(points_dir, 'pinky2')
    with pytest.raises(LayerError, match='other.yaml'):
        load_robot_params(points_dir, 'pinky1', 'other')


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


def fake_controller(tasks, status, body):
    """요청을 받으면 곧바로 정해진 응답을 돌려주는 작업 노드(fleet_control_node) 대역. 받은 요청을 모은다."""
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
    publish, sent = fake_controller(tasks, 202, TASK)
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/tasks', json={'client_request_id': 'r1', 'robot_id': 'pinky1',
                                          'operation': 'goto', 'points': ['P1']})
    assert res.status_code == 202
    assert res.json()['task_id'] == 't-1'
    assert sent[0]['type'] == 'create' and sent[0]['points'] == ['P1']
    assert client.get('/api/health').json()['controller_online'] is True


def test_api_rejected_task_returns_reason_and_task():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    rejected = dict(TASK, state='REJECTED', detail="unknown point: ['P99']")
    publish, _ = fake_controller(tasks, 400, rejected)
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
    publish, sent = fake_controller(tasks, 202, {'robot_id': 'pinky1', 'operation': 'stop'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    assert client.post('/api/robots/pinky1/stop', json={}).status_code == 202
    assert sent[0] == dict(sent[0], type='stop', robot_id='pinky1')
    client.post('/api/tasks/t-1/resolve', json={'note': '확인'})
    assert sent[1]['type'] == 'resolve' and sent[1]['task_id'] == 't-1'
    assert [t['task_id'] for t in client.get('/api/tasks').json()] == ['t-1']
    assert client.get('/api/tasks/t-1').json()['command'] == 'goto:P1'
    assert client.get('/api/tasks/t-9').status_code == 404


def test_api_raw_cmd_passes_through_and_health_flag():
    store, _ = make_store()
    tasks, clock = make_task_store()
    tasks.put_snapshot(json.dumps({'tasks': []}))
    publish, sent = fake_controller(tasks, 202, {'robot_id': 'pinky1', 'command': 'home'})
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
    publish, sent = fake_controller(tasks, 200, {'armed': True, 'changed': True})
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
    publish, _ = fake_controller(tasks, 423, {'detail': '작업 명령 꺼짐'})
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
    assert health['read_only'] is True and health['controller_online'] is True
    assert [t['task_id'] for t in client.get('/api/tasks').json()] == ['t-1']
    for url, body in (('/api/tasks', {'client_request_id': 'r1', 'robot_id': 'pinky1',
                                      'operation': 'home'}),
                      ('/api/commands/arm', {'armed': False}),
                      ('/api/robots/pinky1/stop', {'emergency': True}),
                      ('/api/robots/pinky1/raw_cmd', {'command': 'home'}),
                      ('/api/tasks/t-1/resolve', {})):
        res = client.post(url, json=body)
        assert res.status_code == 503 and '읽기 전용' in res.json()['detail'], url
    publish, _ = fake_controller(tasks, 200, {})
    full = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    assert full.get('/api/health').json()['read_only'] is False


def test_api_controller_offline_is_503():
    store, _ = make_store()
    tasks, _ = make_task_store()
    publish, sent = fake_controller(tasks, 202, TASK)
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


# ---------- fleet_control 전용 요청 (비상정지·복구·수동 상차 확인) ----------

# cobot_fleet_control 의 ControlAPI.snapshot() 모양 (orders·holds 를 함께 낸다)
FLEET_SNAPSHOT = {'time': 1.0, 'armed': False, 'allow_raw_cmd': False,
                  'robots': ['pinky1', 'pinky2'], 'spec': {'pinky1': 'v1', 'pinky2': 'v1'},
                  'tasks': [], 'orders': [], 'holds': {'pinky1': 'ESTOP'}}
RELEASE_BODY = {'operator': 'jihye', 'note': '현장 확인',
                'evidence': {'base_stopped': True, 'arms_safe': True,
                             'cargo_reconciled': True, 'resources_clear': True}}
LOADED_BODY = {'operator': 'jihye', 'note': '실물 상차 확인',
               'evidence': {'sku': 'box_a', 'load_present': True, 'arm_safe': True,
                            'pickup_path_clear': True}}


def test_health_reports_holds():
    store, _ = make_store()
    tasks, clock = make_task_store()
    client = TestClient(create_app(store, tasks=tasks, publish_request=lambda text: None))
    health = client.get('/api/health').json()
    assert 'controller' not in health
    assert health['holds'] == {} and health['orders'] == []
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    health = client.get('/api/health').json()
    assert health['holds'] == {'pinky1': 'ESTOP'}
    # allow_raw_cmd 가 꺼져 있으면 수동 명령 칸이 숨는다
    assert health['raw_cmd_enabled'] is False
    # 작업 노드가 끊기면 보류·주문을 보이지 않는다
    clock.now = 3.5
    health = client.get('/api/health').json()
    assert health['holds'] == {} and health['orders'] == []


def test_fleet_emergency_stop_becomes_estop():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    publish, sent = fake_controller(tasks, 202, {'robot_id': 'pinky1', 'armed': False})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    assert client.post('/api/robots/pinky1/stop',
                       json={'client_request_id': 'c1', 'emergency': True}).status_code == 202
    assert sent[0] == dict(sent[0], type='estop', robot_id='pinky1', client_request_id='c1')
    assert 'emergency' not in sent[0]
    # 일반 정지는 그대로 stop
    client.post('/api/robots/pinky1/stop', json={'emergency': False})
    assert sent[1] == dict(sent[1], type='stop', robot_id='pinky1')
    assert 'emergency' not in sent[1]


def test_fleet_estop_all_and_release_control_pass_through():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    publish, sent = fake_controller(tasks, 409, {'detail': '해제 불가: 구역 이탈 미확인'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    client.post('/api/commands/estop', json={'client_request_id': 'e1'})
    assert sent[0] == dict(sent[0], type='estop', client_request_id='e1')
    assert 'robot_id' not in sent[0]
    res = client.post('/api/robots/pinky1/release_control', json=RELEASE_BODY)
    # fleet 의 거절 사유를 그대로 돌려준다
    assert res.status_code == 409 and res.json()['detail'] == '해제 불가: 구역 이탈 미확인'
    assert sent[1] == dict(sent[1], type='release_control', robot_id='pinky1', **RELEASE_BODY)
    # 화면은 확인 창 한 번 뒤 빈 body 로 보낸다. 누가는 접속 IP(source)로 넘긴다
    client.post('/api/robots/pinky1/release_control', json={'client_request_id': 'r2'})
    assert sent[2]['source'] == 'testclient' and sent[2]['operator'] is None


def test_fleet_initial_pose_passes_through_with_source():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    reply = {'robot_id': 'pinky2', 'point': 'I2', 'x': 0.0, 'y': -0.2, 'yaw': 0.0}
    publish, sent = fake_controller(tasks, 202, reply)
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/robots/pinky2/initial_pose', json={'client_request_id': 'p1'})
    assert res.status_code == 202 and res.json()['point'] == 'I2'
    # 좌표는 보내지 않는다: 홈 좌표는 fleet_control 이 순찰 설정에서 읽는다
    assert sent[0] == {'type': 'initial_pose', 'robot_id': 'pinky2',
                       'client_request_id': 'p1', 'source': 'testclient',
                       'request_id': sent[0]['request_id']}


def test_fleet_confirm_loaded_passes_through():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    publish, sent = fake_controller(tasks, 200, {'order_id': 'o1', 'stage': 'LEAVE_PICKUP'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/orders/o1/confirm_loaded',
                      json=dict(LOADED_BODY, client_request_id='c1'))
    assert res.status_code == 200 and res.json()['stage'] == 'LEAVE_PICKUP'
    assert sent[0] == dict(sent[0], type='confirm_loaded', order_id='o1',
                           client_request_id='c1', **LOADED_BODY)


def test_fleet_order_recover_passes_through_with_source():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    publish, sent = fake_controller(tasks, 200, {'order_id': 'o1', 'state': 'RUNNING'})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/orders/o1/recover',
                      json={'client_request_id': 'r1', 'decision': 'resume'})
    assert res.status_code == 200 and res.json()['state'] == 'RUNNING'
    # fleet 은 resolve + order_id 를 주문 복구로 보낸다 (task_id 가 없어야 함)
    assert sent[0] == dict(sent[0], type='resolve', order_id='o1', decision='resume',
                           client_request_id='r1', source='testclient')
    assert 'task_id' not in sent[0]


def test_fleet_confirm_loaded_returns_rejection_reason():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(FLEET_SNAPSHOT))
    reason = '상차장 도착 완료 후 상차 검증 중인 주문만 수동 확인 가능'
    publish, _ = fake_controller(tasks, 400, {'detail': reason})
    client = TestClient(create_app(store, tasks=tasks, publish_request=publish))
    res = client.post('/api/orders/o1/confirm_loaded', json=LOADED_BODY)
    # fleet 의 거절 사유를 그대로 돌려준다
    assert res.status_code == 400 and res.json()['detail'] == reason


# ---------- 화면용 주문 목록 (수동 상차 확인 버튼) ----------

# fleet 의 주문 원장 사본 모양 (scenario.submit). 상차장 도착 뒤 상차 검증에서 멈춘 주문.
WAITING_LOAD = {'order_id': 'o1', 'sku': 'box_a', 'route': 'lab_delivery', 'kind': 'delivery',
                'quantity': 1, 'input': {'order_id': 'o1'}, 'state': 'RUNNING',
                'stage': 'DOCK_PICKUP', 'robot_id': 'pinky1', 'completed': ['MOVE_PICKUP'],
                'detail': '정차 실측 대기', 'failure': None}


def test_load_confirmable_matches_fleet_rule():
    assert load_confirmable(WAITING_LOAD) is True
    for stage in ('PICKUP_EXIT', 'CORRECT_PICKUP', 'VERIFY_LOAD'):
        assert load_confirmable(dict(WAITING_LOAD, stage=stage)) is True, stage
    assert load_confirmable(dict(WAITING_LOAD, state='UNKNOWN')) is True
    # 아직 상차장에 가는 중
    assert load_confirmable(dict(WAITING_LOAD, stage='MOVE_PICKUP', completed=[])) is False
    # 상차장 도착 기록이 없음
    assert load_confirmable(dict(WAITING_LOAD, completed=[])) is False
    # 상차 뒤 단계
    assert load_confirmable(dict(WAITING_LOAD, stage='LEAVE_PICKUP')) is False
    # 로봇 배정 전, 실패, 끝남, 이미 확인함
    assert load_confirmable(dict(WAITING_LOAD, robot_id=None)) is False
    assert load_confirmable(dict(WAITING_LOAD, failure='timeout')) is False
    assert load_confirmable(dict(WAITING_LOAD, state='FAILED')) is False
    assert load_confirmable(dict(WAITING_LOAD, operator_load_confirmation={'operator': 'a'})) \
        is False
    assert load_confirmable(dict(WAITING_LOAD, manual_load_pending={'operator': 'a'})) is False


def test_active_orders_hide_finished_and_internal_fields():
    orders = [WAITING_LOAD,
              dict(WAITING_LOAD, order_id='o2', state='COMPLETED'),
              dict(WAITING_LOAD, order_id='o3', state='FAILED'),
              dict(WAITING_LOAD, order_id='o4', state='WAITING', stage='MOVE_PICKUP',
                   robot_id=None, completed=[]),
              dict(WAITING_LOAD, order_id='o5', stage='LEAVE_PICKUP',
                   operator_load_confirmation={'operator': 'jihye'}),
              'broken']
    result = active_orders(orders)
    assert [o['order_id'] for o in result] == ['o1', 'o4', 'o5']
    assert result[0] == {'order_id': 'o1', 'robot_id': 'pinky1', 'state': 'RUNNING',
                         'stage': 'DOCK_PICKUP', 'completed': ['MOVE_PICKUP'], 'sku': 'box_a',
                         'route': 'lab_delivery', 'detail': '정차 실측 대기',
                         'load_confirmed': False, 'load_confirmable': True,
                         'blocked': False, 'resumable': False}
    assert result[1]['load_confirmable'] is False
    assert result[2]['load_confirmed'] is True and result[2]['load_confirmable'] is False
    assert active_orders(None) == [] and active_orders({'o1': {}}) == []


def test_active_orders_mark_blocked_and_resumable():
    # 멈춘 주문: 이동 단계면 이어서 가기, 팔 단계면 취소만 (fleet scenario_safety.recover 와 같음)
    driving = dict(WAITING_LOAD, state='ESTOP', stage='MOVE_DROPOFF')
    arm = dict(WAITING_LOAD, state='ESTOP', stage='LOAD')
    waiting = dict(WAITING_LOAD, state='PAUSED', stage='MOVE_PICKUP', robot_id=None)
    first, second, third = active_orders([driving, arm, waiting])
    assert first['blocked'] and first['resumable']
    assert second['blocked'] and not second['resumable']
    assert not third['blocked']


def test_health_reports_active_orders():
    store, _ = make_store()
    tasks, _ = make_task_store()
    tasks.put_snapshot(json.dumps(dict(
        FLEET_SNAPSHOT, orders=[WAITING_LOAD, dict(WAITING_LOAD, order_id='o2',
                                                   state='COMPLETED')])))
    client = TestClient(create_app(store, tasks=tasks, publish_request=lambda text: None))
    orders = client.get('/api/health').json()['orders']
    assert [o['order_id'] for o in orders] == ['o1']
    assert orders[0]['load_confirmable'] is True and 'input' not in orders[0]
