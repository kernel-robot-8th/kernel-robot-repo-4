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

"""관제 웨이포인트·묶음 (waypoint_utils.py, /api/waypoints, 이동·경로의 poses) 을 ROS 없이 검사한다."""

import json
import math
import threading

from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import SnapshotStore, TaskStore
from cobot_control_center.route_utils import split_route
from cobot_control_center.waypoint_utils import WaypointError, WaypointStore
from fastapi.testclient import TestClient
import pytest

LAYERS = {
    'points': {'P1': [1.0, 0.0, 0.0], 'P2': [2.0, 0.0, 0.0]},
    'zones': {'A': {'points': {'ZA': [3.0, 0.0, 0.0]},
                    'exit': {'name': 'ZA_EXIT', 'pose': [3.0, -1.0, 0.0]}, 'queue': []}},
    'homes': {'pinky1': {'name': 'I1', 'pose': [0.0, 0.0, 0.0]}},
}


def robot(x=5.0, y=5.0, yaw=0.5, online=True, warnings=()):
    return {'online': online, 'state': 'IDLE', 'pose': {'x': x, 'y': y, 'yaw': yaw},
            'teach': {'warnings': list(warnings)}}


def make_store(tmp_path, clock=None):
    ticks = iter(range(100, 1000)) if clock is None else clock
    return WaypointStore(str(tmp_path / 'w' / 'waypoints.json'), 'lab', LAYERS, 0.3,
                         clock=lambda: next(ticks))


def test_capture_auto_name_persists_and_reloads(tmp_path):
    store = make_store(tmp_path)
    first = store.capture('pinky1', robot(warnings=['이동 중']))
    assert first['name'] == 'W1' and first['x'] == 5.0 and first['warnings'] == ['이동 중']
    assert store.capture('pinky1', robot(x=6.0), name='dock_1')['name'] == 'DOCK_1'
    assert store.capture('pinky1', robot(x=7.0))['name'] == 'W2'
    again = make_store(tmp_path)
    assert [w['name'] for w in again.snapshot()['waypoints']] == ['W1', 'DOCK_1', 'W2']
    assert again.poses_for(['P1', 'W1']) == {'W1': [5.0, 5.0, 0.5]}


@pytest.mark.parametrize('kwargs,status,text', [
    ({'name': 'P1'}, 409, '로봇 설정'),
    ({'name': 'ZA_EXIT'}, 409, '로봇 설정'),
    ({'name': '1W'}, 400, '이름은'),
    ({'name': 'W' * 17}, 400, '이름은'),
])
def test_capture_name_rules(tmp_path, kwargs, status, text):
    with pytest.raises(WaypointError) as error:
        make_store(tmp_path).capture('pinky1', robot(), **kwargs)
    assert error.value.status == status and text in error.value.detail


def test_capture_refuses_unknown_offline_and_near_zone(tmp_path):
    store = make_store(tmp_path)
    for args, status in ((('pinky9', None), 404), (('pinky1', robot(online=False)), 409),
                         (('pinky1', {'online': True}), 409)):
        with pytest.raises(WaypointError) as error:
            store.capture(*args)
        assert error.value.status == status
    with pytest.raises(WaypointError, match='ZA'):
        store.capture('pinky1', robot(x=3.1, y=0.1))
    with pytest.raises(WaypointError, match='ZA_EXIT'):
        store.capture('pinky1', robot(x=3.0, y=-0.8))
    store.capture('pinky1', robot(x=3.0, y=0.5))   # 0.5 m 떨어지면 된다
    with pytest.raises(WaypointError):
        store.capture('pinky1', robot(), name='W1')   # 이미 있는 이름


def test_rename_and_delete_follow_groups(tmp_path):
    store = make_store(tmp_path)
    store.capture('pinky1', robot())
    store.capture('pinky1', robot(x=6.0))
    group = store.set_group('1층 순찰', ['p1', 'W1', 'ZA', 'W2', 'I1'], note='아침')
    assert group['points'] == ['P1', 'W1', 'ZA', 'W2', 'I1']
    store.update('W1', new_name='DOCK', note='충전기 앞')
    snap = store.snapshot()
    assert snap['groups'][0]['points'] == ['P1', 'DOCK', 'ZA', 'W2', 'I1']
    assert {w['name']: w['note'] for w in snap['waypoints']}['DOCK'] == '충전기 앞'
    assert store.delete('W2') == {'deleted': 'W2', 'groups_changed': ['1층 순찰']}
    assert make_store(tmp_path).snapshot()['groups'][0]['points'] == ['P1', 'DOCK', 'ZA', 'I1']
    with pytest.raises(WaypointError, match='모르는 지점'):
        store.set_group('x', ['W9'])
    with pytest.raises(WaypointError):
        store.set_group('x', [])
    assert store.delete_group('1층 순찰') == {'deleted': '1층 순찰'}
    with pytest.raises(WaypointError):
        store.delete_group('1층 순찰')


def test_broken_file_blocks_writes_but_not_reads(tmp_path):
    path = tmp_path / 'w' / 'waypoints.json'
    path.parent.mkdir()
    path.write_text('{broken', encoding='utf-8')
    store = make_store(tmp_path)
    assert store.load_error and store.snapshot()['waypoints'] == []
    with pytest.raises(WaypointError) as error:
        store.capture('pinky1', robot())
    assert error.value.status == 503
    assert path.read_text(encoding='utf-8') == '{broken'   # 덮어쓰지 않는다


def test_export_yaml(tmp_path):
    store = make_store(tmp_path)
    store.capture('pinky1', robot(x=0.1234, y=-0.4567, yaw=1.5708))
    store.capture('pinky1', robot(x=6.0))
    text = store.export_yaml(['W1'])
    assert '  W1: [0.123, -0.457, 1.57]' in text and 'W2' not in text


def test_split_route_carries_poses_for_waypoints():
    legs = split_route(['P1', 'W1', 'ZA', 'W2', 'I1'], LAYERS, 'pinky1',
                       {'W1': [5.0, 5.0, 0.0], 'W2': [6.0, 5.0, 0.0]})
    assert legs == [
        {'operation': 'goto', 'points': ['P1', 'W1'], 'poses': {'W1': [5.0, 5.0, 0.0]}},
        {'operation': 'zone', 'points': ['ZA']},
        {'operation': 'goto', 'points': ['W2', 'I1'], 'poses': {'W2': [6.0, 5.0, 0.0]}},
    ]
    assert 'poses' not in split_route(['P1', 'P2'], LAYERS, 'pinky1')[0]


# ---------- API ----------

class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_client(tmp_path, read_only=False):
    store = SnapshotStore(3.0, clock=FakeClock())
    store.put(json.dumps({'time': 1.0, 'robots': {'pinky1': robot()}, 'zones': {}}))
    tasks = TaskStore(3.0, 0.5, clock=FakeClock())
    tasks.put_snapshot(json.dumps({'tasks': [], 'armed': True}))
    sent = []

    def publish(text):
        request = json.loads(text)
        sent.append(request)
        reply = {'type': 'reply', 'request_id': request['request_id'], 'status': 202,
                 'body': {'task_id': 't1', 'state': 'ACCEPTED'}}
        threading.Thread(target=tasks.put_event, args=(json.dumps(reply),)).start()

    client = TestClient(create_app(store, layers=LAYERS, tasks=tasks,
                                   publish_request=None if read_only else publish,
                                   waypoints=make_store(tmp_path)))
    return client, sent


def test_api_waypoint_lifecycle(tmp_path):
    client, _ = make_client(tmp_path)
    res = client.post('/api/waypoints', json={'robot_id': 'pinky1'})
    assert res.status_code == 201 and res.json()['name'] == 'W1'
    assert client.post('/api/waypoints', json={'robot_id': 'pinky9'}).status_code == 404
    assert client.patch('/api/waypoints/W1', json={'name': 'DOCK'}).json()['name'] == 'DOCK'
    res = client.put('/api/waypoint_groups/아침', json={'points': ['P1', 'DOCK', 'ZA']})
    assert res.status_code == 200 and res.json()['points'] == ['P1', 'DOCK', 'ZA']
    data = client.get('/api/waypoints').json()
    assert [w['name'] for w in data['waypoints']] == ['DOCK'] and data['groups'][0]['name'] == '아침'
    assert 'DOCK: [5.000, 5.000, 0.50]' in client.get('/api/waypoints/export').text
    assert client.delete('/api/waypoints/DOCK').json()['groups_changed'] == ['아침']
    assert client.delete('/api/waypoint_groups/아침').status_code == 200
    assert client.delete('/api/waypoints/NOPE').status_code == 404


def test_api_task_and_route_attach_poses(tmp_path):
    client, sent = make_client(tmp_path)
    client.post('/api/waypoints', json={'robot_id': 'pinky1'})
    res = client.post('/api/tasks', json={'robot_id': 'pinky1', 'operation': 'goto',
                                          'points': ['P1', 'w1'], 'client_request_id': 'c1'})
    assert res.status_code == 202
    assert sent[-1]['points'] == ['P1', 'W1'] and sent[-1]['poses'] == {'W1': [5.0, 5.0, 0.5]}
    client.post('/api/tasks', json={'robot_id': 'pinky1', 'operation': 'goto',
                                    'points': ['P1'], 'client_request_id': 'c2'})
    assert 'poses' not in sent[-1]


def test_api_read_only_can_read_but_not_write(tmp_path):
    client, _ = make_client(tmp_path, read_only=True)
    assert client.get('/api/waypoints').status_code == 200
    res = client.post('/api/waypoints', json={'robot_id': 'pinky1'})
    assert res.status_code == 503 and '읽기 전용' in res.json()['detail']


def test_wall_distance_and_capture_warning(tmp_path):
    from cobot_control_center.waypoint_utils import wall_distance
    # 5x5 지도, 0.1 m/px, 원점 (0, 0). 맨 윗줄(y = 0.4~0.5)만 벽(0), 나머지 빈칸(254).
    pgm = b'P5\n5 5\n255\n' + bytes([0] * 5 + [254] * 20)
    info = {'image_width': 5, 'image_height': 5, 'resolution': 0.1, 'origin': [0.0, 0.0, 0.0]}
    m = (info, pgm)
    assert wall_distance(m, 0.25, 0.35, 0.15) == pytest.approx(0.1)
    assert wall_distance(m, 0.25, 0.05, 0.15) is None
    assert wall_distance(None, 0.25, 0.35, 0.15) is None
    store = WaypointStore(str(tmp_path / 'w.json'), 'lab', LAYERS, map_data=m, wall_warn_m=0.15)
    near = store.capture('pinky1', robot(x=0.25, y=0.35))
    assert any(w.startswith('벽에 가까움') for w in near['warnings'])
    far = store.capture('pinky1', robot(x=0.25, y=0.05))
    assert far['warnings'] == []


# ---------- 값으로 등록 ----------

def values_store(tmp_path):
    pgm = b'P5\n5 5\n255\n' + bytes([0] * 5 + [254] * 20)
    info = {'image_width': 5, 'image_height': 5, 'resolution': 0.1, 'origin': [-0.2, 0.0, 0.0]}
    return WaypointStore(str(tmp_path / 'v.json'), 'lab', LAYERS, map_data=(info, pgm),
                         wall_warn_m=0.15)


def test_add_values_persists_normalizes_and_warns_wall(tmp_path):
    store = values_store(tmp_path)
    item = store.add_values(-0.1, 0.05, 1.5 * math.pi, note='값')
    assert item['name'] == 'W1' and item['robot_id'] == '' and item['warnings'] == []
    assert item['yaw'] == pytest.approx(-math.pi / 2, abs=1e-3)
    near = store.add_values(0, 0.35, 0, name='near')
    assert near['name'] == 'NEAR' and near['warnings'][0].startswith('벽에 가까움')
    assert values_store(tmp_path).poses()['NEAR'] == [0.0, 0.35, 0.0]


@pytest.mark.parametrize('values,text', [
    ((None, 0.1, 0.0), 'x 는 숫자'), (('0', 0.1, 0.0), 'x 는 숫자'),
    ((0.0, True, 0.0), 'y 는 숫자'), ((0.0, 0.1, math.nan), 'yaw 값'),
    ((math.inf, 0.1, 0.0), 'x 값'), ((10 ** 400, 0.1, 0.0), 'x 값'),
    ((0.0, 0.1, 90), '라디안'),
    ((-0.21, 0.1, 0.0), '지도 밖'), ((0.31, 0.1, 0.0), '지도 밖'),
    ((0.0, -0.01, 0.0), '지도 밖'), ((0.0, 0.51, 0.0), '지도 밖'),
])
def test_add_values_refuses_bad_values(tmp_path, values, text):
    store = values_store(tmp_path)
    with pytest.raises(WaypointError) as error:
        store.add_values(*values)
    assert error.value.status == 400 and text in error.value.detail
    assert store.poses() == {}


def test_add_values_follows_name_and_zone_rules(tmp_path):
    store = make_store(tmp_path)
    for kwargs in ({'name': 'P1'}, {'x': 3.1}):
        with pytest.raises(WaypointError) as error:
            store.add_values(**{'x': 5.0, 'y': 0.0, 'yaw': 0.0, **kwargs})
        assert error.value.status == 409


def test_api_add_values_then_goto(tmp_path):
    client, sent = make_client(tmp_path)
    body = {'x': 6.0, 'y': 5.0, 'yaw': 1.0, 'name': 'dock'}
    res = client.post('/api/waypoints', json=body)
    assert res.status_code == 201 and res.json()['name'] == 'DOCK'
    assert '확인 못 함' in res.json()['warnings'][0]   # 지도 없는 저장소
    assert client.post('/api/waypoints', json=body).status_code == 409
    assert client.post('/api/waypoints', json={'x': 1.0}).status_code == 400
    assert client.post('/api/waypoints', json={**body, 'robot_id': 'pinky1'}).status_code == 400
    client.post('/api/tasks', json={'robot_id': 'pinky1', 'operation': 'goto',
                                    'points': ['DOCK'], 'client_request_id': 'c1'})
    assert sent[-1]['poses'] == {'DOCK': [6.0, 5.0, 1.0]}
    read_only, _ = make_client(tmp_path / 'ro', read_only=True)
    assert read_only.post('/api/waypoints', json=body).status_code == 503
