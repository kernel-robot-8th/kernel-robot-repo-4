"""Replay a recorded arm path with contact-triggered gripper latching.

This is a simulation diagnostic. Once both thin finger proxies touch the same
shoe, the gripper target is latched at its current joint position plus a small
opening backoff. v024 resets from the explicit shoebox_D LeRobot median pose
provided by the user instead of the first parquet observation. It does not add
a rigid weld and does not claim hardware grasp success.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import mujoco
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "versions/v018/code"))
from retarget import plan  # noqa: E402

ARRANGE_INIT = np.array([-12.97, -17.31, -0.85, 43.59, -0.85, 59.68], dtype=float)


def arm(values: list[float] | np.ndarray) -> np.ndarray:
    return ((np.asarray(values, dtype=float) + 100.0) / 200.0 * 4095.0 - 2048.0) * 2.0 * np.pi / 4096.0


def grip(value: float, zero: float) -> float:
    return (float(value) - zero) / 100.0 * 4095.0 * 2.0 * np.pi / 4096.0


def shoe_contacts(model: mujoco.MjModel, data: mujoco.MjData, shoe_name: str) -> tuple[set[str], list[float]]:
    finger_names = {"finger6_proxy_v019", "finger7_proxy_v019", "finger6_proxy", "finger7_proxy"}
    shoe_id = model.body(shoe_name).id
    touched: set[str] = set()
    distances: list[float] = []
    for contact in data.contact:
        geom_names = [model.geom(int(g)).name for g in contact.geom]
        bodies = [int(model.geom_bodyid[int(g)]) for g in contact.geom]
        if shoe_id not in bodies:
            continue
        local_fingers = {name for name in geom_names if name in finger_names}
        touched.update(local_fingers)
        if local_fingers and any(name.startswith(shoe_name + "_") for name in geom_names):
            distances.append(float(contact.dist))
    return touched, distances


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--gripper-zero", type=float, default=46.8)
    parser.add_argument("--open-backoff-rad", type=float, default=0.005)
    parser.add_argument("--shift-x", type=float, default=0.0349720067)
    parser.add_argument("--shift-y", type=float, default=-0.0034275971)
    parser.add_argument("--shift-z", type=float, default=-0.018)
    parser.add_argument("--initial-pose", type=float, nargs=6, default=ARRANGE_INIT.tolist(), metavar=("PAN", "LIFT", "ELBOW", "WRIST", "ROLL", "GRIP"))
    args = parser.parse_args()
    if not 0 < args.seconds <= 45:
        parser.error("--seconds must be in (0,45]")
    if args.out.exists():
        raise FileExistsError(args.out)

    dataset = ROOT / ".local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet"
    rows = pq.read_table(dataset).to_pylist()
    rows.sort(key=lambda row: row["frame_index"])
    model = mujoco.MjModel.from_xml_path(str(args.scene))
    data = mujoco.MjData(model)
    probe = mujoco.MjData(model)
    rows, plan_report = plan(model, rows, args.seconds, np.array([args.shift_x, args.shift_y, args.shift_z]))

    initial_pose = np.asarray(args.initial_pose, dtype=float)
    data.qpos[:5] = arm(initial_pose[:5])
    initial_grip = grip(initial_pose[5], args.gripper_zero)
    data.qpos[5:7] = [initial_grip, -initial_grip]
    data.ctrl[:5] = data.qpos[:5]
    data.ctrl[5] = initial_grip
    mujoco.mj_forward(model, data)

    shoes = ["shoe0", "shoe1"]
    z0 = {name: float(data.xpos[model.body(name).id, 2]) for name in shoes}
    latched: dict[str, bool] = {name: False for name in shoes}
    hold_target: dict[str, float | None] = {name: None for name in shoes}
    contact_first: dict[str, float | None] = {name: None for name in shoes}
    max_penetration: dict[str, float] = {name: 0.0 for name in shoes}
    max_lift: dict[str, float] = {name: 0.0 for name in shoes}
    bilateral_steps: dict[str, int] = {name: 0 for name in shoes}
    arm_hold_q: np.ndarray | None = None
    arm_hold_tcp_z: float | None = None
    arm_hold_release_margin = 0.008
    diagnostics: list[dict[str, float | str | None]] = []
    trajectory: list[list[float]] = []
    reason = "DURATION_COMPLETE"
    fingers = {"finger6_proxy_v019", "finger7_proxy_v019", "finger6_proxy", "finger7_proxy"}

    for step in range(int(args.seconds / model.opt.timestep)):
        row = rows[min(int(data.time * 30.0), len(rows) - 1)]
        q_command = arm(row["action"][:5])
        # The recorded path dips a few millimetres after first contact.  Hold
        # the contact pose until the planned path has clearly risen; otherwise
        # the arm itself drives the fingers through the shoe even if the
        # gripper target is latched.
        q = q_command
        if arm_hold_q is not None:
            body = model.body("link5").id
            probe.qpos[:5] = q_command
            mujoco.mj_forward(model, probe)
            tcp_z_planned = float(probe.xpos[body, 2] + probe.xmat[body].reshape(3, 3)[2, :] @ np.array([0.09193, -0.0016, 0.0]))
            if arm_hold_tcp_z is None or tcp_z_planned < arm_hold_tcp_z + arm_hold_release_margin:
                q = arm_hold_q
            else:
                arm_hold_q = None
                arm_hold_tcp_z = None
        data.ctrl[:5] = q
        for name in shoes:
            touched, _ = shoe_contacts(model, data, name)
            if len(touched & fingers) >= 2:
                bilateral_steps[name] += 1
        # Use the recorded close target until contact.  Afterwards retain the
        # current joint position with a tiny opening backoff.
        pending = [name for name in shoes if not latched[name] and bilateral_steps[name] > 0]
        if pending:
            name = pending[0]
            latched[name] = True
            contact_first[name] = float(data.time)
            hold_target[name] = float(data.qpos[5] + args.open_backoff_rad)
            # Emergency-stop the closing velocity at contact.  This is the
            # simulator equivalent of switching from a position close command
            # to a low-speed force/hold controller; without it the position
            # actuator's stored momentum drives several millimetres through
            # the thin proxy before the new target can take effect.
            data.qvel[5:7] = 0.0
            arm_hold_q = q.copy()
            body = model.body("link5").id
            arm_hold_tcp_z = float(data.xpos[body, 2] + data.xmat[body].reshape(3, 3)[2, :] @ np.array([0.09193, -0.0016, 0.0]))
        active_targets = [x for x in hold_target.values() if x is not None]
        data.ctrl[5] = float(active_targets[0]) if active_targets else grip(row["action"][5], args.gripper_zero)
        mujoco.mj_step(model, data)
        if not np.isfinite(data.qpos).all() or data.warning.number.sum():
            reason = "STOPPED_NUMERICS"
            break

        for name in shoes:
            touched, distances = shoe_contacts(model, data, name)
            finger_touched = touched & fingers
            if len(finger_touched) >= 2:
                bilateral_steps[name] += 1
            if distances:
                max_penetration[name] = max(max_penetration[name], max(0.0, -min(distances)))
            z = float(data.xpos[model.body(name).id, 2])
            max_lift[name] = max(max_lift[name], z - z0[name])
        if step % 15 == 0:
            trajectory.append([float(data.time), *data.qpos[:7], *[float(data.xpos[model.body(s).id, 2]) for s in shoes]])
        diagnostics.append({
            "time_s": float(data.time),
            "gripper_target_rad": float(data.ctrl[5]),
            "gripper_qpos_rad": float(data.qpos[5]),
            "shoe0_latched": str(latched["shoe0"]),
            "shoe1_latched": str(latched["shoe1"]),
            "shoe0_z_m": float(data.xpos[model.body("shoe0").id, 2]),
            "shoe1_z_m": float(data.xpos[model.body("shoe1").id, 2]),
        })

    args.out.mkdir(parents=True)
    np.savetxt(args.out / "trajectory.csv", trajectory, delimiter=",", header="time,q1,q2,q3,q4,q5,grip,mimic,shoe0_z,shoe1_z", comments="")
    with (args.out / "diagnostics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=diagnostics[0].keys())
        writer.writeheader()
        writer.writerows(diagnostics)
    summary = {
        "status": reason,
        "scene": str(args.scene),
        "plan": plan_report,
        "simulated_seconds": float(data.time),
        "initial_pose_le_robot": initial_pose.tolist(),
        "initial_pose_source": "explicit shoebox_D median supplied by user",
        "gripper_mapping": "UNCALIBRATED_CANDIDATE",
        "open_backoff_rad": args.open_backoff_rad,
        "latched": latched,
        "contact_first_s": contact_first,
        "hold_target_rad": hold_target,
        "bilateral_contact_steps": bilateral_steps,
        "max_finger_shoe_penetration_m": max_penetration,
        "peak_shoe_lift_m": max_lift,
        "criterion_penetration_le_1mm": {name: value <= 0.001 for name, value in max_penetration.items()},
        "measurement_tolerance_assumed_m": 0.0002,
        "criterion_penetration_le_0_3mm": {name: value <= 0.0003 for name, value in max_penetration.items()},
        "criterion_lift_ge_30mm": {name: value >= 0.03 for name, value in max_lift.items()},
        "contact_latch_candidate": {name: bool(latched[name] and max_penetration[name] <= 0.001 and max_lift[name] >= 0.03) for name in shoes},
        "warning_count": int(data.warning.number.sum()),
        "limitation": "Simulation-only contact latch; no calibrated gripper angle or sim-to-real claim.",
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
