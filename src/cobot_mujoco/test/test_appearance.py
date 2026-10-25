"""Separate visual recognition diagnostics from physical dynamics and successful grasps."""

import os
from pathlib import Path

import numpy as np
import pytest

from cobot_mujoco.common import PACKAGE, read_json
from cobot_mujoco.environment import OMXEnvironment
from cobot_mujoco.print_detector import PrintedBoxDetector


def assets():
    """Use fetched upstream assets only for the physics integration checks."""
    path = Path(os.environ.get("OMX_ROBOT_ASSETS", "/nonexistent"))
    if not path.exists():
        pytest.skip("Set OMX_ROBOT_ASSETS for image-appearance physics checks")
    return path


def test_visual_only_changes_do_not_change_trajectory_or_box_mass():
    """Make the appearance ablation keep exactly the same control and collision behavior."""
    before = read_json(PACKAGE / "config/scene.json")
    before.pop("appearance", None)
    # Recover frozen original geometry even after the improved scene becomes the default.
    legacy = PACKAGE / "config/scene_legacy.json"
    if legacy.exists():
        before = read_json(legacy)
    after = read_json(PACKAGE / "config/scene_appearance_visual.json")
    first, second = OMXEnvironment(assets(), before), OMXEnvironment(assets(), after)
    try:
        for step in range(60):
            target = np.array(before["initial_state"]) + [0, 0.01 * step, 0, 0, 0, 0]
            first.step(target)
            second.step(target)
            np.testing.assert_allclose(first.data.qpos, second.data.qpos, atol=1e-9)
        for i in range(2):
            assert first.model.body(f"box_{i}").mass == second.model.body(f"box_{i}").mass
    finally:
        first.close()
        second.close()


def test_split_lid_proxy_conserves_box_mass_and_does_not_claim_scene_validation():
    """Prevent a hollow, massless, or automatically successful improved-looking box."""
    config = read_json(PACKAGE / "config/scene_appearance_v2.json")
    env = OMXEnvironment(assets(), config)
    try:
        for i in range(2):
            assert abs(env.model.body(f"box_{i}").mass - config["box_mass"]) < 1e-10
        for _ in range(30):
            env.step(config["initial_state"])
        assert not env.metrics()["scene_validated"]
        assert not env.metrics()["real_world_success_claim_allowed"]
        assert not env.metrics()["success_any_box"]
    finally:
        env.close()


def test_uniform_white_or_pink_background_is_not_a_detected_box():
    """Require printed or bounded object evidence instead of accepting image-wide color."""
    detector = PrintedBoxDetector()
    for color in [[240, 240, 240], [220, 200, 197]]:
        rgb = np.zeros((480, 640, 3), np.uint8)
        rgb[:] = color
        assert not detector.detect(rgb)["detected"]
