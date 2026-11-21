"""사람 승인으로 /fleet/work_request에 답하는 어댑터. 로봇과 팔을 움직이지 않는다."""

import json
import math
import time

from .load_complete import JUDGED_DECISION

MOVING_SPEED_MPS = 0.03
ARM_VALID_SEC = 60.0  # 요청에 timeout_sec 이 없을 때만 쓴다
EVIDENCE = {
    'VERIFY_LOAD': {'load_present': True, 'arm_safe': True},
    'VERIFY_UNLOAD': {'placed': True, 'load_absent': True, 'arm_safe': True},
    'PICKUP_EXIT': {'clear': True}, 'PATH_EXIT': {'clear': True},
    'RETURN_EXIT': {'clear': True},
    'CORRECT_PICKUP': {'no_motion': True}, 'CORRECT_DROPOFF': {'no_motion': True},
}
DOCK_SIDE = {'DOCK_PICKUP': 'pickup', 'DOCK_DROPOFF': 'dropoff'}
# 자동 응답하는 단계. 관제 WORK(origin/sakim scenario_contracts.py)의 vision·navigation 단계 11개다.
# 여기 없는 단계는 무엇을 확인하는지 모르므로 성공으로 답하지 않고 대기에 둔다(11-21 S8).
AUTO_STAGES = frozenset(EVIDENCE) | frozenset(DOCK_SIDE) | {'MARKER', 'QR'}
UNKNOWN_STAGE_REASON = '모르는 단계: 자동 응답 안 함 (운영자 확인 필요)'
# 판정 기준 없이 통신만 잇는 자동 응답의 표시. 결과 data 에 그대로 싣는다.
AUTO_DECISION = 'auto_unjudged'
AUTO_OPERATOR = 'auto'
# 모든 팔을 맡는 팀 팔 노드 이름. 나머지는 omx<N>_adapter 가 그 팔만 맡는다.
GENERIC_ARM_NODE = 'arm_adapter'


def arm_presence(peers, targets):
    """결과 토픽의 팀 팔 노드 이름으로 팔 대상별 응답 노드가 보이는지 만든다."""
    names = set(peers)
    generic = GENERIC_ARM_NODE in names
    return {target: generic or f'{target}_adapter' in names for target in targets}


def arm_missing_text(target):
    return f'팔 노드 없음 ({target}_adapter 미발견)'


def arm_node_warning(request, arm_nodes):
    """
    팔 대상 작업 요청인데 그 대상의 팀 팔 노드가 안 보이면 경고 문구를 준다. 모르면 빈 문자열.

    정지 때 모든 팔에 가는 SAFETY 보류는 답을 기다리는 작업이 아니라서 뺀다.
    """
    target = request.get('target') if isinstance(request, dict) else None
    if (not isinstance(target, str) or arm_nodes.get(target) is not False
            or request.get('stage') == 'SAFETY'):
        return ''
    return arm_missing_text(target)


def known_stage(request):
    """
    자동 응답하는 단계인가. 단계가 문자열이 아니면(목록·객체 등) 모르는 단계로 본다.

    `in AUTO_STAGES` 를 바로 쓰면 목록·객체 단계에서 TypeError 가 난다. 그 요청은 이미 대기로 저장된 뒤라
    재시작 뒤 pending() 마다 다시 터진다. 그래서 문자열인지 먼저 본다.
    """
    stage = request.get('stage') if isinstance(request, dict) else None
    return isinstance(stage, str) and stage in AUTO_STAGES


def _target(request):
    """요청의 대상. 문자열이 아니면 None(어느 담당 대상과도 같지 않다)."""
    target = request.get('target') if isinstance(request, dict) else None
    return target if isinstance(target, str) else None


def yaw_error_deg(actual, target):
    """두 방향의 차이를 -180~180도로 돌려준다."""
    return math.degrees(math.atan2(math.sin(actual - target), math.cos(actual - target)))


class ManualAdapter:
    """target이 자기 담당인 요청을 대기열에 올리고 운영자 판단만 결과로 낸다."""

    def __init__(self, store, publish, targets, points, robot_state, clock=time.time, join=None,
                 exclusive=None, auto_targets=(), judge=None, judge_mode='off',
                 judge_stages=('VERIFY_LOAD',), attribute=None, shadow_wait_sec=5.0,
                 max_wait_sec=30.0, warn=None):
        self.store, self.publish, self.targets = store, publish, set(targets)
        self.warn = warn  # 운영 경고를 노드 로그로 넘기는 함수. 없으면 기록만 한다
        self.points, self.robot_state, self.clock = points, robot_state, clock
        self.session_id = None
        self.sequences = {}
        self.blocked = ''
        self.join = join
        self.exclusive = exclusive
        self.auto = set(auto_targets) & self.targets
        self.yielded = set()  # 다른 결과 발행자(팀 팔 노드)가 맡은 대상. 여기에는 답하지 않는다
        # 비전 판정(load_complete). off 는 판정 없이 자동 응답, shadow 는 판정을 참고값으로만 싣고
        # 자동 응답, enforce 는 판정이 통과해야 답한다. attribute 는 프레임을 이 주문의 로봇에 잇는 검사다.
        if judge_mode not in ('off', 'shadow', 'enforce'):
            raise ValueError('judge_mode 는 off·shadow·enforce 중 하나')
        self.judge, self.judge_mode = judge, judge_mode if judge else 'off'
        self.judge_stages, self.attribute = set(judge_stages), attribute
        self.shadow_wait_sec = shadow_wait_sec
        self.max_wait_sec = max_wait_sec
        self.judged = {}  # 요청별 마지막 판정. 웹에 막힌 이유를 보인다

    def on_heartbeat(self, heartbeat):
        """현재 관제 세션을 기억한다. 세션이 바뀌면 순번도 새로 시작한다."""
        session = heartbeat.get('session_id')
        if not isinstance(session, str) or not session:
            return
        if session != self.session_id:
            if self.join:
                for row in self.store.works('PENDING'):
                    req = json.loads(row['request_json'])
                    if req['stage'] == 'VERIFY_LOAD' and req['session_id'] != session:
                        self.store.claim_work(
                            req['request_id'], 'EXPIRED_SESSION', {}, self.clock())
                        self.join.clear(req['request_id'])
            self.session_id, self.sequences = session, {}

    def on_request(self, request):
        """계약 검사를 통과한 요청만 받는다. 답할 수 없는 요청은 결과를 내지 않는다."""
        target, request_id = _target(request), request.get('request_id')
        if (target not in self.targets or target in self.yielded or not request_id
                or self.blocked):
            return False
        if self.store.work(request_id):
            return False
        now = self.clock()
        if self.join and request.get('stage') == 'VERIFY_LOAD':
            from .load_evidence import finite
            times = ('issued_at', 'ttl_sec', 'timeout_sec')
            route = request.get('route')
            if (not all(finite(request.get(k)) for k in times)
                    or not request.get('session_id') or request['issued_at'] > now + 1
                    or not 0 < request['ttl_sec'] <= 5 or not 0 < request['timeout_sec'] <= 300
                    or type(request.get('seq')) is not int or not isinstance(route, dict)
                    or route.get('pickup') not in self.points
                    or request.get('target') != 'vision'
                    or request.get('action') != 'verify_load'):
                return False
        state = 'PENDING'
        if request.get('session_id') != self.session_id:
            state = 'REJECTED_SESSION'
        elif request.get('seq', 0) <= self.sequences.get(target, 0):
            state = 'REJECTED_SEQ'
        elif now > request.get('issued_at', 0) + request.get('ttl_sec', 0):
            state = 'EXPIRED'
        elif request.get('stage') == 'SAFETY':
            state = 'SAFETY_NOTED'
        # 만료된 요청은 순번을 올리지 않는다(늦게 온 큰 순번이 뒤의 정상 요청을 막지 않게).
        if state in ('PENDING', 'SAFETY_NOTED'):
            self.sequences[target] = request['seq']
        self.store.add_work(request_id, state, request, now)
        if state == 'PENDING' and target in self.auto:
            if known_stage(request):
                self._auto(request)
            else:
                self._unknown_stage(request, now)
        return state == 'PENDING'

    def _unknown_stage(self, request, now):
        """모르는 단계는 대기에 두고 경고만 남긴다. 주문 수신 원문에 kind adapter_warning 으로 들어간다."""
        detail = f"{UNKNOWN_STAGE_REASON} · {request.get('stage')} ({request.get('target')})"
        order_id = request.get('order_id')
        if isinstance(order_id, str) and order_id:
            self.store.record_control(
                'adapter_warning', order_id, request['request_id'],
                {'code': 'UNKNOWN_STAGE', 'detail': detail, 'stage': request.get('stage'),
                 'target': request.get('target'), 'robot_id': request.get('robot_id')}, now)
        if self.warn:
            self.warn(f"{detail} · 요청 {request['request_id']}")

    def _auto(self, request):
        """자동 대상 요청에 판정 없이 성공으로 답한다. 지금 답할 수 없으면 대기에 둔다."""
        if not known_stage(request):
            return None  # 모르는 단계에는 성공을 지어내지 않는다
        if self.join and request.get('stage') == 'VERIFY_LOAD':
            return None  # 적재 결합 시험은 근거 3장과 팔 확인으로만 답한다
        try:
            judged = self._judge(request)
            if judged and self.judge_mode == 'enforce':
                if judged['verdict'] == 'pass':
                    return self._finish(request, 'APPROVED', True, '비전 판정 통과',
                                        judged['data'], AUTO_OPERATOR)
                if judged['verdict'] == 'drop':
                    # 결과만 전한다. 다시 해도 되는지는 모르므로 retry_safe 를 붙이지 않는다.
                    return self._finish(request, 'REJECTED', False, judged['reason'],
                                        judged['data'], AUTO_OPERATOR)
                return None
            data = dict(self._evidence(request, None), decision=AUTO_DECISION, unjudged=True)
            if judged:
                if judged['verdict'] == 'wait' and judged['waited_sec'] < self.shadow_wait_sec:
                    return None  # 판정이 설 시간을 준 뒤에 자동으로 답한다
                data['judge'] = {key: judged[key] for key in
                                 ('verdict', 'state', 'reason', 'conditions', 'waited_sec')}
                if 'suppressed' in judged:
                    data['judge']['suppressed'] = judged['suppressed']
            if data.get('stopped') is False:
                return None  # /odom 이 없어 정지를 모른다. 이대로 답하면 관제가 받지 않고 단계가 멈춘다
            return self._finish(request, 'APPROVED', True, '자동 응답(판정 기준 미적용)', data,
                                AUTO_OPERATOR)
        except (KeyError, ValueError, TypeError):
            return None  # 정차 전·자세 없음·발행 차단·형식 어긋남. 다음 주기에 다시 본다

    def _judge(self, request):
        """판정 대상 단계면 판정을 돌려준다. 판정을 쓰지 않으면 None 이다."""
        if self.judge_mode == 'off' or request.get('stage') not in self.judge_stages:
            return None
        row, now = self.store.work(request['request_id']), self.clock()
        judged = self.judge.judge(request, row['created_at'], now)
        problem = self.attribute(request, now) if self.attribute else ''
        if problem:
            original = {key: judged[key] for key in ('verdict', 'state', 'reason', 'data')}
            judged = dict(judged, verdict='wait', reason=problem, data=None)
            if original['verdict'] == 'drop':
                # 귀속 실패를 추락 응답으로 바꾸지 않고 원래 근거만 보존한다.
                judged['suppressed'] = original
                previous = self.judged.get(request['request_id'], {}).get('suppressed')
                if previous != original:
                    self.store.record_control(
                        'judge_suppressed', request['order_id'], request['request_id'],
                        {'reason': problem, 'original': original}, now)
        judged['waited_sec'] = round(now - row['created_at'], 3)
        prev_entry = self.judged.get(request['request_id'], {})
        if (judged['verdict'] == 'wait' and self.max_wait_sec > 0
                and judged['waited_sec'] >= self.max_wait_sec):
            judged['operator_attention'] = True
            if not prev_entry.get('operator_attention'):
                self.store.record_control(
                    'judge_hold_timeout', request['order_id'], request['request_id'],
                    {'waited_sec': judged['waited_sec'], 'reason': judged['reason'],
                     'state': judged['state']}, now)
        self.judged.pop(request['request_id'], None)
        self.judged[request['request_id']] = judged
        for rid in list(self.judged)[:-50]:
            del self.judged[rid]
        return judged

    def retry_auto(self):
        """대기에 남은 자동 대상 요청을 다시 시도한다. 단계 제한 시간이 지난 요청은 건드리지 않는다."""
        sent = []
        for row in self.store.works('PENDING'):
            request = json.loads(row['request_json'])
            timeout = request.get('timeout_sec')
            if (_target(request) not in self.auto or _target(request) in self.yielded
                    or type(timeout) not in (int, float)
                    or self.clock() >= request.get('issued_at', 0) + timeout):
                continue
            result = self._auto(request)
            if result:
                sent.append(result)
        return sent

    def pending(self):
        """승인 대기 요청을 웹에 넘긴다."""
        if self.join:
            for row in self.store.works('PENDING'):
                req = json.loads(row['request_json'])
                deadline = req['issued_at'] + req['timeout_sec']
                if req['stage'] == 'VERIFY_LOAD' and self.clock() >= deadline:
                    self.store.claim_work(req['request_id'], 'EXPIRED_STAGE', {}, self.clock())
                    self.join.clear(req['request_id'])
        return [dict(json.loads(row['request_json']), received_at=row['created_at'],
                     **self._load_view(row))
                for row in self.store.works('PENDING')]

    def order_work_history(self, order_id):
        history = self.store.order_work_history(order_id)
        for item in history:
            if self.join and item['state'] == 'PENDING' and item['stage'] == 'VERIFY_LOAD':
                item.update(self._load_progress(item['request_id'], item.get('request')))
        return history

    def _load_progress(self, rid, req=None):
        now = self.clock()
        frames = [f for f in self.join.frames.get(rid, [])
                  if f['capture_time'] - f['clock_error_sec'] <= now
                  and now - f['capture_time'] + f['clock_error_sec'] <= 3]
        arm = self.join.arm.get(rid)
        limit = (req.get('timeout_sec')
                 if isinstance(req, dict) and type(req.get('timeout_sec')) in (int, float)
                 else ARM_VALID_SEC)
        if arm and not 0 <= now - arm[1] <= limit:
            arm = None
        return {'load_join': True, 'evidence_count': len(frames),
                'arm_checked': arm is not None,
                'wait_reason': self.join.reasons.get(rid, '적재 영상 대기'),
                'pending_data': {'evidence': frames, 'operator': arm[0] if arm else None,
                                 'arm_confirmed_at': arm[1] if arm else None}}

    def _load_view(self, row):
        req = json.loads(row['request_json'])
        if _target(req) in self.auto and not known_stage(req):
            return {'wait_reason': UNKNOWN_STAGE_REASON, 'unknown_stage': True}
        if not self.join or req.get('stage') != 'VERIFY_LOAD':
            judged = self.judged.get(row['request_id'])
            return ({'judge_mode': self.judge_mode, 'wait_reason': judged['reason'],
                     'arm_checked': judged['conditions'].get('arm') is True,
                     'operator_attention': judged.get('operator_attention') is True,
                     'judge': {key: judged[key] for key in
                               ('verdict', 'state', 'conditions', 'suppressed',
                                'operator_attention')
                               if key in judged}}
                    if judged else {})
        return self._load_progress(row['request_id'], req)

    def _load_request(self, rid):
        req = self._request(rid)
        if (not self.join or req['stage'] != 'VERIFY_LOAD' or req['target'] != 'vision'
                or req['action'] != 'verify_load' or self.blocked
                or req['session_id'] != self.session_id
                or self.clock() >= req['issued_at'] + req['timeout_sec']):
            raise ValueError('현재 처리할 수 없는 적재 요청')
        return req

    def on_evidence(self, frame):
        if self.exclusive and not self.exclusive():
            return
        for row in self.store.works('PENDING'):
            rid = row['request_id']
            try:
                req = self._load_request(rid)
            except ValueError:
                continue
            self.join.observe(req, row['created_at'], frame, self.clock())
            try:
                self._try_load(req)
            except ValueError:
                self.join.reasons[rid] = '다른 결과 발행자 또는 세션 변경'

    def confirm_arm(self, rid, operator):
        req = self._load_request(rid)
        self.join.arm[rid] = (self._operator(operator), self.clock())
        return self._try_load(req) or {'pending': True}

    def _try_load(self, req):
        rid = req['request_id']
        frames = self.join.frames.get(rid, [])
        now = self.clock()
        arm = self.join.arm.get(rid)
        # VERIFY_LOAD 는 ARM_LOAD 완료 뒤 단계라 같은 요청의 팔 퇴피 확인은 단계 제한 시간 동안 유효하다.
        # 세션 변경·단계 만료는 join.clear 가 지운다.
        timeout = req.get('timeout_sec')
        limit = timeout if type(timeout) in (int, float) else ARM_VALID_SEC
        if arm and not 0 <= now - arm[1] <= limit:
            self.join.arm.pop(rid, None)
            self.join.reasons[rid] = '팔 퇴피 확인 만료'
            return None
        if not arm or len(frames) < 3:
            return None
        problem = self.join.attribution(req, now)
        if problem or any(now - f['capture_time'] + f['clock_error_sec'] > 3 for f in frames):
            frames.clear()
            self.join.reasons[rid] = problem or '적재 표본 만료'
            return None
        data = {'load_present': True, 'arm_safe': True, 'evidence': frames,
                'arm_confirmed_at': arm[1], 'decision': 'camera_and_operator'}
        return self._finish(req, 'APPROVED', True, '', data, arm[0])

    def manual_load(self, rid, operator, note, load_present, arm_safe):
        req = self._load_request(rid)
        order = self.join.core.orders.get(req['order_id'], {})
        tasks_at = self.join.core.tasks_at
        if (order.get('request_id') != rid or order.get('stage') != req['stage']
                or order.get('state') != 'RUNNING' or order.get('robot_id') != req['robot_id']
                or tasks_at is None or not 0 <= self.clock() - tasks_at <= 3):
            raise ValueError('현재 주문 확인 필요')
        if (not isinstance(note, str) or not note.strip()
                or load_present is not True or arm_safe is not True):
            raise ValueError('수동 전환 사유·실제 적재·팔 퇴피 확인 필요')
        data = {'load_present': True, 'arm_safe': True, 'decision': 'operator_override'}
        return self._finish(req, 'APPROVED', True, note, data, self._operator(operator))

    def _request(self, request_id):
        row = self.store.work(request_id)
        if not row or row['state'] != 'PENDING':
            raise KeyError(request_id)
        return json.loads(row['request_json'])

    def _dock(self, request):
        """정차 오차는 amcl_pose와 지점 좌표의 차이로만 계산한다."""
        state = self.robot_state(request['robot_id'])
        point = self.points.get(request['route'][DOCK_SIDE[request['stage']]])
        if not point or state.get('pose_x') is None:
            raise ValueError('자세 또는 목표 지점이 없어 정차 오차를 계산할 수 없습니다')
        speed = state.get('speed_mps')
        if speed is not None and speed > MOVING_SPEED_MPS:
            raise ValueError('로봇이 아직 움직이고 있습니다')
        return {'xy_m': math.hypot(state['pose_x'] - point[0], state['pose_y'] - point[1]),
                'yaw_deg': yaw_error_deg(state['pose_yaw'], point[2]),
                # /odom 이 없으면 정지를 확인하지 못한 것이다.
                'stopped': speed is not None, 'base_hold': True}

    def _evidence(self, request, sku):
        stage = request['stage']
        if stage in DOCK_SIDE:
            return self._dock(request)
        if stage in ('MARKER', 'QR'):
            return {'sku': sku or request['sku']}
        return dict(EVIDENCE.get(stage, {}))

    def _finish(self, request, state, success, detail, data, operator):
        result = {'request_id': request['request_id'], 'order_id': request['order_id'],
                  'robot_id': request['robot_id'], 'stage': request['stage'],
                  'source': request['target'], 'measured': True, 'finished': True,
                  'success': success, 'detail': detail,
                  # 카메라 3프레임 + 운영자 팔 확인 결합과 자동 응답은 수동 판정이 아니다.
                  'data': dict(data, manual=data.get('decision') not in (
                      'camera_and_operator', AUTO_DECISION, JUDGED_DECISION), operator=operator)}
        rid = request['request_id']
        if (self.blocked or request['target'] in self.yielded
                or request['session_id'] != self.session_id
                or (self.exclusive and not self.exclusive())):
            raise ValueError('결과 발행 차단 또는 세션 변경')
        if not self.store.claim_work(rid, 'PUBLISH_UNCONFIRMED', result, self.clock()):
            raise ValueError('이미 처리한 요청')
        if self.join:
            self.join.clear(rid)
        self.judged.pop(rid, None)
        self.publish(result)
        self.store.finish_work(rid, state, result, self.clock())
        return result

    @staticmethod
    def _operator(operator):
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError('operator 필요')
        return operator.strip()

    def approve(self, request_id, operator, note='', sku=None):
        """운영자가 현장 확인을 마친 단계를 성공으로 답한다."""
        operator, request = self._operator(operator), self._request(request_id)
        if self.join and request['stage'] == 'VERIFY_LOAD':
            raise ValueError('팔 퇴피 확인 또는 전체 수동 확인을 선택하세요')
        return self._finish(request, 'APPROVED', True, note, self._evidence(request, sku),
                            operator)

    def reject(self, request_id, operator, note='', retry_safe=False):
        """실패로 답한다. retry_safe가 없으면 관제가 중단하고 관리자 확인을 요구한다."""
        operator, request = self._operator(operator), self._request(request_id)
        data = {'retry_safe': True} if retry_safe is True else {}
        return self._finish(request, 'REJECTED', False, note, data, operator)
