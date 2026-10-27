"""Freeze the new local recordings and prepare position/current inputs without leakage."""

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .common import read_json, write_json

SPLIT = {"train": [0, 1, 3, 4, 5, 7], "validation": [2, 6], "test": [8]}


def plan():
    """Keep both ACT sizes and the complete controlled 2x2x2x3 comparison."""
    trials = []
    for architecture, width, feedforward, layers in [("standard", 512, 3200, 4), ("light", 128, 512, 2)]:
        for current in [False, True]:
            for batch in [8, 16]:
                for chunk in [32, 64, 100]:
                    trials.append(
                        {
                            "name": (
                                f"v2_{architecture}_{'current' if current else 'position'}_b{batch}_c{chunk}"
                            ),
                            "architecture": architecture,
                            "current": current,
                            "batch_size": batch,
                            "chunk": chunk,
                            "dim_model": width,
                            "dim_feedforward": feedforward,
                            "n_encoder_layers": layers,
                            "n_vae_encoder_layers": layers,
                            "steps": 15000,
                            "comparison_steps": [5000, 10000, 15000],
                            "seed": 17,
                            "lr": 1e-5,
                            "backbone_lr": 1e-5,
                            "weight_decay": 1e-4,
                            "dropout": 0.1,
                            "save_freq": 1000,
                            "gpu_acceleration": "bf16_tf32_cudnn",
                            "use_amp": True,
                            "num_workers": 4,
                            "split_plan": SPLIT,
                        }
                    )
    extra = next(
        row
        for row in trials
        if row["architecture"] == "standard"
        and row["current"]
        and row["chunk"] == 32
        and row["batch_size"] == 16
    )
    trials.append({**extra, "batch_size": 32, "name": "v2_standard_current_b32_c32"})
    return {
        "trials": trials,
        "split_plan": SPLIT,
        "new_jobs": 25,
        "inherited_jobs": 3,
        "expected_jobs": 28,
        "expected_comparison_cells": 84,
        "lerobot_version": "0.4.4",
        "time_limit": None,
    }


def state_stats(array):
    """Use the installed upstream feature-statistics routine for the expanded state."""
    from lerobot.datasets.compute_stats import get_feature_stats

    return {k: np.asarray(v).reshape(-1) for k, v in get_feature_stats(array, axis=0, keepdims=False).items()}


def prepare(source, run):
    """Copy an immutable snapshot, validate recordings, and derive both training-only normalizers."""
    from lerobot.datasets.compute_stats import aggregate_stats
    from lerobot.datasets.utils import serialize_dict

    source, run = Path(source), Path(run)
    frozen = run / "source_snapshot"
    marker = run / "source_manifest.json"
    if not marker.exists():
        shutil.copytree(source, frozen, dirs_exist_ok=True)
        manifest = {
            str(p.relative_to(frozen)): {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(frozen.rglob("*"))
            if p.is_file()
        }
        write_json(marker, {"original": str(source), "files": manifest})
    info = read_json(frozen / "meta/info.json")
    if info["total_episodes"] != 9 or info["fps"] != 30:
        raise ValueError("Frozen comparison expects 9 recordings at 30 FPS")
    all_ids, arrays = set(), {}
    for file in sorted((frozen / "data").rglob("*.parquet")):
        table = pq.read_table(file).to_pydict()
        ids = np.asarray(table["episode_index"])
        state = np.asarray(table["observation.state"], dtype=np.float32)
        current = np.asarray(table["aux.gripper_current"], dtype=np.float32).reshape(-1, 1)
        action = np.asarray(table["action"], dtype=np.float32)
        if not (np.isfinite(state).all() and np.isfinite(current).all() and np.isfinite(action).all()):
            raise ValueError("Non-finite state, action, or gripper current")
        if not np.all(np.asarray(table["episode_success"]) == 1):
            raise ValueError("A non-success frame is present in the success dataset")
        for episode in np.unique(ids):
            all_ids.add(int(episode))
            arrays.setdefault(int(episode), []).append(
                np.concatenate([state[ids == episode], current[ids == episode]], 1)
            )
    if all_ids != set(range(9)):
        raise ValueError("Unexpected recording IDs")
    arrays = {key: np.concatenate(value) for key, value in arrays.items()}
    for include_current in [False, True]:
        name = "current" if include_current else "position"
        target = run / "datasets" / name
        if (target / "PREPARED").exists():
            continue
        shutil.copytree(frozen / "meta", target / "meta", dirs_exist_ok=True)
        (target / "videos").symlink_to(frozen / "videos", target_is_directory=True) if not (
            target / "videos"
        ).exists() else None
        if include_current:
            for original in sorted((frozen / "data").rglob("*.parquet")):
                table = pq.read_table(original)
                state = np.stack(table["observation.state"].to_numpy()).astype(np.float32)
                current = np.stack(table["aux.gripper_current"].to_numpy()).astype(np.float32).reshape(-1, 1)
                expanded = np.concatenate([state, current], 1)
                column = pa.FixedSizeListArray.from_arrays(pa.array(expanded.reshape(-1), pa.float32()), 7)
                metadata = table.schema.metadata
                table = table.set_column(
                    table.schema.get_field_index("observation.state"),
                    pa.field("observation.state", column.type),
                    column,
                )
                if metadata and b"huggingface" in metadata:
                    hf = json.loads(metadata[b"huggingface"])
                    feature = hf.get("info", {}).get("features", {}).get("observation.state", {})
                    if "length" in feature:
                        feature["length"] = 7
                    metadata = {**metadata, b"huggingface": json.dumps(hf).encode()}
                file = target / original.relative_to(frozen)
                file.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(table.replace_schema_metadata(metadata), file)
        elif not (target / "data").exists():
            (target / "data").symlink_to(frozen / "data", target_is_directory=True)
        changed_info = read_json(frozen / "meta/info.json")
        if include_current:
            changed_info["features"]["observation.state"]["shape"] = [7]
            changed_info["features"]["observation.state"]["names"].append("gripper.current")
        write_json(target / "meta/info.json", changed_info)
        train_stats = []
        for file in sorted((target / "meta/episodes").rglob("*.parquet")):
            rows = pq.read_table(file).to_pylist()
            for row in rows:
                episode = row["episode_index"]
                if include_current:
                    for stat, value in state_stats(arrays[episode]).items():
                        row[f"stats/observation.state/{stat}"] = value.tolist()
                if episode in SPLIT["train"]:
                    stats = {}
                    for key, value in row.items():
                        if key.startswith("stats/"):
                            feature, stat = key[6:].rsplit("/", 1)
                            stats.setdefault(feature, {})[stat] = np.asarray(value)
                    train_stats.append(stats)
            if include_current:
                pq.write_table(pa.Table.from_pylist(rows), file)
        write_json(target / "meta/stats.json", serialize_dict(aggregate_stats(train_stats)))
        write_json(
            target / "training_partition.json",
            {
                "split_plan": SPLIT,
                "normalization_fitted_on": SPLIT["train"],
                "frames": {key: sum(len(arrays[i]) for i in ids) for key, ids in SPLIT.items()},
                "state_dim": 7 if include_current else 6,
            },
        )
        (target / "PREPARED").write_text("training-only normalization; frozen source\n")
    return info
