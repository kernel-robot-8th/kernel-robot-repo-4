"""Fit the top and wrist cameras with the workspace geometry pinned by kinematics (anchor_kinematics.py).

Fixed: box start positions (all episodes), table top height, Pinky disk centre/height, box edge 4 cm.
1) top camera (x, y, z, yaw, pitch, roll, fovy) + table outline in x/y + box yaw (ep 0, ep 10):
   IoU of the arm silhouette (20 frames), the table top face, the boxes of the first frame (A on B in
   ep 0, D in ep 10) and Pinky's disk
2) wrist camera on end_effector_link (x, y, z, yaw, pitch, roll, fovy): IoU of the first box and of
   the white table top in the wrist view while approaching the first box (eps 0, 3, 10, 12)
Earlier image-only fits (calibrate_top_camera.py / fit_workspace.py / calibrate_joint.py) could trade the
camera height against the table height; with the kinematic anchors that ambiguity is gone.

  python -I sim/calibrate_cameras.py      -> scene_params.json, outputs/sim_calib/cameras_*.jpg
"""

import json
import sys
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import cam_params, nelder_mead, rot, to_qpos  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
SCENE = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx/workspace_scene.xml"
W, H = 160, 120
GEOM = mujoco.mjtObj.mjOBJ_GEOM


def load_masks(path):
    z = np.load(path)
    shape = tuple(z["_shape"])
    return {k: np.unpackbits(z[k], axis=-1)[..., : shape[-1]].astype(bool) for k in z.files if k != "_shape"}


def small(m):
    return cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)


def iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


class Scene:
    def __init__(self, P, w=W, h=H):
        self.P = P
        self.m = mujoco.MjModel.from_xml_path(str(SCENE))
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, h, w)
        n2 = lambda t, n: mujoco.mj_name2id(self.m, t, n)  # noqa: E731
        self.cam = {c: n2(mujoco.mjtObj.mjOBJ_CAMERA, c) for c in ("top", "wrist")}
        self.g = {n: n2(GEOM, n) for n in ("box1", "box2", "table", "pinky_disk")}
        self.adr = {n: self.m.jnt_qposadr[self.m.body_jntadr[n2(mujoco.mjtObj.mjOBJ_BODY, n)]] for n in ("box1", "box2")}
        bodies = {n2(mujoco.mjtObj.mjOBJ_BODY, f"link{i}") for i in range(8)} | {n2(mujoco.mjtObj.mjOBJ_BODY, "end_effector_link")}
        self.robot = np.array([g for g in range(self.m.ngeom) if self.m.geom_bodyid[g] in bodies])
        for n in ("box1", "box2"):
            self.m.geom_size[self.g[n]] = [P["boxes"][n]["size_m"] / 2] * 3

    def set_top(self, p):
        pos, q, fovy = cam_params(p)
        c = self.cam["top"]
        self.m.cam_pos[c], self.m.cam_quat[c], self.m.cam_fovy[c] = pos, q, fovy

    def set_wrist(self, p):
        R = rot(*p[3:6]) @ np.array(self.P["wrist_camera"]["base_axes"], float).T
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, R.reshape(-1))
        c = self.cam["wrist"]
        self.m.cam_pos[c], self.m.cam_quat[c], self.m.cam_fovy[c] = p[:3], q, p[6]

    def set_table(self, x0, x1, y0, y1):
        top, fz = self.P["table"]["top_z"], self.P["floor_z"]
        self.m.geom_size[self.g["table"]] = [(x1 - x0) / 2, (y1 - y0) / 2, (top - fz) / 2]
        self.m.geom_pos[self.g["table"]] = [(x0 + x1) / 2, (y0 + y1) / 2, (top + fz) / 2]

    def set_episode(self, ep, state, yaw=0.0):
        st = self.P["box_starts"][f"ep{ep}"]
        for n in ("box1", "box2"):
            a = self.adr[n]
            self.d.qpos[a:a + 3] = st[n]["pos_m"]
            self.d.qpos[a + 3:a + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        self.d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(self.m, self.d)

    def seg(self, cam, hide_world=False):
        opt = mujoco.MjvOption()
        if hide_world:
            opt.geomgroup[1] = 0
        self.r.enable_segmentation_rendering()
        self.r.update_scene(self.d, camera=self.cam[cam], scene_option=opt)
        s = self.r.render()
        self.r.disable_segmentation_rendering()
        return s

    def mask(self, s, name):
        return (s[..., 1] == GEOM) & (s[..., 0] == self.g[name])

    def rgb(self, cam):
        self.r.update_scene(self.d, camera=self.cam[cam])
        return self.r.render()


def main():
    P = json.loads(PARAMS.read_text())
    ds = LeRobotDataset("local/omx_1024_test_jihyeok_success", root=ROOT / "data/omx_1024_test_jihyeok_success")
    rng = lambda ep: (int(ds.meta.episodes[ep]["dataset_from_index"]), int(ds.meta.episodes[ep]["dataset_to_index"]))  # noqa: E731
    img = lambda i, cam: (ds[i][f"observation.images.{cam}"].permute(1, 2, 0).numpy() * 255).astype(np.uint8)  # noqa: E731
    state = lambda i: ds[i]["observation.state"].numpy()  # noqa: E731

    # ---------------- top camera targets
    arm, firsts = [], {}
    for ep in (0, 10):
        a, b = rng(ep)
        idx = np.linspace(a, b - 1, 60).astype(int)
        fr = [img(i, "top") for i in idx]
        v = [cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2] for f in fr]
        bright = cv2.erode((np.median(np.stack(v), 0) > 150).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        dark = [(x < 80) & bright for x in v]
        for k in sorted(np.argsort([-m_.sum() for m_ in dark])[:10]):
            arm.append((small(dark[k]), small(bright), state(idx[k])))
        firsts[ep] = (state(a), np.median(np.stack(fr), 0).astype(np.uint8))
    hsv = cv2.cvtColor(cv2.resize(firsts[10][1], (W, H)), cv2.COLOR_RGB2HSV)
    br = cv2.morphologyEx(((hsv[..., 2] > 150) & (hsv[..., 1] < 60)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, sts, _ = cv2.connectedComponentsWithStats(br)
    comps = sorted(range(1, n), key=lambda i: -sts[i, cv2.CC_STAT_AREA])
    table_real = lab == comps[0]
    disk_real = next((lab == i for i in comps[1:] if sts[i, cv2.CC_STAT_LEFT] <= 1 and sts[i, cv2.CC_STAT_AREA] > 80),
                     np.zeros_like(table_real))
    mk0 = load_masks(ROOT / "data/aug_test/work/ep000/top_masks.npz")
    mk10 = load_masks(ROOT / "data/aug_test/work/ep010/top_masks.npz")
    boxes_real = {0: {"box1": small(mk0["A"][0]), "box2": small(mk0["B"][0])}, 10: {"box1": small(mk10["D"][0])}}

    sc = Scene(P)
    tc, t = P["top_camera"], P["table"]
    x_top = np.array(list(tc["pos_m"]) + list(np.radians(tc["yaw_pitch_roll_deg"])) + [tc["fovy_deg"]]
                     + [t["x_near"], t["x_far"], t["y_right"], t["y_left"], 0.3, 0.0])
    st_top = np.array([0.03, 0.03, 0.05, 0.05, 0.08, 0.05, 4, 0.02, 0.02, 0.02, 0.02, 0.15, 0.15])

    def top_face_mask(pc, x0, x1, y0, y1):
        pos, quat, fovy = cam_params(pc)
        Rc = np.zeros(9)
        mujoco.mju_quat2Mat(Rc, quat)
        z = P["table"]["top_z"]
        c = (np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]]) - pos) @ Rc.reshape(3, 3)
        if (c[:, 2] > -0.01).any():
            return np.zeros((H, W), bool)
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        uv = np.stack([W / 2 + f * c[:, 0] / -c[:, 2], H / 2 - f * c[:, 1] / -c[:, 2]], 1)
        return cv2.fillPoly(np.zeros((H, W), np.uint8), [np.round(uv).astype(np.int32)], 1).astype(bool)

    def loss_top(p, detail=False):
        if not (10 < p[6] < 120 and p[2] > 0.2 and p[8] > p[7] + 0.05 and p[10] > p[9] + 0.05):
            return 2.0
        sc.set_top(p[:7])
        sc.set_table(*p[7:11])
        ia = []
        for rm, bright, st in arm:
            sc.set_episode(10, st)
            s = sc.seg("top", hide_world=True)
            ia.append(iou((s[..., 1] == GEOM) & np.isin(s[..., 0], sc.robot) & bright, rm))
        sc.set_episode(0, firsts[0][0], p[11])
        s = sc.seg("top")
        ib0 = np.mean([iou(sc.mask(s, k), boxes_real[0][k]) for k in ("box1", "box2")])
        sc.set_episode(10, firsts[10][0], p[12])
        s = sc.seg("top")
        ib10 = iou(sc.mask(s, "box1"), boxes_real[10]["box1"])
        # table: only the projected top face (the darker front face is not in the bright region); the box
        # standing on it is part of the bright region's outline
        it = iou(top_face_mask(p[:7], *p[7:11]), table_real | boxes_real[10]["box1"])
        idk = iou(sc.mask(s, "pinky_disk"), disk_real)
        parts = (float(np.mean(ia)), it, ib0, ib10, idk)
        return parts if detail else 1 - float(np.mean(parts))

    print("top start  arm/table/stack/box10/disk:", np.round(loss_top(x_top, True), 3), flush=True)
    best = (x_top, loss_top(x_top))
    for dz in (-0.1, 0.0, 0.1):  # a few restarts in camera height / tilt
        for dp in (-0.2, 0.0, 0.2):
            q = best[0].copy() if (dz, dp) == (0.0, 0.0) else x_top.copy()
            q[2] += dz
            q[4] += dp
            p, v = nelder_mead(loss_top, q, st_top, iters=500)
            if v < best[1]:
                best = (p, v)
    p, v = nelder_mead(loss_top, best[0], st_top / 3, iters=1000, tol=1e-6)
    parts = loss_top(p, True)
    print("top fitted arm/table/stack/box10/disk:", np.round(parts, 3), np.round(p, 3).tolist(), flush=True)
    P["top_camera"] = {"pos_m": list(p[:3]), "yaw_pitch_roll_deg": list(np.degrees(p[3:6])), "fovy_deg": float(p[6]),
                       "source": "calibrate_cameras.py with kinematic anchors; IoU arm %.3f table %.3f boxes %.3f/%.3f disk %.3f" % parts}
    P["table"].update({"x_near": p[7], "x_far": p[8], "y_right": p[9], "y_left": p[10]})
    for ep, yaw in ((0, p[11]), (10, p[12])):
        for n in ("box1", "box2"):
            P["box_starts"][f"ep{ep}"][n]["yaw_deg"] = float(np.degrees(yaw))
    sc.set_top(p[:7])
    sc.set_table(*p[7:11])
    top_p = p

    # ---------------- wrist camera
    wrist = []
    for ep, key in ((0, "A"), (3, "A"), (10, "D"), (12, "D")):
        a, b = rng(ep)
        g = np.array([ds.hf_dataset[i]["action"][5] for i in range(a, b)])
        close = int(np.argmax(g < (np.percentile(g, 90) + g.min()) / 2))
        mk = load_masks(ROOT / f"data/aug_test/work/ep{ep:03d}/wrist_masks.npz")[key]
        cand = [t_ for t_ in range(close - 10) if 0.03 < mk[t_].mean() < 0.6]
        for t_ in np.array(cand)[np.linspace(0, len(cand) - 1, min(5, len(cand))).astype(int)]:
            im = img(a + int(t_), "wrist")
            hsv = cv2.cvtColor(cv2.resize(im, (W, H)), cv2.COLOR_RGB2HSV)
            white = (hsv[..., 2] > 170) & (hsv[..., 1] < 40) & ~small(mk[t_])
            wrist.append((ep, state(a + int(t_)), small(mk[t_]), white, im))
    print(f"{len(wrist)} wrist frames", flush=True)
    wc = P["wrist_camera"]
    x_w = np.array(list(wc["pos_m"]) + list(np.radians(wc["yaw_pitch_roll_deg"])) + [wc["fovy_deg"]])

    def loss_w(p, detail=False):
        if not 20 < p[6] < 150:
            return 2.0
        sc.set_wrist(p)
        ib, iw = [], []
        for ep, st, bm, wm, _ in wrist:
            yaw = np.radians(P["box_starts"].get(f"ep{ep}", {}).get("box1", {}).get("yaw_deg", 0.0))
            sc.set_episode(ep, st, yaw)
            s = sc.seg("wrist")
            ib.append(iou(sc.mask(s, "box1"), bm))
            iw.append(iou(sc.mask(s, "table"), wm))
        parts = (float(np.mean(ib)), float(np.mean(iw)))
        return parts if detail else 1 - float(np.mean(parts))

    best = (x_w, loss_w(x_w))
    for fovy in (50, 70, 90):
        for pitch in (0.0, 0.35, 0.7):
            for z in (0.02, 0.05, 0.08):
                q = np.array([-0.05, 0.0, z, 0.0, pitch, 0.0, fovy])
                v = loss_w(q)
                if v < best[1]:
                    best = (q, v)
    print("wrist grid", np.round(loss_w(best[0], True), 3), flush=True)
    p, v = nelder_mead(loss_w, best[0], [0.02, 0.02, 0.02, 0.1, 0.1, 0.1, 8], iters=800)
    p, v = nelder_mead(loss_w, p, [0.005, 0.005, 0.005, 0.03, 0.03, 0.03, 2], iters=800, tol=1e-6)
    parts_w = loss_w(p, True)
    print("wrist fitted box/table:", np.round(parts_w, 3), np.round(p, 4).tolist(), flush=True)
    P["wrist_camera"] = {"pos_m": list(p[:3]), "yaw_pitch_roll_deg": list(np.degrees(p[3:6])), "fovy_deg": float(p[6]),
                         "base_axes": wc["base_axes"],
                         "source": "calibrate_cameras.py with kinematic anchors; IoU box %.3f table %.3f; "
                                   "pinhole approximation of a wide-angle lens" % parts_w}
    PARAMS.write_text(json.dumps(P, indent=2))

    # ---------------- overlays
    big = Scene(P, 640, 480)
    big.set_top(top_p[:7])
    big.set_table(*top_p[7:11])
    big.set_wrist(p)
    rows = []
    for ep in (0, 10):
        big.set_episode(ep, firsts[ep][0], np.radians(P["box_starts"][f"ep{ep}"]["box1"]["yaw_deg"]))
        real = img(rng(ep)[0], "top")
        sim = big.rgb("top")
        rows.append(np.concatenate([real, sim, (0.5 * real + 0.5 * sim).astype(np.uint8)], 1))
    for ep, st, _, _, im in wrist[::5][:4]:
        big.set_episode(ep, st, np.radians(P["box_starts"][f"ep{ep}"]["box1"]["yaw_deg"]))
        sim = big.rgb("wrist")
        rows.append(np.concatenate([im, sim, (0.5 * im + 0.5 * sim).astype(np.uint8)], 1))
    out = ROOT / "outputs/sim_calib"
    cv2.imwrite(str(out / "cameras_fit.jpg"), cv2.cvtColor(np.concatenate(rows, 0)[::2, ::2], cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
