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
생성 타입 시험 (b): colcon build 로 생긴 Python 타입을 import 해서 필드를 본다.

ROS 2 Jazzy 환경에서 `colcon test --packages-select cobot_interfaces` 로 돈다.
import 가 안 되면 실패다. 건너뛰지(skip) 않는다. skip 은 통과가 아니다.
글자 정의(.msg 등)와 생성 타입의 필드 이름·상수 값이 같아야 통과다.
"""

import importlib
import os

import interface_schema as schema
import pytest
from rclpy.serialization import deserialize_message, serialize_message

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFS = schema.load_package(PKG_DIR, schema.PACKAGE_NAME)
PART_ATTRS = {
    'msg': (None,),
    'srv': ('Request', 'Response'),
    'action': ('Goal', 'Result', 'Feedback'),
}


def _generated_class(iface):
    module = importlib.import_module('{}.{}'.format(schema.PACKAGE_NAME, iface.kind))
    return getattr(module, iface.name)


def _parts(iface):
    top = _generated_class(iface)
    return [top if attr is None else getattr(top, attr) for attr in PART_ATTRS[iface.kind]]


def _expected_value(constant):
    value = schema.constant_value(constant)
    base, _ = schema.split_type(constant.type_text)
    if base in schema.INTEGER_TYPES:
        return int(value)
    if base in schema.FLOAT_TYPES:
        return float(value)
    if base == 'bool':
        return value == 'true'
    return value


@pytest.mark.parametrize('name', sorted(DEFS))
def test_generated_fields_match_definition(name):
    iface = DEFS[name]
    for part, cls in enumerate(_parts(iface)):
        generated = set(cls.get_fields_and_field_types())
        written = {item.name for item in iface.sections[part].fields}
        assert generated == written, '{}: 생성 {} / 정의 {}'.format(
            iface.label(part), sorted(generated), sorted(written))


@pytest.mark.parametrize('name', sorted(DEFS))
def test_generated_constants_match_definition(name):
    iface = DEFS[name]
    for part, cls in enumerate(_parts(iface)):
        for constant in iface.sections[part].constants:
            assert getattr(cls, constant.name) == _expected_value(constant), '{}.{}'.format(
                iface.label(part), constant.name)


def test_fencing_field_types():
    from cobot_interfaces.msg import CommandHeader, FleetCommand, RobotStatus
    header = CommandHeader.get_fields_and_field_types()
    assert header['epoch'] == 'uint32'
    assert header['seq'] == 'uint64'
    assert header['ttl_ms'] == 'uint32'
    assert header['map_hash'] == 'string'
    assert header['sig'] == 'string'
    assert FleetCommand.get_fields_and_field_types()['header'].endswith('CommandHeader')
    status = RobotStatus.get_fields_and_field_types()
    assert status['epoch_accepted'] == 'uint32'
    assert status['robot_boot_id'] == 'string'


def test_default_command_is_not_valid():
    # 빈 명령은 검증을 통과할 수 없어야 한다: 서명 없음, 유효 기한 0.
    from cobot_interfaces.msg import ArmCommand, FleetCommand
    command = FleetCommand()
    assert command.header.sig == ''
    assert command.header.ttl_ms == 0
    assert command.header.epoch == 0
    assert ArmCommand().command == ArmCommand.CMD_HOLD


def test_serialization_round_trip():
    # C 타입 지원 라이브러리까지 실제로 불러지는지 본다.
    from cobot_interfaces.msg import FleetCommand, MapInfo, Waypoint
    command = FleetCommand()
    command.command = FleetCommand.CMD_STOP
    command.header.robot_id = 'pinky_1'
    command.header.epoch = 3
    command.header.seq = 42
    restored = deserialize_message(serialize_message(command), FleetCommand)
    assert restored.command == FleetCommand.CMD_STOP
    assert restored.header.epoch == 3
    assert restored.header.seq == 42
    info = MapInfo()
    info.waypoints = [Waypoint(waypoint_id='WP_LOAD_1', approach_x=1.0)]
    restored_info = deserialize_message(serialize_message(info), MapInfo)
    assert restored_info.waypoints[0].waypoint_id == 'WP_LOAD_1'
    assert restored_info.waypoints[0].approach_x == 1.0
