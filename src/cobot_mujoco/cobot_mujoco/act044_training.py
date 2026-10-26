"""Train and score only ACT policies using the user's unchanged LeRobot 0.4.4 source."""

import hashlib
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

from .common import SOURCE_REPO, read_json


def provenance():
    """Reject a different runtime before any training and record exact source hashes."""
    import lerobot
    import lerobot.scripts.lerobot_train as trainer
    from lerobot.policies.act import modeling_act

    if version("lerobot") != "0.4.4":
        raise RuntimeError(f"LeRobot 0.4.4 required, found {version('lerobot')}")
    package = Path(lerobot.__file__).resolve()
    expected = Path.home() / "il_ws/src/lerobot/src/lerobot"
    if package.parent != expected:
        raise RuntimeError(f"Expected local il_ws LeRobot source, found {package}")
    git = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=expected, text=True).strip()
    return {
        "lerobot_version": version("lerobot"),
        "python": sys.executable,
        "python_version": sys.version,
        "torch": torch.__version__,
        "package": str(package),
        "source_git_commit": git,
        "trainer": trainer.__file__,
        "trainer_sha256": hashlib.sha256(Path(trainer.__file__).read_bytes()).hexdigest(),
        "act_source_sha256": hashlib.sha256(Path(modeling_act.__file__).read_bytes()).hexdigest(),
        "upstream_training_code_modified": False,
    }


def trial_plan():
    """Freeze matched architecture, chunk, step, learning-rate, and decay comparisons."""
    split = {"train": [0, 1, 2, 3, 4, 5, 6, 7, 10, 13, 14], "validation": [8, 12], "test": [9, 11]}
    rows = []
    for family, width, feedforward, depth in [("standard", 512, 3200, 4), ("light", 128, 512, 2)]:
        common = {
            "architecture": family,
            "dim_model": width,
            "dim_feedforward": feedforward,
            "n_encoder_layers": depth,
            "n_vae_encoder_layers": depth,
            "n_decoder_layers": 1,
            "vision_backbone": "resnet18",
            "image_shape": [3, 480, 640],
            "batch_size": 8,
            "seed": 17,
            "lr": 1e-5,
            "backbone_lr": 1e-5,
            "weight_decay": 1e-4,
            "dropout": 0.1,
            "split_plan": split,
            "save_freq": 1000,
        }
        for chunk in [16, 32, 64, 100]:
            rows.append(
                {
                    **common,
                    "name": f"act044_{family}_chunk{chunk}_base",
                    "chunk": chunk,
                    "steps": 20000,
                    "comparison_steps": [2000, 5000, 10000, 20000],
                    "variant": "base",
                }
            )
        for label, changes in [("lr3e5", {"lr": 3e-5}), ("decay1e3", {"weight_decay": 1e-3})]:
            rows.append(
                {
                    **common,
                    **changes,
                    "name": f"act044_{family}_chunk32_{label}",
                    "chunk": 32,
                    "steps": 10000,
                    "comparison_steps": [2000, 5000, 10000],
                    "variant": label,
                }
            )
    return {
        "required_lerobot": "0.4.4",
        "maximum_hours": 12,
        "final_reserve_seconds": 1800,
        "source_repo": SOURCE_REPO,
        "split_plan": split,
        "trials": rows,
        "expected_jobs": 12,
        "expected_comparison_cells": 44,
        "selection": (
            "Lowest validation recording-balanced first-10-step motor MAE per architecture, "
            "then open held-out recordings once for those two selections."
        ),
        "scope": (
            "ACT ResNet18+Transformer only. No standalone CNN, no MuJoCo, no physical robot. "
            "Existing inspected data makes this exploratory validation, not a new independent field test."
        ),
        "step_interpretation": (
            "Step comparisons share one continuous training trajectory; "
            "they are not independent reinitializations. "
            "No automatic LR schedule. Backbone LR held at 1e-5 in the main-LR sweep."
        ),
    }


def command(root, output, cfg):
    """Invoke the real 0.4.4 trainer with training IDs only and validation outside its loop."""
    return [
        sys.executable,
        "-m",
        "lerobot.scripts.lerobot_train",
        "--policy.type=act",
        "--policy.device=cuda",
        "--policy.push_to_hub=false",
        f"--policy.chunk_size={cfg['chunk']}",
        "--policy.n_action_steps=5",
        f"--policy.dim_model={cfg['dim_model']}",
        f"--policy.dim_feedforward={cfg['dim_feedforward']}",
        f"--policy.n_encoder_layers={cfg['n_encoder_layers']}",
        f"--policy.n_vae_encoder_layers={cfg['n_vae_encoder_layers']}",
        "--policy.n_decoder_layers=1",
        f"--policy.dropout={cfg['dropout']}",
        f"--policy.optimizer_lr={cfg['lr']}",
        f"--policy.optimizer_lr_backbone={cfg['backbone_lr']}",
        f"--policy.optimizer_weight_decay={cfg['weight_decay']}",
        f"--dataset.repo_id={SOURCE_REPO}",
        f"--dataset.root={root}",
        "--dataset.episodes=" + str(cfg["split_plan"]["train"]),
        "--dataset.video_backend=pyav",
        "--dataset.image_transforms.enable=false",
        f"--output_dir={output}",
        f"--steps={cfg['steps']}",
        f"--batch_size={cfg['batch_size']}",
        f"--seed={cfg['seed']}",
        f"--save_freq={cfg['save_freq']}",
        "--eval_freq=0",
        "--num_workers=2",
        "--log_freq=100",
        "--wandb.enable=false",
    ]


def verify_training_ids(root, cfg):
    """Verify the actual upstream dataset excludes validation and test recordings."""
    from lerobot.configs.default import DatasetConfig
    from lerobot.configs.train import TrainPipelineConfig
    from lerobot.datasets.factory import make_dataset
    from lerobot.policies.act.configuration_act import ACTConfig

    config = TrainPipelineConfig(
        dataset=DatasetConfig(
            repo_id=SOURCE_REPO, root=str(root), episodes=cfg["split_plan"]["train"], video_backend="pyav"
        ),
        policy=ACTConfig(device="cuda", push_to_hub=False),
    )
    dataset = make_dataset(config)
    if list(dataset.episodes) != cfg["split_plan"]["train"]:
        raise ValueError("Upstream 0.4.4 training recording IDs differ from frozen plan")
    return {"episodes": list(dataset.episodes), "frames": len(dataset)}


def score(checkpoint, root, episodes, stride=12):
    """Use saved 0.4.4 processors, float RGB without dividing it by 255 a second time."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(checkpoint).cuda().eval()
    pre, _ = make_pre_post_processors(
        policy.config,
        pretrained_path=checkpoint,
        preprocessor_overrides={"device_processor": {"device": "cuda"}},
    )
    dataset = LeRobotDataset(
        SOURCE_REPO,
        root=root,
        episodes=episodes,
        video_backend="pyav",
        delta_timestamps={"action": [i / 30 for i in range(policy.config.chunk_size)]},
    )
    loader = DataLoader(Subset(dataset, list(range(0, len(dataset), stride))), batch_size=8, num_workers=0)
    std = torch.tensor(read_json(Path(root) / "meta/stats.json")["action"]["std"], device="cuda")
    values = {}
    with torch.inference_mode():
        for raw in loader:
            ids = raw["episode_index"].reshape(-1).tolist()
            for key in policy.config.image_features:
                if raw[key].dtype == torch.uint8:
                    raw[key] = raw[key].float() / 255
                if raw[key].min() < 0 or raw[key].max() > 1.001:
                    raise ValueError("Expected 0.4.4 raw RGB in [0,1]")
            batch = pre(raw)
            predicted = policy.predict_action_chunk(batch)[:, :10]
            error = (predicted - batch["action"][:, :10]).abs() * std
            mask = ~batch["action_is_pad"][:, :10]
            mae = ((error * mask.unsqueeze(-1)).sum((1, 2)) / (mask.sum(1) * 6).clamp_min(1)).cpu().tolist()
            for episode, value in zip(ids, mae):
                values.setdefault(str(episode), []).append(value)
    result = {
        "control_mae": float(np.mean([np.mean(v) for v in values.values()])),
        "per_episode": {k: {"control_mae": float(np.mean(v)), "samples": len(v)} for k, v in values.items()},
        "parameters": sum(p.numel() for p in policy.parameters() if p.requires_grad),
        "input_shapes": {k: list(v.shape) for k, v in policy.config.input_features.items()},
        "backbone": policy.config.vision_backbone,
        "chunk": policy.config.chunk_size,
        "rgb_input_scale": "float [0,1]; loaded saved processor performs ImageNet normalization",
        "units": "Original LeRobot motor units, not degrees, metres, or task success",
    }
    del policy
    torch.cuda.empty_cache()
    return result
