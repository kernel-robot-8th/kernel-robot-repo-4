"""실제 feature/control-center FastAPI·TaskStore를 fleet ROS 경계에 연결하는 계약 시험.

control-center 패키지가 함께 설치돼 있거나, 해당 브랜치를 PYTHONPATH로 제공할 때 실행한다.
HTTP 라우트·직렬화·응답 대기를 실제 구현으로 검증하며 ROS 전달만 메모리 콜백으로 대체한다.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_scenario import Environment


@pytest.fixture
def web(tmp_path):
    api_module = pytest.importorskip('cobot_control_center.fleet_api_app')
    utils = pytest.importorskip('cobot_control_center.fleet_api_utils')
    pytest.importorskip('httpx')
    from fastapi.testclient import TestClient
    executor = ThreadPoolExecutor(max_workers=1)
    env = executor.submit(Environment, tmp_path / 'web.sqlite3').result()

    def run(function):
        return executor.submit(function, env).result(timeout=3)

    tasks = utils.TaskStore(3.0, 0.2)
    store = utils.SnapshotStore(3.0)
    store.put(json.dumps(dict(robots={'pinky1': {'state': 'IDLE'}})))
    tasks.put_snapshot(json.dumps(run(lambda e: e.api.snapshot())))

    def publish(text):
        def consume(e):
            reply = e.api.handle(json.loads(text))
            tasks.put_event(json.dumps(reply))
            tasks.put_snapshot(json.dumps(e.api.snapshot()))
        run(consume)

    app = api_module.create_app(store, domain_id=100, tasks=tasks, publish_request=publish)
    try:
        with TestClient(app) as client:
            yield client, tasks, run, store
    finally:
        run(lambda e: e.repo.close())
        executor.shutdown()


def test_upstream_http_create_duplicate_arm_and_task_list(web):
    client, tasks, run, _ = web
    run(lambda e: setattr(e.scenario, 'armed', False))
    tasks.put_snapshot(json.dumps(run(lambda e: e.api.snapshot())))
    request = dict(client_request_id='http1', robot_id='pinky1', operation='goto', points=['P1'])
    assert client.post('/api/tasks', json=request).status_code == 423
    assert client.post('/api/commands/arm', json=dict(armed=True)).status_code == 200
    accepted = client.post('/api/tasks', json=request)
    assert accepted.status_code == 202
    task = accepted.json()
    assert task['task_id'] == 'http1' and task['command'] == 'goto:P1'
    assert client.post('/api/tasks', json=request).status_code == 200
    assert client.get('/api/tasks/http1').json()['command'] == 'goto:P1'
    assert client.get('/api/health').json()['commands_armed'] is True
    run(lambda e: e.fleet.tick())
    assert run(lambda e: len(e.gateway.sent)) == 1


def test_upstream_http_stop_and_legacy_resolve_request(web):
    client, tasks, run, _ = web
    client.post('/api/tasks', json=dict(client_request_id='http1', robot_id='pinky1',
                                        operation='goto', points=['P1']))
    # 일반 정지는 보류 없이 멈추고, 아직 안 보낸 작업은 취소한다
    stop = client.post('/api/robots/pinky1/stop', json=dict(emergency=False))
    assert stop.status_code == 202 and stop.json()['task_id'] == 'http1'
    health = client.get('/api/health').json()
    assert health['commands_armed'] is True and health['holds'] == {}
    assert client.get('/api/tasks/http1').json()['state'] == 'FAILED'
    assert run(lambda e: e.gateway.stops) == ['pinky1']
    client.post('/api/tasks', json=dict(client_request_id='http2', robot_id='pinky1',
                                        operation='goto', points=['P1']))
    run(lambda e: e.fleet.tick())
    # 로봇 하나의 비상정지는 그 로봇만 보류하고 작업 명령은 켜 둔다
    stop = client.post('/api/robots/pinky1/stop', json=dict(emergency=True))
    assert stop.status_code == 202 and stop.json()['task_id'] == 'http2'
    health = client.get('/api/health').json()
    assert health['commands_armed'] is True and 'pinky1' in health['holds']
    request = dict(result='FAILED', note='현장에서 정지 확인', client_request_id='resolve1')
    assert client.post('/api/tasks/http2/resolve', json=request).status_code == 409
    run(lambda e: e.scenario.telemetry('pinky1', dict(
        state='STOPPED', busy=False, held_zone=None,
        central_latched=True, central_controlled=True)))
    resolved = client.post('/api/tasks/http2/resolve', json=request)
    assert resolved.status_code == 200 and resolved.json()['state'] == 'FAILED'
    assert client.get('/api/tasks').json()[0]['state'] == 'FAILED'
    assert client.post('/api/robots/pinky1/raw_cmd', json={'command': 'home'}).status_code == 403


def test_upstream_websocket_receives_existing_task_envelope(web):
    client, tasks, run, _ = web
    with client.websocket_connect('/ws/tasks') as websocket:
        assert websocket.receive_json()['type'] == 'tasks'
        client.post('/api/tasks', json=dict(client_request_id='ws1', robot_id='pinky1',
                                            operation='home', points=[]))
        event = websocket.receive_json()
        assert event['type'] == 'task' and event['task']['task_id'] == 'ws1'
        assert event['task']['command'] == 'home'


def test_upstream_map_layers_read_exported_current_profiles(tmp_path):
    utils = pytest.importorskip('cobot_control_center.fleet_api_utils')
    from cobot_fleet_control.web_profiles import export_profiles
    nav = Path(__file__).resolve().parents[2]
    export_profiles(nav / 'cobot_pinky_patrol/config', 'lab',
                    ['pinky1', 'pinky2', 'pinky3'], tmp_path)
    layers = utils.load_map_layers(
        tmp_path, nav / 'cobot_zone_traffic_control/config/zone_params.yaml')
    assert layers['homes']['pinky1']['name'] == 'I1'
    assert layers['homes']['pinky2']['name'] == 'I2'
    assert layers['zones']['A']['points']['ZA'] == [0.6, 0.5, -1.5]
    assert 'P1' in layers['points']
    assert layers['warnings'] == []


def test_upstream_read_only_backend_never_forwards_a_command(web):
    _, tasks, run, store = web
    from cobot_control_center.fleet_api_app import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(store, tasks=tasks, publish_request=None)) as client:
        assert client.post('/api/commands/arm', json={'armed': True}).status_code == 503
        assert client.post('/api/robots/pinky1/stop', json={}).status_code == 503
    assert run(lambda e: e.gateway.sent == [] and e.gateway.halts == [])


def test_old_unknown_survives_upstream_default_fifty_task_limit(web):
    client, tasks, run, _ = web
    from cobot_fleet_control.contracts import Command

    def prepare(e):
        e.api.handle(dict(type='create', client_request_id='old1',
                          robot_id='pinky1', operation='home', points=[]))
        e.fleet.quarantine('old1', '현장 정지 확인 필요')
        for number in range(60):
            command = Command('past' + str(number), 'pinky2', 'home')
            e.repo.create(command)
            e.repo.transition(command.command_id, 'SUCCEEDED')
        return e.api.snapshot()

    tasks.put_snapshot(json.dumps(run(prepare)))
    assert any(t['task_id'] == 'old1' for t in client.get('/api/tasks').json())
    with client.websocket_connect('/ws/tasks') as websocket:
        assert any(t['task_id'] == 'old1' for t in websocket.receive_json()['tasks'])
