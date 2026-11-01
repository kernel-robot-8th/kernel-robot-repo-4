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
    LayerError, load_map, load_map_layers, MapError, SnapshotStore)
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
        'ok': True, 'domain_id': None, 'source_online': False, 'source_age': None}
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


def test_api_has_no_command_routes():
    # 읽기 전용: 쓰기 메서드를 받는 경로가 없어야 한다.
    store, _ = make_store()
    app = create_app(store)
    methods = {m for route in app.routes for m in (getattr(route, 'methods', None) or ())}
    assert methods <= {'GET', 'HEAD'}


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
    for name in ('index.html', 'app.js', 'style.css'):
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


def robot_yaml(robot, home, zb=(0.6, -0.15, -1.5)):
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
"""


def write_layers(tmp_path, zb2=(0.6, -0.15, -1.5)):
    (tmp_path / 'pinky1.yaml').write_text(robot_yaml('pinky1', 'I1'), encoding='utf-8')
    (tmp_path / 'pinky2.yaml').write_text(robot_yaml('pinky2', 'I2', zb2), encoding='utf-8')
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
    json.dumps(layers)


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
