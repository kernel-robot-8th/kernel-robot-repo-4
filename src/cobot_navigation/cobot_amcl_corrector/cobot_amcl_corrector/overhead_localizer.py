"""오버헤드 카메라 ArUco 마커 기반 로봇 2D 위치(x, y, yaw) 추정기.

이전 프로젝트(pinky_pro_team11/tablet/vision)의 OverheadLocalizer, PoseFix, TabletVisionService를
현재 프로젝트 3대 로봇(pinky1, pinky2, pinky3) 규격에 맞게 통합 이식한 모듈이다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class Header:
    stamp_ns: int = 0
    frame_id: str = "map"


@dataclass(frozen=True)
class PoseFix:
    header: Header = field(default_factory=Header)
    robot_id: str = "pinky1"
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    reprojection_error_px: float = 0.0
    confidence: float = 1.0
    marker_id: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RobotMarker:
    marker_id: int
    robot_id: str
    yaw_offset_rad: float = 0.0


@dataclass(frozen=True)
class OverheadConfig:
    reference_markers_map: Dict[int, Tuple[float, float]] = field(
        default_factory=lambda: {
            0: (0.0, 0.0),
            1: (2.5, 0.0),
            2: (2.5, 2.4),
            3: (0.0, 2.4),
        }
    )
    robots: Dict[int, RobotMarker] = field(
        default_factory=lambda: {
            10: RobotMarker(10, "pinky1", 0.0),
            11: RobotMarker(11, "pinky2", 0.0),
            12: RobotMarker(12, "pinky3", 0.0),
        }
    )
    aruco_dict_id: int = 0  # cv2.aruco.DICT_4X4_50 == 0


@dataclass(frozen=True)
class Fix:
    robot_id: str
    marker_id: int
    x: float
    y: float
    yaw: float
    reproj_error_px: float
    confidence: float


class OverheadLocalizer:
    """바닥 기준 마커 4개(ID 0~3)로 3x3 Homography를 계산하고 로봇 마커(ID 10~12) 좌표를 산출한다."""

    def __init__(self, cfg: OverheadConfig | None = None) -> None:
        self.cfg = cfg or OverheadConfig()
        self.H: Optional[np.ndarray] = None
        self.H_reproj_error: float = float("inf")
        self._detector = None
        if cv2 is not None and hasattr(cv2, "aruco"):
            dictionary = cv2.aruco.getPredefinedDictionary(self.cfg.aruco_dict_id)
            params = cv2.aruco.DetectorParameters()
            self._detector = cv2.aruco.ArucoDetector(dictionary, params)

    def detect_markers(self, gray: np.ndarray) -> Dict[int, np.ndarray]:
        if self._detector is None:
            return {}
        corners, ids, _ = self._detector.detectMarkers(gray)
        if ids is None:
            return {}
        return {
            int(mid): c.reshape(4, 2).astype(np.float64)
            for c, mid in zip(corners, ids.flatten())
        }

    def update_homography(self, detected: Dict[int, np.ndarray]) -> bool:
        src, dst = [], []
        for mid, map_xy in self.cfg.reference_markers_map.items():
            if mid in detected:
                src.append(detected[mid].mean(axis=0))
                dst.append(map_xy)
        if len(src) < 4:
            return False
        src_a = np.asarray(src, dtype=np.float64)
        dst_a = np.asarray(dst, dtype=np.float64)
        H, _ = self._compute_homography(src_a, dst_a)
        if H is None:
            return False
        proj = self._apply_H(H, src_a)
        err = float(np.linalg.norm(proj - dst_a, axis=1).mean())
        self.H = H
        self.H_reproj_error = err
        return True

    @staticmethod
    def _compute_homography(
        src_a: np.ndarray, dst_a: np.ndarray
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if cv2 is not None:
            return cv2.findHomography(src_a, dst_a, method=0)
        # DLT fallback when OpenCV is unavailable in pure-Python test environments
        n = src_a.shape[0]
        if n < 4:
            return None, None
        A = []
        for i in range(n):
            x, y = src_a[i, 0], src_a[i, 1]
            u, v = dst_a[i, 0], dst_a[i, 1]
            A.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
            A.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
        _, _, vt = np.linalg.svd(np.asarray(A, dtype=np.float64))
        h = vt[-1].reshape(3, 3)
        if abs(h[2, 2]) < 1e-12:
            return None, None
        return h / h[2, 2], None

    @staticmethod
    def _apply_H(H: np.ndarray, pts_px: np.ndarray) -> np.ndarray:
        ones = np.ones((pts_px.shape[0], 1), dtype=np.float64)
        hom = (H @ np.hstack([pts_px, ones]).T).T
        return hom[:, :2] / hom[:, 2:3]

    def px_to_map(self, pt_px: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        if self.H is None:
            return None
        p = self._apply_H(self.H, np.asarray([pt_px], dtype=np.float64))[0]
        return float(p[0]), float(p[1])

    def robot_pose(self, marker_id: int, corners_px: np.ndarray) -> Optional[Fix]:
        if self.H is None or marker_id not in self.cfg.robots:
            return None
        spec = self.cfg.robots[marker_id]
        pts_map = self._apply_H(self.H, corners_px)
        center = pts_map.mean(axis=0)
        front = 0.5 * (pts_map[0] + pts_map[1])
        back = 0.5 * (pts_map[2] + pts_map[3])
        vec = front - back
        yaw = math.atan2(float(vec[1]), float(vec[0])) + spec.yaw_offset_rad
        yaw = (yaw + math.pi) % (2.0 * math.pi) - math.pi
        conf = float(max(0.0, min(1.0, 1.0 - self.H_reproj_error / 0.05)))
        return Fix(
            robot_id=spec.robot_id,
            marker_id=marker_id,
            x=float(center[0]),
            y=float(center[1]),
            yaw=yaw,
            reproj_error_px=self.H_reproj_error,
            confidence=conf,
        )

    def process_frame(self, gray: np.ndarray) -> List[Fix]:
        detected = self.detect_markers(gray)
        self.update_homography(detected)
        if self.H is None:
            return []
        fixes: List[Fix] = []
        for mid, corners in detected.items():
            if mid in self.cfg.robots:
                fix = self.robot_pose(mid, corners)
                if fix is not None:
                    fixes.append(fix)
        return fixes


class TabletVisionService:
    """태블릿 비전 런타임: 마커 검출 결과를 PoseFix 레코드로 변환하고 가림(occlusion) 상태를 추적한다."""

    def __init__(
        self,
        cfg: OverheadConfig | None = None,
        frame_id: str = "map",
        occlusion_after_s: float = 0.5,
    ) -> None:
        self.localizer = OverheadLocalizer(cfg)
        self.frame_id = frame_id
        self.occlusion_after_s = occlusion_after_s
        self.last_seen_ns: Dict[str, int] = {}
        self.frames_processed = 0
        self.fixes_emitted = 0

    def process_detected(
        self, detected: Dict[int, np.ndarray], now_ns: Optional[int] = None
    ) -> List[PoseFix]:
        stamp = now_ns if now_ns is not None else time.time_ns()
        self.frames_processed += 1
        self.localizer.update_homography(detected)
        if self.localizer.H is None:
            return []
        out: List[PoseFix] = []
        for mid, corners in detected.items():
            fix = self.localizer.robot_pose(mid, corners)
            if fix is None:
                continue
            self.last_seen_ns[fix.robot_id] = stamp
            self.fixes_emitted += 1
            out.append(
                PoseFix(
                    header=Header(stamp_ns=stamp, frame_id=self.frame_id),
                    robot_id=fix.robot_id,
                    x=fix.x,
                    y=fix.y,
                    yaw=fix.yaw,
                    reprojection_error_px=fix.reproj_error_px,
                    confidence=fix.confidence,
                    marker_id=fix.marker_id,
                )
            )
        return out

    def is_occluded(self, robot_id: str, now_ns: Optional[int] = None) -> bool:
        stamp = now_ns if now_ns is not None else time.time_ns()
        last = self.last_seen_ns.get(robot_id)
        if last is None:
            return True
        return (stamp - last) > int(self.occlusion_after_s * 1e9)
