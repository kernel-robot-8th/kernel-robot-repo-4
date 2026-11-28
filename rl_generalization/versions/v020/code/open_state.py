"""Inspect the v020 initial lid state used by a future staged controller."""
import argparse
import json
from pathlib import Path
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[3]

parser = argparse.ArgumentParser()
parser.add_argument("--scene", type=Path, default=ROOT / ".local/robot_facing_hinge_v020/scene.xml")
parser.add_argument("--angle", type=float, default=-np.pi, help="hinge angle: -pi is flat toward OMX")
a = parser.parse_args()
scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
m = mujoco.MjModel.from_xml_path(str(scene))
d = mujoco.MjData(m)
j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "lid_hinge")
if not (-np.pi - 1e-9 <= a.angle <= 1e-9):
    raise SystemExit("angle must be in [-pi, 0]")
d.qpos[m.jnt_qposadr[j]] = a.angle
mujoco.mj_forward(m, d)
g = m.geom("lid_top").id
print(json.dumps({"scene": str(scene), "hinge_angle_rad": a.angle, "lid_top_xyz_m": d.geom_xpos[g].tolist(), "status": "OPEN_INITIAL_STATE" if a.angle < -1e-6 else "CLOSED_STATE"}, indent=2))
