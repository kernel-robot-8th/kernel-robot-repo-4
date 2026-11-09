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
관제 백엔드: 최신 fleet_status 스냅샷·작업 목록·카메라 프레임 보관 (ROS·fastapi 없는 순수 로직).

ROS 콜백 스레드가 put() 으로 넣고, 웹 서버 스레드가 get()·wait_newer() 로 읽는다 (TaskStore·CameraStore 도 같다).
그래서 모든 접근을 lock 으로 감싼다. 시각은 clock 인자로 받아 시험에서 바꿔 끼운다.
"""

import collections
import json
import math
import os
import threading
import time
import uuid

import yaml


class MapError(Exception):
    """지도 파일을 찾거나 읽지 못함."""


def _pgm_size(data):
    """P5(바이너리 PGM) 헤더에서 (가로, 세로)를 읽는다. '#' 주석 줄은 건너뛴다."""
    tokens = []
    pos = 0
    while len(tokens) < 4 and pos < len(data):
        if data[pos:pos + 1] == b'#':
            pos = data.find(b'\n', pos)
            if pos < 0:
                break
            continue
        if data[pos:pos + 1].isspace():
            pos += 1
            continue
        end = pos
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[pos:end])
        pos = end
    if len(tokens) < 4 or tokens[0] != b'P5':
        raise MapError('P5 형식의 PGM 이 아님')
    try:
        return int(tokens[1]), int(tokens[2])
    except ValueError as error:
        raise MapError('PGM 크기를 읽지 못함') from error


def load_map(yaml_path):
    """
    map_server 형식 지도(YAML + PGM)를 읽어 (info, pgm 바이트)를 돌려준다.

    info = {'image_width', 'image_height', 'resolution' [m/px], 'origin' [x, y, yaw]}.
    화면이 PGM 을 직접 그리므로 픽셀은 바꾸지 않고 원본 바이트를 그대로 넘긴다.
    """
    try:
        with open(yaml_path, encoding='utf-8') as f:
            meta = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as error:
        raise MapError(f'지도 YAML 을 읽지 못함: {yaml_path}') from error
    if not isinstance(meta, dict) or 'image' not in meta or 'resolution' not in meta:
        raise MapError(f'지도 YAML 에 image·resolution 이 없음: {yaml_path}')
    image_path = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), meta['image'])
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
    except OSError as error:
        raise MapError(f'지도 이미지를 읽지 못함: {image_path}') from error
    width, height = _pgm_size(data)
    origin = [float(v) for v in meta.get('origin', [0.0, 0.0, 0.0])]
    info = {'image_width': width, 'image_height': height,
            'resolution': float(meta['resolution']), 'origin': origin}
    return info, data


DEFAULT_SITE = 'lab'   # 순찰 설정 sites/<site>.yaml 의 기본 현장


class LayerError(Exception):
    """구역·지점 설정 파일을 찾거나 읽지 못함."""


def _ros_params(path):
    """ROS 파라미터 YAML 의 첫 노드 아래 ros__parameters 를 돌려준다."""
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        params = next(iter(data.values()))['ros__parameters']
    except (OSError, yaml.YAMLError, AttributeError, KeyError, StopIteration, TypeError) as error:
        raise LayerError(f'설정을 읽지 못함: {path}') from error
    if not isinstance(params, dict):
        raise LayerError(f'ros__parameters 가 없음: {path}')
    return params


def load_robot_params(points_dir, robot, site=DEFAULT_SITE):
    """
    로봇 한 대의 순찰 설정을 읽는다. 주행 설정 파일은 읽기만 한다.

    <points_dir>/<robot>.yaml 이 있으면 그 파일이 전부다 (합쳐 내보낸 프로필, 예전 구조).
    없고 common.yaml 이 있으면 순찰 launch 와 같은 순서로 공통 → 현장 → 로봇 파일을 합친다.
    같은 키는 뒤 파일이 이긴다. 지점 표는 현장 파일에만 있어서 키 단위로 덮어써도 된다.
    """
    flat = os.path.join(points_dir, f'{robot}.yaml')
    common = os.path.join(points_dir, 'common.yaml')
    if os.path.exists(flat) or not os.path.exists(common):
        return _ros_params(flat)
    params = {}
    for path in (common, os.path.join(points_dir, 'sites', f'{site}.yaml'),
                 os.path.join(points_dir, 'robots', f'{robot}.yaml')):
        params.update(_ros_params(path))
    return params


def _pose(value):
    """[x, y] 또는 [x, y, yaw] → [x, y, yaw] (float)."""
    x, y = float(value[0]), float(value[1])
    return [x, y, float(value[2]) if len(value) > 2 else 0.0]


def _general_points(params):
    """
    일반 지점(P 로 시작)과 숨긴 예비 지점 수.

    (0, 0, 0) 인 P 지점은 미실측 예비값이라 뺀다 (가짜 핑키·지도 뷰어와 같은 규칙).
    홈 I1 도 (0, 0) 이지만 P 가 아니라 해당하지 않는다. P1, P2, .., P10 순서로 정렬한다.
    """
    points = {}
    hidden = 0
    for name, value in (params.get('points') or {}).items():
        name = str(name)
        if not name.startswith('P'):
            continue
        pose = _pose(value)
        if pose == [0.0, 0.0, 0.0]:
            hidden += 1
            continue
        points[name] = pose
    number = (lambda n: int(n[1:]) if n[1:].isdigit() else math.inf)
    return dict(sorted(points.items(), key=lambda item: (number(item[0]), item[0]))), hidden


def load_map_layers(points_dir, zone_params_path, site=DEFAULT_SITE):
    """
    순찰·zone_manager 설정에서 지도에 겹쳐 그릴 구역 지점·출구·대기 슬롯·홈·일반 지점을 만든다.

    주행 설정 파일을 읽기만 한다. 로봇 목록은 zone_params 의 robot_ids, 로봇별 지점은
    load_robot_params 로 읽는다. 구역 좌표는 로봇끼리 같아야 하므로 첫 로봇 값을 쓰고,
    다른 로봇의 값이 다르면 warnings 에 남긴다. 대기 슬롯 k = 앵커 + k * 간격 * 방향
    (zone_manager 와 같은 식). 좌표는 map 좌표계 [m], yaw [rad].
    """
    zone_params = _ros_params(zone_params_path)
    robots = [str(r) for r in zone_params.get('robot_ids') or []]
    spacing = float(zone_params.get('queue_spacing', 0.3))
    queue_max = int(zone_params.get('queue_max', 3))
    warnings = []

    configs = {}
    for robot in robots:
        try:
            configs[robot] = load_robot_params(points_dir, robot, site)
        except LayerError as error:
            warnings.append(str(error))
    if not configs:
        raise LayerError(f'로봇 설정을 하나도 읽지 못함: {points_dir}')

    def zone_poses(params, zone):
        points = params.get('points') or {}
        names = list((params.get('zone_points') or {}).get(zone) or [])
        exit_name = f'Z{zone}_EXIT'
        poses = {n: _pose(points[n]) for n in names if n in points}
        if exit_name in points:
            poses[exit_name] = _pose(points[exit_name])
        return poses

    reference_robot = next(iter(configs))
    reference = configs[reference_robot]
    zones = {}
    for zone in [str(z) for z in zone_params.get('zone_names') or []]:
        poses = zone_poses(reference, zone)
        for robot, params in configs.items():
            if robot != reference_robot and zone_poses(params, zone) != poses:
                warnings.append(f'구역 {zone} 좌표가 {reference_robot} 와 {robot} 에서 다름')
        exit_name = f'Z{zone}_EXIT'
        exit_pose = poses.pop(exit_name, None)
        settings = zone_params.get(f'zone_{zone}') or {}
        anchor = _pose(settings.get('queue_anchor', [0.0, 0.0, 0.0]))
        back = [float(v) for v in settings.get('queue_back_dir', [0.0, -1.0])]
        norm = math.hypot(back[0], back[1]) or 1.0
        queue = [[round(anchor[0] + k * spacing * back[0] / norm, 4),
                  round(anchor[1] + k * spacing * back[1] / norm, 4), anchor[2]]
                 for k in range(queue_max)]
        zones[zone] = {'points': poses,
                       'exit': {'name': exit_name, 'pose': exit_pose} if exit_pose else None,
                       'queue': queue}

    homes = {}
    for robot, params in configs.items():
        name = params.get('home_name')
        points = params.get('points') or {}
        if name in points:
            homes[robot] = {'name': str(name), 'pose': _pose(points[name])}
        else:
            warnings.append(f'{robot} 의 홈 지점이 points 에 없음: {name}')

    points, hidden_points = _general_points(reference)
    for robot, params in configs.items():
        if robot != reference_robot and _general_points(params)[0] != points:
            warnings.append(f'일반 지점 좌표가 {reference_robot} 와 {robot} 에서 다름')

    return {'zones': zones, 'homes': homes, 'points': points,
            'hidden_points': hidden_points, 'warnings': warnings}


class SnapshotStore:
    """fleet_status JSON 의 최신 값과 받은 시각, 순번을 보관한다."""

    def __init__(self, stale_sec, clock=time.monotonic, events_max=500):
        self.stale_sec = float(stale_sec)
        self.clock = clock
        self._cond = threading.Condition()
        self._snapshot = None
        self._received = None
        self._seq = 0
        # 스냅샷의 'events' 는 그 주기에 새로 생긴 것만 담겨 온다. 여기서 번호를 붙여 쌓는다.
        # 메모리에만 두므로 백엔드를 다시 켜면 지워진다.
        self._events = collections.deque(maxlen=int(events_max))
        self._event_id = 0

    def put(self, text):
        """JSON 문자열을 넣는다. dict 가 아니거나 깨진 값이면 False 이고 기존 값을 유지한다."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        new_events = data.get('events')
        if not isinstance(new_events, list):
            new_events = []
        with self._cond:
            numbered = []
            for event in new_events:
                if isinstance(event, dict):
                    self._event_id += 1
                    numbered.append(dict(event, id=self._event_id))
            self._events.extend(numbered)
            # 화면은 id 로 중복을 거른다 (처음엔 /api/events, 그 뒤엔 스냅샷의 events).
            data['events'] = numbered
            self._snapshot = data
            self._received = self.clock()
            self._seq += 1
            self._cond.notify_all()
        return True

    def health(self):
        """원천(fleet_status_node)이 살아 있는지. 받은 적이 없으면 age 는 None."""
        with self._cond:
            if self._received is None:
                return {'source_online': False, 'source_age': None}
            age = self.clock() - self._received
        return {'source_online': age <= self.stale_sec, 'source_age': round(age, 3)}

    def get(self):
        """(순번, 스냅샷 + health) 를 돌려준다. 받은 적이 없으면 (0, None)."""
        with self._cond:
            if self._snapshot is None:
                return 0, None
            seq, snapshot = self._seq, dict(self._snapshot)
        snapshot.update(self.health())
        return seq, snapshot

    def events(self, after=0, robot=None, limit=200):
        """번호가 after 보다 큰 이벤트를 오래된 것부터 최대 limit 개. robot 을 주면 그 로봇만."""
        with self._cond:
            items = [e for e in self._events
                     if e['id'] > after and (robot is None or e.get('robot') == robot)]
        return items[-limit:] if limit > 0 else []

    def wait_newer(self, seq, timeout):
        """순번이 seq 보다 큰 값이 들어올 때까지 최대 timeout 초 기다린다. 새 값이 있으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: self._seq > seq, timeout)


# MJPEG(multipart/x-mixed-replace) 조각 사이의 구분 문자열. 브라우저 <img> 가 이 형식을 바로 그린다.
MJPEG_BOUNDARY = 'frame'


def mjpeg_part(jpeg):
    """JPEG 바이트 하나를 MJPEG 스트림의 한 조각으로 감싼다."""
    head = (f'--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\n'
            f'Content-Length: {len(jpeg)}\r\n\r\n').encode('ascii')
    return head + jpeg + b'\r\n'


class CameraStore:
    """
    로봇별 카메라 마지막 프레임(JPEG 바이트) 1장만 보관한다.

    영상은 풀지 않고 받은 바이트를 그대로 브라우저에 넘긴다. 지난 프레임은 쌓지 않는다
    (보는 사람이 늦으면 중간 프레임을 건너뛰고 최신 것을 받는다).
    """

    def __init__(self, robots, clock=time.monotonic):
        self.clock = clock
        self._cond = threading.Condition()
        self._frames = {robot: None for robot in robots}  # robot → (seq, bytes, 받은 시각)
        self._counts = {robot: 0 for robot in robots}
        self._seq = 0

    def robots(self):
        """구독하도록 설정된 로봇 목록."""
        return list(self._frames)

    def put(self, robot_id, jpeg):
        """프레임을 넣는다. 설정에 없는 로봇이거나 빈 바이트면 False."""
        if robot_id not in self._frames or not jpeg:
            return False
        with self._cond:
            self._seq += 1
            self._frames[robot_id] = (self._seq, bytes(jpeg), self.clock())
            self._counts[robot_id] += 1
            self._cond.notify_all()
        return True

    def latest(self, robot_id):
        """(순번, JPEG 바이트). 받은 적이 없으면 None."""
        with self._cond:
            frame = self._frames.get(robot_id)
        return None if frame is None else frame[:2]

    def wait_newer(self, robot_id, seq, timeout):
        """그 로봇의 프레임 순번이 seq 보다 커질 때까지 최대 timeout 초 기다린다. 새 값이 있으면 True."""
        def newer():
            frame = self._frames.get(robot_id)
            return frame is not None and frame[0] > seq
        with self._cond:
            return self._cond.wait_for(newer, timeout)

    def health(self):
        """로봇별 {age_sec: 마지막 프레임 뒤 지난 시간(받은 적 없으면 None), frames: 받은 수}."""
        now = self.clock()
        with self._cond:
            return {robot: {'age_sec': None if frame is None else round(now - frame[2], 3),
                            'frames': self._counts[robot]}
                    for robot, frame in self._frames.items()}


# 끝난 주문 상태 (cobot_fleet_control scenario_contracts.TERMINAL 과 같게)
ORDER_TERMINAL = {'COMPLETED', 'FAILED'}
# 수동 상차 확인을 받는 주문 단계: 상차장 도착 뒤 PICKUP_EXIT ~ VERIFY_LOAD, 정밀 보정 CORRECT_PICKUP.
# fleet 의 검사(scenario_safety.confirm_loaded)와 같은 조건이다. 화면 표시용이고 최종 검사는 fleet 이 한다.
LOAD_CONFIRM_STAGES = {'PICKUP_EXIT', 'DOCK_PICKUP', 'CORRECT_PICKUP', 'MARKER', 'PICK', 'LOAD',
                       'VERIFY_LOAD'}
# 멈춘 주문(복구가 필요한) 상태와, 이어서 가기를 받는 이동 단계. fleet 의 scenario_contracts.BLOCKED·
# scenario_safety.recover 와 같은 조건이다. 화면 표시용이고 최종 검사는 fleet 이 한다.
ORDER_BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
ORDER_RESUME_STAGES = {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER'}
# 화면에 내는 주문 필드. 원장 사본(input 등)을 그대로 내지 않는다.
ORDER_FIELDS = ('order_id', 'robot_id', 'state', 'stage', 'completed', 'sku', 'route', 'detail')


def load_confirmable(order):
    """이 주문에 화면의 수동 상차 확인 버튼을 보일지."""
    completed = order.get('completed')
    return (order.get('state') in {'RUNNING', 'UNKNOWN'}
            and order.get('stage') in LOAD_CONFIRM_STAGES
            and isinstance(completed, list) and 'MOVE_PICKUP' in completed
            and bool(order.get('robot_id')) and not order.get('failure')
            and not order.get('operator_load_confirmation')
            and not order.get('manual_load_pending'))


def active_orders(orders):
    """주문 목록(fleet 이 낸 것)에서 끝나지 않은 것만 골라 화면용 필드와 load_confirmable 을 붙인다."""
    if not isinstance(orders, list):
        return []
    result = []
    for order in orders:
        if not isinstance(order, dict) or order.get('state') in ORDER_TERMINAL:
            continue
        item = {key: order.get(key) for key in ORDER_FIELDS}
        item['load_confirmed'] = bool(order.get('operator_load_confirmation')
                                      or order.get('manual_load_pending'))
        item['load_confirmable'] = load_confirmable(order)
        item['blocked'] = order.get('state') in ORDER_BLOCKED and bool(order.get('robot_id'))
        item['resumable'] = item['blocked'] and order.get('stage') in ORDER_RESUME_STAGES
        result.append(item)
    return result


class TaskStore:
    """
    작업 노드(fleet_control_node)와 주고받는 값 보관: 작업 목록 캐시, 요청 응답 기다리기, 바뀐 작업 순번.

    ROS 콜백 스레드가 put_*() 로 넣고, 웹 서버 스레드가 request()·tasks()·changes_since() 로 읽는다.
    request() 는 발행 함수를 받아 요청을 낸 뒤, 같은 request_id 의 응답을 timeout 초까지 기다린다.
    """

    # 바뀐 작업을 이만큼만 기억한다. 더 밀린 WebSocket 은 전체 목록을 다시 받는다.
    CHANGE_LOG = 200

    def __init__(self, stale_sec, reply_timeout_sec, clock=time.monotonic):
        self.stale_sec = float(stale_sec)
        self.reply_timeout_sec = float(reply_timeout_sec)
        self.clock = clock
        self._cond = threading.Condition()
        self._tasks = {}
        self._snapshot = None
        self._received = None
        self._replies = {}
        self._waiting = set()
        self._seq = 0
        self._log = []

    def _upsert(self, task):
        """작업 하나를 반영한다. 바뀌었으면 순번을 올린다. lock 안에서 부른다."""
        if not isinstance(task, dict) or 'task_id' not in task:
            return
        if self._tasks.get(task['task_id']) == task:
            return
        self._tasks[task['task_id']] = task
        self._seq += 1
        self._log.append((self._seq, task))
        del self._log[:-self.CHANGE_LOG]
        self._cond.notify_all()

    def put_snapshot(self, text):
        """/control_center/tasks JSON. 깨진 값이면 False."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get('tasks'), list):
            return False
        with self._cond:
            self._snapshot = data
            self._received = self.clock()
            for task in reversed(data['tasks']):
                self._upsert(task)
            # 목록에서 밀려난 오래된 작업은 캐시에서도 뺀다 (진행 중이면 목록에 남아 있다).
            keep = {t.get('task_id') for t in data['tasks']}
            self._tasks = {k: v for k, v in self._tasks.items() if k in keep}
        return True

    def put_event(self, text):
        """/control_center/task_events JSON. 응답이면 기다리는 요청에 넘기고, 작업이면 반영한다."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        with self._cond:
            if data.get('type') == 'reply' and data.get('request_id') in self._waiting:
                self._replies[data['request_id']] = data
                self._cond.notify_all()
            elif data.get('type') == 'task':
                self._upsert(data.get('task'))
        return True

    def online(self):
        """작업 노드(fleet_control_node)가 살아 있는지 (목록을 stale_sec 안에 받았는지)."""
        with self._cond:
            return self._received is not None and self.clock() - self._received <= self.stale_sec

    def health(self):
        with self._cond:
            age = None if self._received is None else round(self.clock() - self._received, 3)
            snapshot = self._snapshot or {}
            spec = snapshot.get('spec')
            raw = bool(snapshot.get('allow_raw_cmd'))
            armed = bool(snapshot.get('armed'))
            holds = snapshot.get('holds')
            orders = snapshot.get('orders')
        online = age is not None and age <= self.stale_sec
        # 수동 명령 칸은 작업 노드가 켜져 있고 allow_raw_cmd 가 켜져 있을 때만 화면에 보인다.
        # commands_armed: 화면 상단 '작업 명령 켜기/끄기'. 꺼져 있으면 작업 명령 버튼이 잠긴다 (정지는 항상).
        # holds: fleet_control 이 보류한 로봇 → 사유 (정지·estop 뒤 현장 확인 복구 전까지 명령 거절).
        # orders: 끝나지 않은 주문 (화면의 수동 상차 확인 버튼용, active_orders).
        # controller_online: 작업 노드(fleet_control_node)가 살아 있는지.
        # cobot_fleet_control 의 도커 smoke_check 도 이 값을 읽는다.
        return {'controller_online': online, 'controller_age': age, 'spec': spec,
                'raw_cmd_enabled': online and raw, 'commands_armed': online and armed,
                'holds': holds if online and isinstance(holds, dict) else {},
                'orders': active_orders(orders) if online else []}

    def request(self, payload, publish):
        """
        요청을 내고 응답을 기다린다. (상태, 본문) 또는 응답이 없으면 None.

        payload 에 request_id 를 붙여 publish(JSON 문자열) 로 낸다. 기다리는 동안 lock 을 놓는다.
        """
        request_id = uuid.uuid4().hex
        with self._cond:
            self._waiting.add(request_id)
        try:
            publish(json.dumps(dict(payload, request_id=request_id), ensure_ascii=False))
            with self._cond:
                if not self._cond.wait_for(lambda: request_id in self._replies,
                                           self.reply_timeout_sec):
                    return None
                reply = self._replies.pop(request_id)
        finally:
            with self._cond:
                self._waiting.discard(request_id)
                self._replies.pop(request_id, None)
        return reply.get('status'), reply.get('body')

    def tasks(self, robot_id=None, state=None, limit=50):
        """최근 작업 (최신순)."""
        with self._cond:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: (t.get('created_at') or 0, t.get('task_id')), reverse=True)
        tasks = [t for t in tasks
                 if (robot_id is None or t.get('robot_id') == robot_id)
                 and (state is None or t.get('state') == state)]
        return tasks[:max(0, int(limit))]

    def task(self, task_id):
        with self._cond:
            return self._tasks.get(task_id)

    def seq(self):
        with self._cond:
            return self._seq

    def changes_since(self, seq):
        """(지금 순번, seq 뒤에 바뀐 작업 목록). 기록이 밀렸으면 목록 대신 None."""
        with self._cond:
            if self._log and self._log[0][0] > seq + 1:
                return self._seq, None
            return self._seq, [task for s, task in self._log if s > seq]

    def wait_newer(self, seq, timeout):
        with self._cond:
            return self._cond.wait_for(lambda: self._seq > seq, timeout)
