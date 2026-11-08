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

import os
import xml.etree.ElementTree as ET

from cobot_gazebo.sim_guard_utils import check_domains, FORBIDDEN_DOMAINS
import pytest
import yaml

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROBOTS = {'pinky1': 141, 'pinky2': 142, 'pinky3': 143}


def test_default_sim_domains_pass():
    ok, msg = check_domains(140, ROBOTS, 'LOCALHOST')
    assert ok, msg


@pytest.mark.parametrize('domain', sorted(FORBIDDEN_DOMAINS))
def test_real_control_domain_refused(domain):
    ok, msg = check_domains(domain, ROBOTS, 'LOCALHOST')
    assert not ok
    assert '실물' in msg


def test_real_robot_domain_refused():
    ok, _ = check_domains(140, {**ROBOTS, 'pinky2': 20}, 'LOCALHOST')
    assert not ok


def test_overlapping_domains_refused():
    ok, msg = check_domains(140, {**ROBOTS, 'pinky3': 141}, 'LOCALHOST')
    assert not ok
    assert '겹침' in msg


def test_out_of_range_and_non_int_refused():
    assert not check_domains(300, ROBOTS, 'LOCALHOST')[0]
    assert not check_domains(140, {**ROBOTS, 'pinky1': '141'}, 'LOCALHOST')[0]
    assert not check_domains(True, ROBOTS, 'LOCALHOST')[0]


@pytest.mark.parametrize('rng', ['', 'SUBNET', 'OFF'])
def test_non_localhost_refused(rng):
    ok, msg = check_domains(140, ROBOTS, rng)
    assert not ok
    assert 'LOCALHOST' in msg


def _launch_lets():
    root = ET.parse(os.path.join(PKG, 'launch', 'sim_fleet.launch.xml')).getroot()
    # 도메인 숫자만 본다 (central_controlled 같은 다른 let 은 숫자가 아니다)
    return {e.get('name'): int(e.get('value')) for e in root.iter('let')
            if e.get('name').endswith('_domain')}


def test_launch_domains_match_bridge_configs():
    """고정 도메인(sim_fleet.launch.xml)과 브릿지 설정의 숫자가 같고, 검사를 통과해야 한다."""
    lets = _launch_lets()
    control = lets['control_domain']
    robots = {r: lets[f'{r}_domain'] for r in ROBOTS}
    assert check_domains(control, robots, 'LOCALHOST')[0]
    for robot, domain in robots.items():
        with open(os.path.join(PKG, 'config', f'domain_bridge_{robot}.yaml'),
                  encoding='utf-8') as f:
            topics = yaml.safe_load(f)['topics']
        used = {spec['from_domain'] for spec in topics.values()}
        used |= {spec['to_domain'] for spec in topics.values()}
        assert used == {control, domain}, f'{robot}: {used}'


@pytest.mark.parametrize('robot', sorted(ROBOTS))
def test_bridge_carries_battery(robot):
    """관제는 배터리로 서 있는 로봇의 online 을 판단하므로, 시뮬 브릿지도 배터리를 넘겨야 한다."""
    with open(os.path.join(PKG, 'config', f'domain_bridge_{robot}.yaml'), encoding='utf-8') as f:
        topics = yaml.safe_load(f)['topics']
    for name in ('/battery/percent', '/battery/voltage'):
        assert topics[name]['remap'] == f'/{robot}{name}'
        assert topics[name]['type'] == 'std_msgs/msg/Float32'


@pytest.mark.parametrize('robot', sorted(ROBOTS))
def test_bridge_carries_fleet_heartbeat(robot):
    """순찰 노드가 central_controlled 라, 관제 하트비트가 없으면 fleet_control 명령을 거절한다."""
    with open(os.path.join(PKG, 'config', f'domain_bridge_{robot}.yaml'), encoding='utf-8') as f:
        topics = yaml.safe_load(f)['topics']
    spec = topics[f'/{robot}/fleet_heartbeat']
    assert spec['remap'] == '/fleet_heartbeat' and spec['type'] == 'std_msgs/msg/String'
    assert spec['from_domain'] == 140 and spec['to_domain'] == ROBOTS[robot]
