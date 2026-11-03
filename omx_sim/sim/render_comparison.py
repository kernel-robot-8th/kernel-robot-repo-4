"""Render recorded vs predicted joint trajectories on the ROBOTIS OMX MuJoCo model.

Reads the trajectories saved by eval_open_loop.py and writes, per episode:
  - ep###.mp4 : real camera1/camera2 frames next to the OMX replaying ground truth and each model
  - ep###_joints.png : joint trajectories (ground truth vs models)

The arm is posed kinematically (qpos set directly, no physics), so this shows where each
model would send the joints, not what would happen to objects.

Joint conversion (lerobot omx_follower, factory calibration, raw 0..4095 over 360 deg, 0 rad at 2048):
  body joints: RANGE_M100_100 -> angle = value * 1.8 deg
  gripper:     RANGE_0_100    -> angle = (value - 50) * 3.6 deg, clipped to the model's 0..100 deg
This mapping is an assumption; check it against the real camera frames in the video.

Usage (inside omx-lerobot-sim): python -I sim/render_comparison.py --episodes 0,10,19
  10/27 workspace seen from its fitted top camera:
  python -I sim/render_comparison.py --eval_dir outputs/eval/cmp_1027 --dataset_root data/omx_1027_jihyeok_eval1_grip \
      --repo_id local/omx_1027_jihyeok_eval1_grip --episodes 0 --scene workspace_scene_1027.xml --camera top
"""

import argparse
import json
from pathlib import Path

import cv2
import imageio.v3 as iio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

OMX = Path("sim/open_manipulator/open_manipulator_description/mujoco/omx")
JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
W, H = 400, 300
COLORS = {"GT": "black", "base": "tab:red", "2k": "tab:orange", "20k": "tab:blue",
          "full": "tab:blue", "holdout": "tab:green", "phases": "tab:purple",
          "B0": "tab:red", "C30": "tab:orange", "C50": "tab:blue", "C50AUG": "tab:green",
          "5ep": "tab:orange", "10ep": "tab:blue", "15ep": "tab:green", "20ep": "tab:purple"}


def to_qpos(v):
    q = np.zeros(7)
    q[:5] = np.deg2rad(np.asarray(v[:5]) * 1.8)
    g = float(np.clip(np.deg2rad((v[5] - 50.0) * 3.6), 0.0, 1.745329))
    q[5], q[6] = g, -g
    return q


def label(img, text, sub=None):
    img = np.ascontiguousarray(img)
    cv2.rectangle(img, (0, 0), (W, 26), (0, 0, 0), -1)
    cv2.putText(img, text, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    if sub:
        cv2.putText(img, sub, (8, H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)
    return img


def cam_frame(t):
    return cv2.resize((t.permute(1, 2, 0).numpy() * 255).astype(np.uint8), (W, H))


def plot_joints(trajs, ep, fps, path):
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharex=True)
    for j, ax in enumerate(axes.flat):
        for name, tr in trajs.items():
            t = np.arange(len(tr)) / fps
            ax.plot(t, tr[:, j], color=COLORS.get(name), lw=2.2 if name == "GT" else 1.4,
                    ls="--" if name == "GT" else "-", label=name)
        ax.set_title(JOINTS[j])
        ax.grid(alpha=0.3)
    for ax in axes[1]:
        ax.set_xlabel("time [s]")
    axes[0, 0].legend()
    fig.suptitle(f"episode {ep}: recorded action vs open-loop predictions (lerobot units)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval_dir", default="outputs/eval/open_loop")
    ap.add_argument("--dataset_root", default="data/omx_heart_box")
    ap.add_argument("--repo_id", default="Sungah/omx_heart_box")
    ap.add_argument("--episodes", default="0,10,19")
    ap.add_argument("--scene", default="scene.xml", help="scene file next to omx.xml (e.g. workspace_scene_1027.xml)")
    ap.add_argument("--camera", default=None, help="named scene camera (default: free camera from the side)")
    args = ap.parse_args()

    ev = Path(args.eval_dir)
    models = list(json.loads((ev / "metrics.json").read_text())["results"].keys())
    ds = LeRobotDataset(args.repo_id, root=args.dataset_root)
    fps = ds.fps

    m = mujoco.MjModel.from_xml_path(str(OMX / args.scene))
    d = mujoco.MjData(m)
    r = mujoco.Renderer(m, H, W)
    cam = args.camera
    if cam is None:
        cam = mujoco.MjvCamera()
        cam.lookat[:] = [0.12, 0.0, 0.10]
        cam.distance, cam.azimuth, cam.elevation = 0.7, 135, -25

    def render(v):
        d.qpos[:7] = to_qpos(v)  # workspace scenes add box free joints after the arm
        mujoco.mj_forward(m, d)
        r.update_scene(d, cam)
        return r.render()

    for ep in [int(x) for x in args.episodes.split(",")]:
        trajs = {"GT": np.load(ev / f"gt_ep{ep:03d}.npy")}
        for name in models:
            trajs[name] = np.load(ev / f"pred_{name}_ep{ep:03d}.npy")
        plot_joints(trajs, ep, fps, ev / f"ep{ep:03d}_joints.png")

        e = ds.meta.episodes[ep]
        start = int(e["dataset_from_index"])
        frames = []
        for t in range(len(trajs["GT"])):
            s = ds[start + t]
            cams = [k for k in ds.meta.camera_keys]
            panels = [label(cam_frame(s[k]), "real " + k.split(".")[-1]) for k in cams]
            panels.append(label(render(trajs["GT"][t]), "sim: recorded action (GT)", f"t={t / fps:5.1f}s"))
            for name in models:
                err = np.abs(trajs[name][t] - trajs["GT"][t]).mean()
                panels.append(label(render(trajs[name][t]), f"sim: {name}", f"|err| {err:6.2f}"))
            while len(panels) % 3:
                panels.append(np.zeros((H, W, 3), np.uint8))
            rows = [np.concatenate(panels[i:i + 3], 1) for i in range(0, len(panels), 3)]
            frames.append(np.concatenate(rows, 0))
        iio.imwrite(ev / f"ep{ep:03d}.mp4", np.stack(frames), fps=fps, codec="libx264",
                    plugin="pyav", out_pixel_format="yuv420p")
        print(f"ep{ep:03d}: {len(frames)} frames -> {ev / f'ep{ep:03d}.mp4'}", flush=True)


if __name__ == "__main__":
    main()
