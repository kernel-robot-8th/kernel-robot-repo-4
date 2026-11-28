"""Small, headless MuJoCo residual-control environment for the OMX shoes.

The recorded shoebox_D trajectory is the nominal controller.  The policy only
learns a bounded residual around that trajectory.  This keeps the search in the
same joint convention as the real robot while still using MuJoCo contacts,
friction and free-body dynamics for the grasp decision.

The environment deliberately has two attachment modes.  ``physical`` never
teleports a shoe and only reports a success when the free shoe body actually
rises.  ``welded_proxy`` is a curriculum/debug mode which welds a shoe after
stable bilateral contact; its result is labelled proxy success and must not be
used as a sim-to-real claim.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "versions/v018/code"))
from retarget import plan  # noqa: E402

ARRANGE_INIT = np.array([-12.97, -17.31, -0.85, 43.59, -0.85, 59.68], dtype=float)


def arm(values: np.ndarray | list[float]) -> np.ndarray:
    """LeRobot body value (-100..100) to MuJoCo radians."""
    u = np.asarray(values, dtype=float)
    return ((u + 100.0) / 200.0 * 4095.0 - 2048.0) * 2.0 * np.pi / 4096.0


def grip(value: float, zero: float) -> float:
    return (float(value) - float(zero)) / 100.0 * 4095.0 * 2.0 * np.pi / 4096.0


def _contacts(model: mujoco.MjModel, data: mujoco.MjData, shoe: str) -> tuple[set[str], float]:
    shoe_bid = model.body(shoe).id
    fingers: set[str] = set()
    penetration = 0.0
    for i in range(data.ncon):
        c = data.contact[i]
        g0, g1 = int(c.geom1), int(c.geom2)
        names = (model.geom(g0).name, model.geom(g1).name)
        bodies = (int(model.geom_bodyid[g0]), int(model.geom_bodyid[g1]))
        if shoe_bid not in bodies:
            continue
        for n in names:
            if n.startswith("finger"):
                fingers.add(n)
        if any(n.startswith(shoe + "_") for n in names) and any(n.startswith("finger") for n in names):
            penetration = max(penetration, max(0.0, -float(c.dist)))
    return fingers, penetration


class ResidualGraspEnv:
    """Nominal demonstration replay plus bounded residual actions."""

    def __init__(
        self,
        scene: str | Path,
        *,
        seconds: float = 12.0,
        shift: np.ndarray | None = None,
        gripper_zero: float = 46.8,
        open_backoff_rad: float = 0.005,
        shoe: str = "shoe1",
        attachment_mode: str = "physical",
        residual_scale: np.ndarray | None = None,
        # The parquet actions are 30 Hz.  With the scene timestep of 0.002 s,
        # one policy decision must advance 16 physics steps to preserve the
        # recorded 12 s timing; four steps replayed the trajectory 4x too fast.
        frame_skip: int | None = None,
    ) -> None:
        self.scene = str(scene)
        self.seconds = float(seconds)
        self.shift = np.asarray(shift if shift is not None else [0.0349720067, -0.0034275971, -0.004], dtype=float)
        self.gripper_zero = float(gripper_zero)
        self.open_backoff_rad = float(open_backoff_rad)
        self.shoe = shoe
        self.attachment_mode = attachment_mode
        self.model = mujoco.MjModel.from_xml_path(self.scene)
        self.model.opt.timestep = min(float(self.model.opt.timestep), 0.002)
        self.frame_skip = int(frame_skip) if frame_skip is not None else max(1, int(round((1.0 / 30.0) / self.model.opt.timestep)))
        self.data = mujoco.MjData(self.model)
        self._initial_qpos = self.data.qpos.copy()
        self._initial_qvel = self.data.qvel.copy()
        self.shoes = ["shoe0", "shoe1"] if shoe == "both" else [shoe]
        # residual: five arm joints and gripper command, in radians per action.
        self.residual_scale = np.asarray(
            residual_scale if residual_scale is not None else [0.035, 0.035, 0.035, 0.045, 0.045, 0.12], dtype=float
        )
        ds = ROOT / ".local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet"
        rows = pq.read_table(ds).to_pylist()
        rows.sort(key=lambda row: row["frame_index"])
        self.rows, self.plan_report = plan(self.model, rows, self.seconds, self.shift)
        self.n_steps = max(1, min(len(self.rows), int(self.seconds * 30)))
        self.step_index = 0
        self.z0: dict[str, float] = {}
        self.lift: dict[str, float] = {}
        self.max_penetration: dict[str, float] = {}
        self.bilateral: dict[str, int] = {}
        self.stable: dict[str, int] = {}
        self.proxy_attached: dict[str, bool] = {}
        self._proxy_rel: dict[str, np.ndarray] = {}
        self._grasp_q: np.ndarray | None = None
        self._grasp_tcp_z: float | None = None
        self._hold_gripper_target: float | None = None
        self._attachment_penetration: dict[str, float] = {}
        self.reset()

    def reset(self, *, seed: int | None = None) -> np.ndarray:
        if seed is not None:
            np.random.seed(int(seed))
        self.data.qpos[:] = self._initial_qpos
        self.data.qvel[:] = self._initial_qvel
        self.step_index = 0
        q0 = arm(ARRANGE_INIT[:5])
        g0 = grip(ARRANGE_INIT[5], self.gripper_zero)
        self.data.qpos[:5] = q0
        self.data.qpos[5:7] = [g0, -g0]
        self.data.ctrl[:5] = q0
        self.data.ctrl[5] = g0
        mujoco.mj_forward(self.model, self.data)
        self.z0 = {s: float(self.data.xpos[self.model.body(s).id, 2]) for s in self.shoes}
        self.lift = {s: 0.0 for s in self.shoes}
        self.max_penetration = {s: 0.0 for s in self.shoes}
        self.bilateral = {s: 0 for s in self.shoes}
        self.stable = {s: 0 for s in self.shoes}
        self.proxy_attached = {s: False for s in self.shoes}
        self._proxy_rel = {}
        self._grasp_q = None
        self._grasp_tcp_z = None
        self._hold_gripper_target = None
        self._attachment_penetration = {s: 0.0 for s in self.shoes}
        return self.observe()

    def _nominal(self) -> np.ndarray:
        row = self.rows[min(self.step_index, self.n_steps - 1)]
        q = arm(np.asarray(row["action"][:5], dtype=float))
        return np.r_[q, grip(float(row["action"][5]), self.gripper_zero)]

    def observe(self) -> np.ndarray:
        vals = list(self.data.qpos[:6])
        for s in self.shoes:
            bid = self.model.body(s).id
            finger, pen = _contacts(self.model, self.data, s)
            vals.extend(self.data.xpos[bid].tolist())
            vals.extend([float(len(finger) >= 2), float(pen), float(self.lift[s])])
        return np.asarray(vals, dtype=np.float32)

    def _attach_proxy_if_ready(self, shoe: str, fingers: set[str], penetration: float) -> None:
        if (
            self.attachment_mode != "welded_proxy"
            or self.proxy_attached[shoe]
            or len(fingers) < 2
            or penetration > 0.001
        ):
            return
        bid = self.model.body(shoe).id
        link = self.model.body("link5").id
        # Store shoe position relative to TCP.  Subsequent steps keep the free
        # body at that relative pose; this is an explicit curriculum proxy.
        tcp = self.data.xpos[link] + self.data.xmat[link].reshape(3, 3) @ np.array([0.09193, -0.0016, 0.0])
        self._proxy_rel[shoe] = self.data.xpos[bid].copy() - tcp
        self.proxy_attached[shoe] = True

    def _latch_if_ready(self, shoe: str, fingers: set[str], penetration: float) -> None:
        """Stop closing before the next physics step once bilateral contact appears."""
        if len(fingers) < 2 or self._grasp_q is not None:
            return
        # Match the diagnostic replay: hold the commanded arm pose at contact,
        # rather than the lagging joint state.  Holding qpos here leaves the
        # position actuators free to finish the approach and creates excess
        # collision penetration.
        self._grasp_q = self.data.ctrl[:5].copy()
        b = self.model.body("link5").id
        self._grasp_tcp_z = float(
            self.data.xpos[b, 2]
            + self.data.xmat[b].reshape(3, 3)[2, :] @ np.array([0.09193, -0.0016, 0.0])
        )
        self._attachment_penetration[shoe] = float(penetration)
        self._hold_gripper_target = float(self.data.qpos[5] + self.open_backoff_rad)
        self.data.qvel[5:7] = 0.0

    def step(self, action: np.ndarray | list[float]) -> tuple[np.ndarray, float, bool, dict[str, Any]]:
        a = np.clip(np.asarray(action, dtype=float), -1.0, 1.0)
        nominal = self._nominal()
        target = nominal + a * self.residual_scale
        # Once both pads have contacted the recorded shoe, stop the closing
        # motion and hold the contact arm pose until the nominal path has
        # risen.  The old replay allowed the arm to continue dipping through
        # the thin collision proxy, which made a valid contact look like a
        # failed grasp.
        if self._grasp_q is not None:
            probe = mujoco.MjData(self.model)
            probe.qpos[:] = self.data.qpos
            probe.qvel[:] = self.data.qvel
            probe.qpos[:5] = nominal[:5]
            mujoco.mj_forward(self.model, probe)
            b = self.model.body("link5").id
            tcp_z = float(probe.xpos[b, 2] + probe.xmat[b].reshape(3, 3)[2, :] @ np.array([0.09193, -0.0016, 0.0]))
            if self._grasp_tcp_z is not None and tcp_z >= self._grasp_tcp_z + 0.008:
                self._grasp_q = None
                self._grasp_tcp_z = None
            else:
                target[:5] = self._grasp_q
                target[5] = (
                    self._hold_gripper_target
                    if self._hold_gripper_target is not None
                    else max(float(self.data.qpos[5]), float(target[5]))
                )
        # Position actuators on the real model use qpos radians as targets.
        self.data.ctrl[:5] = target[:5]
        self.data.ctrl[5] = target[5]
        reward = 0.0
        for _ in range(self.frame_skip):
            # Apply the hold/release decision at physics-step resolution.  A
            # decision-rate-only check delays release by up to 33 ms and can
            # drive the fingers back through the shoe after the planned TCP
            # has started rising.
            inner_target = target.copy()
            if self._grasp_q is not None:
                probe = mujoco.MjData(self.model)
                probe.qpos[:] = self.data.qpos
                probe.qvel[:] = self.data.qvel
                nominal = self._nominal()
                probe.qpos[:5] = nominal[:5]
                mujoco.mj_forward(self.model, probe)
                b = self.model.body("link5").id
                tcp_z = float(probe.xpos[b, 2] + probe.xmat[b].reshape(3, 3)[2, :] @ np.array([0.09193, -0.0016, 0.0]))
                if self._grasp_tcp_z is not None and tcp_z >= self._grasp_tcp_z + 0.008:
                    self._grasp_q = None
                    self._grasp_tcp_z = None
                    self._hold_gripper_target = None
                else:
                    inner_target[:5] = self._grasp_q
                    inner_target[5] = self._hold_gripper_target if self._hold_gripper_target is not None else inner_target[5]
            self.data.ctrl[:5] = inner_target[:5]
            self.data.ctrl[5] = inner_target[5]
            # Inspect the contact state before stepping as well as after it.
            # This avoids one full physics step of continued closing after
            # bilateral contact, which was enough to create millimetres of
            # artificial finger penetration.
            for s in self.shoes:
                fingers, pen = _contacts(self.model, self.data, s)
                self._latch_if_ready(s, fingers, pen)
            mujoco.mj_step(self.model, self.data)
            for s in self.shoes:
                fingers, pen = _contacts(self.model, self.data, s)
                if len(fingers) >= 2:
                    self.bilateral[s] += 1
                    self.stable[s] += 1
                    self._latch_if_ready(s, fingers, pen)
                else:
                    self.stable[s] = 0
                self.max_penetration[s] = max(self.max_penetration[s], pen)
                bid = self.model.body(s).id
                self.lift[s] = max(self.lift[s], float(self.data.xpos[bid, 2] - self.z0[s]))
                self._attach_proxy_if_ready(s, fingers, pen)
                if self.proxy_attached[s]:
                    link = self.model.body("link5").id
                    tcp = self.data.xpos[link] + self.data.xmat[link].reshape(3, 3) @ np.array([0.09193, -0.0016, 0.0])
                    jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, f"{s}_free")
                    qadr = int(self.model.jnt_qposadr[jid]); dadr = int(self.model.jnt_dofadr[jid])
                    q = self.data.qpos[qadr : qadr + 7]
                    q[:3] = tcp + self._proxy_rel[s]
                    self.data.qpos[qadr : qadr + 7] = q
                    self.data.qvel[dadr : dadr + 6] = 0
                    mujoco.mj_forward(self.model, self.data)
        # Dense curriculum reward uses distance to bilateral contact and lift.
        for s in self.shoes:
            fingers, pen = _contacts(self.model, self.data, s)
            reward += 1.0 * min(len(fingers), 2) / 2.0
            reward += 8.0 * min(self.lift[s] / 0.03, 1.0)
            reward -= 12.0 * min(self.max_penetration[s] / 0.003, 1.0)
            if self.proxy_attached[s]:
                reward += 4.0
        reward -= 0.01 * float(np.dot(a, a))
        self.step_index += 1
        done = self.step_index >= self.n_steps or not np.isfinite(self.data.qpos).all()
        success = self.success()
        proxy_success = self.proxy_success()
        info = {"success": success, "proxy_success": proxy_success, **self.summary()}
        return self.observe(), float(reward), bool(done), info

    def success(self) -> bool:
        return all(self.bilateral[s] > 0 and self.lift[s] >= 0.03 and self.max_penetration[s] <= 0.001 for s in self.shoes)

    def proxy_success(self) -> bool:
        """Curriculum-only outcome; never folded into physical ``success``."""
        return bool(
            self.attachment_mode == "welded_proxy"
            and all(self.proxy_attached[s] and self.lift[s] >= 0.03 for s in self.shoes)
            and all(self.max_penetration[s] <= 0.001 for s in self.shoes)
        )

    def summary(self) -> dict[str, Any]:
        return {
            "shoes": self.shoes,
            "attachment_mode": self.attachment_mode,
            "bilateral_contact_steps": self.bilateral.copy(),
            "max_finger_shoe_penetration_m": self.max_penetration.copy(),
            "attachment_penetration_m": self._attachment_penetration.copy(),
            "peak_shoe_lift_m": self.lift.copy(),
            "success": self.success(),
            "proxy_success": self.proxy_success(),
            "criteria": {"penetration_le_m": 0.001, "lift_ge_m": 0.03, "bilateral_required": True},
        }

