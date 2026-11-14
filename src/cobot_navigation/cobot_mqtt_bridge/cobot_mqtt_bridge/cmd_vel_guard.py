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
속도 명령(cmd_vel) 안전 규칙: 속도 상한 클램프, 오래된 메시지 판정, 워치독.

왜 필요한가: MQTT 를 거치는 속도 명령이 끊기거나 늦게 도착해도 로봇이 계속 움직이면 안 된다.
ROS 에 의존하지 않고 Twist 를 딕셔너리({'linear': {x,y,z}, 'angular': {x,y,z}})로 다뤄서
단독 시험이 된다. 값(상한, 시간)은 모두 호출하는 쪽이 파라미터로 넘기며 기본값을 두지 않는다.

세 가지 방어선 (mqtt_bridge_node.py 의 robot 역할이 명령을 받을 때 차례로 쓴다):
1. is_stale: 네트워크 지연으로 늦게 도착한 명령은 버린다. (이미 지난 명령으로 움직이지 않게)
2. clamp_twist: 너무 빠른 명령은 상한까지 줄인다. (잘못된 값이 와도 최고 속도가 제한되게)
3. Watchdog: 명령이 끊기면 0 속도를 한 번 내보낸다. (연결이 끊긴 채 마지막 속도로 달리지 않게)
세 값 중 하나라도 0 이면 그 방어선이 꺼진 것이다. 그래서 실제 로봇 도메인에서는 노드가
시작할 때 워치독·선속도·각속도 상한이 모두 0 보다 큰지 확인한다(_check_cmd_vel_guard).

Twist 모양: {'linear': {'x':..,'y':..,'z':..}, 'angular': {'x':..,'y':..,'z':..}}
"""

import math

AXES = ('x', 'y', 'z')


def _magnitude(vector):
    """3축 벡터의 크기(길이)를 돌려준다. 예: x=0.3, y=0.4 이면 0.5."""
    return math.sqrt(sum(float(vector[axis]) ** 2 for axis in AXES))


def _scaled(vector, factor):
    """3축 벡터의 모든 축에 같은 비율을 곱한다. 방향은 그대로, 크기만 바뀐다."""
    return {axis: float(vector[axis]) * factor for axis in AXES}


def clamp_twist(data, max_linear, max_angular):
    """
    속도 상한을 넘으면 방향은 유지한 채 크기만 줄인 Twist 를 돌려준다.

    선속도 3축은 같은 비율로, 각속도 3축도 같은 비율로 줄인다(한 축만 자르면 궤적이 휜다).
    상한이 0 이하이면 그 항목은 제한하지 않는다. (새 Twist, 줄였는지 여부)를 돌려준다.
    예: 상한 0.15 에 x=0.30 이 오면 x=0.15 로 줄고, x=0.30, y=0.40(크기 0.5)이면
    x=0.09, y=0.12 로 줄어 비율(방향)이 같다.
    """
    linear = {axis: float(data['linear'][axis]) for axis in AXES}
    angular = {axis: float(data['angular'][axis]) for axis in AXES}
    clamped = False
    # 각 축을 따로 자르지 않고 크기(speed)로 비율을 구한 뒤 모든 축에 곱한다.
    speed = _magnitude(linear)
    if max_linear > 0 and speed > max_linear:
        linear = _scaled(linear, max_linear / speed)
        clamped = True
    turn = _magnitude(angular)
    if max_angular > 0 and turn > max_angular:
        angular = _scaled(angular, max_angular / turn)
        clamped = True
    return {'linear': linear, 'angular': angular}, clamped


def is_zero(data):
    """
    모든 속도 성분이 0 이면 True.

    0 명령은 "멈춰라"라는 뜻이라 워치독이 더 지켜볼 필요가 없다(feed 에서 감시를 푼다).
    """
    return _magnitude(data['linear']) == 0.0 and _magnitude(data['angular']) == 0.0


def is_stale(sent_at, now, max_age_ms):
    """
    보낸 시각(sent_at)이 max_age_ms 보다 오래됐으면 True.

    max_age_ms 가 0 이하이면 검사하지 않는다. 장비 사이 시계가 어긋나면 오판할 수 있어
    PC 와 로봇의 시계를 맞춘 뒤에만 켠다.
    예: max_age_ms=500 이고 보낸 지 0.8 초 지난 명령이면 True(버린다).
    """
    return max_age_ms > 0 and (now - sent_at) * 1000.0 > max_age_ms


class Watchdog:
    """
    마지막 속도 명령 뒤 timeout_ms 가 지나면 정지를 한 번 요청하는 감시기.

    0 이 아닌 명령이 오면 감시를 시작(arm)하고, 0 명령이 오면 이미 멈춘 것이라 해제한다.
    정지를 요청한 뒤에는 다음 0 이 아닌 명령이 올 때까지 다시 요청하지 않는다.
    (0 속도를 계속 쏟아내면 다른 노드의 명령을 방해하므로 한 번만 내보낸다.)

    사용 순서: 명령이 올 때마다 feed() -> 주기적으로 expired() 를 확인하고 True 면 정지 발행.
    """

    def __init__(self, timeout_ms):
        self._timeout = timeout_ms / 1000.0
        self._armed = False  # True 면 "움직이는 명령을 받았고 아직 정지하지 않은" 상태
        self._last = 0.0  # 마지막 명령을 받은 시각(단조 시계, 초)
        self.trips = 0  # 워치독이 정지를 요청한 횟수 (종료 요약과 시험에서 확인한다)

    @property
    def armed(self):
        """감시 중(마지막 명령이 0 이 아니었음)이면 True."""
        return self._armed

    def feed(self, now, nonzero):
        """명령을 받았을 때 부른다. now 는 단조 시계의 초."""
        self._last = now
        self._armed = bool(nonzero)

    def expired(self, now):
        """정지를 요청해야 하면 True 를 돌려주고 감시를 푼다. timeout 이 0 이하면 항상 False."""
        if self._timeout > 0 and self._armed and now - self._last >= self._timeout:
            self._armed = False
            self.trips += 1
            return True
        return False

    def disarm(self):
        """종료 정지를 이미 보냈을 때 감시를 푼다."""
        self._armed = False
