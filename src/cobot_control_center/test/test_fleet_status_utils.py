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

"""읽기 전용 관제 로직(fleet_status_utils.py)을 ROS 없이 검사한다."""

import json
import math

from cobot_control_center.fleet_status_utils import (
    clock_offset, count_state, diff_events, FleetState, judge_infra, judge_teach_pose,
    MOVING_STATES,
    parse_patrol_status, parse_queue_slot, parse_zone_status, std_from_covariance,
    UNKNOWN_NODE_NAME,
    yaw_from_quaternion)
import pytest

BRIDGES = {'pinky1': 'pinky_bridge_pinky1_only_100', 'pinky2': 'pinky_bridge_pinky2_only_100'}


def judge(domain_id=100, node_names=(), zone_publishers=1, pose_publishers=None):
    return judge_infra(domain_id, 100, node_names, 'mock_pinky_node', BRIDGES,
                       zone_publishers, pose_publishers or {})


@pytest.mark.parametrize('count, state', [(0, 'missing'), (1, 'ok'), (2, 'duplicate'),
                                          (3, 'duplicate')])
def test_count_state(count, state):
    assert count_state(count) == state


def test_infra_real_all_ok():
    infra = judge(node_names=['pinky_bridge_pinky1_only_100', 'pinky_bridge_pinky2_only_100',
                              'zone_manager_node'])
    assert infra['mode'] == 'real'
    assert infra['domain_id'] == 100
    assert infra['zone_manager'] == {'state': 'ok', 'count': 1}
    assert infra['bridges']['pinky1'] == {'state': 'ok', 'count': 1,
                                          'node': 'pinky_bridge_pinky1_only_100'}
    assert infra['bridges']['pinky2']['state'] == 'ok'


@pytest.mark.parametrize('zone_publishers, state', [(0, 'missing'), (2, 'duplicate')])
def test_infra_real_zone_manager_missing_or_duplicate(zone_publishers, state):
    assert judge(zone_publishers=zone_publishers)['zone_manager']['state'] == state


def test_infra_real_bridge_missing_and_duplicate():
    infra = judge(node_names=['pinky_bridge_pinky2_only_100'] * 2)
    assert infra['bridges']['pinky1']['state'] == 'missing'
    assert infra['bridges']['pinky2'] == {'state': 'duplicate', 'count': 2,
                                          'node': 'pinky_bridge_pinky2_only_100'}


def test_infra_real_bridge_unknown_when_names_are_hidden():
    # DDS 가 다르면 브릿지 이름은 안 보이고, 위치 발행자 이름만 '모름' 으로 보인다.
    infra = judge(pose_publishers={'pinky1': [UNKNOWN_NODE_NAME]})
    assert infra['bridges']['pinky1']['state'] == 'unknown'
    assert infra['bridges']['pinky2']['state'] == 'missing'


def test_infra_mock_mode_is_not_applicable():
    infra = judge(domain_id=101, node_names=['mock_pinky_node'], zone_publishers=1)
    assert infra['mode'] == 'mock'
    assert infra['zone_manager'] == {'state': 'n/a', 'count': 1}
    assert {b['state'] for b in infra['bridges'].values()} == {'n/a'}


def test_infra_other_domain_is_test_mode():
    infra = judge(domain_id=77, zone_publishers=0)
    assert infra['mode'] == 'test'
    assert infra['zone_manager']['state'] == 'n/a'
    assert json.loads(json.dumps(infra)) == infra


def test_parse_patrol_status_known_fields():
    parsed = parse_patrol_status(
        '{"state": "MOVING", "waypoint": 2, "detail": "ZB", "time": 10.5}')
    assert parsed == {'state': 'MOVING', 'waypoint': 2, 'detail': 'ZB', 'time': 10.5,
                      'extra': {}}


def test_parse_patrol_status_keeps_unknown_fields_in_extra():
    parsed = parse_patrol_status(
        '{"state": "DONE", "command_id": "job-1", "task_finished": true}')
    assert parsed['state'] == 'DONE'
    assert parsed['waypoint'] is None
    assert parsed['extra'] == {'command_id': 'job-1', 'task_finished': True}


@pytest.mark.parametrize('text', ['', 'not json', '[1, 2]', '"MOVING"', None])
def test_parse_patrol_status_rejects_bad_input(text):
    assert parse_patrol_status(text) is None


def test_parse_zone_status():
    assert parse_zone_status('A:free') == ('A', 'free')
    assert parse_zone_status('B:occupied_by:pinky2') == ('B', 'occupied_by:pinky2')


@pytest.mark.parametrize('text', ['', 'A', 'A:', ':free', None])
def test_parse_zone_status_rejects_bad_input(text):
    assert parse_zone_status(text) is None


def test_parse_queue_slot():
    assert parse_queue_slot('A:pinky2:0:1.200,0.400,3.140') == ('A', 'pinky2', 0)
    assert parse_queue_slot('B:pinky3:-1:0,0,0') == ('B', 'pinky3', -1)


@pytest.mark.parametrize('text', ['', 'A:pinky2:0', 'A:pinky2:x:0,0,0', ':pinky2:0:0,0,0', None])
def test_parse_queue_slot_rejects_bad_input(text):
    assert parse_queue_slot(text) is None


def test_queues_order_stale_and_occupant():
    fleet = FleetState(['pinky1', 'pinky2', 'pinky3'], 3.0, queue_stale_sec=2.5)
    fleet.update_zone('A:occupied_by:pinky1')
    assert fleet.update_queue_slot('A:pinky3:1:0,0,0', 10.0) is True
    assert fleet.update_queue_slot('A:pinky2:0:0,0,0', 10.0) is True
    assert fleet.update_queue_slot('broken', 10.0) is False
    # 앞 순번부터
    assert fleet.snapshot(11.0)['queues'] == {'A': ['pinky2', 'pinky3']}
    # 다시 안 오면 대기열을 떠난 것으로 본다 (pinky3 만 새로 옴)
    fleet.update_queue_slot('A:pinky3:0:0,0,0', 12.0)
    assert fleet.snapshot(13.0)['queues'] == {'A': ['pinky3']}
    # 진입 허가를 받아 점유자가 되면 대기열에서 뺀다
    fleet.update_zone('A:occupied_by:pinky3')
    assert fleet.snapshot(13.0)['queues'] == {}
    # 가득 차 거절(k=-1)은 대기열에 넣지 않는다
    fleet.update_queue_slot('B:pinky2:-1:0,0,0', 13.0)
    assert fleet.snapshot(13.0)['queues'] == {}


def test_yaw_from_quaternion():
    assert yaw_from_quaternion(0.0, 0.0, 0.0, 1.0) == pytest.approx(0.0)
    half = math.pi / 4
    assert yaw_from_quaternion(0.0, 0.0, math.sin(half), math.cos(half)) == pytest.approx(
        math.pi / 2)


def test_never_seen_robot_is_offline():
    fleet = FleetState(['pinky1'], 3.0)
    robot = fleet.snapshot(100.0)['robots']['pinky1']
    assert robot['online'] is False
    assert robot['never_seen'] is True
    assert robot['last_seen_age'] is None


def test_stale_boundary():
    fleet = FleetState(['pinky1'], 3.0)
    fleet.update_pose('pinky1', 1.0, 2.0, 0.5, 100.0)
    assert fleet.is_online('pinky1', 103.0) is True
    assert fleet.is_online('pinky1', 103.01) is False


def test_patrol_status_alone_does_not_mark_online():
    # 순찰 상태는 상태가 바뀔 때만 오므로 연결 증거로 쓰지 않는다.
    fleet = FleetState(['pinky1'], 3.0)
    assert fleet.update_status('pinky1', '{"state": "IDLE"}', 100.0) is True
    assert fleet.is_online('pinky1', 100.0) is False


def test_battery_nan_is_unknown():
    fleet = FleetState(['pinky1'], 3.0)
    fleet.update_battery('pinky1', float('nan'), 100.0)
    robot = fleet.snapshot(100.0)['robots']['pinky1']
    assert robot['battery_percent'] is None
    assert robot['online'] is True


def test_unknown_robot_is_ignored():
    fleet = FleetState(['pinky1'], 3.0)
    assert fleet.update_status('pinky9', '{"state": "IDLE"}', 100.0) is False
    fleet.update_pose('pinky9', 0.0, 0.0, 0.0, 100.0)
    assert list(fleet.snapshot(100.0)['robots']) == ['pinky1']


def test_snapshot_is_json_serializable():
    fleet = FleetState(['pinky1', 'pinky2'], 3.0)
    fleet.update_status('pinky1', '{"state": "MOVING", "waypoint": 1, "detail": "P1"}', 99.0)
    fleet.update_pose('pinky1', 0.5, -0.25, 1.0, 99.5)
    fleet.update_battery('pinky1', 87.0, 99.5)
    assert fleet.update_zone('B:occupied_by:pinky1') is True
    assert fleet.update_zone('A:free') is True
    assert fleet.update_zone('broken') is False

    data = json.loads(json.dumps(fleet.snapshot(100.0)))
    pinky1 = data['robots']['pinky1']
    assert pinky1['online'] is True
    assert pinky1['last_seen_age'] == pytest.approx(0.5)
    assert pinky1['state'] == 'MOVING'
    assert pinky1['pose'] == {'x': 0.5, 'y': -0.25, 'yaw': 1.0}
    assert pinky1['battery_percent'] == 87.0
    assert data['robots']['pinky2']['never_seen'] is True
    assert data['zones'] == {'A': 'free', 'B': 'occupied_by:pinky1'}


def cov(var_x, var_y, var_yaw):
    values = [0.0] * 36
    values[0], values[7], values[35] = var_x, var_y, var_yaw
    return values


def test_std_from_covariance():
    std_xy, std_yaw = std_from_covariance(cov(0.0004, 0.0009, 0.01))
    assert std_xy == pytest.approx(0.03)
    assert std_yaw == pytest.approx(0.1)
    assert std_from_covariance(None) == (None, None)
    assert std_from_covariance([0.0] * 6) == (None, None)
    assert std_from_covariance(cov(float('nan'), 0.0, 0.0)) == (None, None)
    # 음수(수치 오차)는 0 으로 본다.
    assert std_from_covariance(cov(-1e-9, 0.0, 0.0)) == (0.0, 0.0)


POSE = {'x': 0.1, 'y': 0.2, 'yaw': 0.3}


def test_judge_teach_pose_ok_and_boundary():
    # 기준값과 같으면 통과, 넘으면 경고.
    ok = judge_teach_pose(True, POSE, 0.05, 0.1, 'ARRIVED', 0.05, 0.1)
    assert ok == {'ok': True, 'warnings': [], 'std_xy': 0.05, 'std_yaw': 0.1}
    over = judge_teach_pose(True, POSE, 0.0501, 0.1001, 'IDLE', 0.05, 0.1)
    assert over['ok'] is False
    assert len(over['warnings']) == 2


@pytest.mark.parametrize('state', sorted(MOVING_STATES))
def test_judge_teach_pose_warns_while_moving(state):
    result = judge_teach_pose(True, POSE, 0.01, 0.01, state, 0.05, 0.1)
    assert result['ok'] is False
    assert state in result['warnings'][0]


def test_judge_teach_pose_missing_values():
    result = judge_teach_pose(False, None, None, None, None, 0.05, 0.1)
    assert result['warnings'] == ['위치를 받은 적 없음', '로봇 연결 끊김',
                                  '위치 불확실성 모름 (공분산 없음)']


def test_snapshot_teach_uses_covariance_and_state():
    fleet = FleetState(['pinky1'], 3.0, teach_max_std_xy=0.05, teach_max_std_yaw=0.1)
    robot = fleet.snapshot(100.0)['robots']['pinky1']
    assert robot['pose_age'] is None
    assert robot['teach']['ok'] is False

    fleet.update_pose('pinky1', 1.0, 2.0, 0.5, 99.0, cov(0.0001, 0.0001, 0.0001))
    robot = fleet.snapshot(100.0)['robots']['pinky1']
    assert robot['pose_age'] == 1.0
    assert robot['teach'] == {'ok': True, 'warnings': [], 'std_xy': 0.01, 'std_yaw': 0.01}

    fleet.update_status('pinky1', json.dumps({'state': 'MOVING'}), 100.0)
    assert fleet.snapshot(100.0)['robots']['pinky1']['teach']['ok'] is False
    json.dumps(fleet.snapshot(100.0))


def alert_codes(snapshot):
    return {(a['robot'], a['code']) for a in snapshot['alerts']}


def test_topic_age_per_topic():
    fleet = FleetState(['pinky1'], 3.0)
    fleet.update_pose('pinky1', 0.0, 0.0, 0.0, 90.0)
    fleet.update_battery('pinky1', 80.0, 99.0)
    robot = fleet.snapshot(100.0)['robots']['pinky1']
    assert robot['topic_age'] == {'pose': 10.0, 'battery': 1.0, 'status': None}


def test_alert_battery_boundary_and_offline():
    fleet = FleetState(['pinky1'], 3.0, battery_warn_percent=20.0)
    fleet.update_battery('pinky1', 20.0, 100.0)
    assert ('pinky1', 'battery_low') in alert_codes(fleet.snapshot(100.0))
    fleet.update_battery('pinky1', 20.5, 100.0)
    assert alert_codes(fleet.snapshot(100.0)) == set()
    # 받은 적 없으면 끊김 경고를 내지 않고, 받았다가 끊기면 낸다.
    assert alert_codes(FleetState(['pinky1'], 3.0).snapshot(100.0)) == set()
    assert ('pinky1', 'offline') in alert_codes(fleet.snapshot(104.0))


def test_alert_bad_state():
    fleet = FleetState(['pinky1'], 3.0)
    fleet.update_battery('pinky1', 80.0, 100.0)
    fleet.update_status('pinky1', '{"state": "FAILED", "detail": "nav abort"}', 100.0)
    alerts = fleet.snapshot(100.0)['alerts']
    assert alerts == [{'robot': 'pinky1', 'code': 'state_bad', 'level': 'bad',
                       'text': 'FAILED: nav abort'}]


def test_alert_stuck_resets_on_start_and_on_move():
    fleet = FleetState(['pinky1'], 30.0, stuck_sec=15.0, stuck_distance_m=0.05)
    fleet.update_pose('pinky1', 0.0, 0.0, 0.0, 0.0)
    # 오래 서 있다가 출발: 출발 순간부터 잰다.
    fleet.update_status('pinky1', '{"state": "MOVING"}', 100.0)
    fleet.update_battery('pinky1', 80.0, 110.0)
    assert ('pinky1', 'stuck') not in alert_codes(fleet.snapshot(110.0))
    fleet.update_battery('pinky1', 80.0, 115.0)
    assert ('pinky1', 'stuck') in alert_codes(fleet.snapshot(115.0))
    # 0.05 m 이하 움직임은 제자리, 넘으면 다시 잰다.
    fleet.update_pose('pinky1', 0.04, 0.0, 0.0, 116.0)
    assert ('pinky1', 'stuck') in alert_codes(fleet.snapshot(116.0))
    fleet.update_pose('pinky1', 0.2, 0.0, 0.0, 117.0)
    assert ('pinky1', 'stuck') not in alert_codes(fleet.snapshot(117.0))


def test_alert_zone_hold():
    fleet = FleetState(['pinky1'], 3.0, zone_hold_warn_sec=200.0)
    fleet.update_zone('A:occupied_by:pinky1', 0.0)
    assert fleet.snapshot(199.0)['alerts'] == []
    alerts = fleet.snapshot(200.0)['alerts']
    assert alerts[0]['code'] == 'zone_hold' and alerts[0]['robot'] == 'pinky1'
    assert alerts[0]['zone'] == 'A'
    # 같은 값이 다시 와도 점유 시작 시각은 그대로.
    fleet.update_zone('A:occupied_by:pinky1', 150.0)
    assert fleet.snapshot(200.0)['alerts'][0]['code'] == 'zone_hold'


def snap(time, robots=None, zones=None, alerts=None):
    base = {'online': True, 'never_seen': False, 'state': None, 'detail': None,
            'waypoint': None, 'extra': {}}
    return {'time': time,
            'robots': {name: dict(base, **values) for name, values in (robots or {}).items()},
            'zones': zones or {}, 'alerts': alerts or []}


def test_diff_events_first_snapshot():
    events = diff_events(None, snap(1.0, {'pinky1': {'state': 'IDLE'},
                                          'pinky2': {'online': False, 'never_seen': True}}))
    assert [(e['robot'], e['kind'], e['text']) for e in events] == [
        ('pinky1', 'link', '연결됨'), ('pinky1', 'state', '- → IDLE')]


def test_diff_events_state_link_zone_alert():
    prev = snap(1.0, {'pinky1': {'state': 'MOVING', 'detail': 'P1'}}, {'A': 'free'},
                [{'robot': 'pinky1', 'code': 'battery_low', 'level': 'warn', 'text': '배터리 19%'}])
    curr = snap(2.0, {'pinky1': {'online': False, 'state': 'FAILED', 'detail': 'abort',
                                 'extra': {'command_id': 'job-1'}}},
                {'A': 'occupied_by:pinky1'},
                [{'robot': 'pinky1', 'code': 'stuck', 'level': 'warn', 'text': '끼임'},
                 {'robot': 'pinky1', 'code': 'offline', 'level': 'bad', 'text': '끊김'}])
    events = diff_events(prev, curr)
    assert [(e['kind'], e['level'], e['text']) for e in events] == [
        ('link', 'bad', '연결 끊김'),
        ('state', 'bad', 'MOVING → FAILED (abort)'),
        ('zone', 'info', '구역 A: 비어 있음 → pinky1'),
        ('alert', 'warn', '경고: 끼임'),
        ('clear', 'info', '해제: 배터리 19%')]
    # 모르는 필드(command_id)도 state 이벤트에 남긴다.
    assert events[1]['data']['extra'] == {'command_id': 'job-1'}
    assert events[2]['robot'] == 'pinky1'
    assert all(e['time'] == 2.0 for e in events)


def test_diff_events_zone_release_names_previous_holder():
    events = diff_events(snap(1.0, zones={'A': 'occupied_by:pinky2'}),
                         snap(2.0, zones={'A': 'free'}))
    assert events == [{'time': 2.0, 'robot': 'pinky2', 'kind': 'zone', 'level': 'info',
                       'text': '구역 A: pinky2 → 비어 있음'}]


def test_collect_events_only_new():
    fleet = FleetState(['pinky1'], 3.0)
    fleet.update_status('pinky1', '{"state": "IDLE"}', 100.0)
    assert [e['kind'] for e in fleet.collect_events(fleet.snapshot(100.0))] == ['state']
    assert fleet.collect_events(fleet.snapshot(101.0)) == []


def test_diff_events_detail_only_and_first_zone():
    events = diff_events(snap(1.0, {'pinky1': {'state': 'MOVING', 'detail': 'P5'}}),
                         snap(2.0, {'pinky1': {'state': 'MOVING', 'detail': 'P3'}},
                              {'A': 'free'}))
    assert [e['text'] for e in events] == ['MOVING (P5 → P3)', '구역 A: 비어 있음']


# ---------- 시계 차이 (로봇 시각 - 받은 시각) ----------

def test_clock_offset_values():
    assert clock_offset(101.25, 100.0) == 1.25
    assert clock_offset(99.0, 100.0) == -1.0
    for bad in (None, True, 'x', float('nan'), float('inf')):
        assert clock_offset(bad, 100.0) is None


def _clock_fleet(robot_time, now=100.0):
    fleet = FleetState(['pinky1'], 3.0, clock_warn_sec=0.5)
    fleet.update_battery('pinky1', 80.0, now)  # online 이 되게
    fleet.update_status('pinky1', json.dumps({'state': 'IDLE', 'time': robot_time}), now)
    return fleet.snapshot(now)


def test_clock_skew_alert_boundary():
    snap = _clock_fleet(100.4)
    assert snap['robots']['pinky1']['clock_offset_sec'] == 0.4
    assert not [a for a in snap['alerts'] if a['code'] == 'clock_skew']
    snap = _clock_fleet(98.8)
    skew = [a for a in snap['alerts'] if a['code'] == 'clock_skew']
    assert skew and skew[0]['level'] == 'warn' and '-1.2' in skew[0]['text']


def test_clock_skew_needs_robot_time_and_online():
    snap = _clock_fleet(None)
    assert snap['robots']['pinky1']['clock_offset_sec'] is None
    assert not [a for a in snap['alerts'] if a['code'] == 'clock_skew']
    fleet = FleetState(['pinky1'], 3.0, clock_warn_sec=0.5)
    fleet.update_status('pinky1', json.dumps({'state': 'IDLE', 'time': 50.0}), 100.0)
    # 위치·배터리를 받은 적 없어 offline 이면 시계 경고를 내지 않는다 (끊김 경고가 먼저)
    assert not [a for a in fleet.snapshot(100.0)['alerts'] if a['code'] == 'clock_skew']
