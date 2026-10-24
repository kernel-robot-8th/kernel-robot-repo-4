import copy
from pathlib import Path

import yaml

MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
ARM_MOTORS = MOTORS[:5]
CAMERA_ROLES = ["wrist", "top"]

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.yaml"
POSES_PATH = APP_DIR / "init_pose.yaml"

DEFAULTS = {
    "session": {
        "output_dir": "./output",
        "task_name": "omx_task",
        "task_text": "",
    },
    "robot": {
        "follower_port": "auto",
        "follower_id": "omx_follower_arm",
        "leader_port": "auto",
        "leader_id": "omx_leader_arm",
    },
    "cameras": {
        "wrist": {"index_or_path": "", "width": 640, "height": 480, "fps": 30},
        "top": {"index_or_path": "", "width": 640, "height": 480, "fps": 30},
    },
    "record": {
        "fps": 30,
        "status_hz": 1.0,
        "vcodec": "libsvtav1",
    },
    "motion": {
        "move_duration_s": 3.0,
        "max_step": 3.0,
    },
    "hub": {
        "user": "",
        "private": True,
    },
    "fk": {
        "signs": [1, 1, 1, 1, 1],
        "offsets_deg": [0.0, 0.0, 0.0, 0.0, 0.0],
    },
}


def _merge(base: dict, upd: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return _merge(DEFAULTS, yaml.safe_load(f) or {})
    cfg = copy.deepcopy(DEFAULTS)
    save_config(cfg, path)
    return cfg


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def load_poses(path: Path = POSES_PATH) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    return {"init": data.get("init"), "rest": data.get("rest")}


def save_poses(poses: dict, path: Path = POSES_PATH) -> None:
    clean = {}
    for k in ("init", "rest"):
        if poses.get(k):
            clean[k] = {m: round(float(poses[k][m]), 3) for m in MOTORS}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(clean, f, allow_unicode=True, sort_keys=False)


def parse_cam_index(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    return int(s) if s.isdigit() else s
