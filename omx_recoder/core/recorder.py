import json
import logging
import shutil
import threading
import time
from pathlib import Path

import numpy as np

from .config import MOTORS

logger = logging.getLogger(__name__)

KINDS = ("success", "fail")
EE_NAMES = ["x", "y", "z", "roll", "pitch", "yaw"]
SIDE_CAR = "collector_episodes.jsonl"
INFO_FILE = "collector_info.json"

UNITS = {
    "action": "leader→follower 실제 전송 목표값 (LeRobot 정규화: 관절 -100~100, gripper 0~100)",
    "observation.state": "follower Present_Position (LeRobot 정규화)",
    "aux.leader_action": "리더암 원본 값 (step 제한 전)",
    "aux.velocity": "Present_Velocity raw (x0.229 rpm)",
    "aux.current": "Present_Current raw (XL330: 1 mA, XL430: Present_Load 0.1 %)",
    "aux.gripper_current": "gripper Present_Current raw (XL330-M288: 1 mA)",
    "aux.temperature": "Present_Temperature (°C), status_hz 주기로 갱신",
    "aux.voltage": "Present_Input_Voltage (V), status_hz 주기로 갱신",
    "aux.ee_pose": "FK 결과 x, y, z (m), roll, pitch, yaw (rad) — omx_f URDF 기준",
    "episode_success": "1 = Success, 0 = Fail",
}


def build_features(camera_shapes: dict) -> dict:
    def vec(names):
        return {"dtype": "float32", "shape": (len(names),), "names": list(names)}

    pos_names = [f"{m}.pos" for m in MOTORS]
    feats = {
        "action": vec(pos_names),
        "observation.state": vec(pos_names),
        "aux.leader_action": vec(pos_names),
        "aux.velocity": vec([f"{m}.vel" for m in MOTORS]),
        "aux.current": vec([f"{m}.cur" for m in MOTORS]),
        "aux.gripper_current": vec(["gripper.cur"]),
        "aux.temperature": vec([f"{m}.temp" for m in MOTORS]),
        "aux.voltage": vec([f"{m}.volt" for m in MOTORS]),
        "aux.ee_pose": vec(EE_NAMES),
        "episode_success": {"dtype": "int64", "shape": (1,), "names": ["success"]},
    }
    for role, shape in camera_shapes.items():
        feats[f"observation.images.{role}"] = {
            "dtype": "video",
            "shape": tuple(shape),
            "names": ["height", "width", "channels"],
        }
    return feats


def _same_features(a: dict, b: dict) -> bool:
    for k in a:
        if k not in b:
            return False
        if tuple(a[k]["shape"]) != tuple(b[k]["shape"]) or a[k]["dtype"] != b[k]["dtype"]:
            return False
    return True


def _flush(ds) -> None:
    """Close parquet writers so files on disk are valid even if the app crashes later."""
    ds._close_writer()
    ds.meta._close_writer()
    ds._writer_closed_for_reading = True


class Recorder:
    def __init__(self):
        self.datasets = {}
        self.task_dir: Path | None = None
        self.fps = 30
        self._busy = threading.Event()
        self._lock = threading.Lock()
        self.on_event = lambda kind, payload: None

    # ---------- lifecycle ----------
    @property
    def is_open(self) -> bool:
        return bool(self.datasets)

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def counts(self) -> dict:
        return {k: (ds.meta.total_episodes if ds else 0) for k, ds in self.datasets.items()}

    @staticmethod
    def disk_counts(task_dir: Path) -> dict:
        out = {}
        for kind in KINDS:
            info = Path(task_dir) / kind / "meta" / "info.json"
            try:
                out[kind] = json.loads(info.read_text())["total_episodes"]
            except Exception:  # noqa: BLE001
                out[kind] = 0
        return out

    def open(self, task_dir: Path, task_name: str, hub_user: str, fps: int, camera_shapes: dict, vcodec: str):
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        self.close()
        self.task_dir = Path(task_dir)
        self.fps = fps
        features = build_features(camera_shapes)
        n_threads = max(4, 4 * len(camera_shapes))
        user = hub_user or "local"
        opened = {}
        for kind in KINDS:
            root = self.task_dir / kind
            repo_id = f"{user}/{task_name}_{kind}"
            info_path = root / "meta" / "info.json"
            ds = None
            if info_path.exists():
                info = json.loads(info_path.read_text())
                if info.get("total_episodes", 0) == 0:
                    shutil.rmtree(root)
                else:
                    if info.get("fps") != fps:
                        raise RuntimeError(
                            f"{root} 의 fps({info.get('fps')})가 현재 설정({fps})과 다릅니다. "
                            "녹화 주기를 맞추거나 다른 태스크명을 사용하세요."
                        )
                    existing = {k: v for k, v in info["features"].items() if k in features}
                    if set(existing) != set(features) or not _same_features(features, info["features"]):
                        raise RuntimeError(
                            f"{root} 의 데이터 구성(카메라·해상도 등)이 현재 설정과 다릅니다. "
                            "설정을 맞추거나 다른 태스크명을 사용하세요."
                        )
                    ds = LeRobotDataset(repo_id, root=root, vcodec=vcodec)
                    ds.start_image_writer(num_processes=0, num_threads=n_threads)
                    _flush(ds)
            if ds is None:
                root.parent.mkdir(parents=True, exist_ok=True)
                ds = LeRobotDataset.create(
                    repo_id,
                    fps,
                    features=features,
                    root=root,
                    robot_type="omx_follower",
                    use_videos=True,
                    image_writer_threads=n_threads,
                    vcodec=vcodec,
                )
            info_file = root / "meta" / INFO_FILE
            info_file.write_text(json.dumps({"units": UNITS, "kind": kind}, ensure_ascii=False, indent=2))
            opened[kind] = ds
        self.datasets = opened

    def close(self) -> None:
        self.wait_idle()
        for ds in self.datasets.values():
            try:
                ds.finalize()
            except Exception:  # noqa: BLE001
                logger.exception("finalize failed")
            try:
                ds.stop_image_writer()
            except Exception:  # noqa: BLE001
                pass
        self.datasets = {}

    def wait_idle(self, timeout: float | None = None) -> None:
        t0 = time.time()
        while self._busy.is_set():
            if timeout is not None and time.time() - t0 > timeout:
                break
            time.sleep(0.05)

    # ---------- recording ----------
    def add_frame(self, frame: dict) -> None:
        self.datasets["success"].add_frame(frame)

    def buffer_size(self) -> int:
        ds = self.datasets.get("success")
        if ds is None or ds.episode_buffer is None:
            return 0
        return ds.episode_buffer["size"]

    def finish(self, outcome: str, meta: dict) -> None:
        """outcome: success | fail | discard. Runs in background thread."""
        self._busy.set()
        threading.Thread(target=self._finish, args=(outcome, meta), daemon=True).start()

    def _finish(self, outcome: str, meta: dict) -> None:
        try:
            src = self.datasets["success"]
            size = self.buffer_size()
            if outcome == "discard" or size == 0:
                src.clear_episode_buffer()
                self.on_event("saved", {"outcome": "discard", "frames": size})
                return
            if outcome == "success":
                ep_idx = self._save(src, src.episode_buffer, 1)
                dst = src
            else:
                dst = self.datasets["fail"]
                buf = self._transfer(src, dst)
                src.episode_buffer = src.create_episode_buffer()
                ep_idx = self._save(dst, buf, 0)
            self._write_sidecar(dst, ep_idx, outcome, size, meta)
            self.on_event("saved", {"outcome": outcome, "frames": size, "episode_index": ep_idx})
        except Exception as e:  # noqa: BLE001
            logger.exception("save failed")
            self.on_event("error", f"에피소드 저장 실패: {e}")
            try:
                self.datasets["success"].clear_episode_buffer()
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._busy.clear()

    def _save(self, ds, buf, success: int) -> int:
        n = buf["size"]
        buf["episode_success"] = [np.array([success], dtype=np.int64) for _ in range(n)]
        ep_idx = int(buf["episode_index"])
        ds.save_episode(episode_data=buf, parallel_encoding=False)
        ds.episode_buffer = ds.create_episode_buffer()
        _flush(ds)
        return ep_idx

    @staticmethod
    def _transfer(src, dst) -> dict:
        """Move the recorded episode (buffer + temp images) from the success dataset to the fail dataset."""
        src._wait_image_writer()
        buf = src.episode_buffer
        old_idx = buf["episode_index"]
        new_idx = dst.meta.total_episodes
        for key in src.meta.video_keys:
            old_dir = src._get_image_file_dir(old_idx, key)
            new_dir = dst._get_image_file_dir(new_idx, key)
            if new_dir.exists():
                shutil.rmtree(new_dir)
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
            buf[key] = [str(dst._get_image_file_path(new_idx, key, i)) for i in range(buf["size"])]
        buf["episode_index"] = new_idx
        return buf

    def _write_sidecar(self, ds, ep_idx: int, outcome: str, frames: int, meta: dict) -> None:
        line = {
            "episode_index": ep_idx,
            "success": outcome == "success",
            "frames": frames,
            "duration_s": round(frames / self.fps, 3),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **meta,
        }
        with open(Path(ds.root) / "meta" / SIDE_CAR, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
