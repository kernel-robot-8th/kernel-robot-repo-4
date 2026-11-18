"""구역 강제 해제: 토큰을 쥔 채 꺼졌거나 다시 켜져 토큰을 잊은 로봇의 구역만 푼다."""

from types import SimpleNamespace

from cobot_fleet_control.control_api import (
    ControlAPI, parse_zone_status, ZONE_STATUS_MAX_AGE_SEC)
from cobot_fleet_control.repository import SqliteRepository
import pytest

ROBOTS = ['pinky1', 'pinky2']
FORGOT = {'busy': False, 'held_zone': None}   # 다시 켜져 토큰을 잊은 로봇


def make_api(tmp_path, status=FORGOT, fresh=True, orders=(),
             zone=('occupied_by:pinky1', 0.5)):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    events, sent = [], []
    store = SimpleNamespace(orders=lambda: list(orders), event=events.append)
    health = {'pinky1': {'status': status}}
    # armed 는 일부러 False: 로봇을 움직이지 않으므로 '작업 명령 켜기' 없이도 된다
    scenario = SimpleNamespace(store=store, _fresh=lambda robot: fresh, health=health,
                               armed=False)
    fleet = SimpleNamespace(repository=repo, robots=ROBOTS)
    gateway = SimpleNamespace(
        zone_state=lambda name: zone if name == 'A' else (None, None),
        release_zone=lambda *args: sent.append(args))
    return ControlAPI(scenario, fleet, gateway), repo, events, sent


def release(api, **extra):
    return api.handle(dict({'type': 'zone_release', 'zone': 'A', 'robot_id': 'pinky1',
                            'client_request_id': 'z1', 'source': '10.0.0.5'}, **extra))


def test_releases_zone_of_rebooted_robot(tmp_path):
    api, repo, events, sent = make_api(tmp_path)
    try:
        reply = release(api)
        assert reply['status'] == 202
        assert reply['body'] == dict(zone='A', robot_id='pinky1', robot_online=True,
                                     released='sent', client_request_id='z1')
        assert sent == [('A', 'pinky1')]
        assert events == [dict(type='zone_release', zone='A', robot_id='pinky1',
                               robot_online=True, note='화면에서 현장 확인 후 구역 강제 해제',
                               source='10.0.0.5')]
    finally:
        repo.close()


def test_releases_zone_of_offline_robot(tmp_path):
    # 꺼진 로봇의 마지막 상태는 아직 그 구역을 잡고 있다고 말한다. 끊겼으면 그 값을 믿지 않는다.
    api, repo, events, sent = make_api(
        tmp_path, status={'busy': True, 'held_zone': 'A'}, fresh=False)
    try:
        reply = release(api, note='현장에서 꺼냄')
        assert reply['status'] == 202 and reply['body']['robot_online'] is False
        assert sent == [('A', 'pinky1')] and events[0]['note'] == '현장에서 꺼냄'
    finally:
        repo.close()


@pytest.mark.parametrize('kwargs, status_code', [
    # 살아 있고 아직 잡고 있다고 아는 로봇: 나가기를 써야 한다
    (dict(status={'busy': False, 'held_zone': 'A'}), 409),
    (dict(status={'busy': True, 'held_zone': None}), 409),
    # held_zone 을 보고하지 않는 순찰 노드는 잊었는지 알 수 없다
    (dict(status={'busy': False}), 409),
    (dict(orders=[{'robot_id': 'pinky1', 'state': 'RUNNING'}]), 409),
    (dict(zone=('occupied_by:pinky2', 0.5)), 409),
    (dict(zone=('free', 0.5)), 409),
    (dict(zone=('occupied_by:pinky1', ZONE_STATUS_MAX_AGE_SEC + 1)), 503),
    (dict(zone=(None, None)), 503),
])
def test_refuses_unsafe_release(tmp_path, kwargs, status_code):
    api, repo, events, sent = make_api(tmp_path, **kwargs)
    try:
        assert release(api)['status'] == status_code
        assert sent == [] and events == []
    finally:
        repo.close()


@pytest.mark.parametrize('extra, status_code', [
    (dict(robot_id='pinky9'), 404),
    (dict(zone='A:pinky2'), 400),
    (dict(zone=''), 400),
    (dict(note=3), 400),
])
def test_refuses_bad_request(tmp_path, extra, status_code):
    api, repo, events, sent = make_api(tmp_path)
    try:
        assert release(api, **extra)['status'] == status_code
        assert sent == []
    finally:
        repo.close()


@pytest.mark.parametrize('text, parsed', [
    ('A:free', ('A', 'free')),
    ('ZA:occupied_by:pinky1', ('ZA', 'occupied_by:pinky1')),
    ('A:occupied_by:', None),
    ('A:busy', None),
    (':free', None),
    (None, None),
])
def test_parse_zone_status(text, parsed):
    assert parse_zone_status(text) == parsed
