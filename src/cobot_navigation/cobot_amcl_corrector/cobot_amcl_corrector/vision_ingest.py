"""태블릿 비전 -> 게이트웨이 위치 수신 및 신선도(Freshness) 검증 스토어.

이전 프로젝트(pinky_pro_team11/relay_station/gateway_web/vision_ingest.py)를
현재 프로젝트 3대 핑키(pinky1, pinky2, pinky3) 및 좌표계 변환(cobot_map_v9 <-> canonical gate67)에 맞게 확장 이식한 모듈이다.
"""
from __future__ import annotations

import math
import time
from typing import Dict, Iterable, Optional, Tuple

ALLOWED_ROBOTS = ("pinky1", "pinky2", "pinky3")
REQUIRED_FIELDS = ("robot_id", "x", "y", "yaw", "reproj_error", "source_ts")
POSE_FIX_TOP_FIELDS = ("header", "robot_id", "x", "y", "yaw", "reprojection_error_px")
STALE_AFTER_MS = 500
MAX_REPROJ_ERROR_PX = 4.0

VISION_FRESH = "VISION_FRESH"
VISION_STALE = "VISION_STALE"
VISION_NEVER = "VISION_NEVER"

# cobot_map_v9 (실물 AMCL 맵, I1=(0.0, 0.0)) <-> canonical gate67 (시뮬/웹 정본 맵, I1=(1.415, 1.639))
V9_TO_CANONICAL_OFFSET_X = 1.415
V9_TO_CANONICAL_OFFSET_Y = 1.639


def v9_to_canonical(x_v9: float, y_v9: float) -> Tuple[float, float]:
    """실물 cobot_map_v9 좌표를 시뮬레이션/웹 정본(canonical gate67) 좌표로 변환한다."""
    return (
        round(float(x_v9) + V9_TO_CANONICAL_OFFSET_X, 4),
        round(float(y_v9) + V9_TO_CANONICAL_OFFSET_Y, 4),
    )


def canonical_to_v9(x_can: float, y_can: float) -> Tuple[float, float]:
    """시뮬레이션/웹 정본(canonical gate67) 좌표를 실물 cobot_map_v9 좌표로 변환한다."""
    return (
        round(float(x_can) - V9_TO_CANONICAL_OFFSET_X, 4),
        round(float(y_can) - V9_TO_CANONICAL_OFFSET_Y, 4),
    )


def transform_xy(x: float, y: float, frame_mode: str = "identity") -> Tuple[float, float]:
    """frame_mode에 따라 좌표를 변환한다.

    - 'identity' 또는 'v9': 입력 좌표를 그대로 사용 (항공뷰 Homography가 대상 맵과 동일한 경우)
    - 'canonical_to_v9': 정본(2.5x2.4m) 항공뷰 좌표를 실물 로봇 cobot_map_v9로 변환
    - 'v9_to_canonical': cobot_map_v9 기준 좌표를 정본(2.5x2.4m) 좌표로 변환
    """
    mode = (frame_mode or "identity").strip().lower()
    if mode == "canonical_to_v9":
        return canonical_to_v9(x, y)
    if mode == "v9_to_canonical":
        return v9_to_canonical(x, y)
    return float(x), float(y)


def _finite(val) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def validate(
    payload: dict, allowed_robots: Iterable[str] = ALLOWED_ROBOTS
) -> Tuple[bool, Optional[str], Optional[dict]]:
    if not isinstance(payload, dict):
        return False, "payload must be a JSON object", None
    for f in REQUIRED_FIELDS:
        if f not in payload:
            return False, f"missing field: {f}", None
    rid = payload["robot_id"]
    if not isinstance(rid, str) or rid not in set(allowed_robots):
        return False, f"invalid robot_id: {rid!r}", None
    for nf in ("x", "y", "yaw", "reproj_error", "source_ts"):
        if not _finite(payload[nf]):
            return False, f"non-finite {nf}", None
    reproj = float(payload["reproj_error"])
    if reproj < 0.0 or reproj > MAX_REPROJ_ERROR_PX:
        return False, f"reproj_error out of range: {reproj}", None
    yaw = float(payload["yaw"])
    if yaw < -math.pi * 2 or yaw > math.pi * 2:
        return False, f"yaw out of range: {yaw}", None
    clean = {
        "robot_id": rid,
        "x": float(payload["x"]),
        "y": float(payload["y"]),
        "yaw": float(payload["yaw"]),
        "reproj_error": reproj,
        "source_ts": int(payload["source_ts"]),
    }
    if "frame_id" in payload and isinstance(payload["frame_id"], str):
        clean["frame_id"] = payload["frame_id"]
    return True, None, clean


def validate_pose_fix(
    payload: dict, allowed_robots: Iterable[str] = ALLOWED_ROBOTS
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """태블릿 로컬라이저가 송신하는 PoseFix JSON 스키마를 검증하고 내부 포맷으로 정규화한다."""
    if not isinstance(payload, dict):
        return False, "payload must be a JSON object", None
    for f in POSE_FIX_TOP_FIELDS:
        if f not in payload:
            return False, f"missing field: {f}", None
    hdr = payload["header"]
    if not isinstance(hdr, dict):
        return False, "header must be an object", None
    if "stamp_ns" not in hdr or "frame_id" not in hdr:
        return False, "header requires stamp_ns and frame_id", None
    if not _finite(hdr["stamp_ns"]) or int(hdr["stamp_ns"]) < 0:
        return False, "invalid header.stamp_ns", None
    if not isinstance(hdr["frame_id"], str) or not hdr["frame_id"]:
        return False, "invalid header.frame_id", None
    translated = {
        "robot_id": payload["robot_id"],
        "x": payload["x"],
        "y": payload["y"],
        "yaw": payload["yaw"],
        "reproj_error": payload["reprojection_error_px"],
        "source_ts": int(hdr["stamp_ns"]) // 1_000_000,
    }
    ok, err, clean = validate(translated, allowed_robots=allowed_robots)
    if not ok or clean is None:
        return False, err, None
    clean["frame_id"] = hdr["frame_id"]
    if "confidence" in payload and _finite(payload["confidence"]):
        clean["confidence"] = float(payload["confidence"])
    if "marker_id" in payload and _finite(payload["marker_id"]):
        clean["marker_id"] = int(payload["marker_id"])
    return True, None, clean


class VisionPoseStore:
    """수신 시각(receiver clock) 기준 500ms 신선도 게이트를 적용하는 비전 위치 저장소."""

    def __init__(
        self,
        allowed_robots: Iterable[str] = ALLOWED_ROBOTS,
        stale_after_ms: int = STALE_AFTER_MS,
        clock_ms=None,
    ) -> None:
        self.allowed_robots = tuple(allowed_robots)
        self.stale_after_ms = int(stale_after_ms)
        self._clock = clock_ms or (lambda: int(time.time() * 1000))
        self._by_robot: Dict[str, dict] = {}
        self.ingested = 0
        self.rejected = 0

    def ingest(self, payload: dict) -> Tuple[bool, Optional[str], Optional[dict]]:
        ok, err, clean = validate(payload, self.allowed_robots)
        if not ok or clean is None:
            self.rejected += 1
            return False, err, None
        now = self._clock()
        record = {**clean, "received_ts": now}
        self._by_robot[clean["robot_id"]] = record
        self.ingested += 1
        return True, None, self._decorate(record, now)

    def ingest_pose_fix(self, payload: dict) -> Tuple[bool, Optional[str], Optional[dict]]:
        ok, err, clean = validate_pose_fix(payload, self.allowed_robots)
        if not ok or clean is None:
            self.rejected += 1
            return False, err, None
        now = self._clock()
        record = {**clean, "received_ts": now}
        self._by_robot[clean["robot_id"]] = record
        self.ingested += 1
        return True, None, self._decorate(record, now)

    def _decorate(self, rec: Optional[dict], now: int) -> dict:
        if rec is None:
            return {"status": VISION_NEVER, "stale": True, "age_ms": None, "pose": None}
        age = max(0, now - rec["received_ts"])
        fresh = age <= self.stale_after_ms
        return {
            "status": VISION_FRESH if fresh else VISION_STALE,
            "stale": not fresh,
            "age_ms": age,
            "pose": dict(rec),
        }

    def get(self, robot_id: str) -> dict:
        now = self._clock()
        return self._decorate(self._by_robot.get(robot_id), now)

    def snapshot(self) -> Dict[str, dict]:
        now = self._clock()
        return {
            rid: self._decorate(self._by_robot.get(rid), now)
            for rid in self.allowed_robots
        }
