"""Protect supplementary-recording roles, source balancing, and official-trainer inputs."""

import json
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cobot_mujoco.common import PACKAGE, read_json, write_json
from cobot_mujoco.data import RecordingDataset, correction_sample_weights, validate_split_plan
from cobot_mujoco.native_training import native_command, prepare_native_root
from cobot_mujoco.retraining_protocol import lightweight_grid, native_grid, recording_fold
from cobot_mujoco.retraining_report import aggregate_holdouts


def test_every_correction_is_held_out_once_and_never_in_its_model_training_set():
    """Keep user's supplemental data usable for learning without leaking each fold's held-out labels."""
    plan = read_json(PACKAGE / "config/retrain.json")
    assert plan["basic_ids"] == list(range(11))
    assert plan["correction_ids"] == list(range(11, 15))
    assert len(lightweight_grid(plan)) == 48
    assert len(native_grid(plan)) == 8
    held = []
    for fold in range(4):
        split, extra = recording_fold(plan, fold, "correction_concat")
        validate_split_plan(split)
        assert len(extra) == 2
        held += [i for i in split["test"] if i in plan["correction_ids"]]
        assert set(split["train"]) & set(split["test"] + split["validation"]) == set()
        basic, _ = recording_fold(plan, fold, "basic_only")
        assert set(basic["train"]) <= set(plan["basic_ids"])
        assert basic["test"] == split["test"] and basic["validation"] == split["validation"]
    assert sorted(held) == plan["correction_ids"]


def test_explicit_new_split_permits_supplementary_training_without_using_held_out_stats(tmp_path):
    """Fit new statistics on basic and supplementary training recordings only."""
    ids = [0, 11, 8, 9]
    values = np.array([[1] * 6, [10] * 6, [1000] * 6, [2000] * 6], np.float32)
    np.save(tmp_path / "states.npy", values)
    np.save(tmp_path / "actions.npy", values)
    np.save(tmp_path / "images.npy", np.zeros((4, 2, 3, 96, 128), dtype=np.uint8))
    write_json(
        tmp_path / "manifest.json",
        {"episodes": [{"id": episode, "start": i, "end": i + 1} for i, episode in enumerate(ids)]},
    )
    split = {"train": [0, 11], "validation": [8], "test": [9]}
    dataset = RecordingDataset(tmp_path, [0, 11], 16, split_plan=split)
    assert dataset.statistics["state_mean"] == [5.5] * 6
    with pytest.raises(ValueError, match="training recordings only"):
        RecordingDataset(tmp_path, [9], 16, split_plan=split)
    with pytest.raises(ValueError, match="disjoint"):
        validate_split_plan({"train": [0, 11], "validation": [11], "test": [9]})


def test_balanced_sampling_is_equal_per_domain_and_per_recording():
    """Do not let a long basic recording erase the intended correction sampling probability."""
    dataset = SimpleNamespace(recording_ids=[0, 0, 1, 11, 11, 11])
    weights = correction_sample_weights(dataset, [11]).numpy()
    assert np.isclose(weights[:3].sum(), 0.5)
    assert np.isclose(weights[3:].sum(), 0.5)
    assert np.isclose(weights[:2].sum(), weights[2])


def test_native_command_uses_upstream_defaults_and_excludes_test_ids():
    """Use the original trainer without hidden ACT width or resolution reductions."""
    split = {"train": [0, 1, 11], "validation": [8, 12], "test": [9, 13]}
    command = native_command("/tmp/source", "/tmp/output", split)
    assert "lerobot.scripts.lerobot_train" in command
    episodes = json.loads(next(x.split("=", 1)[1] for x in command if x.startswith("--dataset.episodes=")))
    assert episodes == split["train"] + split["validation"]
    assert set(episodes).isdisjoint(split["test"])
    assert not any("dim_model" in x or "chunk_size" in x or "resize" in x for x in command)


def test_native_statistics_are_recomputed_only_from_training_episode_metadata(tmp_path):
    """Prevent full-dataset metadata from leaking held-out action means into upstream training."""
    source = tmp_path / "source"
    (source / "meta/episodes/chunk-000").mkdir(parents=True)
    (source / "data").mkdir()
    (source / "videos").mkdir()
    rows = []
    for episode, mean in [(0, 1.0), (11, 9.0), (12, 999.0), (13, 9999.0)]:
        row = {"episode_index": episode}
        for feature in ["action", "observation.state"]:
            for stat, value in {
                "mean": [mean] * 6,
                "std": [1.0] * 6,
                "min": [mean - 1] * 6,
                "max": [mean + 1] * 6,
                "count": [2],
            }.items():
                row[f"stats/{feature}/{stat}"] = value
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows), source / "meta/episodes/chunk-000/file-000.parquet")
    root = prepare_native_root(
        source, tmp_path / "derived", {"train": [0, 11], "validation": [12], "test": [13]}
    )
    assert read_json(root / "meta/stats.json")["action"]["mean"] == [5.0] * 6
    assert (root / "videos").is_symlink()
    assert read_json(root / "training_partition.json")["normalization_fitted_on"] == [0, 11]


def test_summary_counts_unique_correction_recordings_instead_of_seed_repetitions():
    """Use four real held-out recording units rather than claiming eight independent tests."""
    plan = read_json(PACKAGE / "config/retrain.json")
    rows = []
    for seed in [17, 42]:
        for episode in plan["correction_ids"]:
            rows.append(
                {
                    "family": "act",
                    "regime": "correction_concat",
                    "metrics": {
                        "per_episode": {
                            str(episode): {"control_mae": float(episode - 10)},
                            "9": {"control_mae": 0.5},
                        }
                    },
                }
            )
    result = aggregate_holdouts(rows, plan)[0]
    assert result["unique_correction_recordings"] == 4
    assert result["unique_basic_test_recordings"] == 1
    assert result["correction_mae"] == 2.5
