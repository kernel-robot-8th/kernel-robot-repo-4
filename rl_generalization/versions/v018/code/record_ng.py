"""Record a failed MuJoCo replay as an NG video.

This is an evidence tool only.  It records the current experimental replay and
prints the same failure metrics used by ``retarget_contact.py``; it never marks
an apparent lift as a successful grasp.
"""
import argparse
import json
from pathlib import Path

import mujoco
import numpy as np
import pyarrow.parquet as pq
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def arm(u):
    return ((np.asarray(u) + 100) / 200 * 4095 - 2048) * 2 * np.pi / 4096


def grip(g, zero):
    return (g - zero) / 100 * 4095 * 2 * np.pi / 4096


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scene", type=Path, default=ROOT / ".local/finger_proxy_v018/scene.xml")
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--shift-z", type=float, default=-0.018)
    p.add_argument("--shift-x", type=float, default=0.0349720067)
    p.add_argument("--shift-y", type=float, default=-0.0034275971)
    p.add_argument("--gripper-zero", type=float, default=46.8)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if not 0 < a.seconds <= 45:
        p.error("--seconds must be in (0,45]")

    from retarget import plan

    rows = pq.read_table(ROOT / ".local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet").to_pylist()
    rows.sort(key=lambda r: r["frame_index"])
    scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
    m = mujoco.MjModel.from_xml_path(str(scene))
    d = mujoco.MjData(m)
    rows, plan_report = plan(m, rows, a.seconds, np.array([a.shift_x, a.shift_y, a.shift_z]))
    d.qpos[:5] = arm(rows[0]["observation.state"][:5])
    g = grip(rows[0]["observation.state"][5], a.gripper_zero)
    d.qpos[5:7] = [g, -g]
    d.ctrl[:5] = d.qpos[:5]
    d.ctrl[5] = g
    mujoco.mj_forward(m, d)

    a.out.mkdir(parents=True, exist_ok=False)
    video_path = a.out / "ng_replay.mp4"
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "640x480", "-r", "30", "-i", "-", "-vf",
         "drawtext=text='NG SIMULATION ONLY':x=24:y=30:fontsize=28:fontcolor=red:box=1:boxcolor=white@0.7",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_path)], stdin=subprocess.PIPE)

    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.15, -0.07, 0.17]
    cam.distance = 0.70
    cam.azimuth = 135
    cam.elevation = -30
    renderer = mujoco.Renderer(m, height=480, width=640)
    shoes = [m.body(f"shoe{i}").id for i in range(2)]
    z0 = d.xpos[shoes, 2].copy()
    peak = np.zeros(2)
    bilateral = np.zeros(2, dtype=int)
    max_pen = 0.0
    max_pair = None
    for step in range(int(a.seconds / m.opt.timestep)):
        r = rows[min(int(d.time * 30), len(rows) - 1)]
        q = arm(r["action"][:5])
        g = grip(r["action"][5], a.gripper_zero)
        d.ctrl[:5] = q
        d.ctrl[5] = g
        mujoco.mj_step(m, d)
        mujoco.mj_forward(m, d)
        touches = [set(), set()]
        for ci, c in enumerate(d.contact):
            bodies = [int(m.geom_bodyid[x]) for x in c.geom]
            names = [m.body(b).name for b in bodies]
            for i, b in enumerate(shoes):
                if b in bodies:
                    for name in names:
                        if name in ("link6", "link7"):
                            touches[i].add(name)
                            pen = max(0.0, -float(c.dist))
                            if pen >= max_pen:
                                max_pen = pen
                                max_pair = {
                                    "time_s": float(d.time),
                                    "geom_names": [m.geom(int(x)).name for x in c.geom],
                                    "dist_m": float(c.dist),
                                }
        for i in range(2):
            peak[i] = max(peak[i], float(d.xpos[shoes[i], 2] - z0[i]))
            bilateral[i] += int(len(touches[i]) == 2)

        if step % max(1, int(round((1 / 30) / m.opt.timestep))) == 0:
            renderer.update_scene(d, camera=cam)
            ffmpeg.stdin.write(renderer.render().tobytes())
    renderer.close()
    ffmpeg.stdin.close()
    if ffmpeg.wait() != 0:
        raise RuntimeError(f"ffmpeg failed while writing {video_path}")
    summary = {
        "status": "NG_REPLAY_RECORDED",
        "video": str(video_path),
        "plan": plan_report,
        "scene": str(scene),
        "shift_m": [a.shift_x, a.shift_y, a.shift_z],
        "peak_shoe_lift_m": peak.tolist(),
        "bilateral_contact_steps": bilateral.tolist(),
        "max_finger_shoe_penetration_m": float(max_pen),
        "max_finger_pair": max_pair,
        "interpretation": "Apparent lift is rejected as a grasp when penetration exceeds 1 mm; this video documents the collision-model failure.",
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
