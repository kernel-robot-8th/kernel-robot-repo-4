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

ArmCommand 로 내는 명령은 연결·토크(START), 쉬는 자세에서 끄기(RESET), 정지(HOLD·SOFT_LATCH),
정지 해제(RELEASE_HOLD) 뿐이다. 팔 모션은 ArmCommand 로 시작하지 않는다 (ArmCommand.msg).
상태 판정은 팔 노드가 한다. 여기서는 화면 표시용으로 추정만 한다.

작업 시험(make_work): 개발 대시보드에서 팔 하나에 작업 한 건(pick 등)을 시켜 본다.
주문 흐름과 같은 /fleet/work_request 계약(팔 노드 work_contract_utils)으로 보내고,
/fleet/work_result 에서 내가 낸 request_id 의 결과만 받는다. 실제 팔이 움직인다.
주행 관제(fleet_control_node)도 같은 토픽에 보내므로 주문 진행 중에는 쓰지 않는다.
"""

import json
import math
import re
import uuid

# ArmCommand.CMD_* (웹은 소문자 이름으로 보낸다)
COMMANDS = {'hold': 0, 'release_hold': 1, 'reset': 2, 'start': 3, 'soft_latch': 4}
STOP_COMMANDS = frozenset({'hold', 'soft_latch'})
START = 'start'
# 작업 시험 (팔 노드 work_contract_utils.WORK_ACTIONS 와 같다). hold·release_hold 는 위 정지 명령을 쓴다.
WORK = 'work'
WORK_ACTIONS = ('pick', 'load', 'unload', 'warehouse_store')
# 작업 기록 상태
WORK_RUNNING = 'RUNNING'
WORK_SUCCEEDED = 'SUCCEEDED'
WORK_FAILED = 'FAILED'
WORK_NO_RESULT = 'NO_RESULT'

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
    READY: (WORK, 'reset', 'hold', 'soft_latch'),   # work: 작업 시험 (진행 중이면 뺀다)
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

    작업 시험은 노드 실행마다 새 session_id 를 쓰고 seq 는 팔마다 1부터 센다 (fleet_control 과 같은 방식).
    """

    def __init__(self, arm_ids, ttl_ms, ack_timeout_sec, stale_sec, work_timeout_sec=120.0,
                 work_margin_sec=15.0, work_stage='MANUAL_TEST', session_id=None):
        self.arm_ids = [interface_arm_id(a) for a in arm_ids]
        self.ttl_ms = int(ttl_ms)
        self.ack_timeout_sec = float(ack_timeout_sec)
        self.stale_sec = float(stale_sec)
        self.work_timeout_sec = float(work_timeout_sec)
        self.work_margin_sec = float(work_margin_sec)
        self.work_stage = str(work_stage)
        self.session_id = session_id or uuid.uuid4().hex
        self._arms = {a: {'epoch': 0, 'seq': 0, 'accepted_epoch': 0, 'accepted_seq': 0,
                          'status': None, 'status_at': None, 'last_ack': None,
                          'work_seq': 0, 'work': None}
                      for a in self.arm_ids}
        self._pending = {}   # command_id → {request_id, arm_id, command, deadline, ...}
        self._works = {}     # 작업 request_id → {arm_id, deadline}

    def put_status(self, arm_id, status, now_mono):
        """팔 상태(ArmStatus dict)를 넣는다. 등록 안 된 팔이면 False."""
        arm = self._arms.get(arm_id)
        if arm is None:
            return False
        arm['status'], arm['status_at'] = status, now_mono
        arm['accepted_epoch'] = int(status.get('epoch_accepted', 0))
        arm['accepted_seq'] = int(status.get('last_seq_accepted', 0))
        return True

    def _state(self, arm, now_mono):
        online = arm['status_at'] is not None and now_mono - arm['status_at'] <= self.stale_sec
        return derive_state(arm['status'], online)

    def _running_work(self, arm_id):
        return any(w['arm_id'] == arm_id for w in self._works.values())

    def make_work(self, request, now_wall, now_mono):
        """
        작업 시험 요청 dict → /fleet/work_request 로 낼 dict. 틀리면 CommandError.

        404 모르는 팔, 400 모르는 작업, 409 팔이 대기(READY)가 아니거나 앞 작업이 아직 진행 중.
        최종 판정은 팔 노드가 하고 결과(/fleet/work_result)로 알려 준다.
        """
        arm_id = interface_arm_id(str(request.get('arm_id') or ''))
        arm = self._arms.get(arm_id)
        if arm is None:
            raise CommandError(404, f'등록되지 않은 로봇팔: {request.get("arm_id")}')
        action = str(request.get('action') or '').lower()
        if action not in WORK_ACTIONS:
            raise CommandError(400, f'모르는 로봇팔 작업: {request.get("action")} '
                                    f'({", ".join(WORK_ACTIONS)} 중 하나)')
        if self._running_work(arm_id):
            raise CommandError(409, f'{arm_id} 앞 작업이 아직 진행 중')
        state = self._state(arm, now_mono)
        if state != READY:
            raise CommandError(409, f'{arm_id} 가 대기(READY) 상태가 아님 (지금 {state})')
        arm['work_seq'] += 1
        work_id = uuid.uuid4().hex
        payload = {
            'request_id': work_id, 'order_id': '', 'robot_id': '', 'stage': self.work_stage,
            'target': scenario_arm_id(arm_id), 'action': action, 'session_id': self.session_id,
            'seq': arm['work_seq'], 'issued_at': now_wall, 'ttl_sec': self.ttl_ms / 1000.0,
            'timeout_sec': self.work_timeout_sec, 'attempt': 1}
        self._works[work_id] = {
            'arm_id': arm_id, 'deadline': now_mono + self.work_timeout_sec + self.work_margin_sec}
        arm['work'] = {
            'request_id': work_id, 'action': action, 'state': WORK_RUNNING, 'seq': arm['work_seq'],
            'sent_at': now_wall, 'finished_at': None, 'duration': None, 'detail': '',
            'retry_safe': None, 'data': {}, 'source': request.get('source') or '',
            'client_request_id': request.get('client_request_id')}
        return payload

    def put_work_result(self, result, now_wall):
        """
        /fleet/work_result dict 를 넣는다. 내가 낸 작업의 결과면 그 기록 dict, 아니면 None.

        주문(fleet_control) 결과나 같은 결과가 두 번 온 것은 버린다.
        """
        if not isinstance(result, dict):
            return None
        work = self._works.pop(result.get('request_id'), None)
        if work is None:
            return None
        record = self._arms[work['arm_id']]['work']
        data = result.get('data') if isinstance(result.get('data'), dict) else {}
        try:
            json.dumps(data, allow_nan=False)   # 스냅샷 JSON 에 실을 수 있어야 한다
        except (TypeError, ValueError):
            data = {}
        record.update(
            state=WORK_SUCCEEDED if result.get('success') is True else WORK_FAILED,
            finished_at=now_wall, duration=round(now_wall - record['sent_at'], 1),
            detail=str(result.get('detail') or ''), retry_safe=bool(data.get('retry_safe')),
            data=data)
        return dict(record, arm_id=work['arm_id'])

    def expire_works(self, now_mono, now_wall):
        """기한까지 결과가 없는 작업 → 기록 dict 목록 (상태 NO_RESULT)."""
        late = [wid for wid, w in self._works.items() if now_mono > w['deadline']]
        out = []
        for work_id in late:
            work = self._works.pop(work_id)
            record = self._arms[work['arm_id']]['work']
            record.update(
                state=WORK_NO_RESULT, finished_at=now_wall,
                detail=f'{self.work_timeout_sec + self.work_margin_sec:.0f}s 안에 결과가 없음. '
                       '팔 노드 로그·연결 확인 (팔 자세를 모르니 직접 확인)')
            out.append(dict(record, arm_id=work['arm_id']))
        return out

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
            running = self._running_work(arm_id)
            allowed = [c for c in ALLOWED[state] if not (c == WORK and running)]
            arms.append({
                'arm_id': arm_id, 'alias': scenario_arm_id(arm_id), 'online': online,
                'age': None if age is None else round(age, 3), 'state': state,
                'allowed': allowed, 'status': arm['status'],
                'last_ack': arm['last_ack'], 'work': arm['work'],
                'pending': sum(1 for p in self._pending.values() if p['arm_id'] == arm_id),
                'epoch': arm['accepted_epoch'], 'seq': arm['accepted_seq']})
        return {'time': now_wall, 'ttl_ms': self.ttl_ms, 'work_actions': list(WORK_ACTIONS),
                'arms': arms}
