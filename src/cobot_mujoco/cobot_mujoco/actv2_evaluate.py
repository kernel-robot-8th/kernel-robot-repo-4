"""Evaluate all recorded validation frames and gripper transitions without actuating hardware."""

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

from .common import read_json


def events(values, threshold):
    """Find first closing and last reopening using the recorded open/closed levels."""
    closed = values < threshold
    if not closed.any():
        return None, None
    close = int(np.argmax(closed))
    opened = np.where(closed[:-1] & ~closed[1:])[0] + 1
    opened = opened[opened > close]
    return close, int(opened[-1]) if len(opened) else None


def trajectory_metrics(predicted, target, fps=30):
    """Separate body/gripper errors and expose missing release events as explicit counts."""
    error = np.abs(predicted - target)
    threshold = (np.median(target[:10, 5]) + target[:, 5].min()) / 2
    actual, estimate = events(target[:, 5], threshold), events(predicted[:, 5], threshold)
    result = {
        "joint_mae": float(error[:, :5].mean()),
        "gripper_mae": float(error[:, 5].mean()),
        "per_joint_mae": error.mean(0).tolist(),
        "threshold": float(threshold),
    }
    for i, name in enumerate(["close", "open"]):
        result[f"{name}_err_s"] = (
            abs(actual[i] - estimate[i]) / fps if actual[i] is not None and estimate[i] is not None else None
        )
        result[f"missed_{name}"] = int(actual[i] is not None and estimate[i] is None)
        result[f"gt_{name}_frame"] = actual[i]
        result[f"pred_{name}_frame"] = estimate[i]
    return result


def score(checkpoint, root, episodes, stride=1):
    """Score first-ten future MAE plus exact recorded-trajectory inference at horizon 1."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(checkpoint).cuda().eval()
    pre, post = make_pre_post_processors(
        policy.config,
        pretrained_path=checkpoint,
        preprocessor_overrides={"device_processor": {"device": "cuda"}},
    )
    dataset = LeRobotDataset(
        "local/omx1026_v2",
        root=root,
        episodes=episodes,
        video_backend="pyav",
        delta_timestamps={"action": [i / 30 for i in range(policy.config.chunk_size)]},
    )
    loader = DataLoader(Subset(dataset, list(range(0, len(dataset), stride))), batch_size=4, num_workers=0)
    stats = read_json(Path(root) / "meta/stats.json")
    std = torch.tensor(stats["action"]["std"], device="cuda")
    values, chunks, targets = {}, {}, {}
    with torch.inference_mode():
        for raw in loader:
            original_targets = raw["action"][:, 0].clone()
            for key in policy.config.image_features:
                if raw[key].dtype == torch.uint8:
                    raw[key] = raw[key].float() / 255
                if raw[key].min() < 0 or raw[key].max() > 1.001:
                    raise ValueError("Expected RGB [0,1]")
            batch = pre(raw)
            prediction = policy.predict_action_chunk(batch)
            error = (prediction[:, :10] - batch["action"][:, :10]).abs() * std
            mask = ~batch["action_is_pad"][:, :10]
            mae = (error * mask.unsqueeze(-1)).sum((1, 2)) / (mask.sum(1) * 6).clamp_min(1)
            # Saved upstream postprocessor converts normalized outputs back to motor units.
            unnormalized = torch.stack([post(prediction[:, i]) for i in range(policy.config.chunk_size)], 1)
            for i, episode in enumerate(raw["episode_index"].reshape(-1).tolist()):
                values.setdefault(episode, []).append(float(mae[i]))
                if stride == 1:
                    chunks.setdefault(episode, []).append(unnormalized[i].cpu())
                    targets.setdefault(episode, []).append(original_targets[i].cpu().numpy())
    result = {
        "control_mae": float(np.mean([np.mean(v) for v in values.values()])),
        "per_episode": {
            str(k): {"first10_mae": float(np.mean(v)), "frames": len(v)} for k, v in values.items()
        },
        "stride": stride,
        "scope": "Recorded observations, not real-world task success",
    }
    if stride == 1:
        for episode, predictions in chunks.items():
            ensemble = ACTTemporalEnsembler(0.01, policy.config.chunk_size)
            smoothed = [ensemble.update(chunk.unsqueeze(0)).squeeze(0).numpy() for chunk in predictions]
            target = np.asarray(targets[episode])
            result["per_episode"][str(episode)].update(
                {
                    "horizon1": trajectory_metrics(np.stack([p[0].numpy() for p in predictions]), target),
                    "ensemble001": trajectory_metrics(np.asarray(smoothed), target),
                }
            )
    del policy, loader, dataset
    torch.cuda.empty_cache()
    return result
