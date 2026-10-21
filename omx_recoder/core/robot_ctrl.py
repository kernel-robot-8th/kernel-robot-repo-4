import logging
import queue
import threading
import time
import traceback

import numpy as np

from .config import MOTORS
from .kinematics import EEPoseCalculator

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 10


class Mode:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    MOVING = "MOVING"
    ALIGNING = "ALIGNING"
    TELEOP = "TELEOP"
    STOPPING = "STOPPING"
    FAULT = "FAULT"


def _smoothstep(a: float) -> float:
    a = min(max(a, 0.0), 1.0)
    return a * a * (3 - 2 * a)


class RobotController:
    """Owns follower/leader buses and a fixed-rate control loop running in its own thread."""

    def __init__(self, cameras, recorder):
        self.cameras = cameras
        self.recorder = recorder
        self.recorder.on_event = self._emit
        self.events: queue.Queue = queue.Queue()
        self._cmds: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snap: dict = {"mode": Mode.DISCONNECTED}
        self.mode = Mode.DISCONNECTED
        self.follower = None
        self.leader = None

    # ------------------------------------------------------------------ public (UI thread)
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snap)

    def bringup(self, cfg: dict, poses: dict, session: dict) -> None:
        if self.running:
            return
        self._cmds = queue.Queue()
        self._set_mode(Mode.CONNECTING)
        self._thread = threading.Thread(target=self._run, args=(cfg, dict(poses), dict(session)), daemon=True)
        self._thread.start()

    def servo_off(self) -> None:
        self._cmds.put(("servo_off",))

    def start_record(self, task: str) -> None:
        self._cmds.put(("record", task))

    def end_episode(self, outcome: str, meta: dict | None = None) -> None:
        self._cmds.put(("end", outcome, meta or {}))

    def capture_pose(self, which: str) -> None:
        self._cmds.put(("capture", which))

    def shutdown(self, timeout: float = 15.0) -> None:
        if self.running:
            self._cmds.put(("servo_off",))
            self._thread.join(timeout)

    # ------------------------------------------------------------------ internals
    def _emit(self, kind: str, payload=None) -> None:
        self.events.put((kind, payload))

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        with self._lock:
            self._snap["mode"] = mode

    def _connect(self, cfg: dict, session: dict) -> None:
        from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig
        from lerobot.teleoperators.omx_leader import OmxLeader, OmxLeaderConfig

        rc = cfg["robot"]
        self._emit("log", "데이터셋 준비 중...")
        self.recorder.open(
            task_dir=session["task_dir"],
            task_name=session["task_name"],
            hub_user=cfg["hub"]["user"],
            fps=int(cfg["record"]["fps"]),
            camera_shapes=dict(self.cameras.shapes),
            vcodec=cfg["record"]["vcodec"],
        )
        self._emit("counts", self.recorder.counts())
        self._emit("log", f"팔로워 연결: {rc['follower_port']}")
        self.follower = OmxFollower(OmxFollowerConfig(port=rc["follower_port"], id=rc["follower_id"]))
        self.follower.connect()
        self._emit("log", f"리더 연결: {rc['leader_port']}")
        self.leader = OmxLeader(OmxLeaderConfig(port=rc["leader_port"], id=rc["leader_id"]))
        self.leader.connect()
        self.follower.bus.enable_torque()
        self._emit("log", "팔로워 토크 ON")

    def _disconnect_all(self) -> None:
        for dev, name in ((self.follower, "팔로워"), (self.leader, "리더")):
            if dev is None:
                continue
            try:
                if dev.is_connected:
                    if dev is self.follower:
                        dev.bus.disable_torque()
                    dev.disconnect()
                    self._emit("log", f"{name} 토크 OFF · 연결 해제")
            except Exception as e:  # noqa: BLE001
                self._emit("log", f"{name} 해제 중 오류: {e}")
        self.follower = self.leader = None
        try:
            self.recorder.close()
        except Exception as e:  # noqa: BLE001
            self._emit("error", f"데이터셋 마무리 실패: {e}")

    def _read_pos(self) -> dict:
        return self.follower.bus.sync_read("Present_Position")

    def _run(self, cfg: dict, poses: dict, session: dict) -> None:
        try:
            self._connect(cfg, session)
        except Exception as e:  # noqa: BLE001
            logger.exception("bringup failed")
            self._emit("error", f"BringUp 실패: {e}")
            self._disconnect_all()
            self._set_mode(Mode.DISCONNECTED)
            self._emit("servo_off_done", None)
            return

        try:
            self._loop(cfg, poses)
        except Exception as e:  # noqa: BLE001
            logger.exception("control loop crashed")
            self._emit("error", f"제어 루프 오류: {e}\n{traceback.format_exc()}")
        finally:
            self._disconnect_all()
            self._set_mode(Mode.DISCONNECTED)
            with self._lock:
                self._snap.update(recording=False, pending=False)
            self._emit("servo_off_done", None)

    # ------------------------------------------------------------------ loop
    def _loop(self, cfg: dict, poses: dict) -> None:
        fps = int(cfg["record"]["fps"])
        period = 1.0 / fps
        status_period = 1.0 / max(float(cfg["record"]["status_hz"]), 0.01)
        mc = cfg["motion"]
        move_dur = float(mc["move_duration_s"])
        tol_joint = float(mc["align_tol_joint"])
        tol_grip = float(mc["align_tol_gripper"])
        hold_s = float(mc["align_hold_s"])
        max_step = float(mc["max_step"])
        ee_calc = EEPoseCalculator(self.follower.bus.calibration, cfg["fk"]["signs"], cfg["fk"]["offsets_deg"])

        st = {
            "recording": False,
            "pending": False,
            "task": "",
            "rec_t0": 0.0,
            "rec_frames": 0,
            "move": None,  # (start, end, t0, dur, next_mode)
            "hold": None,
            "align_since": None,
            "last_goal": None,
            "stop": False,
        }
        temp = {m: 0.0 for m in MOTORS}
        volt = {m: 0.0 for m in MOTORS}
        last_status = 0.0
        last_frames: dict = {}
        errors = 0
        loop_dt = period

        fpos0 = self._read_pos()

        def start_move(start: dict, end: dict, next_mode: str):
            st["move"] = (dict(start), dict(end), time.perf_counter(), move_dur, next_mode)
            st["hold"] = dict(end)
            self._set_mode(Mode.MOVING)

        def enter_aligning(target: dict):
            st["hold"] = dict(target)
            st["align_since"] = None
            self._set_mode(Mode.ALIGNING)

        if poses.get("init"):
            self._emit("log", f"Init 자세로 이동 ({move_dur:.1f}s)")
            start_move(fpos0, poses["init"], Mode.ALIGNING)
        else:
            self._emit("log", "Init 자세 미설정 — 현재 자세를 유지합니다. 원하는 자세에서 'Init 저장'을 누르세요.")
            enter_aligning(fpos0)

        next_t = time.perf_counter()
        while True:
            t_loop = time.perf_counter()

            # ---------------- commands
            while True:
                try:
                    cmd = self._cmds.get_nowait()
                except queue.Empty:
                    break
                self._handle_cmd(cmd, st, poses, start_move, enter_aligning)
            if st["stop"]:
                break

            try:
                lead = self.leader.get_action()
                lpos = {m: float(lead[f"{m}.pos"]) for m in MOTORS}
                fpos = self._read_pos()
                sent = None
                now = time.perf_counter()

                if self.mode == Mode.TELEOP:
                    if st["last_goal"] is None:
                        st["last_goal"] = dict(fpos)
                    goal = {}
                    for m in MOTORS:
                        d = lpos[m] - st["last_goal"][m]
                        if max_step > 0:
                            d = float(np.clip(d, -max_step, max_step))
                        goal[m] = st["last_goal"][m] + d
                    self.follower.bus.sync_write("Goal_Position", goal)
                    st["last_goal"] = goal
                    sent = goal

                elif self.mode == Mode.MOVING:
                    start, end, t0, dur, next_mode = st["move"]
                    a = _smoothstep((now - t0) / dur) if dur > 0 else 1.0
                    goal = {m: start[m] + (end[m] - start[m]) * a for m in MOTORS}
                    self.follower.bus.sync_write("Goal_Position", goal)
                    sent = goal
                    if a >= 1.0:
                        st["move"] = None
                        if next_mode == Mode.STOPPING:
                            st["stop"] = True
                        else:
                            enter_aligning(end)
                            self._emit("log", "리더암을 Init 자세에 맞추면 녹화가 활성화됩니다.")

                elif self.mode == Mode.ALIGNING:
                    sent = st["hold"]
                    ok = all(
                        abs(lpos[m] - fpos[m]) <= (tol_grip if m == "gripper" else tol_joint) for m in MOTORS
                    )
                    if ok:
                        if st["align_since"] is None:
                            st["align_since"] = now
                        elif now - st["align_since"] >= hold_s:
                            st["last_goal"] = dict(fpos)
                            self._set_mode(Mode.TELEOP)
                            self._emit("aligned", None)
                    else:
                        st["align_since"] = None

                vel = self.follower.bus.sync_read("Present_Velocity")
                cur = self.follower.bus.sync_read("Present_Current")
                if now - last_status >= status_period:
                    temp = self.follower.bus.sync_read("Present_Temperature")
                    volt = {m: v * 0.1 for m, v in self.follower.bus.sync_read("Present_Input_Voltage").items()}
                    last_status = now
                ee = ee_calc.compute(fpos)

                if st["recording"]:
                    frame = self._build_frame(sent or fpos, lpos, fpos, vel, cur, temp, volt, ee, st["task"], last_frames)
                    if frame is not None:
                        self.recorder.add_frame(frame)
                        st["rec_frames"] += 1

                with self._lock:
                    self._snap.update(
                        mode=self.mode,
                        leader=lpos,
                        follower=dict(fpos),
                        velocity=dict(vel),
                        current=dict(cur),
                        temperature=dict(temp),
                        voltage=dict(volt),
                        ee=ee.tolist(),
                        recording=st["recording"],
                        pending=st["pending"],
                        rec_frames=st["rec_frames"],
                        rec_seconds=(now - st["rec_t0"]) if st["recording"] else 0.0,
                        saving=self.recorder.busy,
                        loop_hz=1.0 / loop_dt if loop_dt > 0 else 0.0,
                        tol_joint=tol_joint,
                        tol_grip=tol_grip,
                    )
                errors = 0
            except Exception as e:  # noqa: BLE001
                errors += 1
                if errors in (1, MAX_CONSECUTIVE_ERRORS):
                    self._emit("error", f"통신 오류: {e}")
                if errors >= MAX_CONSECUTIVE_ERRORS and self.mode != Mode.FAULT:
                    if st["recording"]:
                        st["recording"] = False
                        st["pending"] = True
                    self._set_mode(Mode.FAULT)
                    self._emit("error", "연속 통신 오류로 FAULT 상태입니다. 녹화를 정리하고 Servo OFF 하세요.")

            next_t += period
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter()
            loop_dt = time.perf_counter() - t_loop

        # ---------------- shutdown
        self._set_mode(Mode.STOPPING)
        self._emit("log", "녹화 저장 마무리 대기 중...")
        self.recorder.wait_idle()

    def _handle_cmd(self, cmd, st, poses, start_move, enter_aligning) -> None:
        kind = cmd[0]
        if kind == "record":
            if self.mode != Mode.TELEOP or st["recording"] or st["pending"] or self.recorder.busy:
                return
            st.update(recording=True, task=cmd[1] or "", rec_t0=time.perf_counter(), rec_frames=0)
            self._emit("record_started", None)

        elif kind == "end":
            outcome, meta = cmd[1], cmd[2]
            if not (st["recording"] or st["pending"]):
                return
            st["recording"] = st["pending"] = False
            meta = {"task": st["task"], **meta}
            self.recorder.finish(outcome, meta)
            with self._lock:
                self._snap.update(recording=False, pending=False, saving=True)
            if self.mode in (Mode.TELEOP, Mode.ALIGNING) and poses.get("init"):
                try:
                    start_move(self._read_pos(), poses["init"], Mode.ALIGNING)
                    self._emit("log", "Init 자세로 복귀")
                except Exception as e:  # noqa: BLE001
                    self._emit("error", f"Init 복귀 실패: {e}")

        elif kind == "capture":
            which = cmd[1]
            try:
                pose = {m: float(v) for m, v in self._read_pos().items()}
            except Exception as e:  # noqa: BLE001
                self._emit("error", f"자세 읽기 실패: {e}")
                return
            poses[which] = pose
            self._emit("pose_captured", (which, pose))
            if which == "init" and self.mode == Mode.ALIGNING:
                enter_aligning(pose)

        elif kind == "servo_off":
            if st["recording"]:
                self._emit("error", "녹화 중에는 Servo OFF 할 수 없습니다.")
                return
            if st["pending"]:
                self.recorder.finish("discard", {})
                st["pending"] = False
            target = poses.get("rest") or poses.get("init")
            if self.mode == Mode.FAULT or not target:
                st["stop"] = True
                return
            try:
                start_move(self._read_pos(), target, Mode.STOPPING)
                self._emit("log", "Rest 자세로 이동 후 토크 OFF")
            except Exception:  # noqa: BLE001
                st["stop"] = True

    def _build_frame(self, sent, lpos, fpos, vel, cur, temp, volt, ee, task, last_frames):
        try:
            imgs = self.cameras.read_all(max_age_ms=500)
            last_frames.update(imgs)
        except Exception:  # noqa: BLE001
            imgs = {}
        for role in self.cameras.roles:
            if role not in last_frames:
                return None

        def arr(d):
            return np.array([float(d[m]) for m in MOTORS], dtype=np.float32)

        frame = {
            "action": arr(sent),
            "observation.state": arr(fpos),
            "aux.leader_action": arr(lpos),
            "aux.velocity": arr(vel),
            "aux.current": arr(cur),
            "aux.gripper_current": np.array([float(cur["gripper"])], dtype=np.float32),
            "aux.temperature": arr(temp),
            "aux.voltage": arr(volt),
            "aux.ee_pose": np.asarray(ee, dtype=np.float32),
            "episode_success": np.array([0], dtype=np.int64),
            "task": task,
        }
        for role in self.cameras.roles:
            frame[f"observation.images.{role}"] = last_frames[role]
        return frame
