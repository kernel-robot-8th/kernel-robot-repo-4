"""Compile and validate the v020 robot-facing hinged-lid geometry."""

from __future__ import annotations

import json
from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / ".local/finger_proxy_v018/scene.xml"
NEW = ROOT / ".local/robot_facing_hinge_v020/scene.xml"
OUT = ROOT / "versions/v020/evidence/compile_check.json"


def main() -> None:
    old = mujoco.MjModel.from_xml_path(str(OLD))
    new = mujoco.MjModel.from_xml_path(str(NEW))
    do, dn = mujoco.MjData(old), mujoco.MjData(new)
    mujoco.mj_forward(old, do)
    mujoco.mj_forward(new, dn)
    names = ["lid_top", "lid_x-1", "lid_x1", "lid_y-1", "lid_y1"]
    diffs = {}
    for name in names:
        io = mujoco.mj_name2id(old, mujoco.mjtObj.mjOBJ_GEOM, name)
        inn = mujoco.mj_name2id(new, mujoco.mjtObj.mjOBJ_GEOM, name)
        diffs[name] = float(np.linalg.norm(do.geom_xpos[io] - dn.geom_xpos[inn]))
    hinge = mujoco.mj_name2id(new, mujoco.mjtObj.mjOBJ_JOINT, "lid_hinge")
    qadr = new.jnt_qposadr[hinge]
    top = mujoco.mj_name2id(new, mujoco.mjtObj.mjOBJ_GEOM, "lid_top")
    dn.qpos[qadr] = -np.pi / 2
    mujoco.mj_forward(new, dn)
    vertical_top = dn.geom_xpos[top].copy()
    dn.qpos[qadr] = -np.pi
    mujoco.mj_forward(new, dn)
    flat_top = dn.geom_xpos[top].copy()
    result = {
        "compiled": True,
        "nq": int(new.nq),
        "hinge_joint_id": int(hinge),
        "closed_world_pose_max_error_m": max(diffs.values()),
        "closed_world_pose_error_m": diffs,
        "vertical_minus_pi_over_2_lid_top_xyz_m": vertical_top.tolist(),
        "flat_minus_pi_lid_top_xyz_m": flat_top.tolist(),
        "checks": {
            "closed_pose_preserved": bool(max(diffs.values()) < 1e-9),
            "vertical_opening_rises": bool(vertical_top[2] > 0.233),
            "flat_opening_moves_toward_robot_negative_x": bool(flat_top[0] < 0.2235),
        },
        "warning": "Structural hinge only; real lid edge, clearance, compliance, and hardware behavior remain unvalidated.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
