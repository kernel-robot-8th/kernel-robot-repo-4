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
import xml.etree.ElementTree as ET

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LAUNCH = PACKAGE_DIR / 'launch' / 'mqtt_bridge.launch.xml'
DOMAIN_BRIDGE_LAUNCH = (
    PACKAGE_DIR.parent / 'cobot_domain_bridge' / 'launch' / 'bridges.launch.xml')
ROBOTS = ('pinky1', 'pinky2', 'pinky3')


def args_of(path):
    return {arg.get('name'): arg.get('default') for arg in ET.parse(path).getroot().iter('arg')}


def test_launch_parses_and_has_robot_args():
    args = args_of(LAUNCH)
    assert all(robot in args for robot in ROBOTS)


def test_every_robot_has_one_pc_node_with_unique_name():
    nodes = list(ET.parse(LAUNCH).getroot().iter('node'))
    assert [node.get('if') for node in nodes] == [f'$(var {robot})' for robot in ROBOTS]
    assert len({node.get('name') for node in nodes}) == len(ROBOTS)
    for node in nodes:
        params = {p.get('name'): p.get('value') for p in node.iter('param') if p.get('name')}
        assert params['side'] == 'pc'


def test_down_is_off_by_default():
    assert args_of(LAUNCH)['enable_down'] == 'false'


@pytest.mark.skipif(not DOMAIN_BRIDGE_LAUNCH.exists(), reason='bridges.launch.xml 이 없음')
def test_robot_args_match_domain_bridge_launch():
    # 인자 이름만 맞춘다. 기본값은 한 줄 실행을 위해 pinky1 만 켜는 쪽으로 다르다.
    mine = args_of(LAUNCH)
    theirs = args_of(DOMAIN_BRIDGE_LAUNCH)
    assert all(robot in mine and robot in theirs for robot in ROBOTS)


def test_launch_enables_exit_on_parent_loss():
    for node in ET.parse(LAUNCH).getroot().iter('node'):
        params = {p.get('name'): p.get('value') for p in node.iter('param') if p.get('name')}
        assert params['exit_on_parent_loss'] == 'true'


def test_one_line_launch_defaults():
    args = args_of(LAUNCH)
    assert args['mode'] == 'read'
    assert (args['pinky1'], args['pinky2'], args['pinky3']) == ('true', 'false', 'false')
    assert args['pc_domain'] == '200' and args['robot_domain'] == '10'


def test_cmd_mode_opens_down_only_in_cmd():
    text = LAUNCH.read_text(encoding='utf-8')
    # 명령 모드 값(enable_down, 보호 값 파일)은 mode 가 cmd 일 때만 붙는다.
    assert "'$(var mode)' == 'cmd'" in text
    assert text.count('mqtt_down.yaml') >= 2


def test_robot_side_refuses_when_service_is_active():
    text = LAUNCH.read_text(encoding='utf-8')
    assert 'systemctl is-active --quiet mqtt_bridge_robot' in text
    assert 'ssh -tt' in text
