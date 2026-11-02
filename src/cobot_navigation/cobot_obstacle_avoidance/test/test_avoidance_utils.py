"""avoidance_utils 상태 머신 단위 테스트 (ROS 불필요)."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_obstacle_avoidance.avoidance_utils import (  # noqa: E402
    AVOID, AvoidanceController, AvoidanceParams, BACKUP, PASS, Perception, SLOW, STOP, WAIT)
from cobot_obstacle_avoidance.scan_utils import sector_angle  # noqa: E402

N = 72


def _hist(blocked_deg=None, value=2.0):
    hist = [value] * N
    if blocked_deg is not None:
        for i in range(N):
            if abs(sector_angle(i, N)) < math.radians(blocked_deg):
                hist[i] = 0.1
    return hist


def _ctrl():
    return AvoidanceController(AvoidanceParams())


def test_disabled_passes_nav_command():
    c = _ctrl()
    per = Perception(front=0.0, rear=0.0, ttc=0.0, hist=_hist(value=0.1))
    assert c.step(False, 0.1, 0.2, per, 0.0) == (PASS, 0.1, 0.2)


def test_clear_path_passes():
    c = _ctrl()
    assert c.step(True, 0.1, 0.0, Perception(hist=_hist()), 0.0) == (PASS, 0.1, 0.0)


def test_slow_when_close():
    c = _ctrl()
    state, v, _ = c.step(True, 0.1, 0.0, Perception(front=0.26, hist=_hist()), 0.0)
    assert state == SLOW and 0.0 < v < 0.1


def test_stop_then_avoid_after_block_time():
    c = _ctrl()
    per = Perception(front=0.05, hist=_hist(30))
    assert c.step(True, 0.1, 0.0, per, 0.0)[:1] == (STOP,)
    assert c.step(True, 0.1, 0.0, per, 1.0)[0] == STOP
    state, v, w = c.step(True, 0.1, 0.0, per, 2.5)
    assert state == AVOID and w != 0.0 and v == 0.0   # 아직 정렬 전이라 회전만


def test_stop_hysteresis():
    c = _ctrl()
    c.step(True, 0.1, 0.0, Perception(front=0.05, hist=_hist()), 0.0)
    assert c.step(True, 0.1, 0.0, Perception(front=0.15, hist=_hist()), 0.1)[0] == STOP
    assert c.step(True, 0.1, 0.0, Perception(front=0.5, hist=_hist()), 0.2)[0] == PASS


def test_avoid_returns_to_pass_when_clear():
    c = _ctrl()
    blocked = Perception(front=0.05, hist=_hist(30))
    c.step(True, 0.1, 0.0, blocked, 0.0)
    c.step(True, 0.1, 0.0, blocked, 2.5)
    assert c.state == AVOID
    clear = Perception(front=1.0, hist=_hist())
    assert c.step(True, 0.1, 0.0, clear, 3.0)[0] == AVOID       # avoid_min_time 전
    assert c.step(True, 0.1, 0.0, clear, 4.0)[0] == PASS


def test_backup_when_no_free_direction():
    c = _ctrl()
    boxed = Perception(front=0.05, rear=1.0, hist=_hist(value=0.1))
    c.step(True, 0.1, 0.0, boxed, 0.0)
    state, v, _ = c.step(True, 0.1, 0.0, boxed, 2.5)
    assert state == BACKUP and v < 0.0
    assert c.step(True, 0.1, 0.0, boxed, 3.0)[0] == BACKUP


def test_no_backup_when_rear_blocked():
    c = _ctrl()
    boxed = Perception(front=0.05, rear=0.05, hist=_hist(value=0.1))
    c.step(True, 0.1, 0.0, boxed, 0.0)
    assert c.step(True, 0.1, 0.0, boxed, 2.5) == (AVOID, 0.0, 0.0)


def test_avoid_timeout_hands_back_to_nav2():
    c = _ctrl()
    boxed = Perception(front=0.05, rear=1.0, hist=_hist(value=0.1))
    c.step(True, 0.1, 0.0, boxed, 0.0)
    t = 2.5
    while t < 2.5 + c.p.avoid_timeout:
        c.step(True, 0.1, 0.0, boxed, t)
        t += 0.5
    assert c.step(True, 0.1, 0.0, boxed, t + 0.1)[0] == PASS


def test_wait_for_moving_obstacle_then_avoid():
    c = _ctrl()
    per = Perception(front=1.0, ttc=1.0, hist=_hist())
    assert c.step(True, 0.1, 0.0, per, 0.0)[0] == SLOW      # 확인 시간 전에는 감속만
    assert c.step(True, 0.1, 0.0, per, 0.3) == (WAIT, 0.0, 0.0)
    assert c.step(True, 0.1, 0.0, per, 4.0)[0] == WAIT
    assert c.step(True, 0.1, 0.0, per, 5.5)[0] == AVOID


def test_short_ttc_blip_does_not_wait():
    c = _ctrl()
    c.step(True, 0.1, 0.0, Perception(ttc=1.0, hist=_hist()), 0.0)
    assert c.step(True, 0.1, 0.0, Perception(hist=_hist()), 0.1)[0] == PASS
    assert c.step(True, 0.1, 0.0, Perception(ttc=1.0, hist=_hist()), 0.2)[0] == SLOW


def test_wait_release_hysteresis():
    c = _ctrl()
    danger = Perception(ttc=1.0, hist=_hist())
    clear = Perception(hist=_hist())
    c.step(True, 0.1, 0.0, danger, 0.0)
    assert c.step(True, 0.1, 0.0, danger, 0.3)[0] == WAIT
    assert c.step(True, 0.1, 0.0, clear, 0.4)[0] == WAIT     # 해제 시간 전
    assert c.step(True, 0.1, 0.0, danger, 0.5)[0] == WAIT
    assert c.step(True, 0.1, 0.0, clear, 0.6)[0] == WAIT
    assert c.step(True, 0.1, 0.0, clear, 1.2)[0] == PASS


def test_nav2_reverse_checks_rear_only():
    c = _ctrl()
    assert c.step(True, -0.05, 0.0, Perception(front=0.0, rear=1.0), 0.0)[0] == PASS
    assert c.step(True, -0.05, 0.0, Perception(front=1.0, rear=0.05), 0.1)[0] == STOP
