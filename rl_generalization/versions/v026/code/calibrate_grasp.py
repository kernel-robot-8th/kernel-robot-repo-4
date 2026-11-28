"""Grid-search physical contact parameters before residual training."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mujoco_grasp_env import ResidualGraspEnv


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scene", type=Path, default=Path(".local/grasp_proxy_v026/scene.xml"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--gripper-zero", type=float, nargs="+", default=[45.5, 46.0, 46.5, 47.0, 47.5, 48.0])
    p.add_argument("--shift-z", type=float, nargs="+", default=[-0.002, -0.003, -0.004, -0.005, -0.006])
    p.add_argument("--shoe", choices=["shoe0", "shoe1", "both"], default="shoe1")
    a = p.parse_args()
    if a.out.exists(): raise SystemExit(f"output exists: {a.out}")
    rows = []
    for zero in a.gripper_zero:
        for z in a.shift_z:
            env = ResidualGraspEnv(a.scene, shoe=a.shoe, gripper_zero=zero, shift=np.array([0.0349720067, -0.0034275971, z]))
            env.reset()
            for _ in range(env.n_steps):
                _, _, done, _ = env.step(np.zeros(6))
                if done: break
            rows.append({"gripper_zero": zero, "shift_z_m": z, **env.summary()})
    rows.sort(key=lambda x: (not x["success"], -max(x["peak_shoe_lift_m"].values()), max(x["max_finger_shoe_penetration_m"].values())))
    report = {"status": "PHYSICAL_CALIBRATION_SWEEP_COMPLETE", "scene": str(a.scene), "trials": rows, "best": rows[:10], "criteria": {"penetration_le_m": 0.001, "lift_ge_m": 0.03, "bilateral_required": True}, "warning": "No parameter set is accepted as hardware calibration without a real contact/current check."}
    a.out.mkdir(parents=True)
    (a.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "best": report["best"]}, indent=2))


if __name__ == "__main__": main()

