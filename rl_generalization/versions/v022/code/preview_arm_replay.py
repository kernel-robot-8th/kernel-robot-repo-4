"""Interactive preview of the arm-connected demonstration replay.

This uses the same actuator commands and retarget shift as
``v021/code/arm_replay_attempt.py`` but opens a MuJoCo window instead of
writing only a JSON diagnostic. It is a visual inspection tool; it does not
change the grasp-success criteria or claim hardware transfer.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "versions/v018/code"))
from retarget import plan  # noqa: E402


def arm(values: object) -> np.ndarray:
    return ((np.asarray(values, dtype=float) + 100.0) / 200.0 * 4095.0 - 2048.0) * 2.0 * np.pi / 4096.0


def grip(value: float, zero: float) -> float:
    return (float(value) - zero) / 100.0 * 4095.0 * 2.0 * np.pi / 4096.0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--episode", type=int, default=0)
    p.add_argument("--seconds", type=float, default=45.0)
    p.add_argument("--speed", type=float, default=0.5, help="replay speed multiplier")
    p.add_argument("--initial-angle", type=float, default=-2.70)
    p.add_argument("--gripper-zero", type=float, default=46.8)
    p.add_argument("--shift-x", type=float, default=0.0349720067)
    p.add_argument("--shift-y", type=float, default=-0.0034275971)
    p.add_argument("--shift-z", type=float, default=-0.004)
    a = p.parse_args()
    if not 0 < a.seconds <= 45 or a.speed <= 0:
        p.error("seconds must be in (0,45] and speed must be positive")

    rows = []
    for path in sorted((ROOT / ".local/demonstrations/shoebox_D/data").rglob("*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    rows = [r for r in rows if int(r["episode_index"]) == a.episode]
    rows.sort(key=lambda r: r["frame_index"])
    if not rows:
        raise SystemExit(f"episode not found: {a.episode}")
    model = mujoco.MjModel.from_xml_path(str(a.scene))
    data = mujoco.MjData(model)
    rows, report = plan(model, rows, a.seconds, np.array([a.shift_x, a.shift_y, a.shift_z]))
    hinge = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "lid_hinge")
    data.qpos[model.jnt_qposadr[hinge]] = a.initial_angle
    data.qpos[:5] = arm(rows[0]["action"][:5])
    g0 = grip(rows[0]["action"][5], a.gripper_zero)
    data.qpos[5:7] = [g0, -g0]
    data.ctrl[:5] = data.qpos[:5]
    data.ctrl[5] = g0
    mujoco.mj_forward(model, data)
    print("ARM REPLAY PREVIEW: recorded arm/gripper commands; grasp is not validated.")
    print(f"scene={a.scene} seconds={a.seconds} speed={a.speed} shift_z={a.shift_z}")
    print(f"retarget_error={report['max_position_error_m']:.6f}m orientation={report['max_orientation_error_deg']:.3f}deg")
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.lookat[:] = [0.15, -0.06, 0.18]
        viewer.cam.distance = 0.72
        viewer.cam.azimuth = 135
        viewer.cam.elevation = -28
        start = time.monotonic()
        while viewer.is_running() and data.time < a.seconds:
            idx = min(int(data.time * 30.0), len(rows) - 1)
            row = rows[idx]
            data.ctrl[:5] = arm(row["action"][:5])
            data.ctrl[5] = grip(row["action"][5], a.gripper_zero)
            mujoco.mj_step(model, data)
            viewer.sync()
            target = start + data.time / a.speed
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 0.02))
    print("Preview ended. Use arm_replay_attempt.py for the JSON diagnostic.")


if __name__ == "__main__":
    main()
