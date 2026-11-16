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

from array import array

from cobot_mqtt_bridge.relay_utils import (
    check_publish_domain, check_robot_publish_domain, decode_envelope, encode_envelope,
    RateGate)
import pytest


def test_rate_gate_unlimited_passes_everything():
    gate = RateGate(0.0)
    assert all(gate.allow(t * 0.001) for t in range(100))


def test_rate_gate_drops_inside_interval():
    gate = RateGate(10.0)
    assert gate.allow(0.0)
    assert not gate.allow(0.05)
    assert gate.allow(0.10)


def test_rate_gate_effective_rate_is_source_over_ceil():
    # 소스 30 Hz, 상한 20 Hz → 간격 50 ms 이므로 2틱(66 ms)마다 통과 = 15 Hz
    gate = RateGate(20.0)
    passed = sum(gate.allow(i / 30.0) for i in range(300))
    assert passed == 150


def test_envelope_round_trip():
    payload = encode_envelope('std_msgs/msg/Float32', 12.5, {'data': 100.0})
    data, sent_at = decode_envelope(payload, 'std_msgs/msg/Float32')
    assert data == {'data': 100.0}
    assert sent_at == 12.5


def test_envelope_handles_array_types():
    payload = encode_envelope('t', 0.0, {'ranges': array('f', [1.0, 2.0])})
    data, _ = decode_envelope(payload, 't')
    assert data['ranges'] == [1.0, 2.0]


def test_envelope_type_mismatch_raises():
    payload = encode_envelope('a/msg/A', 0.0, {})
    with pytest.raises(ValueError):
        decode_envelope(payload, 'b/msg/B')


@pytest.mark.parametrize('domain', ['101', '102'])
def test_isolated_domains_allowed(domain):
    assert check_publish_domain(domain, '', 200) == ''


def test_real_domain_requires_confirmation():
    assert check_publish_domain('200', '', 200) != ''
    assert check_publish_domain('200', '200', 200) == ''


@pytest.mark.parametrize('domain', ['10', '12', '', '77'])
def test_other_domains_refused(domain):
    assert check_publish_domain(domain, '200', 200) != ''


@pytest.mark.parametrize('domain', ['101', '102'])
def test_robot_publish_isolated_allowed(domain):
    assert check_robot_publish_domain(domain, '', 10) == ''


def test_robot_publish_real_domain_requires_confirmation():
    assert check_robot_publish_domain('10', '', 10) != ''
    assert check_robot_publish_domain('10', '10', 10) == ''


@pytest.mark.parametrize('domain', ['200', '', '77'])
def test_robot_publish_other_domains_refused(domain):
    assert check_robot_publish_domain(domain, '10', 10) != ''
