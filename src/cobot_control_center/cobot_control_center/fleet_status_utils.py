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
읽기 전용 관제: 로봇 상태 모으기 (ROS 없는 순수 로직).

fleet_status_node 가 받은 토픽 값을 여기로 넘기고, 여기서 만든 dict 를 JSON 으로 발행한다.
시각은 모두 인자로 받는다. 시험에서 시계를 흉내 내지 않고 경계값을 바로 넣기 위해서다.

연결 여부는 위치(amcl_pose)·배터리를 마지막으로 받은 시각으로만 판단한다.
patrol_status 는 순찰 노드가 상태가 바뀔 때만 발행하므로, 조용하다고 끊긴 것이 아니다.
"""

import json
import math

PATROL_STATUS_KEYS = ('state', 'waypoint', 'detail', 'time')

# 다른 DDS 구현(예: Cyclone ↔ Fast DDS) 사이에서는 노드 이름이 넘어오지 않아 이 값으로 보인다.
UNKNOWN_NODE_NAME = '_NODE_NAME_UNKNOWN_'


def parse_patrol_status(text):
    """
    patrol_status JSON 문자열을 dict 로 바꾼다.

    깨진 JSON 이나 dict 가 아닌 값이면 None 을 돌려준다 (예외를 내지 않는다).
    알려진 키는 그대로 두고, 그 밖의 키(예: command_id, task_finished)는 'extra' 에 모은다.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    parsed = {key: data.get(key) for key in PATROL_STATUS_KEYS}
    parsed['extra'] = {k: v for k, v in data.items() if k not in PATROL_STATUS_KEYS}
    return parsed


def parse_zone_status(text):
    """
    '/zone_manager/status' 문자열을 (구역, 상태) 로 나눈다.

    'A:free' -> ('A', 'free'), 'A:occupied_by:pinky1' -> ('A', 'occupied_by:pinky1').
    구역 이름이나 상태가 비면 None.
    """
    if not isinstance(text, str):
        return None
    zone, sep, state = text.partition(':')
    zone = zone.strip()
    state = state.strip()
    if not sep or not zone or not state:
        return None
    return zone, state


def count_state(count):
    """같은 역할 노드 개수를 상태로 바꾼다. 0 이면 missing, 1 이면 ok, 그 이상이면 duplicate."""
    if count <= 0:
        return 'missing'
    if count == 1:
        return 'ok'
    return 'duplicate'


def judge_infra(domain_id, control_domain_id, node_names, mock_node_name,
                bridge_names, zone_publishers, pose_publishers):
    """
    관제 PC 기반 노드(브릿지, zone_manager)가 떠 있는지 판정한다.

    node_names 는 그래프에서 이름이 보이는 노드 이름 목록(같은 이름도 그대로), bridge_names 는
    로봇별로 기대하는 브릿지 노드 이름, zone_publishers 는 /zone_manager/status 발행자 수,
    pose_publishers 는 로봇별 /<robot>/amcl_pose 발행자 노드 이름 목록이다.

    mode: 가짜 핑키가 보이면 'mock', 도메인이 control_domain_id 이면 'real', 그 밖은 'test'.
    실물이 아닐 때는 브릿지·zone_manager 가 없는 게 정상이므로 'n/a' 로 둔다.
    zone_manager 는 이름이 아니라 발행자 수로 센다. DDS 가 달라 이름이 안 보여도 개수는 보이기 때문이다.
    """
    names = list(node_names)
    if mock_node_name and mock_node_name in names:
        mode = 'mock'
    elif domain_id == control_domain_id:
        mode = 'real'
    else:
        mode = 'test'
    real = mode == 'real'

    bridges = {}
    for robot, bridge in bridge_names.items():
        count = names.count(bridge)
        if not real:
            state = 'n/a'
        elif count == 0 and UNKNOWN_NODE_NAME in pose_publishers.get(robot, []):
            # 이름 모를 노드가 위치를 내고 있다: 브릿지일 수 있지만 확인할 수 없다.
            state = 'unknown'
        else:
            state = count_state(count)
        bridges[robot] = {'state': state, 'count': count, 'node': bridge}

    return {
        'domain_id': domain_id,
        'control_domain_id': control_domain_id,
        'mode': mode,
        'zone_manager': {'state': count_state(zone_publishers) if real else 'n/a',
                         'count': zone_publishers},
        'bridges': bridges,
    }


def yaw_from_quaternion(x, y, z, w):
    """사원수에서 z 축 회전(yaw, [rad])을 구한다."""
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class RobotState:
    """로봇 한 대의 최신 값."""

    def __init__(self):
        self.last_seen = None      # 위치·배터리를 마지막으로 받은 시각 [s]
        self.status = None         # parse_patrol_status 결과
        self.status_received = None
        self.pose = None           # {'x', 'y', 'yaw'} [m], [m], [rad]
        self.battery_percent = None


class FleetState:
    """여러 로봇과 구역 상태를 모아 두고, 발행할 dict 를 만든다."""

    def __init__(self, robots, stale_timeout_sec):
        self.stale_timeout_sec = float(stale_timeout_sec)
        self.robots = {name: RobotState() for name in robots}
        self.zones = {}

    def update_status(self, robot, text, now):
        """patrol_status 를 반영한다. 깨진 값이면 False."""
        parsed = parse_patrol_status(text)
        if parsed is None or robot not in self.robots:
            return False
        state = self.robots[robot]
        state.status = parsed
        state.status_received = now
        return True

    def update_pose(self, robot, x, y, yaw, now):
        """위치를 반영하고 연결 시각을 갱신한다."""
        if robot not in self.robots:
            return
        state = self.robots[robot]
        state.pose = {'x': float(x), 'y': float(y), 'yaw': float(yaw)}
        state.last_seen = now

    def update_battery(self, robot, percent, now):
        """배터리를 반영하고 연결 시각을 갱신한다. NaN 은 '모름'(None)으로 둔다."""
        if robot not in self.robots:
            return
        state = self.robots[robot]
        value = float(percent)
        state.battery_percent = None if math.isnan(value) else value
        state.last_seen = now

    def update_zone(self, text):
        """구역 상태를 반영한다. 깨진 값이면 False."""
        parsed = parse_zone_status(text)
        if parsed is None:
            return False
        zone, zone_state = parsed
        self.zones[zone] = zone_state
        return True

    def is_online(self, robot, now):
        """마지막 수신 뒤 stale_timeout_sec 안이면 True. 받은 적이 없으면 False."""
        last_seen = self.robots[robot].last_seen
        if last_seen is None:
            return False
        return (now - last_seen) <= self.stale_timeout_sec

    def snapshot(self, now):
        """발행할 dict. JSON 으로 바꿀 수 있는 값만 담는다."""
        robots = {}
        for name, state in self.robots.items():
            status = state.status or {}
            robots[name] = {
                'online': self.is_online(name, now),
                'never_seen': state.last_seen is None,
                'last_seen_age': (None if state.last_seen is None
                                  else round(now - state.last_seen, 3)),
                'state': status.get('state'),
                'waypoint': status.get('waypoint'),
                'detail': status.get('detail'),
                'status_time': status.get('time'),
                'pose': state.pose,
                'battery_percent': state.battery_percent,
                'extra': status.get('extra', {}),
            }
        return {'time': now, 'robots': robots, 'zones': dict(sorted(self.zones.items()))}
