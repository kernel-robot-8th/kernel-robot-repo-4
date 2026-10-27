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

"""Expose raw gripper current as the seventh state input for trained ACT 0.4.4 models."""

from dataclasses import dataclass
from functools import cached_property

from lerobot.robots.config import RobotConfig
from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
from lerobot.robots.omx_follower.omx_follower import OmxFollower


@RobotConfig.register_subclass("omx_follower_current")
@dataclass
class OmxCurrentConfig(OmxFollowerConfig):
    """Use the existing OMX calibration and append only the measured gripper current."""


class OmxCurrent(OmxFollower):
    """Read current every observation while leaving the six action targets unchanged."""

    config_class = OmxCurrentConfig
    name = "omx_follower"

    @cached_property
    def observation_features(self):
        """Match training state order: six positions followed by raw signed current."""
        return {**self._motors_ft, "gripper.current": float, **self._cameras_ft}

    def get_observation(self):
        """Read the live Present_Current register without normalizing or changing motor commands."""
        observation = super().get_observation()
        current = self.bus.sync_read("Present_Current", "gripper", normalize=False)["gripper"]
        return {
            **{key: observation[key] for key in self._motors_ft},
            "gripper.current": float(current),
            **{key: value for key, value in observation.items() if key not in self._motors_ft},
        }
