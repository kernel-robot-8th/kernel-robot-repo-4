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

"""Simulated OpenManipulator-X (5-DOF + Gripper) with velocity-clamped interpolation."""

import math
from typing import Dict, List, Tuple

import numpy as np


class OmxSimAgent:
    """OpenManipulator-X kinematic arm simulation.

    Preserves 5-DOF joints + 2 parallel gripper joints:
    - joint1: Base pan
    - joint2: Shoulder lift
    - joint3: Elbow flex
    - joint4: Wrist flex
    - joint5: Wrist roll
    - gripper_joint_1, gripper_joint_2: Parallel jaw
    """

    # Conservative joint limits in radians
    LIMITS: Dict[str, Tuple[float, float]] = {
        'joint1': (-math.pi, math.pi),
        'joint2': (-1.8675, 1.5708),
        'joint3': (-1.5708, 1.5708),
        'joint4': (-1.7453, 1.7453),
        'joint5': (-math.pi, math.pi),
        'gripper_joint_1': (0.0, 1.7453),
    }

    # Pre-defined operational arm poses (radians)
    PRESET_POSES = {
        'HOME': np.array([0.0, -1.05, 0.35, 0.70, 0.0, 0.0]),
        'PRE_GRASP': np.array([0.0, 0.15, 0.40, 1.02, 0.0, 1.2]),
        'GRASP': np.array([0.0, 0.42, 0.65, 0.50, 0.0, 0.2]),
        'LIFT_Z200': np.array([0.0, -0.20, 0.10, 0.10, 0.0, 0.2]),
        'HANDOVER': np.array([1.57, -0.10, 0.30, 0.30, 0.0, 0.2]),
    }

    def __init__(self, arm_id: str, base_pos: Tuple[float, float, float], base_yaw: float = 0.0):
        """Initialize arm id, mount base pose, and resting joint configuration."""
        self.arm_id = arm_id
        self.base_pos = base_pos
        self.base_yaw = base_yaw

        # Current joint positions: [q1, q2, q3, q4, q5, gripper]
        self.q = self.PRESET_POSES['HOME'].copy()
        self.target_q = self.q.copy()

        # Kinematic motion limits (velocity-clamped linear interpolation)
        self.max_joint_vel = 1.2  # rad/s

        # Trajectory execution sequence
        self.trajectory_queue: List[Tuple[np.ndarray, float]] = []
        self.current_action_timer = 0.0
        self.is_busy = False
        self.has_cargo = False
        self.state_str = 'STANDBY'

    def set_target_joints(self, target_joints: np.ndarray):
        """Command target joint positions with limit clipping."""
        clipped = target_joints.copy()
        clipped[0] = np.clip(clipped[0], *self.LIMITS['joint1'])
        clipped[1] = np.clip(clipped[1], *self.LIMITS['joint2'])
        clipped[2] = np.clip(clipped[2], *self.LIMITS['joint3'])
        clipped[3] = np.clip(clipped[3], *self.LIMITS['joint4'])
        clipped[4] = np.clip(clipped[4], *self.LIMITS['joint5'])
        clipped[5] = np.clip(clipped[5], *self.LIMITS['gripper_joint_1'])
        self.target_q = clipped
        self.is_busy = True

    def trigger_pick_sequence(self):
        """Execute a full standardized pick & place cycle with Z=200mm vertical lift."""
        self.trajectory_queue = [
            (self.PRESET_POSES['PRE_GRASP'], 1.5),
            (self.PRESET_POSES['GRASP'], 1.2),
            (self.PRESET_POSES['LIFT_Z200'], 1.5),
            (self.PRESET_POSES['HANDOVER'], 1.8),
            (self.PRESET_POSES['HOME'], 1.5),
        ]
        self.is_busy = True
        self.state_str = 'EXECUTING'

    def step(self, dt: float):
        """Integrate arm joints toward target using velocity-clamped linear interpolation."""
        # Check trajectory queue
        if self.trajectory_queue:
            target, dur = self.trajectory_queue[0]
            self.target_q = target
            self.current_action_timer += dt
            if self.current_action_timer >= dur:
                self.trajectory_queue.pop(0)
                self.current_action_timer = 0.0
                if not self.trajectory_queue:
                    self.is_busy = False
                    self.state_str = 'STANDBY'

        diff = self.target_q - self.q
        max_step = self.max_joint_vel * dt
        clamped_step = np.clip(diff, -max_step, max_step)
        self.q += clamped_step

        if np.max(np.abs(self.target_q - self.q)) < 1e-4:
            self.q = self.target_q.copy()
            if not self.trajectory_queue:
                self.is_busy = False
                self.state_str = 'STANDBY'

    def get_joint_states(self) -> Dict[str, float]:
        """Return dict of joint names to positions."""
        return {
            f'{self.arm_id}/joint1': float(self.q[0]),
            f'{self.arm_id}/joint2': float(self.q[1]),
            f'{self.arm_id}/joint3': float(self.q[2]),
            f'{self.arm_id}/joint4': float(self.q[3]),
            f'{self.arm_id}/joint5': float(self.q[4]),
            f'{self.arm_id}/gripper_joint_1': float(self.q[5]),
            f'{self.arm_id}/gripper_joint_2': float(-self.q[5]),
        }
