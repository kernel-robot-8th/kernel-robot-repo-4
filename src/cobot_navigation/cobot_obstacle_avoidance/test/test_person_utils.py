"""person_utils 단위 테스트 (ROS 불필요)."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_obstacle_avoidance.person_utils import (  # noqa: E402
    bbox_bearing_interval, camera_intrinsics, person_points)


def test_camera_intrinsics_fallback_from_fov():
    fx, cx = camera_intrinsics(0.0, 0.0, 640, math.radians(90))
    assert math.isclose(fx, 320.0) and cx == 320.0
    assert camera_intrinsics(500.0, 300.0, 640, 1.0) == (500.0, 300.0)


def test_bbox_center_is_straight_ahead():
    lo, hi = bbox_bearing_interval(320, 64, 320, 320, 0.0)
    assert math.isclose(lo, -hi)
    assert lo < 0 < hi


def test_bbox_on_right_side_gives_negative_angles():
    lo, hi = bbox_bearing_interval(560, 40, 320, 320, 0.0)
    assert hi < 0


def test_person_points_selects_by_bearing_and_range():
    pts = [(1.0, 0.0), (1.0, 0.5), (5.0, 0.0), (-1.0, 0.0)]
    sel = person_points(pts, [(-0.1, 0.1)], (0.0, 0.0, 0.0), 3.0)
    assert sel == [(1.0, 0.0)]


def test_person_points_uses_camera_offset():
    # 카메라가 로봇 중심보다 0.5 m 앞이면 (0.6, 0.1) 은 카메라에서 45° 왼쪽
    sel = person_points([(0.6, 0.1)], [(0.7, 0.9)], (0.5, 0.0, 0.0), 3.0)
    assert sel == [(0.6, 0.1)]


def test_no_detection_no_person():
    assert person_points([(1.0, 0.0)], [], (0.0, 0.0, 0.0), 3.0) == []
