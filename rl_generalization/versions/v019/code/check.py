"""Validate the v019 hinged-lid structural transformation."""

from __future__ import annotations

import json
from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / ".local/finger_proxy_v018/scene.xml"
NEW = ROOT / ".local/hinged_lid_v019/scene.xml"
OUT = ROOT / "versions/v019/evidence/compile_check.json"


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
    hinge_qpos = new.jnt_qposadr[hinge]
    dn.qpos[hinge_qpos] = -np.pi / 2
    mujoco.mj_forward(new, dn)
    top = mujoco.mj_name2id(new, mujoco.mjtObj.mjOBJ_GEOM, "lid_top")
    open_top_z = float(dn.geom_xpos[top, 2])
    result = {
        "compiled": True,
        "nq": int(new.nq),
        "hinge_joint_id": int(hinge),
        "closed_world_pose_max_error_m": max(diffs.values()),
        "closed_world_pose_error_m": diffs,
        "open_minus_pi_over_2_lid_top_z_m": open_top_z,
        "checks": {
            "closed_pose_preserved": bool(max(diffs.values()) < 1e-9),
            "hinge_opens_upward": bool(open_top_z > 0.233),
        },
        "warning": "Structural hinge only; hinge direction, clearance, compliance, and hardware behavior are unvalidated.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
