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
"""

from dataclasses import dataclass
from fnmatch import fnmatch

import yaml

UP = 'up'
DOWN = 'down'


@dataclass(frozen=True)
class BridgeSettings:
    """중계 규칙을 만들 때 필요한 설정 (config/mqtt_bridge.yaml 에서 온다)."""

    pc_domain: int = 200
    topic_prefix: str = 'mqtt_bridge'
    exclude_patterns: tuple = ()
    latched_topics: tuple = ()
    rate_limits: tuple = ()


@dataclass(frozen=True)
class TopicRule:
    """토픽 하나의 중계 규칙."""

    robot_topic: str
    pc_topic: str
    msg_type: str
    direction: str
    mqtt_topic: str
    latched: bool
    max_rate_hz: float


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
    """MQTT 주제 이름을 만든다. 방향이 들어 있어 되돌아오는 루프가 생기지 않는다."""
    return f'{prefix}/{robot}/{direction}/{robot_topic.lstrip("/")}'


def status_topic_name(prefix, robot, side):
    """역할(robot|pc)별 상태 주제 이름. 값은 {"state": "online"|"offline"} JSON."""
    return f'{prefix}/{robot}/status/{side}'


def load_rules(bridge_yaml_path, robot, settings):
    """브릿지 YAML 을 읽어 TopicRule 목록을 돌려준다. 제외 패턴에 걸린 토픽은 뺀다."""
    with open(bridge_yaml_path, encoding='utf-8') as handle:
        document = yaml.safe_load(handle) or {}
    topics = document.get('topics') or {}
    limits = parse_rate_limits(settings.rate_limits)
    rules = []
    for name, entry in topics.items():
        rule = _make_rule(name, entry, robot, settings, limits)
        if rule is None or _is_excluded(rule, settings.exclude_patterns):
            continue
        rules.append(rule)
    return rules


def _make_rule(name, entry, robot, settings, limits):
    """항목 하나를 규칙으로 바꾼다. 관제 도메인과 무관한 항목이면 None."""
    pc_domain = settings.pc_domain
    remap = entry.get('remap') or name
    if int(entry['to_domain']) == pc_domain:
        direction, robot_topic, pc_topic = UP, name, remap
    elif int(entry['from_domain']) == pc_domain:
        direction, robot_topic, pc_topic = DOWN, remap, name
    else:
        return None
    return TopicRule(
        robot_topic=robot_topic,
        pc_topic=pc_topic,
        msg_type=entry['type'],
        direction=direction,
        mqtt_topic=mqtt_topic_name(settings.topic_prefix, robot, direction, robot_topic),
        latched=robot_topic in settings.latched_topics,
        max_rate_hz=limits.get(robot_topic, 0.0),
    )


def _is_excluded(rule, patterns):
    """로봇 쪽 또는 관제 쪽 이름이 제외 패턴에 맞으면 True."""
    return any(fnmatch(rule.robot_topic, pattern) or fnmatch(rule.pc_topic, pattern)
               for pattern in patterns)
