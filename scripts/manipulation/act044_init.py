# Copyright 2026 HeoJiHyeok
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

"""Move to the saved dashboard pose after connection, before rollout observes its start."""

import json
import logging
import math
from pathlib import Path
import time

MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
LOGGER = logging.getLogger(__name__)


def load_pose(path):
    """Validate six normalized joint positions without connecting to hardware."""
    pose = json.loads(Path(path).read_text())["init"]
    if set(pose) != set(MOTORS):
        raise ValueError("Init pose must contain exactly the six OMX motor names")
    pose = {key: float(pose[key]) for key in MOTORS}
    for key, value in pose.items():
        lower = 0 if key == "gripper" else -100
        if not math.isfinite(value) or not lower <= value <= 100:
            raise ValueError(f"Invalid normalized Init position: {key}={value}")
    return pose


def move_to_init(robot, target, duration, clock=time.perf_counter, sleep=time.sleep):
    """Interpolate for duration, limit each command to 3 units, and verify arrival."""
    start = robot.bus.sync_read("Present_Position")
    started = clock()
    while True:
        elapsed = clock() - started
        fraction = min(elapsed / duration, 1.0)
        blend = fraction * fraction * (3 - 2 * fraction)
        current = robot.bus.sync_read("Present_Position")
        desired = {key: start[key] + blend * (target[key] - start[key]) for key in MOTORS}
        errors = {key: target[key] - current[key] for key in MOTORS}
        if elapsed >= duration and max(abs(v) for v in errors.values()) <= 3:
            LOGGER.info("Init pose reached; inference may start. Residuals: %s", errors)
            # Avoid carrying the optional EMA's init trajectory into the first policy action.
            if hasattr(robot, "_lpf_prev"):
                del robot._lpf_prev
            return
        if elapsed > duration + 3:
            raise RuntimeError(f"Init pose not reached; inference cancelled. Residuals: {errors}")
        robot.send_action(
            {key + ".pos": current[key] + max(-3, min(3, desired[key] - current[key])) for key in MOTORS}
        )
        sleep(1 / 30)


def install_init_pose(path, duration=3.0):
    """Install a bundle-local connect hook; importing this file never moves hardware."""
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    target = load_pose(path)
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Init duration must be finite and positive")
    original_connect = OmxFollower.connect

    def connect(self, *args, **kwargs):
        if self.config.use_degrees:
            raise ValueError("Saved dashboard Init pose requires robot.use_degrees=false")
        original_connect(self, *args, **kwargs)
        try:
            LOGGER.info("Moving to saved dashboard Init pose over %.1fs: %s", duration, target)
            move_to_init(self, target, duration)
        except BaseException:
            self.disconnect()
            raise

    OmxFollower.connect = connect
