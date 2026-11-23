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
현장 로봇팔 배치(config/site_arms.yaml) 읽기 (ROS 없는 순수 로직).

자리(구역) · 팔 이름 · 보드 시리얼 · Station PC · 그 자리에서 하는 작업을 한 곳에 적는다.
지금은 관제(arm_command_node)만 읽는다. 팔 노드 등록표와 주행 관제 시나리오는 아직 따로 있다.
"""

import re

from cobot_control_center.arm_command_utils import ARM_ID_PATTERN, interface_arm_id, WORK_ACTIONS
import yaml

SITE_ROLES = ('pickup', 'dropoff', 'warehouse')
SERIAL_PATTERN = re.compile(r'[A-Za-z0-9]{1,64}')   # 팔 노드 arm_registry_utils 와 같은 형식
VIDEO_PATTERN = re.compile(r'https?://[^\s/]+(/[^\s]*)?')   # 팔 카메라 미리보기 주소


def _site_text(entry, key, arm_id):
    value = entry.get(key)
    value = '' if value is None else value
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f'{arm_id}.{key} 는 글자여야 함: {value!r}')
    return str(value).strip()


def _site_actions(value, arm_id):
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
        raise ValueError(f'{arm_id}.actions 는 작업 이름 목록이어야 함: {value!r}')
    actions = [a.strip().lower() for a in value]
    unknown = [a for a in actions if a not in WORK_ACTIONS]
    if unknown:
        raise ValueError(f'{arm_id}.actions 에 모르는 작업 {unknown} '
                         f'({", ".join(WORK_ACTIONS)} 중에서)')
    return list(dict.fromkeys(actions))


def _site_video(value, arm_id):
    """팔 카메라 미리보기 주소 (팔 실행기 cam_preview). 비면 ''. http(s) 주소만, 끝 / 는 뺀다."""
    if value is None or value == '':
        return ''
    if not isinstance(value, str) or not VIDEO_PATTERN.fullmatch(value.strip()):
        raise ValueError(f'{arm_id}.video 는 http(s) 주소여야 함: {value!r}')
    return value.strip().rstrip('/')


def parse_site_arms(data):
    """
    현장 팔 배치(config/site_arms.yaml 내용) → {팔 이름(omx_1): {station, role, host, serial, ...}}.

    칸: station, role, host, serial, actions, video.

    팔 순서는 파일 순서를 지킨다. 빈 칸은 '' (미정). actions 는 그 팔이 하는 작업 목록이고,
    칸이 없으면 None (제한 없음), [] 이면 작업 없음. video 는 팔 카메라 미리보기 주소 (없으면 '').
    형식이 틀리면 ValueError.
    """
    if not isinstance(data, dict) or not isinstance(data.get('arms'), dict) or not data['arms']:
        raise ValueError('arms 항목(팔 이름 → 배치)이 필요함')
    site = {}
    for name, entry in data['arms'].items():
        arm_id = interface_arm_id(str(name))
        if not ARM_ID_PATTERN.fullmatch(arm_id) or arm_id in site:
            raise ValueError(f'팔 이름 형식 오류 또는 중복: {name!r}')
        entry = {} if entry is None else entry
        if not isinstance(entry, dict):
            raise ValueError(f'{name}: station·role·host·serial 을 가진 객체가 필요함')
        info = {key: _site_text(entry, key, name) for key in ('station', 'role', 'host', 'serial')}
        if info['role'] and info['role'] not in SITE_ROLES:
            raise ValueError(f'{name}.role 은 {", ".join(SITE_ROLES)} 중 하나: {info["role"]!r}')
        if info['serial'] and not SERIAL_PATTERN.fullmatch(info['serial']):
            raise ValueError(f'{name}.serial 형식 오류: {info["serial"]!r}')
        info['serial'] = info['serial'].upper()
        info['actions'] = _site_actions(entry.get('actions', None), name)
        info['video'] = _site_video(entry.get('video'), name)
        site[arm_id] = info
    return site


def load_site_arms(path):
    """현장 팔 배치 파일을 읽는다. 못 읽거나 형식이 틀리면 ValueError (OSError·YAML 오류 포함)."""
    try:
        with open(path, encoding='utf-8') as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(str(error)) from None
    return parse_site_arms(data)
