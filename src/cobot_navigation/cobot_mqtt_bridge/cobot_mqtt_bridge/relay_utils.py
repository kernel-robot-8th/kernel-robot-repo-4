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
중계의 작은 규칙 모음: 전송 상한, JSON 봉투, 도메인 안전 검사.

ROS 객체 없이 시험할 수 있는 것만 둔다. 스파이크(scripts/spikes/mqtt/core/mqtt_ros_relay.py)
에서 검증된 규칙을 옮겨 왔다.
"""

import json

# 시험 전용 격리 도메인: 어떤 이름으로 발행해도 된다. 실제 도메인과 섞이지 않는다.
ISOLATED_DOMAINS = ('101', '102')
# 도메인 10 은 로봇 도메인이라 관제 쪽 발행 역할이 쓰면 안 된다.
ROBOT_DOMAIN = '10'


class RateGate:
    """
    직전에 통과시킨 시각 기준으로 최소 간격 안에 온 메시지를 막는다.

    max_rate_hz 가 0 이하이면 모두 통과시킨다 (원래 주기 그대로).
    """

    def __init__(self, max_rate_hz):
        self._interval = 1.0 / max_rate_hz if max_rate_hz > 0 else 0.0
        self._last = None

    def allow(self, now):
        """now(초, 단조 시계)에 통과시킬지 돌려준다. 통과시키면 기준 시각을 갱신한다."""
        if self._interval > 0.0 and self._last is not None \
                and now - self._last < self._interval:
            return False
        self._last = now
        return True


def to_json_default(value):
    """직렬화기가 모르는 타입(numpy 배열, array.array 등)을 리스트로 바꾼다."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError(f'JSON 으로 바꿀 수 없는 타입: {type(value)}')


def encode_envelope(msg_type, sent_at, data):
    """{"type","sent_at","data"} 봉투를 JSON 문자열로 만든다."""
    return json.dumps(
        {'type': msg_type, 'sent_at': sent_at, 'data': data}, default=to_json_default)


def decode_envelope(payload, expected_type):
    """JSON 봉투를 풀어 data 딕셔너리와 sent_at 을 돌려준다. 어긋나면 ValueError."""
    envelope = json.loads(payload)
    if envelope.get('type') != expected_type:
        raise ValueError(f"타입 불일치: {envelope.get('type')} != {expected_type}")
    return envelope['data'], float(envelope.get('sent_at', 0.0))


def check_robot_publish_domain(domain, confirm_real_domain, robot_domain):
    """
    로봇 쪽(robot) 역할이 명령을 발행해도 되는 도메인인지 사유를 돌려준다.

    빈 문자열이면 허용. 시험 도메인(101/102)은 허용하고, 로봇 도메인은 확인 값이 같을
    때만 허용하며(실제 로봇이 움직일 수 있다), 그 밖의 값은 거부한다.
    """
    if domain in ISOLATED_DOMAINS:
        return ''
    if domain == str(robot_domain):
        if confirm_real_domain == str(robot_domain):
            return ''
        return (f'실제 로봇 도메인 {robot_domain} 에 명령을 발행하려면 '
                f'confirm_real_domain:={robot_domain} 을 명시해야 한다')
    return (f'ROS_DOMAIN_ID={domain or "없음"} 에서는 명령을 발행하지 않는다 '
            f'(허용: {"/".join(ISOLATED_DOMAINS)}, 확인 후 {robot_domain})')


def check_publish_domain(domain, confirm_real_domain, pc_domain):
    """
    관제 쪽(pc) 발행 역할이 이 도메인에서 시작해도 되는지 사유를 돌려준다.

    빈 문자열이면 허용. 시험 도메인(101/102)은 허용하고, 관제 도메인은 확인 값이 같을
    때만 허용하며, 로봇 도메인(10)이나 그 밖의 값은 거부한다.
    """
    if domain in ISOLATED_DOMAINS:
        return ''
    if domain == str(pc_domain):
        if confirm_real_domain == str(pc_domain):
            return ''
        return (f'실제 관제 도메인 {pc_domain} 에 발행하려면 '
                f'confirm_real_domain:={pc_domain} 을 명시해야 한다')
    if domain == ROBOT_DOMAIN:
        return f'로봇 도메인 {ROBOT_DOMAIN} 에는 관제 쪽 발행을 하지 않는다'
    return (f'ROS_DOMAIN_ID={domain or "없음"} 는 허용되지 않는다 '
            f'(허용: {"/".join(ISOLATED_DOMAINS)}, 확인 후 {pc_domain})')
