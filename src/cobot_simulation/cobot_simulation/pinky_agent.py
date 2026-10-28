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

"""Simulated Pinky mobile robot differential drive agent."""

import math
from typing import Optional, Tuple

import numpy as np


class PinkySimAgent:
    """Differential drive mobile robot kinematic simulation with waypoint navigation."""

    def __init__(
        self,
        robot_id: str,
        initial_pose: Tuple[float, float, float],
        wheel_separation: float = 0.0971,
        wheel_radius: float = 0.028,
        max_lin_vel: float = 0.25,
        max_ang_vel: float = 1.2,
    ):
        """Initialize robot state, wheel dimensions, limits and tolerances."""
        self.robot_id = robot_id
        # State: x (m), y (m), yaw (rad)
        self.x = initial_pose[0]
        self.y = initial_pose[1]
        self.yaw = initial_pose[2]

        # Current commanded velocities
        self.target_v = 0.0
        self.target_w = 0.0

        # Current actual velocities
        self.v = 0.0
        self.w = 0.0

        # Kinematic limits
        self.wheel_separation = wheel_separation
        self.wheel_radius = wheel_radius
        self.max_lin_vel = max_lin_vel
        self.max_ang_vel = max_ang_vel
        self.accel_lin_limit = 0.6  # m/s^2
        self.accel_ang_limit = 2.5  # rad/s^2

        # Wheel positions for joint state publishing
        self.left_wheel_pos = 0.0
        self.right_wheel_pos = 0.0

        # Optional closed-loop autonomous navigation target (x, y, yaw)
        self.goal_target: Optional[Tuple[float, float, float]] = None
        self.goal_tolerance_dist = 0.03
        self.goal_tolerance_yaw = 0.08
        self.state_str = 'IDLE'

    def set_cmd_vel(self, linear_x: float, angular_z: float):
        """Set manual twist velocity commands."""
        self.target_v = max(-self.max_lin_vel, min(self.max_lin_vel, linear_x))
        self.target_w = max(-self.max_ang_vel, min(self.max_ang_vel, angular_z))
        if abs(self.target_v) > 0.01 or abs(self.target_w) > 0.01:
            self.state_str = 'NAVIGATING'
        else:
            if self.goal_target is None:
                self.state_str = 'IDLE'

    def set_goal(self, gx: float, gy: float, gyaw: Optional[float] = None):
        """Set autonomous waypoint goal for closed-loop kinematic pursuit."""
        self.goal_target = (gx, gy, gyaw if gyaw is not None else 0.0)
        self.state_str = 'NAVIGATING'

    def step(self, dt: float):
        """Update robot state for time step dt."""
        # 1. Closed-loop navigation if target is active
        if self.goal_target is not None:
            gx, gy, gyaw = self.goal_target
            dx = gx - self.x
            dy = gy - self.y
            dist = math.hypot(dx, dy)

            if dist > self.goal_tolerance_dist:
                target_heading = math.atan2(dy, dx)
                heading_err = (target_heading - self.yaw + math.pi) % (2 * math.pi) - math.pi

                # Smooth proportional control
                if abs(heading_err) > 0.4:
                    self.target_v = 0.0
                    self.target_w = np.clip(2.0 * heading_err, -self.max_ang_vel, self.max_ang_vel)
                else:
                    self.target_v = np.clip(0.8 * dist, 0.05, self.max_lin_vel)
                    self.target_w = np.clip(1.8 * heading_err, -self.max_ang_vel, self.max_ang_vel)
            else:
                # Close to position, align yaw
                yaw_err = (gyaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
                if abs(yaw_err) > self.goal_tolerance_yaw:
                    self.target_v = 0.0
                    self.target_w = np.clip(1.5 * yaw_err, -self.max_ang_vel, self.max_ang_vel)
                else:
                    # Reached goal!
                    self.target_v = 0.0
                    self.target_w = 0.0
                    self.goal_target = None
                    self.state_str = 'DOCKED'

        # 2. Velocity smoothing (Acceleration limiting)
        dv = np.clip(self.target_v - self.v, -self.accel_lin_limit * dt, self.accel_lin_limit * dt)
        dw = np.clip(self.target_w - self.w, -self.accel_ang_limit * dt, self.accel_ang_limit * dt)
        self.v += dv
        self.w += dw

        # 3. Kinematic integration (Differential drive)
        d_theta = self.w * dt
        self.yaw = (self.yaw + d_theta + math.pi) % (2 * math.pi) - math.pi

        ds = self.v * dt
        self.x += ds * math.cos(self.yaw)
        self.y += ds * math.sin(self.yaw)

        # 4. Wheel rotation integration
        v_l = self.v - self.w * (self.wheel_separation / 2.0)
        v_r = self.v + self.w * (self.wheel_separation / 2.0)
        self.left_wheel_pos += (v_l / self.wheel_radius) * dt
        self.right_wheel_pos += (v_r / self.wheel_radius) * dt

    def get_pose(self) -> Tuple[float, float, float]:
        """Return (x, y, yaw)."""
        return self.x, self.y, self.yaw

    def get_twist(self) -> Tuple[float, float]:
        """Return (v, w)."""
        return self.v, self.w
