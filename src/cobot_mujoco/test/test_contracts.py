"""Guard physical calibration, leakage boundaries, and success semantics."""

import copy
from pathlib import Path

import numpy as np
import pytest

from cobot_mujoco.common import PACKAGE, read_json
from cobot_mujoco.data import SPLITS, chunk_indices
from cobot_mujoco.environment import (
    OMXEnvironment,
    normalized_to_radians,
    placed_success,
    radians_to_normalized,
)
from cobot_mujoco.runner import trial_grid

SCENE = read_json(PACKAGE / "config/scene.json")


@pytest.mark.parametrize("gripper", [0, 50, 57, 62, 100])
def test_calibration_round_trip_and_gripper_zero(gripper):
    state = np.array([-50, -20, 35, 60, 0, gripper])
    q = normalized_to_radians(state, SCENE["calibration"])
    np.testing.assert_allclose(radians_to_normalized(q, SCENE["calibration"]), state, atol=1e-5)
    expected = (gripper / 100 * 4095 - 2048) * 2 * np.pi / 4096
    assert abs(q[5] - expected) < 1e-12


def test_drive_mode_round_trip():
    calibration = copy.deepcopy(SCENE["calibration"])
    calibration["drive_mode"] = [1] * 6
    state = np.array([3, 5, 7, 9, -4, 60])
    q = normalized_to_radians(state, calibration)
    np.testing.assert_allclose(radians_to_normalized(q, calibration), state, atol=1e-5)


def test_split_is_recording_disjoint_and_temporally_held_out():
    assert set(SPLITS["train"]).isdisjoint(SPLITS["validation"])
    assert set(SPLITS["train"]).isdisjoint(SPLITS["test"])
    assert set(SPLITS["validation"]).isdisjoint(SPLITS["test"])
    assert set(sum(SPLITS.values(), [])) == set(range(15))
    assert max(SPLITS["validation"]) < min(SPLITS["test"])


def test_action_chunk_does_not_cross_next_episode():
    indices, padded = chunk_indices(40, 50, 48, 5)
    assert indices.tolist() == [48, 49, 49, 49, 49]
    assert padded.tolist() == [False, False, True, True, True]


def test_success_needs_lift_release_stability_and_full_footprint():
    config = copy.deepcopy(SCENE)
    position = np.array([*config["receiver_center_xy"], config["receiver_top"] + config["box_half_size"][2]])
    assert placed_success(position, [0, 0, 0], True, True, config)
    assert not placed_success(position, [0, 0, 0], False, True, config)
    assert not placed_success(position, [0, 0, 0], True, False, config)
    assert not placed_success(position, [1, 0, 0], True, True, config)
    position[0] += config["receiver_radius"] - 0.005
    assert not placed_success(position, [0, 0, 0], True, True, config)


def test_grid_covers_families_and_scarcity_before_replicates():
    sweep = read_json(PACKAGE / "config/sweep.json")
    grid = trial_grid(sweep)
    first = grid[: len(sweep["experiments"])]
    assert len({c["name"] for c in grid}) == len(grid)
    assert {c["family"] for c in first} == {"state", "cnn", "act"}
    assert {c["train_episodes"] for c in first} == {2, 4, 8}
    assert len({c["seed"] for c in first}) == 1


def test_physics_step_preserves_finite_state_and_does_not_invent_success():
    import os

    assets = Path(os.environ.get("OMX_ROBOT_ASSETS", "/nonexistent"))
    if not assets.exists():
        pytest.skip("Fetch pinned robot assets and set OMX_ROBOT_ASSETS for integration test")
    env = OMXEnvironment(assets)
    try:
        for _ in range(30):
            env.step(env.config["initial_state"])
        assert abs(env.data.time - 1.0) < env.config["timestep"]
        assert np.isfinite(env.state()).all()
        assert not env.metrics()["success_any_box"]
        assert not env.metrics()["real_world_success_claim_allowed"]
        with pytest.raises(ValueError):
            env.step([float("nan")] * 6)
    finally:
        env.close()
