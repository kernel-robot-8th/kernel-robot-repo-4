"""Open-loop evaluation of policy checkpoints (SmolVLA or ACT, type read from config.json) on recorded episodes.

For each episode, every `chunk` frames the policy gets the recorded observation (real camera
images + joint state + task text) and predicts an action chunk; the chunks are concatenated
into a predicted joint trajectory and compared with the recorded actions.
The policy's actions never change what it sees next (open loop).

Usage (inside the omx-lerobot-sim container):
  python -I sim/eval_open_loop.py --out outputs/eval/open_loop \
      --model base=lerobot/smolvla_base \
      --model 2k=outputs/train/smolvla_omx_heart_box/checkpoints/002000/pretrained_model \
      --model 20k=outputs/train/smolvla_omx_heart_box/checkpoints/020000/pretrained_model
  ACT trained with the gripper current in the state (7 values) on a dataset whose state has 6:
  python -I sim/eval_open_loop.py --dataset_root data/omx_1024_test_jihyeok_success \
      --repo_id local/omx_1024_test_jihyeok_success --add_gripper_current --chunk 100 \
      --model 5ep=outputs/train/act_omx_1024_boxaug_grip/checkpoints/088655/pretrained_model
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import get_policy_class, make_pre_post_processors

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def episode_range(ds, ep):
    e = ds.meta.episodes[ep]
    return int(e["dataset_from_index"]), int(e["dataset_to_index"])


def load_policy(path):
    cfg = json.loads((Path(path) / "config.json").read_text()) if Path(path).exists() else {"type": "smolvla"}
    return get_policy_class(cfg["type"]).from_pretrained(path)


def predict_episode(policy, pre, post, ds, ep, chunk, device, task_override=None, add_gripper_current=False):
    start, end = episode_range(ds, ep)
    preds = []
    for t in range(start, end, chunk):
        s = ds[t]
        obs = {k: v for k, v in s.items() if k.startswith("observation.")}
        if add_gripper_current:  # policy trained on state = 6 joints + aux.gripper_current
            obs["observation.state"] = torch.cat([obs["observation.state"], s["aux.gripper_current"].reshape(1).float()])
        obs["task"] = task_override or s["task"]
        with torch.inference_mode():
            batch = pre(obs)
            a = policy.predict_action_chunk(batch)  # (1, chunk_size, action_dim), normalized
            a = post(a)
        a = a.squeeze(0).float().cpu().numpy()[: min(chunk, end - t)]
        preds.append(a)
    return np.concatenate(preds, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_root", default="data/omx_heart_box")
    ap.add_argument("--repo_id", default="Sungah/omx_heart_box")
    ap.add_argument("--model", action="append", required=True, help="name=path_or_hub_id")
    ap.add_argument("--episodes", default="all", help="comma list or 'all'")
    ap.add_argument("--chunk", type=int, default=50, help="frames executed per prediction")
    ap.add_argument("--out", default="outputs/eval/open_loop")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--task_override", default=None, help="feed this task text instead of the dataset's")
    ap.add_argument("--add_gripper_current", action="store_true",
                    help="append aux.gripper_current to observation.state (for *_grip policies)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = LeRobotDataset(args.repo_id, root=args.dataset_root)
    episodes = list(range(ds.num_episodes)) if args.episodes == "all" else [int(x) for x in args.episodes.split(",")]

    gt = {}
    for ep in episodes:
        start, end = episode_range(ds, ep)
        gt[ep] = np.stack([np.asarray(x) for x in ds.hf_dataset[start:end]["action"]]).astype(np.float32)

    results = {}
    for spec in args.model:
        name, path = spec.split("=", 1)
        print(f"== {name}: {path}", flush=True)
        torch.manual_seed(args.seed)
        policy = load_policy(path)
        policy.config.device = args.device
        policy.to(args.device).eval()
        pre, post = make_pre_post_processors(
            policy.config, pretrained_path=path,
            preprocessor_overrides={"device_processor": {"device": args.device}},
        )
        per_ep = {}
        for ep in episodes:
            pred = predict_episode(policy, pre, post, ds, ep, args.chunk, args.device, args.task_override,
                                   args.add_gripper_current)
            np.save(out / f"pred_{name}_ep{ep:03d}.npy", pred)
            err = np.abs(pred - gt[ep])
            per_ep[ep] = err.mean(0).tolist()
            print(f"  ep{ep:03d} MAE per joint: {np.round(err.mean(0), 2).tolist()}", flush=True)
        all_err = np.concatenate([np.abs(np.load(out / f"pred_{name}_ep{ep:03d}.npy") - gt[ep]) for ep in episodes])
        results[name] = {
            "path": path,
            "mae_per_joint": dict(zip(JOINTS, np.round(all_err.mean(0), 3).tolist())),
            "mae_mean": round(float(all_err.mean()), 3),
            "per_episode": per_ep,
        }
        del policy
        torch.cuda.empty_cache()

    for ep in episodes:
        np.save(out / f"gt_ep{ep:03d}.npy", gt[ep])
    meta = {"chunk": args.chunk, "episodes": episodes, "task_override": args.task_override, "units": "lerobot range (-100..100, gripper 0..100)",
            "results": results}
    (out / "metrics.json").write_text(json.dumps(meta, indent=2))
    print("\nMAE (lerobot units; body joints ~1.8 deg per unit)")
    print(f"{'model':>6} " + " ".join(f"{j[:11]:>11}" for j in JOINTS) + "        mean")
    for name, r in results.items():
        print(f"{name:>6} " + " ".join(f"{r['mae_per_joint'][j]:11.2f}" for j in JOINTS) + f"  {r['mae_mean']:10.2f}")


if __name__ == "__main__":
    main()
