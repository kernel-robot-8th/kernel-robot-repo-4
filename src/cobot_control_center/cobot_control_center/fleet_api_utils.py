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


def parse_initial_pose(pose, map_info=None):
    """
    화면에서 찍은 초기위치 pose {x, y, yaw} 를 검사해 float dict 로 돌려준다.

    잘못되면 사유를 담은 ValueError. map_info 가 있으면 지도 범위 안인지도 본다
    (지도 밖으로 AMCL 을 잡으면 위치를 잃는다). 작업 노드도 숫자 검사를 다시 하지만,
    지도는 이 백엔드만 가지고 있어 범위는 여기서 본다.
    """
    try:
        if not isinstance(pose, dict):
            raise TypeError
        x, y, yaw = (float(pose[key]) for key in ('x', 'y', 'yaw'))
    except (KeyError, TypeError, ValueError):
        raise ValueError('pose 는 {x, y, yaw} 숫자여야 합니다') from None
    if not all(math.isfinite(v) for v in (x, y, yaw)):
        raise ValueError('pose 는 유한한 수여야 합니다')
    if map_info is not None:
        ox, oy = map_info['origin'][:2]
        res = map_info['resolution']
        width = map_info['image_width'] * res
        height = map_info['image_height'] * res
        if not (ox <= x <= ox + width and oy <= y <= oy + height):
            raise ValueError(f'지도 밖 좌표 ({x:.2f}, {y:.2f}) m')
    return {'x': x, 'y': y, 'yaw': yaw}


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


def json_object(text):
    """JSON 문자열 → dict. 깨졌거나 dict 가 아니면 None (토픽으로 받은 값 검사용)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class EventLog:
    """
    번호를 붙인 이벤트 기록 (최근 maxlen 개, 메모리에만). 핑키 이벤트와 팔 기록이 같이 쓴다.

    who 는 대상 필드 이름 ('robot' / 'arm'). 잠금은 하지 않으므로 쓰는 저장소의 lock 안에서 부른다.
    """

    def __init__(self, maxlen, who):
        self._items = collections.deque(maxlen=int(maxlen))
        self._last_id = 0
        self.who = who

    def add(self, event):
        """이벤트 하나에 다음 번호를 붙여 쌓고, 번호가 붙은 dict 를 돌려준다."""
        self._last_id += 1
        numbered = dict(event, id=self._last_id)
        self._items.append(numbered)
        return numbered

    def since(self, after=0, who=None, limit=200):
        """번호가 after 보다 큰 것을 오래된 것부터 최대 limit 개. who 를 주면 그 대상만."""
        items = [e for e in self._items
                 if e['id'] > after and (who is None or e.get(self.who) == who)]
        return items[-limit:] if limit > 0 else []


class ReplyWaiter:
    """
    요청에 request_id 를 붙여 내고, 같은 번호의 응답({type: reply})을 timeout 초까지 기다린다.

    작업 노드(TaskStore)와 로봇팔 명령 노드(ArmStore)가 같이 쓴다. ROS 콜백 스레드가 offer() 로
    응답을 넣고, 웹 서버 스레드가 request() 로 기다린다. 기다리는 동안 lock 을 놓는다.
    """

    def __init__(self, timeout_sec):
        self.timeout_sec = float(timeout_sec)
        self._cond = threading.Condition()
        self._replies = {}
        self._waiting = set()

    def offer(self, data):
        """기다리는 요청의 응답이면 넘기고 True. 아니면 False (다른 종류이거나 이미 늦은 응답)."""
        if data.get('type') != 'reply':
            return False
        with self._cond:
            if data.get('request_id') not in self._waiting:
                return False
            self._replies[data['request_id']] = data
            self._cond.notify_all()
        return True

    def request(self, payload, publish):
        """요청을 내고 응답을 기다린다. (상태, 본문) 또는 응답이 없으면 None."""
        request_id = uuid.uuid4().hex
        with self._cond:
            self._waiting.add(request_id)
        try:
            publish(json.dumps(dict(payload, request_id=request_id), ensure_ascii=False))
            with self._cond:
                if not self._cond.wait_for(lambda: request_id in self._replies,
                                           self.timeout_sec):
                    return None
                reply = self._replies.pop(request_id)
        finally:
            with self._cond:
                self._waiting.discard(request_id)
                self._replies.pop(request_id, None)
        return reply.get('status'), reply.get('body')


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
        self._events = EventLog(events_max, 'robot')
        # 백엔드가 직접 만든 이벤트 (네트워크 경고 생김·풀림). 다음 스냅샷과 함께 WebSocket 으로 나간다.
        self._pending = []

    def add_events(self, events):
        """fleet_status 가 아닌 곳의 이벤트를 넣는다. 번호를 바로 붙여 /api/events 에도 바로 보인다."""
        with self._cond:
            for event in events:
                if isinstance(event, dict):
                    self._pending.append(self._events.add(event))

    def put(self, text):
        """JSON 문자열을 넣는다. dict 가 아니거나 깨진 값이면 False 이고 기존 값을 유지한다."""
        data = json_object(text)
        if data is None:
            return False
        new_events = data.get('events')
        if not isinstance(new_events, list):
            new_events = []
        with self._cond:
            # 직접 넣은 이벤트는 이미 번호가 있고 _events 에도 있다. 스냅샷에만 같이 싣는다.
            numbered, self._pending = self._pending, []
            numbered += [self._events.add(e) for e in new_events if isinstance(e, dict)]
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
            return self._events.since(after, robot, limit)

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
# RESUME_STAGES 를 복사한 값이다 (패키지끼리 import 하지 않음). 화면 표시용이고 최종 검사는 fleet 이 한다.
ORDER_BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
ORDER_RESUME_STAGES = {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER',
                       'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'MOVE_RESTOCK'}
# 팔 단계에서 멈춘 주문: '다시'(팔 퇴피·물건 제자리 확인) 와 '사람이 처리함'(하차·정리·반환만).
# fleet 의 scenario_contracts.ARM_STAGES·HAND_DONE 키를 복사한 값이다. 상차는 수동 상차 확인을 쓴다.
ORDER_ARM_RETRY_STAGES = {'PICK', 'LOAD', 'PICK_DROPOFF', 'UNLOAD', 'ARRANGE', 'RESTOCK'}
ORDER_HAND_DONE_STAGES = {'PICK_DROPOFF', 'UNLOAD', 'ARRANGE', 'RESTOCK'}
# 직원 취소(자동 반납)를 받는 단계. fleet 의 scenario_contracts.CANCEL_STAGES 를 복사한 값이다.
ORDER_CANCEL_STAGES = LOAD_CONFIRM_STAGES | {'MOVE_PICKUP', 'LEAVE_PICKUP', 'MOVE_CUSTOMER',
                                             'CUSTOMER'}
# 화면에 내는 주문 필드. 원장 사본(input 등)을 그대로 내지 않는다.
ORDER_FIELDS = ('order_id', 'robot_id', 'state', 'stage', 'completed', 'sku', 'route', 'detail')


def _order_failure(order):
    failure = order.get('failure') or order.get('detail')
    return f': {failure}' if failure else ''


def order_events(prev_orders, orders, now):
    """
    주문 목록(fleet 이 1초마다 내는 tasks 스냅샷의 orders)을 직전 것과 비교해 이벤트 목록을 만든다.

    이벤트는 fleet_status 이벤트와 같은 모양 {'time', 'robot', 'kind': 'order', 'level', 'text', 'data'}.
    prev_orders 가 None 이면(백엔드를 막 켬) 끝나지 않은 주문만 '진행 중' 한 줄씩 남긴다.
    """
    if not isinstance(orders, list):
        return []
    events = []
    before = {} if prev_orders is None else {
        o.get('order_id'): o for o in prev_orders if isinstance(o, dict)}

    def add(order, level, text):
        events.append({'time': now, 'robot': order.get('robot_id') or None, 'kind': 'order',
                       'level': level, 'text': f'주문 {order.get("order_id")} {text}',
                       'data': {key: order.get(key) for key in ORDER_FIELDS}})

    for order in orders:
        if not isinstance(order, dict) or not order.get('order_id'):
            continue
        state, stage = order.get('state'), order.get('stage')
        if prev_orders is None:
            if state not in ORDER_TERMINAL:
                add(order, 'info', f'진행 중 {state} {stage}')
            continue
        old = before.get(order['order_id'])
        if old is None:
            if state not in ORDER_TERMINAL:
                add(order, 'info',
                    f'접수 ({order.get("sku") or "-"}, 루트 {order.get("route") or "-"})')
            continue
        if state != old.get('state'):
            if state == 'COMPLETED':
                add(order, 'info', '완료')
            elif state == 'FAILED' or state in ORDER_BLOCKED:
                add(order, 'bad', f'{old.get("state")} → {state} ({stage}){_order_failure(order)}')
            else:
                add(order, 'info', f'{old.get("state")} → {state} ({stage})')
        elif stage != old.get('stage') and state not in ORDER_TERMINAL:
            add(order, 'info', f'{old.get("stage") or "-"} → {stage}')
        # fleet 은 실패 사유를 먼저 적고 HOME 복귀까지 마친 뒤 FAILED 로 끝낸다. 사유가 생긴 순간을 남긴다.
        if order.get('failure') and not old.get('failure') and state not in ORDER_TERMINAL:
            add(order, 'bad', f'실패 사유 생김 ({stage}): {order["failure"]}')
        if order.get('robot_id') and order.get('robot_id') != old.get('robot_id'):
            add(order, 'info', f'로봇 배정 {order["robot_id"]}')
    return events


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
        item['retryable'] = item['blocked'] and order.get('stage') in ORDER_ARM_RETRY_STAGES
        item['hand_done'] = item['blocked'] and order.get('stage') in ORDER_HAND_DONE_STAGES
        result.append(item)
    return result


# ---------- 서비스 화면 (/api/service, 매장 직원용) ----------

# 서비스 화면의 큰 단계. 단계 번호는 이 순서의 위치다 (0 접수 ... 5 복귀).
SERVICE_STEPS = ('접수', '상품 준비', '이동', '고객 응대', '회수·정리', '복귀')
# fleet 주문 단계(cobot_fleet_control scenario_tree.STAGES·CUSTOMER_STAGES) → (큰 단계 번호, 직원용 설명).
# 패키지끼리 import 하지 않으므로 이름만 복사한다. 모르는 단계는 코드 그대로 보인다.
SERVICE_STAGE = {
    'MOVE_PICKUP': (1, '상차장으로 이동 중'),
    'PICKUP_EXIT': (1, '상차장 도착 확인'), 'DOCK_PICKUP': (1, '상차장 자리 맞추는 중'),
    'CORRECT_PICKUP': (1, '상차장 자리 맞추는 중'), 'MARKER': (1, '상품 확인 중'),
    'PICK': (1, '로봇팔이 상품 꺼내는 중'), 'LOAD': (1, '로봇에 싣는 중'),
    'VERIFY_LOAD': (1, '실은 상품 확인 중'), 'LEAVE_PICKUP': (1, '상차장 나가는 중'),
    'MOVE_CUSTOMER': (2, '고객 자리로 이동 중'), 'MOVE_DROPOFF': (2, '하차장으로 이동 중'),
    'PATH_EXIT': (3, '하차장 도착 확인'), 'DOCK_DROPOFF': (3, '하차장 자리 맞추는 중'),
    'CORRECT_DROPOFF': (3, '하차장 자리 맞추는 중'), 'QR': (3, '하차 상품 확인 중'),
    'PICK_DROPOFF': (3, '로봇팔이 상품 내리는 중'), 'UNLOAD': (3, '내려놓는 중'),
    'VERIFY_UNLOAD': (3, '내려놓은 상품 확인 중'), 'LEAVE_DROPOFF': (3, '하차장 나가는 중'),
    'CUSTOMER': (3, '고객이 고르는 중 (구매/회수)'),
    'MOVE_ARRANGE': (4, '정리 구역으로 이동 중'), 'ARRANGE': (4, '로봇팔이 신발 정리 중'),
    'LEAVE_ARRANGE': (4, '정리 구역 나가는 중'), 'MOVE_RESTOCK': (4, '선반 구역으로 이동 중'),
    'RESTOCK': (4, '로봇팔이 선반에 되돌리는 중'), 'LEAVE_RESTOCK': (4, '선반 구역 나가는 중'),
    'RETURN_HOME': (5, '대기 자리로 돌아가는 중'), 'RETURN_EXIT': (5, '대기 자리 도착 확인'),
}
# 끝난 주문 결과 → (결과 코드, 직원용 글). 위에서부터 먼저 맞는 것.
SERVICE_OUTCOMES = (
    ('customer_received', 'sold', '구매 완료'),
    ('customer_timed_out', 'timeout', '고객 응답 없음 (시간 초과)'),
    ('customer_declined', 'declined', '구매 안 함 (회수)'),
)


def service_order(order):
    """
    주문 원장 사본 하나를 서비스 화면용으로 줄인다.

    step 은 SERVICE_STEPS 위치, step_text 는 지금 하는 일, outcome 은 끝난 주문의 결과 코드
    (sold·timeout·declined·done·cancelled·failed, 진행 중이면 None)다. 조치 표시(blocked·resumable·
    load_confirmable)는 active_orders 와 같은 조건이고 최종 검사는 fleet 이 한다.
    """
    state, stage = order.get('state'), order.get('stage')
    item = {key: order.get(key) for key in ORDER_FIELDS}
    item.update({key: order.get(key) for key in (
        'destination', 'failure', 'created_at', 'updated_at')})
    item['returning'] = bool(order.get('customer_declined') or order.get('customer_timed_out'))
    unassigned = not order.get('robot_id')
    if state == 'WAITING' and unassigned:
        item['step'], item['step_text'] = 0, '로봇 배정 기다리는 중'
    elif state in ORDER_BLOCKED and unassigned:
        # fleet 은 재시작 때 대기 주문을 UNKNOWN 으로 바꾼다. 로봇이 없으니 단계(MOVE_PICKUP)는 뜻이 없다.
        item['step'], item['step_text'] = 0, '관제 재시작으로 멈춤 · 로봇 배정 전'
    else:
        item['step'], item['step_text'] = SERVICE_STAGE.get(stage, (None, stage or ''))
    item['cancel_requested'] = bool(order.get('cancel_requested'))
    if item['cancel_requested']:
        item['step_text'] = '취소 · ' + (
            '홈 복귀' if order.get('operator_cancelled') else '반납 중') + f" · {item['step_text']}"
        if order.get('operator_cancelled'):
            item['failure'] = None  # 집기 전 취소는 안전 복귀 길을 빌려 쓸 뿐 고장이 아니다
    item['outcome'] = item['outcome_text'] = None
    if state == 'FAILED' and order.get('operator_cancelled'):
        item['outcome'] = 'cancelled'
        item['outcome_text'] = '직원 취소' if item['cancel_requested'] else '접수 취소'
    elif state == 'FAILED' and order.get('operator_restocked'):
        item['outcome'], item['outcome_text'] = 'cancelled', '직원 취소 (직접 반납)'
    elif state == 'FAILED':
        item['outcome'], item['outcome_text'] = 'failed', '처리 못 함'
    elif state in ORDER_TERMINAL:
        item['outcome'], item['outcome_text'] = 'done', '완료'
        if item['cancel_requested']:
            item['outcome'], item['outcome_text'] = 'cancelled', '직원 취소 (선반 반납)'
        for key, code, text in SERVICE_OUTCOMES:
            if order.get(key) and not item['cancel_requested']:
                item['outcome'], item['outcome_text'] = code, text
                break
    if state in ORDER_TERMINAL:
        item['step'] = len(SERVICE_STEPS) - 1
    item['load_confirmed'] = bool(order.get('operator_load_confirmation')
                                  or order.get('manual_load_pending'))
    item['load_confirmable'] = state not in ORDER_TERMINAL and load_confirmable(order)
    item['blocked'] = state in ORDER_BLOCKED and bool(order.get('robot_id'))
    item['resumable'] = item['blocked'] and stage in ORDER_RESUME_STAGES
    item['retryable'] = item['blocked'] and stage in ORDER_ARM_RETRY_STAGES
    item['hand_done'] = item['blocked'] and stage in ORDER_HAND_DONE_STAGES
    item['purchased'] = bool(order.get('customer_received'))
    # 직접 처리로 취소할 때 '선반에 돌려놓았다' 칸을 보일지. 집기 전 취소는 재고가 저절로 돌아온다.
    item['shelf_returnable'] = (
        item['blocked'] and not item['purchased'] and not order.get('operator_cancelled')
        and bool(order.get('destination')) and order.get('kind', 'delivery') == 'delivery')
    # 진행 중 취소(자동 반납). 표시 조건이고 최종 검사는 fleet(scenario_safety.request_cancel)이 한다.
    item['returnable'] = (
        state == 'RUNNING' and not unassigned and stage in ORDER_CANCEL_STAGES
        and bool(order.get('destination')) and order.get('kind', 'delivery') == 'delivery'
        and not any(order.get(key) for key in (
            'cancel_requested', 'failure', 'customer_received', 'customer_declined',
            'customer_timed_out')))
    # 로봇 배정 전(접수) 취소. fleet 의 검사(scenario_safety.recover)와 같은 조건이다.
    item['cancelable'] = unassigned and state in ORDER_BLOCKED | {'WAITING'}
    return item


def service_orders(orders, finished_limit):
    """진행 중 주문 전부(오래된 것부터)와 끝난 주문 최근 finished_limit 건(최신부터)."""
    if not isinstance(orders, list):
        return [], []
    items = [service_order(o) for o in orders if isinstance(o, dict) and o.get('order_id')]
    active = [o for o in items if o['outcome'] is None]
    finished = [o for o in items if o['outcome'] is not None]
    active.sort(key=lambda o: o.get('created_at') or 0)
    finished.sort(key=lambda o: o.get('updated_at') or 0, reverse=True)
    return active, finished[:max(0, int(finished_limit))]


def service_summary(orders, since):
    """
    관리화면 위 숫자 타일: since [s] 뒤에 접수한 주문 건수.

    total 접수, active 진행 중, sold 구매 완료, returned 구매 안 함(시간 초과 포함),
    failed 처리 못 함, cancelled 접수·직원 취소, done 고객 결정 없이 끝난 주문.
    """
    counts = {'total': 0, 'active': 0, 'sold': 0, 'returned': 0, 'failed': 0, 'cancelled': 0,
              'done': 0}
    if not isinstance(orders, list):
        return counts
    key = {None: 'active', 'sold': 'sold', 'declined': 'returned', 'timeout': 'returned',
           'failed': 'failed', 'cancelled': 'cancelled', 'done': 'done'}
    for order in orders:
        if not isinstance(order, dict) or not order.get('order_id'):
            continue
        created = order.get('created_at')
        if not isinstance(created, (int, float)) or created < since:
            continue
        counts['total'] += 1
        counts[key[service_order(order)['outcome']]] += 1
    return counts


class TaskStore:
    """
    작업 노드(fleet_control_node)와 주고받는 값 보관: 작업 목록 캐시, 요청 응답 기다리기, 바뀐 작업 순번.

    ROS 콜백 스레드가 put_*() 로 넣고, 웹 서버 스레드가 request()·tasks()·changes_since() 로 읽는다.
    request() 는 발행 함수를 받아 요청을 낸 뒤, 같은 request_id 의 응답을 timeout 초까지 기다린다 (ReplyWaiter).
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
        self._replies = ReplyWaiter(reply_timeout_sec)
        self._seq = 0
        self._log = []
        self._order_events = []

    def take_events(self):
        """put_snapshot 이 쌓은 주문 이벤트를 꺼낸다 (꺼낸 것은 비운다)."""
        with self._cond:
            events, self._order_events = self._order_events, []
        return events

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

    def put_snapshot(self, text, now=None):
        """
        /control_center/tasks JSON. 깨진 값이면 False.

        직전 주문 목록과 비교한 주문 이벤트(order_events)를 쌓아 두고, take_events() 로 꺼낸다.
        now 는 이벤트 시각 [s] (벽시계). 시험에서 넣으려고 인자로 둔다.
        """
        data = json_object(text)
        if data is None or not isinstance(data.get('tasks'), list):
            return False
        with self._cond:
            prev = self._snapshot.get('orders') if self._snapshot is not None else None
            self._order_events += order_events(prev, data.get('orders'),
                                               time.time() if now is None else now)
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
        data = json_object(text)
        if data is None:
            return False
        if not self._replies.offer(data) and data.get('type') == 'task':
            with self._cond:
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

    def service(self, finished_limit, today_start=0.0):
        """
        서비스 화면 값: 주문(진행 중 전부, 끝난 것 최근 finished_limit 건)·재고·자리·오늘 건수.

        today_start 는 오늘 0시 [s] (벽시계). 그 뒤 접수한 주문을 today 에 센다.

        작업 노드가 끊겨도 마지막 값을 보여 주고 controller_online 으로 알린다 (재고·끝난 주문은
        끊긴 동안에도 볼 만하다). 아직 한 번도 못 받았으면 빈 목록이다.
        """
        with self._cond:
            age = None if self._received is None else round(self.clock() - self._received, 3)
            snapshot = self._snapshot or {}
        active, finished = service_orders(snapshot.get('orders'), finished_limit)
        stock = snapshot.get('stock')
        destinations = snapshot.get('destinations')
        holds = snapshot.get('holds')
        online = age is not None and age <= self.stale_sec
        return {'controller_online': online, 'controller_age': age,
                'commands_armed': online and bool(snapshot.get('armed')),
                'holds': holds if online and isinstance(holds, dict) else {},
                'active': active, 'finished': finished,
                'today': service_summary(snapshot.get('orders'), today_start),
                'stock': stock if isinstance(stock, list) else [],
                'destinations': destinations if isinstance(destinations, dict) else {},
                'steps': list(SERVICE_STEPS)}

    def request(self, payload, publish):
        """요청을 내고 응답을 기다린다. (상태, 본문) 또는 응답이 없으면 None."""
        return self._replies.request(payload, publish)

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


class ArmStore:
    """
    로봇팔 명령 노드(arm_command_node)와 주고받는 값 보관: 팔 상태 모음, 요청 응답 기다리기.

    ROS 콜백 스레드가 put_*() 로 넣고, 웹 서버 스레드가 snapshot()·request()·events() 로 읽는다.
    응답 기다리기는 TaskStore 와 같다 (ReplyWaiter). 팔 끄기(RESET) 응답은 팔이 쉬는 자세를 확인한 뒤에 와서
    수 초 걸리므로 reply_timeout_sec 는 작업 노드보다 길다.
    """

    def __init__(self, stale_sec, reply_timeout_sec, clock=time.monotonic, events_max=300):
        self.stale_sec = float(stale_sec)
        self.reply_timeout_sec = float(reply_timeout_sec)
        self.clock = clock
        self._cond = threading.Condition()
        self._snapshot = None
        self._received = None
        self._replies = ReplyWaiter(reply_timeout_sec)
        # 알람 기록: 번호를 붙여 메모리에만 둔다 (SnapshotStore 이벤트와 같은 방식, 번호 체계는 따로)
        self._events = EventLog(events_max, 'arm')

    def put_snapshot(self, text):
        """/control_center/arms JSON. 깨진 값이면 False."""
        data = json_object(text)
        if data is None or not isinstance(data.get('arms'), list):
            return False
        with self._cond:
            self._snapshot = data
            self._received = self.clock()
        return True

    def put_event(self, text):
        """/control_center/arm_events JSON. 기다리는 요청의 응답이면 넘기고, 알람 기록이면 쌓는다."""
        data = json_object(text)
        if data is None:
            return False
        if not self._replies.offer(data) and data.get('type') == 'event' \
                and isinstance(data.get('event'), dict):
            with self._cond:
                self._events.add(data['event'])
        return True

    def events(self, after=0, arm=None, limit=100):
        """번호가 after 보다 큰 알람 기록을 오래된 것부터 최대 limit 개. arm 을 주면 그 팔만."""
        with self._cond:
            return self._events.since(after, arm, limit)

    def _age(self):
        return None if self._received is None else self.clock() - self._received

    def online(self):
        """로봇팔 명령 노드가 살아 있는지 (상태 모음을 stale_sec 안에 받았는지)."""
        with self._cond:
            age = self._age()
        return age is not None and age <= self.stale_sec

    def snapshot(self):
        """화면용: 명령 노드가 꺼져 있으면 팔마다 online 을 false 로 바꿔 STALE 로 보인다."""
        with self._cond:
            age = self._age()
            data = self._snapshot or {}
        online = age is not None and age <= self.stale_sec
        arms = [a if online else dict(a, online=False, state='STALE',
                                      allowed=['hold', 'soft_latch'])
                for a in data.get('arms', []) if isinstance(a, dict)]
        return {'controller_online': online,
                'controller_age': None if age is None else round(age, 3),
                'ttl_ms': data.get('ttl_ms'), 'work_actions': data.get('work_actions') or [],
                'arms': arms}

    def request(self, payload, publish):
        """요청을 내고 응답을 기다린다. (상태, 본문) 또는 응답이 없으면 None."""
        return self._replies.request(payload, publish)
