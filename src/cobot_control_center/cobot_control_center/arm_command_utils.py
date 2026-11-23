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

주문 작업(put_other_request): fleet_control 이 /fleet/work_request 로 보낸 요청도 듣기만 해서
그 팔 카드의 작업 칸(work, source 'order')에 진행 중으로 보이고, 결과와 request_id 로 짝짓는다.
"""

from collections import deque
import json
import math
import re
import uuid

# ArmCommand.CMD_* (웹은 소문자 이름으로 보낸다)
COMMANDS = {'hold': 0, 'release_hold': 1, 'reset': 2, 'start': 3, 'soft_latch': 4, 'unlatch': 5}
STOP_COMMANDS = frozenset({'hold', 'soft_latch'})
START = 'start'
# 작업 시험 (팔 노드 work_contract_utils.WORK_ACTIONS 와 같다). hold·release_hold 는 위 정지 명령을 쓴다.
WORK = 'work'
WORK_ACTIONS = ('pick', 'load', 'unload', 'warehouse_store', 'arrange_shoe')
# 작업 기록 상태
WORK_RUNNING = 'RUNNING'
WORK_SUCCEEDED = 'SUCCEEDED'
WORK_FAILED = 'FAILED'
WORK_NO_RESULT = 'NO_RESULT'
# 작업 칸(work)을 채운 쪽: 웹의 작업 시험 / fleet_control 의 주문
WORK_TEST = 'test'
# 작업 시험의 선반 행(shelf_row). 주문은 fleet_control 이 재고 칸에서 싣고, 팔 노드가 실행기의 box(상자 번호)로
# 넘긴다. 상자 번호를 받는 모델(omx_1031 E 등, info.worker.models.<작업>.box_required)은 이것이 있어야 움직인다.
SHELF_ROW_MAX = 9
WORK_ORDER = 'order'
# 팔 동작이 아닌 fleet_control 요청 단계 (release_hold 등). 카드 작업 칸은 바꾸지 않고 기록만 한다.
SAFETY_STAGE = 'SAFETY'

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
# 고장: 팔 실행기가 멈춤 (팔 노드 전원 상태 FAULT). ArmStatus 에 전원 상태 칸이 없어 토크만 보면 OFF 와 같다.
# 팔 노드는 FAULT 에서 START 를 '꺼짐(DISARMED)에서만 켤 수 있음 (지금 FAULT)' 으로 거절하므로,
# OFF 인데 마지막 응답이 그 거절이면 FAULT 로 본다. 끄기(RESET) 수락 등 다음 응답이 오면 풀린다.
# (근본 해결은 ArmStatus 에 전원 상태 칸을 넣는 것 — 팀 합의 필요)
FAULT = 'FAULT'
FAULT_HINT = '(지금 FAULT)'

# 화면 버튼을 켤지 정하는 힌트. 최종 판정은 팔 노드가 한다. 정지는 언제나 낼 수 있다.
ALLOWED = {
    STALE: ('hold', 'soft_latch'),
    OFF: ('start', 'hold', 'soft_latch'),
    FAULT: ('reset', 'hold', 'soft_latch'),          # 고장은 끄기(RESET)로만 풀림
    READY: (WORK, 'reset', 'hold', 'soft_latch'),   # work: 작업 시험 (진행 중이면 뺀다)
    BUSY: ('hold', 'soft_latch'),
    HOLD: ('release_hold', 'reset', 'soft_latch'),
    SOFT_LATCH: ('unlatch', 'reset', 'hold'),      # 잠금 해제(unlatch)는 사람이 확인 창 뒤에만 보낸다
}

# 알람·기록 문구용 화면 상태 이름 (web/arms.js ARM_STATE 와 같은 말)
STATE_TEXT = {STALE: '미연결', OFF: '꺼짐', FAULT: '고장', READY: '대기', BUSY: '작업·연결 중',
              HOLD: '정지', SOFT_LATCH: '비상정지'}
COMMAND_TEXT = {'start': '켜기', 'reset': '끄기', 'hold': '정지', 'release_hold': '정지 해제',
                'soft_latch': '비상정지', 'unlatch': '잠금 해제'}
# 대기 ↔ 작업 중은 작업마다 바뀌어 기록이 넘친다. 작업 결과 기록으로 대신한다.
QUIET_CHANGES = frozenset({(READY, BUSY), (BUSY, READY)})

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


def is_fault_ack(last_ack):
    """마지막 응답이 '고장이라 켤 수 없음' 거절인지 (위 FAULT 설명)."""
    return bool(last_ack and not last_ack.get('accepted')
                and FAULT_HINT in (last_ack.get('reason') or ''))


def is_fault_info(status, info):
    """
    팔 노드 info 의 전원 상태가 FAULT 인지.

    START 가 수락된 뒤에 실행기가 죽으면 거절 응답이 없어 is_fault_ack 로는 못 알아본다 (2026-11-21 omx2).
    info 와 status 의 boot_id 가 다르면 팔 노드가 다시 켜진 뒤 남은 옛 info 라 보지 않는다.
    """
    if not isinstance(info, dict) or info.get('power') != FAULT:
        return False
    boot, status_boot = info.get('boot_id'), (status or {}).get('robot_boot_id')
    return not (boot and status_boot and boot != status_boot)


def derive_state(status, online, last_ack=None, info=None):
    """팔 상태(ArmStatus dict)·info → 화면 상태 (위 STALE·OFF·FAULT·READY·BUSY·HOLD·SOFT_LATCH)."""
    if not online or not status:
        return STALE
    if is_fault_info(status, info):
        return FAULT
    if status.get('hold_reason') == 'SOFT_LATCH':
        return SOFT_LATCH
    if status.get('hold_active'):
        return HOLD
    if not status.get('torque_enabled'):
        return FAULT if is_fault_ack(last_ack) else OFF
    if status.get('work_step') == 'IDLE':
        return READY
    return BUSY


DEFAULT_SAFE_TOL = 3.0   # 팔 실행기 --safe-tol 기본값 (omx_fleet_worker.py). info 에 값이 있으면 그것을 쓴다
# 실행기 ready 가 info.worker 에 남기는 칸 (팔 노드 arm_info_utils.WORKER_KEYS)
WORKER_REPORTED = ('actions', 'models', 'rest_pose', 'safe_tol')


def start_block(info):
    """
    팔 노드 info 로 본 '켜기가 안 되는 이유'. 막힘이 없거나 info 가 없으면 ''.

    info 는 팔 노드가 /manipulation/<arm>/info 로 내는 dict (cobot_manipulation arm_info_utils).
    예전 팔 노드는 info 를 내지 않으므로 그때는 막지 않는다 (최종 판정은 팔 노드가 한다).
    """
    if not isinstance(info, dict):
        return ''
    if info.get('backend') == 'none':
        return '실행기 없음 (backend=none): 팔 노드를 backend:=worker 로 띄워야 켤 수 있음'
    detect = info.get('detect') or {}
    if detect.get('state') and detect.get('state') != 'READY':
        return f'보드 없음 ({detect.get("state")}): {detect.get("reason") or "?"}'
    if info.get('dead'):
        return f'실행기 고장: {info["dead"]}'
    return ''


def rest_check(status, info):
    """
    지금 관절과 쉬는 자세(rest_pose)의 차이. 끄기(RESET)는 그리퍼 뺀 관절이 모두 tol 안이어야 된다.

    None: info 가 없거나 실행기 정보가 아직 없음. configured=False: 실행기에 rest_pose 가 없음 (끄기는 늘 거절).
    diff·at_rest 가 None 이면 관절 값을 아직 모름 (실행기가 안 떠 있음).
    """
    worker = (info or {}).get('worker') if isinstance(info, dict) else None
    if not worker or worker.get('fake') or not any(k in worker for k in WORKER_REPORTED):
        return None   # 실행기가 아직 한 번도 ready 를 보내지 않음 (none·fake 백엔드 포함)
    tol = worker.get('safe_tol')
    number = isinstance(tol, (int, float)) and not isinstance(tol, bool)
    tol = float(tol) if number else DEFAULT_SAFE_TOL
    rest = {k: v for k, v in (worker.get('rest_pose') or {}).items() if k != 'gripper'}
    if not rest:
        return {'configured': False, 'tol': tol, 'diff': None, 'worst': None, 'at_rest': None}
    names = (status or {}).get('joint_names') or []
    values = (status or {}).get('joint_positions') or []
    now = {n: v for n, v in zip(names, values) if v is not None}
    if not all(k in now for k in rest):
        return {'configured': True, 'tol': tol, 'diff': None, 'worst': None, 'at_rest': None}
    diff = {k: round(now[k] - v, 2) for k, v in rest.items()}
    worst = max(abs(d) for d in diff.values())
    return {'configured': True, 'tol': tol, 'diff': diff, 'worst': round(worst, 2),
            'at_rest': worst <= tol}


def parse_request(text):
    """/control_center/arm_request JSON → dict. 틀리면 ValueError."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f'JSON 이 아님: {error}') from None
    if not isinstance(data, dict) or not data.get('request_id'):
        raise ValueError('request_id 가 없는 요청')
    return data


def arm_event(time, arm_id, kind, level, text, data=None):
    """
    기록 한 줄. level 은 'info' / 'warn' / 'bad' (핑키 이벤트 로그와 같다).

    kind: link(연결·끊김), state(상태 바뀜), boot(팔 노드 다시 켜짐), ack(명령 응답),
    timeout(응답 없음), work(작업 결과).
    """
    event = {'time': time, 'arm': arm_id, 'kind': kind, 'level': level, 'text': text}
    if data:
        event['data'] = data
    return event


def work_level(success, retry_safe):
    """작업 결과 → 기록 수준. 도중 실패는 팔 자세를 모르니 bad."""
    if success:
        return 'info'
    return 'warn' if retry_safe else 'bad'


def work_label(record):
    """작업 칸 기록의 머리말: '작업 시험 pick' / '주문 작업 PICK (cust-1, pinky1)'."""
    if record.get('source') == WORK_ORDER:
        return (f'주문 작업 {record.get("stage") or "?"} {record.get("action")} '
                f'({record.get("order_id") or "-"}, {record.get("robot_id") or "-"})')
    return f'작업 시험 {record.get("action")}'


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

    def __init__(self, arm_ids, ttl_ms, ack_timeout_sec, stale_sec, work_timeout_sec=300.0,
                 work_margin_sec=15.0, work_stage='MANUAL_TEST', session_id=None, site=None):
        self.arm_ids = [interface_arm_id(a) for a in arm_ids]
        # 현장 배치 (site_arms_utils.parse_site_arms 결과). actions 말고는 화면 표시용이다.
        self.site = dict(site or {})
        self.ttl_ms = int(ttl_ms)
        self.ack_timeout_sec = float(ack_timeout_sec)
        self.stale_sec = float(stale_sec)
        self.work_timeout_sec = float(work_timeout_sec)
        self.work_margin_sec = float(work_margin_sec)
        self.work_stage = str(work_stage)
        self.session_id = session_id or uuid.uuid4().hex
        self._arms = {a: {'epoch': 0, 'seq': 0, 'accepted_epoch': 0, 'accepted_seq': 0,
                          'status': None, 'status_at': None, 'last_ack': None,
                          'work_seq': 0, 'work': None,
                          # 알람·기록용: 연결 여부, 마지막 화면 상태와 그 시각, 끊긴 시각,
                          # 팔 노드 boot id, 팔 자세 모름 {since, text}
                          'linked': False, 'state': None, 'state_since': None,
                          'lost_at': None, 'boot_id': None, 'posture': None,
                          # 팔 노드 info (백엔드·탐지·실행기 모델·쉬는 자세)와 받은 시각
                          'info': None, 'info_at': None}
                      for a in self.arm_ids}
        self._pending = {}   # command_id → {request_id, arm_id, command, deadline, ...}
        self._works = {}     # 작업 request_id → {arm_id, deadline, timeout} (작업 시험·주문 작업)
        self._events = []    # take_events() 가 가져갈 기록
        self._seen_results = deque(maxlen=256)   # 주문 작업 결과 중복 거르기

    def _add(self, now_wall, arm_id, kind, level, text, data=None):
        self._events.append(arm_event(now_wall, arm_id, kind, level, text, data))

    def take_events(self):
        """쌓인 기록을 꺼낸다 (오래된 것부터). 꺼낸 것은 지운다."""
        events, self._events = self._events, []
        return events

    def _set_posture(self, arm_id, now_wall, text):
        self._arms[arm_id]['posture'] = {'since': now_wall, 'text': text}

    def put_info(self, arm_id, info, now_mono, now_wall=None):
        """
        팔 노드 info(dict)를 넣는다. 등록 안 된 팔이거나 dict 가 아니면 False.

        고장(FAULT)은 info 로만 알 수 있어 여기서도 상태 바뀜을 기록한다 (is_fault_info).
        """
        arm = self._arms.get(arm_id)
        if arm is None or not isinstance(info, dict):
            return False
        arm['info'], arm['info_at'] = info, now_mono
        if arm['linked'] and arm['status']:
            when = now_mono if now_wall is None else now_wall
            self._track_state(arm_id, derive_state(arm['status'], True, None, info), when)
        return True

    def put_status(self, arm_id, status, now_mono, now_wall=None):
        """
        팔 상태(ArmStatus dict)를 넣는다. 등록 안 된 팔이면 False.

        연결됨·상태 바뀜·팔 노드 다시 켜짐을 기록한다. now_wall 이 없으면 now_mono 를 시각으로 쓴다.
        """
        arm = self._arms.get(arm_id)
        if arm is None:
            return False
        when = now_mono if now_wall is None else now_wall
        arm['status'], arm['status_at'] = status, now_mono
        arm['accepted_epoch'] = int(status.get('epoch_accepted', 0))
        arm['accepted_seq'] = int(status.get('last_seq_accepted', 0))
        boot = status.get('robot_boot_id') or None
        if boot and arm['boot_id'] and boot != arm['boot_id']:
            self._add(when, arm_id, 'boot', 'warn', '팔 노드 다시 켜짐')
        if boot:
            arm['boot_id'] = boot
        state = derive_state(status, True, None, arm['info'])
        linked_now = not arm['linked']
        if linked_now:
            arm['linked'], arm['lost_at'] = True, None
            self._add(when, arm_id, 'link', 'info', f'연결됨 ({STATE_TEXT[state]})')
        self._track_state(arm_id, state, when, log=not linked_now)
        return True

    def _track_state(self, arm_id, state, when, log=True):
        """화면 상태가 바뀌면 기록하고 state_since 를 옮긴다 (대기 ↔ 작업 중은 기록 안 함)."""
        arm = self._arms[arm_id]
        if state == arm['state']:
            return
        if log and (arm['state'], state) not in QUIET_CHANGES:
            level = {HOLD: 'warn', SOFT_LATCH: 'bad', FAULT: 'bad'}.get(state, 'info')
            self._add(when, arm_id, 'state', level,
                      f'{STATE_TEXT.get(arm["state"], "?")} → {STATE_TEXT[state]}')
        arm['state'], arm['state_since'] = state, when

    def check_links(self, now_mono, now_wall):
        """상태가 stale_sec 넘게 끊긴 팔을 끊김으로 기록한다 (한 번만)."""
        for arm_id in self.arm_ids:
            arm = self._arms[arm_id]
            if arm['linked'] and now_mono - arm['status_at'] > self.stale_sec:
                arm['linked'], arm['lost_at'] = False, now_wall
                arm['state'], arm['state_since'] = STALE, now_wall
                self._add(now_wall, arm_id, 'link', 'bad',
                          '연결 끊김 (팔 노드·네트워크 확인)')

    def _state(self, arm, now_mono):
        online = arm['status_at'] is not None and now_mono - arm['status_at'] <= self.stale_sec
        return derive_state(arm['status'], online, arm['last_ack'], arm['info'])

    def work_actions(self, arm_id):
        """그 팔이 할 수 있는 작업 (현장 배치 actions, 없으면 WORK_ACTIONS 전부)."""
        actions = (self.site.get(arm_id) or {}).get('actions')
        return list(WORK_ACTIONS) if actions is None else list(actions)

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
        allowed = self.work_actions(arm_id)
        if action not in allowed:
            station = (self.site.get(arm_id) or {}).get('station')
            where = f' ({station})' if station else ''
            raise CommandError(409, f'{arm_id}{where} 는 이 작업({action})을 하지 않음 '
                                    f'(가능: {", ".join(allowed) or "없음"}, site_arms.yaml)')
        shelf_row = request.get('shelf_row')
        if shelf_row in (None, ''):
            shelf_row = None
        elif (isinstance(shelf_row, bool) or not isinstance(shelf_row, int)
              or not 1 <= shelf_row <= SHELF_ROW_MAX):
            raise CommandError(400, f'선반 행(shelf_row)은 1..{SHELF_ROW_MAX} 정수: {shelf_row!r}')
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
        if shelf_row is not None:
            payload['shelf_row'] = shelf_row
        self._works[work_id] = {
            'arm_id': arm_id, 'timeout': self.work_timeout_sec,
            'deadline': now_mono + self.work_timeout_sec + self.work_margin_sec}
        arm['work'] = {
            'request_id': work_id, 'action': action, 'state': WORK_RUNNING, 'seq': arm['work_seq'],
            'sent_at': now_wall, 'finished_at': None, 'duration': None, 'detail': '',
            'retry_safe': None, 'data': {}, 'source': WORK_TEST,
            'requested_by': request.get('source') or '',
            'order_id': '', 'robot_id': '', 'stage': self.work_stage, 'shelf_row': shelf_row,
            'client_request_id': request.get('client_request_id')}
        return payload

    def put_other_request(self, request, now_wall, now_mono):
        """
        /fleet/work_request 에서 들은 요청 dict 를 넣는다 (주문 작업). 기록했으면 팔 이름, 아니면 None.

        내가 낸 작업 시험(이미 _works 에 있음)과 등록 안 된 팔 요청은 무시한다.
        SAFETY 단계(release_hold 등)는 카드 작업 칸을 바꾸지 않고 기록만 한다.
        """
        if not isinstance(request, dict):
            return None
        request_id = request.get('request_id')
        arm_id = interface_arm_id(str(request.get('target') or ''))
        if not request_id or request_id in self._works or arm_id not in self._arms:
            return None
        stage = str(request.get('stage') or '?')
        action = str(request.get('action') or '?')
        order = request.get('order_id') or '-'
        robot = request.get('robot_id') or '-'
        if stage == SAFETY_STAGE:
            self._add(now_wall, arm_id, 'work', 'info',
                      f'주문 관제 {action} 요청 ({robot})')
            return arm_id
        timeout = request.get('timeout_sec')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
                or not math.isfinite(timeout) or timeout <= 0:
            timeout = self.work_timeout_sec
        self._works[request_id] = {
            'arm_id': arm_id, 'timeout': float(timeout),
            'deadline': now_mono + float(timeout) + self.work_margin_sec}
        self._arms[arm_id]['work'] = {
            'request_id': request_id, 'action': action, 'state': WORK_RUNNING,
            'seq': request.get('seq'), 'sent_at': now_wall, 'finished_at': None,
            'duration': None, 'detail': '', 'retry_safe': None, 'data': {},
            'source': WORK_ORDER, 'requested_by': 'fleet_control',
            'order_id': request.get('order_id') or '', 'robot_id': request.get('robot_id') or '',
            'stage': stage, 'shelf_row': request.get('shelf_row'), 'client_request_id': None}
        self._add(now_wall, arm_id, 'work', 'info',
                  f'주문 작업 {stage} {action} 요청 ({order}, {robot})')
        return arm_id

    def put_work_result(self, result, now_wall):
        """
        /fleet/work_result dict 를 넣는다. 내가 낸 작업의 결과면 그 기록 dict, 아니면 None.

        주문(fleet_control) 결과나 같은 결과가 두 번 온 것은 버린다.
        """
        if not isinstance(result, dict):
            return None
        work = self._works.pop(result.get('request_id'), None)
        if work is None:
            self._put_other_result(result, now_wall)
            return None
        record = self._arms[work['arm_id']]['work']
        if record is None or record.get('request_id') != result.get('request_id'):
            # 카드 작업 칸이 그새 다른 작업으로 바뀜: 기록만 남긴다
            self._put_other_result(result, now_wall)
            return None
        # 같은 결과가 또 오면 _put_other_result 가 거르게 한다 (_works 에서는 이미 뺐다)
        self._seen_results.append(result.get('request_id'))
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
        self._note_work(work['arm_id'], now_wall, result.get('success') is True,
                        record['retry_safe'],
                        f'{work_label(record)} → '
                        f'{"성공" if record["state"] == WORK_SUCCEEDED else "실패"} '
                        f'({record["duration"]} s)', record['detail'])
        return dict(record, arm_id=work['arm_id'])

    def _note_work(self, arm_id, now_wall, success, retry_safe, text, detail):
        """작업 결과 기록 + 팔 자세 모름 알람 켜기·풀기."""
        self._add(now_wall, arm_id, 'work', work_level(success, retry_safe),
                  text + (f': {detail}' if detail else ''))
        if success:
            self._arms[arm_id]['posture'] = None
        elif not retry_safe:
            self._set_posture(arm_id, now_wall, f'팔 자세 확인: {text}')

    def _put_other_result(self, result, now_wall):
        """내가 낸 작업이 아닌 결과 (주문 작업). source 가 내 팔이면 기록만 한다."""
        request_id = result.get('request_id')
        arm_id = interface_arm_id(str(result.get('source') or ''))
        if arm_id not in self._arms or not request_id or request_id in self._seen_results:
            return
        self._seen_results.append(request_id)
        data = result.get('data') if isinstance(result.get('data'), dict) else {}
        success = result.get('success') is True
        order = result.get('order_id') or '-'
        self._note_work(arm_id, now_wall, success, bool(data.get('retry_safe')),
                        f'주문 작업 {result.get("stage") or "?"} → {"성공" if success else "실패"} '
                        f'({order}, {result.get("robot_id") or "-"})',
                        str(result.get('detail') or ''))

    def expire_works(self, now_mono, now_wall):
        """기한까지 결과가 없는 작업 → 기록 dict 목록 (상태 NO_RESULT)."""
        late = [wid for wid, w in self._works.items() if now_mono > w['deadline']]
        out = []
        for work_id in late:
            work = self._works.pop(work_id)
            arm_id = work['arm_id']
            detail = (f'{work["timeout"] + self.work_margin_sec:.0f}s 안에 결과가 없음. '
                      '팔 노드 로그·연결 확인 (팔 자세를 모르니 직접 확인)')
            record = self._arms[arm_id]['work']
            if record is None or record.get('request_id') != work_id:
                # 카드 작업 칸이 그새 다른 작업으로 바뀜: 기록·알람만 남긴다
                self._add(now_wall, arm_id, 'work', 'bad', f'작업 {work_id[:8]} → 결과 없음: {detail}')
                self._set_posture(arm_id, now_wall, f'팔 자세 확인: 작업 {work_id[:8]} 결과 없음')
                continue
            record.update(state=WORK_NO_RESULT, finished_at=now_wall, detail=detail)
            self._add(now_wall, arm_id, 'work', 'bad',
                      f'{work_label(record)} → 결과 없음: {detail}')
            self._set_posture(arm_id, now_wall, f'팔 자세 확인: {work_label(record)} 결과 없음')
            out.append(dict(record, arm_id=arm_id))
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
            what = COMMAND_TEXT.get(record.get('command'), '다른 곳이 낸 명령')
            reason = f': {record["reason"]}' if record['reason'] else ''
            stop = ' (정지는 실행됨)' if record['stop_executed'] and not record['accepted'] else ''
            self._add(now_wall, ack.get('robot_id'), 'ack',
                      'info' if record['accepted'] or record['stop_executed'] else 'warn',
                      f'{what} → {"수락" if record["accepted"] else record["result"]}{stop}{reason}')
            if record['accepted'] and record.get('command') == 'reset':
                arm['posture'] = None   # 쉬는 자세를 확인하고 꺼졌다
                # 끄기·고장 해제로 정리했으니 끝난 작업 결과(실패 등)는 카드에서 내린다.
                # 기록은 이벤트에 남아 있다. 진행 중 작업은 결과를 받아야 하므로 둔다.
                if arm['work'] and arm['work']['state'] != WORK_RUNNING:
                    arm['work'] = None
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

    def expire(self, now_mono, now_wall=None):
        """기한까지 응답이 없는 명령 → reply dict 목록 (504). 응답 없음도 기록한다."""
        late = [cid for cid, p in self._pending.items() if now_mono > p['deadline']]
        replies = []
        for command_id in late:
            pending = self._pending.pop(command_id)
            self._add(now_mono if now_wall is None else now_wall, pending['arm_id'], 'timeout',
                      'bad', f'{COMMAND_TEXT.get(pending["command"], pending["command"])} → '
                             f'응답 없음 ({self.ack_timeout_sec:.0f}s)')
            replies.append(reply(pending['request_id'], 504, {
                'detail': f'로봇팔 {pending["arm_id"]} 이 {pending["command"]} 에 답하지 않음 '
                          f'({self.ack_timeout_sec:.0f}s). 팔 노드·도메인·시계 동기화 확인',
                'arm_id': pending['arm_id'], 'command': pending['command'],
                'command_id': command_id, 'client_request_id': pending['client_request_id']}))
        return replies

    @staticmethod
    def _alarms(arm, state, online):
        """활성 알람 목록 (지금 이어지는 상태). 풀리면 사라진다."""
        alarms = []
        if not online and arm['lost_at'] is not None:
            alarms.append({'code': 'offline', 'level': 'bad', 'since': arm['lost_at'],
                           'text': '연결 끊김 (팔 노드·네트워크 확인)'})
        if online and state == SOFT_LATCH:
            alarms.append({'code': 'soft_latch', 'level': 'bad', 'since': arm['state_since'],
                           'text': '비상정지 잠김: 끄기 → 켜기로만 풀림'})
        if online and state == FAULT:
            dead = (arm.get('info') or {}).get('dead') or '팔 실행기가 멈춤'
            since = arm['state_since'] or (arm['last_ack'] or {}).get('received_at')
            alarms.append({'code': 'fault', 'level': 'bad', 'since': since,
                           'text': f'고장: {dead}. 원인을 고치고 고장 해제(끄기) 뒤 다시 켜기'})
        if online and state == HOLD:
            alarms.append({'code': 'hold', 'level': 'warn', 'since': arm['state_since'],
                           'text': '정지 유지 중: 정지 해제 또는 끄기'})
        torque = (arm.get('info') or {}).get('torque') or {}
        if online and state == OFF and torque.get('enabled') is True:
            # 실행기가 강제로 꺼지면 토크를 끄지 못한 채 남는다. 팔 노드가 모터에서 잰 값 (info.torque).
            alarms.append({'code': 'torque_left_on', 'level': 'warn', 'since': torque.get('at'),
                           'text': '꺼짐인데 모터 토크가 켜져 있음 (실측): 켜기 → 끄기로 풀기'})
        if arm['posture']:
            alarms.append({'code': 'posture_unknown', 'level': 'bad',
                           'since': arm['posture']['since'], 'text': arm['posture']['text']})
        return alarms

    def snapshot(self, now_mono, now_wall):
        """/control_center/arms JSON 의 내용."""
        arms = []
        for arm_id in self.arm_ids:
            arm = self._arms[arm_id]
            age = None if arm['status_at'] is None else now_mono - arm['status_at']
            online = age is not None and age <= self.stale_sec
            state = derive_state(arm['status'], online, arm['last_ack'], arm['info'])
            running = self._running_work(arm_id)
            work_actions = self.work_actions(arm_id)
            block = start_block(arm['info'])
            allowed = [c for c in ALLOWED[state]
                       if not (c == WORK and (running or not work_actions))
                       and not (c == START and block)]
            arms.append({
                'arm_id': arm_id, 'alias': scenario_arm_id(arm_id), 'online': online,
                'age': None if age is None else round(age, 3), 'state': state,
                'allowed': allowed, 'status': arm['status'],
                'last_ack': arm['last_ack'], 'work': arm['work'],
                'alarms': self._alarms(arm, state, online),
                'site': self.site.get(arm_id), 'work_actions': work_actions,
                'info': arm['info'], 'start_block': block,
                'rest_check': rest_check(arm['status'], arm['info']),
                'pending': sum(1 for p in self._pending.values() if p['arm_id'] == arm_id),
                'epoch': arm['accepted_epoch'], 'seq': arm['accepted_seq']})
        return {'time': now_wall, 'ttl_ms': self.ttl_ms, 'work_actions': list(WORK_ACTIONS),
                'arms': arms}
