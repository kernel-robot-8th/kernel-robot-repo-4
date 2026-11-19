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
관제 작업 요청 검사와 결과 만들기 (ROS 없는 순수 로직).

규격의 정본은 관제 코드다. 요청은 cobot_fleet_control 의 fleet_control_node.work() 와
scenario_runtime 이 만들고, 결과는 scenario_runtime.receive() 가 검사한다.
receive() 는 request_id·robot_id·stage·source·measured·finished 중 하나라도 틀리면
결과를 조용히 버린다. 그래서 결과의 이 필드들은 받은 요청에서 그대로 복사한다.

실패 결과에 data.retry_safe=true 가 없으면 관제는 재시도하지 않고 주문을 보류한다.
팔이 움직이지 않았음이 확실한 거절(탐지 안 됨·만료·작업 중)에만 retry_safe 를 붙인다.
"""

from collections import deque
import json
import math

WORK_ACTIONS = frozenset({'pick', 'load', 'unload', 'warehouse_store', 'arrange_shoe'})
SAFETY_ACTIONS = frozenset({'hold', 'release_hold'})
# 정지는 만료·순번 역행이어도 실행한다. 멈춤을 거절하는 쪽이 더 위험하기 때문이다 (D4 추천안).
STOP_ACTIONS = frozenset({'hold'})
MAX_MESSAGE_BYTES = 16384

IGNORE, EXECUTE, REJECT = 'IGNORE', 'EXECUTE', 'REJECT'
REQUIRED_TEXT = ('request_id', 'stage', 'action', 'session_id')


def decode(text):
    """JSON 문자열을 dict 로. 관제와 같은 16 KiB 제한을 둔다. 실패하면 ValueError."""
    if len(text.encode('utf-8')) > MAX_MESSAGE_BYTES:
        raise ValueError('JSON 요청 크기는 16 KiB 이하')
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('JSON 객체 필요')
    return data


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class RequestFilter:
    """
    팔 1대의 요청 판정기. check() 는 (판정, 이유, retry_safe) 를 돌려준다.

    IGNORE: 내 요청이 아니거나, 결과를 보낼 수 없거나, 이미 처리한 요청 (로그만)
    REJECT: 실패 결과를 돌려줄 요청
    EXECUTE: 실행할 요청
    """

    def __init__(self, arm_id, dedupe_size=256):
        self.arm_id = arm_id
        self.session_id = None
        self.last_seq = None
        self.seen = deque(maxlen=dedupe_size)

    def check(self, request, now):
        """요청 하나를 판정한다. 판정한 요청은 다시 와도 IGNORE 다."""
        if request.get('target') != self.arm_id:
            return IGNORE, '다른 장치 요청', False
        for key in REQUIRED_TEXT:
            if not isinstance(request.get(key), str) or not request[key]:
                return IGNORE, f'{key} 없음', False
        if (not isinstance(request.get('seq'), int) or isinstance(request.get('seq'), bool)
                or not _finite(request.get('issued_at')) or not _finite(request.get('ttl_sec'))):
            return IGNORE, 'seq·issued_at·ttl_sec 형식 오류', False
        if request['request_id'] in self.seen:
            return IGNORE, '이미 처리한 request_id', False
        self.seen.append(request['request_id'])
        action = request['action']
        stop = action in STOP_ACTIONS
        if request['session_id'] != self.session_id:
            # 관제 노드가 다시 켜지면 session_id 가 바뀌고 seq 는 1부터 다시 센다.
            self.session_id, self.last_seq = request['session_id'], None
        stale = self.last_seq is not None and request['seq'] <= self.last_seq
        if not stale:
            self.last_seq = request['seq']
        if stale and not stop:
            return IGNORE, f'순번 역행 (seq {request["seq"]} <= {self.last_seq})', False
        issued, ttl = request['issued_at'], request['ttl_sec']
        if not stop and now > issued + ttl:
            return REJECT, f'요청 만료 ({now - issued:.1f}s > ttl {ttl}s)', True
        if not stop and issued > now + ttl:
            return REJECT, '요청 시각이 미래: 두 PC 시계 동기화 확인', True
        if action not in WORK_ACTIONS | SAFETY_ACTIONS:
            return REJECT, f'모르는 action: {action}', False
        return EXECUTE, '', False


def make_result(request, arm_id, success, data=None, detail=''):
    """관제 receive() 가 받아들이는 최종 결과 dict. 실측·완료된 결과만 만든다."""
    result = {
        'request_id': request.get('request_id'),
        'order_id': request.get('order_id'),
        'robot_id': request.get('robot_id'),
        'stage': request.get('stage'),
        'source': arm_id,
        'measured': True,
        'finished': True,
        'success': bool(success),
        'data': dict(data or {}),
    }
    if detail:
        result['detail'] = detail
    return result


def reject_result(request, arm_id, detail, retry_safe):
    """팔을 움직이지 않은 거절 결과. 움직이지 않았으므로 팔은 안전 자세 그대로다."""
    data = {'retry_safe': True} if retry_safe else {}
    return make_result(request, arm_id, False, data, detail)


def encode(payload):
    """한글을 그대로 담은 JSON 문자열."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
