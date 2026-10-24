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
맵 계약 도구: 맵 읽기, map_hash 계산, 맵 린트.

ROS 없이 돈다 (표준 라이브러리와 PyYAML 만 쓴다). 노드 로직은 아직 없다 (로드맵 S2).
로봇 토픽을 발행하지 않는다. 정의와 절차는 docs/fms_map_contract.md 에 있다.

- map_hash = sha256( sha256(PGM 바이트) ‖ sha256(LF 정규화한 맵 YAML 바이트) ).
  ‖ 는 32바이트 다이제스트 두 개를 이어 붙인 것이다. 결과는 소문자 16진수 64자다.
- 맵 린트: 웨이포인트 자세마다 반경 r 원 안에 중심이 있는 셀이 모두 자유인지 본다.
  점유·미지·맵 밖 셀이 하나라도 있으면 실패다.

명령 두 개를 준다. 종료 코드는 0 = 통과, 1 = 린트 실패, 2 = 파일을 찾거나 읽지 못함.
  map_hash  map_hash 를 표준 출력에 한 줄로 쓴다.
  map_lint  매니페스트, 웨이포인트 대조, 반경 원 검사를 한다.

ROS 환경(ROS 를 source 한 셸)에서는 cobot_bringup 의 install 맵만 쓴다. install 이 없으면
소스 트리로 떨어지지 않고 종료 코드 2 로 멈춘다 (--allow-source 를 주면 경고와 함께 소스 트리).
"""

import argparse
import hashlib
import importlib
import logging
import math
import os
import re
import sys

import yaml

LOGGER = logging.getLogger(__name__)

# 맵 정본 위치. FMS 와 핑키 가드는 cobot_bringup 의 install 결과(share)에서 읽는다.
BRINGUP_PACKAGE = 'cobot_bringup'
MAPS_SUBDIR = os.path.join('config', 'maps')
MAPS_RELPATH = os.path.join('src', BRINGUP_PACKAGE, MAPS_SUBDIR)
POSES_FILENAME = 'approach_poses.yaml'
POSES_SCHEMA_VERSION = 1

APPROACH_POSE = 'approach_pose'
WORK_POSE = 'work_pose'
POSE_KINDS = (APPROACH_POSE, WORK_POSE)
POSE_STATUSES = ('draft', 'confirmed')
ARM_ID = 'arm_id'
WAYPOINT_KEYS = (WORK_POSE, APPROACH_POSE)
WAYPOINT_OPTIONAL_KEYS = (ARM_ID, 'note')
# arm_id 는 토픽 이름(/manipulation/<arm_id>/...)에 들어가므로 ROS 이름 글자 규칙만 본다.
# 팀이 쓰는 값(omx_1~omx_3)은 인터페이스 계약이 정한다.
ARM_ID_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]*')
MAP_BLOCK_KEYS = ('yaml', 'pgm_sha256', 'yaml_lf_sha256', 'map_hash')
MAP_BLOCK_OPTIONAL_KEYS = ('source_repo', 'source_branch', 'source_commit', 'source_path')
POSES_TOP_KEYS = ('schema_version', 'status', 'map', 'clearance_radius_m', 'waypoints')

# nav2 map_server 의 맵 YAML 키. mode 가 없으면 nav2 처럼 trinary 로 본다.
MAP_YAML_REQUIRED_KEYS = (
    'image', 'resolution', 'origin', 'negate', 'occupied_thresh', 'free_thresh')
SUPPORTED_MODE = 'trinary'
PGM_MAGIC = b'P5'
PGM_MAX_MAXVAL = 255
HEX_DIGEST_LENGTH = 64

# 셀 상태. 자유(FREE)가 아닌 셀은 모두 린트 실패다.
FREE = 'free'
OCCUPIED = 'occupied'
UNKNOWN = 'unknown'
OUTSIDE = 'outside'

# 부동소수 오차 여유. 원 경계(거리 = r)에 중심이 걸린 셀은 원 안으로 친다 (보수적).
DISTANCE_EPS_M = 1e-9
# work_pose 와 맵 YAML waypoints 를 같다고 볼 오차.
POSE_MATCH_EPS = 1e-9
# 후보 좌표를 반올림할 자릿수 (0.000001 m). 0.38499999 같은 표기를 막는다.
COORD_DIGITS = 6
# 린트 실패 때 정차점 후보를 찾는 최대 거리 [m]. 안내용이고 판정에는 쓰지 않는다.
SUGGEST_MAX_DISTANCE_M = 0.5

EXIT_OK = 0
EXIT_LINT_FAILED = 1
EXIT_NOT_FOUND = 2

# 맵 폴더를 어디서 찾았는지.
ORIGIN_INSTALL = 'install'
ORIGIN_SOURCE = 'source'
# ROS 환경인데 cobot_bringup install 이 없어서 소스 트리에서 찾았다. 계약 값(install)이 아닐 수 있다.
ORIGIN_SOURCE_NO_INSTALL = 'source-no-install'


class MapError(Exception):
    """맵·자세 파일을 찾거나 읽지 못했다. 명령은 종료 코드 2 로 끝난다."""


def normalize_newlines(data):
    """
    줄 끝 CRLF 를 LF 로 바꾼다.

    다른 바이트는 그대로 둔다. Windows 체크아웃(core.autocrlf=true)에서도 같은 map_hash 를
    얻기 위해서다.

    :param data: 바이트
    :return: 바꾼 바이트
    """
    return data.replace(b'\r\n', b'\n')


def compute_map_hash(pgm_bytes, yaml_bytes):
    """
    map_hash 를 계산한다.

    sha256( sha256(PGM 바이트) ‖ sha256(LF 정규화한 YAML 바이트) ). ‖ 는 32바이트
    다이제스트 두 개를 이어 붙인 것이다.

    :param pgm_bytes: PGM 파일 바이트
    :param yaml_bytes: 맵 YAML 파일 바이트
    :return: 소문자 16진수 64자
    """
    pgm_digest = hashlib.sha256(pgm_bytes).digest()
    yaml_digest = hashlib.sha256(normalize_newlines(yaml_bytes)).digest()
    return hashlib.sha256(pgm_digest + yaml_digest).hexdigest()


def _is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _is_pose(value):
    return isinstance(value, list) and len(value) == 3 and all(_is_number(v) for v in value)


def _is_bare_filename(value):
    return isinstance(value, str) and bool(value) and os.path.basename(value) == value


def _is_hex_digest(value):
    if not isinstance(value, str) or len(value) != HEX_DIGEST_LENGTH:
        return False
    return all(char in '0123456789abcdef' for char in value)


def _read_bytes(path, what):
    try:
        with open(path, 'rb') as stream:
            return stream.read()
    except OSError as exc:
        raise MapError('{}을(를) 열 수 없다: {} ({})'.format(what, path, exc.strerror))


def _load_yaml(data, path, what):
    try:
        return yaml.safe_load(data.decode('utf-8'))
    except UnicodeDecodeError as exc:
        raise MapError('{}을(를) UTF-8 로 읽을 수 없다: {} ({})'.format(what, path, exc.reason))
    except yaml.YAMLError as exc:
        raise MapError('{} YAML 오류: {} ({})'.format(what, path, exc))


def parse_pgm(data):
    """
    P5(바이너리) PGM 을 읽는다.

    머리(폭, 높이, 최댓값) 사이의 공백과 '#' 주석을 허용한다. 최댓값은 1~255 만 받는다.
    최댓값 뒤 공백 한 바이트 다음부터가 픽셀이고, 픽셀 수는 폭 × 높이와 같아야 한다.

    :param data: PGM 파일 바이트
    :return: (폭, 높이, 최댓값, 픽셀 바이트). 픽셀은 윗줄부터, 줄마다 왼쪽에서 오른쪽 순서다.
    :raises MapError: 형식이 틀리거나 크기가 맞지 않을 때
    """
    if data[:2] != PGM_MAGIC:
        raise MapError('P5 PGM 이 아니다 (첫 두 바이트: {!r})'.format(data[:2]))
    pos = len(PGM_MAGIC)
    if not data[pos:pos + 1].isspace():
        raise MapError('PGM 의 P5 뒤에 공백이 없다')
    fields = []
    while len(fields) < 3:
        char = data[pos:pos + 1]
        if not char:
            raise MapError('PGM 머리가 끝나기 전에 파일이 끝났다')
        if char.isspace():
            pos += 1
        elif char == b'#':
            while pos < len(data) and data[pos:pos + 1] not in (b'\n', b'\r'):
                pos += 1
        else:
            start = pos
            while pos < len(data) and not data[pos:pos + 1].isspace():
                pos += 1
            token = data[start:pos]
            if not token.isdigit():
                raise MapError('PGM 머리 값이 숫자가 아니다: {!r}'.format(token))
            fields.append(int(token))
    # 최댓값 바로 뒤의 공백 한 바이트가 머리의 끝이다 (PGM 규격).
    if not data[pos:pos + 1].isspace():
        raise MapError('PGM 머리 뒤에 공백 한 바이트가 없다')
    pos += 1
    width, height, maxval = fields
    if width <= 0 or height <= 0:
        raise MapError('PGM 크기가 0 이다: {} x {}'.format(width, height))
    if not 1 <= maxval <= PGM_MAX_MAXVAL:
        raise MapError('PGM 최댓값은 1~{} 만 받는다: {}'.format(PGM_MAX_MAXVAL, maxval))
    pixels = data[pos:]
    if len(pixels) != width * height:
        raise MapError('PGM 픽셀 수가 맞지 않는다: 기대 {}, 실제 {}'.format(
            width * height, len(pixels)))
    return width, height, maxval, pixels


def classify_pixel(value, maxval, negate, occupied_thresh, free_thresh):
    """
    PGM 픽셀 하나를 셀 상태로 바꾼다 (nav2 map_server trinary 와 같은 식, 경계값만 보수적).

    occ = 1 - 픽셀 / 최댓값 (negate 0) 또는 픽셀 / 최댓값 (negate 1).
    occ > occupied_thresh 이면 점유, occ < free_thresh 이면 자유, 그 사이는 미지다.
    문턱과 딱 같은 값은 미지로 본다. Jazzy 의 map_server 는 occ >= occupied_thresh 를 점유,
    occ <= free_thresh 를 자유로 본다. 미지는 린트 실패라서 이 차이는 린트가 더 엄격한 쪽이다.

    :return: FREE, OCCUPIED, UNKNOWN 중 하나
    """
    shade = value / maxval
    occ = shade if negate else 1.0 - shade
    if occ > occupied_thresh:
        return OCCUPIED
    if occ < free_thresh:
        return FREE
    return UNKNOWN


class OccupancyGrid:
    """
    맵을 셀 상태 격자로 들고 있는다.

    셀 (mx, my) 순서는 nav_msgs/OccupancyGrid 와 같다. my = 0 이 맵 아래쪽(PGM 의 마지막 줄)이다.
    셀 중심의 map frame 좌표는 (origin_x + (mx + 0.5) * resolution,
    origin_y + (my + 0.5) * resolution) 이다.
    """

    def __init__(self, width, height, resolution, origin_x, origin_y, states):
        self.width = width
        self.height = height
        self.resolution = resolution
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.states = states

    def state(self, mx, my):
        """셀 상태를 돌려준다. 맵 밖이면 OUTSIDE 다."""
        if 0 <= mx < self.width and 0 <= my < self.height:
            return self.states[my * self.width + mx]
        return OUTSIDE

    def cell_center(self, mx, my):
        """셀 중심의 map frame 좌표 (x, y) [m] 를 돌려준다."""
        return (self.origin_x + (mx + 0.5) * self.resolution,
                self.origin_y + (my + 0.5) * self.resolution)

    def cell_of(self, x, y):
        """점 (x, y) 가 든 셀 (mx, my) 를 돌려준다. 맵 밖일 수도 있다."""
        return (int(math.floor((x - self.origin_x) / self.resolution)),
                int(math.floor((y - self.origin_y) / self.resolution)))


def build_grid(pgm_bytes, map_doc):
    """
    PGM 바이트와 맵 YAML 내용으로 OccupancyGrid 를 만든다.

    :raises MapError: PGM 형식이 틀릴 때
    """
    width, height, maxval, pixels = parse_pgm(pgm_bytes)
    table = [
        classify_pixel(value, maxval, map_doc['negate'], map_doc['occupied_thresh'],
                       map_doc['free_thresh'])
        for value in range(maxval + 1)]
    states = []
    # PGM 은 윗줄부터 저장한다. 격자는 아랫줄(my = 0)부터 쌓는다.
    for my in range(height):
        row = height - 1 - my
        for mx in range(width):
            value = pixels[row * width + mx]
            if value > maxval:
                raise MapError('PGM 픽셀 값이 최댓값보다 크다: {} > {}'.format(value, maxval))
            states.append(table[value])
    origin = map_doc['origin']
    return OccupancyGrid(width, height, float(map_doc['resolution']), float(origin[0]),
                         float(origin[1]), states)


def validate_map_doc(map_doc):
    """
    맵 YAML 내용의 형식을 검사한다.

    nav2 map_server 키(image, resolution, origin, negate, occupied_thresh, free_thresh,
    mode)와 팀 확장 키 waypoints 를 본다.

    :return: 오류 문자열 목록. 빈 목록이면 통과다.
    """
    if not isinstance(map_doc, dict):
        return ['맵 YAML 최상위가 mapping 이 아니다']
    errors = []
    for key in MAP_YAML_REQUIRED_KEYS:
        if key not in map_doc:
            errors.append('맵 YAML 에 {} 가 없다'.format(key))
    if errors:
        return errors
    if not isinstance(map_doc['image'], str) or not map_doc['image']:
        errors.append('맵 YAML image 는 비어 있지 않은 문자열이어야 한다')
    if not _is_number(map_doc['resolution']) or map_doc['resolution'] <= 0:
        errors.append('맵 YAML resolution 은 0 보다 큰 수여야 한다: {!r}'.format(
            map_doc['resolution']))
    if not _is_pose(map_doc['origin']):
        errors.append('맵 YAML origin 은 수 3개 목록이어야 한다: {!r}'.format(map_doc['origin']))
    elif map_doc['origin'][2] != 0:
        errors.append('맵 YAML origin 의 yaw 가 0 이 아니다. 회전한 맵은 아직 지원하지 않는다')
    if map_doc['negate'] not in (0, 1) or isinstance(map_doc['negate'], bool):
        errors.append('맵 YAML negate 는 0 또는 1 이어야 한다: {!r}'.format(map_doc['negate']))
    occ = map_doc['occupied_thresh']
    free = map_doc['free_thresh']
    if not (_is_number(occ) and _is_number(free) and 0 <= free < occ <= 1):
        errors.append('맵 YAML 은 0 <= free_thresh < occupied_thresh <= 1 이어야 한다: '
                      '{!r}, {!r}'.format(free, occ))
    mode = map_doc.get('mode', SUPPORTED_MODE)
    if mode != SUPPORTED_MODE:
        errors.append('맵 YAML mode 는 {} 만 지원한다: {!r}'.format(SUPPORTED_MODE, mode))
    waypoints = map_doc.get('waypoints')
    if waypoints is not None:
        if not isinstance(waypoints, dict):
            errors.append('맵 YAML waypoints 는 mapping 이어야 한다')
        else:
            for wp_id, pose in waypoints.items():
                if not _is_pose(pose):
                    errors.append('맵 YAML waypoints.{} 는 [x, y, theta_deg] 여야 한다: '
                                  '{!r}'.format(wp_id, pose))
    return errors


class LoadedMap:
    """맵 YAML 하나와 그 PGM 을 읽은 결과."""

    def __init__(self, yaml_path, pgm_path, yaml_bytes, pgm_bytes, doc, grid):
        self.yaml_path = yaml_path
        self.pgm_path = pgm_path
        self.yaml_bytes = yaml_bytes
        self.pgm_bytes = pgm_bytes
        self.doc = doc
        self.grid = grid
        self.pgm_sha256 = hashlib.sha256(pgm_bytes).hexdigest()
        self.yaml_lf_sha256 = hashlib.sha256(normalize_newlines(yaml_bytes)).hexdigest()
        self.map_hash = compute_map_hash(pgm_bytes, yaml_bytes)


def load_map(yaml_path):
    """
    맵 YAML 과 PGM 을 읽는다.

    PGM 경로는 YAML 의 image 를 YAML 이 있는 폴더 기준으로 푼다.

    :param yaml_path: 맵 YAML 경로
    :return: LoadedMap
    :raises MapError: 파일을 찾거나 읽지 못할 때, 형식이 틀릴 때
    """
    yaml_bytes = _read_bytes(yaml_path, '맵 YAML')
    doc = _load_yaml(yaml_bytes, yaml_path, '맵 YAML')
    errors = validate_map_doc(doc)
    if errors:
        raise MapError('맵 YAML 형식 오류: {} ({})'.format('; '.join(errors), yaml_path))
    pgm_path = doc['image']
    if not os.path.isabs(pgm_path):
        pgm_path = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), pgm_path)
    pgm_bytes = _read_bytes(pgm_path, 'PGM')
    grid = build_grid(pgm_bytes, doc)
    return LoadedMap(yaml_path, pgm_path, yaml_bytes, pgm_bytes, doc, grid)


def disk_cells(grid, x, y, radius_m):
    """
    점 (x, y) 둘레 반경 radius_m 원 안의 셀을 하나씩 돌려준다 (린트 규칙의 정의).

    셀 중심과 점의 거리가 radius_m 이하이면 원 안이다. 점이 든 셀은 반경과 관계없이 늘 넣는다.
    맵 밖 셀의 상태는 OUTSIDE 다.

    :return: (mx, my, 상태) 를 내는 반복자
    """
    res = grid.resolution
    lo_x = int(math.floor((x - radius_m - grid.origin_x) / res)) - 1
    hi_x = int(math.floor((x + radius_m - grid.origin_x) / res)) + 1
    lo_y = int(math.floor((y - radius_m - grid.origin_y) / res)) - 1
    hi_y = int(math.floor((y + radius_m - grid.origin_y) / res)) + 1
    own_cell = grid.cell_of(x, y)
    for my in range(lo_y, hi_y + 1):
        for mx in range(lo_x, hi_x + 1):
            center_x, center_y = grid.cell_center(mx, my)
            inside = math.hypot(center_x - x, center_y - y) <= radius_m + DISTANCE_EPS_M
            if inside or (mx, my) == own_cell:
                yield mx, my, grid.state(mx, my)


def disk_problems(grid, x, y, radius_m):
    """
    점 (x, y) 둘레 반경 radius_m 원 안의 셀 중 자유가 아닌 셀을 돌려준다.

    원의 정의는 disk_cells 와 같다.

    :return: (원 안 셀 수, [(mx, my, 상태)] 목록). 목록이 비면 통과다.
    """
    count = 0
    problems = []
    for mx, my, state in disk_cells(grid, x, y, radius_m):
        count += 1
        if state != FREE:
            problems.append((mx, my, state))
    return count, problems


def disk_is_free(grid, x, y, radius_m):
    """원 안 셀이 모두 자유이면 True. 자유가 아닌 셀을 만나면 바로 멈춘다."""
    return all(state == FREE for _, _, state in disk_cells(grid, x, y, radius_m))


def lint_waypoints(grid, waypoints, radius_m):
    """
    웨이포인트마다 반경 radius_m 원 안 셀이 모두 자유인지 본다.

    :param waypoints: {웨이포인트 ID: [x, y, theta_deg]}
    :return: {웨이포인트 ID: (원 안 셀 수, 문제 셀 목록)}. 통과한 웨이포인트는 넣지 않는다.
    """
    failures = {}
    for wp_id in sorted(waypoints):
        pose = waypoints[wp_id]
        count, problems = disk_problems(grid, pose[0], pose[1], radius_m)
        if problems:
            failures[wp_id] = (count, problems)
    return failures


def nearest_free_point(grid, x, y, radius_m, max_distance_m=SUGGEST_MAX_DISTANCE_M):
    """
    (x, y) 에서 가장 가까운, 반경 radius_m 원이 모두 자유인 점을 찾는다.

    후보는 (x, y) 에서 맵 해상도 간격으로 떨어진 격자점이다. 거리가 같은 후보가 여럿이면
    y 가 가장 작은 (아래쪽) 점, 그다음 x 가 가장 작은 (왼쪽) 점을 고른다. 정차점 초안을 안내하려고 쓴다.
    기하만 본 값이라 진입 방향·팔 도달 거리·경로 연결은 주행 담당이 확인해야 한다.

    :return: (x, y) 또는 max_distance_m 안에 없으면 None
    """
    step = grid.resolution
    steps = int(math.floor(max_distance_m / step + DISTANCE_EPS_M))
    limit = steps * steps
    offsets = sorted(
        (i * i + j * j, j, i)
        for j in range(-steps, steps + 1)
        for i in range(-steps, steps + 1)
        if i * i + j * j <= limit)
    for _, j, i in offsets:
        cand_x = round(x + i * step, COORD_DIGITS)
        cand_y = round(y + j * step, COORD_DIGITS)
        if disk_is_free(grid, cand_x, cand_y, radius_m):
            return cand_x, cand_y
    return None


def read_poses(path):
    """
    approach_poses.yaml 을 읽고 형식을 검사한다.

    :return: (내용, 오류 문자열 목록). 목록이 비면 형식은 통과다.
    :raises MapError: 파일을 찾거나 읽지 못할 때
    """
    data = _read_bytes(path, POSES_FILENAME)
    doc = _load_yaml(data, path, POSES_FILENAME)
    if not isinstance(doc, dict):
        return doc, ['{} 최상위가 mapping 이 아니다'.format(POSES_FILENAME)]
    errors = []
    for key in POSES_TOP_KEYS:
        if key not in doc:
            errors.append('{} 에 {} 가 없다'.format(POSES_FILENAME, key))
    for key in sorted(set(doc) - set(POSES_TOP_KEYS)):
        errors.append('{} 에 모르는 키가 있다: {}'.format(POSES_FILENAME, key))
    if errors:
        return doc, errors
    if doc['schema_version'] != POSES_SCHEMA_VERSION:
        errors.append('schema_version 은 {} 이어야 한다: {!r}'.format(
            POSES_SCHEMA_VERSION, doc['schema_version']))
    if doc['status'] not in POSE_STATUSES:
        errors.append('status 는 {} 중 하나여야 한다: {!r}'.format(
            ', '.join(POSE_STATUSES), doc['status']))
    radius = doc['clearance_radius_m']
    if not _is_number(radius) or radius <= 0:
        errors.append('clearance_radius_m 은 0 보다 큰 수여야 한다: {!r}'.format(radius))
    errors.extend(_validate_map_block(doc['map']))
    errors.extend(_validate_waypoint_block(doc['waypoints']))
    return doc, errors


def _validate_map_block(block):
    if not isinstance(block, dict):
        return ['map 은 mapping 이어야 한다']
    errors = []
    for key in MAP_BLOCK_KEYS:
        if key not in block:
            errors.append('map 에 {} 가 없다'.format(key))
    for key in sorted(set(block) - set(MAP_BLOCK_KEYS) - set(MAP_BLOCK_OPTIONAL_KEYS)):
        errors.append('map 에 모르는 키가 있다: {}'.format(key))
    for key in MAP_BLOCK_OPTIONAL_KEYS:
        if key in block and not isinstance(block[key], str):
            errors.append('map.{} 는 문자열이어야 한다'.format(key))
    if 'yaml' in block and not _is_bare_filename(block['yaml']):
        errors.append('map.yaml 은 같은 폴더의 파일 이름이어야 한다 (경로 금지): {!r}'.format(
            block['yaml']))
    for key in ('pgm_sha256', 'yaml_lf_sha256', 'map_hash'):
        if key in block and not _is_hex_digest(block[key]):
            errors.append('map.{} 는 소문자 16진수 64자여야 한다: {!r}'.format(key, block[key]))
    return errors


def _validate_waypoint_block(waypoints):
    if not isinstance(waypoints, dict) or not waypoints:
        return ['waypoints 는 비어 있지 않은 mapping 이어야 한다']
    errors = []
    for wp_id, entry in waypoints.items():
        if not isinstance(entry, dict):
            errors.append('waypoints.{} 는 mapping 이어야 한다'.format(wp_id))
            continue
        for key in WAYPOINT_KEYS:
            if not _is_pose(entry.get(key)):
                errors.append('waypoints.{}.{} 는 [x, y, theta_deg] 여야 한다: {!r}'.format(
                    wp_id, key, entry.get(key)))
        for key in sorted(set(entry) - set(WAYPOINT_KEYS) - set(WAYPOINT_OPTIONAL_KEYS)):
            errors.append('waypoints.{} 에 모르는 키가 있다: {}'.format(wp_id, key))
        if 'note' in entry and not isinstance(entry['note'], str):
            errors.append('waypoints.{}.note 는 문자열이어야 한다'.format(wp_id))
        if ARM_ID in entry:
            arm_id = entry[ARM_ID]
            if not isinstance(arm_id, str) or not ARM_ID_PATTERN.fullmatch(arm_id):
                errors.append('waypoints.{}.arm_id 는 영문자로 시작하고 영문자·숫자·_ 만 쓴 '
                              '문자열이어야 한다: {!r}'.format(wp_id, arm_id))
    return errors


def arm_ids_of(poses_doc):
    """
    approach_poses.yaml 내용에서 웨이포인트별 연계된 팔을 뽑는다.

    arm_id 가 없는 웨이포인트(팔이 없는 지점)는 빈 문자열이다 (Waypoint.msg 의 arm_id 와 같다).

    :return: {웨이포인트 ID: arm_id 또는 ''}
    """
    return {wp_id: entry.get(ARM_ID, '') for wp_id, entry in poses_doc['waypoints'].items()}


def poses_of(poses_doc, kind):
    """
    approach_poses.yaml 내용에서 한 종류의 자세만 뽑는다.

    :param kind: APPROACH_POSE 또는 WORK_POSE
    :return: {웨이포인트 ID: [x, y, theta_deg]}
    """
    return {wp_id: entry[kind] for wp_id, entry in poses_doc['waypoints'].items()}


def check_manifest(block, loaded):
    """
    approach_poses.yaml 의 map 블록(sha256, map_hash)이 실제 파일과 같은지 본다.

    맵을 바꾸고 값을 갱신하지 않으면 여기서 실패한다.

    :return: 오류 문자열 목록
    """
    errors = []
    actual = {
        'pgm_sha256': loaded.pgm_sha256,
        'yaml_lf_sha256': loaded.yaml_lf_sha256,
        'map_hash': loaded.map_hash,
    }
    for key in ('pgm_sha256', 'yaml_lf_sha256', 'map_hash'):
        if block[key] != actual[key]:
            errors.append('map.{} 가 실제 파일과 다르다: 적힌 값 {}, 실제 {}'.format(
                key, block[key], actual[key]))
    return errors


def check_work_poses(poses_doc, map_doc):
    """
    work_pose 가 맵 YAML 의 waypoints 와 같은지 본다 (ID 집합과 좌표).

    :return: 오류 문자열 목록
    """
    map_waypoints = map_doc.get('waypoints')
    if not map_waypoints:
        return ['맵 YAML 에 waypoints 가 없다. work_pose 를 대조할 수 없다']
    errors = []
    poses = poses_of(poses_doc, WORK_POSE)
    for wp_id in sorted(set(map_waypoints) - set(poses)):
        errors.append('{} 에 없는 웨이포인트: {}'.format(POSES_FILENAME, wp_id))
    for wp_id in sorted(set(poses) - set(map_waypoints)):
        errors.append('맵 YAML waypoints 에 없는 웨이포인트: {}'.format(wp_id))
    for wp_id in sorted(set(poses) & set(map_waypoints)):
        pairs = zip(poses[wp_id], map_waypoints[wp_id])
        if any(abs(mine - theirs) > POSE_MATCH_EPS for mine, theirs in pairs):
            errors.append('{} work_pose {} 가 맵 YAML waypoints 값 {} 과 다르다'.format(
                wp_id, poses[wp_id], map_waypoints[wp_id]))
    return errors


class LintReport:
    """run_lint 결과."""

    def __init__(self, errors, failures, loaded, radius_m, kind, poses):
        self.errors = errors
        self.failures = failures
        self.loaded = loaded
        self.radius_m = radius_m
        self.kind = kind
        self.poses = poses


def _describe_failure(wp_id, kind, pose, radius_m, count, problems):
    by_state = {}
    for _, _, state in problems:
        by_state[state] = by_state.get(state, 0) + 1
    detail = ', '.join('{} {}'.format(state, by_state[state]) for state in sorted(by_state))
    return '{} {} ({:.3f}, {:.3f}): 반경 {:.3f} m 원 안 셀 {}개 중 {}개가 자유가 아니다 ({})'.format(
        wp_id, kind, pose[0], pose[1], radius_m, count, len(problems), detail)


def run_lint(maps_dir, kind=APPROACH_POSE, radius_m=None):
    """
    맵 폴더 하나를 검사한다.

    순서: approach_poses.yaml 형식 → 맵 YAML·PGM 읽기 → 매니페스트(sha256·map_hash) →
    work_pose 와 맵 YAML waypoints 대조 → kind 자세마다 반경 원 검사.

    :param maps_dir: approach_poses.yaml 이 있는 폴더
    :param kind: 반경 원을 볼 자세 (APPROACH_POSE 또는 WORK_POSE)
    :param radius_m: 반경 [m]. None 이면 approach_poses.yaml 의 clearance_radius_m
    :return: LintReport. errors 가 비면 통과다.
    :raises MapError: 파일을 찾거나 읽지 못할 때
    """
    if kind not in POSE_KINDS:
        raise ValueError('kind 는 {} 중 하나다: {!r}'.format(POSE_KINDS, kind))
    poses_path = os.path.join(maps_dir, POSES_FILENAME)
    poses_doc, errors = read_poses(poses_path)
    if errors:
        return LintReport(errors, {}, None, radius_m, kind, {})
    if radius_m is None:
        radius_m = poses_doc['clearance_radius_m']
    if not _is_number(radius_m) or radius_m <= 0:
        return LintReport(['반경은 0 보다 큰 수여야 한다: {!r}'.format(radius_m)], {}, None,
                          radius_m, kind, {})
    loaded = load_map(os.path.join(maps_dir, poses_doc['map']['yaml']))
    if not _is_bare_filename(loaded.doc['image']):
        errors.append('맵 YAML image 는 같은 폴더의 파일 이름이어야 한다 (경로 금지): {!r}'.format(
            loaded.doc['image']))
    errors.extend(check_manifest(poses_doc['map'], loaded))
    errors.extend(check_work_poses(poses_doc, loaded.doc))
    poses = poses_of(poses_doc, kind)
    failures = lint_waypoints(loaded.grid, poses, radius_m)
    for wp_id in sorted(failures):
        count, problems = failures[wp_id]
        errors.append(_describe_failure(wp_id, kind, poses[wp_id], radius_m, count, problems))
    return LintReport(errors, failures, loaded, radius_m, kind, poses)


def _installed_maps_dir():
    # (install 맵 폴더 또는 None, ROS 환경인가) 를 돌려준다.
    # ament_index_python 을 불러올 수 있으면 ROS 환경(ROS 를 source 한 셸)으로 본다.
    try:
        packages = importlib.import_module('ament_index_python.packages')
    except ImportError:
        return None, False
    try:
        share = packages.get_package_share_directory(BRINGUP_PACKAGE)
    except (LookupError, OSError, ValueError):
        return None, True
    path = os.path.join(share, MAPS_SUBDIR)
    if os.path.isfile(os.path.join(path, POSES_FILENAME)):
        return path, True
    return None, True


def _source_maps_dir(start):
    current = os.path.abspath(start)
    while True:
        path = os.path.join(current, MAPS_RELPATH)
        if os.path.isfile(os.path.join(path, POSES_FILENAME)):
            return path
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_maps_dir(start=None):
    """
    맵 폴더(approach_poses.yaml 이 있는 곳)를 찾는다.

    start 를 주면 start 에서 위로 올라가며 src/cobot_bringup/config/maps 만 찾는다.
    start 가 없으면 (1) cobot_bringup 의 install share/config/maps (ROS 환경일 때),
    (2) 현재 폴더에서 위로, (3) 이 파일 위치에서 위로 찾는다.
    map_hash 의 기준은 install 된 파일이므로 ROS 환경에서는 install 을 먼저 쓴다.
    ROS 환경인데 install 이 없어서 소스 트리에서 찾았으면 출처를 ORIGIN_SOURCE_NO_INSTALL 로
    따로 표시한다. 명령은 이 경우 --allow-source 없이는 멈춘다.

    :return: (폴더 경로, ORIGIN_INSTALL·ORIGIN_SOURCE·ORIGIN_SOURCE_NO_INSTALL 중 하나).
        못 찾으면 (None, None)
    """
    if start is not None:
        path = _source_maps_dir(start)
        return (path, ORIGIN_SOURCE) if path else (None, None)
    path, ros_env = _installed_maps_dir()
    if path:
        return path, ORIGIN_INSTALL
    origin = ORIGIN_SOURCE_NO_INSTALL if ros_env else ORIGIN_SOURCE
    for candidate in (os.getcwd(), os.path.dirname(os.path.realpath(__file__))):
        path = _source_maps_dir(candidate)
        if path:
            return path, origin
    return None, None


def _resolve_maps_dir(maps_dir, allow_source=False):
    if maps_dir is not None:
        if not os.path.isfile(os.path.join(maps_dir, POSES_FILENAME)):
            raise MapError('{} 이 없다: {}'.format(POSES_FILENAME, maps_dir))
        return maps_dir
    path, origin = find_maps_dir()
    if path is None:
        raise MapError('맵 폴더를 찾지 못했다. 레포 안에서 돌리거나 install/setup.bash 를 '
                       'source 하거나 --maps-dir 로 경로를 준다.')
    if origin == ORIGIN_SOURCE_NO_INSTALL:
        if not allow_source:
            raise MapError(
                'ROS 환경인데 cobot_bringup 의 install 맵을 찾지 못했다. map_hash 의 입력은 '
                'install 된 파일이다. 레포 루트에서 colcon build --packages-up-to cobot_bringup '
                'cobot_control_center 를 하고 source install/setup.bash 를 한 뒤 다시 돌린다. '
                '소스 트리 맵을 알고서 보려면 --allow-source 를 준다 (소스 트리: {})'.format(path))
        LOGGER.warning('맵 폴더 (source): %s. install 이 아니라 소스 트리다. '
                       '이 값은 install 된 맵의 값(계약 값)과 다를 수 있다', path)
        return path
    LOGGER.info('맵 폴더 (%s): %s', origin, path)
    return path


ALLOW_SOURCE_HELP = ('ROS 환경에서 cobot_bringup install 이 없을 때 소스 트리 맵을 쓴다 '
                     '(경고가 나온다. 계약 값은 install 된 맵의 값이다)')


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def hash_main(argv=None):
    """
    map_hash 명령의 진입점.

    map_hash 를 표준 출력에 한 줄로 쓴다 (스크립트에서 받아 쓰도록). 진행 메시지는 logging
    (표준 오류)으로 낸다. 맵을 찾거나 읽지 못하면 2, 성공하면 0 을 돌려준다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(description='맵의 map_hash 를 계산한다.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--maps-dir', help='approach_poses.yaml 이 있는 맵 폴더 (기본: 찾는다)')
    group.add_argument('--map-yaml', help='맵 YAML 경로를 바로 준다 (approach_poses.yaml 을 안 본다)')
    parser.add_argument('--allow-source', action='store_true', help=ALLOW_SOURCE_HELP)
    args = parser.parse_args(argv)
    _setup_logging()
    try:
        yaml_path = args.map_yaml
        if yaml_path is None:
            maps_dir = _resolve_maps_dir(args.maps_dir, args.allow_source)
            poses_doc, errors = read_poses(os.path.join(maps_dir, POSES_FILENAME))
            block = poses_doc.get('map') if isinstance(poses_doc, dict) else None
            name = block.get('yaml') if isinstance(block, dict) else None
            if not isinstance(name, str) or not name:
                raise MapError('{} 의 map.yaml 을 읽지 못했다: {}'.format(
                    POSES_FILENAME, '; '.join(errors)))
            yaml_path = os.path.join(maps_dir, name)
        loaded = load_map(yaml_path)
    except MapError as exc:
        LOGGER.error('%s', exc)
        return EXIT_NOT_FOUND
    LOGGER.info('맵 YAML: %s', loaded.yaml_path)
    LOGGER.info('PGM: %s', loaded.pgm_path)
    # 결과 값 한 줄. 로그가 아니라 명령의 출력이라 표준 출력에 쓴다.
    sys.stdout.write(loaded.map_hash + '\n')
    return EXIT_OK


def lint_main(argv=None):
    """
    map_lint 명령의 진입점.

    오류가 있으면 1, 파일을 찾거나 읽지 못하면 2, 통과하면 0 을 돌려준다.
    --suggest 를 주면 반경 원 검사에 실패한 웨이포인트에 가장 가까운 자유 점(초안 후보)을
    알려 준다. 반경이 크면 오래 걸려서 기본으로는 하지 않는다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(description='맵과 웨이포인트 자세를 검사한다.')
    parser.add_argument('--maps-dir', help='approach_poses.yaml 이 있는 맵 폴더 (기본: 찾는다)')
    parser.add_argument('--poses', choices=POSE_KINDS, default=APPROACH_POSE,
                        help='반경 원을 볼 자세 (기본: approach_pose)')
    parser.add_argument('--radius', type=float,
                        help='반경 [m] (기본: approach_poses.yaml 의 clearance_radius_m)')
    parser.add_argument('--suggest', action='store_true',
                        help='실패한 웨이포인트에 가장 가까운 자유 점(초안 후보)을 알려 준다')
    parser.add_argument('--allow-source', action='store_true', help=ALLOW_SOURCE_HELP)
    args = parser.parse_args(argv)
    _setup_logging()
    try:
        maps_dir = _resolve_maps_dir(args.maps_dir, args.allow_source)
        report = run_lint(maps_dir, args.poses, args.radius)
    except MapError as exc:
        LOGGER.error('%s', exc)
        return EXIT_NOT_FOUND
    if report.loaded is not None:
        LOGGER.info('map_hash: %s', report.loaded.map_hash)
    if report.loaded is not None and args.suggest:
        for wp_id in sorted(report.failures):
            pose = report.poses[wp_id]
            point = nearest_free_point(report.loaded.grid, pose[0], pose[1], report.radius_m)
            if point is None:
                LOGGER.info('%s: %.2f m 안에 자유 점이 없다', wp_id, SUGGEST_MAX_DISTANCE_M)
            else:
                LOGGER.info('%s: 가장 가까운 자유 점(초안 후보) [%.3f, %.3f, %s] (%.3f m 이동)',
                            wp_id, point[0], point[1], pose[2],
                            math.hypot(point[0] - pose[0], point[1] - pose[1]))
    for error in report.errors:
        LOGGER.error('%s', error)
    if report.errors:
        LOGGER.error('실패: 오류 %d건', len(report.errors))
        return EXIT_LINT_FAILED
    LOGGER.info('통과: 웨이포인트 %d개, %s, 반경 %.3f m, 오류 0건',
                len(report.poses), report.kind, report.radius_m)
    return EXIT_OK


def main(argv=None):
    """
    모듈 실행(python3 -m cobot_control_center.map_contract)의 진입점.

    첫 인자가 hash 이면 map_hash, lint 이면 map_lint 와 같다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    args = sys.argv[1:] if argv is None else list(argv)
    commands = {'hash': hash_main, 'lint': lint_main}
    if not args or args[0] not in commands:
        _setup_logging()
        LOGGER.error('사용법: python3 -m cobot_control_center.map_contract {hash|lint} [옵션]')
        return EXIT_NOT_FOUND
    return commands[args[0]](args[1:])


if __name__ == '__main__':
    sys.exit(main())
