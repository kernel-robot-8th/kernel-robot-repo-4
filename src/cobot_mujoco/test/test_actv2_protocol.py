"""Protect the new experiment boundary and release-event evaluation."""

import numpy as np

from cobot_mujoco.actv2_data import SPLIT, plan
from cobot_mujoco.actv2_evaluate import trajectory_metrics
from cobot_mujoco.actv2_runner import prune, training_command


def test_plan_excludes_chunk16_and_preserves_the_one_extra_batch32_trial():
    """Compare currents and architectures without reintroducing a time cutoff."""
    value = plan()
    trials = value["trials"]
    assert len(trials) == value["new_jobs"] == 25
    assert value["expected_jobs"] == 28 and value["inherited_jobs"] == 3
    assert sum(len(t["comparison_steps"]) for t in trials) == 75
    assert value["expected_comparison_cells"] == 75 + 9
    assert value["time_limit"] is None
    assert all(t["comparison_steps"] == [5000, 10000, 15000] for t in trials)
    assert {t["chunk"] for t in trials} == {32, 64, 100}
    assert all(t["steps"] == 15000 for t in trials)
    assert len([t for t in trials if t["batch_size"] == 32]) == 1
    assert trials[-1]["current"] and trials[-1]["architecture"] == "standard"
    assert set(SPLIT["train"]).isdisjoint(SPLIT["validation"] + SPLIT["test"])
    assert set(sum(SPLIT.values(), [])) == set(range(9))
    args = training_command("/dataset", "/output", trials[0])
    assert "--dataset.repo_id=local/omx1026_v2" in args
    assert args[2] == "cobot_mujoco.actv2_fast_train"
    assert "--policy.use_amp=true" in args and "--num_workers=4" in args
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


def test_revised_retention_keeps_5k_10k_15k_and_latest(tmp_path):
    """Do not discard the user's newly requested early comparison saves."""
    for step in [5000, 6000, 10000, 15000, 16000]:
        path = tmp_path / "checkpoints" / f"{step:06d}/pretrained_model"
        path.mkdir(parents=True)
        (path / "policy_postprocessor.json").write_text("{}")
    (tmp_path / "checkpoints/last").symlink_to(tmp_path / "checkpoints/016000")
    prune(tmp_path)
    assert (tmp_path / "checkpoints/005000").exists()
    assert (tmp_path / "checkpoints/010000").exists()
    assert (tmp_path / "checkpoints/015000").exists()
    assert (tmp_path / "checkpoints/016000").exists()
    assert not (tmp_path / "checkpoints/006000").exists()
