"""Replay a recorded episode in the fitted MuJoCo workspace and save real | sim views side by side.

Kinematic replay (no physics): the arm follows observation.state; a box is attached to the gripper
from the moment the gripper closes on it until it opens (grasp k holds box k: A then B, or D), and on
release it is set down on whatever is below it (other box, Pinky's disk or the table).
Box starts come from the scene parameter file (box_starts of the episode, or of ep 0 / ep 10); its
"boxes" entry says which box each grasp holds. Dataset and scene come from the same file.

  python -I sim/replay_episode.py --episode 10 --out outputs/sim_replay/ep010.mp4
  python -I sim/replay_episode.py --params sim/calib/scene_params_1027.json --episode 0
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import imageio.v3 as iio
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import to_qpos  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
OMX = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx"
TW, TH = 480, 360


def grasps(actions, min_len=15):
    g = actions[:, 5]
    thr = (np.percentile(g, 90) + g.min()) / 2
    closed = np.concatenate([[False], g < thr, [False]])
    e = np.flatnonzero(np.diff(closed.astype(int)))
    return [(int(s), int(t)) for s, t in zip(e[::2], e[1::2]) if t - s >= min_len]


def quat_mat(q):
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(q, float))
    return R.reshape(3, 3)


def mat_quat(R):
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, float).reshape(-1))
    return q


def label(img, text):
    img = np.ascontiguousarray(cv2.resize(img, (TW, TH)))
    cv2.rectangle(img, (0, 0), (TW, 24), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--params", default=str(PARAMS))
    ap.add_argument("--root", default=None, help="dataset dir (default: the parameter file's dataset)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--every", type=int, default=1, help="render every n-th frame (fps divided accordingly)")
    args = ap.parse_args()
    ep = args.episode
    P = json.loads(Path(args.params).read_text())
    starts = P["box_starts"].get(f"ep{ep}") or P["box_starts"]["ep0" if ep < 10 else "ep10"]
    root = Path(args.root) if args.root else ROOT / P.get("dataset", "data/omx_1024_test_jihyeok_success")
    ds = LeRobotDataset("local/" + root.name, root=root)
    e = ds.meta.episodes[ep]
    a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
    rows = ds.hf_dataset.select(range(a, b))
    states = np.stack([np.asarray(x) for x in rows["observation.state"]])
    actions = np.stack([np.asarray(x) for x in rows["action"]])
    order = list(starts["boxes"])  # grasp k holds order[k]
    holds = grasps(actions)[: len(order)]
    names = list(P["boxes"])

    m = mujoco.MjModel.from_xml_path(str(OMX / P.get("scene_file", "workspace_scene.xml")))
    d = mujoco.MjData(m)
    r = mujoco.Renderer(m, 480, 640)
    half = {n: np.broadcast_to(np.asarray(P["boxes"][n]["size_m"], float), 3) / 2 for n in names}
    adr, bid = {}, {}
    for n in names:
        bid[n] = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)
        adr[n] = m.jnt_qposadr[m.body_jntadr[bid[n]]]
        m.geom_size[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n)] = half[n]
    ee = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "end_effector_link")
    pose = {n: (np.array(starts[n]["pos_m"], float), mat_quat(
        quat_mat([np.cos(np.radians(starts[n]["yaw_deg"]) / 2), 0, 0, np.sin(np.radians(starts[n]["yaw_deg"]) / 2)])))
        for n in names}
    t_, pk = P["table"], P["pinky"]

    def support_z(n, xy):
        z = -10.0
        if t_["x_near"] <= xy[0] <= t_["x_far"] and t_["y_right"] <= xy[1] <= t_["y_left"]:
            z = max(z, t_["top_z"])
        if np.hypot(xy[0] - pk["x"], xy[1] - pk["y"]) <= pk["disk_radius"]:
            z = max(z, pk["disk_top_z"])
        for o in names:
            if o != n and np.all(np.abs(pose[o][0][:2] - xy) < (half[o][:2] + half[n][:2]) * 0.9):
                z = max(z, pose[o][0][2] + half[o][2])
        return z if z > -10 else P["floor_z"]

    attached, rel = None, None
    frames = []
    for t in range(len(states)):
        d.qpos[:7] = to_qpos(states[t])
        mujoco.mj_forward(m, d)
        Pe, Re = d.xpos[ee].copy(), d.xmat[ee].reshape(3, 3).copy()
        for k, (c, o) in enumerate(holds):
            n = order[k]
            if t == c:  # grasp: keep the box pose relative to the gripper
                attached = n
                p0, q0 = pose[n]
                rel = (Re.T @ (p0 - Pe), Re.T @ quat_mat(q0))
            if t == o and attached == n:  # release: set it down on what is below
                p0, q0 = pose[n]
                pose[n] = (np.array([p0[0], p0[1], support_z(n, p0[:2]) + half[n][2]]), q0)
                attached = None
        if attached:
            pose[attached] = (Pe + Re @ rel[0], mat_quat(Re @ rel[1]))
        for n in names:
            d.qpos[adr[n]:adr[n] + 3], d.qpos[adr[n] + 3:adr[n] + 7] = pose[n]
        mujoco.mj_forward(m, d)
        if t % args.every:
            continue
        s_ = ds[a + t]
        views = []
        for cam in ("top", "wrist"):
            r.update_scene(d, camera=cam)
            real = (s_[f"observation.images.{cam}"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
            views += [label(real, f"real {cam}  t={t / ds.fps:5.1f}s"), label(r.render(), f"sim {cam}")]
        frames.append(np.concatenate([np.concatenate(views[:2], 1), np.concatenate(views[2:], 1)], 0))
    out = Path(args.out or ROOT / f"outputs/sim_replay/ep{ep:03d}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(out, np.stack(frames), fps=ds.fps / args.every, codec="libx264", plugin="pyav",
                out_pixel_format="yuv420p")
    print(f"ep{ep}: {len(frames)} frames, grasps {holds} -> {out}")


if __name__ == "__main__":
    main()
