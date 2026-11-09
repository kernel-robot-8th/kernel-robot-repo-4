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
"""

import math

AXES = ('x', 'y', 'z')


def _magnitude(vector):
    return math.sqrt(sum(float(vector[axis]) ** 2 for axis in AXES))


def _scaled(vector, factor):
    return {axis: float(vector[axis]) * factor for axis in AXES}


def clamp_twist(data, max_linear, max_angular):
    """
    속도 상한을 넘으면 방향은 유지한 채 크기만 줄인 Twist 를 돌려준다.

    선속도 3축은 같은 비율로, 각속도 3축도 같은 비율로 줄인다(한 축만 자르면 궤적이 휜다).
    상한이 0 이하이면 그 항목은 제한하지 않는다. (새 Twist, 줄였는지 여부)를 돌려준다.
    """
    linear = {axis: float(data['linear'][axis]) for axis in AXES}
    angular = {axis: float(data['angular'][axis]) for axis in AXES}
    clamped = False
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
    """모든 속도 성분이 0 이면 True."""
    return _magnitude(data['linear']) == 0.0 and _magnitude(data['angular']) == 0.0


def is_stale(sent_at, now, max_age_ms):
    """
    보낸 시각(sent_at)이 max_age_ms 보다 오래됐으면 True.

    max_age_ms 가 0 이하이면 검사하지 않는다. 장비 사이 시계가 어긋나면 오판할 수 있어
    PC 와 로봇의 시계를 맞춘 뒤에만 켠다.
    """
    return max_age_ms > 0 and (now - sent_at) * 1000.0 > max_age_ms


class Watchdog:
    """
    마지막 속도 명령 뒤 timeout_ms 가 지나면 정지를 한 번 요청하는 감시기.

    0 이 아닌 명령이 오면 감시를 시작(arm)하고, 0 명령이 오면 이미 멈춘 것이라 해제한다.
    정지를 요청한 뒤에는 다음 0 이 아닌 명령이 올 때까지 다시 요청하지 않는다.
    """

    def __init__(self, timeout_ms):
        self._timeout = timeout_ms / 1000.0
        self._armed = False
        self._last = 0.0
        self.trips = 0

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
