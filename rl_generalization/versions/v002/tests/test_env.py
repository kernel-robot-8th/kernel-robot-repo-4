import numpy as np
import pytest
from stable_baselines3.common.env_checker import check_env
from omx_rl.env import EnvConfig, ToyGraspEnv


def test_api_and_deterministic_reset():
    env = ToyGraspEnv()
    check_env(env)
    a, _ = env.reset(seed=7)
    b, _ = env.reset(seed=7)
    np.testing.assert_array_equal(a, b)
    assert env.observation_space.contains(a)


def test_timeout_is_not_success():
    env = ToyGraspEnv(EnvConfig(max_steps=1))
    env.reset(seed=1)
    _, _, terminated, truncated, info = env.step(np.zeros(4))
    assert truncated and not terminated and not info['is_success']
    with pytest.raises(RuntimeError): env.step(np.zeros(4))


def test_empty_close_is_not_grasp():
    env = ToyGraspEnv()
    env.reset(seed=0)
    for _ in range(4): env.step([0,0,0,1])
    assert not env.held


def test_lift_hold_and_release():
    env = ToyGraspEnv()
    env.reset(seed=0, options={'object_xy':[0.15,0.0]})
    for _ in range(13): env.step([0,0,-1,0])
    for _ in range(3): env.step([0,0,0,1])
    assert env.held
    for _ in range(3): env.step([0,0,1,0])
    for _ in range(3): env.step([0,0,0,-1])
    assert not env.held and env.obj[2] == 0.02 and env.hold == 0
    # Reset and demonstrate the complete task through the public API.
    env.reset(seed=0, options={'object_xy':[0.15,0.0]})
    for _ in range(13): env.step([0,0,-1,0])
    for _ in range(3): env.step([0,0,0,1])
    terminated = False
    for _ in range(12):
        obs, _, terminated, truncated, info = env.step([0,0,1,0])
        if terminated: break
    assert terminated and not truncated and info['is_success']
    assert env.observation_space.contains(obs)


@pytest.mark.parametrize('action', [[0,0,float('nan'),0], [2,0,0,0], [0,0]])
def test_invalid_action(action):
    env = ToyGraspEnv(); env.reset(seed=0)
    with pytest.raises(ValueError): env.step(action)


def test_config_validation():
    with pytest.raises(ValueError): EnvConfig(spread_m=1)
    with pytest.raises(ValueError): EnvConfig(max_steps=0)
