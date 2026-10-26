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
cobot_interfaces 의 .msg/.srv/.action 글자를 읽고 계약을 검사한다.

ROS 없이 돈다. 시험 파일 두 개(test_interface_schema.py, test_generated_types.py)가
같이 쓰는 도우미다. 동작 코드가 아니라 검사 코드다.

줄을 나누는 규칙은 rosidl 과 같다. 주석(#)을 먼저 떼고, 남은 줄에 '=' 가 있으면 상수,
없으면 필드다. 검사 함수는 오류 문자열 목록을 돌려준다. 빈 목록이면 통과다.
"""

from dataclasses import dataclass, field
import hashlib
import os
import re
from xml.etree import ElementTree

PACKAGE_NAME = 'cobot_interfaces'

# 종류별 부분 수와 이름. srv 는 요청·응답, action 은 목표·결과·피드백이다.
SECTION_NAMES = {
    'msg': ('',),
    'srv': ('Request', 'Response'),
    'action': ('Goal', 'Result', 'Feedback'),
}

PRIMITIVE_TYPES = (
    'bool', 'byte', 'char', 'float32', 'float64',
    'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64',
    'string', 'wstring',
)
FLOAT_TYPES = ('float32', 'float64')
INTEGER_TYPES = (
    'byte', 'char', 'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64',
)

# 다른 패키지의 타입은 이 목록에 있는 것만 쓴다.
# 더하려면 package.xml 의 depend 와 CMakeLists.txt 의 find_package·DEPENDENCIES 도 고친다.
EXTERNAL_TYPES = {
    'builtin_interfaces': ('Duration', 'Time'),
    'geometry_msgs': ('Point', 'Pose', 'PoseStamped', 'Quaternion', 'Twist', 'Vector3'),
    'std_msgs': ('Header',),
}

# rosidl 이 받는 이름 규칙.
INTERFACE_NAME_RE = re.compile(r'^[A-Z][A-Za-z0-9]*$')
FIELD_NAME_RE = re.compile(r'^(?!.*__)(?!.*_$)[a-z][a-z0-9_]*$')
CONSTANT_NAME_RE = re.compile(r'^[A-Z]([A-Z0-9_]?[A-Z0-9]+)*$')

# 생성 코드(Python, C, C++)나 IDL 에서 문제가 되는 이름. 필드 이름으로 쓰지 않는다.
RESERVED_NAMES = frozenset((
    'and', 'any', 'as', 'assert', 'async', 'auto', 'await', 'bool', 'break', 'case', 'catch',
    'char', 'class', 'component', 'const', 'context', 'continue', 'default', 'def', 'del',
    'delete', 'do', 'double', 'elif', 'else', 'enum', 'except', 'exception', 'explicit',
    'export', 'extern', 'false', 'finally', 'fixed', 'float', 'for', 'friend', 'from',
    'global', 'goto', 'home', 'if', 'import', 'in', 'inline', 'int', 'interface', 'is',
    'lambda', 'local', 'long', 'map', 'module', 'mutable', 'namespace', 'native', 'new',
    'none', 'nonlocal', 'not', 'object', 'octet', 'operator', 'or', 'out', 'pass', 'port',
    'private', 'protected', 'public', 'raise', 'register', 'return', 'sequence', 'short',
    'signed', 'sizeof', 'static', 'string', 'struct', 'switch', 'template', 'this',
    'throw', 'true', 'try', 'typedef', 'typename', 'union', 'unsigned', 'using',
    'virtual', 'void', 'volatile', 'while', 'with', 'yield',
))

# 이름 끝이 이것이면 주석에 그 단위 표기가 있어야 한다.
SUFFIX_UNITS = {
    '_ms': '[ms]',
    '_mm': '[mm]',
    '_deg': '[deg]',
    '_sec': '[s]',
    '_hz': '[Hz]',
    '_percent': '[%]',
}

# --- 계약 (설계 초안 §3.3~§3.6 의 펜싱·상태 필드, 로드맵 S1 출구 검사 2) ---

# 있어야 하는 인터페이스. 배열 원소용 서브 메시지 6종을 포함한다.
REQUIRED_INTERFACES = (
    'CommandHeader', 'FleetCommand', 'FmsHeartbeat', 'CommandAck', 'RobotStatus',
    'CompletionEvidence', 'FleetSafetyState', 'ArmStatus', 'ArmMode', 'ArmCommand',
    'LaneLeaseState', 'OrderStatus', 'Assignment', 'UnloadQueue', 'AlarmEvent',
    'CameraHealth', 'MediaHealth', 'VisionEvent', 'HwEstopState', 'DiagSnapshot',
    'MapInfo', 'InventoryState',
    'Waypoint', 'DeviceDiag', 'TopicDiag', 'NodeDiag', 'ReconcileItem', 'InventoryItem',
    'AuditEvent',
    'OperatorCommand', 'ConsoleLease', 'SubmitOrder', 'QueryAudit', 'ReconcileReport',
    'HandoverTask', 'RecoveryTask', 'DropEvent',
)

# colcon test 에 린트를 등록하는 test_depend (이 패키지는 ament_cmake 다).
LINT_TEST_DEPENDS = ('ament_cmake_copyright', 'ament_cmake_flake8', 'ament_cmake_pep257')

# 아직 넣지 않는 인터페이스. DatasetSummary 는 D12(PT-23 공식 도구) 결정 뒤에 넣는다.
FORBIDDEN_INTERFACES = ('DatasetSummary',)

# 명령 헤더를 싣는 곳. 헤더 안의 펜싱 필드까지 따라가서 본다.
_HEADER_FENCING = (
    ('command_id', 'string'),
    ('epoch', 'uint32'),
    ('seq', 'uint64'),
    ('issued_at', 'builtin_interfaces/Time'),
    ('ttl_ms', 'uint32'),
    ('map_hash', 'string'),
    ('key_id', 'string'),
    ('sig', 'string'),
)
_HEADER_CARRIERS = (('FleetCommand', 0), ('ArmCommand', 0), ('HandoverTask', 0))

# (인터페이스, 부분 번호, 필드 경로, 타입). 경로의 '.' 은 이 패키지 안의 타입을 따라간다.
REQUIRED_FIELDS = (
    ('CommandHeader', 0, 'command_id', 'string'),
    ('CommandHeader', 0, 'tx_id', 'string'),
    ('CommandHeader', 0, 'order_id', 'string'),
    ('CommandHeader', 0, 'task_id', 'string'),
    ('CommandHeader', 0, 'robot_id', 'string'),
    ('CommandHeader', 0, 'epoch', 'uint32'),
    ('CommandHeader', 0, 'seq', 'uint64'),
    ('CommandHeader', 0, 'issued_at', 'builtin_interfaces/Time'),
    ('CommandHeader', 0, 'ttl_ms', 'uint32'),
    ('CommandHeader', 0, 'map_hash', 'string'),
    ('CommandHeader', 0, 'issued_by', 'string'),
    ('CommandHeader', 0, 'key_id', 'string'),
    ('CommandHeader', 0, 'sig', 'string'),
    ('FleetCommand', 0, 'header', 'CommandHeader'),
    ('FleetCommand', 0, 'command', 'uint8'),
    ('FleetCommand', 0, 'lane_lease_id', 'string'),
    ('FleetCommand', 0, 'lease_valid_until', 'builtin_interfaces/Time'),
    ('ArmCommand', 0, 'header', 'CommandHeader'),
    ('ArmCommand', 0, 'command', 'uint8'),
    ('FmsHeartbeat', 0, 'robot_id', 'string'),
    ('FmsHeartbeat', 0, 'epoch', 'uint32'),
    ('FmsHeartbeat', 0, 'hb_seq', 'uint64'),
    ('FmsHeartbeat', 0, 'issued_at', 'builtin_interfaces/Time'),
    ('FmsHeartbeat', 0, 'ttl_ms', 'uint32'),
    ('FmsHeartbeat', 0, 'map_hash', 'string'),
    ('FmsHeartbeat', 0, 'fleet_mode', 'uint8'),
    ('FmsHeartbeat', 0, 'lane_lease_id', 'string'),
    ('FmsHeartbeat', 0, 'lease_valid_until', 'builtin_interfaces/Time'),
    ('FmsHeartbeat', 0, 'last_cmd_seq_issued', 'uint64'),
    ('FmsHeartbeat', 0, 'key_id', 'string'),
    ('FmsHeartbeat', 0, 'sig', 'string'),
    ('CommandAck', 0, 'command_id', 'string'),
    ('CommandAck', 0, 'robot_id', 'string'),
    ('CommandAck', 0, 'epoch', 'uint32'),
    ('CommandAck', 0, 'seq', 'uint64'),
    ('CommandAck', 0, 'result', 'uint8'),
    ('CommandAck', 0, 'stop_executed', 'bool'),
    ('CommandAck', 0, 'rx_to_ack_ms', 'uint32'),
    ('RobotStatus', 0, 'header', 'std_msgs/Header'),
    ('RobotStatus', 0, 'robot_id', 'string'),
    ('RobotStatus', 0, 'robot_boot_id', 'string'),
    ('RobotStatus', 0, 'state', 'string'),
    ('RobotStatus', 0, 'current_pose', 'geometry_msgs/Pose'),
    ('RobotStatus', 0, 'linear_vel', 'float32'),
    ('RobotStatus', 0, 'angular_vel', 'float32'),
    ('RobotStatus', 0, 'battery_percentage', 'float32'),
    ('RobotStatus', 0, 'motor_power_present', 'bool'),
    ('RobotStatus', 0, 'base_hold_engaged', 'bool'),
    ('RobotStatus', 0, 'hold_reason', 'string'),
    ('RobotStatus', 0, 'epoch_accepted', 'uint32'),
    ('RobotStatus', 0, 'last_seq_accepted', 'uint64'),
    ('RobotStatus', 0, 'last_heartbeat_seq', 'uint64'),
    ('RobotStatus', 0, 'last_heartbeat_rx_age_ms', 'uint32'),
    ('RobotStatus', 0, 'map_hash_loaded', 'string'),
    ('RobotStatus', 0, 'clock_offset_known', 'bool'),
    ('RobotStatus', 0, 'clock_offset_ms', 'int32'),
    ('RobotStatus', 0, 'nav2_action_clients', 'uint8'),
    ('CompletionEvidence', 0, 'header', 'std_msgs/Header'),
    ('CompletionEvidence', 0, 'evidence_id', 'string'),
    ('CompletionEvidence', 0, 'command_id', 'string'),
    ('CompletionEvidence', 0, 'task_id', 'string'),
    ('CompletionEvidence', 0, 'source_id', 'string'),
    ('CompletionEvidence', 0, 'kind', 'uint8'),
    ('CompletionEvidence', 0, 'satisfied', 'bool'),
    ('CompletionEvidence', 0, 'measured', 'bool'),
    ('FleetSafetyState', 0, 'run_state', 'string'),
    ('FleetSafetyState', 0, 'hw_estop', 'string'),
    ('FleetSafetyState', 0, 'hw_estop_source', 'string'),
    ('FleetSafetyState', 0, 'power_lost_targets', 'string[]'),
    ('FleetSafetyState', 0, 'latched_targets', 'string[]'),
    ('FleetSafetyState', 0, 'epoch_targets', 'string[]'),
    ('FleetSafetyState', 0, 'epochs', 'uint32[]'),
    ('FleetSafetyState', 0, 'allowed_actions', 'string[]'),
    ('ArmStatus', 0, 'robot_boot_id', 'string'),
    ('ArmStatus', 0, 'epoch_accepted', 'uint32'),
    ('ArmStatus', 0, 'retract_safe', 'bool'),
    ('ArmStatus', 0, 'retract_safe_measured', 'bool'),
    ('ArmStatus', 0, 'hold_active', 'bool'),
    ('ArmStatus', 0, 'power_present', 'bool'),
    ('ArmStatus', 0, 'work_step', 'string'),
    ('ArmMode', 0, 'mode', 'string'),
    ('HandoverTask', 0, 'header', 'CommandHeader'),
    ('HandoverTask', 0, 'robot_id', 'string'),
    ('HandoverTask', 0, 'waypoint_id', 'string'),
    ('HandoverTask', 1, 'retract_safe', 'bool'),
    ('HandoverTask', 1, 'load_confirmed', 'bool'),
    ('HandoverTask', 1, 'evidence_ids', 'string[]'),
    ('HandoverTask', 2, 'step', 'string'),
    ('LaneLeaseState', 0, 'state', 'string'),
    ('LaneLeaseState', 0, 'lease_id', 'string'),
    ('LaneLeaseState', 0, 'epoch', 'uint32'),
    ('LaneLeaseState', 0, 'valid_until', 'builtin_interfaces/Time'),
    ('LaneLeaseState', 0, 'exit_space_ok', 'bool'),
    ('LaneLeaseState', 0, 'tail_exit_evidence_id', 'string'),
    ('HwEstopState', 0, 'state', 'string'),
    ('HwEstopState', 0, 'source_device', 'string'),
    ('CameraHealth', 0, 'age_basis', 'string'),
    ('CameraHealth', 0, 'source_kind', 'string'),
    ('VisionEvent', 0, 'capture_stamp', 'builtin_interfaces/Time'),
    ('VisionEvent', 0, 'age_basis', 'string'),
    ('MapInfo', 0, 'map_hash', 'string'),
    ('MapInfo', 0, 'waypoints', 'Waypoint[]'),
    ('Waypoint', 0, 'waypoint_id', 'string'),
    ('Waypoint', 0, 'work_x', 'float64'),
    ('Waypoint', 0, 'work_y', 'float64'),
    ('Waypoint', 0, 'work_yaw', 'float64'),
    ('Waypoint', 0, 'approach_x', 'float64'),
    ('Waypoint', 0, 'approach_y', 'float64'),
    ('Waypoint', 0, 'approach_yaw', 'float64'),
    ('DiagSnapshot', 0, 'devices', 'DeviceDiag[]'),
    ('DiagSnapshot', 0, 'topics', 'TopicDiag[]'),
    ('DiagSnapshot', 0, 'nodes', 'NodeDiag[]'),
    ('DeviceDiag', 0, 'ros_domain_id_reported', 'int16'),
    ('DiagSnapshot', 0, 'ros_domain_id_configured', 'int16'),
    ('TopicDiag', 0, 'publishers', 'uint16'),
    ('TopicDiag', 0, 'single_writer_state', 'string'),
    ('NodeDiag', 0, 'alive', 'bool'),
    ('InventoryState', 0, 'items', 'InventoryItem[]'),
    ('InventoryItem', 0, 'qty_reserved', 'uint32'),
    ('OperatorCommand', 0, 'client_request_id', 'string'),
    ('OperatorCommand', 0, 'op', 'string'),
    ('OperatorCommand', 0, 'scope', 'string'),
    ('OperatorCommand', 0, 'console_token', 'string'),
    ('OperatorCommand', 0, 'approval_ref', 'string'),
    ('OperatorCommand', 0, 'attest', 'string[]'),
    ('OperatorCommand', 0, 'gw_nonce', 'string'),
    ('OperatorCommand', 0, 'gw_sig', 'string'),
    ('OperatorCommand', 1, 'result', 'string'),
    ('OperatorCommand', 1, 'reject_code', 'string'),
    ('OperatorCommand', 1, 'command_ids', 'string[]'),
    ('ConsoleLease', 0, 'op', 'string'),
    ('ConsoleLease', 0, 'gw_sig', 'string'),
    ('ConsoleLease', 1, 'granted', 'bool'),
    ('ConsoleLease', 1, 'console_token', 'string'),
    ('SubmitOrder', 0, 'idempotency_key', 'string'),
    ('SubmitOrder', 0, 'gw_sig', 'string'),
    ('SubmitOrder', 1, 'order_id', 'string'),
    ('SubmitOrder', 1, 'duplicate', 'bool'),
    ('QueryAudit', 1, 'events', 'AuditEvent[]'),
    ('QueryAudit', 1, 'chain_ok', 'bool'),
    ('ReconcileReport', 1, 'items', 'ReconcileItem[]'),
    ('ReconcileReport', 1, 'report_hash', 'string'),
    ('ReconcileItem', 0, 'target_id', 'string'),
    ('ReconcileItem', 0, 'observed', 'string'),
    ('ReconcileItem', 0, 'matched', 'bool'),
    ('AuditEvent', 0, 'seq', 'uint64'),
    ('AuditEvent', 0, 'row_hash', 'string'),
) + tuple(
    (name, part, 'header.' + fld, kind)
    for name, part in _HEADER_CARRIERS
    for fld, kind in _HEADER_FENCING
)

# (인터페이스, 부분 번호, 상수 이름, 타입, 값). 문자열 값은 따옴표 없이 적는다.
REQUIRED_CONSTANTS = (
    ('FleetCommand', 0, 'CMD_GOTO', 'uint8', '0'),
    ('FleetCommand', 0, 'CMD_STOP', 'uint8', '1'),
    ('FleetCommand', 0, 'CMD_RESUME', 'uint8', '2'),
    ('FleetCommand', 0, 'CMD_CANCEL', 'uint8', '3'),
    ('FleetCommand', 0, 'CMD_SET_INITIAL_POSE', 'uint8', '4'),
    ('FleetCommand', 0, 'CMD_SET_SPEED', 'uint8', '5'),
    ('FleetCommand', 0, 'CMD_SET_MAP', 'uint8', '6'),
    ('FleetCommand', 0, 'CMD_HEARTBEAT', 'uint8', '7'),
    ('FleetCommand', 0, 'CMD_RESET', 'uint8', '8'),
    ('FleetCommand', 0, 'CMD_START', 'uint8', '9'),
    ('FleetCommand', 0, 'CMD_SOFT_LATCH', 'uint8', '10'),
    ('ArmCommand', 0, 'CMD_HOLD', 'uint8', '0'),
    ('ArmCommand', 0, 'CMD_RESET', 'uint8', '2'),
    ('ArmCommand', 0, 'CMD_START', 'uint8', '3'),
    ('ArmCommand', 0, 'CMD_SOFT_LATCH', 'uint8', '4'),
    ('FmsHeartbeat', 0, 'MODE_RUN', 'uint8', '0'),
    ('FmsHeartbeat', 0, 'MODE_PAUSE', 'uint8', '1'),
    ('FmsHeartbeat', 0, 'MODE_SOFT_LATCH', 'uint8', '2'),
    ('FmsHeartbeat', 0, 'MODE_DISARMED', 'uint8', '3'),
    ('CommandAck', 0, 'ACCEPTED', 'uint8', '0'),
    ('CommandAck', 0, 'REJECTED_EPOCH', 'uint8', '1'),
    ('CommandAck', 0, 'REJECTED_SEQ', 'uint8', '2'),
    ('CommandAck', 0, 'REJECTED_TTL', 'uint8', '3'),
    ('CommandAck', 0, 'REJECTED_MAP_HASH', 'uint8', '4'),
    ('CommandAck', 0, 'REJECTED_STATE', 'uint8', '5'),
    ('CommandAck', 0, 'REJECTED_ROBOT_ID', 'uint8', '6'),
    ('CommandAck', 0, 'REJECTED_CLOCK_UNSYNCED', 'uint8', '7'),
    ('CommandAck', 0, 'REJECTED_SIGNATURE', 'uint8', '8'),
    ('RobotStatus', 0, 'STATE_PAUSED', 'string', 'PAUSED'),
    ('RobotStatus', 0, 'STATE_HOLD', 'string', 'HOLD'),
    ('RobotStatus', 0, 'STATE_DISARMED', 'string', 'DISARMED'),
    ('RobotStatus', 0, 'STATE_SOFT_LATCH', 'string', 'SOFT_LATCH'),
    ('RobotStatus', 0, 'STATE_LINK_LOST', 'string', 'LINK_LOST'),
    ('RobotStatus', 0, 'STATE_RECOVERING', 'string', 'RECOVERING'),
    ('RobotStatus', 0, 'HOLD_REASON_WATCHDOG', 'string', 'WATCHDOG'),
    ('CompletionEvidence', 0, 'ENCODER_VEL_ZERO', 'uint8', '0'),
    ('CompletionEvidence', 0, 'BASE_HOLD_ENGAGED', 'uint8', '1'),
    ('CompletionEvidence', 0, 'ARM_RETRACT_SAFE', 'uint8', '2'),
    ('CompletionEvidence', 0, 'LOAD_SENSOR_PRESENT', 'uint8', '3'),
    ('CompletionEvidence', 0, 'GRIPPER_HOLD_OK', 'uint8', '4'),
    ('CompletionEvidence', 0, 'TAIL_EXIT_CONFIRMED', 'uint8', '5'),
    ('CompletionEvidence', 0, 'ZONE_PRESENT', 'uint8', '6'),
    ('FleetSafetyState', 0, 'RUN_STATE_SOFT_LATCH', 'string', 'SOFT_LATCH'),
    ('FleetSafetyState', 0, 'HW_ESTOP_UNKNOWN', 'string', 'UNKNOWN'),
    ('LaneLeaseState', 0, 'STATE_UNKNOWN_BLOCKED', 'string', 'UNKNOWN_BLOCKED'),
    ('HwEstopState', 0, 'STATE_UNKNOWN', 'string', 'UNKNOWN'),
    ('CameraHealth', 0, 'AGE_BASIS_RECEIVE', 'string', 'RECEIVE'),
    ('HandoverTask', 2, 'STEP_RETRACTING', 'string', 'RETRACTING'),
    ('HandoverTask', 2, 'STEP_VERIFYING', 'string', 'VERIFYING'),
    ('ArmStatus', 0, 'WORK_STEP_RETRACTING', 'string', 'RETRACTING'),
    ('OperatorCommand', 1, 'REJECT_BAD_SIGNATURE', 'string', 'BAD_SIGNATURE'),
    ('OperatorCommand', 1, 'REJECT_ATTEST_MISMATCH', 'string', 'ATTEST_MISMATCH'),
    ('OperatorCommand', 1, 'REJECT_APPROVAL_DWELL', 'string', 'APPROVAL_DWELL'),
)

# --- v1(fleet_msgs) 에서 옮긴 것 ---

# 옛 정의 사본의 출처. 미병합 브랜치 feature/setup-fleet-msgs-structure 의 커밋 9e51d4d.
LEGACY_SNAPSHOT = '9e51d4d'
LEGACY_PACKAGE_NAME = 'fleet_msgs'
LEGACY_SHA256 = {
    'DropEvent.msg': 'b677aa92ad5f3bd19afdefc076c4675f0708cc64a07137f7f9c0bc32850fd7d8',
    'FleetCommand.msg': '4d7344703205656c2204fff2e8751fadaae2adf316fec0c96d74c37ebfc865b9',
    'RobotStatus.msg': '75349fc9f1cf6ab9f377b46d2af0c7357cf2b0d4c5d2e225757ce3c9134cfd50',
    'HandoverTask.action': 'f936fdf10a39d8672a21454e044cee52137ccad4e26817165875a10c23e6d78a',
    'RecoveryTask.action': '0867d4721c555612c8862466b18561d23b32088f3f61155f99a5b0447bec31ee',
}

# v1 필드가 v2 에 없으면 반드시 여기 적힌 이름 바꿈이어야 한다.
V1_RENAMED = {
    ('RobotStatus', 0, 'timestamp'): 'header',
    ('HandoverTask', 0, 'station_id'): 'waypoint_id',
    ('HandoverTask', 0, 'item_type'): 'sku',
}

# 필드까지 그대로 옮긴 것. SR-17 단계에서 다시 정의한다.
V1_UNCHANGED = ('DropEvent', 'RecoveryTask')


@dataclass
class Field:
    """필드 한 줄."""

    type_text: str
    name: str
    default: str
    comment: str
    line_no: int


@dataclass
class Constant:
    """상수 한 줄."""

    type_text: str
    name: str
    value: str
    comment: str
    line_no: int


@dataclass
class Section:
    """msg 하나, 또는 srv·action 의 한 부분."""

    fields: list = field(default_factory=list)
    constants: list = field(default_factory=list)

    def get_field(self, name):
        """이름이 같은 필드를 돌려준다. 없으면 None."""
        for item in self.fields:
            if item.name == name:
                return item
        return None

    def get_constant(self, name):
        """이름이 같은 상수를 돌려준다. 없으면 None."""
        for item in self.constants:
            if item.name == name:
                return item
        return None


@dataclass
class Interface:
    """인터페이스 파일 하나."""

    name: str
    kind: str
    sections: list
    path: str = ''

    def label(self, part):
        """오류 문구에 쓸 이름 (예: HandoverTask.Goal)."""
        suffix = SECTION_NAMES[self.kind][part]
        return self.name + ('.' + suffix if suffix else '')


def split_type(type_text):
    """배열 표기와 문자열 길이 제한을 떼고 (기본 타입, 배열 여부)를 돌려준다."""
    is_array = type_text.endswith(']')
    base = type_text.split('[', 1)[0]
    if base.startswith(('string<=', 'wstring<=')):
        base = base.split('<=', 1)[0]
    return base, is_array


def normalize_type(type_text, package_name):
    """같은 패키지 접두사를 뗀 타입 표기를 돌려준다 (cobot_interfaces/X -> X)."""
    prefix = package_name + '/'
    if type_text.startswith(prefix):
        return type_text[len(prefix):]
    return type_text


def local_type_name(base, package_name):
    """이 패키지 안의 타입이면 그 이름을, 아니면 None 을 돌려준다."""
    if base in PRIMITIVE_TYPES:
        return None
    if '/' in base:
        pkg, _, name = base.partition('/')
        return name if pkg == package_name else None
    return base


def constant_value(constant):
    """상수 값을 비교하기 좋게 돌려준다. 문자열은 바깥 따옴표를 뗀다."""
    value = constant.value
    if constant.type_text in ('string', 'wstring'):
        for quote in ('"', "'"):
            if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
                return value[1:-1]
    return value


def _parse_section(lines):
    section = Section()
    for line_no, raw in lines:
        line = raw.replace('\t', ' ').rstrip()
        comment = ''
        index = line.find('#')
        if index >= 0:
            comment = line[index + 1:].strip()
            line = line[:index].rstrip()
        if not line.strip():
            continue
        if line != line.lstrip():
            raise ValueError('줄 {}: 들여쓴 정의는 rosidl 이 읽지 못한다'.format(line_no))
        type_text, _, rest = line.partition(' ')
        rest = rest.strip()
        if not rest:
            raise ValueError('줄 {}: 이름이 없다: {!r}'.format(line_no, raw))
        if '=' in rest:
            name, _, value = rest.partition('=')
            section.constants.append(
                Constant(type_text, name.strip(), value.strip(), comment, line_no))
        else:
            name, _, default = rest.partition(' ')
            section.fields.append(Field(type_text, name, default.strip(), comment, line_no))
    return section


def parse_text(name, kind, text, path=''):
    """인터페이스 글자 하나를 읽어 Interface 로 돌려준다."""
    parts = [[]]
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() == '---':
            parts.append([])
            continue
        parts[-1].append((line_no, raw))
    expected = len(SECTION_NAMES[kind])
    if len(parts) != expected:
        raise ValueError('{}.{}: 부분 수가 {} 이어야 하는데 {} 이다'.format(
            name, kind, expected, len(parts)))
    return Interface(name, kind, [_parse_section(p) for p in parts], path)


def read_text(path):
    """UTF-8 로 읽는다. 줄 끝(CRLF/LF)은 splitlines 가 같게 다룬다."""
    with open(path, encoding='utf-8') as stream:
        return stream.read()


def load_package(pkg_dir, package_name):
    """패키지 폴더의 msg/ srv/ action/ 을 모두 읽어 {이름: Interface} 로 돌려준다."""
    defs = {}
    for kind in SECTION_NAMES:
        folder = os.path.join(pkg_dir, kind)
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(filename)
            if ext != '.' + kind:
                continue
            if stem in defs:
                raise ValueError('{}: 같은 이름이 두 번 있다'.format(stem))
            path = os.path.join(folder, filename)
            defs[stem] = parse_text(stem, kind, read_text(path), path)
    return defs


def find_field(defs, name, part, dotted, package_name=PACKAGE_NAME):
    """필드 경로를 따라가 (Field, 오류) 를 돌려준다. 찾으면 오류는 None 이다."""
    iface = defs.get(name)
    if iface is None:
        return None, '{}: 정의 없음'.format(name)
    if part >= len(iface.sections):
        return None, '{}: 부분 {} 없음'.format(name, part)
    section = iface.sections[part]
    steps = dotted.split('.')
    for depth, step in enumerate(steps):
        found = section.get_field(step)
        if found is None:
            return None, '{}: {} 없음'.format(iface.label(part), '.'.join(steps[:depth + 1]))
        if depth == len(steps) - 1:
            return found, None
        base, _ = split_type(found.type_text)
        inner = local_type_name(base, package_name)
        if inner is None or inner not in defs:
            return None, '{}: {} 의 타입 {} 을 이 패키지에서 찾을 수 없음'.format(
                iface.label(part), '.'.join(steps[:depth + 1]), found.type_text)
        section = defs[inner].sections[0]
    return None, '{}: 빈 경로'.format(name)


def check_contract(defs, package_name=PACKAGE_NAME):
    """설계 초안의 펜싱·상태 필드와 상수가 있는지 본다."""
    errors = []
    for name in REQUIRED_INTERFACES:
        if name not in defs:
            errors.append('{}: 정의 없음'.format(name))
    for name in FORBIDDEN_INTERFACES:
        if name in defs:
            errors.append('{}: 아직 넣지 않는다 (D12 결정 뒤)'.format(name))
    for name, part, dotted, kind in REQUIRED_FIELDS:
        found, error = find_field(defs, name, part, dotted, package_name)
        if error:
            if not error.endswith('정의 없음'):
                errors.append(error)
            continue
        actual = normalize_type(found.type_text, package_name)
        if actual != kind:
            errors.append('{}: {} 의 타입이 {} 이어야 하는데 {} 이다'.format(
                defs[name].label(part), dotted, kind, actual))
    for name, part, cname, kind, value in REQUIRED_CONSTANTS:
        iface = defs.get(name)
        if iface is None or part >= len(iface.sections):
            continue
        constant = iface.sections[part].get_constant(cname)
        if constant is None:
            errors.append('{}: 상수 {} 없음'.format(iface.label(part), cname))
            continue
        if constant.type_text != kind or constant_value(constant) != value:
            errors.append('{}: 상수 {} 는 {} {} 이어야 하는데 {} {} 이다'.format(
                iface.label(part), cname, kind, value, constant.type_text,
                constant_value(constant)))
    # 헤더가 없으면 header.* 경로마다 같은 오류가 나온다. 한 번만 남긴다.
    return list(dict.fromkeys(errors))


def _known_type(base, defs, package_name):
    if base in PRIMITIVE_TYPES:
        return True
    local = local_type_name(base, package_name)
    if local is not None:
        return local in defs
    pkg, _, name = base.partition('/')
    return name in EXTERNAL_TYPES.get(pkg, ())


def _unit_errors(label, item):
    base, _ = split_type(item.type_text)
    if base not in FLOAT_TYPES and base not in INTEGER_TYPES:
        return []
    if not item.comment:
        return ['{}: 숫자 필드 {} 에 주석(단위·뜻)이 없다'.format(label, item.name)]
    errors = []
    if base in FLOAT_TYPES and not re.search(r'\[[^\]]+\]', item.comment):
        errors.append('{}: 실수 필드 {} 의 주석에 [단위] 가 없다'.format(label, item.name))
    for suffix, unit in SUFFIX_UNITS.items():
        if item.name.endswith(suffix) and unit not in item.comment:
            errors.append('{}: {} 는 주석에 {} 가 있어야 한다'.format(label, item.name, unit))
    return errors


def _estop_errors(iface, label, section):
    # 'ESTOP' 이름은 HW 릴레이 전용이다. 소프트웨어 정지는 SOFT_LATCH 계열만 쓴다.
    errors = []
    for item in section.fields:
        if 'estop' in item.name and not item.name.startswith('hw_estop'):
            errors.append('{}: estop 이 든 필드 {} 는 hw_estop 으로 시작해야 한다'.format(
                label, item.name))
    for item in section.constants:
        if 'ESTOP' in item.name and not (
                iface.name == 'FleetSafetyState' and item.name.startswith('HW_ESTOP_')):
            errors.append('{}: ESTOP 이 든 상수 {} 는 HW 릴레이 전용 이름이다'.format(
                label, item.name))
    return errors


def check_style(defs, package_name=PACKAGE_NAME):
    """이름·주석·타입 규칙을 본다 (CLAUDE.md §3-4, §6)."""
    errors = []
    for iface in defs.values():
        if not INTERFACE_NAME_RE.match(iface.name):
            errors.append('{}: 파일 이름은 PascalCase'.format(iface.name))
        for part, section in enumerate(iface.sections):
            label = iface.label(part)
            seen = set()
            for item in section.fields + section.constants:
                if item.name in seen:
                    errors.append('{}: 이름 {} 가 두 번 있다'.format(label, item.name))
                seen.add(item.name)
            for item in section.fields:
                if not FIELD_NAME_RE.match(item.name):
                    errors.append('{}: 필드 {} 는 snake_case'.format(label, item.name))
                if item.name in RESERVED_NAMES:
                    errors.append('{}: 필드 {} 는 예약어라 쓰지 않는다'.format(label, item.name))
                if item.default:
                    errors.append('{}: 필드 {} 에 기본값을 두지 않는다'.format(label, item.name))
                base, _ = split_type(item.type_text)
                if not _known_type(base, defs, package_name):
                    errors.append('{}: 필드 {} 의 타입 {} 을 모른다'.format(
                        label, item.name, item.type_text))
                errors.extend(_unit_errors(label, item))
            for item in section.constants:
                if not CONSTANT_NAME_RE.match(item.name):
                    errors.append('{}: 상수 {} 는 UPPER_SNAKE_CASE'.format(label, item.name))
                if item.type_text not in PRIMITIVE_TYPES:
                    errors.append('{}: 상수 {} 의 타입 {} 은 기본 타입이어야 한다'.format(
                        label, item.name, item.type_text))
            errors.extend(_estop_errors(iface, label, section))
    return errors


def external_packages(defs, package_name=PACKAGE_NAME):
    """정의가 쓰는 다른 패키지 이름들."""
    used = set()
    for iface in defs.values():
        for section in iface.sections:
            for item in section.fields:
                base, _ = split_type(item.type_text)
                if '/' in base:
                    pkg = base.partition('/')[0]
                    if pkg != package_name:
                        used.add(pkg)
    if any(iface.kind == 'action' for iface in defs.values()):
        used.add('action_msgs')
    return used


def _lint_errors(test_deps):
    # ament_cmake 패키지에서는 ament_lint_auto 가 ament_cmake_* 이름만 시험으로 등록한다.
    # ament_flake8 처럼 적으면 경고 없이 빠져서, 린트가 돌지 않는데도 colcon test 가 통과한다.
    errors = []
    if 'ament_lint_auto' not in test_deps:
        errors.append('package.xml: <test_depend>ament_lint_auto</test_depend> 가 없다')
    for name in LINT_TEST_DEPENDS:
        if name not in test_deps:
            errors.append('package.xml: 린트 <test_depend>{}</test_depend> 가 없다'.format(name))
        bare = name.replace('ament_cmake_', 'ament_', 1)
        if bare in test_deps:
            errors.append(
                'package.xml: {} 는 ament_cmake 패키지에서 시험으로 등록되지 않는다. '
                '{} 로 적는다'.format(bare, name))
    return errors


def check_build_files(pkg_dir, defs, package_name=PACKAGE_NAME):
    """CMakeLists.txt·package.xml 이 정의 파일·의존성과 맞는지 본다 (CLAUDE.md §7)."""
    errors = []
    cmake = read_text(os.path.join(pkg_dir, 'CMakeLists.txt'))
    listed = set(re.findall(r'"((?:msg|srv|action)/[A-Za-z0-9_]+\.(?:msg|srv|action))"', cmake))
    on_disk = {'{0}/{1}.{0}'.format(iface.kind, iface.name) for iface in defs.values()}
    for path in sorted(on_disk - listed):
        errors.append('CMakeLists.txt: {} 가 목록에 없다'.format(path))
    for path in sorted(listed - on_disk):
        errors.append('CMakeLists.txt: {} 는 목록에 있는데 파일이 없다'.format(path))
    match = re.search(r'DEPENDENCIES([^)]*)\)', cmake)
    cmake_deps = set(match.group(1).split()) if match else set()
    found = set(re.findall(r'find_package\(\s*([A-Za-z0-9_]+)', cmake))
    root = ElementTree.parse(os.path.join(pkg_dir, 'package.xml')).getroot()
    xml_deps = {node.text.strip() for node in root.findall('depend') if node.text}
    for pkg in sorted(external_packages(defs, package_name)):
        if pkg not in cmake_deps:
            errors.append('CMakeLists.txt: DEPENDENCIES 에 {} 가 없다'.format(pkg))
        if pkg not in found:
            errors.append('CMakeLists.txt: find_package({}) 가 없다'.format(pkg))
        if pkg not in xml_deps:
            errors.append('package.xml: <depend>{}</depend> 가 없다'.format(pkg))
    test_deps = {node.text.strip() for node in root.findall('test_depend') if node.text}
    errors.extend(_lint_errors(test_deps))
    name = root.findtext('name', '').strip()
    if name != package_name:
        errors.append('package.xml: name 이 {} 이어야 하는데 {} 이다'.format(package_name, name))
    if 'rosidl_interface_packages' not in [
            node.text for node in root.findall('member_of_group')]:
        errors.append('package.xml: member_of_group rosidl_interface_packages 가 없다')
    return errors


def check_attribution(pkg_dir):
    """team11 pinky_fleet_msgs(Apache-2.0) 원저작 표기를 본다."""
    errors = []
    xml_path = os.path.join(pkg_dir, 'package.xml')
    notice_path = os.path.join(pkg_dir, 'NOTICE')
    xml_text = read_text(xml_path) if os.path.isfile(xml_path) else ''
    notice = read_text(notice_path) if os.path.isfile(notice_path) else ''
    if '<license>Apache-2.0</license>' not in xml_text:
        errors.append('package.xml: license 가 Apache-2.0 이 아니다')
    for word in ('team11', 'pinky_fleet_msgs'):
        if word not in xml_text:
            errors.append('package.xml: 원저작 표기 {} 가 없다'.format(word))
        if word not in notice:
            errors.append('NOTICE: 원저작 표기 {} 가 없다'.format(word))
    if 'Apache' not in notice:
        errors.append('NOTICE: Apache 라이선스 표기가 없다')
    return errors


def lf_sha256(data):
    """CRLF 를 LF 로 바꾼 바이트의 sha256 (Windows 의 autocrlf 체크아웃 대비)."""
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def check_fixture_hashes(fixture_dir):
    """옛 정의 사본이 스냅샷 9e51d4d 의 파일과 같은지 본다."""
    errors = []
    for filename, expected in sorted(LEGACY_SHA256.items()):
        kind = os.path.splitext(filename)[1][1:]
        path = os.path.join(fixture_dir, kind, filename)
        if not os.path.isfile(path):
            errors.append('{}/{}: 사본이 없다'.format(kind, filename))
            continue
        with open(path, 'rb') as stream:
            actual = lf_sha256(stream.read())
        if actual != expected:
            errors.append('{}/{}: 스냅샷 {} 과 내용이 다르다'.format(
                kind, filename, LEGACY_SNAPSHOT))
    return errors


def check_v1_carryover(old_defs, new_defs, package_name=PACKAGE_NAME):
    """v1 필드·상수가 v2 에 남았는지, 없어진 것은 기록된 이름 바꿈인지 본다."""
    errors = []
    for name, old in sorted(old_defs.items()):
        new = new_defs.get(name)
        if new is None:
            errors.append('{}: v1 정의가 v2 에서 사라졌다'.format(name))
            continue
        for part, old_section in enumerate(old.sections):
            label = new.label(part)
            new_section = new.sections[part]
            if name in V1_UNCHANGED:
                old_shape = [(f.type_text, f.name) for f in old_section.fields]
                new_shape = [(f.type_text, f.name) for f in new_section.fields]
                if old_shape != new_shape:
                    errors.append('{}: 그대로 옮기기로 한 정의의 필드가 바뀌었다'.format(label))
            for item in old_section.fields:
                target = V1_RENAMED.get((name, part, item.name), item.name)
                found = new_section.get_field(target)
                if found is None:
                    errors.append('{}: v1 필드 {} 가 사라졌다 (V1_RENAMED 에도 없음)'.format(
                        label, item.name))
                elif target == item.name and normalize_type(
                        found.type_text, package_name) != item.type_text:
                    errors.append('{}: v1 필드 {} 의 타입이 바뀌었다'.format(label, item.name))
            for item in old_section.constants:
                found = new_section.get_constant(item.name)
                if found is None or constant_value(found) != constant_value(item):
                    errors.append('{}: v1 상수 {} 의 값이 바뀌었거나 없다'.format(
                        label, item.name))
    return errors
