"""Open-loop evaluation of ACT / SmolVLA checkpoints on recorded episodes.

Every `horizon` frames the policy gets the recorded observation (real images + state + task),
predicts an action chunk, and the first `horizon` actions are kept. The kept actions are
concatenated into a predicted trajectory and compared with the recorded actions (open loop:
the predictions never change what the policy sees next).

Metrics, pooled over all frames of the given episodes (lerobot units, body joint 1 unit ~ 1.8 deg):
  joint_mae    mean |pred - gt| over the 5 body joints
  gripper_mae  mean |pred - gt| of the gripper
  close_err_s / open_err_s
               |pred - gt| time of the gripper closing (first) / opening (last) event, seconds,
               averaged over episodes; events use a threshold halfway between the recorded
               gripper's open level and its most-closed value. missed_* counts episodes where
               the prediction never crosses the threshold.
  smoothness   mean |a[t] - a[t-1]| over the 5 body joints (lower = smoother)
Stochastic policies (SmolVLA) are run with several seeds and the metrics averaged.
--ensemble_k k re-predicts every k frames and executes the weighted average of all overlapping
chunks (ACT temporal ensembling generalized; k=1 equals lerobot's temporal_ensemble_coeff).

Usage (inside the training image, e.g. via tools.sh):
  ./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 5,15,25,35,45 --horizon 50 \
      --model smolvla20k=/outputs/train/smolvla_box_merged/checkpoints/020000/pretrained_model \
      --out /outputs/eval/box_merged_1022.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import get_policy_class, make_pre_post_processors

DETERMINISTIC = {"act"}


def episode_range(ds, ep):
    e = ds.meta.episodes[ep]
    return int(e["dataset_from_index"]), int(e["dataset_to_index"])


def load_policy(path, device):
    ptype = json.loads((Path(path) / "config.json").read_text())["type"]
    policy = get_policy_class(ptype).from_pretrained(path)
    policy.config.device = device
    policy.to(device).eval()
    pre, post = make_pre_post_processors(
        policy.config, pretrained_path=path, preprocessor_overrides={"device_processor": {"device": device}}
    )
    return ptype, policy, pre, post


def predict_episode(policy, pre, post, frames, horizon):
    preds = []
    n = len(frames)
    for t in range(0, n, horizon):
        s = frames[t]
        obs = {k: v for k, v in s.items() if k.startswith("observation.")}
        obs["task"] = s["task"]
        with torch.inference_mode():
            a = post(policy.predict_action_chunk(pre(obs)))
        preds.append(a.squeeze(0).float().cpu().numpy()[: min(horizon, n - t)])
    return np.concatenate(preds, 0)


def ensemble_weights(ages, m):
    """ACT temporal-ensembling weights: exp(-m * i), i = 0 for the oldest prediction."""
    order = np.argsort(-np.asarray(ages))  # oldest (largest age) first
    w = np.empty(len(ages))
    w[order] = np.exp(-m * np.arange(len(ages)))
    return w / w.sum()


def predict_episode_ensemble(policy, pre, post, frames, k, m):
    """Re-predict every k frames; each executed action is the weighted average of every
    stored chunk that covers that frame (k=1 is lerobot's temporal ensembling)."""
    n, chunks, out = len(frames), [], []
    for t in range(n):
        if t % k == 0:
            s = frames[t]
            obs = {key: v for key, v in s.items() if key.startswith("observation.")}
            obs["task"] = s["task"]
            with torch.inference_mode():
                chunks.append((t, post(policy.predict_action_chunk(pre(obs))).squeeze(0).float().cpu().numpy()))
        chunks = [(s0, c) for s0, c in chunks if t - s0 < len(c)]
        ages = [t - s0 for s0, _ in chunks]
        w = ensemble_weights(ages, m)
        out.append(sum(wi * c[t - s0] for wi, (s0, c) in zip(w, chunks)))
    return np.stack(out)


def smoothness(preds):
    """Mean |a[t] - a[t-1]| over the 5 body joints (lower = smoother)."""
    return float(np.mean(np.concatenate([np.abs(np.diff(p[:, :5], axis=0)) for p in preds])))


def gripper_events(g, thr):
    below = g < thr
    if not below.any():
        return None, None
    close = int(np.argmax(below))
    rises = np.where(below[:-1] & ~below[1:])[0] + 1
    rises = rises[rises > close]
    return close, (int(rises[-1]) if len(rises) else None)


def metrics(preds, gts, fps):
    err = np.concatenate([np.abs(p - g) for p, g in zip(preds, gts)])
    out = {"joint_mae": float(err[:, :5].mean()), "gripper_mae": float(err[:, 5].mean())}
    for name, idx in (("close", 0), ("open", 1)):
        diffs, missed = [], 0
        for p, g in zip(preds, gts):
            thr = (np.median(g[:10, 5]) + g[:, 5].min()) / 2
            ge, pe = gripper_events(g[:, 5], thr)[idx], gripper_events(p[:, 5], thr)[idx]
            if ge is None:
                continue
            if pe is None:
                missed += 1
            else:
                diffs.append(abs(pe - ge) / fps)
        out[f"{name}_err_s"] = float(np.mean(diffs)) if diffs else None
        out[f"missed_{name}"] = missed
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_root", required=True)
    ap.add_argument("--episodes", required=True, help="comma list")
    ap.add_argument("--model", action="append", required=True, help="name=checkpoint_dir")
    ap.add_argument("--horizon", default="50",
                    help="frames executed per prediction, or 'default' (policy n_action_steps)")
    ap.add_argument("--seeds", type=int, default=3, help="seeds for stochastic policies")
    ap.add_argument("--out", required=True, help="metrics json path (predictions saved next to it)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--ensemble_k", type=int, default=0,
                    help="if > 0: re-predict every k frames and average overlapping chunks (ignores --horizon)")
    ap.add_argument("--ensemble_m", type=float, default=0.01, help="ensembling weight coefficient")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ds = LeRobotDataset("local/" + Path(args.dataset_root).name, root=args.dataset_root)
    episodes = [int(x) for x in args.episodes.split(",")]
    frames, gts = {}, {}
    for ep in episodes:
        a, b = episode_range(ds, ep)
        frames[ep] = [ds[i] for i in range(a, b)]
        gts[ep] = np.stack([np.asarray(f["action"]) for f in frames[ep]]).astype(np.float32)

    results = json.loads(out.read_text()) if out.exists() else {}
    for spec in args.model:
        name, path = spec.split("=", 1)
        ptype, policy, pre, post = load_policy(path, args.device)
        horizon = policy.config.n_action_steps if args.horizon == "default" else int(args.horizon)
        assert horizon <= policy.config.chunk_size, (horizon, policy.config.chunk_size)
        tag = f"e{args.ensemble_k}m{args.ensemble_m}" if args.ensemble_k else f"h{horizon}"
        seeds = [0] if ptype in DETERMINISTIC else list(range(args.seeds))
        per_seed = []
        for seed in seeds:
            torch.manual_seed(seed)
            if args.ensemble_k:
                preds = [predict_episode_ensemble(policy, pre, post, frames[ep], args.ensemble_k, args.ensemble_m)
                         for ep in episodes]
            else:
                preds = [predict_episode(policy, pre, post, frames[ep], horizon) for ep in episodes]
            for ep, p in zip(episodes, preds):
                np.save(out.parent / f"{out.stem}_{name}_{tag}_s{seed}_ep{ep:03d}.npy", p)
            per_seed.append({**metrics(preds, [gts[ep] for ep in episodes], ds.fps), "smoothness": smoothness(preds)})
        agg = {}
        for k in per_seed[0]:
            vals = [m[k] for m in per_seed if m[k] is not None]
            agg[k] = round(float(np.mean(vals)), 4) if vals else None
        results[f"{name}@{tag}"] = {"path": path, "type": ptype, "horizon": horizon, "seeds": len(seeds),
                                    "ensemble_k": args.ensemble_k,
                                    "ensemble_m": args.ensemble_m if args.ensemble_k else None,
                                    "episodes": episodes, **agg}
        print(f"{name:>24} {tag:>10} " + " ".join(f"{k}={v}" for k, v in agg.items()), flush=True)
        out.write_text(json.dumps(results, indent=2))
        del policy
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
