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
팔 동작 백엔드 (ROS 없는 순수 로직).

노드는 '요청을 받아 결과를 돌려주는 일' 만 하고 실제 동작은 백엔드에 맡긴다.
실제 팔 백엔드(정책·MoveIt 등)는 로봇팔 팀이 ArmBackend 를 상속해 추가하고
make_backend() 에 이름을 등록하면 된다.

- none: 백엔드 없음. 모든 작업을 거절한다 (기본값). 실물 PC 에서 실수로 가짜 성공을 보내지 않게.
- fake: 정해진 시간 뒤 성공을 돌려준다. 격리 도메인 전용 (check_domain).
"""

# 실물이 쓰는 도메인. cobot_mock 과 같은 규칙이다 (코드는 import 하지 않는다, CLAUDE.md 3-6).
FORBIDDEN_DOMAINS = frozenset({0, 10, 12, 20, 30, 100})


def check_domain(env):
    """가짜 결과를 내도 되는 도메인인지 본다. (ok, 메시지) 를 돌려준다."""
    raw = env.get('ROS_DOMAIN_ID', '')
    try:
        domain = int(raw)
    except ValueError:
        return False, 'ROS_DOMAIN_ID 가 비어 있음: 격리 도메인(예: 101)을 지정하세요'
    if domain in FORBIDDEN_DOMAINS:
        return False, (f'ROS_DOMAIN_ID={domain} 은 실물 도메인({sorted(FORBIDDEN_DOMAINS)}): '
                       'fake 백엔드를 쓰지 않습니다. 예: 101')
    return True, f'ROS_DOMAIN_ID={domain}'


class ArmBackend:
    """
    팔 1대의 동작 백엔드 틀. 한 번에 작업 하나만 한다.

    start() 로 시작하고, 노드가 주기적으로 poll() 을 불러 끝난 작업을 받아 간다.
    poll() 은 (요청, 성공 여부, data, detail) 목록을 돌려준다.
    """

    name = 'base'
    available = False

    def __init__(self):
        self.job = None

    def busy(self):
        """작업 중인지."""
        return self.job is not None

    def start(self, request, port, now):
        """작업을 시작한다. 시작하지 못하면 이유 문자열, 시작했으면 None."""
        raise NotImplementedError

    def poll(self, now):
        """끝난 작업 목록."""
        return []

    def hold(self, now):
        """즉시 멈춘다. 하던 작업이 있으면 실패로 끝낸다 (팔 자세를 모르므로 재시도 금지)."""
        return []

    def release_hold(self, now):
        """정지 해제. 동작을 시작하지는 않는다."""


class NoBackend(ArmBackend):
    """실제 팔 백엔드가 아직 없음. 모든 작업을 거절한다."""

    name = 'none'

    def start(self, request, port, now):
        return '팔 동작 백엔드가 설정되지 않음 (backend=none)'


class FakeBackend(ArmBackend):
    """시험용: duration_sec 뒤에 성공. 결과 data 에 fake=true 를 붙여 진짜와 구분한다."""

    name = 'fake'
    available = True

    def __init__(self, duration_sec):
        super().__init__()
        self.duration_sec = duration_sec

    def start(self, request, port, now):
        if self.busy():
            return '팔 작업 중'
        self.job = (request, now + self.duration_sec)
        return None

    def poll(self, now):
        if self.job is None or now < self.job[1]:
            return []
        request, self.job = self.job[0], None
        return [(request, True, {'arm_safe': True, 'fake': True}, '')]

    def hold(self, now):
        if self.job is None:
            return []
        request, self.job = self.job[0], None
        return [(request, False, {'fake': True}, 'hold 로 작업 중단')]


def make_backend(name, fake_duration_sec):
    """이름으로 백엔드를 만든다. 모르는 이름이면 ValueError."""
    if name == 'none':
        return NoBackend()
    if name == 'fake':
        return FakeBackend(fake_duration_sec)
    raise ValueError(f'모르는 backend: {name} (none, fake)')
