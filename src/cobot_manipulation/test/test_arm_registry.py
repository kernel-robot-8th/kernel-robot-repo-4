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

"""등록표 읽기와 by-id 이름으로 팔 보드를 찾는 로직."""

import os

from cobot_manipulation.arm_registry_utils import (detect, list_by_id, load_registry,
                                                   parse_registry, READY, RegistryError,
                                                   UNKNOWN)
import pytest

SERIAL = '6D96FA0450323952582E3120FF052A1E'
OTHER = 'AAAABBBBCCCCDDDD'
BY_ID = '/dev/serial/by-id'


def entry(serial, intf='00'):
    return f'usb-ROBOTIS_OpenRB-150_{serial}-if{intf}'


def registry(**arms):
    return parse_registry({'arms': {name: {'serial': value} for name, value in arms.items()}})


def test_ready_when_exactly_one_board_matches():
    state, port, _ = detect('omx1', registry(omx1=SERIAL), [entry(SERIAL)], BY_ID)
    assert state == READY
    assert port == f'{BY_ID}/{entry(SERIAL)}'


def test_serial_match_ignores_case_and_other_interfaces():
    names = [entry(SERIAL.lower()), entry(SERIAL.lower(), '01')]
    state, _, _ = detect('omx1', registry(omx1=SERIAL), names, BY_ID)
    assert state == READY


def test_ftdi_style_name_with_port_suffix():
    name = f'usb-FTDI_USB__-__Serial_Converter_{OTHER}-if00-port0'
    state, _, _ = detect('omx2', registry(omx2=OTHER), [name], BY_ID)
    assert state == READY


@pytest.mark.parametrize('arms, names, arm_id', [
    ({'omx1': SERIAL}, [], 'omx1'),                                  # 연결 안 됨
    ({'omx1': SERIAL}, [entry(OTHER)], 'omx1'),                      # 다른 보드만 있음
    ({'omx1': ''}, [entry(SERIAL)], 'omx1'),                         # 아직 등록 안 됨
    ({'omx1': SERIAL}, [entry(SERIAL)], 'omx3'),                     # 등록표에 없음
    ({'omx1': SERIAL, 'omx2': SERIAL}, [entry(SERIAL)], 'omx1'),     # 시리얼 중복 등록
])
def test_unknown_cases(arms, names, arm_id):
    state, port, reason = detect(arm_id, registry(**arms), names, BY_ID)
    assert (state, port) == (UNKNOWN, None)
    assert reason


def test_same_serial_on_two_devices_is_unknown():
    names = [entry(SERIAL), 'usb-ROBOTIS_OpenRB-150_X_' + SERIAL + '-if00']
    state, _, reason = detect('omx1', registry(omx1=SERIAL), names, BY_ID)
    assert state == UNKNOWN
    assert '여러 장치' in reason


@pytest.mark.parametrize('data', [
    None, {}, {'arms': []}, {'arms': {'omx 1': {'serial': SERIAL}}},
    {'arms': {'omx1': 'not-a-dict'}}, {'arms': {'omx1': {'serial': 'bad/serial'}}},
])
def test_bad_registry_is_rejected(data):
    with pytest.raises(RegistryError):
        parse_registry(data)


def test_empty_entry_means_unregistered():
    assert parse_registry({'arms': {'omx3': None}}) == {'omx3': ''}


def test_load_registry_and_missing_file(tmp_path):
    path = tmp_path / 'arms.yaml'
    path.write_text(f'arms:\n  omx1:\n    serial: {SERIAL.lower()}\n', encoding='utf-8')
    assert load_registry(str(path)) == {'omx1': SERIAL}
    with pytest.raises(RegistryError):
        load_registry(str(tmp_path / 'missing.yaml'))


def test_shipped_registry_is_valid():
    path = os.path.join(os.path.dirname(__file__), '..', 'config', 'arm_registry.yaml')
    assert set(load_registry(path)) == {'omx1', 'omx2', 'omx3'}


def test_list_by_id_without_folder(tmp_path):
    assert list_by_id(str(tmp_path / 'none')) == []
    (tmp_path / entry(SERIAL)).touch()
    assert list_by_id(str(tmp_path)) == [entry(SERIAL)]
