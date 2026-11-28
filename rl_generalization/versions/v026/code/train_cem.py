"""Train bounded residuals around shoebox_D using a MuJoCo CEM policy search."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mujoco_grasp_env import ResidualGraspEnv


def run(env: ResidualGraspEnv, params: np.ndarray, horizon: int) -> tuple[float, dict]:
    env.reset()
    total = 0.0
    last: dict = {}
    for k in range(horizon):
        u = params[min(k, len(params) - 1)]
        _, r, done, last = env.step(u)
        total += r
        if done:
            break
    return total, last


def rank(score: float, info: dict) -> tuple[float, ...]:
    """Prefer task milestones over dense reward accumulated during contact.

    Penetration is intentionally a hard tie-breaker.  Otherwise a no-contact
    rollout can win simply because it avoided the per-step contact penalty.
    """
    bilateral = float(sum(info.get("bilateral_contact_steps", {}).values()))
    lift = float(max(info.get("peak_shoe_lift_m", {"_": 0.0}).values()))
    penetration = float(max(info.get("max_finger_shoe_penetration_m", {"_": 0.0}).values()))
    return (
        float(bool(info.get("proxy_success", False))),
        float(bool(info.get("success", False))),
        float(lift >= 0.03),
        bilateral,
        lift,
        -penetration,
        float(score),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scene", type=Path, default=Path(".local/grasp_proxy_v026/scene.xml"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--population", type=int, default=24)
    p.add_argument("--elite", type=int, default=6)
    # The recorded shoe contact happens around 7.5 s (about 225 decisions).
    # A 90-step default ended before contact, so it could never learn a grasp.
    p.add_argument("--horizon", type=int, default=360)
    p.add_argument("--shoe", choices=["shoe0", "shoe1", "both"], default="shoe1")
    p.add_argument("--attachment-mode", choices=["physical", "welded_proxy"], default="physical")
    p.add_argument("--gripper-zero", type=float, default=46.8)
    p.add_argument("--shift-z", type=float, default=-0.004)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"output exists: {a.out}")
    rng = np.random.default_rng(a.seed)
    env = ResidualGraspEnv(
        a.scene,
        shoe=a.shoe,
        attachment_mode=a.attachment_mode,
        gripper_zero=a.gripper_zero,
        shift=np.array([0.0349720067, -0.0034275971, a.shift_z]),
    )
    # Piecewise-constant residuals.  The nominal trajectory still drives every
    # arm joint; CEM learns only corrections, so this is residual RL rather
    # than an unconstrained policy that can leave the measured workspace.
    knots = max(3, a.horizon // 15)
    mean = np.zeros((knots, 6), dtype=float)
    std = np.full_like(mean, 0.35)
    history: list[dict] = []
    best_params = mean.copy(); best_score = -np.inf; best_info = {}
    for it in range(a.iterations):
        samples = np.clip(rng.normal(mean, std, size=(a.population, knots, 6)), -1.0, 1.0)
        # Always score the measured demonstration with zero residual.  This
        # prevents CEM from discarding the only known approach trajectory and
        # makes a successful nominal/proxy rollout reproducible.
        samples[0] = 0.0
        scored = []
        for x in samples:
            # interpolate each knot to one policy action per decision.
            policy = np.array([x[min(int(k * knots / a.horizon), knots - 1)] for k in range(a.horizon)])
            score, info = run(env, policy, a.horizon)
            scored.append((score, x, info, rank(score, info)))
        scored.sort(key=lambda z: z[3], reverse=True)
        elite = scored[: max(1, min(a.elite, len(scored)))]
        mean = np.mean([z[1] for z in elite], axis=0)
        std = np.maximum(0.06, 0.85 * np.std([z[1] for z in elite], axis=0))
        if rank(elite[0][0], elite[0][2]) > rank(best_score, best_info or {}):
            best_score, best_params, best_info = elite[0][0], elite[0][1].copy(), elite[0][2]
        rec = {"iteration": it + 1, "best_score": float(elite[0][0]), "best_rank": list(elite[0][3]), "population": a.population, "best": elite[0][2]}
        history.append(rec)
        print(json.dumps(rec), flush=True)
    a.out.mkdir(parents=True)
    np.save(a.out / "policy_knots.npy", best_params)
    report = {
        "status": "CEM_RESIDUAL_TRAIN_COMPLETE",
        "scene": str(a.scene),
        "policy": str(a.out / "policy_knots.npy"),
        "shoe": a.shoe,
        "attachment_mode": a.attachment_mode,
        "seed": a.seed,
        "iterations": a.iterations,
        "population": a.population,
        "horizon": a.horizon,
        "gripper_zero": a.gripper_zero,
        "shift_z_m": a.shift_z,
        "best_score": float(best_score),
        "best_rollout": best_info,
        "history": history,
        "warning": "MuJoCo-only. physical mode requires free-body lift; welded_proxy is curriculum evidence and is not a sim-to-real claim.",
    }
    (a.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "best_score": report["best_score"], "best_rollout": report["best_rollout"]}, indent=2))


if __name__ == "__main__":
    main()

