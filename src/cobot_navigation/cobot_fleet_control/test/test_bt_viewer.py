"""실시간 조회 도구의 변경 감지·읽기 전용 계약·HTTP 응답을 검증한다."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cobot_fleet_control.bt_viewer import make_server, read_snapshots, viewer_page
from cobot_fleet_control.bt_visualization import export_traces
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.service import FleetService
import pytest

from test_scenario import Environment
from test_service import Gateway


@pytest.fixture
def env(tmp_path):
    """각각 갱신 가능한 실제 주문·원장 환경을 만든다."""
    environment = Environment(tmp_path / 'viewer.sqlite3')
    environment.scenario.store.set_stock('SHOE42', 10)
    yield environment
    environment.repo.close()


@contextmanager
def server_for(path):
    """시험용 포트에서 조회 서버만 실행하며 종료 시 연결을 정리한다."""
    server = make_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_missing_journal_waits_without_creating_database(tmp_path):
    path = tmp_path / 'not-created.sqlite3'
    assert read_snapshots(path)['status'] == 'waiting'
    assert not path.exists()


def test_initial_latest_tree_and_incremental_changes_are_read_only(env):
    env.order()
    env.tick()
    first = read_snapshots(env.path)
    assert {trace['type'] for trace in first['snapshots']} == {
        'scenario_bt_snapshot', 'bt_snapshot'}
    assert len(first['snapshots']) == 2
    head = env.repo.db.execute('SELECT max(event_id) FROM outbox').fetchone()[0]
    assert read_snapshots(env.path, first['cursor'])['snapshots'] == []
    assert env.repo.db.execute('SELECT max(event_id) FROM outbox').fetchone()[0] == head
    env.until('MARKER')
    env.result(dict(sku='SHOE42'))
    later = read_snapshots(env.path, first['cursor'])
    assert later['cursor'] > first['cursor']
    assert any(trace.get('stage') == 'PICK' for trace in later['snapshots'])
    assert later['orders'][0]['stage'] == 'PICK'


def test_reader_handles_navigation_only_journal_and_cursor_reset(tmp_path):
    path = tmp_path / 'navigation.sqlite3'
    repo = SqliteRepository(str(path))
    service = FleetService(repo, Gateway(), ['pinky1'])
    service.submit(dict(command_id='move1', robot_id='pinky1', operation='home'))
    service.tick()
    result = read_snapshots(path)
    assert result['orders'] == []
    assert len(result['snapshots']) == 1
    assert read_snapshots(path, after=999999)['reset'] is True
    repo.close()


def test_http_serves_local_assets_updates_and_rejects_mutations(env):
    env.order()
    env.tick()
    with server_for(env.path) as base:
        with urlopen(base) as response:
            page = response.read().decode('utf-8')
            assert '실시간 행동 트리' in page and 'setInterval(poll,500)' in page
        with urlopen(base + '/api/snapshots') as response:
            payload = json.load(response)
            assert payload['snapshots']
            assert response.headers['Cache-Control'] == 'no-store'
        for target, status in [('/../config/scenario.yaml', 404),
                               ('/api/snapshots?after=-1', 400),
                               ('/api/snapshots?after=bad', 400)]:
            with pytest.raises(HTTPError) as error:
                urlopen(base + target)
            assert error.value.code == status
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/api/snapshots', data=b'{}', method='POST'))
        assert error.value.code == 405


def test_reader_reports_invalid_schema_without_creating_control_tables(tmp_path):
    path = tmp_path / 'other.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE other(value TEXT)')
    with server_for(path) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/api/snapshots')
        assert error.value.code == 503
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ('other',)]


def test_viewer_asset_and_entry_point_are_installed():
    root = Path(__file__).parents[1]
    setup = (root / 'setup.py').read_text(encoding='utf-8')
    assert 'fleet_bt_viewer = cobot_fleet_control.bt_viewer:main' in setup
    assert "glob('docs/*.html')" in setup
    assert viewer_page() == (root / 'docs/bt_viewer.html').read_bytes()


def test_offline_export_contains_real_order_tree_and_command_filter(env):
    env.order()
    env.until('LOAD')
    order_traces = export_traces(env.path, order_id='order1')['snapshots']
    assert order_traces and all(row['type'] == 'scenario_bt_snapshot' for row in order_traces)
    command_id = env.gateway.sent[0][1]['command_id']
    command_traces = export_traces(env.path, command_id=command_id)['snapshots']
    assert command_traces and all(row['type'] == 'bt_snapshot' for row in command_traces)
    assert export_traces(env.path, order_id='absent')['snapshots'] == []
