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

needs_yaml = pytest.mark.skipif(not PINKY1.exists(), reason='MQTT 토픽 YAML 이 없음')


def by_robot_topic(rules):
    return {rule.robot_topic: rule for rule in rules}


@needs_yaml
def test_pinky1_direction_counts():
    rules = load_rules(PINKY1, 'pinky1', BridgeSettings())
    assert len(rules) == 21
    assert sum(rule.direction == UP for rule in rules) == 15
    assert sum(rule.direction == DOWN for rule in rules) == 6


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
def test_exclude_patterns_drop_lane_topics():
    settings = BridgeSettings(exclude_patterns=('*/lane/*', '*/crossline/*'))
    rules = load_rules(PINKY1, 'pinky1', settings)
    assert len(rules) == 18
    assert not any('lane' in rule.robot_topic or 'crossline' in rule.robot_topic
                   for rule in rules)


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


@pytest.mark.parametrize('name,total', [('pinky1', 21), ('pinky2', 18), ('pinky3', 18)])
def test_all_robot_configs_parse(name, total):
    path = CONFIG_DIR / f'mqtt_topics_{name}.yaml'
    assert path.exists(), f'{path} 가 없다'
    rules = load_rules(path, name, BridgeSettings())
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
