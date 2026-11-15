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
관제 ArmCommand 로 팔을 켜고 끄는 상태 흐름 (ROS 없는 순수 로직).

명령 번호·판정 번호는 cobot_interfaces 의 ArmCommand·CommandAck 와 같다 (그 파일이 정본).
노드가 메시지를 dict 로 바꿔 넘기므로 여기서는 ROS 타입을 쓰지 않는다.

전원 상태
  DISARMED   팔 연결 없음. 토크 없음. 노드는 이 상태로 시작한다 (auto_start=false).
  CONNECTING CMD_START 를 받아 실행기가 팔에 연결하고 모델을 불러오는 중.
  ARMED      일을 받는다.
  LATCHED    CMD_SOFT_LATCH 로 멈춘 상태. 토크는 유지. CMD_RESET 으로만 풀린다.
  RELEASING  CMD_RESET 을 받아 실행기가 쉬는 자세인지 보고 연결을 끊는 중.
  FAULT      실행기가 죽음. 팔 상태 모름. CMD_RESET 으로 DISARMED 로 돌아간다.

정지(HOLD)는 전원 상태와 따로 든다. CMD_HOLD·hold 요청으로 걸고 CMD_RELEASE_HOLD·release_hold 로 푼다.
다만 꺼지면(DISARMED) 지운다 (keep_hold). 토크 없는 팔에는 멈출 동작이 없고, 남겨 두면 꺼진 팔이
'정지' 로 보이고 다시 켠 뒤에도 일을 거절한다. 다시 켠 뒤에도 멈춰야 하면 관제가 HOLD 를 다시 보낸다.

관제는 팔 모션을 시작하지 않는다 (ArmCommand.msg). 그래서 끄기(RESET)는 팔을 옮기지 않고,
지금 자세가 쉬는 자세일 때만 실행기가 연결을 끊는다. 아니면 거절한다.
"""

import re

# ArmCommand.CMD_*
CMD_HOLD, CMD_RELEASE_HOLD, CMD_RESET, CMD_START, CMD_SOFT_LATCH = 0, 1, 2, 3, 4
COMMAND_NAMES = {CMD_HOLD: 'HOLD', CMD_RELEASE_HOLD: 'RELEASE_HOLD', CMD_RESET: 'RESET',
                 CMD_START: 'START', CMD_SOFT_LATCH: 'SOFT_LATCH'}
# 정지 계열은 판정이 거부여도 정지한다 (ArmCommand.msg, D4)
STOP_COMMANDS = frozenset({CMD_HOLD, CMD_SOFT_LATCH})

# CommandAck.result
ACCEPTED, REJECTED_EPOCH, REJECTED_SEQ, REJECTED_TTL = 0, 1, 2, 3
REJECTED_STATE, REJECTED_ROBOT_ID = 5, 6

DISARMED, CONNECTING, ARMED = 'DISARMED', 'CONNECTING', 'ARMED'
LATCHED, RELEASING, FAULT = 'LATCHED', 'RELEASING', 'FAULT'

# 실행기가 켜져 팔에 연결돼 있을(수 있는) 상태
WORKER_STATES = frozenset({CONNECTING, ARMED, LATCHED, RELEASING})


def interface_arm_id(arm_id):
    """관제 시나리오 이름(omx1) → 명세 토픽 이름(omx_1). 이미 omx_1 형식이면 그대로."""
    match = re.fullmatch(r'([a-z]+)_?([0-9]+)', arm_id or '')
    return f'{match.group(1)}_{match.group(2)}' if match else arm_id


class CommandGate:
    """
    ArmCommand 헤더 판정 (SR-20 의 epoch·seq·TTL).

    map_hash 는 팔이 맵을 쓰지 않아 보지 않는다. 서명(sig)은 D13 이 정해지기 전이라 보지 않는다.
    check() 는 판정만 하고, 명령을 실제로 받아들일 때 accept() 로 epoch·seq 를 남긴다.
    """

    def __init__(self, robot_id):
        self.robot_id = robot_id
        self.epoch_accepted = 0     # 0 = 아직 없음 (ArmStatus.epoch_accepted)
        self.last_seq = 0

    def check(self, header, command, now):
        """(판정, 이유). header 는 robot_id·epoch·seq·issued_at[s]·ttl_ms 를 가진 dict."""
        if header.get('robot_id') != self.robot_id:
            return REJECTED_ROBOT_ID, f'대상이 {self.robot_id} 가 아님 ({header.get("robot_id")})'
        ttl = header.get('ttl_ms', 0) / 1000.0
        issued = header.get('issued_at', 0.0)
        if ttl <= 0:
            return REJECTED_TTL, 'ttl_ms 가 0'
        if now > issued + ttl:
            return REJECTED_TTL, f'명령 만료 ({now - issued:.1f}s > ttl {ttl:.1f}s)'
        if issued > now + ttl:
            return REJECTED_TTL, '명령 시각이 미래: 두 PC 시계 동기화 확인'
        epoch, seq = header.get('epoch', 0), header.get('seq', 0)
        if command == CMD_START:
            if epoch <= self.epoch_accepted:
                return REJECTED_EPOCH, f'START 는 새 epoch 에서만 ({epoch} <= {self.epoch_accepted})'
            return ACCEPTED, ''
        if epoch != self.epoch_accepted:
            return REJECTED_EPOCH, f'epoch 가 다름 (받은 {epoch}, 지금 {self.epoch_accepted})'
        if seq <= self.last_seq:
            return REJECTED_SEQ, f'seq 역행 ({seq} <= {self.last_seq})'
        return ACCEPTED, ''

    def accept(self, header, command):
        if command == CMD_START:
            self.epoch_accepted = header['epoch']
        self.last_seq = header['seq']


def decide(power, command, busy, backend_name):
    """
    정지 계열이 아닌 명령이 지금 상태에서 되는지. (되는가, 이유, 할 일).

    할 일: 'connect' (실행기 켜기), 'release' (쉬는 자세면 끄기), 'clear' (실행기 없이 DISARMED 로),
    'release_hold' (HOLD 해제).
    """
    if command == CMD_RELEASE_HOLD:
        return True, '', 'release_hold'
    if command == CMD_START:
        if backend_name == 'none':
            return False, '팔 동작 백엔드가 없음 (backend=none)', ''
        if power != DISARMED:
            return False, f'꺼짐(DISARMED)에서만 켤 수 있음 (지금 {power})', ''
        return True, '', 'connect'
    if command == CMD_RESET:
        if power == FAULT:
            return True, '', 'clear'
        if power in (DISARMED, CONNECTING, RELEASING):
            return False, f'지금 {power} 에서는 끌 수 없음', ''
        if busy:
            return False, '작업 중에는 끌 수 없음 (먼저 HOLD)', ''
        return True, '', 'release'
    return False, f'모르는 명령 {command}', ''


def keep_hold(new_power, held):
    """전원이 new_power 로 바뀐 뒤에도 HOLD 를 남기는지. 꺼지면(DISARMED) 지운다 (모듈 설명)."""
    return held and new_power != DISARMED


def hold_status(power, held):
    """(hold_active, hold_reason) 을 ArmStatus 에 낸다. 소프트 정지(LATCHED)가 HOLD 보다 먼저다."""
    if power == LATCHED:
        return True, 'SOFT_LATCH'
    if held:
        return True, 'HOLD'
    return False, ''
