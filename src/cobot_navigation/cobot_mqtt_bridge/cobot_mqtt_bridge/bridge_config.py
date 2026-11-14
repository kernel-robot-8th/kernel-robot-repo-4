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
MQTT 토픽 목록 YAML(config/mqtt_topics_<로봇>.yaml)을 읽어 중계 규칙으로 바꾸는 순수 로직.

왜 따로 두는가: 토픽 목록은 코드에 적지 않고 YAML 로 관리한다. 이 YAML 은 DDS 브릿지
(cobot_domain_bridge)의 것과 형식만 같고 파일은 별개라서, 여기를 고쳐도 DDS 쪽에는 영향이
없다. ROS 에 의존하지 않아 단독 시험이 된다.

방향: to_domain 이 관제 도메인이면 up(로봇→관제), from_domain 이 관제 도메인이면
down(관제→로봇). 로봇 쪽 토픽 이름과 관제 쪽 이름이 다르면 remap 이 관제 쪽(up) 또는
로봇 쪽(down) 이름이다.

읽는 순서: load_rules() 가 입구다. YAML 항목을 _make_rule() 로 TopicRule 하나씩 만들고,
_is_excluded() 로 빼야 할 것을 거른다. 결과 목록을 mqtt_bridge_node.py 가 받아 토픽마다
ROS 구독자/발행자를 만든다.

YAML 항목 예 (up: 로봇이 만든 값을 관제로 보낸다):
    topics:
      /odom:
        type: nav_msgs/msg/Odometry
        from_domain: 10      # 로봇 도메인
        to_domain: 200       # 관제 도메인 -> to_domain 이 관제이므로 up
        remap: /pinky1/odom  # 관제 쪽에서 보이는 이름 (없으면 같은 이름)
이 항목은 다음 TopicRule 이 된다:
    robot_topic=/odom, pc_topic=/pinky1/odom, direction=up,
    mqtt_topic=mqtt_bridge/pinky1/up/odom
"""

from dataclasses import dataclass
from fnmatch import fnmatch

import yaml

UP = 'up'
DOWN = 'down'


@dataclass(frozen=True)
class BridgeSettings:
    """중계 규칙을 만들 때 필요한 설정 (config/mqtt_bridge.yaml 에서 온다)."""

    pc_domain: int = 200  # 관제 쪽 ROS 도메인. YAML 항목의 방향을 가르는 기준값이다.
    topic_prefix: str = 'mqtt_bridge'  # 모든 MQTT 주제의 맨 앞 글자 (다른 용도와 섞이지 않게)
    exclude_patterns: tuple = ()  # 중계에서 뺄 토픽 이름 패턴(fnmatch). 예: '*/lane/*'
    latched_topics: tuple = ()  # 마지막 값을 새로 접속한 쪽에도 주어야 하는 토픽(/tf_static 등)
    rate_limits: tuple = ()  # '/토픽=Hz' 문자열 목록. 너무 자주 오는 토픽(/tf)의 전송 상한


@dataclass(frozen=True)
class TopicRule:
    """토픽 하나의 중계 규칙."""

    robot_topic: str  # 로봇 도메인(10)에서 쓰는 이름. 예: /odom
    pc_topic: str  # 관제 도메인(200)에서 쓰는 이름. 예: /pinky1/odom
    msg_type: str  # ROS 메시지 타입 문자열. 예: nav_msgs/msg/Odometry
    direction: str  # UP(로봇->관제) 또는 DOWN(관제->로봇)
    mqtt_topic: str  # 이 토픽이 브로커에서 지나가는 주제 이름
    latched: bool  # True 면 ROS 는 transient_local, MQTT 는 retain 으로 마지막 값을 남긴다
    max_rate_hz: float  # 초당 전송 상한. 0 이면 제한 없음


def parse_rate_limits(entries):
    """'토픽=Hz' 문자열 목록을 {토픽: Hz} 로 바꾼다. 형식이 틀리면 ValueError."""
    limits = {}
    for entry in entries:
        topic, sep, value = str(entry).partition('=')
        if not sep or not topic.startswith('/'):
            raise ValueError(f'rate_limits 항목은 "/토픽=Hz" 형식이어야 한다: {entry!r}')
        limits[topic] = float(value)
    return limits


def mqtt_topic_name(prefix, robot, direction, robot_topic):
    """
    MQTT 주제 이름을 만든다. 방향이 들어 있어 되돌아오는 루프가 생기지 않는다.

    예: ('mqtt_bridge', 'pinky1', 'up', '/odom') -> 'mqtt_bridge/pinky1/up/odom'
    up 과 down 이 서로 다른 주제를 쓰므로 내가 보낸 것을 내가 다시 받는 일이 없다.
    """
    return f'{prefix}/{robot}/{direction}/{robot_topic.lstrip("/")}'


def status_topic_name(prefix, robot, side):
    """역할(robot|pc)별 상태 주제 이름. 값은 {"state": "online"|"offline"} JSON."""
    return f'{prefix}/{robot}/status/{side}'


def load_rules(bridge_yaml_path, robot, settings):
    """브릿지 YAML 을 읽어 TopicRule 목록을 돌려준다. 제외 패턴에 걸린 토픽은 뺀다."""
    with open(bridge_yaml_path, encoding='utf-8') as handle:
        document = yaml.safe_load(handle) or {}  # 빈 파일이어도 오류 없이 빈 목록이 된다
    topics = document.get('topics') or {}
    limits = parse_rate_limits(settings.rate_limits)  # 반복마다 풀지 않게 한 번만 변환
    rules = []
    for name, entry in topics.items():
        rule = _make_rule(name, entry, robot, settings, limits)
        # None 은 관제 도메인과 상관없는 항목(예: 로봇 안에서만 쓰는 토픽)이다.
        if rule is None or _is_excluded(rule, settings.exclude_patterns):
            continue
        rules.append(rule)
    return rules


def _make_rule(name, entry, robot, settings, limits):
    """항목 하나를 규칙으로 바꾼다. 관제 도메인과 무관한 항목이면 None."""
    pc_domain = settings.pc_domain
    remap = entry.get('remap') or name
    # YAML 의 키(name)는 "값이 만들어지는 쪽" 이름이고 remap 은 "받는 쪽" 이름이다.
    # 그래서 방향에 따라 로봇 쪽/관제 쪽 이름이 뒤바뀐다.
    if int(entry['to_domain']) == pc_domain:  # 관제로 가는 항목 = up
        direction, robot_topic, pc_topic = UP, name, remap
    elif int(entry['from_domain']) == pc_domain:  # 관제에서 오는 항목 = down
        direction, robot_topic, pc_topic = DOWN, remap, name
    else:
        return None
    return TopicRule(
        robot_topic=robot_topic,
        pc_topic=pc_topic,
        msg_type=entry['type'],
        direction=direction,
        mqtt_topic=mqtt_topic_name(settings.topic_prefix, robot, direction, robot_topic),
        # latched 와 속도 상한은 로봇 쪽 이름으로 찾는다 (설정 파일이 로봇 쪽 이름으로 적혀 있다)
        latched=robot_topic in settings.latched_topics,
        max_rate_hz=limits.get(robot_topic, 0.0),
    )


def _is_excluded(rule, patterns):
    """
    로봇 쪽 또는 관제 쪽 이름이 제외 패턴에 맞으면 True.

    둘 다 보는 이유: 패턴을 어느 쪽 이름으로 적어도 같은 토픽이 빠지게 하기 위해서다.
    """
    return any(fnmatch(rule.robot_topic, pattern) or fnmatch(rule.pc_topic, pattern)
               for pattern in patterns)
