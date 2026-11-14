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

구성 (mqtt_bridge_node.py 가 부른다):
- RateGate: 너무 자주 오는 토픽(/tf 등)의 전송 횟수를 줄인다.
- encode_envelope / decode_envelope: ROS 메시지 내용을 MQTT 로 보낼 JSON 봉투로 싸고 푼다.
- check_publish_domain / check_robot_publish_domain: "이 도메인에서 발행해도 되는가"를
  시작하기 전에 검사한다. 잘못된 도메인에 명령이 나가는 사고를 막는 마지막 문지기다.
  돌려주는 값이 빈 문자열이면 허용, 아니면 거부 사유다(노드가 출력하고 종료 코드 2 로 끝낸다).

도메인 규칙 요약 (ISOLATED 는 시험용 101/102):
              시험(101/102)   관제(200)         로봇(10)
  pc 역할        허용         확인 값 필요         거부
  robot 역할     허용         거부            확인 값 필요
"""

import json

# 시험 전용 격리 도메인: 어떤 이름으로 발행해도 된다. 실제 도메인과 섞이지 않는다.
# (시험 때는 CycloneDDS 를 루프백 전용으로 설정해 네트워크로 새지 않게 한다.)
ISOLATED_DOMAINS = ('101', '102')
# 도메인 10 은 로봇 도메인이라 관제 쪽 발행 역할이 쓰면 안 된다.
ROBOT_DOMAIN = '10'


class RateGate:
    """
    직전에 통과시킨 시각 기준으로 최소 간격 안에 온 메시지를 막는다.

    max_rate_hz 가 0 이하이면 모두 통과시킨다 (원래 주기 그대로).
    예: max_rate_hz=10 이면 간격이 0.1 초 미만인 메시지는 버린다. 버린 메시지를 모아 두지
    않고 그냥 버리므로, 값이 계속 바뀌는 센서·좌표 토픽에만 쓴다(최신 값이 곧 다음에 온다).
    """

    def __init__(self, max_rate_hz):
        self._interval = 1.0 / max_rate_hz if max_rate_hz > 0 else 0.0
        self._last = None

    def allow(self, now):
        """now(초, 단조 시계)에 통과시킬지 돌려준다. 통과시키면 기준 시각을 갱신한다."""
        if self._interval > 0.0 and self._last is not None \
                and now - self._last < self._interval:
            return False  # 막힌 메시지는 기준 시각을 갱신하지 않는다(간격은 통과한 것끼리 잰다)
        self._last = now
        return True


def to_json_default(value):
    """
    직렬화기가 모르는 타입(numpy 배열, array.array 등)을 리스트로 바꾼다.

    ROS 메시지의 배열 필드(LaserScan.ranges 등)가 이런 타입으로 오기 때문이다.
    """
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError(f'JSON 으로 바꿀 수 없는 타입: {type(value)}')


def encode_envelope(msg_type, sent_at, data):
    """
    {"type","sent_at","data"} 봉투를 JSON 문자열로 만든다.

    type 은 받는 쪽이 메시지 종류를 확인하는 용도, sent_at 은 받는 쪽이 "오래된 명령"을
    버릴 때 쓰는 보낸 시각, data 는 ROS 메시지 내용이다.
    """
    return json.dumps(
        {'type': msg_type, 'sent_at': sent_at, 'data': data}, default=to_json_default)


def decode_envelope(payload, expected_type):
    """JSON 봉투를 풀어 data 딕셔너리와 sent_at 을 돌려준다. 어긋나면 ValueError."""
    envelope = json.loads(payload)
    # 주제가 같아도 타입이 다르면 엉뚱한 메시지로 바꾸게 되므로 여기서 걸러낸다.
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
        # 실제 로봇 도메인: 사람이 값을 직접 적어야 한다(기본값이 우연히 맞아 움직이는 것을 막는다).
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
        # 실제 관제 도메인: GUI·구역 관리가 쓰는 곳이라 확인 값이 있어야 한다.
        if confirm_real_domain == str(pc_domain):
            return ''
        return (f'실제 관제 도메인 {pc_domain} 에 발행하려면 '
                f'confirm_real_domain:={pc_domain} 을 명시해야 한다')
    if domain == ROBOT_DOMAIN:
        # 관제 쪽 노드가 로봇 도메인에 발행하면 로봇이 받는 값과 섞인다. 확인 값으로도 못 푼다.
        return f'로봇 도메인 {ROBOT_DOMAIN} 에는 관제 쪽 발행을 하지 않는다'
    return (f'ROS_DOMAIN_ID={domain or "없음"} 는 허용되지 않는다 '
            f'(허용: {"/".join(ISOLATED_DOMAINS)}, 확인 후 {pc_domain})')
