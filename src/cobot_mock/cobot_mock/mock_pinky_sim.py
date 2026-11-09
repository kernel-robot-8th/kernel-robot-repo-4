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
가짜 핑키 시뮬레이션 (ROS 없는 순수 로직).

실제 순찰 노드(cobot_pinky_patrol/pinky_patrol_node_pinky1.py)의 명령·상태 순서와
zone_manager 의 토큰·대기열을 흉내 낸다. Nav2·장치는 쓰지 않고 위치를 직선으로 옮긴다.
관제 코드가 진짜와 구분하지 못하게 상태 문자열(state, detail)을 실제와 같게 맞춘다.

시각(now)과 dt 는 모두 인자로 받는다. 이벤트는 dict 로 돌려주고 ROS 발행은 노드가 한다.
"""

from collections import deque
import json
import math
import os
import time

import yaml

# 실물이 쓰는 도메인. 0 은 '지정 안 함' 이라 실물과 섞일 수 있어 같이 막는다.
FORBIDDEN_DOMAINS = {0, 10, 12, 20, 30, 100}
ARRIVE_EPS_M = 1e-3
# 구역 진입·대기 단계 처리 결과
PROCEED, WAIT, REPLACED = 'proceed', 'wait', 'replaced'


class MockConfigError(Exception):
    """핑키 설정 파일을 찾거나 읽지 못함."""


def check_domain(env):
    """
    가짜 이벤트를 내도 되는 도메인인지 본다. (ok, 메시지) 를 돌려준다.

    실물 도메인에서 /pinkyN/* 를 내면 진짜 관제가 가짜 로봇을 진짜로 믿게 된다.
    """
    raw = env.get('ROS_DOMAIN_ID', '')
    try:
        domain = int(raw)
    except ValueError:
        return False, 'ROS_DOMAIN_ID 가 비어 있음: 격리 도메인(예: 101)을 지정하세요'
    if domain in FORBIDDEN_DOMAINS:
        return False, (f'ROS_DOMAIN_ID={domain} 은 실물 도메인({sorted(FORBIDDEN_DOMAINS)}): '
                       '가짜 핑키를 띄우지 않습니다. 예: 101')
    return True, f'ROS_DOMAIN_ID={domain}'


def _ros_params(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return next(iter(data.values()))['ros__parameters']
    except (OSError, yaml.YAMLError, AttributeError, KeyError, StopIteration, TypeError) as e:
        raise MockConfigError(f'설정을 읽지 못함: {path}') from e


def load_robot_config(path):
    """합쳐진 순찰 설정 파일 하나(pinkyN.yaml)에서 지점·구역·홈을 읽는다."""
    return _robot_config(_ros_params(path), path)


def _split_params(points_dir, robot, site):
    """순찰 launch 와 같은 순서로 공통 → 현장 → 로봇 파일을 합친다. 같은 키는 뒤 파일이 이긴다."""
    params = {}
    for path in (os.path.join(points_dir, 'common.yaml'),
                 os.path.join(points_dir, 'sites', f'{site}.yaml'),
                 os.path.join(points_dir, 'robots', f'{robot}.yaml')):
        params.update(_ros_params(path))
    return params


def _robot_config(params, path):
    """
    순찰 설정 값에서 지점·구역·홈을 뽑는다.

    (0, 0, 0) 인 P 지점은 미실측 예비 점이라 뺀다 (지도 뷰어와 같은 규칙).
    """
    points = {}
    for name, value in (params.get('points') or {}).items():
        x, y = float(value[0]), float(value[1])
        yaw = float(value[2]) if len(value) > 2 else 0.0
        if name.startswith('P') and x == 0.0 and y == 0.0 and yaw == 0.0:
            continue
        points[name] = (x, y, yaw)
    zone_points = {str(z): list(names) for z, names in (params.get('zone_points') or {}).items()}
    home = params.get('home_name')
    if home not in points:
        raise MockConfigError(f'홈 지점이 points 에 없음: {home} ({path})')
    return {'robot_id': params.get('robot_id'), 'home': home,
            'points': points, 'zone_points': zone_points}


def load_robot_configs(points_dir, robots, site='lab'):
    """
    로봇 이름마다 설정을 읽는다.

    <points_dir>/<이름>.yaml 이 있으면 그 파일을, 없으면 common·sites·robots 를 합쳐 쓴다.
    """
    configs = {}
    for robot in robots:
        flat = os.path.join(points_dir, f'{robot}.yaml')
        if os.path.exists(flat) or not os.path.exists(os.path.join(points_dir, 'common.yaml')):
            configs[robot] = load_robot_config(flat)
        else:
            configs[robot] = _robot_config(_split_params(points_dir, robot, site), points_dir)
    return configs


def load_zone_params(path):
    """zone_manager 설정(zone_params.yaml)에서 구역별 대기 앵커·방향과 공통 값을 읽는다."""
    params = _ros_params(path)
    zones = {}
    for name in params.get('zone_names', []):
        z = params.get(f'zone_{name}', {})
        anchor = [float(v) for v in z.get('queue_anchor', [0.0, 0.0, 0.0])]
        back = [float(v) for v in z.get('queue_back_dir', [0.0, -1.0])]
        norm = math.hypot(back[0], back[1]) or 1.0
        yaw = anchor[2] if len(anchor) > 2 else 0.0
        zones[str(name)] = {'anchor': (anchor[0], anchor[1], yaw),
                            'back': (back[0] / norm, back[1] / norm)}
    return {'zones': zones,
            'spacing': float(params.get('queue_spacing', 0.3)),
            'queue_max': int(params.get('queue_max', 3)),
            'max_hold_sec': float(params.get('max_hold_sec', 240.0))}


def parse_command(raw):
    """
    patrol_cmd 문자열을 (kind, names, command_id) 로 나눈다.

    JSON 봉투 {"command_id": .., "command": ".."} 도 받는다. 형식이 틀리면 kind 가 None.
    """
    command_id = None
    text = raw.strip() if isinstance(raw, str) else ''
    if text.startswith('{'):
        try:
            envelope = json.loads(text)
            command_id, text = envelope['command_id'], envelope['command']
        except (ValueError, KeyError, TypeError):
            return None, [], None
        if not isinstance(command_id, str) or not command_id or not isinstance(text, str):
            return None, [], None
        text = text.strip()
    kind, _, rest = text.partition(':')
    names = [n.strip() for n in rest.split(',') if n.strip()]
    if kind not in ('goto', 'zone', 'leave', 'home', 'stop', 'emergency_stop', 'start'):
        return None, names, command_id
    return kind, names, command_id


class CentralGuard:
    """
    중앙 관제(fleet_control) 명령 허용 규칙. 실제 순찰 노드의 central_guard.py 와 같게 맞춘다.

    패키지끼리 import 하지 않는 규칙(CLAUDE.md 3-6) 때문에 복사해 둔다. 실제 파일이 바뀌면 같이 고친다.
    - 하트비트는 연결 상태만 살린다. 정지 잠금(latched)은 풀지 않는다.
    - 명령은 연결이 살아 있을 때 현재 세션에서 순번이 늘어나는 것만 받는다. 잠긴 동안은 control_reset 만.
    - PC 끼리 시계를 비교하지 않는다 (issued_at·ttl_sec 는 보지 않음, 2026-11-09).
    - 서버 세션이 바뀌거나 하트비트가 끊기면 잠근다.
    """

    def __init__(self, timeout_sec=3.0, clock=time.monotonic):
        self.timeout, self.clock = timeout_sec, clock
        self.session = None
        self.heartbeat_seq = self.command_seq = 0
        self.received = None
        self.latched = False
        self.retired_sessions = set()

    @property
    def healthy(self):
        return self.received is not None and self.clock() - self.received < self.timeout

    def heartbeat(self, payload, busy=True):
        """서버 세션이 바뀌어 정지해야 하면 True. 움직이던 중일 때만 (실물 순찰 노드와 같음)."""
        if not isinstance(payload, dict):
            return False
        session, seq = payload.get('session_id'), payload.get('seq')
        if (not isinstance(session, str) or not session or isinstance(seq, bool)
                or not isinstance(seq, int) or seq <= 0 or session in self.retired_sessions):
            return False
        changed = self.session is not None and session != self.session and busy
        if session == self.session and seq <= self.heartbeat_seq:
            return False
        if session != self.session:
            if self.session:
                self.retired_sessions.add(self.session)
            self.session, self.heartbeat_seq, self.command_seq = session, 0, 0
        if changed:
            self.latched = True
        self.heartbeat_seq, self.received = seq, self.clock()
        return changed

    def expired(self, busy=True):
        """움직이던 중 하트비트가 끊기면 한 번만 True (그때 잠근다). 놀던 중이면 잠그지 않는다."""
        if busy and self.received is not None and not self.healthy and not self.latched:
            self.latched = True
            return True
        return False

    def stop(self, emergency=False):
        """정지는 늘 받는다. 잠금은 비상정지만 건다 (실물 CentralGuard.stop 과 같음)."""
        if emergency:
            self.latched = True

    def accept(self, payload, reset=False):
        """현재 세션·늘어나는 순번의 명령만 받는다. reset 이면 잠금을 푼다."""
        if (not self.healthy or not isinstance(payload, dict)
                or payload.get('session_id') != self.session or (self.latched and not reset)):
            return False
        seq = payload.get('seq')
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= self.command_seq:
            return False
        self.command_seq = seq
        if reset:
            self.latched = False
        return True


def central_command(guard, raw):
    """
    중앙 모드에서 patrol_cmd 를 거른다. (로봇에 넘길 명령 또는 None, 처리 결과) 를 돌려준다.

    결과: 'stop' (정지는 늘 받음, 잠금은 비상정지만), 'reset' (잠금 해제, 로봇에 넘기지 않음),
    'accepted', 'rejected'. 실제 순찰 노드 _cmd_cb 와 같은 순서다.
    """
    envelope = None
    text = raw.strip() if isinstance(raw, str) else ''
    if text.startswith('{'):
        try:
            envelope = json.loads(text)
            command = envelope['command']
        except (ValueError, KeyError, TypeError):
            return None, 'rejected'
        if not isinstance(command, str):
            return None, 'rejected'
    else:
        command = text
    kind = command.strip().lower()
    if kind in ('stop', 'emergency_stop'):
        # 일반 정지는 멈추고(구역 안이면 물러나) 끝, 잠그지 않는다 (실물 순찰 노드와 같음)
        guard.stop(emergency=kind == 'emergency_stop')
        return raw, 'stop'
    if command == 'control_reset':
        return None, 'reset' if guard.accept(envelope or {}, True) else 'rejected'
    if not guard.accept(envelope or {}):
        return None, 'rejected'
    return raw, 'accepted'


V2_OPERATIONS = ('goto', 'zone', 'leave', 'home', 'stop', 'emergency_stop')
STOP_OPERATIONS = ('stop', 'emergency_stop')


def v2_to_v1(task_id, operation, points):
    """
    v2 PatrolCommand 를 v1 명령(JSON 봉투)으로 바꾼다. (명령 문자열, 거절 이유) 를 돌려준다.

    로봇 동작은 v1 과 같게 두고 형식만 바꾸려고, v2 명령도 v1 처리기를 그대로 탄다.
    """
    if not task_id:
        return None, 'bad task_id'
    if operation not in V2_OPERATIONS:
        return None, 'unknown operation'
    command = operation + (':' + ','.join(points) if points else '')
    return json.dumps({'command_id': task_id, 'command': command}), None


def ack_for(operation, events):
    """
    명령 처리 결과(command() 가 돌려준 이벤트)로 v2 받음/거절을 정한다. (accepted, reason).

    v1 은 바쁠 때 아무것도 내지 않으므로 빈 결과를 'busy'(stop 계열은 'not running')로 읽는다.
    검증 실패는 첫 이벤트가 FAILED 하나로 바로 온다. 그 detail 을 거절 이유로 쓴다.
    """
    if not events:
        return False, 'not running' if operation in STOP_OPERATIONS else 'busy'
    first = events[0]
    if len(events) == 1 and first['state'] == 'FAILED':
        return False, first['detail']
    return True, ''


def exit_name(zone):
    """구역 출구 이름. 실제 patrol_points_utils.exit_name 과 같다."""
    return f'Z{zone}_EXIT'


def choose_auto_command(robot, rng):
    """
    쉬는 로봇에게 줄 무작위 명령 문자열. 실제 관제가 보낼 법한 명령만 고른다.

    배터리가 낮으면 홈, 구역을 쥐고 있으면 대개 leave, 그 밖에는 goto(1~3곳) 또는 zone.
    """
    if robot.charging or robot.battery < 15.0:
        return 'home'
    if robot.held_zone is not None and rng.random() < 0.7:
        return 'leave'
    general = sorted(n for n in robot.points if robot._goto_allowed(n) and n != robot.home)
    zone_targets = sorted(n for names in robot.zone_points.values() for n in names)
    if zone_targets and rng.random() < 0.3:
        return f'zone:{rng.choice(zone_targets)}'
    if not general:
        return 'home'
    return 'goto:' + ','.join(rng.sample(general, rng.randint(1, min(3, len(general)))))


class ZoneBook:
    """구역마다 토큰 1개와 FIFO 대기열 (zone_manager 흉내)."""

    def __init__(self, zone_params):
        self.params = zone_params
        self.owner = {z: None for z in zone_params['zones']}
        self.granted_at = {z: None for z in zone_params['zones']}
        self.queue = {z: [] for z in zone_params['zones']}

    def request(self, zone, robot, now):
        """'granted', 대기 순번 k(0 부터), 또는 -1(대기열 가득)."""
        if self.owner[zone] in (None, robot):
            self.owner[zone] = robot
            self.granted_at[zone] = now
            if robot in self.queue[zone]:
                self.queue[zone].remove(robot)
            return 'granted'
        if robot not in self.queue[zone]:
            if len(self.queue[zone]) >= self.params['queue_max']:
                return -1
            self.queue[zone].append(robot)
        return self.queue[zone].index(robot)

    def slot_of(self, zone, robot):
        q = self.queue[zone]
        return q.index(robot) if robot in q else None

    def slot_pose(self, zone, k):
        """대기 슬롯 k 좌표 = 앵커 + k * 간격 * 후방벡터 (zone_manager 와 같은 식)."""
        z = self.params['zones'][zone]
        d = k * self.params['spacing']
        ax, ay, ayaw = z['anchor']
        return (ax + d * z['back'][0], ay + d * z['back'][1], ayaw)

    def release(self, zone, robot, now):
        """점유자만 반납할 수 있다. 반납되면 대기열 선두가 점유자가 된다."""
        if zone is None or self.owner.get(zone) != robot:
            return
        self._promote(zone, now)

    def cancel(self, zone, robot):
        if zone in self.queue and robot in self.queue[zone]:
            self.queue[zone].remove(robot)

    def tick(self, now):
        """max_hold_sec 를 넘긴 점유는 강제로 푼다 (점유자가 반납하지 못한 경우 대비)."""
        for zone, owner in self.owner.items():
            if owner and now - self.granted_at[zone] > self.params['max_hold_sec']:
                self._promote(zone, now)

    def _promote(self, zone, now):
        q = self.queue[zone]
        self.owner[zone] = q.pop(0) if q else None
        self.granted_at[zone] = now if self.owner[zone] else None

    def slot_lines(self):
        """'/zone_manager/queue_slot' 로 낼 문자열 목록 (zone_manager 와 같은 형식, 대기 로봇마다)."""
        lines = []
        for zone, q in sorted(self.queue.items()):
            for k, robot in enumerate(q):
                x, y, yaw = self.slot_pose(zone, k)
                lines.append(f'{zone}:{robot}:{k}:{x:.3f},{y:.3f},{yaw:.3f}')
        return lines

    def status_lines(self):
        """'/zone_manager/status' 로 낼 문자열 목록."""
        return [f'{z}:free' if o is None else f'{z}:occupied_by:{o}'
                for z, o in sorted(self.owner.items())]


class RobotSim:
    """
    핑키 한 대. command() 와 step() 이 상태 이벤트 목록을 돌려준다.

    작업은 단계(step) 목록으로 펼쳐 순서대로 처리한다. 구역 진입처럼 결과에 따라 갈리는
    단계는 처리할 때 다음 단계를 앞에 끼워 넣는다.
    """

    def __init__(self, name, config, book, speed_mps=0.15, idle_return_sec=40.0,
                 battery=100.0, drain_moving=1.0, drain_idle=0.2, charge_per_min=5.0):
        self.name = name
        self.points = config['points']
        self.zone_points = config['zone_points']
        self.home = config['home']
        self.book = book
        self.speed = float(speed_mps)
        self.idle_return_sec = float(idle_return_sec)
        self.drain_moving = drain_moving
        self.drain_idle = drain_idle
        self.charge_per_min = charge_per_min
        self.pose = self.points[self.home]
        self.battery = float(battery)
        self.charging = False
        self.held_zone = None
        self.arrived_zone = None     # 구역 목표에 실제로 도착했을 때만 (held_zone 은 예약 토큰)
        self.last_point = self.home
        self.steps = deque()
        self.running = False
        self.moving = False
        self.command_id = None
        self.last_task_id = ''       # v2 PatrolState.task_id: 진행 중 또는 마지막 작업 ('' = 관제가 안 보냄)
        self.last_event = {'state': 'IDLE', 'waypoint': -1, 'detail': ''}
        self.ctx = (-1, '')          # stop 때 낼 (waypoint, detail)
        self.idle_deadline = None
        self.finished_at = 0.0

    # ---------- 지점 분류 (실제 노드의 zone_allowed / goto_allowed) ----------

    def zone_of(self, name):
        for zone, names in self.zone_points.items():
            if name in names:
                return zone
        return None

    def _goto_allowed(self, name):
        # 일반 지점(P*)과 자기 홈만. 다른 로봇 홈·구역 출구는 막는다.
        return name == self.home or (name.startswith('P') and self.zone_of(name) is None)

    # ---------- 이벤트 ----------

    def _event(self, state, waypoint, detail, final=False):
        ev = {'state': state, 'waypoint': waypoint, 'detail': detail}
        self.last_event = ev
        if self.command_id is not None:
            ev['command_id'] = self.command_id
            ev['task_finished'] = final
        return ev

    def status(self, ev=None):
        """v1 patrol_status 에 실을 값. 실제 순찰 노드처럼 구역·바쁨 상태를 함께 싣는다."""
        if ev is None:
            # 주기 발행: 끝난 작업의 완료 표시를 새 완료 근거로 다시 보내지 않는다 (실제 노드와 같게)
            ev = dict(self.last_event, task_finished=False)
            ev.pop('command_id', None)
            if self.command_id is not None:
                ev['command_id'] = self.command_id
        else:
            ev = dict(ev)
        ev.update(held_zone=self.held_zone, arrived_zone=self.arrived_zone, busy=self.running)
        return ev

    def v2_state(self, ev=None):
        """v2 PatrolState 에 실을 값. ev 가 없으면 마지막 상태 (1초 주기 발행용)."""
        ev = ev or self.last_event
        return {'state': ev['state'], 'waypoint': ev['waypoint'], 'detail': ev['detail'],
                'task_id': self.last_task_id,
                'task_finished': ev.get('task_finished', not self.running),
                'held_zone': self.held_zone or ''}

    # ---------- 명령 ----------

    def command(self, raw, now):
        """patrol_cmd 하나를 처리한다. 실제 노드처럼 검증 실패는 바로 FAILED, 작업 중이면 무시."""
        kind, names, command_id = parse_command(raw)
        if kind is None:
            return [self._reject(command_id, f'unknown command: {raw}')]
        if kind in ('stop', 'emergency_stop'):
            return self._stop(kind == 'emergency_stop', now)
        if kind == 'start':
            return [self._reject(command_id, 'start disabled')]
        if kind == 'home':
            if self.running:
                return []
            return self._start(self._plan_return('home'), command_id, now)
        if kind == 'leave':
            if self.running:
                return []
            if self.held_zone is None:
                return [self._reject(command_id, 'no zone held')]
            return self._start(self._plan_leave(), command_id, now)

        if not names:
            return [self._reject(command_id, 'no point given')]
        unknown = [n for n in names if n not in self.points]
        if unknown:
            return [self._reject(command_id, f'unknown point: {unknown}')]
        if kind == 'goto':
            in_zone = [n for n in names if self.zone_of(n) is not None]
            if in_zone:
                return [self._reject(command_id, f'use zone: {in_zone}')]
            denied = [n for n in names if not self._goto_allowed(n)]
            if denied:
                return [self._reject(command_id, f'not allowed: {denied}')]
        elif len(names) != 1 or self.zone_of(names[0]) is None:
            return [self._reject(command_id, f'zone needs one zone point: {list(names)}')]
        if self.running:
            return []
        plan = self._plan_goto(names) if kind == 'goto' else self._plan_zone(names[0])
        return self._start(plan, command_id, now)

    def _reject(self, command_id, detail):
        ev = {'state': 'FAILED', 'waypoint': -1, 'detail': detail}
        if command_id is not None:
            ev.update(command_id=command_id, task_finished=True)
        return ev

    def _start(self, plan, command_id, now):
        # 도착 증거는 이동을 시작하면 다시 확인해야 한다 (실제 patrol_controller 와 같게)
        self.arrived_zone = None
        self.command_id = command_id
        self.last_task_id = command_id or ''
        self.steps = deque(plan)
        self.running = True
        self.idle_deadline = None
        self.charging = False
        return self._run(now, 0.0)

    # ---------- 작업 계획 (실제 노드의 _run_goto / _run_zone / _run_leave / _run_idle_return) ----------

    def _plan_exit_held(self, idx):
        zone = self.held_zone
        ex = exit_name(zone)
        return [('status', 'LEAVING_ZONE', idx, ex), ('move', self.points[ex], idx, ex),
                ('release', zone)]

    def _plan_goto(self, names):
        plan = [('status', 'STARTING', -1, ','.join(names))]
        if self.held_zone is not None:
            plan += self._plan_exit_held(-1)
        for idx, name in enumerate(names):
            plan += [('status', 'MOVING', idx, name), ('move', self.points[name], idx, name),
                     ('arrive', name), ('status', 'ARRIVED', idx, name)]
        plan += [('end', 'DONE', -1, f'arrived {names[-1]}', True)]
        return plan

    def _plan_zone(self, name):
        target = self.zone_of(name)
        plan = [('status', 'STARTING', -1, name)]
        if self.held_zone is not None and self.held_zone != target:
            plan += self._plan_exit_held(0)
        if self.held_zone != target:
            plan += [('enter', target, 0, name)]
        plan += [('status', 'MOVING', 0, name), ('move', self.points[name], 0, name),
                 ('arrive', name), ('status', 'ARRIVED', 0, name),
                 ('end', 'DONE', -1, f'arrived {name}', True)]
        return plan

    def _plan_leave(self):
        return [('status', 'STARTING', -1, 'leave')] + self._plan_exit_held(-1) + [
            ('arrive', None), ('end', 'DONE', -1, 'left zone', True)]

    def _plan_return(self, detail):
        plan = [('status', 'STARTING', -1, detail)]
        if self.held_zone is not None:
            plan += self._plan_exit_held(-1)
        if self.last_point != self.home or self.held_zone is not None:
            plan += [('status', 'RETURNING', -1, self.home),
                     ('move', self.points[self.home], -1, 'return'), ('arrive', self.home)]
        plan += [('end', 'DONE', -1, 'returned home', False)]
        return plan

    # ---------- 진행 ----------

    def step(self, now, dt):
        """시간을 dt 초 진행한다. 배터리·유휴 복귀·작업 단계를 처리하고 이벤트를 돌려준다."""
        self._battery(dt)
        events = []
        if (not self.running and self.idle_deadline is not None
                and now >= self.idle_deadline):
            self.idle_deadline = None
            events += self._start(self._plan_return('idle return'), None, now)
            return events
        if self.running:
            events += self._run(now, dt)
        return events

    def _battery(self, dt):
        at_home = self._dist(self.points[self.home]) < 0.02 and not self.running
        if self.battery < 15.0:
            self.charging = True
        if self.charging and at_home:
            self.battery = min(100.0, self.battery + self.charge_per_min * dt / 60.0)
            if self.battery >= 95.0:
                self.charging = False
            return
        rate = self.drain_moving if self.moving else self.drain_idle
        self.battery = max(0.0, self.battery - rate * dt / 60.0)

    def _dist(self, target):
        return math.hypot(target[0] - self.pose[0], target[1] - self.pose[1])

    def _run(self, now, dt):
        events = []
        budget = dt
        while self.steps:
            step = self.steps[0]
            kind = step[0]
            if kind == 'status':
                _, state, idx, detail = step
                self.ctx = (idx, detail)
                events.append(self._event(state, idx, detail))
            elif kind == 'move':
                budget = self._move(step[1], budget)
                if self._dist(step[1]) > ARRIVE_EPS_M:
                    return events
                self.pose = step[1]
                self.moving = False
            elif kind == 'arrive':
                if step[1] is not None:
                    self.last_point = step[1]
                    if self.held_zone is not None and self.zone_of(step[1]) == self.held_zone:
                        self.arrived_zone = self.held_zone
                else:
                    self.last_point = None
            elif kind == 'release':
                self.book.release(step[1], self.name, now)
                self.held_zone = None
                self.arrived_zone = None
            elif kind in ('enter', 'queued'):
                # PROCEED: 이 단계를 끝내고 다음으로 / WAIT: 다음 틱에 다시 / REPLACED: 단계를 바꿔 끼움
                handler = self._enter if kind == 'enter' else self._wait_grant
                result = handler(step, now, events)
                if result == WAIT:
                    return events
                if result == REPLACED:
                    continue
            elif kind == 'end':
                _, state, idx, detail, arm = step
                self.steps.popleft()
                events += self._finish(state, idx, detail, now, arm)
                return events
            self.steps.popleft()
        return events

    def _move(self, target, budget):
        """목표 쪽으로 budget 초만큼 직선 이동한다. 남은 시간을 돌려준다."""
        dist = self._dist(target)
        if dist <= ARRIVE_EPS_M:
            self.pose = target
            return budget
        self.moving = True
        heading = math.atan2(target[1] - self.pose[1], target[0] - self.pose[0])
        reach = self.speed * budget
        if reach >= dist:
            self.pose = target
            self.moving = False
            return budget - dist / self.speed
        ratio = reach / dist
        self.pose = (self.pose[0] + (target[0] - self.pose[0]) * ratio,
                     self.pose[1] + (target[1] - self.pose[1]) * ratio, heading)
        return 0.0

    def _enter(self, step, now, events):
        """구역 진입 요청. 허가면 다음 단계로, 대기면 슬롯으로 가서 QUEUEING."""
        _, zone, idx, name = step
        result = self.book.request(zone, self.name, now)
        if result == 'granted':
            self.held_zone = zone
            return PROCEED
        if result == -1:
            self.steps.clear()
            events += self._finish('FAILED', idx, 'queue_full', now, arm=False)
            return WAIT
        self._replace_first([
            ('status', 'MOVING', idx, 'slot'),
            ('move', self.book.slot_pose(zone, result), idx, 'slot'),
            ('status', 'QUEUEING', idx, f'slot{result}'),
            ('queued', zone, idx, name, result)])
        return REPLACED

    def _replace_first(self, new_steps):
        self.steps.popleft()
        self.steps.extendleft(reversed(new_steps))

    def _wait_grant(self, step, now, events):
        """대기 중: 점유자가 되면 진입, 순번이 앞당겨지면 새 슬롯으로 이동."""
        _, zone, idx, name, k = step
        if self.book.owner[zone] == self.name:
            self.held_zone = zone
            return PROCEED
        current = self.book.slot_of(zone, self.name)
        if current is None:                       # 대기열에서 빠짐 (실제로는 stale 제거)
            self.book.request(zone, self.name, now)
            return WAIT
        if current != k:
            self._replace_first([
                ('move', self.book.slot_pose(zone, current), idx, 'slot'),
                ('status', 'QUEUEING', idx, f'slot{current}'),
                ('queued', zone, idx, name, current)])
            return REPLACED
        return WAIT

    def _stop(self, emergency, now):
        # 실제 patrol_controller.stop() 과 같게: 정지는 유휴 복귀 예약을 지우고,
        # 쉬는 중이어도 구역을 잡고 있으면 처리한다 (일반 정지 = 물러나기, 비상정지 = 제자리).
        self.idle_deadline = None
        if not self.running and self.held_zone is None:
            return []
        if not self.running:
            if emergency:
                return self._finish('STOPPED', -1, 'emergency_stop: 구역 토큰 유지', now, arm=False)
            ex = exit_name(self.held_zone)
            return self._start([('status', 'RETREATING', -1, ex),
                                ('move', self.points[ex], -1, ex),
                                ('release', self.held_zone), ('arrive', None),
                                ('end', 'STOPPED', -1, 'retreated', False)], None, now)
        idx, detail = self.ctx
        for zone in self.book.queue:
            self.book.cancel(zone, self.name)
        self.steps.clear()
        self.moving = False
        if self.held_zone is not None and not emergency:
            # 실제 노드: 작업은 STOPPED 로 끝나고, 마무리에서 EXIT 로 후퇴해 반납한 뒤 다시 STOPPED.
            ex = exit_name(self.held_zone)
            self.steps.extend([('status', 'STOPPED', idx, detail),
                               ('status', 'RETREATING', -1, ex),
                               ('move', self.points[ex], -1, ex),
                               ('release', self.held_zone), ('arrive', None),
                               ('end', 'STOPPED', -1, 'retreated', False)])
            return self._run(now, 0.0)
        if emergency:
            # 실제 노드처럼 토큰을 쥔 채 제자리에 선다 (held_zone 유지). 복구 뒤 leave 로 나간다.
            return self._finish('STOPPED', idx, 'emergency_stop: 구역 토큰 유지'
                                if self.held_zone else detail, now, arm=False)
        return self._finish('STOPPED', idx, detail, now, arm=False)

    def _finish(self, state, idx, detail, now, arm):
        events = [self._event(state, idx, detail, final=True)]
        self.command_id = None
        self.running = False
        self.moving = False
        self.finished_at = now
        if arm:
            events += self._arm_idle(now)
        return events

    def _arm_idle(self, now):
        events = []
        if self.held_zone is not None:
            events.append(self._event('HOLDING_ZONE', -1, self.held_zone))
        if self.idle_return_sec <= 0:
            return events
        if self.held_zone is None and self.last_point == self.home:
            return events
        self.idle_deadline = now + self.idle_return_sec
        events.append(self._event('IDLE_WAIT', -1, f'{self.idle_return_sec:g}'))
        return events
