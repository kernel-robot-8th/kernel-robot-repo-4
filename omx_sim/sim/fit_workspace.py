"""With the fitted top camera (calibrate_top_camera.py), fit the box table and the Pinky disk of the
workspace scene to the real top video: their silhouettes in the static background (median of an
episode's frames) are matched by adjusting position / size / height (Nelder-Mead, IoU), starting from
the user's measurements. Prints fitted vs. measured values and writes the result next to the camera.

  python -I sim/fit_workspace.py --episode 10 --out outputs/sim_calib
"""

import argparse
import json
from pathlib import Path

import cv2
import mujoco
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # run with python -I: add sim/ explicitly
from calibrate_top_camera import Sim, cam_params, nelder_mead  # noqa: E402

W, H = 320, 240


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/omx_1024_test_jihyeok_success")
    ap.add_argument("--episode", type=int, default=10)
    ap.add_argument("--out", default="outputs/sim_calib")
    args = ap.parse_args()
    out = Path(args.out)
    cam = json.loads((out / "top_camera.json").read_text())
    p_cam = list(cam["pos_m"]) + list(np.radians(cam["yaw_pitch_roll_deg"])) + [cam["fovy_deg"]]

    ds = LeRobotDataset("local/" + Path(args.root).name, root=args.root)
    e = ds.meta.episodes[args.episode]
    a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
    frames = [(ds[i]["observation.images.top"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
              for i in np.linspace(a, b - 1, 40).astype(int)]
    bg = np.median(np.stack(frames), 0).astype(np.uint8)
    hsv = cv2.cvtColor(cv2.resize(bg, (W, H)), cv2.COLOR_RGB2HSV)
    bright = (hsv[..., 2] > 150) & (hsv[..., 1] < 60)
    bright = cv2.morphologyEx(bright.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)
    n, lab, st, _ = cv2.connectedComponentsWithStats(bright.astype(np.uint8))
    comps = sorted(range(1, n), key=lambda i: -st[i, cv2.CC_STAT_AREA])
    table_real = lab == comps[0]                                   # the largest white region
    disk_real = np.zeros_like(table_real)                          # white region touching the left border
    for i in comps[1:]:
        if st[i, cv2.CC_STAT_LEFT] <= 2 and st[i, cv2.CC_STAT_AREA] > 300:
            disk_real = lab == i
            break

    sim = Sim(W, H)
    sim.set_cam(p_cam)
    m = sim.m
    g_table = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "table")
    g_disk = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "pinky_disk")
    b_pinky = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pinky")
    sim.pose(np.zeros(6) + np.array([0, 0, 0, 0, 0, 50]))
    floor_z = -0.07

    def seg(gid):
        opt = mujoco.MjvOption()
        opt.geomgroup[:] = 0
        opt.geomgroup[1] = 1
        sim.r.enable_segmentation_rendering()
        sim.r.update_scene(sim.d, camera=sim.cam, scene_option=opt)
        s = sim.r.render()
        sim.r.disable_segmentation_rendering()
        return (s[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & (s[..., 0] == gid)

    def set_table(p):
        x0, x1, y0, y1, top = p
        m.geom_size[g_table] = [abs(x1 - x0) / 2, abs(y1 - y0) / 2, (top - floor_z) / 2]
        m.geom_pos[g_table] = [(x0 + x1) / 2, (y0 + y1) / 2, (top + floor_z) / 2]
        mujoco.mj_forward(m, sim.d)

    def set_disk(p):
        x, y, top = p
        m.body_pos[b_pinky] = [x, y, 0]
        m.geom_pos[g_disk] = [0, 0, top - 0.01]
        mujoco.mj_forward(m, sim.d)

    def iou(a_, b_):
        return (a_ & b_).sum() / max((a_ | b_).sum(), 1)

    meas_table = [0.05, 0.25, -0.10, 0.10, 0.20]  # x near, x far (depth unknown), y right, y left, top z

    pos, quat, fovy = cam_params(p_cam)
    Rc = np.zeros(9)
    mujoco.mju_quat2Mat(Rc, quat)
    Rc = Rc.reshape(3, 3)
    f = (H / 2) / np.tan(np.radians(fovy) / 2)

    def project(P):
        c = (np.asarray(P) - pos) @ Rc  # camera coords (x right, y up, looking along -z)
        return np.stack([W / 2 + f * c[:, 0] / -c[:, 2], H / 2 - f * c[:, 1] / -c[:, 2]], 1)

    def top_face_mask(p):
        x0, x1, y0, y1, top = p
        uv = project([[x0, y0, top], [x1, y0, top], [x1, y1, top], [x0, y1, top]])
        return cv2.fillPoly(np.zeros((H, W), np.uint8), [np.round(uv).astype(np.int32)], 1).astype(bool)

    def loss_table(p):
        # only the top face is compared: the front face of the white box is darker in the video and is
        # not part of the bright region (comparing the whole box turned it into a tall tower)
        if p[1] <= p[0] + 0.02 or p[3] <= p[2] + 0.02:
            return 2.0
        return 1 - iou(top_face_mask(p), table_real)

    best = None
    for top in (0.05, 0.12, 0.20, 0.28):
        p0 = list(meas_table[:4]) + [top]
        p, v = nelder_mead(loss_table, p0, [0.03, 0.05, 0.03, 0.03, 0.04], iters=400)
        print(f"table start top={top}: IoU {1 - v:.3f} {np.round(p, 3).tolist()}", flush=True)
        if best is None or v < best[1]:
            best = (p, v)
    pt, vt = best
    set_table(pt)

    meas_disk = [0.07, 0.20, 0.10]

    def loss_disk(p):
        set_disk(p)
        return 1 - iou(seg(g_disk), disk_real)

    pd_, vd = nelder_mead(loss_disk, meas_disk, [0.03, 0.03, 0.04], iters=300) if disk_real.any() else (meas_disk, 1.0)
    set_disk(pd_)

    res = {
        "table": {"fitted": {"x_near": pt[0], "x_far": pt[1], "y_right": pt[2], "y_left": pt[3], "top_z": pt[4],
                             "iou": 1 - vt},
                  "measured": {"x_near": 0.05, "x_far": "?", "y_right": -0.10, "y_left": 0.10, "top_z": 0.20}},
        "pinky_disk": {"fitted": {"x": pd_[0], "y": pd_[1], "top_z": pd_[2], "iou": 1 - vd},
                       "measured": {"x": 0.07, "y": 0.20, "top_z": 0.10}},
        "camera": cam,
    }
    (out / "workspace_fit.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res["table"], indent=1), json.dumps(res["pinky_disk"], indent=1))

    # comparison image: real background | sim (fitted) | overlay of outlines
    big = Sim(640, 480)
    big.set_cam(p_cam)
    big.m.geom_size[g_table], big.m.geom_pos[g_table] = m.geom_size[g_table], m.geom_pos[g_table]
    big.m.body_pos[b_pinky], big.m.geom_pos[g_disk] = m.body_pos[b_pinky], m.geom_pos[g_disk]
    st0 = ds[a]["observation.state"].numpy()
    rgb = big.rgb(st0)
    ov = bg.copy()
    for real_mask, col in ((table_real, (0, 255, 0)), (disk_real, (255, 255, 0))):
        cnts, _ = cv2.findContours(cv2.resize(real_mask.astype(np.uint8), (640, 480)), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(ov, cnts, -1, col, 2)
    cv2.imwrite(str(out / "workspace_fit.jpg"),
                cv2.cvtColor(np.concatenate([ov, rgb, (0.5 * bg + 0.5 * rgb).astype(np.uint8)], 1), cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
