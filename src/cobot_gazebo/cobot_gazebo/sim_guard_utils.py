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
시뮬 도메인 검사 (ROS 없는 순수 로직).

시뮬 핑키는 실물과 같은 토픽 이름(/pinkyN/patrol_status 등)을 낸다. 실물 도메인에서 띄우면
진짜 관제가 시뮬 로봇을 진짜로 믿고, 시뮬 관제 명령이 진짜 로봇에 갈 수 있다.
launch/sim_fleet.launch.xml 의 eval 조건에도 같은 목록이 있다 (test_sim_guard_utils 가 맞는지 본다).
"""

# 실물이 쓰는 도메인. 0 은 '지정 안 함' 이라 실물과 섞일 수 있어 같이 막는다.
FORBIDDEN_DOMAINS = frozenset({0, 10, 12, 20, 30, 100})
# ROS 2 가 쓸 수 있는 도메인 범위 (Linux 기본 포트 계산 기준)
MAX_DOMAIN_ID = 232


def check_domains(control_domain, robot_domains, discovery_range=''):
    """
    시뮬을 띄워도 되는 도메인 조합인지 본다. (ok, 메시지) 를 돌려준다.

    :param control_domain: 관제 쪽 도메인 (실물 100 자리)
    :param robot_domains: {로봇 이름: 도메인} (실물 10/20/30 자리)
    :param discovery_range: ROS_AUTOMATIC_DISCOVERY_RANGE 값. LOCALHOST 가 아니면 같은 망에 샌다
    """
    named = {'control': control_domain, **robot_domains}
    for name, domain in named.items():
        if not isinstance(domain, int) or isinstance(domain, bool):
            return False, f'{name} 도메인이 정수가 아님: {domain!r}'
        if not 0 <= domain <= MAX_DOMAIN_ID:
            return False, f'{name} 도메인 {domain} 은 0~{MAX_DOMAIN_ID} 밖'
        if domain in FORBIDDEN_DOMAINS:
            return False, (f'{name} 도메인 {domain} 은 실물 도메인({sorted(FORBIDDEN_DOMAINS)}): '
                           '시뮬을 띄우지 않습니다. 기본값 140·141~143 을 쓰세요')
    if len(set(named.values())) != len(named):
        return False, f'도메인이 서로 겹침: {named}'
    if discovery_range != 'LOCALHOST':
        return False, (f'ROS_AUTOMATIC_DISCOVERY_RANGE={discovery_range!r}: '
                       'LOCALHOST 가 아니면 같은 망의 다른 PC 와 섞입니다')
    return True, f'시뮬 도메인 확인: {named} (LOCALHOST)'
