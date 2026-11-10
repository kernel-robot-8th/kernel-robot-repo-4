"""Workspace geometry from the robot's own kinematics (most reliable source).

When the gripper closes on a box, the box is between the fingers; when it opens, the box rests on its
support. Forward kinematics of the recorded joint state (ROBOTIS OMX model) at those moments gives:
  - box start position of every episode (box centre ~ gripper tip end_effector_link at grasp)
      eps 0-9: grasp 1 = A on top of B, grasp 2 = B on the table; eps 10-14: grasp 1 = D
  - table top height   = median over episodes of (B / D centre z) - box edge / 2
  - Pinky disk centre and top height = median over episodes of the first release (A or D on the disk)
Consistency check printed: A is grasped ~one box edge higher than B.
Writes box_starts (all 15 episodes), table.top_z and pinky.{x, y, disk_top_z} into scene_params.json.

  python -I sim/anchor_kinematics.py
"""

import json
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_top_camera import to_qpos  # noqa: E402
from replay_episode import grasps  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "sim/calib/scene_params.json"
OMX = ROOT / "sim/open_manipulator/open_manipulator_description/mujoco/omx/omx.xml"
SETTLE = 5  # frames after the gripper command closes (fingers reach the box)


def main():
    P = json.loads(PARAMS.read_text())
    s = P["boxes"]["box1"]["size_m"]
    m = mujoco.MjModel.from_xml_path(str(OMX))
    d = mujoco.MjData(m)
    ee = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "end_effector_link")
    ds = LeRobotDataset("local/omx_1024_test_jihyeok_success", root=ROOT / "data/omx_1024_test_jihyeok_success")

    def tip(state):
        d.qpos[:7] = to_qpos(state)
        mujoco.mj_forward(m, d)
        return d.xpos[ee].copy()

    starts, on_table, release1, stack_dz = {}, [], [], []
    for ep in range(ds.meta.total_episodes):
        e = ds.meta.episodes[ep]
        a, b = int(e["dataset_from_index"]), int(e["dataset_to_index"])
        rows = ds.hf_dataset.select(range(a, b))
        st = np.stack([np.asarray(x) for x in rows["observation.state"]])
        ac = np.stack([np.asarray(x) for x in rows["action"]])
        g = grasps(ac)[: (2 if ep < 10 else 1)]
        grab = [tip(st[c + SETTLE]) for c, _ in g]
        rel = [tip(st[o]) for _, o in g]
        if ep < 10:
            A, B = grab
            starts[f"ep{ep}"] = {"box1": {"pos_m": A.tolist(), "yaw_deg": 0.0},
                                 "box2": {"pos_m": B.tolist(), "yaw_deg": 0.0}, "boxes": {"box1": "A", "box2": "B"}}
            on_table.append(B[2])
            stack_dz.append(A[2] - B[2])
        else:
            D = grab[0]
            starts[f"ep{ep}"] = {"box1": {"pos_m": D.tolist(), "yaw_deg": 0.0},
                                 "box2": {"pos_m": [0.6, -0.6, D[2]], "yaw_deg": 0.0}, "boxes": {"box1": "D"}}
            on_table.append(D[2])
        release1.append(rel[0])
    top = float(np.median(on_table) - s / 2)
    r1 = np.median(np.stack(release1), 0)
    for v in starts.values():  # put every box exactly on its support (B / D on the table, A on B)
        v["box1"]["pos_m"][2] = top + (1.5 if "box2" in v["boxes"] else 0.5) * s
        if "box2" in v["boxes"]:
            v["box2"]["pos_m"][2] = top + 0.5 * s
            v["box1"]["pos_m"][:2] = v["box2"]["pos_m"][:2]  # A stacked on B
        else:
            v["box2"]["pos_m"][2] = top + 0.5 * s
        v["source"] = "gripper tip (forward kinematics) at grasp"
    print(f"box centre z on the table: median {np.median(on_table) * 100:.1f} cm (spread {np.ptp(on_table) * 100:.1f})"
          f" -> table top {top * 100:.1f} cm")
    print(f"A above B at grasp: {np.mean(stack_dz) * 100:.1f} +- {np.std(stack_dz) * 100:.1f} cm (box edge {s * 100:.1f})")
    print(f"first release (box on Pinky): centre {np.round(r1[:2] * 100, 1).tolist()} cm, box centre z "
          f"{r1[2] * 100:.1f} -> disk top {(r1[2] - s / 2) * 100:.1f} cm")
    P["box_starts"] = starts
    P["table"]["top_z"] = top
    P["table"]["source"] = (P["table"].get("source", "") + "; top_z from kinematics (anchor_kinematics.py)").lstrip("; ")
    P["pinky"].update({"x": float(r1[0]), "y": float(r1[1]), "disk_top_z": float(r1[2] - s / 2),
                       "source": "centre and height from kinematics (first release); radius / body from the user"})
    for n in ("box1", "box2"):
        P["boxes"][n]["pos_m"] = starts["ep0"][n]["pos_m"]
        P["boxes"][n]["yaw_deg"] = 0.0
    PARAMS.write_text(json.dumps(P, indent=2))


if __name__ == "__main__":
    main()
