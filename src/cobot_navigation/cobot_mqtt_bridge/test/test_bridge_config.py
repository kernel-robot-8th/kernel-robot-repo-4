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

from pathlib import Path

from cobot_mqtt_bridge.bridge_config import (
    BridgeSettings, DOWN, load_rules, mqtt_topic_name, parse_rate_limits, status_topic_name,
    UP)
import pytest

CONFIG_DIR = Path(__file__).resolve().parents[1] / 'config'
PINKY1 = CONFIG_DIR / 'mqtt_topics_pinky1.yaml'
ROBOT_DOMAINS = {'pinky1': 10, 'pinky2': 20, 'pinky3': 30}  # 결정 A0: 10/20/30 유지
DOWN_TOPICS = {'/patrol_cmd', '/cmd_vel', '/initialpose', '/goal_pose', '/fleet_heartbeat',
               '/zone_manager/grant_entry', '/zone_manager/queue_slot'}

needs_yaml = pytest.mark.skipif(not PINKY1.exists(), reason='MQTT 토픽 YAML 이 없음')


def by_robot_topic(rules):
    return {rule.robot_topic: rule for rule in rules}


@needs_yaml
def test_pinky1_direction_counts():
    rules = load_rules(PINKY1, 'pinky1', BridgeSettings())
    assert len(rules) == 19
    assert sum(rule.direction == UP for rule in rules) == 12
    assert sum(rule.direction == DOWN for rule in rules) == 7


@needs_yaml
def test_up_remap_goes_to_pc_name():
    rule = by_robot_topic(load_rules(PINKY1, 'pinky1', BridgeSettings()))['/scan']
    assert rule.direction == UP
    assert rule.pc_topic == '/pinky1/scan'
    assert rule.msg_type == 'sensor_msgs/msg/LaserScan'
    assert rule.mqtt_topic == 'mqtt_bridge/pinky1/up/scan'


@needs_yaml
def test_down_remap_goes_to_robot_name():
    rule = by_robot_topic(load_rules(PINKY1, 'pinky1', BridgeSettings()))['/cmd_vel']
    assert rule.direction == DOWN
    assert rule.pc_topic == '/pinky1/cmd_vel'
    assert rule.mqtt_topic == 'mqtt_bridge/pinky1/down/cmd_vel'


@needs_yaml
def test_topic_without_remap_keeps_same_name():
    rule = by_robot_topic(load_rules(PINKY1, 'pinky1', BridgeSettings()))[
        '/zone_manager/request_entry']
    assert rule.pc_topic == rule.robot_topic


@needs_yaml
def test_lane_topics_removed():
    # 결정 A0: 차선 토픽은 쓰지 않는다. 목록에서 지웠으므로 제외 패턴 없이도 없어야 한다.
    rules = load_rules(PINKY1, 'pinky1', BridgeSettings())
    assert not any('lane' in rule.robot_topic or 'crossline' in rule.robot_topic
                   for rule in rules)


@needs_yaml
def test_exclude_patterns_drop_matching_topics():
    settings = BridgeSettings(exclude_patterns=('/cmd_vel', '/goal_pose'))
    names = set(by_robot_topic(load_rules(PINKY1, 'pinky1', settings)))
    assert '/cmd_vel' not in names and '/goal_pose' not in names
    assert '/patrol_cmd' in names


@needs_yaml
def test_latched_and_rate_limit_applied():
    settings = BridgeSettings(
        latched_topics=('/tf_static', '/amcl_pose'), rate_limits=('/tf=30.0',))
    rules = by_robot_topic(load_rules(PINKY1, 'pinky1', settings))
    assert rules['/tf_static'].latched
    assert rules['/amcl_pose'].latched
    assert not rules['/odom'].latched
    assert rules['/tf'].max_rate_hz == 30.0
    assert rules['/odom'].max_rate_hz == 0.0


@pytest.mark.parametrize('name,total', [('pinky1', 19), ('pinky2', 19), ('pinky3', 19)])
def test_all_robot_configs_parse(name, total):
    path = CONFIG_DIR / f'mqtt_topics_{name}.yaml'
    assert path.exists(), f'{path} 가 없다'
    rules = load_rules(path, name, BridgeSettings(robot_domain=ROBOT_DOMAINS[name]))
    assert len(rules) == total
    assert len({rule.mqtt_topic for rule in rules}) == len(rules)
    assert all(rule.mqtt_topic.startswith(f'mqtt_bridge/{name}/') for rule in rules)


def test_topic_yaml_is_independent_of_dds_bridge(tmp_path):
    # 이 패키지의 토픽 목록은 cobot_domain_bridge 의 파일이 없어도 읽혀야 한다.
    path = tmp_path / 'mqtt_topics_pinky9.yaml'
    path.write_text(
        'topics:\n'
        '  /camera/image_raw/compressed:\n'
        '    type: sensor_msgs/msg/CompressedImage\n'
        '    from_domain: 10\n'
        '    to_domain: 200\n'
        '    remap: /pinky9/camera/image_raw/compressed\n', encoding='utf-8')
    rule = load_rules(path, 'pinky9', BridgeSettings())[0]
    assert rule.direction == UP
    assert rule.robot_topic == '/camera/image_raw/compressed'
    assert rule.pc_topic == '/pinky9/camera/image_raw/compressed'
    assert rule.mqtt_topic == 'mqtt_bridge/pinky9/up/camera/image_raw/compressed'


def test_parse_rate_limits():
    assert parse_rate_limits(['/tf=30.0', '/scan=5']) == {'/tf': 30.0, '/scan': 5.0}
    with pytest.raises(ValueError):
        parse_rate_limits(['tf=30'])
    with pytest.raises(ValueError):
        parse_rate_limits(['/tf'])


def test_mqtt_topic_name():
    assert mqtt_topic_name('mqtt_bridge', 'pinky2', UP, '/battery/percent') == \
        'mqtt_bridge/pinky2/up/battery/percent'


def test_status_topic_name():
    assert status_topic_name('mqtt_bridge', 'pinky1', 'robot') == 'mqtt_bridge/pinky1/status/robot'
    assert status_topic_name('mqtt_bridge', 'pinky1', 'pc') == 'mqtt_bridge/pinky1/status/pc'


@pytest.mark.parametrize('name', sorted(ROBOT_DOMAINS))
def test_every_robot_opens_all_down_topics(name):
    # 결정 A0: 관제→로봇 7개를 모두 연다 (fleet_heartbeat 포함)
    path = CONFIG_DIR / f'mqtt_topics_{name}.yaml'
    rules = load_rules(path, name, BridgeSettings(robot_domain=ROBOT_DOMAINS[name]))
    down = {rule.robot_topic for rule in rules if rule.direction == DOWN}
    assert down == DOWN_TOPICS


@pytest.mark.parametrize('name', sorted(ROBOT_DOMAINS))
def test_heartbeat_goes_down_to_robot_name(name):
    path = CONFIG_DIR / f'mqtt_topics_{name}.yaml'
    rules = load_rules(path, name, BridgeSettings(robot_domain=ROBOT_DOMAINS[name]))
    rule = by_robot_topic(rules)['/fleet_heartbeat']
    assert rule.direction == DOWN
    assert rule.pc_topic == f'/{name}/fleet_heartbeat'


@needs_yaml
def test_direction_does_not_depend_on_pc_domain(tmp_path):
    # 관제 도메인이 200(시험)이든 100(운영)이든 YAML 을 고치지 않고 같은 규칙이 나와야 한다.
    text = PINKY1.read_text(encoding='utf-8')
    moved = tmp_path / 'mqtt_topics_pinky1.yaml'
    moved.write_text(text.replace('domain: 200', 'domain: 100'), encoding='utf-8')
    before = load_rules(PINKY1, 'pinky1', BridgeSettings())
    after = load_rules(moved, 'pinky1', BridgeSettings())
    assert before == after


@pytest.mark.parametrize('name,wrong', [('pinky2', 10), ('pinky3', 20)])
def test_wrong_robot_domain_raises(name, wrong):
    # 도메인이 맞지 않으면 아무것도 중계하지 않은 채 켜지지 않고 바로 오류를 낸다.
    path = CONFIG_DIR / f'mqtt_topics_{name}.yaml'
    with pytest.raises(ValueError, match=f'robot_domain={wrong}'):
        load_rules(path, name, BridgeSettings(robot_domain=wrong))


def test_empty_topic_yaml_is_not_an_error(tmp_path):
    path = tmp_path / 'mqtt_topics_empty.yaml'
    path.write_text('topics:\n', encoding='utf-8')
    assert load_rules(path, 'pinky1', BridgeSettings()) == []
