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

"""관제 ArmCommand 헤더 판정과 켜기·끄기 상태 흐름."""

from cobot_interfaces.msg import ArmCommand, CommandAck
from cobot_manipulation import arm_power_utils as power
import pytest

NOW = 1_000_000.0


def header(**overrides):
    base = {'command_id': 'c1', 'robot_id': 'omx_1', 'epoch': 1, 'seq': 1,
            'issued_at': NOW, 'ttl_ms': 5000}
    base.update(overrides)
    return base


def test_numbers_match_interfaces():
    """번호는 cobot_interfaces 가 정본이다. 바뀌면 여기서 걸린다."""
    assert (power.CMD_HOLD, power.CMD_RELEASE_HOLD, power.CMD_RESET, power.CMD_START,
            power.CMD_SOFT_LATCH) == (ArmCommand.CMD_HOLD, ArmCommand.CMD_RELEASE_HOLD,
                                      ArmCommand.CMD_RESET, ArmCommand.CMD_START,
                                      ArmCommand.CMD_SOFT_LATCH)
    assert (power.ACCEPTED, power.REJECTED_EPOCH, power.REJECTED_SEQ, power.REJECTED_TTL,
            power.REJECTED_STATE, power.REJECTED_ROBOT_ID) == (
        CommandAck.ACCEPTED, CommandAck.REJECTED_EPOCH, CommandAck.REJECTED_SEQ,
        CommandAck.REJECTED_TTL, CommandAck.REJECTED_STATE, CommandAck.REJECTED_ROBOT_ID)


@pytest.mark.parametrize('name, expected', [
    ('omx1', 'omx_1'), ('omx_2', 'omx_2'), ('omx12', 'omx_12'), ('weird-name', 'weird-name')])
def test_interface_arm_id(name, expected):
    assert power.interface_arm_id(name) == expected


def test_start_needs_new_epoch_then_others_need_same_epoch_and_rising_seq():
    gate = power.CommandGate('omx_1')
    assert gate.check(header(), power.CMD_RESET, NOW)[0] == power.REJECTED_EPOCH
    assert gate.check(header(), power.CMD_START, NOW)[0] == power.ACCEPTED
    gate.accept(header(), power.CMD_START)
    assert gate.epoch_accepted == 1
    assert gate.check(header(seq=2), power.CMD_START, NOW)[0] == power.REJECTED_EPOCH
    assert gate.check(header(seq=1), power.CMD_RESET, NOW)[0] == power.REJECTED_SEQ
    assert gate.check(header(seq=2, epoch=2), power.CMD_RESET, NOW)[0] == power.REJECTED_EPOCH
    assert gate.check(header(seq=2), power.CMD_RESET, NOW)[0] == power.ACCEPTED
    gate.accept(header(seq=2), power.CMD_RESET)
    assert gate.check(header(epoch=2, seq=1), power.CMD_START, NOW)[0] == power.ACCEPTED


@pytest.mark.parametrize('overrides, result', [
    ({'robot_id': 'omx_2'}, power.REJECTED_ROBOT_ID),
    ({'ttl_ms': 0}, power.REJECTED_TTL),
    ({'issued_at': NOW - 6}, power.REJECTED_TTL),
    ({'issued_at': NOW + 6}, power.REJECTED_TTL),
])
def test_header_rejections(overrides, result):
    assert power.CommandGate('omx_1').check(header(**overrides), power.CMD_START, NOW)[0] == result


@pytest.mark.parametrize('state, command, busy, backend, ok, todo', [
    (power.DISARMED, power.CMD_START, False, 'worker', True, 'connect'),
    (power.DISARMED, power.CMD_START, False, 'none', False, ''),
    (power.ARMED, power.CMD_START, False, 'worker', False, ''),
    (power.ARMED, power.CMD_RESET, False, 'worker', True, 'release'),
    (power.ARMED, power.CMD_RESET, True, 'worker', False, ''),
    (power.LATCHED, power.CMD_RESET, False, 'worker', True, 'release'),
    (power.FAULT, power.CMD_RESET, False, 'worker', True, 'clear'),
    (power.DISARMED, power.CMD_RESET, False, 'worker', False, ''),
    (power.CONNECTING, power.CMD_RESET, False, 'worker', False, ''),
    (power.RELEASING, power.CMD_RESET, False, 'worker', False, ''),
    (power.ARMED, power.CMD_RELEASE_HOLD, False, 'worker', True, 'release_hold'),
])
def test_decide(state, command, busy, backend, ok, todo):
    got_ok, reason, got_todo = power.decide(state, command, busy, backend)
    assert (got_ok, got_todo) == (ok, todo)
    assert bool(reason) is not ok
