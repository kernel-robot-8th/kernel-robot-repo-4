"""Protect the new experiment boundary and release-event evaluation."""

import numpy as np

from cobot_mujoco.actv2_data import SPLIT, plan
from cobot_mujoco.actv2_evaluate import trajectory_metrics
from cobot_mujoco.actv2_runner import training_command


def test_plan_excludes_chunk16_and_preserves_the_one_extra_batch32_trial():
    """Compare currents and architectures without reintroducing a time cutoff."""
    value = plan()
    trials = value["trials"]
    assert len(trials) == value["expected_jobs"] == 25
    assert sum(len(t["comparison_steps"]) for t in trials) == 75
    assert value["time_limit"] is None
    assert {t["chunk"] for t in trials} == {32, 64, 100}
    assert all(t["steps"] == 40000 for t in trials)
    assert len([t for t in trials if t["batch_size"] == 32]) == 1
    assert trials[-1]["current"] and trials[-1]["architecture"] == "standard"
    assert set(SPLIT["train"]).isdisjoint(SPLIT["validation"] + SPLIT["test"])
    assert set(sum(SPLIT.values(), [])) == set(range(9))
    args = training_command("/dataset", "/output", trials[0])
    assert "--dataset.repo_id=local/omx1026_v2" in args
    assert "--dataset.episodes=[0, 1, 3, 4, 5, 7]" in args
    assert not any("deadline" in arg for arg in args)


def test_gripper_missing_release_is_not_hidden_by_small_body_joint_errors():
    """Detect a release omitted by prediction even when every body joint is exact."""
    target = np.zeros((60, 6))
    target[:, 5] = 65
    target[15:40, 5] = 45
    exact = trajectory_metrics(target, target)
    assert exact["missed_open"] == 0 and exact["open_err_s"] == 0
    predicted = target.copy()
    predicted[40:, 5] = 45
    result = trajectory_metrics(predicted, target)
    assert result["joint_mae"] == 0
    assert result["missed_open"] == 1
    assert result["open_err_s"] is None
