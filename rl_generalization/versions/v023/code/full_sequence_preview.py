"""Replay the two OMX demonstrations through the complete workcell sequence.

This is a visual and geometric verification tool for v023.  It uses the
explicit LeRobot median poses supplied for the two demonstrations rather than
the first row of either parquet file:

* shoebox_D: open lid, pick/insert two shoes, close lid, lift and carry;
* move_in_success: reset to its own start pose and carry the closed box to the
  stationary robot's circular tray.

The shoe insertion and box carry are deliberately kinematic proxies until the
gripper zero, compliance, contact and paper-box attachment are calibrated.
The report therefore distinguishes arm-command replay from validated physical
grasp success.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "versions/v018/code"))
from retarget import plan  # noqa: E402

ARRANGE_INIT = np.array([-12.97, -17.31, -0.85, 43.59, -0.85, 59.68], dtype=float)
MOVE_IN_INIT = np.array([2.22, -34.99, 14.68, 40.37, 1.0, 58.93], dtype=float)
POSE_KEYS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def read_arrange_pose(path: Path) -> tuple[np.ndarray, str]:
    """Read the user's init_pose.json, with an explicit-value fallback.

    The detached GPU checkout may not have the private ``~/il_ws`` tree.  In
    that case the values supplied by the user are retained and the report
    records that the fallback was used instead of silently taking a parquet
    first row.
    """
    if path.exists():
        try:
            obj = json.loads(path.read_text())
            if isinstance(obj, dict):
                for candidate in (obj, obj.get("pose"), obj.get("state"), obj.get("observation")):
                    if isinstance(candidate, dict) and all(k in candidate for k in POSE_KEYS):
                        return np.array([float(candidate[k]) for k in POSE_KEYS], dtype=float), str(path)
        except (OSError, ValueError, TypeError):
            pass
    return ARRANGE_INIT.copy(), "user-supplied fallback (init_pose.json unavailable or unrecognized)"


def arm(values: object) -> np.ndarray:
    """Map the five LeRobot body values to the MuJoCo OMX joint radians."""
    return ((np.asarray(values, dtype=float) + 100.0) / 200.0 * 4095.0 - 2048.0) * 2.0 * np.pi / 4096.0


def grip(value: float, zero: float) -> float:
    """Map the normalized LeRobot gripper value to the candidate actuator radian."""
    return (float(value) - zero) / 100.0 * 4095.0 * 2.0 * np.pi / 4096.0


def free_qadr(model: mujoco.MjModel, body_name: str) -> int:
    bid = model.body(body_name).id
    for jid in range(model.njnt):
        if int(model.jnt_bodyid[jid]) == bid and int(model.jnt_type[jid]) == int(mujoco.mjtJoint.mjJNT_FREE):
            return int(model.jnt_qposadr[jid])
    raise ValueError(f"body has no free joint: {body_name}")


def body_pos(model: mujoco.MjModel, data: mujoco.MjData, body_name: str) -> np.ndarray:
    return np.array(data.xpos[model.body(body_name).id], dtype=float, copy=True)


def set_free(model: mujoco.MjModel, data: mujoco.MjData, body_name: str, xyz: np.ndarray) -> None:
    q = free_qadr(model, body_name)
    data.qpos[q : q + 3] = np.asarray(xyz, dtype=float)
    data.qpos[q + 3 : q + 7] = [1.0, 0.0, 0.0, 0.0]
    data.qvel[q : q + 6] = 0.0


def set_arm(model: mujoco.MjModel, data: mujoco.MjData, values: np.ndarray, gripper_zero: float) -> None:
    q = arm(values[:5])
    g = grip(float(values[5]), gripper_zero)
    data.qpos[:5] = q
    data.qpos[5:7] = [g, -g]
    data.ctrl[:5] = q
    data.ctrl[5] = g


def load_rows(dataset: Path, episode: int, seconds: float, shift: np.ndarray) -> tuple[list[dict], dict]:
    rows = pq.read_table(dataset).to_pylist()
    rows = [r for r in rows if int(r["episode_index"]) == episode]
    rows.sort(key=lambda r: r["frame_index"])
    if not rows:
        raise ValueError(f"episode {episode} not found in {dataset}")
    model_probe = mujoco.MjModel.from_xml_path(str(ROOT / ".local/robot_facing_hinge_v022/scene.xml"))
    return plan(model_probe, rows, seconds, shift)


def stage(name: str, status: str, reason: str, data: mujoco.MjData, **extra: object) -> dict:
    out = {"stage": name, "status": status, "reason": reason, "sim_time_s": float(data.time)}
    out.update(extra)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, default=ROOT / ".local/robot_facing_hinge_v022/scene.xml")
    p.add_argument("--arrange-data", type=Path, default=ROOT / ".local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet")
    p.add_argument("--move-in-data", type=Path, default=ROOT / ".local/demonstrations/move_in_success/data/chunk-000/file-000.parquet")
    p.add_argument("--arrange-init-json", type=Path, default=Path.home() / "il_ws/omx_shoebox_d/init_pose.json")
    p.add_argument("--episode", type=int, default=0)
    p.add_argument("--initial-angle", type=float, default=-2.70)
    p.add_argument("--gripper-zero", type=float, default=46.8)
    p.add_argument("--shift-x", type=float, default=0.0349720067)
    p.add_argument("--shift-y", type=float, default=-0.0034275971)
    p.add_argument("--shift-z", type=float, default=-0.004)
    p.add_argument("--view", action="store_true")
    p.add_argument("--speed", type=float, default=0.5)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"output already exists: {a.out}")
    if not (-math.pi < a.initial_angle < 0.0):
        p.error("--initial-angle must be in (-pi,0)")

    scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    arrange_init, arrange_init_source = read_arrange_pose(a.arrange_init_json)
    # Free bodies are placed by the scripted sequence; disabling gravity keeps
    # them from falling between kinematic stage updates during visual review.
    model.opt.gravity[:] = [0.0, 0.0, 0.0]
    hinge = model.joint("lid_hinge").id
    hinge_q = int(model.jnt_qposadr[hinge])
    data.qpos[:] = model.qpos0
    data.qvel[:] = 0.0
    data.qpos[hinge_q] = a.initial_angle
    set_arm(model, data, arrange_init, a.gripper_zero)
    mujoco.mj_forward(model, data)

    arrange_rows, arrange_plan = load_rows(a.arrange_data, a.episode, 45.0, np.array([a.shift_x, a.shift_y, a.shift_z]))
    move_rows, move_plan = load_rows(a.move_in_data, a.episode, 24.3, np.array([a.shift_x, a.shift_y, a.shift_z]))
    records: list[dict] = []
    viewer = None
    if a.view:
        viewer = mujoco.viewer.launch_passive(model, data)
        viewer.cam.lookat[:] = [0.12, -0.08, 0.16]
        viewer.cam.distance = 0.72
        viewer.cam.azimuth = 135
        viewer.cam.elevation = -28

    wall_start = time.monotonic()

    def sync() -> None:
        if viewer is not None:
            if not viewer.is_running():
                raise RuntimeError("viewer closed")
            viewer.sync()
            time.sleep(max(0.0, 0.01 / a.speed))

    def record(name: str, status: str, reason: str, **extra: object) -> None:
        records.append(stage(name, status, reason, data, **extra))

    def run_commands(rows: list[dict], duration_s: float, offset_s: float = 0.0) -> None:
        """Replay a segment at the recorded 30 Hz rate while rendering."""
        steps = max(1, int(round(duration_s / model.opt.timestep)))
        for step in range(steps):
            t = offset_s + step * model.opt.timestep
            idx = min(int(t * 30.0), len(rows) - 1)
            cmd = np.asarray(rows[idx]["action"], dtype=float)
            data.ctrl[:5] = arm(cmd[:5])
            data.ctrl[5] = grip(cmd[5], a.gripper_zero)
            mujoco.mj_step(model, data)
            sync()

    # Initial state: explicitly the supplied shoebox_D median pose.
    record("OPEN_INITIAL", "PASS_GEOMETRY_ONLY", "shoebox_D explicit LeRobot median start; lid faces OMX", hinge_angle_rad=float(data.qpos[hinge_q]), le_robot_pose=arrange_init.tolist(), pose_source=arrange_init_source)
    run_commands([{"action": arrange_init.tolist()}], 2.0)

    box0 = body_pos(model, data, "paper_box")
    # The two shoe placements preserve the measured 6x6 cm box interior.
    shoe_targets = [box0 + np.array([-0.010, -0.012, 0.004]), box0 + np.array([0.010, 0.012, 0.004])]
    for i, target in enumerate(shoe_targets):
        record(f"PICK_SHOE{i}", "NOT_VALIDATED_ARM_GRASP", "arm command replay is present; contact/force attachment is not calibrated", arm_source="shoebox_D", initial_pose_source="shoebox_D/init_pose.json")
        offset = 0.0 if i == 0 else 12.0
        run_commands(arrange_rows, 12.0, offset)
        set_free(model, data, f"shoe{i}", target)
        mujoco.mj_forward(model, data)
        rel = body_pos(model, data, f"shoe{i}") - body_pos(model, data, "paper_box")
        inside = bool(abs(rel[0]) <= 0.021 and abs(rel[1]) <= 0.021 and 0.0 <= rel[2] <= 0.055)
        record(f"INSERT_SHOE{i}", "PASS_GEOMETRY_ONLY" if inside else "FAIL", "kinematic placement for box-fit verification; physical shoe grasp not claimed", relative_to_box_m=rel.tolist(), inside_box=inside)
        sync()

    # Close the lid after the gripper is explicitly driven fully closed.
    closed_value = 0.0
    # Keep the arm at the last shoebox_D command; only the gripper is forced
    # to its fully-closed normalized value before the lid motion begins.
    closed_rad = grip(closed_value, a.gripper_zero)
    data.qpos[5:7] = [closed_rad, -closed_rad]
    data.ctrl[5] = closed_rad
    for _ in range(max(1, int(1.0 / model.opt.timestep))):
        data.ctrl[5] = closed_rad
        mujoco.mj_step(model, data); sync()
    record("GRIPPER_FULLY_CLOSED_BEFORE_LID", "PASS_COMMAND_ONLY", "gripper command set to normalized 0 before lid motion", gripper_normalized=closed_value, gripper_ctrl_rad=float(data.ctrl[5]))
    for k in range(max(1, int(5.0 / model.opt.timestep))):
        data.qpos[hinge_q] = a.initial_angle * (1.0 - (k + 1) / max(1, int(5.0 / model.opt.timestep)))
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data); sync()
    record("CLOSE_LID", "PASS_GEOMETRY_ONLY", "lid interpolated from robot-facing open angle to closed limit", hinge_angle_rad=float(data.qpos[hinge_q]), gripper_closed=True)

    # Reset at the second demonstration's explicit move_in start pose.
    set_arm(model, data, MOVE_IN_INIT, a.gripper_zero)
    mujoco.mj_forward(model, data)
    record("MOVE_IN_RESET", "PASS_POSE_SET", "move_in_success explicit LeRobot start pose", le_robot_pose=MOVE_IN_INIT.tolist())
    run_commands(move_rows, 6.0)

    # Closed box is attached as one kinematic payload and carried to the
    # circular tray floor (z=14 cm), matching the supplied workcell photo.
    box_before = body_pos(model, data, "paper_box")
    tray_target = np.array([0.08, -0.2325, 0.141], dtype=float)
    lift = np.array([0.0, 0.0, 0.050])
    for n in ["paper_box", "shoe0", "shoe1"]:
        set_free(model, data, n, body_pos(model, data, n) + lift)
    mujoco.mj_forward(model, data)
    record("LIFT_CLOSED_BOX", "PASS_KINEMATIC_ONLY", "closed paper box and contents attached as payload; arm grasp not validated", box_xyz_m=body_pos(model, data, "paper_box").tolist(), lift_m=float(lift[2]))
    sync()
    payload_start = {n: body_pos(model, data, n) for n in ["paper_box", "shoe0", "shoe1"]}
    start = payload_start["paper_box"]
    for k in range(120):
        alpha = (k + 1) / 120.0
        delta = start * 0.0 + (tray_target - start) * alpha
        for n in ["paper_box", "shoe0", "shoe1"]:
            # Preserve the shoes' offsets from the box while the closed payload
            # travels to the stationary circular tray.
            set_free(model, data, n, payload_start[n] + delta)
        mujoco.mj_forward(model, data); sync()
    # Correct any integration drift and verify the box center at the tray.
    final_box = body_pos(model, data, "paper_box")
    correction = tray_target - final_box
    for n in ["paper_box", "shoe0", "shoe1"]:
        set_free(model, data, n, body_pos(model, data, n) + correction)
    mujoco.mj_forward(model, data)
    final_box = body_pos(model, data, "paper_box")
    record("LOAD_RIGHT_TRAY", "PASS_KINEMATIC_ONLY" if np.linalg.norm(final_box[:2] - tray_target[:2]) < 1e-6 else "FAIL", "closed box placed on stationary logistics robot circular tray; robot base does not drive", box_xyz_m=final_box.tolist(), tray_target_xyz_m=tray_target.tolist(), xy_error_m=float(np.linalg.norm(final_box[:2] - tray_target[:2])))
    sync()
    if viewer is not None:
        viewer.close()

    report = {
        "status": "FULL_SEQUENCE_ARM_REPLAY_KINEMATIC_TRANSFER",
        "scene": str(scene),
        "stages": records,
        "initial_pose_sources": {
            "shoebox_D": {"path": str(a.arrange_init_json), "values": arrange_init.tolist(), "units": "LeRobot normalized", "source_used": arrange_init_source},
            "move_in_success": {"values": MOVE_IN_INIT.tolist(), "units": "LeRobot normalized"},
        },
        "arm_command_replay": {"arrange_rows": len(arrange_rows), "move_in_rows": len(move_rows), "arrange_plan": arrange_plan, "move_in_plan": move_plan},
        "lid_convention": {"closed_rad": 0.0, "vertical_rad": -math.pi / 2.0, "open_toward_omx_rad": float(a.initial_angle)},
        "gripper_close_before_lid": True,
        "transport_target": "right-side white circular tray (stationary logistics robot)",
        "physical_grasp_success": "NOT_VALIDATED",
        "limitation": "Kinematic shoe insertion and box attachment remain proxies; calibrated gripper, paper compliance, contact forces and sim-to-real must be validated before hardware execution.",
        "elapsed_wall_s": time.monotonic() - wall_start,
    }
    a.out.mkdir(parents=True)
    (a.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
