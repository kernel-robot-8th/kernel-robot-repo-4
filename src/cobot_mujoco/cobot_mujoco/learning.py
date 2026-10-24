"""Small baselines and genuine LeRobot ACT with a shared evaluation contract."""

import random
import time

import numpy as np
import torch
from torch import nn

from .data import CAMERAS, HEIGHT, WIDTH


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(4)
    torch.set_float32_matmul_precision("high")


class BaselinePolicy(nn.Module):
    """State BC and two-camera CNN BC expose the same action chunk interface."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.vision = config["family"] == "cnn"
        self.horizon = config["horizon"]
        hidden = config.get("hidden", 256)
        if self.vision:
            self.encoder = nn.Sequential(
                nn.Conv2d(3, 24, 5, 2, 2),
                nn.ReLU(),
                nn.Conv2d(24, 48, 3, 2, 1),
                nn.ReLU(),
                nn.Conv2d(48, 64, 3, 2, 1),
                nn.ReLU(),
                nn.Conv2d(64, 64, 3, 2, 1),
                nn.ReLU(),
                nn.AdaptiveAvgPool2d((3, 4)),
                nn.Flatten(),
                nn.Linear(64 * 3 * 4, 128),
                nn.ReLU(),
            )
        inputs = 6 + (256 if self.vision else 0)
        self.head = nn.Sequential(
            nn.Linear(inputs, hidden),
            nn.ReLU(),
            nn.Dropout(config["dropout"]),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Dropout(config["dropout"]),
            nn.Linear(hidden, self.horizon * 6),
        )

    def predict_action_chunk(self, batch):
        state = batch["observation.state"]
        if self.vision:
            images = torch.stack([batch[f"observation.images.{name}"] for name in CAMERAS], 1)
            b, cameras, channels, h, w = images.shape
            features = self.encoder(images.reshape(b * cameras, channels, h, w)).reshape(b, -1)
            state = torch.cat([state, features], -1)
        return self.head(state).reshape(-1, self.horizon, 6)

    def forward(self, batch):
        prediction = self.predict_action_chunk(batch)
        valid = (~batch["action_is_pad"]).unsqueeze(-1)
        loss = ((prediction - batch["action"]).abs() * valid).sum() / (valid.sum() * 6).clamp_min(1)
        return loss, {"l1_loss": loss.detach().item()}


def make_policy(config, pretrained_backbone=True):
    if config["family"] != "act":
        return BaselinePolicy(config)
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy

    features = {"observation.state": PolicyFeature(type=FeatureType.STATE, shape=(6,))}
    features.update(
        {
            f"observation.images.{name}": PolicyFeature(type=FeatureType.VISUAL, shape=(3, HEIGHT, WIDTH))
            for name in CAMERAS
        }
    )
    cfg = ACTConfig(
        input_features=features,
        output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(6,))},
        chunk_size=config["horizon"],
        n_action_steps=config.get("action_steps", 10),
        dim_model=config.get("dim_model", 256),
        n_heads=8,
        dim_feedforward=config.get("dim_feedforward", 1024),
        n_encoder_layers=2,
        n_decoder_layers=1,
        n_vae_encoder_layers=2,
        dropout=config["dropout"],
        kl_weight=config.get("kl_weight", 10.0),
        pretrained_backbone_weights=("ResNet18_Weights.IMAGENET1K_V1" if pretrained_backbone else None),
        push_to_hub=False,
        device="cuda",
    )
    return ACTPolicy(cfg)


def prepare_batch(batch, device, augment=False, state_noise=0.0, ablation=None):
    pixels = batch["pixels"].to(device, non_blocking=True).float() / 255
    if augment:
        brightness = torch.empty(len(pixels), 2, 1, 1, 1, device=device).uniform_(0.8, 1.2)
        contrast = torch.empty(len(pixels), 2, 1, 1, 1, device=device).uniform_(0.8, 1.2)
        pixels = ((pixels - 0.5) * contrast + 0.5) * brightness
        # A small shared spatial translation preserves camera identity and image size.
        dx, dy = torch.randint(-3, 4, (2,)).tolist()
        pixels = torch.roll(pixels, (dx, dy), (-2, -1)).clamp(0, 1)
    mean = pixels.new_tensor([0.485, 0.456, 0.406])[None, None, :, None, None]
    std = pixels.new_tensor([0.229, 0.224, 0.225])[None, None, :, None, None]
    pixels = (pixels - mean) / std
    state = batch["observation.state"].to(device)
    if state_noise:
        state = state + torch.randn_like(state) * state_noise
    out = {
        "observation.state": state,
        "action": batch["action"].to(device),
        "action_is_pad": batch["action_is_pad"].to(device),
    }
    for i, camera in enumerate(CAMERAS):
        out[f"observation.images.{camera}"] = (
            torch.zeros_like(pixels[:, i]) if ablation == camera else pixels[:, i]
        )
    return out


@torch.inference_mode()
def evaluate(policy, loader, statistics, device="cuda", max_batches=None, ablation=None):
    """Evaluate deterministic latent-zero inference, in original motor units."""
    policy.eval()
    sums = {}
    std = torch.tensor(statistics["action_std"], device=device)
    started = time.monotonic()
    frames = 0
    for i, batch in enumerate(loader):
        if max_batches is not None and i >= max_batches:
            break
        prepared = prepare_batch(batch, device, ablation=ablation)
        prediction = policy.predict_action_chunk(prepared)
        error = (prediction - prepared["action"]).abs() * std
        valid = ~prepared["action_is_pad"]
        point = error[:, 0].mean(-1).cpu().numpy()
        chunk = ((error * valid.unsqueeze(-1)).sum((1, 2)) / (valid.sum(-1) * 6).clamp_min(1)).cpu().numpy()
        control_mask = valid[:, :10]
        control = (
            (
                (error[:, :10] * control_mask.unsqueeze(-1)).sum((1, 2))
                / (control_mask.sum(-1) * 6).clamp_min(1)
            )
            .cpu()
            .numpy()
        )
        for episode, p, c, h in zip(batch["episode"].tolist(), point, chunk, control):
            row = sums.setdefault(
                str(episode), {"point_sum": 0.0, "chunk_sum": 0.0, "control_sum": 0.0, "count": 0}
            )
            row["point_sum"] += float(p)
            row["chunk_sum"] += float(c)
            row["control_sum"] += float(h)
            row["count"] += 1
            frames += 1
    if not sums:
        raise ValueError("Empty evaluation")
    per_episode = {
        k: {
            "point_mae": v["point_sum"] / v["count"],
            "chunk_mae": v["chunk_sum"] / v["count"],
            "control_mae": v["control_sum"] / v["count"],
            "frames": v["count"],
        }
        for k, v in sums.items()
    }
    values = np.array([v["control_mae"] for v in per_episode.values()])
    rng = np.random.default_rng(1729)
    bootstrap = rng.choice(values, (2000, len(values)), replace=True).mean(1)
    return {
        "point_mae": float(np.mean([v["point_mae"] for v in per_episode.values()])),
        "control_mae": float(values.mean()),
        "selection_metric": "recording-balanced MAE over first 10 future control steps",
        "chunk_mae": float(np.mean([v["chunk_mae"] for v in per_episode.values()])),
        "recording_bootstrap_ci95": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
        "per_episode": per_episode,
        "sampled_frames": frames,
        "elapsed_s": time.monotonic() - started,
        "units": "LeRobot normalized motor positions; not metres or task success",
    }


class SimulationPolicy:
    """Adapt a checkpoint to rendered observations with its fitted normalization."""

    def __init__(self, policy, statistics, config, device="cuda", ensemble=False):
        self.policy, self.statistics, self.config = policy, statistics, config
        self.device, self.ensemble = device, ensemble
        self.queue = []
        self.chunks = []
        self.step = 0

    @torch.inference_mode()
    def action(self, environment):
        interval = min(self.config.get("action_steps", 10), self.config["horizon"])
        if self.step % interval == 0:
            state = (environment.state() - self.statistics["state_mean"]) / self.statistics["state_std"]
            pixels = np.stack([environment.render(name).transpose(2, 0, 1) for name in CAMERAS])
            batch = {
                "observation.state": torch.tensor(state, dtype=torch.float32)[None],
                "pixels": torch.from_numpy(pixels)[None],
                "action": torch.zeros(1, self.config["horizon"], 6),
                "action_is_pad": torch.zeros(1, self.config["horizon"], dtype=torch.bool),
            }
            self.policy.eval()
            prediction = self.policy.predict_action_chunk(prepare_batch(batch, self.device))[0]
            prediction = prediction.cpu().numpy() * self.statistics["action_std"]
            prediction += self.statistics["action_mean"]
            self.queue = list(prediction[:interval])
            self.chunks.append((self.step, prediction))
        if self.ensemble:
            self.chunks = [(start, chunk) for start, chunk in self.chunks if self.step - start < len(chunk)]
            actions = [chunk[self.step - start] for start, chunk in self.chunks]
            weights = np.exp(-0.01 * np.arange(len(actions)))
            action = np.average(actions, axis=0, weights=weights)
        else:
            action = self.queue.pop(0)
        self.step += 1
        return action
