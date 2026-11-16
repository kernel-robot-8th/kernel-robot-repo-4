"""화면 '초기위치' 요청: 멈춘 로봇만 홈 좌표로 AMCL 을 다시 잡고 기록한다."""

import math
from types import SimpleNamespace

from cobot_fleet_control.contracts import Command
from cobot_fleet_control.control_api import ControlAPI, initial_pose_fields
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.web_profiles import PointRules
import pytest

ROBOTS = ['pinky1', 'pinky2']
RULES = PointRules({
    'pinky1': {'home_name': 'I1', 'points': {'I1': [0.0, 0.0, 0.0]}},
    # yaw 없는 2개짜리 지점은 0 으로 본다
    'pinky2': {'home_name': 'I2', 'points': {'I2': [0.0, -0.2]}},
})


def make_api(tmp_path, status=None, fresh=True, orders=(), rules=RULES):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    events, sent = [], []
    store = SimpleNamespace(orders=lambda: list(orders), event=events.append)
    health = {'pinky2': {'status': {'busy': False} if status is None else status}}
    # armed 는 일부러 False: 초기위치는 '작업 명령 켜기' 없이도 된다
    scenario = SimpleNamespace(store=store, _fresh=lambda robot: fresh, health=health,
                               armed=False)
    fleet = SimpleNamespace(repository=repo, robots=ROBOTS)
    gateway = SimpleNamespace(set_initial_pose=lambda *args: sent.append(args))
    return ControlAPI(scenario, fleet, gateway, point_rules=rules), repo, events, sent


def test_initial_pose_sends_home_without_arming(tmp_path):
    api, repo, events, sent = make_api(tmp_path)
    try:
        reply = api.handle({'type': 'initial_pose', 'robot_id': 'pinky2',
                            'client_request_id': 'p1', 'source': '10.0.0.5'})
        assert reply['status'] == 202
        assert reply['body'] == dict(reply['body'], robot_id='pinky2', point='I2',
                                     x=0.0, y=-0.2, yaw=0.0, client_request_id='p1')
        assert sent == [('pinky2', 0.0, -0.2, 0.0)]
        assert events == [dict(type='operator_initial_pose', robot_id='pinky2', mode='home',
                               point='I2', x=0.0, y=-0.2, yaw=0.0, source='10.0.0.5')]
    finally:
        repo.close()


def test_initial_pose_sends_manual_pose(tmp_path):
    # 지도에서 찍은 좌표는 순찰 설정 없이도 보낼 수 있다 (홈 좌표가 필요 없으므로)
    api, repo, events, sent = make_api(tmp_path, rules=None)
    try:
        reply = api.handle({'type': 'initial_pose', 'robot_id': 'pinky2',
                            'pose': {'x': 0.3, 'y': '0.4', 'yaw': 1.57}})
        assert reply['status'] == 202
        assert reply['body']['mode'] == 'manual' and reply['body']['point'] == '좌표'
        assert sent == [('pinky2', 0.3, 0.4, 1.57)]
        assert events[0]['mode'] == 'manual' and events[0]['x'] == 0.3
    finally:
        repo.close()


@pytest.mark.parametrize('pose', [
    {'x': 0.0, 'y': 0.0},
    {'x': 'a', 'y': 0.0, 'yaw': 0.0},
    {'x': float('nan'), 'y': 0.0, 'yaw': 0.0},
    {'x': 0.0, 'y': float('inf'), 'yaw': 0.0},
    [0.0, 0.0, 0.0],
])
def test_initial_pose_rejects_bad_manual_pose(tmp_path, pose):
    api, repo, events, sent = make_api(tmp_path)
    try:
        reply = api.handle({'type': 'initial_pose', 'robot_id': 'pinky2', 'pose': pose})
        assert reply['status'] == 400
        assert sent == [] and events == []
    finally:
        repo.close()


def test_initial_pose_manual_still_requires_stopped_robot(tmp_path):
    api, repo, events, sent = make_api(tmp_path, status={'busy': True})
    try:
        reply = api.handle({'type': 'initial_pose', 'robot_id': 'pinky2',
                            'pose': {'x': 0.3, 'y': 0.4, 'yaw': 0.0}})
        assert reply['status'] == 409 and sent == []
    finally:
        repo.close()


@pytest.mark.parametrize('kwargs, robot, status_code', [
    ({}, 'pinky9', 404),
    ({'rules': None}, 'pinky2', 503),
    ({'fresh': False}, 'pinky2', 503),
    ({'status': {'busy': True}}, 'pinky2', 409),
    # 멈춤이 확인되지 않으면(상태 없음) 보내지 않는다
    ({'status': {}}, 'pinky2', 409),
    ({'orders': [{'robot_id': 'pinky2', 'state': 'RUNNING'}]}, 'pinky2', 409),
])
def test_initial_pose_rejects_unsafe_requests(tmp_path, kwargs, robot, status_code):
    api, repo, events, sent = make_api(tmp_path, **kwargs)
    try:
        reply = api.handle({'type': 'initial_pose', 'robot_id': robot})
        assert reply['status'] == status_code
        assert sent == [] and events == []
    finally:
        repo.close()


def test_initial_pose_rejects_robot_with_running_task(tmp_path):
    api, repo, events, sent = make_api(tmp_path)
    try:
        repo.create(Command('t1', 'pinky2', 'goto', ('P1',)))
        reply = api.handle({'type': 'initial_pose', 'robot_id': 'pinky2'})
        assert reply['status'] == 409 and '진행 중인 작업' in reply['body']['detail']
        assert sent == []
    finally:
        repo.close()


def test_initial_pose_fields_quaternion_and_covariance():
    fields = initial_pose_fields(1.0, -2.0, math.pi / 2, 0.0625, 0.068)
    assert (fields['x'], fields['y']) == (1.0, -2.0)
    assert fields['qz'] == pytest.approx(math.sqrt(0.5))
    assert fields['qw'] == pytest.approx(math.sqrt(0.5))
    cov = fields['covariance']
    assert len(cov) == 36 and cov[0] == cov[7] == 0.0625 and cov[35] == 0.068
    assert sum(cov) == pytest.approx(0.0625 * 2 + 0.068)


@pytest.mark.parametrize('args', [
    (math.nan, 0.0, 0.0, 0.0625, 0.068),
    (0.0, 0.0, 0.0, 0.0, 0.068),
])
def test_initial_pose_fields_rejects_bad_values(args):
    with pytest.raises(ValueError):
        initial_pose_fields(*args)
