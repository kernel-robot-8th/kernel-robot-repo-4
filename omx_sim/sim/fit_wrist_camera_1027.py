"""Wrist camera of the 10/27 workspace: fit the mount (pose on end_effector_link + FOV) to the wrist video.

No tracked box masks exist for omx_1027_jihyeok_train8, so the cue is everything white in the wrist view:
real = bright, unsaturated pixels (thin floor tape removed by an opening), sim = table + Pinky disk + box +
stand rendered from the wrist camera with the arm posed from the recorded joint state. Frames: the last 2.5 s before the
grasp (box at its start, box_starts of scene_params_1027.json) and 2 s after the release (box on the disk), only while the arm is away from its rest pose (the rest view shows little but the stand). Parameters as in fit_wrist_camera.py; the real lens is wide-angle, the MuJoCo camera a pinhole.

  python -I sim/fit_wrist_camera_1027.py   -> calib/wrist_camera_1027.json, outputs/sim_calib/wrist1027_fit.jpg
then rerun fit_env_1027.py and build_scene.py --params sim/calib/scene_params_1027.json
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import nelder_mead, rot, to_qpos  # noqa: E402
from replay_episode import grasps  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CALIB = ROOT / "sim/calib"
OMX = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx"
W, H = 160, 120
WHITE_GEOMS = ("table", "pinky_disk", "box1", "robot_stand")  # the pale wooden stand also passes the threshold


def white_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 2] > 165) & (hsv[..., 1] < 55)).astype(np.uint8)
    m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)


class WristSim:
    def __init__(self, P, w=W, h=H):
        self.m = mujoco.MjModel.from_xml_path(str(OMX / P["scene_file"]))
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, h, w)
        self.cam = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
        self.white = [mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, g) for g in WHITE_GEOMS]
        b = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, "box1")
        self.box_adr = self.m.jnt_qposadr[self.m.body_jntadr[b]]

    def set_cam(self, p, base_axes):
        x, y, z, yaw, pitch, roll, fovy = p
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, (rot(yaw, pitch, roll) @ np.array(base_axes, float).T).reshape(-1))
        self.m.cam_pos[self.cam], self.m.cam_quat[self.cam], self.m.cam_fovy[self.cam] = [x, y, z], q, fovy

    def pose(self, state, box_pos):
        self.d.qpos[:7] = to_qpos(state)
        self.d.qpos[self.box_adr:self.box_adr + 3] = box_pos
        self.d.qpos[self.box_adr + 3:self.box_adr + 7] = [1, 0, 0, 0]
        mujoco.mj_forward(self.m, self.d)

    def white_mask(self, state, box_pos):
        self.pose(state, box_pos)
        self.r.enable_segmentation_rendering()
        self.r.update_scene(self.d, camera=self.cam)
        s = self.r.render()
        self.r.disable_segmentation_rendering()
        return (s[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & np.isin(s[..., 0], self.white)

    def rgb(self, state, box_pos):
        self.pose(state, box_pos)
        self.r.update_scene(self.d, camera=self.cam)
        return self.r.render()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="0,2,4,6")
    ap.add_argument("--frames_per_ep", type=int, default=10)
    args = ap.parse_args()
    P = json.loads((CALIB / "scene_params_1027.json").read_text())
    wc = P["wrist_camera"]
    ds = LeRobotDataset("local/" + Path(P["dataset"]).name, root=ROOT / P["dataset"])
    pk, hz = P["pinky"], np.asarray(P["boxes"]["box1"]["size_m"])[2] / 2

    data = []  # (state, box position, real white mask, real frame)
    for ep in [int(e) for e in args.episodes.split(",")]:
        e = ds.meta.episodes[ep]
        a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
        rows = ds.hf_dataset.select(range(a, b))
        ac = np.stack([np.asarray(x) for x in rows["action"]])
        st0 = np.stack([np.asarray(x) for x in rows["observation.state"]])
        moving = np.abs(st0[:, :5] - st0[0, :5]).max(1) > 8  # lerobot units (~14 deg)
        c, o = grasps(ac)[0]
        start = P["box_starts"][f"ep{ep}"]["box1"]["pos_m"]
        on_disk = [pk["x"], pk["y"], pk["disk_top_z"] + hz]
        cand = [(t, start) for t in range(max(15, c - 75), c - 5, 2) if moving[t]] + \
               [(t, on_disk) for t in range(o + 5, min(o + 60, b - a), 2) if moving[t]]
        picked = []
        for t, box in cand:
            s = ds[a + t]
            img = (s["observation.images.wrist"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
            wm = white_mask(img)
            if 0.05 < wm.mean() < 0.85:
                picked.append((s["observation.state"].numpy(), box, wm, img))
        for i in np.linspace(0, len(picked) - 1, min(args.frames_per_ep, len(picked))).astype(int):
            data.append(picked[i])
    print(f"{len(data)} wrist frames", flush=True)

    sim = WristSim(P)

    def loss(p):
        if not (20 < p[6] < 150):
            return 2.0
        sim.set_cam(p, wc["base_axes"])
        ious = [(lambda sm: (sm & real).sum() / max((sm | real).sum(), 1))(sim.white_mask(st, box))
                for st, box, real, _ in data]
        return 1 - float(np.mean(ious))

    old = list(wc["pos_m"]) + list(np.radians(wc["yaw_pitch_roll_deg"])) + [wc["fovy_deg"]]
    print(f"10/24 wrist camera: IoU {1 - loss(old):.3f}", flush=True)
    best = (old, loss(old))
    for fovy in (40, 60, 80):
        for pitch in (0, 20, 40):
            for yaw in (-15, 0, 15):
                p0 = list(wc["pos_m"]) + [np.radians(yaw), np.radians(pitch), 0, fovy]
                v = loss(p0)
                if v < best[1]:
                    best = (p0, v)
    print("grid best IoU", round(1 - best[1], 3), np.round(best[0], 3).tolist(), flush=True)
    p, v = nelder_mead(loss, best[0], [0.02, 0.02, 0.02, 0.1, 0.1, 0.1, 8], iters=500)
    p, v = nelder_mead(loss, p, [0.005, 0.005, 0.005, 0.03, 0.03, 0.03, 2], iters=500)
    print("fitted IoU", round(1 - v, 3), np.round(p, 4).tolist(), flush=True)
    res = {"pos_m": [float(x) for x in p[:3]], "yaw_pitch_roll_deg": np.degrees(p[3:6]).tolist(),
           "fovy_deg": float(p[6]), "base_axes": wc["base_axes"], "old_iou": 1 - loss(old),
           "source": f"fit_wrist_camera_1027.py: white regions (table, disk, box) in the wrist video of "
                     f"{P['dataset']} eps {args.episodes}, IoU {1 - v:.3f} (10/24 camera {1 - loss(old):.3f}); "
                     "pinhole approximation of a wide-angle lens"}
    (CALIB / "wrist_camera_1027.json").write_text(json.dumps(res, indent=2))

    big = WristSim(P, 320, 240)
    rows = []
    for st, box, _, img in data[:: max(1, len(data) // 4)][:4]:
        r = []
        for q in (old, p):
            big.set_cam(q, wc["base_axes"])
            rgb = big.rgb(st, box)
            r.append((0.5 * cv2.resize(img, (320, 240)) + 0.5 * rgb).astype(np.uint8))
        rows.append(np.concatenate([cv2.resize(img, (320, 240))] + r, 1))
    out = ROOT / "outputs/sim_calib"
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "wrist1027_fit.jpg"), cv2.cvtColor(np.concatenate(rows, 0), cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
