"""Joint fit of the top camera, the box table and the boxes to the recorded top video.

Fitting the camera to the arm alone left a tilt/position trade-off (boxes then showed far too much of
their sides). Here one set of parameters must explain at the same time
  - the arm silhouette in 20 frames (ep 0 and 10; joint angles recorded -> known shape and scale)
  - the white top face of the table (static background of ep 10)
  - the box masks of the first frame: A stacked on B (ep 0) and D (ep 10), cubes of edge s
  - wrist camera (--wrist): the box and the white table top seen from the wrist camera while
    approaching the first box (box still at its start position)
Parameters: top camera (x, y, z, yaw, pitch, roll, fovy), table top (x near/far, y right/left, z),
box edge s, ep 0 stack (x, y, yaw of B; A shares x, y), ep 10 box (x, y, yaw)
[, wrist camera on end_effector_link (x, y, z, yaw, pitch, roll, fovy)].
Loss = 1 - mean IoU of the groups. Nelder-Mead from the previous fits.

  python -I sim/calibrate_joint.py   -> updates sim/calib/scene_params.json, outputs/sim_calib/joint_*.jpg
"""

import json
import sys
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import Sim, cam_params, nelder_mead, rot, to_qpos  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
W, H = 160, 120
PARK = [0.6, -0.6, 0.0]


def load_masks(path):
    z = np.load(path)
    shape = tuple(z["_shape"])
    return {k: np.unpackbits(z[k], axis=-1)[..., : shape[-1]].astype(bool) for k in z.files if k != "_shape"}


def small(m):
    return cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)


def iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--wrist", action="store_true")
    args = ap.parse_args()
    P = json.loads(PARAMS.read_text())
    ds = LeRobotDataset("local/omx_1024_test_jihyeok_success", root=ROOT / "data/omx_1024_test_jihyeok_success")

    def frames_of(ep, n):
        e = ds.meta.episodes[ep]
        a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
        idx = np.linspace(a, b - 1, n).astype(int)
        return ([(ds[i]["observation.images.top"].permute(1, 2, 0).numpy() * 255).astype(np.uint8) for i in idx],
                [ds[i]["observation.state"].numpy() for i in idx])

    # --- targets
    arm = []
    for ep in (0, 10):
        fr, st = frames_of(ep, 60)
        bgv = np.median(np.stack([cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2] for f in fr]), 0)
        bright = cv2.erode((bgv > 150).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        dark = [(cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2] < 80) & bright for f in fr]
        for k in sorted(np.argsort([-m.sum() for m in dark])[:10]):
            arm.append((small(dark[k]), small(bright), st[k]))
        if ep == 10:
            bg = np.median(np.stack(fr), 0).astype(np.uint8)
            hsv = cv2.cvtColor(cv2.resize(bg, (W, H)), cv2.COLOR_RGB2HSV)
            br = cv2.morphologyEx(((hsv[..., 2] > 150) & (hsv[..., 1] < 60)).astype(np.uint8), cv2.MORPH_OPEN,
                                  np.ones((3, 3), np.uint8))
            n, lab, sts, _ = cv2.connectedComponentsWithStats(br)
            table_real = lab == (1 + int(sts[1:, cv2.CC_STAT_AREA].argmax()))
    m0, m10 = (load_masks(ROOT / f"data/aug_test/work/ep{e:03d}/top_masks.npz") for e in (0, 10))
    st0 = ds[int(ds.meta.episodes[0]["dataset_from_index"])]["observation.state"].numpy()
    st10 = ds[int(ds.meta.episodes[10]["dataset_from_index"])]["observation.state"].numpy()
    boxes_real = {0: {"box1": small(m0["A"][0]), "box2": small(m0["B"][0])}, 10: {"box1": small(m10["D"][0])}}

    wrist = []  # (episode, state, box mask, table mask) from the approach to the first box
    if args.wrist:
        for ep, key in ((0, "A"), (10, "D")):
            e = ds.meta.episodes[ep]
            a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
            g = np.array([ds.hf_dataset[i]["action"][5] for i in range(a, b)])
            close = int(np.argmax(g < (np.percentile(g, 90) + g.min()) / 2))
            mk = load_masks(ROOT / f"data/aug_test/work/ep{ep:03d}/wrist_masks.npz")[key]
            cand = [t for t in range(close - 10) if 0.03 < mk[t].mean() < 0.6]
            for t in np.array(cand)[np.linspace(0, len(cand) - 1, min(6, len(cand))).astype(int)]:
                img = (ds[a + int(t)]["observation.images.wrist"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
                hsv = cv2.cvtColor(cv2.resize(img, (W, H)), cv2.COLOR_RGB2HSV)
                white = (hsv[..., 2] > 170) & (hsv[..., 1] < 40) & ~small(mk[t])
                wrist.append((ep, ds[a + int(t)]["observation.state"].numpy(), small(mk[t]), white))
        print(f"{len(wrist)} wrist frames", flush=True)

    sim = Sim(W, H)
    mdl, d = sim.m, sim.d
    gid = {n: mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_GEOM, n) for n in ("box1", "box2")}
    jadr = {n: mdl.jnt_qposadr[mdl.body_jntadr[mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_BODY, n)]] for n in gid}

    def place(name, x, y, z, yaw):
        a = jadr[name]
        d.qpos[a:a + 3] = [x, y, z]
        d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]

    def seg(hide_world=False):
        opt = mujoco.MjvOption()
        if hide_world:
            opt.geomgroup[1] = 0
        sim.r.enable_segmentation_rendering()
        sim.r.update_scene(d, camera=sim.cam, scene_option=opt)
        s = sim.r.render()
        sim.r.disable_segmentation_rendering()
        return s

    # --- parameter vector
    tc, t = P["top_camera"], P["table"]
    bs = P.get("box_starts", {})
    e0, e10 = bs.get("ep0", {}), bs.get("ep10", {})
    x0 = np.array(list(tc["pos_m"]) + list(np.radians(tc["yaw_pitch_roll_deg"])) + [tc["fovy_deg"]]
                  + [t["x_near"], t["x_far"], t["y_right"], t["y_left"], t["top_z"]] + [0.04]
                  + ([e0["box2"]["pos_m"][0], e0["box2"]["pos_m"][1], np.radians(e0["box2"]["yaw_deg"])] if e0 else [0.12, 0.0, 0.3])
                  + ([e10["box1"]["pos_m"][0], e10["box1"]["pos_m"][1], np.radians(e10["box1"]["yaw_deg"])] if e10 else [0.15, 0.0, 0.0]))
    steps = np.array([0.02, 0.02, 0.04, 0.05, 0.08, 0.05, 4, 0.02, 0.02, 0.02, 0.02, 0.03, 0.005, 0.01, 0.01, 0.1, 0.01, 0.01, 0.1])
    wc = P["wrist_camera"]
    if args.wrist:
        x0 = np.concatenate([x0, list(wc["pos_m"]) + list(np.radians(wc["yaw_pitch_roll_deg"])) + [wc["fovy_deg"]]])
        steps = np.concatenate([steps, [0.01, 0.01, 0.01, 0.05, 0.05, 0.05, 4]])
    wcam = mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_CAMERA, "wrist")
    g_table = mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_GEOM, "table")

    def unpack(p):
        return p[:7], p[7:12], p[12], p[13:16], p[16:19]

    def set_wrist(pw):
        R = rot(*pw[3:6]) @ np.array(wc["base_axes"], float).T
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, R.reshape(-1))
        mdl.cam_pos[wcam], mdl.cam_quat[wcam], mdl.cam_fovy[wcam] = pw[:3], q, pw[6]

    def set_table(tp):
        x0_, x1_, y0_, y1_, z_ = tp
        fz = P["floor_z"]
        mdl.geom_size[g_table] = [(x1_ - x0_) / 2, (y1_ - y0_) / 2, (z_ - fz) / 2]
        mdl.geom_pos[g_table] = [(x0_ + x1_) / 2, (y0_ + y1_) / 2, (z_ + fz) / 2]

    def table_mask(pc, tp):
        pos, quat, fovy = cam_params(pc)
        Rc = np.zeros(9)
        mujoco.mju_quat2Mat(Rc, quat)
        Rc = Rc.reshape(3, 3)
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        x0_, x1_, y0_, y1_, z_ = tp
        c = (np.array([[x0_, y0_, z_], [x1_, y0_, z_], [x1_, y1_, z_], [x0_, y1_, z_]]) - pos) @ Rc
        if (c[:, 2] > -0.01).any():
            return np.zeros((H, W), bool)
        uv = np.stack([W / 2 + f * c[:, 0] / -c[:, 2], H / 2 - f * c[:, 1] / -c[:, 2]], 1)
        return cv2.fillPoly(np.zeros((H, W), np.uint8), [np.round(uv).astype(np.int32)], 1).astype(bool)

    def set_size(s):
        for g in gid.values():
            mdl.geom_size[g] = [s / 2] * 3

    def loss(p, detail=False):
        pc, tp, s, b0, b10 = unpack(p)
        if not (10 < pc[6] < 120 and pc[2] > 0.15 and 0.02 < s < 0.12 and tp[1] > tp[0] + 0.05 and tp[3] > tp[2] + 0.05):
            return 2.0
        sim.set_cam(pc)
        set_size(s)
        # arm (world hidden)
        place("box1", *PARK[:2], 0, 0)
        place("box2", *PARK[:2], 0, 0)
        ia = []
        for rm, br, st in arm:
            d.qpos[:7] = to_qpos(st)
            mujoco.mj_forward(mdl, d)
            sg = seg(hide_world=True)
            sm = (sg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM) & np.isin(sg[..., 0], sim.robot_geoms) & br
            ia.append(iou(sm, rm))
        it = iou(table_mask(pc, tp), table_real)
        top = tp[4]
        # ep 0 stack
        place("box2", b0[0], b0[1], top + s / 2, b0[2])
        place("box1", b0[0], b0[1], top + 1.5 * s, b0[2])
        d.qpos[:7] = to_qpos(st0)
        mujoco.mj_forward(mdl, d)
        sg = seg()
        ib0 = np.mean([iou((sg[..., 1] == 5) & (sg[..., 0] == gid[n]), boxes_real[0][n]) for n in ("box1", "box2")])
        # ep 10 single box
        place("box1", b10[0], b10[1], top + s / 2, b10[2])
        place("box2", *PARK[:2], 0, 0)
        d.qpos[:7] = to_qpos(st10)
        mujoco.mj_forward(mdl, d)
        sg = seg()
        ib10 = iou((sg[..., 1] == 5) & (sg[..., 0] == gid["box1"]), boxes_real[10]["box1"])
        parts = (float(np.mean(ia)), it, ib0, ib10)
        if args.wrist:
            pw = p[19:26]
            if not 20 < pw[6] < 150:
                return 2.0
            set_wrist(pw)
            set_table(tp)
            iw = []
            for ep, st, bm, wm in wrist:
                if ep == 0:
                    place("box2", b0[0], b0[1], top + s / 2, b0[2])
                    place("box1", b0[0], b0[1], top + 1.5 * s, b0[2])
                else:
                    place("box1", b10[0], b10[1], top + s / 2, b10[2])
                    place("box2", *PARK[:2], 0, 0)
                d.qpos[:7] = to_qpos(st)
                mujoco.mj_forward(mdl, d)
                sim.r.enable_segmentation_rendering()
                sim.r.update_scene(d, camera=wcam)
                sg = sim.r.render()
                sim.r.disable_segmentation_rendering()
                isg = sg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM
                iw.append(0.5 * iou(isg & (sg[..., 0] == gid["box1"]), bm) + 0.5 * iou(isg & (sg[..., 0] == g_table), wm))
            parts = parts + (float(np.mean(iw)),)
        if detail:
            return parts
        return 1 - float(np.mean(parts))

    print("start  arm/table/stack/box10[/wrist] IoU:", np.round(loss(x0, True), 3), flush=True)
    p, v = nelder_mead(loss, x0, steps, iters=1500, tol=1e-5)
    p, v = nelder_mead(loss, p, steps / 3, iters=1500, tol=1e-6)
    parts = loss(p, True)
    print("fitted arm/table/stack/box10[/wrist] IoU:", np.round(parts, 3), flush=True)
    pc, tp, s, b0, b10 = unpack(p)

    P["top_camera"] = {"pos_m": list(pc[:3]), "yaw_pitch_roll_deg": list(np.degrees(pc[3:6])), "fovy_deg": float(pc[6]),
                       "source": "joint fit (sim/calibrate_joint.py): arm IoU %.3f" % parts[0]}
    P["table"] = {"x_near": tp[0], "x_far": tp[1], "y_right": tp[2], "y_left": tp[3], "top_z": tp[4],
                  "source": "joint fit: top face IoU %.3f" % parts[1]}
    for n in ("box1", "box2"):
        P["boxes"][n]["size_m"] = float(s)
    P["box_size_source"] = "joint fit (user said 0.04)"
    top = tp[4]
    P["box_starts"] = {
        "ep0": {"box2": {"pos_m": [b0[0], b0[1], top + s / 2], "yaw_deg": float(np.degrees(b0[2]))},
                "box1": {"pos_m": [b0[0], b0[1], top + 1.5 * s], "yaw_deg": float(np.degrees(b0[2]))},
                "iou": parts[2], "boxes": {"box1": "A", "box2": "B"}},
        "ep10": {"box1": {"pos_m": [b10[0], b10[1], top + s / 2], "yaw_deg": float(np.degrees(b10[2]))},
                 "box2": {"pos_m": [PARK[0], PARK[1], top + s / 2], "yaw_deg": 0.0},
                 "iou": parts[3], "boxes": {"box1": "D"}}}
    for n in ("box1", "box2"):
        P["boxes"][n]["pos_m"] = P["box_starts"]["ep0"][n]["pos_m"]
        P["boxes"][n]["yaw_deg"] = P["box_starts"]["ep0"][n]["yaw_deg"]
    if args.wrist:
        pw = p[19:26]
        P["wrist_camera"] = {"pos_m": list(pw[:3]), "yaw_pitch_roll_deg": list(np.degrees(pw[3:6])),
                             "fovy_deg": float(pw[6]), "base_axes": wc["base_axes"],
                             "source": "joint fit with the top camera (box + table top in the wrist view), IoU %.3f; "
                                       "pinhole approximation of a wide-angle lens" % parts[4]}
    PARAMS.write_text(json.dumps(P, indent=2))
    print(json.dumps({k: P[k] for k in ("top_camera", "table", "box_starts", "wrist_camera")}, indent=1))
    print("box edge", s)


if __name__ == "__main__":
    main()
