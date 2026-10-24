"""OMX follower that also reports the gripper motor current (robot type: omx_follower_grip).

Models trained on the *_grip datasets expect observation.state =
[shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos,
 gripper.pos, gripper.current]. The last value is the raw, signed Present_Current register of
the gripper motor (XL330-M288: 1 unit = 1 mA), the same value the recorder stored as
aux.gripper_current. Here it is named gripper_current.pos (see GRIP_KEY).

Importing this module registers the robot type; omx_rollout.py does that before lerobot-rollout.
Calibration is shared with the plain omx_follower (same robot name and calibration file).
"""

from dataclasses import dataclass
from functools import cached_property

from lerobot.robots.config import RobotConfig
from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
from lerobot.robots.omx_follower.omx_follower import OmxFollower

# lerobot-rollout only routes scalar features ending in ".pos"/".vel" into observation.state
# (lerobot/rollout/context.py), so the current needs a ".pos" suffix to reach the policy.
# Policies only use the state's order and size, not these names.
GRIP_KEY = "gripper_current.pos"


@RobotConfig.register_subclass("omx_follower_grip")
@dataclass
class OmxFollowerGripConfig(OmxFollowerConfig):
    pass


class OmxFollowerGrip(OmxFollower):
    config_class = OmxFollowerGripConfig
    name = "omx_follower"  # reuse omx_follower calibration files

    @cached_property
    def observation_features(self) -> dict:
        # state floats in dataset order (6 positions, then the current), then the cameras
        return {**self._motors_ft, GRIP_KEY: float, **self._cameras_ft}

    def get_observation(self):
        obs = super().get_observation()
        current = self.bus.sync_read("Present_Current", "gripper", normalize=False)["gripper"]
        ordered = {k: obs[k] for k in self._motors_ft}
        ordered[GRIP_KEY] = float(current)
        ordered.update({k: v for k, v in obs.items() if k not in ordered})
        return ordered
