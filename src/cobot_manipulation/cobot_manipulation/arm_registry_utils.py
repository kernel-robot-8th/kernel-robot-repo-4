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
팔 등록표와 USB 시리얼 탐지 (ROS 없는 순수 로직).

팔 이름(arm_id)은 관제 scenario.yaml 의 자리 역할 이름이다 (omx1 = 상차 팔 등).
등록표는 '그 자리에 있어야 할 보드의 시리얼' 을 적는다. 보드가 바뀌면 시리얼이 달라
UNKNOWN 이 되고 일을 하지 않는다. 다른 팔로 추측해 움직이는 것이 가장 위험하기 때문이다.

리눅스는 USB 시리얼 장치마다 /dev/serial/by-id/usb-<제조사>_<모델>_<시리얼>-if<번호> 를
만든다. 어느 PC·어느 포트에 꽂아도 이름이 같아서 udev 규칙 없이 쓸 수 있다.
여기서는 목록의 이름만 읽고 장치는 열지 않는다.
"""

import os
import re

import yaml

READY, UNKNOWN = 'READY', 'UNKNOWN'
ARM_ID_PATTERN = re.compile(r'[A-Za-z0-9_-]{1,80}')
SERIAL_PATTERN = re.compile(r'[A-Za-z0-9]{1,64}')
# 시리얼은 마지막 '_' 뒤, '-if' 앞이다. 첫 인터페이스(if00)만 장치 1개로 센다.
BY_ID_PATTERN = re.compile(r'^usb-.+_(?P<serial>[A-Za-z0-9]+)-if(?P<intf>\d+)(?:-port\d+)?$')


class RegistryError(Exception):
    """등록표를 읽지 못했거나 형식이 틀림."""


def parse_registry(data):
    """
    등록표 dict 를 {arm_id: serial} 로 바꾼다. 시리얼이 빈 팔은 '아직 등록 안 됨' 이다.

    형식: {'arms': {'omx1': {'serial': '6D96...'}, ...}}
    """
    if not isinstance(data, dict) or not isinstance(data.get('arms'), dict):
        raise RegistryError('등록표에 arms 항목(객체)이 필요합니다')
    registry = {}
    for arm_id, entry in data['arms'].items():
        if not isinstance(arm_id, str) or not ARM_ID_PATTERN.fullmatch(arm_id):
            raise RegistryError(f'팔 이름 형식 오류: {arm_id!r}')
        entry = {} if entry is None else entry
        if not isinstance(entry, dict):
            raise RegistryError(f'{arm_id}: serial 항목을 가진 객체가 필요합니다')
        serial = entry.get('serial')
        serial = '' if serial is None else str(serial).strip()
        if serial and not SERIAL_PATTERN.fullmatch(serial):
            raise RegistryError(f'{arm_id}: 시리얼 형식 오류: {serial!r}')
        registry[arm_id] = serial.upper()
    return registry


def load_registry(path):
    """등록표 YAML 파일을 읽는다."""
    try:
        with open(os.path.expanduser(path), encoding='utf-8') as handle:
            return parse_registry(yaml.safe_load(handle))
    except (OSError, yaml.YAMLError) as error:
        raise RegistryError(f'등록표를 읽지 못함 ({path}): {error}') from error


def list_by_id(directory):
    """by-id 폴더의 이름 목록. 장치가 하나도 없으면 폴더 자체가 없으므로 빈 목록이다."""
    try:
        return sorted(os.listdir(directory))
    except FileNotFoundError:
        return []


def detect(arm_id, registry, entries, directory):
    """
    이 팔의 포트를 찾는다. (상태, 포트 경로 또는 None, 이유) 를 돌려준다.

    READY 는 등록된 시리얼이 정확히 1개 보일 때뿐이다. 나머지는 모두 UNKNOWN 이다.
    """
    serial = registry.get(arm_id)
    if serial is None:
        return UNKNOWN, None, f'등록표에 {arm_id} 가 없음'
    if not serial:
        return UNKNOWN, None, f'{arm_id} 시리얼이 아직 등록되지 않음'
    owners = [name for name, value in registry.items() if value == serial]
    if len(owners) > 1:
        return UNKNOWN, None, f'같은 시리얼이 여러 팔에 등록됨: {", ".join(sorted(owners))}'
    matches = []
    for name in entries:
        found = BY_ID_PATTERN.match(name)
        if found and found.group('serial').upper() == serial and int(found.group('intf')) == 0:
            matches.append(name)
    if not matches:
        return UNKNOWN, None, f'{arm_id} 보드(시리얼 {serial})가 연결되어 있지 않음'
    if len(matches) > 1:
        return UNKNOWN, None, f'{arm_id} 시리얼이 여러 장치에서 보임: {", ".join(matches)}'
    return READY, os.path.join(directory, matches[0]), f'{arm_id} 보드 확인 ({matches[0]})'
