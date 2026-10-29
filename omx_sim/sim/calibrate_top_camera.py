"""Fit the pose and field of view of the top camera in the MuJoCo workspace scene to the real top video.

Nobody measured the camera's tilt or FOV, but the robot arm is in every frame and its joint angles are
recorded: render the arm silhouette in MuJoCo for a set of frames and adjust the camera
(position, yaw/pitch/roll, vertical FOV) until it overlaps the dark arm in the real frames
(maximise the mean IoU; Nelder-Mead from the measured starting pose, several FOV starts).

  python -I sim/calibrate_top_camera.py --episodes 0,10 --out outputs/sim_calib
Output: top_camera.json (fitted camera), overlay_*.jpg (real | real + sim arm outline | sim view)
"""

import argparse
import json
from pathlib import Path

import cv2
import mujoco
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset

SCENE = "sim/open_manipulator/open_manipulator_description/mujoco/omx/workspace_scene.xml"
ROBOT_BODIES = [f"link{i}" for i in range(8)] + ["end_effector_link"]
W, H = 160, 120  # fitting resolution (real frames 640x480)


def to_qpos(v):
    q = np.zeros(7)
    q[:5] = np.deg2rad(np.asarray(v[:5]) * 1.8)
    g = float(np.clip(np.deg2rad((v[5] - 50.0) * 3.6), 0.0, 1.745329))
    q[5], q[6] = g, -g
    return q


def rot(yaw, pitch, roll):
    cz, sz, cy, sy, cx, sx = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch), np.cos(roll), np.sin(roll)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    return Rz @ Ry @ Rx


# camera looking straight down, image up = robot forward (+x), image right = robot right (-y)
R0 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float).T  # columns: cam x (right), cam y (up), cam z (back)


def cam_params(p):
    x, y, z, yaw, pitch, roll, fovy = p
    R = rot(yaw, pitch, roll) @ R0
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, R.reshape(-1))
    return np.array([x, y, z]), q, fovy


class Sim:
    def __init__(self, w=W, h=H):
        self.m = mujoco.MjModel.from_xml_path(SCENE)
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, h, w)
        self.cam = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_CAMERA, "top")
        bodies = {mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, b) for b in ROBOT_BODIES}
        self.robot_geoms = np.array([g for g in range(self.m.ngeom) if self.m.geom_bodyid[g] in bodies])

    def set_cam(self, p):
        pos, quat, fovy = cam_params(p)
        self.m.cam_pos[self.cam], self.m.cam_quat[self.cam], self.m.cam_fovy[self.cam] = pos, quat, fovy

    def pose(self, state):
        self.d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(self.m, self.d)

    def arm_mask(self, state):
        """Arm silhouette with the workspace hidden (the table/Pinky sizes are uncertain and must not
        occlude the arm; in the real video the arm is always in front of them)."""
        self.pose(state)
        self.r.enable_segmentation_rendering()
        opt = mujoco.MjvOption()
        opt.geomgroup[1] = 0
        self.r.update_scene(self.d, camera=self.cam, scene_option=opt)
        seg = self.r.render()
        self.r.disable_segmentation_rendering()
        return (seg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & np.isin(seg[..., 0], self.robot_geoms)

    def rgb(self, state):
        self.pose(state)
        self.r.update_scene(self.d, camera=self.cam)
        return self.r.render()


def nelder_mead(f, x0, step, iters=300, tol=1e-4):
    n = len(x0)
    pts = [np.array(x0, float)] + [np.array(x0, float) + np.eye(n)[i] * step[i] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        o = np.argsort(vals)
        pts, vals = [pts[i] for i in o], [vals[i] for i in o]
        if abs(vals[-1] - vals[0]) < tol:
            break
        c = np.mean(pts[:-1], 0)
        xr = c + (c - pts[-1]); fr = f(xr)
        if fr < vals[0]:
            xe = c + 2 * (c - pts[-1]); fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = c + 0.5 * (pts[-1] - c); fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/omx_1024_test_jihyeok_success")
    ap.add_argument("--episodes", default="0,10")
    ap.add_argument("--frames_per_ep", type=int, default=10)
    ap.add_argument("--out", default="outputs/sim_calib")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = LeRobotDataset("local/" + Path(args.root).name, root=args.root)

    samples = []  # (real frame 640x480, state)
    for ep in [int(e) for e in args.episodes.split(",")]:
        e = ds.meta.episodes[ep]
        a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
        idx = np.linspace(a, b - 1, 60).astype(int)
        frames = [(ds[i]["observation.images.top"].permute(1, 2, 0).numpy() * 255).astype(np.uint8) for i in idx]
        states = [ds[i]["observation.state"].numpy() for i in idx]
        bg = np.median(np.stack([cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2] for f in frames]), 0)
        bright = cv2.erode((bg > 150).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        # frames where a good part of the arm is over the bright table / Pinky
        dark = [(cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2] < 80) & bright for f in frames]
        order = np.argsort([-m.sum() for m in dark])[: args.frames_per_ep]
        for k in sorted(order):
            samples.append((frames[k], states[k], bright, dark[k]))
    print(f"{len(samples)} calibration frames")

    sim = Sim()
    small = lambda m: cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)  # noqa: E731
    real = [(small(dk), small(br), st) for _, st, br, dk in samples]

    def loss(p):
        if not (5 < p[6] < 140 and p[2] > 0.1):
            return 2.0
        sim.set_cam(p)
        ious = []
        for rm, br, st in real:
            sm = sim.arm_mask(st) & br
            ious.append((sm & rm).sum() / max((sm | rm).sum(), 1))
        return 1 - float(np.mean(ious))

    best = None
    for fovy in (45, 65, 85, 105):
        p0 = [-0.07, 0.0, 0.30, 0.0, 0.0, 0.0, fovy]
        p, v = nelder_mead(loss, p0, [0.03, 0.03, 0.05, 0.1, 0.15, 0.1, 10])
        p, v = nelder_mead(loss, p, [0.01, 0.01, 0.02, 0.03, 0.05, 0.03, 3])
        print(f"start fovy {fovy}: IoU {1 - v:.3f}  cam {np.round(p, 3).tolist()}", flush=True)
        if best is None or v < best[1]:
            best = (p, v)
    p, v = best
    x, y, z, yaw, pitch, roll, fovy = p
    res = {"pos_m": [x, y, z], "yaw_pitch_roll_deg": np.degrees([yaw, pitch, roll]).tolist(), "fovy_deg": fovy,
           "fovx_deg": float(np.degrees(2 * np.arctan(np.tan(np.radians(fovy) / 2) * 640 / 480))),
           "mean_iou": 1 - v, "episodes": args.episodes}
    (out / "top_camera.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))

    # overlays at full resolution
    big = Sim(640, 480)
    big.set_cam(p)
    for i, (f, st, _, _) in enumerate(samples[:: max(1, len(samples) // 6)]):
        sm = big.arm_mask(st)
        ov = f.copy()
        cnts, _ = cv2.findContours(sm.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(ov, cnts, -1, (0, 255, 0), 2)
        rgb = big.rgb(st)
        blend = (0.5 * f + 0.5 * rgb).astype(np.uint8)
        cv2.imwrite(str(out / f"overlay_{i}.jpg"),
                    cv2.cvtColor(np.concatenate([ov, rgb, blend], 1), cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
