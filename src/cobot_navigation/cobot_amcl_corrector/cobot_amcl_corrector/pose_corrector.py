"""AMCL 드리프트 감지 및 원샷(One-Shot) /initialpose 보정 판정 엔진.

이전 프로젝트(pinky_pro_team11/pinky_fleet_agent/pose_fuser.py)의 각도 래핑(wrap),
변위 계산(pose_diff), 3회 연속 확인(confirm_count) 로직을 현재 팀 프로젝트의
Nav2 AMCL 구조(/pinkyN/amcl_pose 비교 -> /pinkyN/initialpose 원샷 재초기화)에 맞게 재설계한 모듈이다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time
from typing import Dict, Iterable, Optional, Tuple

from .vision_ingest import (
    ALLOWED_ROBOTS,
    VISION_FRESH,
    VisionPoseStore,
    transform_xy,
)

STATIONARY_STATES = frozenset(
    {"IDLE", "QUEUEING", "HOLDING_ZONE", "STOPPED", "WAITING", "READY"}
)


def wrap_angle(angle_rad: float) -> float:
    """각도를 [-pi, pi) 범위로 정규화한다."""
    return (float(angle_rad) + math.pi) % (2.0 * math.pi) - math.pi


def pose_diff(
    pose_a: Tuple[float, float, float], pose_b: Tuple[float, float, float]
) -> Tuple[float, float]:
    """두 2D 포즈 (x, y, yaw) 간의 유클리드 거리(m)와 절대 각도차(rad)를 반환한다."""
    dx = float(pose_a[0]) - float(pose_b[0])
    dy = float(pose_a[1]) - float(pose_b[1])
    dyaw = abs(wrap_angle(float(pose_a[2]) - float(pose_b[2])))
    return math.hypot(dx, dy), dyaw


@dataclass
class InitialPoseCommand:
    """/pinkyN/initialpose 토픽으로 발행할 원샷 보정 명령."""

    robot_id: str
    frame_id: str
    x: float
    y: float
    yaw: float
    cov_x: float
    cov_y: float
    cov_yaw: float
    reason: str
    drift_dist_m: float
    drift_yaw_rad: float
    reproj_error_px: float
    timestamp_sec: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RobotCorrectionTracker:
    robot_id: str
    amcl_pose: Optional[Tuple[float, float, float]] = None
    amcl_updated_sec: float = 0.0
    patrol_state: str = "IDLE"
    linear_speed_mps: float = 0.0
    confirm_streak: int = 0
    last_correction_sec: float = -1e9
    corrections_emitted: int = 0
    last_drift_dist_m: float = 0.0
    last_drift_yaw_rad: float = 0.0
    last_reason: str = "NONE"


class AmclVisionCorrector:
    """항공뷰 비전 좌표와 로봇 AMCL 위치 간의 오차를 감시하고 안전한 시점에만 보정 명령을 생성한다.

    설계 핵심 (주행 중 버벅임 방지 4중 게이트):
    1. 신선도(Freshness): 수신 시각 기준 500ms 이내(VISION_FRESH) 및 reproj_error <= 4.0px 데이터만 사용.
    2. 정지/대기 상태 게이트: 주행 중(MOVING_TO_*, ENTERING_ZONE 등)에는 로컬 코스트맵 리셋 방지를 위해
       자동 보정을 보류하고 IDLE/QUEUEING/HOLDING_ZONE/STOPPED 상태에서만 자동 보정 수행.
    3. 3회 연속 확인(confirm_count=3): 단일 프레임 마커 노이즈로 인한 오보정을 막기 위해
       임계치(거리 >= 0.15m 또는 각도 >= 20도) 이상 오차가 3회 연속 관측될 때만 발화.
    4. 쿨다운(cooldown_sec=5.0s): 원샷 /initialpose 발행 후 최소 5초간 재발행 억제.
    """

    def __init__(
        self,
        store: Optional[VisionPoseStore] = None,
        allowed_robots: Iterable[str] = ALLOWED_ROBOTS,
        drift_dist_m: float = 0.15,
        drift_yaw_rad: float = math.radians(20.0),
        confirm_count: int = 3,
        cooldown_sec: float = 5.0,
        max_stationary_speed_mps: float = 0.03,
        frame_mode: str = "identity",
        target_frame_id: str = "map",
        cov_x: float = 0.04,
        cov_y: float = 0.04,
        cov_yaw: float = 0.05,
        auto_correct_enabled: bool = True,
        clock_sec=None,
    ) -> None:
        self.allowed_robots = tuple(allowed_robots)
        self.store = store or VisionPoseStore(allowed_robots=self.allowed_robots)
        self.drift_dist_m = float(drift_dist_m)
        self.drift_yaw_rad = float(drift_yaw_rad)
        self.confirm_count = max(1, int(confirm_count))
        self.cooldown_sec = float(cooldown_sec)
        self.max_stationary_speed_mps = float(max_stationary_speed_mps)
        self.frame_mode = frame_mode
        self.target_frame_id = target_frame_id
        self.cov_x = float(cov_x)
        self.cov_y = float(cov_y)
        self.cov_yaw = float(cov_yaw)
        self.auto_correct_enabled = bool(auto_correct_enabled)
        self._clock_sec = clock_sec or time.time

        self.trackers: Dict[str, RobotCorrectionTracker] = {
            rid: RobotCorrectionTracker(robot_id=rid) for rid in self.allowed_robots
        }

    def update_amcl_pose(
        self, robot_id: str, x: float, y: float, yaw: float, now_sec: Optional[float] = None
    ) -> None:
        if robot_id not in self.trackers:
            return
        now = now_sec if now_sec is not None else self._clock_sec()
        tr = self.trackers[robot_id]
        tr.amcl_pose = (float(x), float(y), wrap_angle(yaw))
        tr.amcl_updated_sec = float(now)

    def update_robot_state(
        self, robot_id: str, patrol_state: str, linear_speed_mps: float = 0.0
    ) -> None:
        if robot_id not in self.trackers:
            return
        tr = self.trackers[robot_id]
        # patrol_status 문자열이 "HOLDING_ZONE:zone_A" 형태일 경우 앞 토큰 추출
        state_token = (patrol_state or "IDLE").split(":")[0].strip().upper()
        tr.patrol_state = state_token
        tr.linear_speed_mps = abs(float(linear_speed_mps))

    def is_robot_stationary(self, robot_id: str) -> bool:
        tr = self.trackers.get(robot_id)
        if tr is None:
            return False
        if tr.linear_speed_mps > self.max_stationary_speed_mps:
            return False
        return tr.patrol_state in STATIONARY_STATES

    def _converted_vision_pose(self, raw_pose: dict) -> Tuple[float, float, float]:
        vx, vy = transform_xy(raw_pose["x"], raw_pose["y"], self.frame_mode)
        vyaw = wrap_angle(raw_pose["yaw"])
        return vx, vy, vyaw

    def evaluate_robot(
        self, robot_id: str, now_sec: Optional[float] = None
    ) -> Optional[InitialPoseCommand]:
        """최신 비전 포즈와 AMCL 포즈를 비교하여 자동 보정이 필요한 경우 InitialPoseCommand를 반환한다."""
        if robot_id not in self.trackers:
            return None
        tr = self.trackers[robot_id]
        now = now_sec if now_sec is not None else self._clock_sec()

        vision_entry = self.store.get(robot_id)
        if vision_entry["status"] != VISION_FRESH or vision_entry["pose"] is None:
            tr.confirm_streak = 0
            tr.last_reason = f"SKIP_{vision_entry['status']}"
            return None

        raw_pose = vision_entry["pose"]
        vx, vy, vyaw = self._converted_vision_pose(raw_pose)

        if tr.amcl_pose is None:
            tr.last_drift_dist_m = 0.0
            tr.last_drift_yaw_rad = 0.0
            tr.last_reason = "WAIT_AMCL_POSE"
            return None

        dist, dyaw = pose_diff((vx, vy, vyaw), tr.amcl_pose)
        tr.last_drift_dist_m = dist
        tr.last_drift_yaw_rad = dyaw

        if not self.auto_correct_enabled:
            tr.confirm_streak = 0
            tr.last_reason = "AUTO_DISABLED"
            return None

        if not self.is_robot_stationary(robot_id):
            tr.confirm_streak = 0
            tr.last_reason = f"MOVING({tr.patrol_state})"
            return None

        if (now - tr.last_correction_sec) < self.cooldown_sec:
            tr.last_reason = "COOLDOWN"
            return None

        exceeded = (dist >= self.drift_dist_m) or (dyaw >= self.drift_yaw_rad)
        if not exceeded:
            tr.confirm_streak = 0
            tr.last_reason = "IN_TOLERANCE"
            return None

        tr.confirm_streak += 1
        if tr.confirm_streak < self.confirm_count:
            tr.last_reason = f"CONFIRMING({tr.confirm_streak}/{self.confirm_count})"
            return None

        # 3회 연속 드리프트 확인 완료 -> 원샷 보정 명령 생성 및 상태 리셋
        tr.confirm_streak = 0
        tr.last_correction_sec = float(now)
        tr.corrections_emitted += 1
        tr.last_reason = "AUTO_DRIFT_CORRECTED"
        # 보정 직후 AMCL 예상 위치를 비전 좌표로 낙관적 갱신하여 중복 발행 방지
        tr.amcl_pose = (vx, vy, vyaw)

        return InitialPoseCommand(
            robot_id=robot_id,
            frame_id=self.target_frame_id,
            x=vx,
            y=vy,
            yaw=vyaw,
            cov_x=self.cov_x,
            cov_y=self.cov_y,
            cov_yaw=self.cov_yaw,
            reason="auto_drift",
            drift_dist_m=round(dist, 4),
            drift_yaw_rad=round(dyaw, 4),
            reproj_error_px=float(raw_pose["reproj_error"]),
            timestamp_sec=float(now),
        )

    def manual_sync(
        self,
        robot_id: str,
        force_while_moving: bool = False,
        now_sec: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[InitialPoseCommand]]:
        """운용자(태블릿/웹 콘솔)가 요청한 수동 원샷 AMCL 위치 동기화를 수행한다."""
        if robot_id not in self.trackers:
            return False, f"unknown robot_id: {robot_id}", None
        tr = self.trackers[robot_id]
        now = now_sec if now_sec is not None else self._clock_sec()

        vision_entry = self.store.get(robot_id)
        if vision_entry["status"] != VISION_FRESH or vision_entry["pose"] is None:
            tr.last_reason = f"MANUAL_REJECT_{vision_entry['status']}"
            return (
                False,
                f"{robot_id} vision status is {vision_entry['status']} (age={vision_entry['age_ms']}ms)",
                None,
            )

        if not force_while_moving and not self.is_robot_stationary(robot_id):
            tr.last_reason = f"MANUAL_REJECT_MOVING({tr.patrol_state})"
            return (
                False,
                f"{robot_id} is currently moving ({tr.patrol_state}); stop or wait for IDLE/HOLDING_ZONE",
                None,
            )

        raw_pose = vision_entry["pose"]
        vx, vy, vyaw = self._converted_vision_pose(raw_pose)
        if tr.amcl_pose is not None:
            dist, dyaw = pose_diff((vx, vy, vyaw), tr.amcl_pose)
        else:
            dist, dyaw = 0.0, 0.0

        tr.confirm_streak = 0
        tr.last_correction_sec = float(now)
        tr.corrections_emitted += 1
        tr.last_drift_dist_m = dist
        tr.last_drift_yaw_rad = dyaw
        tr.last_reason = "MANUAL_SYNC_CORRECTED"
        tr.amcl_pose = (vx, vy, vyaw)

        cmd = InitialPoseCommand(
            robot_id=robot_id,
            frame_id=self.target_frame_id,
            x=vx,
            y=vy,
            yaw=vyaw,
            cov_x=self.cov_x,
            cov_y=self.cov_y,
            cov_yaw=self.cov_yaw,
            reason="manual_sync",
            drift_dist_m=round(dist, 4),
            drift_yaw_rad=round(dyaw, 4),
            reproj_error_px=float(raw_pose["reproj_error"]),
            timestamp_sec=float(now),
        )
        return True, "ok", cmd

    def status_snapshot(self) -> dict:
        vision_snap = self.store.snapshot()
        robots_out = {}
        for rid, tr in self.trackers.items():
            v_info = vision_snap.get(rid, {})
            converted_pose = None
            if v_info.get("pose") is not None:
                vx, vy, vyaw = self._converted_vision_pose(v_info["pose"])
                converted_pose = {"x": vx, "y": vy, "yaw": round(vyaw, 4)}
            robots_out[rid] = {
                "vision_status": v_info.get("status", "VISION_NEVER"),
                "vision_age_ms": v_info.get("age_ms"),
                "vision_pose_map": converted_pose,
                "reproj_error_px": (
                    v_info["pose"]["reproj_error"] if v_info.get("pose") else None
                ),
                "amcl_pose": (
                    {
                        "x": round(tr.amcl_pose[0], 4),
                        "y": round(tr.amcl_pose[1], 4),
                        "yaw": round(tr.amcl_pose[2], 4),
                    }
                    if tr.amcl_pose is not None
                    else None
                ),
                "patrol_state": tr.patrol_state,
                "stationary": self.is_robot_stationary(rid),
                "drift_dist_m": round(tr.last_drift_dist_m, 4),
                "drift_yaw_deg": round(math.degrees(tr.last_drift_yaw_rad), 2),
                "confirm_streak": tr.confirm_streak,
                "confirm_target": self.confirm_count,
                "corrections_emitted": tr.corrections_emitted,
                "last_reason": tr.last_reason,
            }
        return {
            "auto_correct_enabled": self.auto_correct_enabled,
            "frame_mode": self.frame_mode,
            "drift_dist_threshold_m": self.drift_dist_m,
            "drift_yaw_threshold_deg": round(math.degrees(self.drift_yaw_rad), 2),
            "stale_after_ms": self.store.stale_after_ms,
            "ingested_total": self.store.ingested,
            "rejected_total": self.store.rejected,
            "robots": robots_out,
        }
