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
스키마 시험 (a): .msg/.srv/.action 글자를 읽어 계약을 본다. ROS 가 없어도 돈다.

로드맵 S1 출구 검사 2 의 시험이다. 같은 검사를 미병합 브랜치의 옛 fleet_msgs 사본에
돌리면 실패해야 한다 (음성 대조). 그래서 검사가 실패할 수 있는지도 이 파일에서 본다.

ROS 없이 돌리기 (레포 루트에서):
    python3 -m pytest src/cobot_interfaces/test/test_interface_schema.py
"""

import copy
import os

import interface_schema as schema
import pytest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(PKG_DIR, 'test', 'fixtures', 'fleet_msgs_9e51d4d')
DOC_PATH = os.path.join(os.path.dirname(os.path.dirname(PKG_DIR)), 'docs', 'fms_interfaces.md')


@pytest.fixture(scope='module')
def defs():
    return schema.load_package(PKG_DIR, schema.PACKAGE_NAME)


@pytest.fixture(scope='module')
def legacy():
    return schema.load_package(FIXTURE_DIR, schema.LEGACY_PACKAGE_NAME)


def _replace(defs, name, kind, edit):
    # 원본 글자를 고친 사본으로 바꾼 정의 묶음을 돌려준다 (돌연변이 시험용).
    path = os.path.join(PKG_DIR, kind, name + '.' + kind)
    text = edit(schema.read_text(path))
    changed = copy.deepcopy(defs)
    changed[name] = schema.parse_text(name, kind, text, path)
    return changed


def _drop_line(token):
    def edit(text):
        lines = text.splitlines()
        kept = [line for line in lines if token not in line]
        assert len(kept) == len(lines) - 1, '지울 줄이 정확히 하나여야 한다: ' + token
        return '\n'.join(kept) + '\n'
    return edit


def _assert_has(errors, *expected):
    for text in expected:
        assert any(text in error for error in errors), '기대한 오류가 없다: {}\n{}'.format(
            text, '\n'.join(errors))


def test_package_has_expected_files(defs):
    counts = {'msg': 0, 'srv': 0, 'action': 0}
    for iface in defs.values():
        counts[iface.kind] += 1
    # 파일을 더하거나 빼면 이 숫자와 docs/fms_interfaces.md 의 개수 줄을 같은 PR 에서 고친다.
    assert counts == {'msg': 30, 'srv': 5, 'action': 2}


def test_contract_passes(defs):
    errors = schema.check_contract(defs)
    assert errors == [], '\n'.join(errors)


def test_contract_fails_on_legacy_fleet_msgs(legacy):
    # 음성 대조: 옛 fleet_msgs 에는 펜싱 필드가 없어서 같은 검사가 실패해야 한다.
    errors = schema.check_contract(legacy)
    assert errors, '옛 fleet_msgs 에서도 계약 검사가 통과했다. 검사가 실패할 수 없는 상태다.'
    _assert_has(
        errors,
        'CommandHeader: 정의 없음',
        'FmsHeartbeat: 정의 없음',
        'CommandAck: 정의 없음',
        'CompletionEvidence: 정의 없음',
        'Waypoint: 정의 없음',
        'DeviceDiag: 정의 없음',
        'TopicDiag: 정의 없음',
        'NodeDiag: 정의 없음',
        'ReconcileItem: 정의 없음',
        'InventoryItem: 정의 없음',
        'FleetCommand: header 없음',
        'FleetCommand: 상수 CMD_RESET 없음',
        'RobotStatus: robot_boot_id 없음',
        'RobotStatus: epoch_accepted 없음',
        'RobotStatus: header 없음',
        'HandoverTask.Goal: header 없음',
        'HandoverTask.Result: retract_safe 없음',
        'HandoverTask.Feedback: 상수 STEP_RETRACTING 없음',
    )


def test_contract_catches_missing_command_header(defs):
    changed = _replace(defs, 'FleetCommand', 'msg', _drop_line('CommandHeader header'))
    _assert_has(schema.check_contract(changed), 'FleetCommand: header 없음')


def test_contract_catches_missing_epoch_inside_header(defs):
    changed = _replace(defs, 'CommandHeader', 'msg', _drop_line('uint32 epoch'))
    _assert_has(
        schema.check_contract(changed),
        'CommandHeader: epoch 없음',
        'FleetCommand: header.epoch 없음',
        'ArmCommand: header.epoch 없음',
        'HandoverTask.Goal: header.epoch 없음',
    )


def test_contract_catches_wrong_type(defs):
    changed = _replace(
        defs, 'CommandHeader', 'msg', lambda text: text.replace('uint64 seq ', 'uint32 seq '))
    _assert_has(schema.check_contract(changed), 'CommandHeader: seq 의 타입이 uint64')


def test_contract_catches_changed_constant(defs):
    changed = _replace(
        defs, 'FleetCommand', 'msg', lambda text: text.replace('CMD_RESET=8', 'CMD_RESET=11'))
    _assert_has(schema.check_contract(changed), 'FleetCommand: 상수 CMD_RESET 는 uint8 8')


def test_contract_catches_missing_robot_status_fields(defs):
    changed = _replace(defs, 'RobotStatus', 'msg', _drop_line('string robot_boot_id'))
    _assert_has(schema.check_contract(changed), 'RobotStatus: robot_boot_id 없음')


def test_missing_sub_message_is_caught(defs):
    changed = copy.deepcopy(defs)
    del changed['Waypoint']
    _assert_has(schema.check_contract(changed), 'Waypoint: 정의 없음')
    _assert_has(schema.check_style(changed), 'MapInfo: 필드 waypoints 의 타입 Waypoint[] 을 모른다')


def test_contract_forbids_dataset_summary(defs):
    # DatasetSummary 는 D12 결정 뒤에 넣는다.
    changed = copy.deepcopy(defs)
    changed['DatasetSummary'] = schema.parse_text('DatasetSummary', 'msg', 'string arm_id\n')
    _assert_has(schema.check_contract(changed), 'DatasetSummary: 아직 넣지 않는다')


def test_style_passes(defs):
    errors = schema.check_style(defs)
    assert errors == [], '\n'.join(errors)


def test_style_catches_bad_lines(defs):
    bad = '\n'.join((
        'float32 speed',
        'float64 distance  # 단위가 없다',
        'uint32 wait_ms  # [s] 이름과 단위가 다르다',
        'uint32 countMs  # [ms]',
        'uint8 bad_const=1',
        'string from  # 예약어',
        'geometry_msgs/Twist2 twist  # 없는 타입',
        'float64 offset 1.0  # [m] 기본값',
        'uint8 SOFT_ESTOP=1',
        'bool soft_estop',
        '',
    ))
    changed = copy.deepcopy(defs)
    changed['BadMessage'] = schema.parse_text('BadMessage', 'msg', bad)
    _assert_has(
        schema.check_style(changed),
        'BadMessage: 숫자 필드 speed 에 주석',
        'BadMessage: 실수 필드 distance 의 주석에 [단위] 가 없다',
        'BadMessage: wait_ms 는 주석에 [ms]',
        'BadMessage: 필드 countMs 는 snake_case',
        'BadMessage: 상수 bad_const 는 UPPER_SNAKE_CASE',
        'BadMessage: 필드 from 는 예약어',
        'BadMessage: 필드 twist 의 타입 geometry_msgs/Twist2 을 모른다',
        'BadMessage: 필드 offset 에 기본값을 두지 않는다',
        'BadMessage: ESTOP 이 든 상수 SOFT_ESTOP',
        'BadMessage: estop 이 든 필드 soft_estop',
    )


def test_parser_reads_constants_and_comments_like_rosidl():
    iface = schema.parse_text('Sample', 'srv', '\n'.join((
        '# 파일 머리 주석',
        'string NAME_A="A=B"  # 상수 값 안의 = 는 값이다',
        'uint8 x  # [-] (= 주석 안의 = 는 무시)',
        '---',
        'string[] names',
        '',
    )))
    request, response = iface.sections
    assert [c.name for c in request.constants] == ['NAME_A']
    assert schema.constant_value(request.constants[0]) == 'A=B'
    assert [f.name for f in request.fields] == ['x']
    assert request.fields[0].comment.startswith('[-]')
    assert response.fields[0].type_text == 'string[]'
    with pytest.raises(ValueError):
        schema.parse_text('Broken', 'srv', 'string a\n')


def test_build_files_match(defs):
    errors = schema.check_build_files(PKG_DIR, defs)
    assert errors == [], '\n'.join(errors)


def test_build_files_catch_unlisted_interface(defs):
    changed = copy.deepcopy(defs)
    changed['Extra'] = schema.parse_text('Extra', 'msg', 'geometry_msgs/Vector3 v\n')
    del changed['DropEvent']
    _assert_has(
        schema.check_build_files(PKG_DIR, changed),
        'msg/Extra.msg 가 목록에 없다',
        'msg/DropEvent.msg 는 목록에 있는데 파일이 없다',
    )


def test_build_files_catch_missing_dependency(defs, tmp_path):
    for name in ('CMakeLists.txt', 'package.xml'):
        text = schema.read_text(os.path.join(PKG_DIR, name))
        if name == 'package.xml':
            text = text.replace('<depend>geometry_msgs</depend>', '')
        (tmp_path / name).write_text(text, encoding='utf-8')
    _assert_has(
        schema.check_build_files(str(tmp_path), defs),
        'package.xml: <depend>geometry_msgs</depend> 가 없다',
    )


def test_build_files_catch_unregistered_lint(defs, tmp_path):
    # ament_flake8 처럼 적으면 린트가 colcon test 에 등록되지 않는다 (S1 Jazzy 검증에서 찾음).
    for name in ('CMakeLists.txt', 'package.xml'):
        text = schema.read_text(os.path.join(PKG_DIR, name))
        if name == 'package.xml':
            assert '<test_depend>ament_cmake_flake8</test_depend>' in text
            text = text.replace('ament_cmake_flake8', 'ament_flake8')
        (tmp_path / name).write_text(text, encoding='utf-8')
    _assert_has(
        schema.check_build_files(str(tmp_path), defs),
        'package.xml: 린트 <test_depend>ament_cmake_flake8</test_depend> 가 없다',
        'package.xml: ament_flake8 는 ament_cmake 패키지에서 시험으로 등록되지 않는다',
    )


def test_attribution_present():
    errors = schema.check_attribution(PKG_DIR)
    assert errors == [], '\n'.join(errors)


def test_attribution_check_can_fail(tmp_path):
    (tmp_path / 'package.xml').write_text(
        '<package><license>Apache-2.0</license></package>', encoding='utf-8')
    _assert_has(
        schema.check_attribution(str(tmp_path)),
        'package.xml: 원저작 표기 team11 가 없다',
        'NOTICE: 원저작 표기 pinky_fleet_msgs 가 없다',
    )


def test_legacy_fixture_is_unmodified_snapshot_copy():
    errors = schema.check_fixture_hashes(FIXTURE_DIR)
    assert errors == [], '\n'.join(errors)
    # 해시 검사가 실패할 수 있는지: 1바이트만 달라도 값이 달라야 한다.
    original = schema.read_text(os.path.join(FIXTURE_DIR, 'msg', 'FleetCommand.msg'))
    expected = schema.LEGACY_SHA256['FleetCommand.msg']
    assert schema.lf_sha256(original.encode('utf-8')) == expected
    assert schema.lf_sha256((original + ' ').encode('utf-8')) != expected


def test_v1_fields_kept_or_renamed(defs, legacy):
    errors = schema.check_v1_carryover(legacy, defs)
    assert errors == [], '\n'.join(errors)


def test_v1_check_catches_dropped_field(defs, legacy):
    changed = _replace(defs, 'RobotStatus', 'msg', _drop_line('float32 battery_percentage'))
    _assert_has(
        schema.check_v1_carryover(legacy, changed),
        'RobotStatus: v1 필드 battery_percentage 가 사라졌다',
    )
    changed = _replace(
        defs, 'DropEvent', 'msg',
        lambda text: text.replace('float32 confidence', 'float64 confidence'))
    _assert_has(
        schema.check_v1_carryover(legacy, changed),
        'DropEvent: 그대로 옮기기로 한 정의의 필드가 바뀌었다',
    )


def test_every_interface_is_documented(defs):
    # 인터페이스를 바꾸면 docs/fms_interfaces.md 도 같은 PR 에서 고친다 (CLAUDE.md §4-2).
    assert os.path.isfile(DOC_PATH), '문서가 없다: docs/fms_interfaces.md'
    text = schema.read_text(DOC_PATH)
    missing = sorted(name for name in defs if '`{}`'.format(name) not in text)
    assert missing == [], '문서에 없는 인터페이스: ' + ', '.join(missing)
