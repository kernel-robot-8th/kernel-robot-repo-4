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

"""끄기(RESET) 의 ACK 시점: 실행기가 쉬는 자세로 옮기면 먼저 받아들였다고 한 번만 답한다."""

import time
from types import SimpleNamespace

from cobot_manipulation import arm_power_utils as power
from cobot_manipulation.arm_adapter_node import ArmAdapterNode


class Logger:

    def __init__(self):
        self.lines = []

    def info(self, text):
        self.lines.append(('info', text))

    warning = error = info


class Backend:
    """take_* 로 한 번씩 꺼내는 끄기 진행을 흉내낸다."""

    def __init__(self, moving=None, result=None, alive=True):
        self.moving, self.result, self.alive, self.dead = moving, result, alive, ''

    def take_release_moving(self):
        moving, self.moving = self.moving, None
        return moving

    def take_release(self):
        result, self.result = self.result, None
        return result

    def running(self):
        return self.alive

    def reset(self):
        self.alive = False


def node(backend):
    logger = Logger()
    fake = SimpleNamespace(
        arm_id='omx1', backend=backend, power=power.RELEASING, release_ok=False,
        release_acked=False, release_timeout_sec=5.0, acks=[],
        pending_reset=('ack', time.monotonic() + 5.0, power.ARMED),
        get_logger=lambda: logger)
    fake._ack = lambda ack, result, reason, stop: fake.acks.append((result, reason))
    fake._ack_release = lambda ack, result, reason: ArmAdapterNode._ack_release(
        fake, ack, result, reason)
    return fake


def tick(fake):
    ArmAdapterNode._tick_release(fake)


def test_move_then_release_acks_once_when_moving():
    backend = Backend(moving=12.0)
    fake = node(backend)
    tick(fake)
    assert fake.acks == [(power.ACCEPTED, '쉬는 자세로 이동 중 (약 12s), 도착하면 토크 끔')]
    assert fake.power == power.RELEASING
    assert fake.pending_reset[1] > time.monotonic() + 15.0   # 이동 시간 + 여유로 기한을 늘림
    backend.result, backend.alive = (True, ''), False
    tick(fake)
    assert fake.power == power.DISARMED and len(fake.acks) == 1


def test_move_then_blocked_returns_to_before_without_second_ack():
    backend = Backend(moving=3.0)
    fake = node(backend)
    tick(fake)
    backend.result = (False, '도착 못 함')
    tick(fake)
    assert fake.power == power.ARMED and len(fake.acks) == 1
    assert not fake.release_acked


def test_refuse_without_move_acks_rejection():
    fake = node(Backend(result=(False, '쉬는 자세가 아님')))
    tick(fake)
    assert fake.acks == [(power.REJECTED_STATE, '쉬는 자세가 아님')]
    assert fake.power == power.ARMED
