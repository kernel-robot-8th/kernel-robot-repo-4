"""Test leakage protection and conservative learning-curve interpretation."""

import numpy as np
import pytest

from cobot_mujoco.analysis import summarize_results
from cobot_mujoco.common import write_json
from cobot_mujoco.data import RecordingDataset


def test_statistics_use_only_the_selected_training_recordings(tmp_path):
    """Keep large held-out values from changing fitted means or padded targets."""
    np.save(tmp_path / "states.npy", np.array([[1] * 6, [3] * 6, [1000] * 6, [1000] * 6], np.float32))
    np.save(tmp_path / "actions.npy", np.array([[2] * 6, [4] * 6, [1000] * 6, [1000] * 6], np.float32))
    np.save(tmp_path / "images.npy", np.zeros((4, 2, 3, 96, 128), dtype=np.uint8))
    write_json(
        tmp_path / "manifest.json",
        {"episodes": [{"id": 0, "start": 0, "end": 2}, {"id": 8, "start": 2, "end": 4}]},
    )
    train = RecordingDataset(tmp_path, [0], horizon=3, stride=1)
    assert train.statistics["state_mean"] == [2] * 6
    assert train.statistics["action_mean"] == [3] * 6
    assert train[1]["action_is_pad"].tolist() == [False, True, True]
    with pytest.raises(ValueError, match="training recordings only"):
        RecordingDataset(tmp_path, [8], horizon=3)
    valid = RecordingDataset(tmp_path, [8], horizon=3, statistics=train.statistics)
    assert valid.statistics == train.statistics


def test_a_gap_alone_is_not_called_an_overfitting_pattern():
    """Require training improvement and later validation deterioration together."""
    config = {"name": "state_bc_2_seed17", "seed": 17}
    trial = {
        "config": config,
        "best_validation_mae": 2.0,
        "history": [
            {"step": 1, "training_mae": 1.0, "validation_mae": 2.5},
            {"step": 2, "training_mae": 0.8, "validation_mae": 2.0},
            {"step": 3, "training_mae": 0.8, "validation_mae": 3.0},
        ],
    }
    assert summarize_results([trial], [], {})["overfit_pattern_count"] == 0
    trial["history"][-1]["training_mae"] = 0.5
    assert summarize_results([trial], [], {})["overfit_pattern_count"] == 1
