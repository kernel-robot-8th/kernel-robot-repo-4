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
로봇팔 켜기·끄기 명령 (ROS 없는 순수 로직). arm_command_node 가 쓴다.

웹이 /api/arms/<arm>/command 로 낸 요청을 ArmCommand 헤더(epoch·seq·TTL)로 바꾸고,
팔 노드(cobot_manipulation arm_adapter_node)의 CommandAck 를 요청에 짝지어 답한다.
명령·판정 번호는 cobot_interfaces 의 ArmCommand·CommandAck 가 정본이다.

관제는 팔 모션을 시작하지 않는다 (ArmCommand.msg). 여기서 내는 명령은 연결·토크(START),
쉬는 자세에서 끄기(RESET), 정지(HOLD·SOFT_LATCH), 정지 해제(RELEASE_HOLD) 뿐이다.
상태 판정은 팔 노드가 한다. 여기서는 화면 표시용으로 추정만 한다.
"""

import json
import math
import re
import uuid

# ArmCommand.CMD_* (웹은 소문자 이름으로 보낸다)
COMMANDS = {'hold': 0, 'release_hold': 1, 'reset': 2, 'start': 3, 'soft_latch': 4}
STOP_COMMANDS = frozenset({'hold', 'soft_latch'})
START = 'start'

# CommandAck.result
ACK_RESULTS = {0: 'ACCEPTED', 1: 'REJECTED_EPOCH', 2: 'REJECTED_SEQ', 3: 'REJECTED_TTL',
               4: 'REJECTED_MAP_HASH', 5: 'REJECTED_STATE', 6: 'REJECTED_ROBOT_ID',
               7: 'REJECTED_CLOCK_UNSYNCED', 8: 'REJECTED_SIGNATURE'}
ACCEPTED = 0

# 화면 상태 (ArmStatus 에는 전원 상태 칸이 없어 토크·정지·작업 단계로 추정한다)
STALE = 'STALE'            # 팔 노드 상태가 안 들어옴
OFF = 'OFF'                # 토크 꺼짐. 고장(FAULT)도 이렇게 보인다 → last_ack 사유를 함께 본다
READY = 'READY'            # 켜짐, 일 없음 (work_step IDLE)
BUSY = 'BUSY'              # 켜짐, 연결 중·작업 중·끄는 중
HOLD = 'HOLD'
SOFT_LATCH = 'SOFT_LATCH'

# 화면 버튼을 켤지 정하는 힌트. 최종 판정은 팔 노드가 한다. 정지는 언제나 낼 수 있다.
ALLOWED = {
    STALE: ('hold', 'soft_latch'),
    OFF: ('start', 'reset', 'hold', 'soft_latch'),   # reset: 고장(FAULT) 풀기
    READY: ('reset', 'hold', 'soft_latch'),
    BUSY: ('hold', 'soft_latch'),
    HOLD: ('release_hold', 'reset', 'soft_latch'),
    SOFT_LATCH: ('reset', 'hold'),
}

ARM_ID_PATTERN = re.compile(r'([a-z]+)_?([0-9]+)')


class CommandError(Exception):
    """요청을 명령으로 바꿀 수 없음. status 는 HTTP 상태 번호."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def interface_arm_id(arm_id):
    """omx1·omx_1 → 명세 이름 omx_1. 형식이 다르면 그대로 (팔 노드 arm_power_utils 와 같은 규칙)."""
    match = ARM_ID_PATTERN.fullmatch(arm_id or '')
    return f'{match.group(1)}_{match.group(2)}' if match else arm_id


def scenario_arm_id(arm_id):
    """omx_1 → 관제 시나리오 이름 omx1 (scenario.yaml pickup_arm·dropoff_arm)."""
    return (arm_id or '').replace('_', '')


def clean_float(value):
    """JSON 에 NaN·inf 를 실을 수 없어 None 으로 바꾼다."""
    value = float(value)
    return value if math.isfinite(value) else None


def derive_state(status, online):
    """팔 상태(ArmStatus dict) → 화면 상태 (위 STALE·OFF·READY·BUSY·HOLD·SOFT_LATCH)."""
    if not online or not status:
        return STALE
    if status.get('hold_reason') == 'SOFT_LATCH':
        return SOFT_LATCH
    if status.get('hold_active'):
        return HOLD
    if not status.get('torque_enabled'):
        return OFF
    if status.get('work_step') == 'IDLE':
        return READY
    return BUSY


def parse_request(text):
    """/control_center/arm_request JSON → dict. 틀리면 ValueError."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f'JSON 이 아님: {error}') from None
    if not isinstance(data, dict) or not data.get('request_id'):
        raise ValueError('request_id 가 없는 요청')
    return data


def reply(request_id, status, body):
    """/control_center/arm_events 응답 (fleet_api 의 ArmStore 가 기다린다)."""
    return {'type': 'reply', 'request_id': request_id, 'status': status, 'body': body}


class ArmCommander:
    """
    팔 여러 대의 명령 번호와 응답 대기.

    epoch: START 마다 (내가 쓴 값, 팔이 받아들인 값) 중 큰 값 + 1. 팔 노드를 다시 켜면 팔의 epoch 가 0 으로
    돌아가는데, 그래도 새 START 는 더 큰 값이라 받아들여진다. 그 밖의 명령은 팔이 받아들인 epoch 를 쓴다.
    seq: (내가 쓴 값, 팔이 받아들인 값) 중 큰 값 + 1. 같은 epoch 안에서 늘기만 한다.
    시각은 인자로 받는다: wall 은 issued_at(두 PC 시계 비교), mono 는 끊김·응답 기한.
    """

    def __init__(self, arm_ids, ttl_ms, ack_timeout_sec, stale_sec):
        self.arm_ids = [interface_arm_id(a) for a in arm_ids]
        self.ttl_ms = int(ttl_ms)
        self.ack_timeout_sec = float(ack_timeout_sec)
        self.stale_sec = float(stale_sec)
        self._arms = {a: {'epoch': 0, 'seq': 0, 'accepted_epoch': 0, 'accepted_seq': 0,
                          'status': None, 'status_at': None, 'last_ack': None}
                      for a in self.arm_ids}
        self._pending = {}   # command_id → {request_id, arm_id, command, deadline, ...}

    def put_status(self, arm_id, status, now_mono):
        """팔 상태(ArmStatus dict)를 넣는다. 등록 안 된 팔이면 False."""
        arm = self._arms.get(arm_id)
        if arm is None:
            return False
        arm['status'], arm['status_at'] = status, now_mono
        arm['accepted_epoch'] = int(status.get('epoch_accepted', 0))
        arm['accepted_seq'] = int(status.get('last_seq_accepted', 0))
        return True

    def make_command(self, request, now_wall, now_mono):
        """
        요청 dict → (header dict, 명령 번호). 틀리면 CommandError.

        header 의 issued_at 은 [s] float 다 (노드가 builtin_interfaces/Time 으로 바꾼다).
        """
        arm_id = interface_arm_id(str(request.get('arm_id') or ''))
        arm = self._arms.get(arm_id)
        if arm is None:
            raise CommandError(404, f'등록되지 않은 로봇팔: {request.get("arm_id")}')
        name = str(request.get('command') or '').lower()
        if name not in COMMANDS:
            raise CommandError(400, f'모르는 로봇팔 명령: {request.get("command")} '
                                    f'({", ".join(COMMANDS)} 중 하나)')
        if name == START:
            epoch = max(arm['epoch'], arm['accepted_epoch']) + 1
            arm['epoch'] = epoch
        else:
            epoch = arm['accepted_epoch']
        seq = max(arm['seq'], arm['accepted_seq']) + 1
        arm['seq'] = seq
        command_id = str(uuid.uuid4())
        header = {'command_id': command_id, 'tx_id': str(request.get('client_request_id') or ''),
                  'robot_id': arm_id, 'epoch': epoch, 'seq': seq, 'issued_at': now_wall,
                  'ttl_ms': self.ttl_ms, 'issued_by': 'control_center'}
        self._pending[command_id] = {
            'request_id': request['request_id'], 'arm_id': arm_id, 'command': name,
            'epoch': epoch, 'seq': seq, 'source': request.get('source') or '',
            'client_request_id': request.get('client_request_id'),
            'deadline': now_mono + self.ack_timeout_sec}
        return header, COMMANDS[name]

    def put_ack(self, ack, now_wall):
        """
        팔 응답(CommandAck dict)을 넣는다. 내가 낸 명령의 응답이면 reply dict, 아니면 None.

        내 명령이 아니어도(다른 관제·시험 스크립트) 그 팔의 마지막 응답으로는 남긴다.
        """
        arm = self._arms.get(ack.get('robot_id'))
        last = arm and arm['last_ack']
        if last and ack.get('command_id') and last['command_id'] == ack.get('command_id'):
            # 같은 응답이 두 번 올 수 있다 (도메인 101 LOCALHOST 시험에서 DDS 가 겹쳐 전달함).
            # 두 번째는 명령 이름을 모르므로 첫 기록을 덮어쓰지 않는다.
            return None
        result = int(ack.get('result', -1))
        record = {'command_id': ack.get('command_id'),
                  'result': ACK_RESULTS.get(result, str(result)),
                  'accepted': result == ACCEPTED, 'reason': ack.get('reason') or '',
                  'stop_executed': bool(ack.get('stop_executed')),
                  'epoch': ack.get('epoch'), 'seq': ack.get('seq'),
                  'rx_to_ack_ms': ack.get('rx_to_ack_ms'), 'received_at': now_wall}
        pending = self._pending.pop(ack.get('command_id'), None)
        if pending is not None:
            record['command'] = pending['command']
        if arm is not None:
            arm['last_ack'] = record
            if record['accepted'] and record.get('command') == START:
                # 상태 토픽보다 응답이 먼저 오면, 바로 다음 명령이 새 epoch 를 쓰게 한다.
                arm['accepted_epoch'] = max(arm['accepted_epoch'], int(ack.get('epoch', 0)))
        if pending is None:
            return None
        # 정지 계열은 판정이 거부여도 팔이 멈췄으면 성공으로 본다 (stop_executed).
        ok = record['accepted'] or record['stop_executed']
        return reply(pending['request_id'], 200 if ok else 409,
                     dict(record, arm_id=pending['arm_id'],
                          client_request_id=pending['client_request_id']))

    def expire(self, now_mono):
        """기한까지 응답이 없는 명령 → reply dict 목록 (504)."""
        late = [cid for cid, p in self._pending.items() if now_mono > p['deadline']]
        replies = []
        for command_id in late:
            pending = self._pending.pop(command_id)
            replies.append(reply(pending['request_id'], 504, {
                'detail': f'로봇팔 {pending["arm_id"]} 이 {pending["command"]} 에 답하지 않음 '
                          f'({self.ack_timeout_sec:.0f}s). 팔 노드·도메인·시계 동기화 확인',
                'arm_id': pending['arm_id'], 'command': pending['command'],
                'command_id': command_id, 'client_request_id': pending['client_request_id']}))
        return replies

    def snapshot(self, now_mono, now_wall):
        """/control_center/arms JSON 의 내용."""
        arms = []
        for arm_id in self.arm_ids:
            arm = self._arms[arm_id]
            age = None if arm['status_at'] is None else now_mono - arm['status_at']
            online = age is not None and age <= self.stale_sec
            state = derive_state(arm['status'], online)
            arms.append({
                'arm_id': arm_id, 'alias': scenario_arm_id(arm_id), 'online': online,
                'age': None if age is None else round(age, 3), 'state': state,
                'allowed': list(ALLOWED[state]), 'status': arm['status'],
                'last_ack': arm['last_ack'],
                'pending': sum(1 for p in self._pending.values() if p['arm_id'] == arm_id),
                'epoch': arm['accepted_epoch'], 'seq': arm['accepted_seq']})
        return {'time': now_wall, 'ttl_ms': self.ttl_ms, 'arms': arms}
