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
관제 웨이포인트와 묶음 (ROS 없음, 2026-11-18).

상용 관제처럼 지점 원본을 관제에 둔다. 로봇을 세우고 화면에서 '저장'을 누르면 그 순간의 위치를
이름(기본 W1, W2 …)과 함께 JSON 파일에 남긴다. 이동·경로 명령에 이 이름이 들어가면 관제가 좌표를
봉투의 poses 로 실어 보내고, 순찰 노드는 로봇 설정 파일 없이 그 좌표로 간다 (goto 만).

- 이름은 로봇 설정(P·구역 지점·출구·홈)과 겹치면 안 된다. 같은 이름에 좌표가 둘이 되면 헷갈린다.
- keepout_m > 0 이면 구역 지점·출구에서 그 거리 안은 저장하지 않는다 (구역은 zone 명령·토큰으로만).
  기본 0 = 검사 안 함 (2026-11-18 사용자 결정, 기록이 너무 자주 막혀서).
- 묶음은 이름 붙인 지점 순서다 (로봇 설정 지점과 관제 웨이포인트를 섞음). 경로 띠에서 불러온다.
파일은 임시 파일에 쓴 뒤 바꿔치기해서 쓰는 중에 꺼져도 깨지지 않는다.
"""

import json
import math
import os
import re
import tempfile
import threading
import time

NAME_RE = re.compile(r'[A-Z][A-Z0-9_]{0,15}')
GROUP_NAME_MAX = 40
NOTE_MAX = 200
GROUP_POINTS_MAX = 20     # 경로 지점 최대 개수 (route_utils.ROUTE_POINTS_MAX) 와 같게
WAYPOINTS_MAX = 200
AUTO_PREFIX = 'W'


class WaypointError(ValueError):
    """요청을 처리할 수 없음 (HTTP 상태와 함께)."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def config_poses(layers):
    """로봇 설정 지점 이름 → (x, y) (일반 지점·구역 지점·출구·홈). layers 는 load_map_layers() 결과."""
    found = {}
    if not layers:
        return found
    for name, pose in (layers.get('points') or {}).items():
        found[name] = pose
    for zone in (layers.get('zones') or {}).values():
        for name, pose in (zone.get('points') or {}).items():
            found[name] = pose
        exit_ = zone.get('exit')
        if exit_ and exit_.get('name'):
            found[exit_['name']] = exit_.get('pose')
    for home in (layers.get('homes') or {}).values():
        if home.get('name'):
            found[home['name']] = home.get('pose')
    return found


def zone_poses(layers):
    """구역 지점·출구 이름 → 좌표 (keepout 검사용)."""
    found = {}
    for zone in ((layers or {}).get('zones') or {}).values():
        for name, pose in (zone.get('points') or {}).items():
            found[name] = pose
        exit_ = zone.get('exit')
        if exit_ and exit_.get('name') and exit_.get('pose'):
            found[exit_['name']] = exit_['pose']
    return found


# 지도 픽셀이 이 값보다 어두우면 벽(점유)으로 본다. map_server 기본 occupied_thresh 0.65 (negate 0):
# 점유 확률 = (255 - p) / 255 > 0.65  →  p < 89.
OCCUPIED_BELOW = 89


def pgm_raster(data):
    """P5 PGM 바이트 → (가로, 세로, 픽셀 바이트). 형식이 아니면 None."""
    tokens, pos = [], 0
    while len(tokens) < 4 and pos < len(data):
        if data[pos:pos + 1] == b'#':
            pos = data.find(b'\n', pos)
            if pos < 0:
                return None
            continue
        if data[pos:pos + 1].isspace():
            pos += 1
            continue
        end = pos
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[pos:end])
        pos = end
    if len(tokens) < 4 or tokens[0] != b'P5' or int(tokens[3]) > 255:
        return None
    width, height = int(tokens[1]), int(tokens[2])
    pixels = data[pos + 1:pos + 1 + width * height]   # 헤더 끝 공백 한 개 다음부터
    return (width, height, pixels) if len(pixels) == width * height else None


def wall_distance(map_data, x, y, radius):
    """
    (x, y) [m] 에서 radius [m] 안의 가장 가까운 벽까지 거리 [m]. 없거나 지도가 없으면 None.

    map_data 는 fleet_api_utils.load_map() 결과 (info, pgm 바이트).
    """
    if not map_data or radius <= 0:
        return None
    info, data = map_data
    raster = pgm_raster(data)
    if raster is None:
        return None
    width, height, pixels = raster
    res = float(info['resolution'])
    ox, oy = info['origin'][0], info['origin'][1]
    # 연속 픽셀 좌표 (왼쪽 위 모서리가 0). 픽셀 (r, c) 의 가운데는 (c + 0.5, r + 0.5).
    col = (x - ox) / res
    row = height - (y - oy) / res
    reach = int(math.ceil(radius / res)) + 1
    best = None
    for r in range(max(0, int(row) - reach), min(height, int(row) + reach + 1)):
        for c in range(max(0, int(col) - reach), min(width, int(col) + reach + 1)):
            if pixels[r * width + c] < OCCUPIED_BELOW:
                d = math.hypot(c + 0.5 - col, r + 0.5 - row) * res
                if d <= radius and (best is None or d < best):
                    best = d
    return best


def _text(value, field, limit):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise WaypointError(400, f'{field} 는 {limit}자 이내 글')
    return value.strip()


class WaypointStore:
    """
    웨이포인트·묶음 파일 하나 (사이트별). 웹 서버 스레드에서 부른다 (잠금으로 보호).

    layers 는 load_map_layers() 결과 (없으면 이름 충돌·구역 거리 검사를 하지 않는다).
    """

    def __init__(self, path, site='lab', layers=None, keepout_m=0.0, clock=time.time,
                 map_data=None, wall_warn_m=0.0):
        self.path = os.path.expanduser(path) if path else ''
        self.site = site
        self.keepout_m = float(keepout_m)
        # 벽(지도 점유 픽셀)이 이만큼 [m] 안이면 저장은 하되 주의를 남긴다 (Nav2 가 길을 못 만들 수 있어서).
        self.map_data = map_data
        self.wall_warn_m = float(wall_warn_m)
        self.clock = clock
        self._reserved = config_poses(layers)
        self._zones = zone_poses(layers)
        self._lock = threading.Lock()
        self._waypoints = {}
        self._groups = {}
        self.load_error = ''
        self._load()

    # ---------- 파일 ----------

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            self._waypoints = dict(data.get('waypoints') or {})
            self._groups = dict(data.get('groups') or {})
        except (OSError, ValueError, AttributeError) as error:
            # 깨진 파일을 덮어쓰지 않게 기록만 하고 빈 채로 시작한다 (저장은 막는다).
            self.load_error = f'웨이포인트 파일을 읽지 못함: {error}'

    def _save(self):
        if not self.path:
            return
        if self.load_error:
            raise WaypointError(503, f'{self.load_error} (파일을 고치거나 옮긴 뒤 백엔드를 다시 켜세요)')
        folder = os.path.dirname(self.path) or '.'
        os.makedirs(folder, exist_ok=True)
        data = {'version': 1, 'site': self.site, 'waypoints': self._waypoints,
                'groups': self._groups}
        fd, tmp = tempfile.mkstemp(prefix='.waypoints-', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as error:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise WaypointError(503, f'웨이포인트 파일을 쓰지 못함: {error}') from None

    # ---------- 검사 ----------

    def _check_name(self, name, current=None):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise WaypointError(400, '이름은 대문자로 시작하는 대문자·숫자·_ 16자 이내 (예: W3, DOCK_1)')
        if name in self._reserved:
            raise WaypointError(409, f'{name} 은 로봇 설정에 이미 있는 지점 이름')
        if name != current and name in self._waypoints:
            raise WaypointError(409, f'{name} 은 이미 있는 웨이포인트')

    def near_zone(self, x, y):
        """구역 지점·출구에서 keepout_m 안이면 그 지점 이름, 아니면 '' 를 돌려준다."""
        for name, pose in self._zones.items():
            if pose and math.hypot(pose[0] - x, pose[1] - y) < self.keepout_m:
                return name
        return ''

    def _next_name(self):
        used = set(self._waypoints) | set(self._reserved)
        n = 1
        while f'{AUTO_PREFIX}{n}' in used:
            n += 1
        return f'{AUTO_PREFIX}{n}'

    # ---------- 읽기 ----------

    def snapshot(self):
        with self._lock:
            waypoints = [dict(v, name=k) for k, v in self._waypoints.items()]
            groups = [dict(v, name=k) for k, v in self._groups.items()]
        waypoints.sort(key=lambda w: w.get('captured_at') or 0)
        groups.sort(key=lambda g: g['name'])
        return {'waypoints': waypoints, 'groups': groups, 'keepout_m': self.keepout_m,
                'load_error': self.load_error}

    def poses(self):
        """이름 → [x, y, yaw] (명령 봉투·경로 나누기용)."""
        with self._lock:
            return {k: [v['x'], v['y'], v['yaw']] for k, v in self._waypoints.items()}

    def poses_for(self, names):
        """주어진 이름 가운데 관제 웨이포인트만 {이름: [x, y, yaw]} 로 돌려준다."""
        poses = self.poses()
        return {n: poses[n] for n in names if n in poses}

    # ---------- 쓰기 ----------

    def capture(self, robot_id, robot, name=None, note=None):
        """
        로봇의 지금 위치(fleet_status 스냅샷의 pose)로 저장한다. 저장한 웨이포인트를 돌려준다.

        위치가 없거나 연결이 끊겼으면 409. teach.warnings(이동 중·불확실성 큼)는 같이 남긴다.
        """
        if not isinstance(robot, dict):
            raise WaypointError(404, f'등록되지 않은 로봇: {robot_id}')
        pose = robot.get('pose')
        if not robot.get('online') or not isinstance(pose, dict):
            raise WaypointError(409, f'{robot_id} 위치를 모름 (연결·위치 수신 확인)')
        try:
            x, y, yaw = float(pose['x']), float(pose['y']), float(pose.get('yaw') or 0.0)
        except (KeyError, TypeError, ValueError):
            raise WaypointError(409, f'{robot_id} 위치 값이 이상함') from None
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            raise WaypointError(409, f'{robot_id} 위치 값이 이상함')
        note = _text(note, 'note', NOTE_MAX)
        with self._lock:
            if len(self._waypoints) >= WAYPOINTS_MAX:
                raise WaypointError(409, f'웨이포인트는 {WAYPOINTS_MAX}개까지')
            name = name.strip().upper() if isinstance(name, str) and name.strip() else (
                self._next_name())
            self._check_name(name)
            near = self.near_zone(x, y)
            if near:
                raise WaypointError(409, f'구역 지점 {near} 에서 {self.keepout_m:g} m 안이라 저장하지 않음 '
                                         '(구역은 구역 명령으로만 들어감)')
            teach = robot.get('teach') if isinstance(robot.get('teach'), dict) else {}
            warnings = list(teach.get('warnings') or [])
            wall = wall_distance(self.map_data, x, y, self.wall_warn_m)
            if wall is not None:
                warnings.append(f'벽에 가까움 ({wall * 100:.0f} cm, 가지 못할 수 있음)')
            item = {'x': round(x, 4), 'y': round(y, 4), 'yaw': round(yaw, 4),
                    'robot_id': robot_id, 'captured_at': self.clock(),
                    'warnings': warnings, 'note': note}
            self._waypoints[name] = item
            try:
                self._save()
            except WaypointError:
                del self._waypoints[name]
                raise
        return dict(item, name=name)

    def update(self, name, new_name=None, note=None):
        """이름 바꾸기(묶음 안 이름도 바꿈)·메모."""
        with self._lock:
            if name not in self._waypoints:
                raise WaypointError(404, f'없는 웨이포인트: {name}')
            before = (dict(self._waypoints), {k: dict(v) for k, v in self._groups.items()})
            item = dict(self._waypoints[name])
            if note is not None:
                item['note'] = _text(note, 'note', NOTE_MAX)
            target = name
            if isinstance(new_name, str) and new_name.strip().upper() != name:
                target = new_name.strip().upper()
                self._check_name(target, current=name)
                del self._waypoints[name]
                for group in self._groups.values():
                    group['points'] = [target if p == name else p for p in group['points']]
            self._waypoints[target] = item
            try:
                self._save()
            except WaypointError:
                self._waypoints, self._groups = before
                raise
        return dict(item, name=target)

    def delete(self, name):
        """지운다. 이 이름을 쓰던 묶음에서도 빼고, 바뀐 묶음 이름을 돌려준다."""
        with self._lock:
            if name not in self._waypoints:
                raise WaypointError(404, f'없는 웨이포인트: {name}')
            before = (dict(self._waypoints), {k: dict(v) for k, v in self._groups.items()})
            del self._waypoints[name]
            changed = []
            for group_name, group in self._groups.items():
                if name in group['points']:
                    group['points'] = [p for p in group['points'] if p != name]
                    changed.append(group_name)
            try:
                self._save()
            except WaypointError:
                self._waypoints, self._groups = before
                raise
        return {'deleted': name, 'groups_changed': sorted(changed)}

    def set_group(self, name, points, note=None):
        """묶음을 만들거나 바꾼다. 지점은 로봇 설정 지점 또는 관제 웨이포인트."""
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > GROUP_NAME_MAX:
            raise WaypointError(400, f'묶음 이름은 {GROUP_NAME_MAX}자 이내')
        name = name.strip()
        if (not isinstance(points, list) or not points or len(points) > GROUP_POINTS_MAX
                or any(not isinstance(p, str) for p in points)):
            raise WaypointError(400, f'지점은 1~{GROUP_POINTS_MAX}개의 이름 목록')
        points = [p.strip().upper() for p in points if p.strip()]
        note = _text(note, 'note', NOTE_MAX)
        with self._lock:
            unknown = [p for p in points if p not in self._reserved and p not in self._waypoints]
            if unknown:
                raise WaypointError(400, f'모르는 지점: {", ".join(unknown)}')
            before = dict(self._groups)
            self._groups[name] = {'points': points, 'note': note, 'updated_at': self.clock()}
            try:
                self._save()
            except WaypointError:
                self._groups = before
                raise
        return dict(self._groups[name], name=name)

    def delete_group(self, name):
        with self._lock:
            if name not in self._groups:
                raise WaypointError(404, f'없는 묶음: {name}')
            before = dict(self._groups)
            del self._groups[name]
            try:
                self._save()
            except WaypointError:
                self._groups = before
                raise
        return {'deleted': name}

    def export_yaml(self, names=None):
        """로봇 설정 points 에 붙일 수 있는 줄들 (예: '  W1: [0.123, -0.456, 1.57]')."""
        with self._lock:
            items = sorted(self._waypoints.items(), key=lambda kv: kv[1].get('captured_at') or 0)
        if names:
            items = [kv for kv in items if kv[0] in set(names)]
        lines = [f'# 관제 웨이포인트 ({self.site}). 로봇 설정 points: 아래에 붙인다.']
        lines += [f"  {name}: [{w['x']:.3f}, {w['y']:.3f}, {w['yaw']:.2f}]" for name, w in items]
        return '\n'.join(lines) + '\n'
