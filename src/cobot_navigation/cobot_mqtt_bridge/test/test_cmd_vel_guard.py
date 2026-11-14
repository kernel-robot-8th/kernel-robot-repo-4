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

import math

from cobot_mqtt_bridge.cmd_vel_guard import clamp_twist, is_stale, is_zero, Watchdog
import pytest


def twist(lx=0.0, ly=0.0, lz=0.0, ax=0.0, ay=0.0, az=0.0):
    return {'linear': {'x': lx, 'y': ly, 'z': lz}, 'angular': {'x': ax, 'y': ay, 'z': az}}


def test_clamp_below_limit_unchanged():
    data, clamped = clamp_twist(twist(lx=0.1, az=0.5), 0.2, 1.0)
    assert not clamped
    assert data == twist(lx=0.1, az=0.5)


def test_clamp_linear_keeps_direction():
    data, clamped = clamp_twist(twist(lx=0.3, ly=0.4), 0.25, 1.0)
    assert clamped
    assert math.isclose(math.hypot(data['linear']['x'], data['linear']['y']), 0.25)
    assert math.isclose(data['linear']['x'] / data['linear']['y'], 0.3 / 0.4)


def test_clamp_angular_independent_of_linear():
    data, clamped = clamp_twist(twist(lx=0.1, az=3.0), 0.2, 1.0)
    assert clamped
    assert data['linear']['x'] == 0.1
    assert math.isclose(data['angular']['z'], 1.0)


def test_clamp_zero_limit_means_unlimited():
    data, clamped = clamp_twist(twist(lx=5.0, az=9.0), 0.0, 0.0)
    assert not clamped
    assert data['linear']['x'] == 5.0


def test_is_zero():
    assert is_zero(twist())
    assert not is_zero(twist(az=0.01))


def test_is_stale():
    assert not is_stale(10.0, 10.2, 0.0)
    assert not is_stale(10.0, 10.2, 500.0)
    assert is_stale(10.0, 10.6, 500.0)


def test_watchdog_trips_once_after_timeout():
    dog = Watchdog(500.0)
    dog.feed(0.0, True)
    assert not dog.expired(0.4)
    assert dog.expired(0.5)
    assert not dog.expired(1.0)
    assert dog.trips == 1


def test_watchdog_zero_command_disarms():
    dog = Watchdog(500.0)
    dog.feed(0.0, True)
    dog.feed(0.2, False)
    assert not dog.expired(5.0)
    assert dog.trips == 0


def test_watchdog_new_command_rearms():
    dog = Watchdog(500.0)
    dog.feed(0.0, True)
    assert dog.expired(0.6)
    dog.feed(1.0, True)
    assert dog.expired(1.6)
    assert dog.trips == 2


@pytest.mark.parametrize('timeout', [0.0, -1.0])
def test_watchdog_disabled_never_trips(timeout):
    dog = Watchdog(timeout)
    dog.feed(0.0, True)
    assert not dog.expired(1000.0)
