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

"""보드가 빠졌다 다시 잡혀도 탐지 로그에서 노드가 죽지 않는다 (2026-11-24 omx3)."""

from types import SimpleNamespace

from cobot_manipulation import arm_power_utils as power
from cobot_manipulation import arm_registry_utils as registry_utils
from cobot_manipulation.arm_adapter_node import ArmAdapterNode
import pytest
from rclpy.logging import get_logger


def node():
    # 가짜 로거는 등급 변경 오류를 내지 않으므로 실제 rclpy 로거를 쓴다.
    # 호출 줄 기록이 로거 객체에 남으므로 노드처럼 하나를 계속 쓴다.
    logger = get_logger('test_adapter_detect')
    return SimpleNamespace(
        arm_id='omx1', registry={}, by_id_dir='', state=None, port=None, reason='',
        probe_due=False, auto_start=False, power=power.ARMED,
        backend=SimpleNamespace(busy=lambda: False),
        get_logger=lambda: logger)


@pytest.mark.parametrize('order', [
    [True, False, True], [False, True, False]], ids=['connected_first', 'missing_first'])
def test_detect_survives_unplug_and_replug(monkeypatch, order):
    fake = node()
    monkeypatch.setattr(registry_utils, 'list_by_id', lambda path: [])
    for found in order:
        result = ((registry_utils.READY, '/dev/null', '보드 확인') if found
                  else (registry_utils.UNKNOWN, None, '보드 없음'))
        monkeypatch.setattr(registry_utils, 'detect', lambda *args: result)
        ArmAdapterNode._detect(fake)
        assert (fake.state, fake.port) == result[:2]
