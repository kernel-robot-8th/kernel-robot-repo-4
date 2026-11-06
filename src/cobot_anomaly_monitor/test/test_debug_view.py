"""디버그 표시 시험. 틀린 표시는 잘못된 조치로 이어진다."""

from cobot_anomaly_monitor.debug_view import (
    parse_zone_status, ready_problems, RouteTrace, zone_table)
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
import pytest


def graph(publishers=1, subscribers=1, request=1, tasks=1):
    return {'request': {'subscribers': request}, 'tasks': {'publishers': tasks},
            'robots': {'pinky1': {'patrol_cmd': {'publishers': publishers,
                                                 'subscribers': subscribers}}}}


@pytest.mark.parametrize('text,parsed', [
    ('A:free', ('A', None)), ('C:occupied_by:pinky2', ('C', 'pinky2')),
    ('A', None), ('', None), ('A:other', None), (':free', None),
])
def test_zone_status_text(text, parsed):
    assert parse_zone_status(text) == parsed


def test_zone_table_flags_a_leaked_token():
    rows = zone_table({'A': 'pinky1', 'B': None}, {'pinky2': {'held_zone': 'B'}, 'pinky3': {}})
    assert [(r['zone'], r['manager'], r['robot'], r['match']) for r in rows] == [
        ('A', 'pinky1', None, False), ('B', None, 'pinky2', False)]


def test_zone_table_does_not_claim_a_match_before_the_manager_reports():
    rows = zone_table({}, {'pinky1': {'held_zone': 'A'}})
    assert rows[0]['manager_known'] is False and rows[0]['match'] is None


def test_ready_problems_are_empty_when_fleet_would_accept():
    assert ready_problems('pinky1', graph()) == []


@pytest.mark.parametrize('changes,text', [
    ({'publishers': 2}, 'patrol_cmd 발행자 2개'), ({'subscribers': 0}, 'patrol_cmd 구독자 0개'),
    ({'request': 2}, 'task_request 구독자 2개'), ({'tasks': 0}, 'tasks 발행자 0개'),
])
def test_ready_problems_name_the_blocking_link(changes, text):
    assert ready_problems('pinky1', graph(**changes)) == [text + ' (1개여야 함)']


def test_ready_problems_without_graph():
    assert ready_problems('pinky1', None) == ['연결 정보 없음']


def test_route_trace_records_gate_order_once():
    trace = RouteTrace({'P5': [-0.25, -1.28, 3.14], 'P6': [-0.25, -1.45, 0.0], 'ZC': [-0.5, 0.3]})
    for y in (-1.27, -1.28, -1.46, -1.45, -1.0):
        trace.update('pinky1', -0.25, y)
    trace.update('pinky1', -0.5, 0.31)
    assert trace.routes == {'pinky1': ['P5', 'P6', 'ZC']}


def test_route_trace_keeps_the_latest_points():
    trace = RouteTrace({'A': [0.0, 0.0], 'B': [1.0, 0.0]}, limit=3)
    for x in (0.0, 1.0, 0.0, 1.0):
        trace.update('pinky1', x, 0.0)
    assert trace.routes['pinky1'] == ['B', 'A', 'B']


@pytest.fixture
def core(tmp_path):
    store = MonitorStore(tmp_path / 'm.sqlite3')
    now = [10.0]
    sent = []
    item = MonitorCore(store, {}, ['pinky1'], sent.append, clock=lambda: now[0],
                       points={'ZA': [0.6, 0.5, -1.5]})
    item.now, item.sent = now, sent
    yield item
    store.close()


def test_request_log_shows_status_and_round_trip_time(core):
    request_id = core.request({'type': 'create', 'robot_id': 'pinky1', 'operation': 'goto',
                               'points': ['P1']})
    core.now[0] = 10.25
    core.on_task_event({'type': 'reply', 'request_id': request_id, 'status': 423,
                        'body': {'detail': '작업 명령 꺼짐'}})
    row = core.live()['log'][0]
    assert (row['type'], row['operation'], row['points']) == ('create', 'goto', ['P1'])
    assert (row['status'], row['rtt_ms'], row['detail']) == (423, 250.0, '작업 명령 꺼짐')


def test_request_without_a_reply_stays_visible_as_unanswered(core):
    core.request({'type': 'arm'})
    assert core.live()['log'][0]['status'] is None


def test_link_shows_status_fields_and_ages(core):
    core.on_status('pinky1', {'state': 'MOVING', 'detail': 'ZA', 'central_latched': True,
                              'extra': 1})
    core.now[0] = 12.0
    link = core.live()['links'][0]
    assert link['status']['state'] == 'MOVING' and link['status']['central_latched'] is True
    assert 'extra' not in link['status'] and link['ages'] == {'patrol_status': 2.0}
    assert link['problems'] == ['연결 정보 없음']


def test_live_carries_route_and_recent_tasks(core):
    core.on_pose('pinky1', 0.6, 0.5, 0.0)
    core.on_tasks({'armed': True, 'orders': [], 'tasks': [{'task_id': str(i)} for i in range(20)]})
    live = core.live()
    assert live['routes'] == {'pinky1': ['ZA']} and len(live['tasks']) == 10
