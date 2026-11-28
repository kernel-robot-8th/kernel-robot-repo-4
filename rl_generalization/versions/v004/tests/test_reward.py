import numpy as np
import pytest
from omx_rl.env import EnvConfig, ToyGraspEnv


def grasp_rewards(mode):
    env = ToyGraspEnv(EnvConfig(reward_mode=mode))
    env.reset(seed=0, options={'object_xy': [0.15, 0]})
    for _ in range(13): env.step([0, 0, -1, 0])
    for _ in range(2): env.step([0, 0, 0, 1])
    _, before, _, _, _ = env.step([0, 0, 0, 0])
    _, after, _, _, info = env.step([0, 0, 0, 1])
    assert info['grasp_event']
    return before, after


def test_reward_reversal_reproduced_and_corrected():
    before, after = grasp_rewards('legacy_v003')
    assert after < before
    before, after = grasp_rewards('staged_v1')
    assert after > before


@pytest.mark.parametrize('seed', range(20))
def test_scripted_oracle_can_reach_grasp_lift(seed):
    # Reachability check only; this controller is NOT training data or a policy result.
    env = ToyGraspEnv()
    env.reset(seed=seed)
    for _ in range(100):
        if env.held:
            action = [0, 0, 1 if env.obj[2] < 0.10 else 0, 0]
        else:
            delta = env.obj-env.ee
            action = [*np.clip(delta/env.config.delta_m, -1, 1),
                      1 if np.linalg.norm(delta) < 0.005 else -1]
        _, _, term, trunc, info = env.step(action)
        if term or trunc: break
    assert info['is_success']
