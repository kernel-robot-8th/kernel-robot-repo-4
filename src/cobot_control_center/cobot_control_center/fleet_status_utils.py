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

# 순찰 노드 state 중 로봇이 움직이는 중인 것. 이때 위치를 웨이포인트로 복사하면 안 된다.
MOVING_STATES = frozenset({'MOVING', 'STARTING', 'RETURNING', 'LEAVING_ZONE', 'RETREATING'})
# 사람이 봐야 하는 state. 화면·이벤트에서 빨강으로 표시한다.
BAD_STATES = frozenset({'FAILED', 'STOPPED'})
# 이벤트로 따로 남기지 않는 경고. 연결·state 이벤트가 같은 내용을 이미 남긴다.
ALERTS_WITHOUT_EVENT = frozenset({'offline', 'state_bad'})


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


def std_from_covariance(covariance):
    """
    위치(amcl PoseWithCovariance)의 6x6 공분산(36개, 행 우선)에서 (위치 표준편차 [m], yaw 표준편차 [rad]).

    위치는 x·y 중 큰 쪽을 쓴다. 공분산이 없거나 깨졌으면 (None, None).
    """
    try:
        values = [float(v) for v in covariance]
    except (TypeError, ValueError):
        return None, None
    if len(values) != 36 or any(math.isnan(v) for v in (values[0], values[7], values[35])):
        return None, None
    return (math.sqrt(max(values[0], values[7], 0.0)), math.sqrt(max(values[35], 0.0)))


def judge_teach_pose(online, pose, std_xy, std_yaw, state, max_std_xy, max_std_yaw):
    """
    지금 위치를 웨이포인트로 복사해도 되는지 판단한다. 막지는 않고 경고만 돌려준다.

    amcl 은 로봇이 멈춰 있으면 위치를 새로 내지 않으므로(update_min_d·a), 평균 대신 마지막
    추정값과 그 불확실성(공분산)으로 본다.
    """
    warnings = []
    if pose is None:
        warnings.append('위치를 받은 적 없음')
    if not online:
        warnings.append('로봇 연결 끊김')
    if state in MOVING_STATES:
        warnings.append(f'이동 중 ({state}). 멈춘 뒤 복사')
    if std_xy is None or std_yaw is None:
        warnings.append('위치 불확실성 모름 (공분산 없음)')
    else:
        if std_xy > max_std_xy:
            warnings.append(f'위치 불확실성 큼 (±{std_xy:.3f} m > {max_std_xy} m)')
        if std_yaw > max_std_yaw:
            warnings.append(f'방향 불확실성 큼 (±{std_yaw:.3f} rad > {max_std_yaw} rad)')
    return {'ok': not warnings, 'warnings': warnings,
            'std_xy': None if std_xy is None else round(std_xy, 4),
            'std_yaw': None if std_yaw is None else round(std_yaw, 4)}


class RobotState:
    """로봇 한 대의 최신 값."""

    def __init__(self):
        self.last_seen = None      # 위치·배터리를 마지막으로 받은 시각 [s]
        self.status = None         # parse_patrol_status 결과
        self.status_received = None
        self.pose = None           # {'x', 'y', 'yaw'} [m], [m], [rad]
        self.pose_received = None  # 위치를 마지막으로 받은 시각 [s]
        self.pose_std = (None, None)  # amcl 공분산에서 구한 (위치 [m], yaw [rad]) 표준편차
        self.battery_percent = None
        self.battery_received = None
        # 끼임 의심 판단용: 마지막으로 stuck_distance_m 넘게 움직인 위치와 시각.
        # amcl 은 멈춰 있으면 위치를 새로 내지 않으므로 '새 위치가 안 옴'도 제자리로 본다.
        self.moved_pose = None
        self.moved_at = None


def _age(now, received):
    return None if received is None else round(now - received, 3)


def judge_alerts(robots, zones, zone_since, now, battery_warn_percent, stuck_sec,
                 zone_hold_warn_sec):
    """
    지금 사람이 봐야 하는 경고 목록. 각 경고는 {'robot', 'code', 'level', 'text'} (+ 'zone').

    robots 는 snapshot 의 robots 에 '_moved_at' 을 더한 dict, zones 는 구역 상태, zone_since 는
    구역 상태가 마지막으로 바뀐 시각이다. level 은 'warn'(주황) 또는 'bad'(빨강).
    """
    alerts = []
    for name, robot in robots.items():
        if not robot['online'] and not robot['never_seen']:
            alerts.append({'robot': name, 'code': 'offline', 'level': 'bad',
                           'text': f'연결 끊김 ({robot["last_seen_age"]:.0f}초)'})
        battery = robot['battery_percent']
        if battery is not None and battery <= battery_warn_percent:
            alerts.append({'robot': name, 'code': 'battery_low', 'level': 'warn',
                           'text': f'배터리 {battery:.0f}%'})
        state = robot['state']
        if state in BAD_STATES:
            detail = f': {robot["detail"]}' if robot['detail'] else ''
            alerts.append({'robot': name, 'code': 'state_bad', 'level': 'bad',
                           'text': f'{state}{detail}'})
        moved_at = robot.get('_moved_at')
        if (robot['online'] and state in MOVING_STATES and moved_at is not None
                and now - moved_at >= stuck_sec):
            alerts.append({'robot': name, 'code': 'stuck', 'level': 'warn',
                           'text': f'{state} 인데 {now - moved_at:.0f}초째 거의 제자리 (끼임 의심)'})
    for zone, value in zones.items():
        since = zone_since.get(zone)
        if value.startswith('occupied_by:') and since is not None \
                and now - since >= zone_hold_warn_sec:
            alerts.append({'robot': value[len('occupied_by:'):], 'code': 'zone_hold',
                           'level': 'warn', 'zone': zone,
                           'text': f'구역 {zone} 을 {now - since:.0f}초째 점유'})
    return alerts


def _zone_label(value):
    if value is None:
        return '?'
    if value.startswith('occupied_by:'):
        return value[len('occupied_by:'):]
    return '비어 있음' if value == 'free' else value


def diff_events(prev, curr):
    """
    이전·지금 스냅샷을 비교해 이벤트 목록을 만든다 (state 변화, 연결·끊김, 구역, 경고).

    prev 가 None 이면(처음) 받은 적 있는 값만 이벤트로 남긴다. 이벤트는
    {'time', 'robot', 'kind', 'level', 'text'} 이고 state 이벤트는 'data' 를 더 갖는다.
    level 은 'info' / 'warn' / 'bad'.
    """
    events = []
    now = curr['time']
    prev_robots = (prev or {}).get('robots', {})

    def add(robot, kind, level, text, data=None):
        event = {'time': now, 'robot': robot, 'kind': kind, 'level': level, 'text': text}
        if data is not None:
            event['data'] = data
        events.append(event)

    for name, robot in curr['robots'].items():
        before = prev_robots.get(name, {})
        if robot['online'] != before.get('online', False):
            if robot['online']:
                add(name, 'link', 'info', '연결됨')
            elif not robot['never_seen']:
                add(name, 'link', 'bad', '연결 끊김')
        state, detail = robot['state'], robot['detail']
        if state is not None and (state, detail) != (before.get('state'), before.get('detail')):
            if state == before.get('state'):
                # 같은 state 에서 목표만 바뀜 (예: MOVING P5 → P3)
                text = f'{state} ({before.get("detail") or "-"} → {detail or "-"})'
            else:
                text = f'{before.get("state") or "-"} → {state}'
                if detail:
                    text += f' ({detail})'
            add(name, 'state', 'bad' if state in BAD_STATES else 'info', text,
                {'state': state, 'detail': detail, 'waypoint': robot['waypoint'],
                 'extra': robot['extra']})

    prev_zones = (prev or {}).get('zones', {})
    for zone, value in curr['zones'].items():
        old = prev_zones.get(zone)
        if value != old:
            occupier = value if value.startswith('occupied_by:') else (old or '')
            robot = occupier[len('occupied_by:'):] if occupier.startswith('occupied_by:') else None
            text = (f'구역 {zone}: {_zone_label(value)}' if old is None
                    else f'구역 {zone}: {_zone_label(old)} → {_zone_label(value)}')
            add(robot, 'zone', 'info', text)

    def key(alert):
        return (alert['robot'], alert['code'], alert.get('zone'))

    prev_alerts = {key(a): a for a in (prev or {}).get('alerts', [])}
    curr_alerts = {key(a): a for a in curr.get('alerts', [])}
    for k, alert in curr_alerts.items():
        if k not in prev_alerts and alert['code'] not in ALERTS_WITHOUT_EVENT:
            add(alert['robot'], 'alert', alert['level'], f'경고: {alert["text"]}')
    for k, alert in prev_alerts.items():
        if k not in curr_alerts and alert['code'] not in ALERTS_WITHOUT_EVENT:
            add(alert['robot'], 'clear', 'info', f'해제: {alert["text"]}')
    return events


class FleetState:
    """여러 로봇과 구역 상태를 모아 두고, 발행할 dict 를 만든다."""

    def __init__(self, robots, stale_timeout_sec, teach_max_std_xy=0.05, teach_max_std_yaw=0.1,
                 battery_warn_percent=20.0, stuck_sec=15.0, stuck_distance_m=0.05,
                 zone_hold_warn_sec=200.0):
        self.stale_timeout_sec = float(stale_timeout_sec)
        self.teach_max_std_xy = float(teach_max_std_xy)
        self.teach_max_std_yaw = float(teach_max_std_yaw)
        self.battery_warn_percent = float(battery_warn_percent)
        self.stuck_sec = float(stuck_sec)
        self.stuck_distance_m = float(stuck_distance_m)
        self.zone_hold_warn_sec = float(zone_hold_warn_sec)
        self.robots = {name: RobotState() for name in robots}
        self.zones = {}
        self.zone_since = {}       # 구역 상태가 마지막으로 바뀐 시각 [s]
        self._prev_snapshot = None

    def update_status(self, robot, text, now):
        """patrol_status 를 반영한다. 깨진 값이면 False."""
        parsed = parse_patrol_status(text)
        if parsed is None or robot not in self.robots:
            return False
        state = self.robots[robot]
        was_moving = (state.status or {}).get('state') in MOVING_STATES
        state.status = parsed
        state.status_received = now
        # 오래 서 있다가 출발했을 때 곧바로 끼임으로 보지 않도록, 출발 순간부터 다시 잰다.
        if parsed.get('state') in MOVING_STATES and not was_moving:
            state.moved_at = now
        return True

    def update_pose(self, robot, x, y, yaw, now, covariance=None):
        """위치를 반영하고 연결 시각을 갱신한다. covariance 는 amcl 의 6x6 공분산(36개)."""
        if robot not in self.robots:
            return
        state = self.robots[robot]
        state.pose = {'x': float(x), 'y': float(y), 'yaw': float(yaw)}
        state.pose_received = now
        state.pose_std = std_from_covariance(covariance)
        state.last_seen = now
        moved = state.moved_pose
        if moved is None or math.hypot(x - moved[0], y - moved[1]) > self.stuck_distance_m:
            state.moved_pose = (float(x), float(y))
            state.moved_at = now

    def update_battery(self, robot, percent, now):
        """배터리를 반영하고 연결 시각을 갱신한다. NaN 은 '모름'(None)으로 둔다."""
        if robot not in self.robots:
            return
        state = self.robots[robot]
        value = float(percent)
        state.battery_percent = None if math.isnan(value) else value
        state.battery_received = now
        state.last_seen = now

    def update_zone(self, text, now=None):
        """구역 상태를 반영한다. 깨진 값이면 False. now 는 점유 시간 경고에 쓴다."""
        parsed = parse_zone_status(text)
        if parsed is None:
            return False
        zone, zone_state = parsed
        if self.zones.get(zone) != zone_state:
            self.zone_since[zone] = now
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
            online = self.is_online(name, now)
            robots[name] = {
                'online': online,
                'never_seen': state.last_seen is None,
                'last_seen_age': (None if state.last_seen is None
                                  else round(now - state.last_seen, 3)),
                'state': status.get('state'),
                'waypoint': status.get('waypoint'),
                'detail': status.get('detail'),
                'status_time': status.get('time'),
                'pose': state.pose,
                'pose_age': (None if state.pose_received is None
                             else round(now - state.pose_received, 3)),
                'teach': judge_teach_pose(online, state.pose, *state.pose_std,
                                          status.get('state'), self.teach_max_std_xy,
                                          self.teach_max_std_yaw),
                'battery_percent': state.battery_percent,
                # 어느 토픽이 끊겼는지 보려고 따로 낸다 (브릿지 문제인지 로봇 노드 문제인지).
                'topic_age': {'pose': _age(now, state.pose_received),
                              'battery': _age(now, state.battery_received),
                              'status': _age(now, state.status_received)},
                'extra': status.get('extra', {}),
            }
        zones = dict(sorted(self.zones.items()))
        alerts = judge_alerts(
            {name: dict(robot, _moved_at=self.robots[name].moved_at)
             for name, robot in robots.items()},
            zones, self.zone_since, now, self.battery_warn_percent, self.stuck_sec,
            self.zone_hold_warn_sec)
        return {'time': now, 'robots': robots, 'zones': zones, 'alerts': alerts}

    def collect_events(self, snapshot):
        """직전에 넘긴 스냅샷과 비교해 새 이벤트를 돌려준다. 발행 주기마다 한 번 부른다."""
        events = diff_events(self._prev_snapshot, snapshot)
        self._prev_snapshot = snapshot
        return events
