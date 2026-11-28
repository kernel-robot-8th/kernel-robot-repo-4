"""Replay the recorded OMX arm command into the v020 workcell scene.

This is the first arm-connected diagnostic for v021.  It drives the five arm
actuators and gripper actuator from episode-0 telemetry, with the measured
robot-facing lid angle set at reset.  Contact and lift are reported, but this
script never declares a grasp unless the calibrated gripper/contact contract
is supplied.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]


def arm(values: object) -> np.ndarray:
    return ((np.asarray(values, dtype=float) + 100.0) / 200.0 * 4095.0 - 2048.0) * 2.0 * np.pi / 4096.0


def grip(value: float, zero: float) -> float:
    return (float(value) - zero) / 100.0 * 4095.0 * 2.0 * np.pi / 4096.0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, default=ROOT / ".local/robot_facing_hinge_v020/scene.xml")
    p.add_argument("--episode", type=int, default=0)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--initial-angle", type=float, default=-2.70)
    p.add_argument("--gripper-zero", type=float, default=46.8)
    p.add_argument("--shift-x", type=float, default=0.0349720067)
    p.add_argument("--shift-y", type=float, default=-0.0034275971)
    p.add_argument("--shift-z", type=float, default=-0.006)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if not 0 < a.seconds <= 45:
        p.error("--seconds must be in (0,45]")

    from retarget import plan

    rows = []
    for path in sorted((ROOT / ".local/demonstrations/shoebox_D/data").rglob("*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    rows = [r for r in rows if int(r["episode_index"]) == a.episode]
    rows.sort(key=lambda r: r["frame_index"])
    if not rows:
        raise SystemExit(f"episode not found: {a.episode}")

    scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    rows, plan_report = plan(model, rows, a.seconds, np.array([a.shift_x, a.shift_y, a.shift_z]))
    hinge = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "lid_hinge")
    data.qpos[model.jnt_qposadr[hinge]] = a.initial_angle
    first = rows[0]
    data.qpos[:5] = arm(first["action"][:5])
    g0 = grip(first["action"][5], a.gripper_zero)
    data.qpos[5:7] = [g0, -g0]
    data.ctrl[:5] = data.qpos[:5]
    data.ctrl[5] = g0
    mujoco.mj_forward(model, data)

    shoes = [model.body(f"shoe{i}").id for i in range(2)]
    z0 = data.xpos[shoes, 2].copy()
    peak_lift = np.zeros(2)
    contact_steps = np.zeros(2, dtype=int)
    bilateral_steps = np.zeros(2, dtype=int)
    max_penetration = 0.0
    max_pair = None
    finite = True
    for step in range(int(a.seconds / model.opt.timestep)):
        idx = min(int(data.time * 30.0), len(rows) - 1)
        row = rows[idx]
        q = arm(row["action"][:5])
        g = grip(row["action"][5], a.gripper_zero)
        data.ctrl[:5] = q
        data.ctrl[5] = g
        mujoco.mj_step(model, data)
        finite = finite and bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
        touches = [set(), set()]
        for c in data.contact:
            names = [model.geom(int(x)).name for x in c.geom]
            bodies = [int(model.geom_bodyid[int(x)]) for x in c.geom]
            for i, bid in enumerate(shoes):
                if bid in bodies:
                    for name in names:
                        if name.startswith("finger") or name in {"link6", "link7"}:
                            touches[i].add(name)
                    pen = max(0.0, -float(c.dist))
                    if pen > max_penetration:
                        max_penetration = pen
                        max_pair = {"time_s": float(data.time), "geom_names": names, "dist_m": float(c.dist)}
        for i in range(2):
            peak_lift[i] = max(peak_lift[i], float(data.xpos[shoes[i], 2] - z0[i]))
            contact_steps[i] += int(bool(touches[i]))
            bilateral_steps[i] += int(len(touches[i]) >= 2)

    result = {
        "status": "ARM_REPLAY_FINITE_CONTACT_DIAGNOSTIC",
        "scene": str(scene),
        "episode": a.episode,
        "seconds": a.seconds,
        "initial_angle_rad": a.initial_angle,
        "shift_m": [a.shift_x, a.shift_y, a.shift_z],
        "plan": plan_report,
        "finite": finite,
        "peak_shoe_lift_m": peak_lift.tolist(),
        "contact_steps": contact_steps.tolist(),
        "bilateral_contact_steps": bilateral_steps.tolist(),
        "max_finger_shoe_penetration_m": float(max_penetration),
        "max_finger_pair": max_pair,
        "grasp_success": False,
        "grasp_status": "NOT_VALIDATED_CALIBRATION_AND_ATTACHMENT",
        "warning": "Arm and gripper actuators were replayed, but gripper zero, finger geometry, compliance, and attachment/lift criteria are not calibrated; finite/contact output is not a successful grasp.",
    }
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
