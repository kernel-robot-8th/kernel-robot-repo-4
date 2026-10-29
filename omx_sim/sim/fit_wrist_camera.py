"""Fit the wrist camera mount (pose on end_effector_link + FOV) to the recorded wrist video.

Before the first grasp of an episode the box still stands at its start position, which is known from
the top-camera fit (scene_params.json box_starts). For frames of that approach phase the box is
rendered from the wrist camera (arm posed from the recorded joint state) and compared with the box
mask tracked in the real wrist video (data/aug_test/work/epXXX/wrist_masks.npz). Parameters: camera
position in the link frame, yaw/pitch/roll relative to "looking along the gripper", vertical FOV.
The real wrist camera is wide-angle with barrel distortion; the MuJoCo camera is a pinhole, so the
fit is an approximation (best near the image centre).

  python -I sim/fit_wrist_camera.py --episodes 10,0
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

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
SCENE = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx/workspace_scene.xml"
W, H = 160, 120


def load_masks(path):
    z = np.load(path)
    shape = tuple(z["_shape"])
    return {k: np.unpackbits(z[k], axis=-1)[..., : shape[-1]].astype(bool) for k in z.files if k != "_shape"}


def grasp_close(ds, ep):
    e = ds.meta.episodes[ep]
    a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
    g = np.array([ds.hf_dataset[i]["action"][5] for i in range(a, b)])
    thr = (np.percentile(g, 90) + g.min()) / 2
    return int(np.argmax(g < thr))


class WristSim:
    def __init__(self, w=W, h=H):
        self.m = mujoco.MjModel.from_xml_path(str(SCENE))
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, h, w)
        self.cam = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
        self.g_box = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "box1")
        self.g_table = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "table")

    def set_cam(self, p, base_axes):
        x, y, z, yaw, pitch, roll, fovy = p
        R = rot(yaw, pitch, roll) @ np.array(base_axes, float).T
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, R.reshape(-1))
        self.m.cam_pos[self.cam], self.m.cam_quat[self.cam], self.m.cam_fovy[self.cam] = [x, y, z], q, fovy

    def place_boxes(self, start, size):
        for n in ("box1", "box2"):
            b = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, n)
            a = self.m.jnt_qposadr[self.m.body_jntadr[b]]
            yaw = np.radians(start[n]["yaw_deg"])
            self.d.qpos[a:a + 3] = start[n]["pos_m"]
            self.d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
            self.m.geom_size[mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, n)] = [size / 2] * 3

    def seg(self, state):
        self.d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(self.m, self.d)
        self.r.enable_segmentation_rendering()
        self.r.update_scene(self.d, camera=self.cam)
        s = self.r.render()
        self.r.disable_segmentation_rendering()
        return s

    def rgb(self, state):
        self.d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(self.m, self.d)
        self.r.update_scene(self.d, camera=self.cam)
        return self.r.render()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="10,0")
    ap.add_argument("--frames_per_ep", type=int, default=12)
    args = ap.parse_args()
    P = json.loads(PARAMS.read_text())
    wc = P["wrist_camera"]
    size = P["boxes"]["box1"]["size_m"]
    ds = LeRobotDataset("local/omx_1024_test_jihyeok_success", root=ROOT / "data/omx_1024_test_jihyeok_success")

    data = []  # (episode start dict, state, real box mask small, real frame)
    for ep in [int(e) for e in args.episodes.split(",")]:
        start = P["box_starts"][f"ep{ep}"]
        a0 = int(ds.meta.episodes[ep]["dataset_from_index"])
        close = grasp_close(ds, ep)
        masks = load_masks(ROOT / f"data/aug_test/work/ep{ep:03d}/wrist_masks.npz")
        mk = masks["A"] if "A" in masks else masks["D"]  # box1 = the box grasped first
        cand = [t for t in range(0, close - 10) if 0.03 < mk[t].mean() < 0.6]  # box visible, not filling the view
        for t in np.array(cand)[np.linspace(0, len(cand) - 1, min(args.frames_per_ep, len(cand))).astype(int)]:
            s = ds[a0 + int(t)]
            real = cv2.resize(mk[t].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
            data.append((start, s["observation.state"].numpy(), real,
                         (s["observation.images.wrist"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)))
    print(f"{len(data)} wrist frames", flush=True)

    sim = WristSim()

    def loss(p):
        if not (20 < p[6] < 150):
            return 2.0
        sim.set_cam(p, wc["base_axes"])
        ious = []
        for start, st, real, _ in data:
            sim.place_boxes(start, size)
            sg = sim.seg(st)
            sm = (sg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & (sg[..., 0] == sim.g_box)
            ious.append((sm & real).sum() / max((sm | real).sum(), 1))
        return 1 - float(np.mean(ious))

    best = None
    for fovy in (50, 70, 90):
        for pitch in (0, 20, 40):
            p0 = list(wc["pos_m"]) + [0, np.radians(pitch), 0, fovy]
            v = loss(p0)
            if best is None or v < best[1]:
                best = (p0, v)
    print("grid best IoU", 1 - best[1], np.round(best[0], 3).tolist(), flush=True)
    p, v = nelder_mead(loss, best[0], [0.02, 0.02, 0.02, 0.1, 0.1, 0.1, 8], iters=600)
    p, v = nelder_mead(loss, p, [0.005, 0.005, 0.005, 0.03, 0.03, 0.03, 2], iters=600)
    print("fitted IoU", 1 - v, np.round(p, 4).tolist(), flush=True)
    P["wrist_camera"] = {"pos_m": list(p[:3]), "yaw_pitch_roll_deg": list(np.degrees(p[3:6])), "fovy_deg": float(p[6]),
                         "base_axes": wc["base_axes"],
                         "source": f"fitted to the wrist box masks before the first grasp (ep {args.episodes}), "
                                   f"IoU {1 - v:.3f}; pinhole approximation of a wide-angle lens"}
    PARAMS.write_text(json.dumps(P, indent=2))

    big = WristSim(640, 480)
    big.set_cam(p, wc["base_axes"])
    rows = []
    for start, st, real, img in data[:: max(1, len(data) // 4)][:4]:
        big.place_boxes(start, size)
        rgb = big.rgb(st)
        rows.append(np.concatenate([img, rgb, (0.5 * img + 0.5 * rgb).astype(np.uint8)], 1))
    cv2.imwrite(str(ROOT / "outputs/sim_calib/wrist_fit.jpg"),
                cv2.cvtColor(np.concatenate(rows, 0)[::2, ::2], cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
