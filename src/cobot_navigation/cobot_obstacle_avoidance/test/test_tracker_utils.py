"""tracker_utils 단위 테스트 (ROS 불필요)."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_obstacle_avoidance.tracker_utils import (  # noqa: E402
    min_ttc, ObstacleTracker, time_to_collision, to_robot, to_world)


def test_world_robot_roundtrip():
    pose = (1.0, 2.0, 0.7)
    p = (0.3, -0.2)
    q = to_robot(to_world(p, pose), pose)
    assert math.isclose(q[0], p[0]) and math.isclose(q[1], p[1])


def test_tracker_estimates_velocity():
    tr = ObstacleTracker(match_dist=0.25, max_age=0.5, alpha=1.0, min_hits=3)
    for k in range(5):
        tr.update([(1.0 + 0.02 * k, 0.0)], 0.1 * k)
    assert len(tr.tracks) == 1
    assert math.isclose(tr.tracks[0].vx, 0.2, rel_tol=1e-6)
    assert len(tr.moving_tracks(0.08)) == 1


def test_tracker_static_object_not_moving():
    tr = ObstacleTracker(0.25, 0.5, 0.4, 3)
    for k in range(5):
        tr.update([(1.0, 0.5)], 0.1 * k)
    assert tr.moving_tracks(0.08) == []


def test_tracker_drops_old_tracks():
    tr = ObstacleTracker(0.25, 0.5, 0.4, 3)
    tr.update([(1.0, 0.0)], 0.0)
    tr.update([], 1.0)
    assert tr.tracks == []


def test_ttc_head_on():
    # 1 m 앞에서 0.5 m/s 로 다가옴, 반경 0.25 -> 0.75/0.5 = 1.5 s
    assert math.isclose(time_to_collision(1.0, 0.0, -0.5, 0.0, 0.25), 1.5)


def test_ttc_receding_or_passing_is_inf():
    assert time_to_collision(1.0, 0.0, 0.5, 0.0, 0.25) == math.inf
    assert time_to_collision(1.0, 1.0, -0.5, 0.0, 0.25) == math.inf


def test_ttc_inside_radius_is_zero():
    assert time_to_collision(0.1, 0.0, 0.0, 0.0, 0.25) == 0.0


def test_min_ttc_uses_relative_velocity():
    tr = ObstacleTracker(0.25, 0.5, 1.0, 1)
    tr.update([(1.0, 0.0)], 0.0)
    tr.update([(0.95, 0.0)], 0.1)   # -0.5 m/s
    ttc = min_ttc(tr.tracks, (0.0, 0.0, 0.0), (0.0, 0.0), 0.25)
    assert math.isclose(ttc, (0.95 - 0.25) / 0.5)
