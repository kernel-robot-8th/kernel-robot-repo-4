"""Scene parameters of the 10/27 workspace (omx_1027_jihyeok_train8 / eval1) -> sim/calib/scene_params_1027.json.

Sources (the user chose "video values" where tape and recording disagreed):
  tape (2026-10-28): stand 8 cm high, 27 x 20 cm (27 assumed along y); table x 17..44.5, y -15..15 cm;
      Pinky disk centre (7, 20) cm, diameter 11.5, thickness 1.5; box 6 x 6 x 4 cm, 10 g
  kinematics: box start of every episode = gripper tip at grasp; table top = median box centre - 2 cm
      (tape said 30 cm above the floor = 22 above the base; the grasps put it ~6.5 cm lower)
  kinematics: Pinky disk centre ~ gripper tip at release (the box is dropped over the disk; tape said (7, 20))
  top video: top camera pose / FOV (fit_top_camera_1027.py -> calib/top_camera_1027.json; the tape lens
      position (17, -28, 64) fitted clearly worse), Pinky disk centre / height (silhouette of the white disk,
      searched around the release point)
  unchanged: wrist camera (same OMX-AI mount) from calib/scene_params.json

  python -I sim/fit_env_1027.py && python -I sim/build_scene.py --params sim/calib/scene_params_1027.json
"""

import json
import sys
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import cam_params, to_qpos  # noqa: E402
from replay_episode import grasps  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CALIB = ROOT / "sim/calib"
OMX = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx"
DATASET = "data/omx_1027_jihyeok_train8"
SETTLE = 5  # frames after the gripper command closes (fingers reach the box)
BOX = [0.06, 0.06, 0.04]
W, H = 320, 240


def disk_xml(P):
    pk = P["pinky"]
    return f'''<mujoco><include file="omx.xml"/><worldbody>
  <body name="disk" mocap="true">  <!-- mocap: geoms of the world body are not re-posed by mj_forward -->
    <geom name="disk" group="1" type="cylinder" size="{pk["disk_radius"]} {pk["disk_half_height"]}"/>
  </body>
  <camera name="top" pos="0 0 1"/></worldbody></mujoco>'''


def fit_disk(P, ds, x0, y0):
    """White disk seen by the top camera: real = bright, unsaturated blob in the median frame of ep 0.
    Grid search of the disk centre (+-5 cm around x0, y0) and top height (0..20 cm), best IoU wins."""
    e = ds.meta.episodes[0]
    idx = np.linspace(int(e["dataset_from_index"]), int(e["dataset_to_index"]) - 1, 40).astype(int)
    hsv = np.median(np.stack([cv2.cvtColor((ds[i]["observation.images.top"].permute(1, 2, 0).numpy() * 255)
                                           .astype(np.uint8), cv2.COLOR_RGB2HSV) for i in idx]), 0)
    bright = cv2.resize(((hsv[..., 2] > 170) & (hsv[..., 1] < 50)).astype(np.uint8), (W, H),
                        interpolation=cv2.INTER_NEAREST)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))  # cut the white floor tape
    n, lab = cv2.connectedComponents(bright)
    path = OMX / "_disk_fit.xml"
    path.write_text(disk_xml(P))
    m = mujoco.MjModel.from_xml_path(str(path))
    path.unlink()
    m.cam_pos[0], m.cam_quat[0], m.cam_fovy[0] = cam_params(P["top_camera"]["_p"])
    d = mujoco.MjData(m)
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "disk")
    r = mujoco.Renderer(m, H, W)
    r.enable_segmentation_rendering()
    opt = mujoco.MjvOption()
    opt.geomgroup[2] = opt.geomgroup[3] = 0
    best = None
    for x in x0 + np.arange(-0.05, 0.0501, 0.005):
        for y in y0 + np.arange(-0.05, 0.0501, 0.005):
            for z in np.arange(0.0, 0.2001, 0.005):
                d.mocap_pos[0] = [x, y, z - P["pinky"]["disk_half_height"]]
                mujoco.mj_forward(m, d)
                r.update_scene(d, camera=0, scene_option=opt)
                sim = r.render()[..., 0] == g
                ids = np.unique(lab[sim & (lab > 0)])
                real = np.isin(lab, ids) if len(ids) else np.zeros_like(sim)
                iou = (sim & real).sum() / max((sim | real).sum(), 1)
                if best is None or iou > best[3]:
                    best = (float(x), float(y), float(z), float(iou))
    return best


def main():
    old = json.loads((CALIB / "scene_params.json").read_text())
    tc = json.loads((CALIB / "top_camera_1027.json").read_text())
    m = mujoco.MjModel.from_xml_path(str(OMX / "omx.xml"))
    d = mujoco.MjData(m)
    ee = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "end_effector_link")
    ds = LeRobotDataset("local/" + Path(DATASET).name, root=ROOT / DATASET)

    def tip(state):
        d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(m, d)
        return d.xpos[ee].copy()

    grabs, releases = {}, []
    for ep in range(ds.meta.total_episodes):
        e = ds.meta.episodes[ep]
        rows = ds.hf_dataset.select(range(int(e["dataset_from_index"]), int(e["dataset_to_index"])))
        st = np.stack([np.asarray(x) for x in rows["observation.state"]])
        c, o = grasps(np.stack([np.asarray(x) for x in rows["action"]]))[0]
        grabs[ep] = tip(st[min(c + SETTLE, len(st) - 1)])
        releases.append(tip(st[o]))
    top = float(np.median([g[2] for g in grabs.values()]) - BOX[2] / 2)
    print(f"box centre z at grasp: {[round(g[2] * 100, 1) for g in grabs.values()]} cm -> table top {top * 100:.1f} cm")

    P = {
        "_doc": "10/27 workspace (sim/fit_env_1027.py). Metres, degrees. Frame: robot base bottom centre, "
                "x forward, y left, z up.",
        "dataset": DATASET,
        "scene_file": "workspace_scene_1027.xml",
        "floor_z": -0.08,
        "stand_size_m": [0.20, 0.27],
        "stand_rgba": [0.82, 0.66, 0.46, 1],
        "top_camera": {k: tc[k] for k in ("pos_m", "yaw_pitch_roll_deg", "fovy_deg")} | {
            "source": f"fit_top_camera_1027.py, arm silhouette IoU {tc['mean_iou']:.3f} "
                      f"(tape lens position {tc['tape_pos_m']} fitted IoU {tc['tape_iou']:.3f})"},
        "table": {"x_near": 0.17, "x_far": 0.445, "y_right": -0.15, "y_left": 0.15, "top_z": top,
                  "source": "x/y tape; top_z from kinematics (box centre at grasp - 2 cm); tape said 0.22"},
        "pinky": {"x": 0.07, "y": 0.20, "disk_top_z": None, "disk_radius": 0.0575, "disk_half_height": 0.0075,
                  "body_size_m": old["pinky"]["body_size_m"]},
        "boxes": {"box1": {"pos_m": None, "yaw_deg": 0.0, "size_m": BOX, "mass_kg": 0.01,
                           "rgba": [0.85, 0.4, 0.38, 1]}},
        "wrist_camera": old["wrist_camera"],
    }
    P["top_camera"]["_p"] = tc["_p"]
    rel = np.median(np.stack(releases), 0)
    print(f"release (box dropped over Pinky): {np.round(rel * 100, 1).tolist()} cm")
    x, y, z, iou = fit_disk(P, ds, rel[0], rel[1])
    del P["top_camera"]["_p"]
    P["pinky"].update({"x": x, "y": y, "disk_top_z": z, "source": (
        f"diameter / thickness tape; centre and top height from the top video (disk IoU {iou:.3f}) around the "
        f"release point {np.round(rel[:2] * 100, 1).tolist()} cm; tape said centre (7, 20), top 0.032; "
        "body size from the 10/24 scene")})
    print(f"Pinky disk: centre ({x * 100:.1f}, {y * 100:.1f}) cm, top {z * 100:.1f} cm (IoU {iou:.3f})")
    P["box_starts"] = {f"ep{ep}": {"box1": {"pos_m": [float(g[0]), float(g[1]), top + BOX[2] / 2], "yaw_deg": 0.0},
                                   "boxes": {"box1": "heart box"},
                                   "source": "gripper tip (forward kinematics) at grasp"}
                       for ep, g in grabs.items()}
    P["boxes"]["box1"]["pos_m"] = P["box_starts"]["ep0"]["box1"]["pos_m"]
    (CALIB / "scene_params_1027.json").write_text(json.dumps(P, indent=2))
    print("wrote", CALIB / "scene_params_1027.json")


if __name__ == "__main__":
    main()
