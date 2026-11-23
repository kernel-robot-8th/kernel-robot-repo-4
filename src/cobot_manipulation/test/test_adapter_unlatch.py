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

"""잠금(SOFT_LATCH)은 관제 CMD_UNLATCH 로만 풀리고, 작업 토픽 release_hold 로는 안 풀린다."""

import json
import time
from types import SimpleNamespace

from cobot_manipulation import arm_power_utils as power
from cobot_manipulation import arm_registry_utils as registry_utils
from cobot_manipulation import work_contract_utils as contract
from cobot_manipulation.arm_adapter_node import ArmAdapterNode


class Logger:

    def __init__(self):
        self.lines = []

    def info(self, text):
        self.lines.append(text)

    warning = error = info


class Backend:
    name = 'fake'

    def __init__(self):
        self.started, self.calls = [], []

    def hold(self, now):
        self.calls.append('hold')
        return []

    def release_hold(self, now):
        self.calls.append('release_hold')

    def busy(self):
        return False

    def start(self, request, port, now):
        self.started.append(request['action'])
        return ''


class Clock:

    def now(self):
        return SimpleNamespace(to_msg=lambda: None)


def node():
    logger = Logger()
    fake = SimpleNamespace(
        arm_id='omx1', iid='omx_1', backend=Backend(), power=power.ARMED, held=False,
        state=registry_utils.READY, reason='', port='/dev/null', retract=(False, False),
        filter=contract.RequestFilter('omx1', 16), gate=power.CommandGate('omx_1'),
        acks=[], rejects=[], get_logger=lambda: logger, get_clock=Clock)
    fake.gate.epoch_accepted = 1
    fake._ack = lambda ack, result, reason, stop: fake.acks.append((result, reason))
    fake._reject = lambda request, detail, safe: fake.rejects.append(detail)
    fake._publish_finished = lambda finished, why: None
    fake._stop = lambda latch, why: ArmAdapterNode._stop(fake, latch, why)
    return fake


SEQ = {'command': 0, 'work': 0}


def command(fake, cmd):
    SEQ['command'] += 1
    header = SimpleNamespace(
        command_id=f'c{SEQ["command"]}', robot_id='omx_1', epoch=1, seq=SEQ['command'],
        ttl_ms=5000, issued_at=SimpleNamespace(sec=int(time.time()), nanosec=0))
    ArmAdapterNode._on_command(fake, SimpleNamespace(header=header, command=cmd))
    return fake.acks[-1]


def work(fake, action):
    SEQ['work'] += 1
    request = {'request_id': f'r{SEQ["work"]}', 'order_id': '', 'robot_id': 'pinky1',
               'target': 'omx1', 'stage': 'SAFETY' if 'hold' in action else 'LOAD',
               'action': action, 'session_id': 's1', 'seq': SEQ['work'],
               'issued_at': time.time(), 'ttl_sec': 5.0}
    ArmAdapterNode._on_request(fake, SimpleNamespace(data=json.dumps(request)))


def test_release_hold_does_not_unlatch_but_unlatch_does():
    fake = node()
    assert command(fake, power.CMD_SOFT_LATCH)[0] == power.ACCEPTED
    assert fake.power == power.LATCHED
    work(fake, 'release_hold')                      # fleet_control 자동 흐름
    work(fake, 'load')
    assert fake.power == power.LATCHED and fake.backend.started == []
    assert fake.rejects[-1] == '팔 전원 LATCHED (잠금 해제(CMD_UNLATCH) 필요)'
    assert command(fake, power.CMD_UNLATCH) == (power.ACCEPTED, '')
    assert fake.power == power.ARMED and fake.backend.calls[-1] == 'release_hold'
    work(fake, 'load')
    assert fake.backend.started == ['load']


def test_unlatch_also_clears_plain_hold():
    """전체 비상정지는 잠금 + fleet 의 hold 가 함께 온다. 잠금 해제 한 번으로 둘 다 풀린다."""
    fake = node()
    command(fake, power.CMD_SOFT_LATCH)
    work(fake, 'hold')                              # fleet_control 이 경로 팔에 보내는 정지
    assert fake.held and fake.power == power.LATCHED
    assert command(fake, power.CMD_UNLATCH)[0] == power.ACCEPTED
    assert fake.power == power.ARMED and not fake.held
    assert power.hold_status(fake.power, fake.held) == (False, '')
    work(fake, 'load')
    assert fake.backend.started == ['load']


def test_unlatch_rejected_when_not_latched():
    fake = node()
    result, reason = command(fake, power.CMD_UNLATCH)
    assert result == power.REJECTED_STATE and 'LATCHED' in reason
    assert fake.power == power.ARMED
