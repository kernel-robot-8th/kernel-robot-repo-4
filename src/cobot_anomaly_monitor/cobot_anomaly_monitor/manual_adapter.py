"""사람 승인으로 /fleet/work_request에 답하는 어댑터. 로봇과 팔을 움직이지 않는다."""

import json
import math
import time

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


def yaw_error_deg(actual, target):
    """두 방향의 차이를 -180~180도로 돌려준다."""
    return math.degrees(math.atan2(math.sin(actual - target), math.cos(actual - target)))


class ManualAdapter:
    """target이 자기 담당인 요청을 대기열에 올리고 운영자 판단만 결과로 낸다."""

    def __init__(self, store, publish, targets, points, robot_state, clock=time.time, join=None,
                 exclusive=None):
        self.store, self.publish, self.targets = store, publish, set(targets)
        self.points, self.robot_state, self.clock = points, robot_state, clock
        self.session_id = None
        self.sequences = {}
        self.blocked = ''
        self.join = join
        self.exclusive = exclusive

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
                        self.store.claim_work(req['request_id'], 'EXPIRED_SESSION', {}, self.clock())
                        self.join.clear(req['request_id'])
            self.session_id, self.sequences = session, {}

    def on_request(self, request):
        """계약 검사를 통과한 요청만 받는다. 답할 수 없는 요청은 결과를 내지 않는다."""
        target, request_id = request.get('target'), request.get('request_id')
        if target not in self.targets or not request_id or self.blocked:
            return False
        if self.store.work(request_id):
            return False
        now = self.clock()
        if self.join and request.get('stage') == 'VERIFY_LOAD':
            from .load_evidence import finite
            times = ('issued_at', 'ttl_sec', 'timeout_sec')
            if (not all(finite(request.get(k)) for k in times)
                    or not request.get('session_id') or request['issued_at'] > now + 1
                    or not 0 < request['ttl_sec'] <= 5 or not 0 < request['timeout_sec'] <= 300
                    or type(request.get('seq')) is not int or not isinstance(request.get('route'), dict)
                    or request['route'].get('pickup') not in self.points
                    or request.get('target') != 'vision' or request.get('action') != 'verify_load'):
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
        return state == 'PENDING'

    def pending(self):
        """승인 대기 요청을 웹에 넘긴다."""
        if self.join:
            for row in self.store.works('PENDING'):
                req = json.loads(row['request_json'])
                if req['stage'] == 'VERIFY_LOAD' and self.clock() >= req['issued_at'] + req['timeout_sec']:
                    self.store.claim_work(req['request_id'], 'EXPIRED_STAGE', {}, self.clock())
                    self.join.clear(req['request_id'])
        return [dict(json.loads(row['request_json']), received_at=row['created_at'], **self._load_view(row))
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
        return dict(load_join=True, evidence_count=len(frames), arm_checked=arm is not None,
                    wait_reason=self.join.reasons.get(rid, '적재 영상 대기'),
                    pending_data=dict(evidence=frames, operator=arm[0] if arm else None,
                                      arm_confirmed_at=arm[1] if arm else None))

    def _load_view(self, row):
        req = json.loads(row['request_json'])
        if not self.join or req.get('stage') != 'VERIFY_LOAD':
            return {}
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
        limit = req.get('timeout_sec') if type(req.get('timeout_sec')) in (int, float) else ARM_VALID_SEC
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
        data = dict(load_present=True, arm_safe=True, evidence=frames,
                    arm_confirmed_at=arm[1], decision='camera_and_operator')
        return self._finish(req, 'APPROVED', True, '', data, arm[0])

    def manual_load(self, rid, operator, note, load_present, arm_safe):
        req = self._load_request(rid)
        order = self.join.core.orders.get(req['order_id'], {})
        if (order.get('request_id') != rid or order.get('stage') != req['stage']
                or order.get('state') != 'RUNNING' or order.get('robot_id') != req['robot_id']
                or self.join.core.tasks_at is None or not 0 <= self.clock() - self.join.core.tasks_at <= 3):
            raise ValueError('현재 주문 확인 필요')
        if not isinstance(note, str) or not note.strip() or load_present is not True or arm_safe is not True:
            raise ValueError('수동 전환 사유·실제 적재·팔 퇴피 확인 필요')
        data = dict(load_present=True, arm_safe=True, decision='operator_override')
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
                  # 카메라 3프레임 + 운영자 팔 확인 결합은 수동 판정이 아니다.
                  'data': dict(data, manual=data.get('decision') != 'camera_and_operator',
                               operator=operator)}
        rid = request['request_id']
        if (self.blocked or request['session_id'] != self.session_id
                or (self.exclusive and not self.exclusive())):
            raise ValueError('결과 발행 차단 또는 세션 변경')
        if not self.store.claim_work(rid, 'PUBLISH_UNCONFIRMED', result, self.clock()):
            raise ValueError('이미 처리한 요청')
        if self.join:
            self.join.clear(rid)
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
