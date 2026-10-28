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

"""Arena layout, obstacles, waypoints and 2D LiDAR raycasting model.

Based on Floor Map 1021 & map_shoe_store_1021_gate67.yaml contract:
- Arena dimensions: 2.50m (X) x 2.40m (Y)
- Central dividing wall: X in [1.20, 1.30], Y in [0.67, 2.40]
- Transfer gate opening: 67cm wide at X in [1.20, 1.30], Y in [0.00, 0.67]
- Racks, benches, counters, and named waypoints.
"""

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ObstacleBox:
    """Axis-aligned 2D bounding box obstacle for collision and raycasting."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def ray_intersect(
        self, rx: float, ry: float, cos_a: float, sin_a: float, max_range: float
    ) -> float:
        """Find the intersection distance of a ray with this axis-aligned bounding box."""
        t_min = 0.0
        t_max = max_range

        # X slab
        if abs(cos_a) > 1e-6:
            tx1 = (self.x_min - rx) / cos_a
            tx2 = (self.x_max - rx) / cos_a
            t_min = max(t_min, min(tx1, tx2))
            t_max = min(t_max, max(tx1, tx2))
        else:
            if rx < self.x_min or rx > self.x_max:
                return max_range

        # Y slab
        if abs(sin_a) > 1e-6:
            ty1 = (self.y_min - ry) / sin_a
            ty2 = (self.y_max - ry) / sin_a
            t_min = max(t_min, min(ty1, ty2))
            t_max = min(t_max, max(ty1, ty2))
        else:
            if ry < self.y_min or ry > self.y_max:
                return max_range

        if t_min <= t_max and t_max > 0.0:
            return max(t_min, 0.0)
        return max_range


class ShoeStoreArena:
    """Represents the complete 2.5m x 2.4m PRD_3 shoe store arena."""

    def __init__(self, gate_clearance_m: float = 0.67):
        """Initialize waypoints and arena bounding obstacles with configurable gate width."""
        self.gate_clearance_m = gate_clearance_m

        # Named Waypoints per map_shoe_store_1021_gate67.yaml [X, Y, Theta_deg]
        self.waypoints: Dict[str, Tuple[float, float, float]] = {
            # Legacy 1021 map waypoints (origin/main)
            'WP_HOME_1': (1.41, 2.05375, 270.0),
            'WP_HOME_2': (1.41, 1.8575, 270.0),
            'WP_HOME_3': (1.41, 1.66125, 270.0),
            'WP_LOAD_1': (2.015, 2.105, 0.0),
            'WP_LOAD_2': (2.015, 1.5375, 0.0),
            'WP_GATE_TRANSIT': (1.25, 0.335, 180.0),
            'WP_UNLOAD': (0.415, 1.85, 180.0),
            'WP_BENCH_DELIVERY': (0.29, 1.31, 90.0),

            # Synchronized navigation_v9 waypoints (X_sim = X_v9 + 1.372, Y_sim = Y_v9 + 1.579)
            'I1': (1.372, 1.579, 0.0),
            'I2': (1.372, 1.379, 0.0),
            'I3': (1.372, 1.179, 0.0),
            'ZA': (1.972, 2.079, 274.1),
            'ZB': (1.972, 1.429, 274.1),
            'ZC': (0.872, 1.879, 85.9),
            'ZA_EXIT': (1.872, 1.579, 274.1),
            'ZB_EXIT': (1.922, 0.979, 274.1),
            'ZC_EXIT': (1.072, 1.179, 85.9),
            'WA_slot0': (1.472, 2.179, 0.0),
            'WA_slot1': (1.472, 1.879, 0.0),
            'WA_slot2': (1.472, 1.579, 0.0),
            'WC_slot0': (0.672, 1.499, 85.9),
            'WC_slot1': (0.672, 1.199, 85.9),
            'WC_slot2': (0.672, 0.899, 85.9),
        }

        # Fixed Obstacles (Border walls + Interior furniture)
        self.obstacles: List[ObstacleBox] = [
            # Arena Outer Borders
            ObstacleBox('border_south', -0.05, 2.55, -0.05, 0.00),
            ObstacleBox('border_north', -0.05, 2.55, 2.40, 2.45),
            ObstacleBox('border_west', -0.05, 0.00, -0.05, 2.45),
            ObstacleBox('border_east', 2.50, 2.55, -0.05, 2.45),

            # Central Dividing Wall (X: 1.20~1.30, Y: gate_clearance_m~2.40)
            ObstacleBox('central_partition_wall', 1.20, 1.30, self.gate_clearance_m, 2.40),

            # Warehouse Right Rack (X: 2.16~2.40, Y: 0.67~2.40)
            ObstacleBox('wh_right_rack', 2.16, 2.40, 0.67, 2.40),

            # Warehouse Top Rack (X: 1.42~2.40, Y: 2.14~2.40)
            ObstacleBox('wh_top_rack', 1.42, 2.40, 2.14, 2.40),

            # Store Counter (X: 0.14~1.04, Y: 2.14~2.34)
            ObstacleBox('store_counter', 0.14, 1.04, 2.14, 2.34),

            # Store Display A (X: 0.44~0.82, Y: 1.29~1.45)
            ObstacleBox('store_display_a', 0.44, 0.82, 1.29, 1.45),

            # Store Bench B (X: 0.34~0.79, Y: 0.74~0.92)
            ObstacleBox('store_bench_b', 0.34, 0.79, 0.74, 0.92),

            # Store Racks 1 & 2
            ObstacleBox('store_rack_1', 0.04, 0.36, 1.64, 2.09),
            ObstacleBox('store_rack_2', 0.82, 1.14, 1.64, 2.09),
        ]

    def is_in_collision(self, x: float, y: float, radius: float = 0.07) -> bool:
        """Check if a circle at (x, y) with radius collides with any obstacle."""
        for obs in self.obstacles:
            closest_x = max(obs.x_min, min(x, obs.x_max))
            closest_y = max(obs.y_min, min(y, obs.y_max))
            dx = x - closest_x
            dy = y - closest_y
            if (dx * dx + dy * dy) < (radius * radius):
                return True
        return False

    def raycast_scan(
        self,
        rx: float,
        ry: float,
        yaw: float,
        num_rays: int = 180,
        min_range: float = 0.05,
        max_range: float = 3.5,
        extra_obstacles: Optional[List[ObstacleBox]] = None,
    ) -> List[float]:
        """Simulate a 360-degree 2D planar LiDAR scan around (rx, ry, yaw)."""
        all_obs = self.obstacles if extra_obstacles is None else self.obstacles + extra_obstacles
        angles = np.linspace(-math.pi, math.pi, num_rays, endpoint=False)
        ranges = []

        for rel_a in angles:
            beam_a = yaw + rel_a
            cos_a = math.cos(beam_a)
            sin_a = math.sin(beam_a)

            closest_dist = max_range
            for obs in all_obs:
                d = obs.ray_intersect(rx, ry, cos_a, sin_a, closest_dist)
                if d < closest_dist:
                    closest_dist = d

            if closest_dist < min_range:
                closest_dist = min_range
            ranges.append(closest_dist)

        return ranges
