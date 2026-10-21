import math

import numpy as np

from .config import ARM_MOTORS

# open_manipulator_description/urdf/omx_f/omx_f.urdf (ROBOTIS)
JOINT_ORIGINS = [
    (-0.01125, 0.0, 0.034),
    (0.0, 0.0, 0.0635),
    (0.0415, 0.0, 0.11315),
    (0.162, 0.0, 0.0),
    (0.0287, 0.0, 0.0),
]
JOINT_AXES = ["z", "y", "y", "y", "x"]
EE_OFFSET = (0.09193, -0.0016, 0.0)

TICKS_PER_REV = 4096
CENTER_TICK = 2048


def _trans(xyz):
    t = np.eye(4)
    t[:3, 3] = xyz
    return t


def _rot(axis, q):
    c, s = math.cos(q), math.sin(q)
    r = np.eye(4)
    if axis == "x":
        r[1:3, 1:3] = [[c, -s], [s, c]]
    elif axis == "y":
        r[0, 0], r[0, 2], r[2, 0], r[2, 2] = c, s, -s, c
    else:
        r[0:2, 0:2] = [[c, -s], [s, c]]
    return r


def _rpy(r):
    roll = math.atan2(r[2, 1], r[2, 2])
    pitch = math.atan2(-r[2, 0], math.hypot(r[2, 1], r[2, 2]))
    yaw = math.atan2(r[1, 0], r[0, 0])
    return roll, pitch, yaw


def forward_kinematics(q_rad):
    t = np.eye(4)
    for origin, axis, q in zip(JOINT_ORIGINS, JOINT_AXES, q_rad):
        t = t @ _trans(origin) @ _rot(axis, q)
    t = t @ _trans(EE_OFFSET)
    return np.array([t[0, 3], t[1, 3], t[2, 3], *_rpy(t[:3, :3])], dtype=np.float32)


class EEPoseCalculator:
    """Normalized joint values (-100~100) -> joint radians -> EE pose (x, y, z, roll, pitch, yaw)."""

    def __init__(self, calibration: dict, signs=None, offsets_deg=None):
        self.calibration = calibration
        self.signs = list(signs or [1] * 5)
        self.offsets = [math.radians(o) for o in (offsets_deg or [0.0] * 5)]

    def norm_to_rad(self, motor: str, norm: float, idx: int) -> float:
        cal = self.calibration[motor]
        v = -norm if cal.drive_mode else norm
        tick = cal.range_min + (v + 100.0) / 200.0 * (cal.range_max - cal.range_min)
        rad = (tick - CENTER_TICK) * 2.0 * math.pi / TICKS_PER_REV
        return self.signs[idx] * rad + self.offsets[idx]

    def compute(self, pos: dict) -> np.ndarray:
        q = [self.norm_to_rad(m, pos[m], i) for i, m in enumerate(ARM_MOTORS)]
        return forward_kinematics(q)
