"""사람 승인으로 /fleet/work_request에 답하는 어댑터. 로봇과 팔을 움직이지 않는다."""

import json
import math
import time

MOVING_SPEED_MPS = 0.03
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

    def __init__(self, store, publish, targets, points, robot_state, clock=time.time):
        self.store, self.publish, self.targets = store, publish, set(targets)
        self.points, self.robot_state, self.clock = points, robot_state, clock
        self.session_id = None
        self.sequences = {}
        self.blocked = ''

    def on_heartbeat(self, heartbeat):
        """현재 관제 세션을 기억한다. 세션이 바뀌면 순번도 새로 시작한다."""
        session = heartbeat.get('session_id')
        if session != self.session_id:
            self.session_id, self.sequences = session, {}

    def on_request(self, request):
        """계약 검사를 통과한 요청만 받는다. 답할 수 없는 요청은 결과를 내지 않는다."""
        target, request_id = request.get('target'), request.get('request_id')
        if target not in self.targets or not request_id or self.blocked:
            return False
        if self.store.work(request_id):
            return False
        now = self.clock()
        state = 'PENDING'
        if request.get('session_id') != self.session_id:
            state = 'REJECTED_SESSION'
        elif request.get('seq', 0) <= self.sequences.get(target, 0):
            state = 'REJECTED_SEQ'
        elif now > request.get('issued_at', 0) + request.get('ttl_sec', 0):
            state = 'EXPIRED'
        elif request.get('stage') == 'SAFETY':
            state = 'SAFETY_NOTED'
        if state in ('PENDING', 'SAFETY_NOTED', 'EXPIRED'):
            self.sequences[target] = request['seq']
        self.store.add_work(request_id, state, request, now)
        return state == 'PENDING'

    def pending(self):
        """승인 대기 요청을 웹에 넘긴다."""
        return [dict(json.loads(row['request_json']), received_at=row['created_at'])
                for row in self.store.works('PENDING')]

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
                'stopped': True, 'base_hold': True}

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
                  'data': dict(data, manual=True, operator=operator)}
        self.publish(result)
        self.store.finish_work(request['request_id'], state, result, self.clock())
        return result

    @staticmethod
    def _operator(operator):
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError('operator 필요')
        return operator.strip()

    def approve(self, request_id, operator, note='', sku=None):
        """운영자가 현장 확인을 마친 단계를 성공으로 답한다."""
        operator, request = self._operator(operator), self._request(request_id)
        return self._finish(request, 'APPROVED', True, note, self._evidence(request, sku),
                            operator)

    def reject(self, request_id, operator, note='', retry_safe=False):
        """실패로 답한다. retry_safe가 없으면 관제가 중단하고 관리자 확인을 요구한다."""
        operator, request = self._operator(operator), self._request(request_id)
        data = {'retry_safe': True} if retry_safe is True else {}
        return self._finish(request, 'REJECTED', False, note, data, operator)
