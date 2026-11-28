"""Evaluate a v026 residual policy with physical grasp criteria."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mujoco_grasp_env import ResidualGraspEnv


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scene", type=Path, default=Path(".local/grasp_proxy_v026/scene.xml"))
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--shoe", choices=["shoe0", "shoe1", "both"], default="shoe1")
    p.add_argument("--attachment-mode", choices=["physical", "welded_proxy"], default="physical")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    knots = np.load(a.policy)
    env = ResidualGraspEnv(a.scene, shoe=a.shoe, attachment_mode=a.attachment_mode)
    successes = 0; proxy = 0; episodes = []
    for ep in range(a.episodes):
        env.reset(seed=ep)
        total = 0.0; info = {}
        for k in range(env.n_steps):
            idx = min(int(k * len(knots) / env.n_steps), len(knots) - 1)
            _, r, done, info = env.step(knots[idx])
            total += r
            if done: break
        successes += int(info.get("success", False)); proxy += int(info.get("proxy_success", False))
        episodes.append({"episode": ep, "return": total, **info})
    report = {"status": "EVALUATION_COMPLETE", "episodes": a.episodes, "successes": successes, "success_rate": successes / max(a.episodes, 1), "proxy_successes": proxy, "attachment_mode": a.attachment_mode, "episodes_detail": episodes, "warning": "A physical success is only valid when attachment_mode=physical; welded_proxy is labelled separately."}
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

