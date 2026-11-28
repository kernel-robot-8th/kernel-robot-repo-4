"""Run a small explicit-pose contact-latch calibration sweep.

This script calls the v024 diagnostic for each gripper-zero and vertical-shift
pair, then ranks candidates by bilateral contact, penetration, and lift. It is
not RL and it does not claim a hardware calibration.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V024 = ROOT / "versions/v024/code/contact_latch_explicit.py"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, default=ROOT / ".local/robot_facing_hinge_v022/scene.xml")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--gripper-zero", type=float, nargs="+", default=[46.4, 46.8, 47.2])
    p.add_argument("--shift-z", type=float, nargs="+", default=[-0.002, -0.004, -0.006])
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"output already exists: {a.out}")
    a.out.mkdir(parents=True)
    trials: list[dict] = []
    for zero in a.gripper_zero:
        for shift in a.shift_z:
            name = f"zero_{zero:.1f}_z_{abs(shift):.3f}".replace(".", "p")
            trial_dir = a.out / name
            cmd = [
                sys.executable, str(V024),
                "--scene", str(a.scene),
                "--seconds", str(a.seconds),
                "--gripper-zero", str(zero),
                "--shift-z", str(shift),
                "--out", str(trial_dir),
            ]
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
            summary = json.loads((trial_dir / "summary.json").read_text())
            for shoe in ("shoe0", "shoe1"):
                trials.append({
                    "trial": name,
                    "gripper_zero": float(zero),
                    "shift_z_m": float(shift),
                    "shoe": shoe,
                    "latched": bool(summary["latched"][shoe]),
                    "bilateral_steps": int(summary["bilateral_contact_steps"][shoe]),
                    "penetration_m": float(summary["max_finger_shoe_penetration_m"][shoe]),
                    "lift_m": float(summary["peak_shoe_lift_m"][shoe]),
                    "candidate": bool(summary["contact_latch_candidate"][shoe]),
                })
            print(completed.stdout.splitlines()[-1], flush=True)
    ranked = sorted(trials, key=lambda x: (not x["candidate"], -x["lift_m"], x["penetration_m"]))
    report = {
        "status": "CONTACT_SWEEP_COMPLETE",
        "scene": str(a.scene),
        "trials": trials,
        "best_by_lift": ranked[:6],
        "candidate_count": sum(int(x["candidate"]) for x in trials),
        "criteria": {"penetration_le_m": 0.001, "lift_ge_m": 0.03, "bilateral_required": True},
        "warning": "Simulation-only sweep; shift and gripper zero remain uncalibrated and no sim-to-real claim is made.",
    }
    (a.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "candidate_count": report["candidate_count"], "best_by_lift": report["best_by_lift"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
