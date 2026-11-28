"""Open the v020 workcell scene at a chosen lid hinge angle."""
import argparse
import time
from pathlib import Path
import numpy as np
import mujoco
import mujoco.viewer

ROOT = Path(__file__).resolve().parents[3]
p = argparse.ArgumentParser()
p.add_argument("--scene", type=Path, default=ROOT / ".local/robot_facing_hinge_v020/scene.xml")
p.add_argument("--angle", type=float, default=-np.pi, help="0 closed, -pi/2 vertical, -pi toward OMX")
a = p.parse_args()
if not (-np.pi - 1e-9 <= a.angle <= 1e-9):
    raise SystemExit("--angle must be in [-pi, 0]")
a.angle = float(np.clip(a.angle, -np.pi, 0.0))
scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
m = mujoco.MjModel.from_xml_path(str(scene))
d = mujoco.MjData(m)
j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "lid_hinge")
d.qpos[m.jnt_qposadr[j]] = a.angle
mujoco.mj_forward(m, d)
print(f"SIMULATION PREVIEW ONLY: lid_hinge={a.angle:.6f} rad; 0=closed, -pi=OMX-facing open")
with mujoco.viewer.launch_passive(m, d) as viewer:
    viewer.cam.lookat[:] = [0.16, 0.0, 0.18]
    viewer.cam.distance = 0.65
    viewer.cam.azimuth = 135
    viewer.cam.elevation = -25
    while viewer.is_running():
        viewer.sync()
        time.sleep(0.03)
