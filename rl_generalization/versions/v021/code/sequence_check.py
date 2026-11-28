"""Run a complete workcell sequence smoke check on the v020 hinge scene.

The script intentionally separates geometric/kinematic checks from robot
checks.  It places the two shoe bodies inside the box and transports the box
by updating the free-joint state.  This verifies the scene dimensions,
robot-facing hinge, close pose and tray fit without pretending that an arm
controller, gripper contact, or paper-box grasp has been validated.

Use ``--view`` for a short interactive preview.  The default run is headless
and writes a JSON report that is suitable for CI/evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCENE = ROOT / ".local/robot_facing_hinge_v020/scene.xml"


def qadr(model: mujoco.MjModel, joint_name: str) -> int:
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
    if jid < 0:
        raise ValueError(f"joint not found: {joint_name}")
    return int(model.jnt_qposadr[jid])


def body_qadr(model: mujoco.MjModel, body_name: str) -> int:
    """Return the free-joint qpos address for a body."""
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if bid < 0:
        raise ValueError(f"body not found: {body_name}")
    for jid in range(model.njnt):
        if int(model.jnt_bodyid[jid]) == bid and int(model.jnt_type[jid]) == int(mujoco.mjtJoint.mjJNT_FREE):
            return int(model.jnt_qposadr[jid])
    raise ValueError(f"body has no free joint: {body_name}")


def body_pos(model: mujoco.MjModel, data: mujoco.MjData, name: str) -> np.ndarray:
    return np.asarray(data.xpos[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)], dtype=float).copy()


def finite(model: mujoco.MjModel, data: mujoco.MjData) -> bool:
    return bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())


def stage_record(name: str, status: str, reason: str, data: mujoco.MjData, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "stage": name,
        "status": status,
        "reason": reason,
        "sim_time_s": float(data.time),
    }
    row.update(extra)
    return row


def set_free_pose(model: mujoco.MjModel, data: mujoco.MjData, name: str, xyz: np.ndarray) -> None:
    a = body_qadr(model, name)
    data.qpos[a : a + 3] = np.asarray(xyz, dtype=float)
    # Free-joint quaternion is x/y/z/w in MuJoCo qpos; identity is [1,0,0,0].
    data.qpos[a + 3 : a + 7] = [1.0, 0.0, 0.0, 0.0]


def move_free_with_contents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    names: list[str],
    delta: np.ndarray,
) -> None:
    for name in names:
        p = body_pos(model, data, name)
        set_free_pose(model, data, name, p + delta)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--initial-angle", type=float, default=-2.70, help="robot-facing open angle in rad; 0=closed, -pi=flat; provisional video fit")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--view", action="store_true", help="show each scripted stage in a passive MuJoCo viewer")
    parser.add_argument("--stage-seconds", type=float, default=0.5)
    args = parser.parse_args()
    if not (-math.pi < args.initial_angle < -0.05):
        parser.error("--initial-angle must be between -pi and 0 (open, not closed)")
    if args.out.exists():
        raise SystemExit(f"output already exists: {args.out}")
    scene = args.scene if args.scene.is_absolute() else ROOT / args.scene
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    model.opt.gravity[:] = [0.0, 0.0, -9.81]
    data.qpos[:] = model.qpos0
    data.qvel[:] = 0.0
    hinge_a = qadr(model, "lid_hinge")
    data.qpos[hinge_a] = float(args.initial_angle)
    mujoco.mj_forward(model, data)

    lid_geom = model.geom("lid_top").id
    box = body_pos(model, data, "paper_box")
    shoe_names = ["shoe0", "shoe1"]
    contents = shoe_names + ["paper_box"]
    box_center = box.copy()
    # User-provided scene tray floor is at z=0.139 m; the box bottom is 1 mm
    # above its free-body centre.  This target leaves the 6 cm box inside the
    # approximately 11.5 cm tray diameter while retaining a visible rim.
    tray_target = np.array([0.08, -0.2325, 0.141], dtype=float)
    records: list[dict[str, object]] = []

    viewer = None
    if args.view:
        from mujoco import viewer as mujoco_viewer

        viewer = mujoco_viewer.launch_passive(model, data)
        viewer.cam.lookat[:] = [0.14, -0.08, 0.18]
        viewer.cam.distance = 0.65
        viewer.cam.azimuth = 135
        viewer.cam.elevation = -28

    def sync() -> None:
        if viewer is not None:
            if not viewer.is_running():
                raise RuntimeError("viewer closed")
            viewer.sync()
            time.sleep(max(0.0, args.stage_seconds))

    def check_open() -> None:
        mujoco.mj_forward(model, data)
        top = data.geom_xpos[lid_geom].copy()
        records.append(stage_record("OPEN_INITIAL", "PASS_GEOMETRY_ONLY", "hinge set to measured/provisional open angle", data, hinge_angle_rad=float(data.qpos[hinge_a]), lid_top_xyz_m=top.tolist(), finite=finite(model, data)))
        sync()

    check_open()

    # Place shoes side by side in the measured 6 x 6 cm box.  This is a
    # kinematic insertion check, not a learned-policy replay.
    insertion_z = float(box_center[2] + 0.004)
    shoe_targets = [
        box_center + np.array([-0.010, -0.012, insertion_z - box_center[2]]),
        box_center + np.array([0.010, 0.012, insertion_z - box_center[2]]),
    ]
    for i, target in enumerate(shoe_targets):
        # Keep the order from the demonstration: pick one shoe, insert it,
        # then pick the second shoe and insert it.
        records.append(stage_record(f"PICK_SHOE{i}", "NOT_VALIDATED_ARM_GRASP", "requires calibrated arm trajectory and gripper contact/force model", data, finite=finite(model, data)))
        sync()
        set_free_pose(model, data, shoe_names[i], target)
        mujoco.mj_forward(model, data)
        p = body_pos(model, data, shoe_names[i])
        rel = p - body_pos(model, data, "paper_box")
        inside = bool(abs(rel[0]) <= 0.020 and abs(rel[1]) <= 0.020 and 0.0 <= rel[2] <= 0.052)
        records.append(stage_record(f"INSERT_SHOE{i}", "PASS_GEOMETRY_ONLY" if inside and finite(model, data) else "FAIL", "shoe teleported into box interior for fit check", data, shoe_xyz_m=p.tolist(), relative_to_box_m=rel.tolist(), inside_box=inside, finite=finite(model, data)))
        sync()

    # Close the robot-facing lid.  No torque/controller is claimed: qpos is
    # set directly so this stage tests hinge limits and clearances only.
    data.qpos[hinge_a] = 0.0
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    top_closed = data.geom_xpos[lid_geom].copy()
    shoes_inside_after_close = all(
        abs(body_pos(model, data, n)[0] - body_pos(model, data, "paper_box")[0]) <= 0.020
        and abs(body_pos(model, data, n)[1] - body_pos(model, data, "paper_box")[1]) <= 0.020
        for n in shoe_names
    )
    records.append(stage_record("CLOSE_LID", "PASS_GEOMETRY_ONLY" if shoes_inside_after_close and finite(model, data) else "FAIL", "hinge driven directly to closed limit; controller not validated", data, hinge_angle_rad=float(data.qpos[hinge_a]), lid_top_xyz_m=top_closed.tolist(), contents_remain_inside=shoes_inside_after_close, finite=finite(model, data)))
    sync()

    # Kinematic carry: move the closed box and its contents together.  This
    # confirms the tray target and dimensions but bypasses grasp dynamics.
    lift_delta = np.array([0.0, 0.0, 0.050])
    move_free_with_contents(model, data, contents, lift_delta)
    mujoco.mj_forward(model, data)
    records.append(stage_record("LIFT_BOX", "PASS_KINEMATIC_ONLY" if finite(model, data) else "FAIL", "box and contents translated together; no gripper attachment", data, box_xyz_m=body_pos(model, data, "paper_box").tolist(), finite=finite(model, data)))
    sync()
    carry_delta = tray_target - body_pos(model, data, "paper_box")
    move_free_with_contents(model, data, contents, carry_delta)
    mujoco.mj_forward(model, data)
    final_box = body_pos(model, data, "paper_box")
    tray_xy_error = float(np.linalg.norm(final_box[:2] - tray_target[:2]))
    records.append(stage_record("LOAD_TRAY", "PASS_KINEMATIC_ONLY" if tray_xy_error <= 1e-6 and finite(model, data) else "FAIL", "box placed at stationary tray target; logistics robot motion not simulated", data, box_xyz_m=final_box.tolist(), tray_target_xyz_m=tray_target.tolist(), tray_xy_error_m=tray_xy_error, finite=finite(model, data)))
    sync()

    if viewer is not None:
        viewer.close()

    arm_unvalidated = [r["stage"] for r in records if r["status"] == "NOT_VALIDATED_ARM_GRASP"]
    geometry_failures = [r["stage"] for r in records if r["status"] == "FAIL"]
    overall = "GEOMETRY_SEQUENCE_PASS_ARM_UNVALIDATED" if not geometry_failures and arm_unvalidated else ("GEOMETRY_SEQUENCE_FAIL" if geometry_failures else "FULL_SEQUENCE_ARM_VALIDATED")
    report = {
        "status": overall,
        "scene": str(scene),
        "initial_angle_rad": float(args.initial_angle),
        "convention": {"closed_rad": 0.0, "vertical_rad": -math.pi / 2.0, "flat_toward_omx_rad": -math.pi},
        "stages": records,
        "arm_grasp_stages": "NOT_VALIDATED",
        "transport_mode": "KINEMATIC_FREEJOINT_TRANSLATION",
        "warning": "This run verifies geometry and a scripted full sequence only; it is not robot performance, a learned-policy rollout, or proof of sim-to-real transfer.",
    }
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
