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
관제 백엔드: 최신 fleet_status 스냅샷 보관 (ROS·fastapi 없는 순수 로직).

ROS 콜백 스레드가 put() 으로 넣고, 웹 서버 스레드가 get()·wait_newer() 로 읽는다.
그래서 모든 접근을 lock 으로 감싼다. 시각은 clock 인자로 받아 시험에서 바꿔 끼운다.
"""

import json
import os
import threading
import time

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


class SnapshotStore:
    """fleet_status JSON 의 최신 값과 받은 시각, 순번을 보관한다."""

    def __init__(self, stale_sec, clock=time.monotonic):
        self.stale_sec = float(stale_sec)
        self.clock = clock
        self._cond = threading.Condition()
        self._snapshot = None
        self._received = None
        self._seq = 0

    def put(self, text):
        """JSON 문자열을 넣는다. dict 가 아니거나 깨진 값이면 False 이고 기존 값을 유지한다."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        with self._cond:
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

    def wait_newer(self, seq, timeout):
        """순번이 seq 보다 큰 값이 들어올 때까지 최대 timeout 초 기다린다. 새 값이 있으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: self._seq > seq, timeout)
