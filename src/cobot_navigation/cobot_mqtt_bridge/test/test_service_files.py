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

from configparser import ConfigParser
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[1] / 'config'


def read_unit(name):
    parser = ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(CONFIG_DIR / name, encoding='utf-8')
    return parser


def test_robot_service_is_subscribe_only():
    text = (CONFIG_DIR / 'mqtt_bridge_robot.service').read_text(encoding='utf-8')
    exec_start = [line for line in text.splitlines() if line.startswith('ExecStart=')]
    assert len(exec_start) == 1
    # 실제 로봇에 명령을 내보내는 설정은 서비스에 넣지 않는다.
    for forbidden in ('enable_down:=true', 'confirm_real_domain'):
        assert forbidden not in exec_start[0]
    assert 'side:=robot' in exec_start[0]
    assert 'ROS_DOMAIN_ID=10' in text


def test_robot_service_restart_policy():
    unit = read_unit('mqtt_bridge_robot.service')
    # 터널이 아직 없어 종료 코드 2 로 끝나도 다시 시도해야 한다.
    assert unit['Service']['Restart'] == 'on-failure'
    assert int(unit['Service']['RestartSec']) >= 5
    assert unit['Service']['User'] == 'pinky'


def test_tunnel_service_reconnects_without_autossh():
    unit = read_unit('mqtt_bridge_tunnel.service')
    exec_start = unit['Service']['ExecStart']
    assert 'autossh' not in exec_start
    assert 'ExitOnForwardFailure=yes' in exec_start
    assert 'ServerAliveInterval' in exec_start
    assert '-R 127.0.0.1:1883:127.0.0.1:1883' in exec_start
    assert unit['Service']['Restart'] == 'always'
