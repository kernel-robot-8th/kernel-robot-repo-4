"""중복·잘못된 상태·시간 초과·재시작 상황에서 중복 이동을 방지한다."""

import json

from cobot_fleet_control.contracts import Command
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.resolve_unknown import main as resolve_unknown_main
from cobot_fleet_control.service import FleetService
import pytest


class Gateway:
    """실제 주행 없이 전달 횟수를 관찰한다."""

    def __init__(self):
        self.sent = []

    def send(self, robot_id, payload):
        self.sent.append((robot_id, payload))


def request(command_id='job1', robot_id='pinky1', **changes):
    data = {'command_id': command_id, 'robot_id': robot_id,
            'operation': 'goto', 'points': ['P1'], 'timeout_sec': 10}
    return dict(data, **changes)


@pytest.fixture
def env(tmp_path):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    gateway = Gateway()
    clock = [0.0]
    service = FleetService(repo, gateway, ['pinky1', 'pinky2'], lambda: clock[0])
    yield repo, gateway, clock, service
    repo.close()


def finish(service, command_id='job1', robot_id='pinky1', **changes):
    service.on_status(robot_id, dict(command_id=command_id, state='DONE',
                                     task_finished=True, **changes))
    service.tick()


def test_duplicate_and_delayed_wrong_results(env):
    repo, gateway, clock, service = env
    service.submit(request())
    service.submit(request())
    service.tick()
    for _ in range(4):
        service.tick()
    assert len(gateway.sent) == 1
    service.on_status('pinky2', {'command_id': 'job1', 'state': 'DONE', 'task_finished': True})
    service.on_status('pinky1', {'command_id': 'old', 'state': 'DONE', 'task_finished': True})
    service.on_status('pinky1', {'command_id': 'job1', 'state': 'DONE', 'task_finished': False})
    service.tick()
    assert repo.get('job1')['state'] == 'RUNNING'
    finish(service)
    assert repo.get('job1')['state'] == 'SUCCEEDED'
    service.submit(request())
    service.tick()
    assert len(gateway.sent) == 1


def test_conflict_and_robot_busy(env):
    repo, gateway, clock, service = env
    service.submit(request())
    with pytest.raises(ValueError, match='다른 명령'):
        service.submit(request(points=['P2']))
    with pytest.raises(ValueError, match='작업 중'):
        service.submit(request('job2'))
    service.submit(request('job3', 'pinky2'))
    service.tick()
    assert len(gateway.sent) == 2


def test_timeout_keeps_robot_reserved_until_real_late_result(env):
    repo, gateway, clock, service = env
    service.submit(request())
    service.tick()
    clock[0] = 11
    service.tick()
    assert repo.get('job1')['state'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        service.submit(request('job2'))
    finish(service)
    assert repo.get('job1')['state'] == 'SUCCEEDED'
    service.submit(request('job2'))


def test_restart_never_redispatches(tmp_path):
    path = str(tmp_path / 'recovery.sqlite3')
    repo = SqliteRepository(path)
    gateway = Gateway()
    service = FleetService(repo, gateway, ['pinky1'])
    service.submit(request())
    service.tick()
    repo.close()
    repo = SqliteRepository(path)
    service = FleetService(repo, gateway, ['pinky1'])
    service.submit(request())
    service.tick()
    assert len(gateway.sent) == 1
    assert repo.get('job1')['state'] == 'UNKNOWN'
    finish(service)
    assert not repo.busy('pinky1')
    repo.close()


def test_failure_and_outbox_ack(env):
    repo, gateway, clock, service = env
    service.submit(request())
    service.tick()
    service.on_status('pinky1', {
        'command_id': 'job1', 'state': 'FAILED',
        'detail': 'navigation failed', 'task_finished': True})
    service.tick()
    assert repo.get('job1')['state'] == 'FAILED'
    events = repo.pending()
    assert [event['state'] for e in events
            if (event := json.loads(e['payload']))['type'] == 'command_state'] == [
        'ACCEPTED', 'RUNNING', 'FAILED']
    for event in events:
        repo.acknowledge(event['event_id'])
    assert repo.pending() == []


def test_telemetry_is_real_payload_with_receipt_time(env):
    repo, *_ = env
    status = {'state': 'MOVING', 'waypoint': 0, 'detail': 'P1', 'time': 123.0}
    repo.record_status('pinky1', status)
    event = json.loads(repo.pending()[0]['payload'])
    assert event['status'] == status
    assert event['type'] == 'robot_status'
    assert event['recorded_at'] > 123


@pytest.mark.parametrize('changes', [
    {'command_id': '../bad'}, {'robot_id': 'unknown'}, {'robot_id': []},
    {'operation': 'start'}, {'operation': []}, {'points': 'P1'}, {'points': ['P1:stop']},
    {'points': []}, {'points': [None]}, {'timeout_sec': float('nan')},
    {'timeout_sec': float('inf')}, {'timeout_sec': True}, {'timeout_sec': 0},
    {'operation': 'home'}, {'operation': 'zone', 'points': ['ZA', 'ZB']},
    {'unknown': 1},
])
def test_invalid_inputs(changes):
    with pytest.raises(ValueError):
        Command.parse(request(**changes), ['pinky1'])


@pytest.mark.parametrize('operation,points,wire', [
    ('goto', ['P1', 'P2'], 'goto:P1,P2'), ('zone', ['ZA'], 'zone:ZA'),
    ('leave', [], 'leave'), ('home', [], 'home'),
])
def test_wire_contract(operation, points, wire):
    command = Command.parse(request(operation=operation, points=points), ['pinky1'])
    assert command.wire() == {'command_id': 'job1', 'command': wire}


def test_dispatch_error_stays_unknown(env):
    repo, gateway, clock, service = env

    def fail(*args):
        raise RuntimeError('transport failure')

    gateway.send = fail
    service.submit(request())
    with pytest.raises(RuntimeError):
        service.tick()
    assert repo.get('job1')['state'] == 'UNKNOWN'
    assert repo.busy('pinky1')


def test_manual_resolution_preserves_history_and_releases_only_unknown(env):
    repo, gateway, clock, service = env
    service.submit(request())
    service.tick()
    clock[0] = 11
    service.tick()
    with pytest.raises(ValueError, match='robot_id'):
        repo.resolve_unknown('job1', 'pinky2', 'operator1', '현장 정지 확인')
    row = repo.resolve_unknown('job1', 'pinky1', 'operator1', '현장 정지 확인')
    assert row['state'] == 'FAILED'
    assert 'operator1' in row['detail']
    assert not repo.busy('pinky1')
    event = json.loads(repo.pending()[-1]['payload'])
    assert event['type'] == 'command_state'
    assert event['state'] == 'FAILED'
    assert event['detail'] == row['detail']
    with pytest.raises(ValueError, match='UNKNOWN'):
        repo.resolve_unknown('job1', 'pinky1', 'operator1', '반복 해제')
    finish(service)
    assert repo.get('job1')['state'] == 'FAILED'
    service.submit(request('job2'))


def test_resolution_cli_requires_server_stop_and_confirmation(tmp_path, capsys):
    path = str(tmp_path / 'fleet.sqlite3')
    repo = SqliteRepository(path)
    service = FleetService(repo, Gateway(), ['pinky1'])
    service.submit(request())
    service.tick()
    repo.transition('job1', 'UNKNOWN', '응답 시간 초과')
    args = ['--db', path, '--command-id', 'job1', '--robot-id', 'pinky1',
            '--operator', 'operator1', '--reason', '현장 정지 확인']
    with pytest.raises(SystemExit):
        resolve_unknown_main(args)
    with pytest.raises(SystemExit):
        resolve_unknown_main(args + ['--confirm-stopped'])
    assert repo.get('job1')['state'] == 'UNKNOWN'
    repo.close()
    resolve_unknown_main(args + ['--confirm-stopped'])
    assert 'job1 (pinky1): FAILED' in capsys.readouterr().out
    check = SqliteRepository(path)
    assert check.get('job1')['state'] == 'FAILED'
    check.close()
