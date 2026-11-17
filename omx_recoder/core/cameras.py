import logging
import os
import threading

import cv2

from .config import CAMERA_ROLES, parse_cam_index

logger = logging.getLogger(__name__)

# udev symlinks from ~/il_ws/udev/99-omx-cameras.rules; stable across replug/reboot unlike /dev/videoN.
ALIAS_FMT = "/dev/cam_{}"


def role_alias(role: str) -> str | None:
    path = ALIAS_FMT.format(role)
    return path if os.path.exists(path) else None


def _alias_map() -> dict[str, str]:
    """{'/dev/videoN': role} for every role whose alias exists."""
    out = {}
    for role in CAMERA_ROLES:
        path = role_alias(role)
        if path:
            out[os.path.realpath(path)] = role
    return out


def scan_cameras(max_frames: int = 5) -> list[dict]:
    """Return [{'id', 'alias', 'alias_role', 'width', 'height', 'fps', 'frame'(RGB or None)}] for every openable /dev/video*."""
    from lerobot.cameras.opencv import OpenCVCamera

    aliases = _alias_map()
    found = []
    for info in OpenCVCamera.find_cameras():
        cam_id = info["id"]
        alias_role = aliases.get(os.path.realpath(str(cam_id)))
        cap = cv2.VideoCapture(cam_id)
        frame = None
        if cap.isOpened():
            # Some cameras stream nothing in default YUYV and each read() blocks ~10 s; MJPG answers at once
            # and is ignored by cameras without it. Preview only — connect() does its own MJPG fallback.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            for _ in range(max_frames):
                ok, img = cap.read()
                if not ok:
                    break
                frame = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        cap.release()
        prof = info.get("default_stream_profile", {})
        found.append(
            {
                "id": cam_id,
                "alias": ALIAS_FMT.format(alias_role) if alias_role else None,
                "alias_role": alias_role,
                "width": prof.get("width"),
                "height": prof.get("height"),
                "fps": prof.get("fps"),
                "frame": frame,
            }
        )
    return found


class CameraManager:
    def __init__(self):
        self.cameras = {}
        self.shapes = {}
        self.paths = {}
        self._lock = threading.Lock()

    def connect(self, cam_cfg: dict) -> list[str]:
        from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig

        self.disconnect()
        errors = []
        cams, shapes, paths = {}, {}, {}
        for role in CAMERA_ROLES:
            c = cam_cfg.get(role, {})
            idx = parse_cam_index(c.get("index_or_path"))
            if idx is None:
                idx = role_alias(role)
            if idx is None:
                continue
            # Try MJPG first: uncompressed YUYV from two cameras on one USB2 hub exceeds its bandwidth.
            last_err = None
            for fourcc in ("MJPG", None):
                cam = None
                try:
                    cfg = OpenCVCameraConfig(
                        index_or_path=idx,
                        fps=int(c.get("fps", 30)),
                        width=int(c.get("width", 640)),
                        height=int(c.get("height", 480)),
                        fourcc=fourcc,
                    )
                    cam = OpenCVCamera(cfg)
                    cam.connect()
                    cams[role] = cam
                    shapes[role] = (cfg.height, cfg.width, 3)
                    paths[role] = str(idx)
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    # A failed settings check leaves the device open; release it so the retry can open it.
                    if cam is not None:
                        try:
                            cam.disconnect()
                        except Exception:  # noqa: BLE001
                            pass
            else:
                errors.append(f"{role} 카메라({idx}) 연결 실패: {last_err}")
        with self._lock:
            self.cameras, self.shapes, self.paths = cams, shapes, paths
        return errors

    def disconnect(self) -> None:
        with self._lock:
            cams, self.cameras, self.shapes, self.paths = self.cameras, {}, {}, {}
        for cam in cams.values():
            try:
                cam.disconnect()
            except Exception:  # noqa: BLE001
                pass

    @property
    def roles(self) -> list[str]:
        with self._lock:
            return list(self.cameras)

    def latest(self, role: str, max_age_ms: int = 500):
        with self._lock:
            cam = self.cameras.get(role)
        if cam is None:
            return None
        try:
            return cam.read_latest(max_age_ms=max_age_ms)
        except Exception:  # noqa: BLE001
            return None

    def read_all(self, max_age_ms: int = 200) -> dict:
        with self._lock:
            cams = dict(self.cameras)
        out = {}
        for role, cam in cams.items():
            try:
                out[role] = cam.read_latest(max_age_ms=max_age_ms)
            except Exception:  # noqa: BLE001
                pass
        return out
