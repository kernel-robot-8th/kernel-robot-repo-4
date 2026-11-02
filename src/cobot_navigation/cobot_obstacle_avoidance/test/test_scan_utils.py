"""scan_utils 단위 테스트 (ROS 불필요)."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_obstacle_avoidance.scan_utils import (  # noqa: E402
    choose_free_direction, cluster_extent, cluster_points, corridor_clearance,
    polar_histogram, scan_to_points, sector_angle)


def _scan(n, value):
    return [value] * n


def test_scan_to_points_drops_invalid_and_keeps_order():
    ranges = [1.0, math.inf, float('nan'), 0.01, 2.0]
    pts = scan_to_points(ranges, 0.0, 0.1, 0.05, 12.0)
    assert len(pts) == 2
    assert pts[0] == (1.0, 0.0)


def test_scan_to_points_applies_flipped_lidar():
    """핑키 라이다는 yaw=pi 로 달려 있어 라이다 각도 0 이 로봇 뒤쪽이다."""
    pts = scan_to_points([1.0], 0.0, 0.1, 0.05, 12.0, yaw=math.pi)
    assert math.isclose(pts[0][0], -1.0, abs_tol=1e-9)
    assert math.isclose(pts[0][1], 0.0, abs_tol=1e-9)


def test_corridor_clearance_front_and_rear():
    pts = [(0.5, 0.0), (0.3, 0.5), (-0.4, 0.05)]
    assert math.isclose(corridor_clearance(pts, 0.1, 0.06, True), 0.44)
    assert math.isclose(corridor_clearance(pts, 0.1, 0.06, False), 0.34)
    assert corridor_clearance([(0.3, 0.5)], 0.1, 0.06, True) == math.inf


def test_cluster_points_splits_on_gap_and_merges_wraparound():
    pts = [(1.0, 0.0), (1.0, 0.05), (2.0, 2.0), (2.0, 2.05), (1.0, -0.05)]
    clusters = cluster_points(pts, 0.1)
    assert len(clusters) == 2
    assert len(clusters[0]) == 3   # 처음 두 점 + 마지막 점 (360° 이어붙임)
    assert cluster_extent([(0.0, 0.0), (0.3, 0.4)]) == 0.5


def test_polar_histogram_records_nearest():
    hist = polar_histogram([(1.0, 0.0), (0.5, 0.0), (0.0, 1.0)], 4, 3.0)
    front = min(range(4), key=lambda i: abs(sector_angle(i, 4)))
    assert min(hist) == 0.5
    assert hist.count(3.0) == 2
    assert front in (1, 2)


def test_choose_free_direction_prefers_front_when_clear():
    hist = [2.0] * 72
    d = choose_free_direction(hist, 0.35, 0.1, 1.75)
    assert abs(d) <= math.radians(5)


def test_choose_free_direction_goes_around_blocked_front():
    n = 72
    hist = [2.0] * n
    for i in range(n):
        if abs(sector_angle(i, n)) < math.radians(30):
            hist[i] = 0.2
    d = choose_free_direction(hist, 0.35, 0.1, 1.75)
    assert d is not None and abs(d) > math.radians(30)


def test_choose_free_direction_respects_prefer_sign():
    n = 72
    hist = [2.0] * n
    for i in range(n):
        if abs(sector_angle(i, n)) < math.radians(30):
            hist[i] = 0.2
    assert choose_free_direction(hist, 0.35, 0.1, 1.75, prefer_sign=1.0) > 0
    assert choose_free_direction(hist, 0.35, 0.1, 1.75, prefer_sign=-1.0) < 0


def test_choose_free_direction_none_when_surrounded():
    assert choose_free_direction([0.2] * 72, 0.35, 0.1, 1.75) is None
