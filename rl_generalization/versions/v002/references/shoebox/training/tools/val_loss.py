"""Validation loss of ACT checkpoints on held-out episodes (lerobot 0.4.4 lerobot-train has no val loss).

loss = the l1_loss term of ACT training (|predicted chunk - recorded chunk|, normalized action units,
padded steps masked), but computed the way the policy runs at inference: eval mode, VAE latent = 0,
no image augmentation. Training's logged loss also has the KL term (x10) and uses the VAE posterior,
so compare checkpoints with this number, not with the training log.

Every given episode is scored separately (every --stride-th frame as chunk start), so held-out and
training episodes can be compared with the same metric. Samples are decoded once and reused for all
checkpoints.

Usage (omx-act:0.4.4 or omx-moge:0.4.4 image, from the project root):
  python -I tools/val_loss.py --dataset_root data/shoebox_ab --episodes 0,9,10,19 \
      --ckpts outputs/train/act_shoebox_a/checkpoints --out outputs/eval/val_shoebox.json [--stride 2]
--ckpts is a checkpoints/ folder (all numbered checkpoints) or one pretrained_model folder; repeatable.
The dataset must contain every input of the model (e.g. top_depth -> the _moge dataset).
"""

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import default_collate

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import get_policy_class, make_pre_post_processors


def compact(s):
    """Images back to uint8 (they are decoded from 8-bit video, so this is lossless) to keep RAM small."""
    return {k: (v * 255).round().to(torch.uint8) if k.startswith("observation.images.") else v for k, v in s.items()}


def expand(batch):
    return {k: v.float() / 255 if k.startswith("observation.images.") else v for k, v in batch.items()}


def checkpoint_dirs(path):
    p = Path(path)
    if (p / "config.json").exists():
        return [(p.parent.name, p)]
    return [(d.name, d / "pretrained_model") for d in sorted(p.iterdir()) if d.name.isdigit()]


@torch.no_grad()
def l1(policy, pre, samples, bs, device):
    total, count = 0.0, 0.0
    for i in range(0, len(samples), bs):
        batch = pre(expand(default_collate(samples[i : i + bs])))
        batch["observation.images"] = [batch[k].to(device) for k in policy.config.image_features]
        actions_hat, _ = policy.model(batch)
        mask = ~batch["action_is_pad"].to(device).unsqueeze(-1)
        err = (batch["action"].to(device) - actions_hat).abs() * mask
        total += err.sum().item()
        count += mask.sum().item() * actions_hat.shape[-1]
    return total / count  # = training l1_loss when nothing is padded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_root", required=True)
    ap.add_argument("--episodes", required=True, help="comma list")
    ap.add_argument("--ckpts", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    ckpts = [(Path(c), checkpoint_dirs(c)) for c in args.ckpts]
    cfg = json.loads((ckpts[0][1][0][1] / "config.json").read_text())
    root = Path(args.dataset_root)
    meta = LeRobotDataset(f"local/{root.name}", root=root).meta
    ds = LeRobotDataset(f"local/{root.name}", root=root,
                        delta_timestamps={"action": [i / meta.fps for i in range(cfg["chunk_size"])]})
    samples = {}
    for ep in (int(x) for x in args.episodes.split(",")):
        e = ds.meta.episodes[ep]
        samples[ep] = [compact(ds[i]) for i in range(int(e["dataset_from_index"]), int(e["dataset_to_index"]), args.stride)]
        print(f"episode {ep}: {len(samples[ep])} samples", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(out.read_text()) if out.exists() else {}
    for run_dir, dirs in ckpts:
        run = run_dir.parent.name if run_dir.name == "checkpoints" else str(run_dir)
        for step, path in dirs:
            policy = get_policy_class("act").from_pretrained(path)
            policy.config.device = args.device
            policy.to(args.device).eval()
            pre, _ = make_pre_post_processors(policy.config, pretrained_path=path,
                                              preprocessor_overrides={"device_processor": {"device": args.device}})
            r = {str(ep): round(l1(policy, pre, s, args.batch_size, args.device), 5) for ep, s in samples.items()}
            results.setdefault(run, {})[str(int(step))] = r
            print(f"{run} {int(step):>6} " + " ".join(f"ep{k}={v}" for k, v in r.items()), flush=True)
            out.write_text(json.dumps(results, indent=2))
            del policy
            torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
