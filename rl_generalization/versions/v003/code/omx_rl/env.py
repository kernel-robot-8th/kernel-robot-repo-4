"""Kinematic software test double. NOT an OMX/shoe physics simulator."""
from dataclasses import dataclass, asdict
import gymnasium as gym
import numpy as np
from gymnasium import spaces


@dataclass(frozen=True)
class EnvConfig:
    spread_m: float = 0.03
    max_steps: int = 100
    delta_m: float = 0.01
    hold_steps: int = 3

    def __post_init__(self):
        if not 0 <= self.spread_m <= 0.08:
            raise ValueError('spread_m must be in [0, 0.08] for this toy workspace')
        if not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError('max_steps must be a positive integer')
        if not isinstance(self.hold_steps, int) or self.hold_steps < 1:
            raise ValueError('hold_steps must be a positive integer')
        if not 0 < self.delta_m <= 0.02:
            raise ValueError('delta_m must be in (0, 0.02]')


class ToyGraspEnv(gym.Env):
    """4D action: dx,dy,dz,d(close fraction), each [-1,1].

    Fixed tool orientation, oracle target and attachment, no IK/contact/dynamics.
    16D observation: ee(3), object(3), object-ee(3), grip, held, hold fraction,
    previous normalized action(4). All positions are toy base-frame meters.
    """
    metadata = {'render_modes': []}

    def __init__(self, config=None):
        super().__init__()
        self.config = config or EnvConfig()
        self.action_space = spaces.Box(-1.0, 1.0, (4,), dtype=np.float32)
        self.observation_space = spaces.Box(-1.0, 1.0, (16,), dtype=np.float32)
        self.finished = True

    def _obs(self):
        return np.concatenate((self.ee, self.obj, self.obj-self.ee,
            [self.grip, float(self.held), self.hold/self.config.hold_steps], self.last)).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.ee = np.array([0.15, 0.0, 0.15], dtype=np.float64)
        xy = self.np_random.uniform(-self.config.spread_m, self.config.spread_m, 2)
        self.obj = np.array([0.15 + xy[0], xy[1], 0.02])
        if options and 'object_xy' in options:
            xy = np.asarray(options['object_xy'], dtype=float)
            if xy.shape != (2,) or not np.isfinite(xy).all() or not (0.05 <= xy[0] <= 0.25 and abs(xy[1]) <= 0.1):
                raise ValueError('object_xy must be a finite reachable toy position')
            self.obj[:2] = xy
        self.grip = 0.0
        self.held = False
        self.hold = self.steps = 0
        self.last = np.zeros(4)
        self.finished = False
        return self._obs(), {'is_success': False, 'domain': 'toy_only', 'config': asdict(self.config)}

    def step(self, action):
        if self.finished:
            raise RuntimeError('reset required before step / after episode end')
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (4,) or not np.isfinite(action).all() or np.any(abs(action) > 1.000001):
            raise ValueError('action must be finite shape (4,) in [-1, 1]')
        action = np.clip(action, -1, 1)
        self.ee = np.clip(self.ee + action[:3]*self.config.delta_m,
                          [0.03, -0.12, 0.02], [0.27, 0.12, 0.25])
        previous_grip = self.grip
        self.grip = float(np.clip(self.grip + 0.25*action[3], 0, 1))
        if self.held and self.grip <= 0.3:
            self.held = False
            self.obj[2] = 0.02  # toy instantaneous fall, not physical simulation
        if not self.held and previous_grip < 0.7 <= self.grip and np.linalg.norm(self.obj-self.ee) < 0.015:
            self.held = True
        if self.held:
            self.obj = self.ee.copy()
        self.hold = self.hold + 1 if self.held and self.obj[2] >= 0.09 else 0
        success = self.hold >= self.config.hold_steps
        # Dense reward uses oracle positions in the toy ONLY, unavailable on real robot.
        distance = float(np.linalg.norm(self.obj-self.ee))
        lift_error = max(0.0, 0.09-self.obj[2])
        reward = -0.01 - (lift_error if self.held else distance) - 0.001*float(action@action)
        if success:
            reward += 5.0
        self.steps += 1
        terminated = bool(success)
        truncated = bool(self.steps >= self.config.max_steps and not terminated)
        self.finished = terminated or truncated
        self.last = action.copy()
        info = {'is_success': bool(success), 'domain': 'toy_only',
                'termination_reason': 'success' if success else ('timeout' if truncated else None),
                'requested_action': action.tolist(), 'ee_target_m': self.ee.tolist(),
                'object_m': self.obj.tolist(), 'held': self.held}
        return self._obs(), float(reward), terminated, truncated, info
