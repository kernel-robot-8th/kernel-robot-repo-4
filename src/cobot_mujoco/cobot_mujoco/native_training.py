"""Run the installed, unmodified LeRobot trainer with auditable dataset partitions."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pyarrow.parquet as pq

from .common import SOURCE_REPO, read_json, write_json
from .data import validate_split_plan


def prepare_native_root(source, target, split):
    """Keep source videos intact and restrict normalization statistics to training episodes."""
    from lerobot.datasets.compute_stats import aggregate_stats
    from lerobot.datasets.utils import serialize_dict

    source, target = Path(source), Path(target)
    validate_split_plan(split)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "meta", target / "meta", dirs_exist_ok=True)
    for name in ["data", "videos"]:
        path = target / name
        if not path.exists():
            path.symlink_to((source / name).resolve(), target_is_directory=True)
    rows = []
    for path in sorted((source / "meta/episodes").rglob("*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    statistics = []
    for row in rows:
        if row["episode_index"] not in split["train"]:
            continue
        stats = {}
        for key, value in row.items():
            if key.startswith("stats/"):
                feature, stat = key[6:].rsplit("/", 1)
                stats.setdefault(feature, {})[stat] = np.asarray(value)
        statistics.append(stats)
    if len(statistics) != len(split["train"]):
        raise ValueError("Native statistics need every declared training recording")
    write_json(target / "meta/stats.json", serialize_dict(aggregate_stats(statistics)))
    write_json(
        target / "training_partition.json",
        {
            "source": str(source),
            "split_plan": split,
            "normalization_fitted_on": split["train"],
            "upstream_training_code_modified": False,
        },
    )
    return target


def native_command(root, output, split, steps=10000, seed=17, batch_size=8, save_freq=1000):
    """Preserve ACT architecture defaults and original 640 by 480 camera inputs."""
    train = list(split["train"])
    validation = list(split["validation"])
    if validation and len(validation) != 2:
        raise ValueError("Native comparison expects the two predeclared validation recordings")
    episodes = train + validation
    fraction = 1.5 / len(episodes) if validation else 0.0
    return [
        sys.executable,
        "-m",
        "lerobot.scripts.lerobot_train",
        "--policy.type=act",
        "--policy.device=cuda",
        "--policy.push_to_hub=false",
        f"--dataset.repo_id={SOURCE_REPO}",
        f"--dataset.root={root}",
        f"--dataset.episodes={json.dumps(episodes)}",
        f"--dataset.eval_split={fraction}",
        "--dataset.video_backend=pyav",
        "--dataset.image_transforms.enable=false",
        f"--output_dir={output}",
        f"--steps={steps}",
        f"--batch_size={batch_size}",
        f"--seed={seed}",
        f"--save_freq={save_freq}",
        f"--eval_steps={save_freq if validation else 0}",
        "--max_eval_samples=192",
        "--log_freq=100",
        "--env_eval_freq=0",
        "--num_workers=2",
        "--prefetch_factor=2",
        "--wandb.enable=false",
    ]


def verify_native_partition(root, split):
    """Check the upstream episode split matches the frozen plan before training."""
    from lerobot.configs.default import DatasetConfig
    from lerobot.configs.train import TrainPipelineConfig
    from lerobot.datasets.factory import make_train_eval_datasets
    from lerobot.policies.act.configuration_act import ACTConfig

    episodes = split["train"] + split["validation"]
    cfg = TrainPipelineConfig(
        dataset=DatasetConfig(
            repo_id=SOURCE_REPO,
            root=str(root),
            episodes=episodes,
            eval_split=1.5 / len(episodes) if split["validation"] else 0.0,
            video_backend="pyav",
        ),
        policy=ACTConfig(device="cuda", push_to_hub=False),
    )
    train, valid = make_train_eval_datasets(cfg)
    actual = {
        "train": list(train.episodes),
        "validation": list(valid.episodes) if valid else [],
        "test": split["test"],
    }
    assert actual == split, (actual, split)
    return actual


def native_provenance():
    """Record the exact installed upstream source rather than claiming a modified loop is official."""
    from importlib.metadata import version
    import lerobot.scripts.lerobot_train as trainer

    path = Path(trainer.__file__)
    return {
        "lerobot_version": version("lerobot"),
        "train_module": str(path),
        "train_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "upstream_training_code_modified": False,
        "architecture": {
            "dim_model": 512,
            "dim_feedforward": 3200,
            "n_encoder_layers": 4,
            "n_decoder_layers": 1,
            "n_vae_encoder_layers": 4,
            "chunk_size": 100,
            "n_action_steps": 100,
            "images": [3, 480, 640],
            "optimizer_lr": 0.00001,
        },
    }


def native_checkpoints(output):
    """Locate actual saved upstream pretrained-model directories."""
    return sorted(
        [p for p in (Path(output) / "checkpoints").glob("*/pretrained_model") if p.parent.name.isdigit()],
        key=lambda p: int(p.parent.name),
    )


def evaluate_native(checkpoint, root, ids, stride=6):
    """Score original-resolution upstream models in original motor units over ten future steps."""
    import torch
    from torch.utils.data import DataLoader, Subset
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(checkpoint).cuda().eval()
    cfg = policy.config
    preprocessor, _ = make_pre_post_processors(
        cfg, pretrained_path=checkpoint, preprocessor_overrides={"device_processor": {"device": "cuda"}}
    )
    dataset = LeRobotDataset(
        SOURCE_REPO,
        root=root,
        episodes=ids,
        delta_timestamps={"action": [i / 30 for i in range(cfg.chunk_size)]},
        video_backend="pyav",
        return_uint8=True,
    )
    loader = DataLoader(Subset(dataset, list(range(0, len(dataset), stride))), batch_size=8, num_workers=0)
    stats = read_json(Path(root) / "meta/stats.json")
    std = torch.tensor(stats["action"]["std"], device="cuda")
    rows = {}
    with torch.inference_mode():
        for raw in loader:
            episode_ids = raw["episode_index"].reshape(-1).tolist()
            for key in policy.config.image_features:
                raw[key] = raw[key].float() / 255
            batch = preprocessor(raw)
            prediction = policy.predict_action_chunk(batch)
            error = (prediction[:, :10] - batch["action"][:, :10]).abs() * std
            valid = ~batch["action_is_pad"][:, :10]
            values = (
                ((error * valid.unsqueeze(-1)).sum((1, 2)) / (valid.sum(1) * 6).clamp_min(1)).cpu().tolist()
            )
            for episode, value in zip(episode_ids, values):
                rows.setdefault(str(episode), []).append(value)
    result = {
        "control_mae": float(np.mean([np.mean(v) for v in rows.values()])),
        "per_episode": {k: {"control_mae": float(np.mean(v)), "frames": len(v)} for k, v in rows.items()},
        "checkpoint": str(checkpoint),
        "steps": int(Path(checkpoint).parent.name),
        "learned_parameters": sum(p.numel() for p in policy.parameters()),
        "input_features": {k: list(v.shape) for k, v in cfg.input_features.items()},
        "metric": "Recording-balanced first-10-step motor MAE; not physical task success",
    }
    del policy
    torch.cuda.empty_cache()
    return result
