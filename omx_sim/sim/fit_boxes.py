"""Fit the start position / yaw of the boxes on the table from the top video (first frame), using the box
masks tracked for the box-swap augmentation (data/aug_test/work/epXXX/top_masks.npz).
  ep 0-9 : A stacked on B  -> box1 = A (on top of box2), box2 = B (on the table)
  ep 10-14: one box D      -> box1 = D, box2 parked off the table
Writes "box_starts" into sim/calib/scene_params.json.

  python -I sim/fit_boxes.py --episodes 0,10
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import Sim, nelder_mead, to_qpos  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
W, H = 320, 240
PARK = [0.6, -0.6]  # x, y of an unused box (out of view)


def load_masks(path):
    z = np.load(path)
    shape = tuple(z["_shape"])
    return {k: np.unpackbits(z[k], axis=-1)[..., : shape[-1]].astype(bool) for k in z.files if k != "_shape"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/omx_1024_test_jihyeok_success")
    ap.add_argument("--episodes", default="0,10")
    args = ap.parse_args()
    params = json.loads(PARAMS.read_text())
    tc = params["top_camera"]
    p_cam = list(tc["pos_m"]) + list(np.radians(tc["yaw_pitch_roll_deg"])) + [tc["fovy_deg"]]
    top_z = params["table"]["top_z"]
    ds = LeRobotDataset("local/" + Path(args.root).name, root=args.root)

    sim = Sim(W, H)
    sim.set_cam(p_cam)
    m, d = sim.m, sim.d
    gid = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n) for n in ("box1", "box2")}
    jadr = {n: m.jnt_qposadr[m.body_jntadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)]] for n in gid}

    def place(name, x, y, z, yaw):
        a = jadr[name]
        d.qpos[a:a + 3] = [x, y, z]
        d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]

    def seg():
        opt = mujoco.MjvOption()
        sim.r.enable_segmentation_rendering()
        sim.r.update_scene(d, camera=sim.cam, scene_option=opt)
        s = sim.r.render()
        sim.r.disable_segmentation_rendering()
        return {n: (s[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & (s[..., 0] == g) for n, g in gid.items()}

    iou = lambda a, b: (a & b).sum() / max((a | b).sum(), 1)  # noqa: E731
    big = Sim(640, 480)  # one renderer for the overlays (a second OSMesa context per episode rendered noise)
    big.set_cam(p_cam)
    starts = params.get("box_starts", {})
    for ep in [int(e) for e in args.episodes.split(",")]:
        a0 = int(ds.meta.episodes[ep]["dataset_from_index"])
        state = ds[a0]["observation.state"].numpy()
        masks = load_masks(ROOT / f"data/aug_test/work/ep{ep:03d}/top_masks.npz")
        small = {k: cv2.resize(v[0].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
                 for k, v in masks.items()}
        stacked = ep < 10
        real = {"box1": small["A"], "box2": small["B"]} if stacked else {"box1": small["D"]}
        h = params["boxes"]["box1"]["size_m"]

        def setp(p):
            x2, y2, yaw2, dx1, dy1, yaw1 = p if stacked else (PARK[0], PARK[1], 0, *p)
            if stacked:  # B on the table, A on B (offset dx1, dy1)
                place("box2", x2, y2, top_z + h / 2, yaw2)
                place("box1", x2 + dx1, y2 + dy1, top_z + 1.5 * h, yaw1)
            else:        # p = (x, y, yaw) of the single box
                place("box2", *PARK, top_z + h / 2, 0)
                place("box1", p[0], p[1], top_z + h / 2, p[2])
            sim.d.qpos[:7] = to_qpos(state)  # the arm can occlude the boxes
            mujoco.mj_forward(m, d)

        def loss(p):
            setp(p)
            s = seg()
            return 1 - np.mean([iou(s[n], real[n]) for n in real])

        # coarse grid over the table, then Nelder-Mead
        p0 = [0.18, 0.0, 0.0, 0.0, 0.0, 0.0] if stacked else [0.18, 0.0, 0.0]
        best = None
        for x0 in (0.14, 0.18, 0.22):
            for y0 in (-0.05, 0.0, 0.05):
                q = list(p0)
                q[0], q[1] = x0, y0
                v = loss(q)
                if best is None or v < best[1]:
                    best = (q, v)
        step = [0.01, 0.01, 0.2, 0.005, 0.005, 0.2] if stacked else [0.01, 0.01, 0.2]
        p, v = nelder_mead(loss, best[0], step, iters=400)
        print(f"ep{ep}: IoU {1 - v:.3f}  params {np.round(p, 4).tolist()}", flush=True)
        if stacked:
            x2, y2, yaw2, dx1, dy1, yaw1 = p
            starts[f"ep{ep}"] = {"box2": {"pos_m": [x2, y2, top_z + h / 2], "yaw_deg": float(np.degrees(yaw2))},
                                 "box1": {"pos_m": [x2 + dx1, y2 + dy1, top_z + 1.5 * h], "yaw_deg": float(np.degrees(yaw1))},
                                 "iou": 1 - v, "boxes": {"box1": "A", "box2": "B"}}
        else:
            starts[f"ep{ep}"] = {"box1": {"pos_m": [p[0], p[1], top_z + h / 2], "yaw_deg": float(np.degrees(p[2]))},
                                 "box2": {"pos_m": [*PARK, top_z + h / 2], "yaw_deg": 0.0},
                                 "iou": 1 - v, "boxes": {"box1": "D"}}
        # overlay
        setp(p)
        big.d.qpos[:] = d.qpos
        mujoco.mj_forward(big.m, big.d)
        big.r.update_scene(big.d, camera=big.cam)
        rgb = big.r.render()
        real_img = (ds[a0]["observation.images.top"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
        cv2.imwrite(str(ROOT / f"outputs/sim_calib/boxes_ep{ep:03d}.jpg"),
                    cv2.cvtColor(np.concatenate([real_img, rgb, (0.5 * real_img + 0.5 * rgb).astype(np.uint8)], 1),
                                 cv2.COLOR_RGB2BGR))
    params["box_starts"] = starts
    # default positions in the scene file = the stacked start of ep 0
    if "ep0" in starts:
        for n in ("box1", "box2"):
            params["boxes"][n]["pos_m"] = starts["ep0"][n]["pos_m"]
            params["boxes"][n]["yaw_deg"] = starts["ep0"][n]["yaw_deg"]
    PARAMS.write_text(json.dumps(params, indent=2))


if __name__ == "__main__":
    main()
