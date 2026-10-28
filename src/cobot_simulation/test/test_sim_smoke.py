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

"""Smoke tests for lightweight multi-robot and arena simulation."""

import math

from cobot_simulation.arena_model import ShoeStoreArena
from cobot_simulation.omx_agent import OmxSimAgent
from cobot_simulation.pinky_agent import PinkySimAgent


def test_arena_geometry():
    """Verify official arena dimensions and obstacle collision detection."""
    arena = ShoeStoreArena()
    assert len(arena.waypoints) >= 8
    assert 'WP_GATE_TRANSIT' in arena.waypoints
    assert 'WP_LOAD_1' in arena.waypoints
    assert 'WP_UNLOAD' in arena.waypoints
    # Verify v9 synchronized waypoints are also registered
    assert 'ZA' in arena.waypoints
    assert 'ZC' in arena.waypoints
    assert 'I1' in arena.waypoints

    # Test variable gate clearance (e.g. 0.31m for v9 narrow passage)
    narrow_arena = ShoeStoreArena(gate_clearance_m=0.31)
    assert narrow_arena.is_in_collision(1.25, 0.50) is True

    # Central wall should block X=1.25, Y=1.5
    assert arena.is_in_collision(1.25, 1.50) is True

    # 67cm Gate at X=1.25, Y=0.335 should be free passage
    assert arena.is_in_collision(1.25, 0.335) is False

    # Outer wall bounds
    assert arena.is_in_collision(-0.02, 1.0) is True


def test_arena_raycast_lidar():
    """Verify 2D LiDAR raycasting gives valid distances."""
    arena = ShoeStoreArena()
    # At gate center (1.25, 0.335), ray pointing North should hit central wall at Y=0.67
    ranges = arena.raycast_scan(1.25, 0.335, yaw=0.0, num_rays=36)
    assert len(ranges) == 36
    assert all(0.05 <= r <= 3.5 for r in ranges)


def test_pinky_kinematics_and_waypoint_tracking():
    """Verify differential drive integration and autonomous goal pursuit."""
    agent = PinkySimAgent('pinky1', initial_pose=(1.41, 2.05, 0.0))

    # Test direct velocity integration
    agent.set_cmd_vel(0.2, 0.0)
    for _ in range(10):
        agent.step(0.02)
    assert agent.x > 1.41

    # Test closed-loop goal pursuit to WP_GATE_TRANSIT
    agent.set_goal(1.25, 0.335, -math.pi / 2.0)
    for _ in range(500):  # 10 seconds of simulated time
        agent.step(0.02)
        if agent.goal_target is None:
            break

    # Should arrive close to gate
    assert math.hypot(agent.x - 1.25, agent.y - 0.335) < 0.15


def test_omx_arm_kinematics_and_interpolation():
    """Verify arm kinematic velocity-clamped interpolation and trajectory execution."""
    arm = OmxSimAgent('omx_1', base_pos=(2.015, 2.105, 0.085))

    initial_joints = arm.get_joint_states()
    assert 'omx_1/joint1' in initial_joints
    assert 'omx_1/gripper_joint_1' in initial_joints

    # Test pick sequence triggering
    arm.trigger_pick_sequence()
    assert arm.is_busy is True
    assert arm.state_str == 'EXECUTING'

    # Step motion
    for _ in range(50):
        arm.step(0.02)

    new_joints = arm.get_joint_states()
    # Verify joints moved smoothly under velocity clamp without instant jump
    assert any(abs(new_joints[k] - initial_joints[k]) > 0.001 for k in initial_joints)
