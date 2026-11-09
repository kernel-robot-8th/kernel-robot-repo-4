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
    mine = args_of(LAUNCH)
    theirs = args_of(DOMAIN_BRIDGE_LAUNCH)
    for robot in ROBOTS:
        assert mine[robot] == theirs[robot]


def test_launch_enables_exit_on_parent_loss():
    for node in ET.parse(LAUNCH).getroot().iter('node'):
        params = {p.get('name'): p.get('value') for p in node.iter('param') if p.get('name')}
        assert params['exit_on_parent_loss'] == 'true'
