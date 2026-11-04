"""트리 상태와 실제 tick 방문 경로를 구분해 기록하는지 검증한다."""

import json

from cobot_fleet_control.bt_visualization import export_traces
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.service import FleetService
import pytest


def snapshots(repo):
    """MQTT로 보낼 outbox 중 BT 관측 이벤트만 추린다."""
    return [event for row in repo.pending()
            if (event := json.loads(row['payload']))['type'] == 'bt_snapshot']


@pytest.mark.parametrize('result,job_state,root_status', [
    ('DONE', 'SUCCEEDED', 'SUCCESS'), ('FAILED', 'FAILED', 'FAILURE'),
    ('timeout', 'UNKNOWN', 'FAILURE'),
])
def test_actual_tick_paths_and_terminal_snapshot(tmp_path, result, job_state, root_status):
    """이전 SUCCESS와 이번 tick에 다시 실행한 SUCCESS를 시각적으로 구분한다."""
    repo = SqliteRepository(str(tmp_path / 'trace.sqlite3'))
    clock = [0]
    sent = []

    class Gateway:
        """실제 발행 횟수와 관측 결과를 비교한다."""

        def send(self, *args):
            sent.append(args)

    service = FleetService(repo, Gateway(), ['pinky1'], lambda: clock[0])
    service.submit({'command_id': 'trace1', 'robot_id': 'pinky1',
                    'operation': 'home', 'timeout_sec': 2})
    initial = snapshots(repo)[0]
    assert all(n['status'] == 'INVALID' and not n['visited'] for n in initial['nodes'])
    service.tick()
    first = {n['kind']: n for n in snapshots(repo)[-1]['nodes']}
    assert first['Dispatch']['status'] == 'SUCCESS'
    assert first['Dispatch']['visited'] is True
    assert first['AwaitResult']['status'] == 'RUNNING'
    service.tick()
    second = {n['kind']: n for n in snapshots(repo)[-1]['nodes']}
    assert second['Dispatch']['status'] == 'SUCCESS'
    assert second['Dispatch']['visited'] is False
    assert second['AwaitResult']['visited'] is True
    count = len(snapshots(repo))
    service.tick()
    assert len(snapshots(repo)) == count
    if result == 'timeout':
        clock[0] = 3
    else:
        service.on_status('pinky1', {
            'command_id': 'trace1', 'state': result, 'task_finished': True})
    service.tick()
    final = snapshots(repo)[-1]
    assert final['job_state'] == job_state
    assert next(n for n in final['nodes'] if n['id'] == final['root_id'])[
        'status'] == root_status
    assert len(sent) == 1
    assert not service.traces
    # PUBACK 처리 뒤에도 이력 내보내기에 남아 있어야 한다.
    for event in repo.pending():
        repo.acknowledge(event['event_id'])
    repo.close()
    exported = export_traces(tmp_path / 'trace.sqlite3')
    assert exported['format'] == 'cobot-bt-trace-v1'
    assert exported['snapshots'][-1] == final


def test_read_only_export_never_creates_missing_database(tmp_path):
    """운영 DB 경로 오타를 빈 DB 생성으로 숨기지 않는다."""
    import sqlite3

    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        export_traces(path)
    assert not path.exists()
