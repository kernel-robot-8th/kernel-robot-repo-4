"""Top camera of the 10/27 workspace: fit pose + FOV to the arm silhouette in omx_1027_jihyeok_train8 (eps 0, 3, 6).

Two fits: position fixed at the tape measurement (17, -28, 64 cm) and all 7 parameters free; the free fit
is kept (IoU 0.639 vs 0.495). Writes outputs/sim_calib/top1027.json and overlays top1027_{fixed,free}.jpg;
calib/top_camera_1027.json was made from that json. Takes ~40 min on CPU rendering.

  python -I sim/fit_top_camera_1027.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "sim")
Path("outputs/sim_calib").mkdir(parents=True, exist_ok=True)
import cv2, numpy as np
from calibrate_top_camera import Sim, nelder_mead, W, H
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset("local/x", root="data/omx_1027_jihyeok_train8")
samples = []
for ep in (0, 3, 6):
    e = ds.meta.episodes[ep]; a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
    idx = np.linspace(a, b - 1, 60).astype(int)
    fr = [(ds[i]["observation.images.top"].permute(1, 2, 0).numpy() * 255).astype(np.uint8) for i in idx]
    st = [ds[i]["observation.state"].numpy() for i in idx]
    hsv = [cv2.cvtColor(f, cv2.COLOR_RGB2HSV) for f in fr]
    bg = np.median(np.stack([h[..., 2] for h in hsv]), 0)
    bright = cv2.erode((bg > 150).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    dark = [(h[..., 2] < 80) & bright for h in hsv]
    for k in sorted(np.argsort([-m.sum() for m in dark])[:10]):
        samples.append((fr[k], st[k], bright, dark[k]))
sim = Sim()
small = lambda m: cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
real = [(small(dk), small(br), st) for _, st, br, dk in samples]
def iou(p):
    sim.set_cam(p); v = []
    for rm, br, st in real:
        sm = sim.arm_mask(st) & br; v.append((sm & rm).sum() / max((sm | rm).sum(), 1))
    return float(np.mean(v))
POS = [0.17, -0.28, 0.64]
res = {}
for mode in ("fixed", "free"):
    best = None
    for fovy in (40, 55, 70):
        for pitch in (-0.4, 0.0, 0.4):
            for roll in (-0.4, 0.0, 0.4):
                if mode == "fixed":
                    f = lambda q: (2.0 if not 5 < q[3] < 140 else 1 - iou(POS + list(q)))
                    q0, st = [np.pi / 2, pitch, roll, fovy], [0.15, 0.15, 0.15, 8]
                else:
                    f = lambda q: (2.0 if not (5 < q[6] < 140 and q[2] > 0.1) else 1 - iou(list(q)))
                    q0, st = POS + [np.pi / 2, pitch, roll, fovy], [0.04, 0.04, 0.06, 0.15, 0.15, 0.15, 8]
                q, v = nelder_mead(f, q0, st, iters=150)
                if best is None or v < best[1]: best = (q, v)
    q, v = best
    q, v = nelder_mead(f, q, [s / 4 for s in st], iters=300)
    p = (POS + list(q)) if mode == "fixed" else list(q)
    res[mode] = {"pos_cm": np.round(np.array(p[:3]) * 100, 1).tolist(), "ypr_deg": np.round(np.degrees(p[3:6]), 1).tolist(),
                 "fovy": round(p[6], 1), "iou": round(1 - v, 3), "p": [float(x) for x in p]}
    print(mode, {k: v for k, v in res[mode].items() if k != "p"}, flush=True)
json.dump(res, open("outputs/sim_calib/top1027.json", "w"), indent=1)
big = Sim(640, 480)
for mode in ("fixed", "free"):
    big.set_cam(res[mode]["p"]); rows = []
    for f, st, _, _ in samples[::6][:4]:
        ov = f.copy(); cn, _ = cv2.findContours(big.arm_mask(st).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(ov, cn, -1, (0, 255, 0), 2); rows.append(cv2.resize(ov, (320, 240)))
    cv2.imwrite(f"outputs/sim_calib/top1027_{mode}.jpg", cv2.cvtColor(np.concatenate(rows, 1), cv2.COLOR_RGB2BGR))
