"""pose_recovery_utils 단위 테스트 (ROS 불필요)."""
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_pinky_patrol.patrol_points_utils import PointsConfigError  # noqa: E402,I100,I101
from cobot_pinky_patrol.pose_recovery_utils import (  # noqa: E402,I100,I101
    angle_delta, build_status, cov_xy, FULL_TURN_RAD, get_waypoint, is_converged, LEFT,
    load_waypoints, make_initialpose_cov, plan_lr_scan, quat_from_yaw, RIGHT, RotationTracker,
    segment_timeout_sec, UnknownWaypointError, validate_scan_params, yaw_from_quat)

PINKY2_YAML = Path(__file__).resolve().parent.parent / 'config' / 'pinky2.yaml'


def _cov(xx=0.0, yy=0.0, yaw=0.0):
    cov = [0.0] * 36
    cov[0], cov[7], cov[35] = xx, yy, yaw
    return cov


def _write(tmp_path, text):
    path = tmp_path / 'points.yaml'
    path.write_text(text, encoding='utf-8')
    return str(path)


# ---------------------------------------------------------------- 수렴 판정
def test_cov_xy_takes_larger():
    assert cov_xy(_cov(xx=0.01, yy=0.2)) == 0.2


@pytest.mark.parametrize('cov,expected', [
    (_cov(0.01, 0.01, 0.05), True),
    (_cov(0.05, 0.05, 0.1), True),          # 경계값은 수렴
    (_cov(0.2, 0.01, 0.05), False),         # x 분산이 큼
    (_cov(0.01, 0.01, 0.5), False),         # yaw 분산이 큼
])
def test_is_converged(cov, expected):
    assert is_converged(cov, 0.05, 0.1) is expected


# ---------------------------------------------------------------- 각도 변환
@pytest.mark.parametrize('yaw', [0.0, 1.5, -1.5, 3.0, -3.0])
def test_quat_yaw_roundtrip(yaw):
    z, w = quat_from_yaw(yaw)
    assert yaw_from_quat(z, w) == pytest.approx(yaw)


# ---------------------------------------------------------------- waypoint 읽기
def test_load_waypoints_ok(tmp_path):
    path = _write(tmp_path, (
        'pinky_patrol_node:\n'
        '  ros__parameters:\n'
        '    points:\n'
        '      P1: [0.1, -0.2, 1.5]\n'
        '      P2: [0.3, 0.4]\n'))
    points = load_waypoints(path)
    assert points == {'P1': (0.1, -0.2, 1.5), 'P2': (0.3, 0.4)}


def test_load_waypoints_real_config():
    points = load_waypoints(str(PINKY2_YAML))
    assert 'P1' in points and 'I2' in points
    assert len(get_waypoint(points, 'P1')) == 3


def test_load_waypoints_missing_file(tmp_path):
    with pytest.raises(PointsConfigError):
        load_waypoints(str(tmp_path / 'none.yaml'))


def test_load_waypoints_broken_yaml(tmp_path):
    with pytest.raises(PointsConfigError):
        load_waypoints(_write(tmp_path, 'a: [1, 2\n'))


@pytest.mark.parametrize('text', [
    '',                                                       # 빈 파일
    'other_node:\n  ros__parameters:\n    points: {P1: [0.0, 0.0]}\n',  # 노드 키 없음
    'pinky_patrol_node:\n  ros__parameters:\n    robot_id: pinky2\n',   # points 없음
    'pinky_patrol_node:\n  ros__parameters:\n    points: []\n',          # points 형식 오류
])
def test_load_waypoints_missing_points(tmp_path, text):
    with pytest.raises(PointsConfigError):
        load_waypoints(_write(tmp_path, text))


def test_load_waypoints_bad_coordinate(tmp_path):
    path = _write(tmp_path, (
        'pinky_patrol_node:\n  ros__parameters:\n    points:\n      P1: [0.0]\n'))
    with pytest.raises(PointsConfigError):
        load_waypoints(path)


# ---------------------------------------------------------------- waypoint 선택
def test_get_waypoint_with_yaw():
    assert get_waypoint({'P3': (1.0, 2.0, 0.5)}, 'P3') == (1.0, 2.0, 0.5)


def test_get_waypoint_without_yaw_is_zero():
    assert get_waypoint({'P3': (1.0, 2.0)}, 'P3') == (1.0, 2.0, 0.0)


def test_get_waypoint_normalizes_name():
    assert get_waypoint({'P3': (1.0, 2.0, 0.5)}, ' p3 ') == (1.0, 2.0, 0.5)


@pytest.mark.parametrize('name', ['P9', '', None, 3])
def test_get_waypoint_unknown(name):
    with pytest.raises(UnknownWaypointError):
        get_waypoint({'P3': (1.0, 2.0)}, name)


# ---------------------------------------------------------------- 각도 변화, 회전 누적
@pytest.mark.parametrize('prev,cur,expected', [
    (0.0, 0.3, 0.3),
    (0.3, 0.0, -0.3),
    (math.pi - 0.1, -math.pi + 0.1, 0.2),     # +pi 경계를 넘어 왼쪽으로 0.2
    (-math.pi + 0.1, math.pi - 0.1, -0.2),    # -pi 경계를 넘어 오른쪽으로 0.2
    (1.0, 1.0, 0.0),
])
def test_angle_delta_wraps(prev, cur, expected):
    assert angle_delta(prev, cur) == pytest.approx(expected)


def test_rotation_tracker_accumulates_across_boundary():
    tracker = RotationTracker(3.0)                 # pi 근처에서 시작
    total = 0.0
    yaw = 3.0
    for _ in range(40):                            # 왼쪽으로 0.1 rad 씩 4 rad
        yaw += 0.1
        wrapped = math.atan2(math.sin(yaw), math.cos(yaw))   # odom 은 -pi~pi 로 접어서 준다
        total = tracker.update(wrapped)
    assert total == pytest.approx(4.0)


def test_rotation_tracker_right_is_negative():
    tracker = RotationTracker(-3.0)
    yaw = -3.0
    for _ in range(25):
        yaw -= 0.1
        total = tracker.update(math.atan2(math.sin(yaw), math.cos(yaw)))
    assert total == pytest.approx(-2.5)


def test_rotation_tracker_full_turn():
    tracker = RotationTracker(0.5)
    total = 0.0
    for i in range(1, 64):
        total = tracker.update(math.atan2(math.sin(0.5 + i * 0.1), math.cos(0.5 + i * 0.1)))
    assert total == pytest.approx(6.3)
    assert total >= FULL_TURN_RAD


# ---------------------------------------------------------------- 스캔 계획
def test_plan_lr_scan_order_and_angles():
    plan = plan_lr_scan(1.5)
    assert [d for d, _ in plan] == [LEFT, RIGHT, LEFT]
    assert [a for _, a in plan] == pytest.approx([1.5, 3.0, 1.5])


def test_plan_lr_scan_net_rotation_is_zero():
    # 왼쪽 +a -> 오른쪽 -2a -> 왼쪽 +a: 끝나면 시작 방향(정면)으로 돌아온다
    assert sum(d * a for d, a in plan_lr_scan(1.2)) == pytest.approx(0.0)


@pytest.mark.parametrize('half', [0.0, -1.0, math.nan, math.inf])
def test_plan_lr_scan_rejects_bad_values(half):
    with pytest.raises(ValueError):
        plan_lr_scan(half)


def test_segment_timeout_sec():
    assert segment_timeout_sec(1.5, 0.3, 2.0) == pytest.approx(10.0)


@pytest.mark.parametrize('angle,speed,factor', [
    (0.0, 0.3, 2.0), (1.5, 0.0, 2.0), (1.5, 0.3, 0.0), (-1.5, 0.3, 2.0), (1.5, math.nan, 2.0)])
def test_segment_timeout_sec_rejects_bad_values(angle, speed, factor):
    with pytest.raises(ValueError):
        segment_timeout_sec(angle, speed, factor)


def test_validate_scan_params_ok():
    validate_scan_params(1.5, 0.3, 0.05, 1.0, 2.0)


@pytest.mark.parametrize('args', [
    (0.0, 0.3, 0.05, 1.0, 2.0),      # 반각 0
    (1.5, 0.0, 0.05, 1.0, 2.0),      # 속도 0
    (1.5, 0.3, 0.0, 1.0, 2.0),       # 허용 오차 0
    (1.5, 0.3, 0.05, 0.0, 2.0),      # odom 허용 시간 0
    (1.5, 0.3, 0.05, 1.0, 0.0),      # 계수 0
    (0.05, 0.3, 0.05, 1.0, 2.0),     # 허용 오차가 반각 이상
    (1.5, math.inf, 0.05, 1.0, 2.0),
])
def test_validate_scan_params_rejects(args):
    with pytest.raises(ValueError):
        validate_scan_params(*args)


# ---------------------------------------------------------------- /initialpose 공분산, 상태 JSON
def test_make_initialpose_cov():
    cov = make_initialpose_cov(0.25, 0.3)
    assert len(cov) == 36
    assert (cov[0], cov[7], cov[35]) == (0.25, 0.25, 0.3)
    assert sum(1 for v in cov if v != 0.0) == 3


def test_make_initialpose_cov_is_not_converged_by_default_limits():
    # 노드가 보내는 분산은 수렴 기준보다 커서, 보낸 직후 값만으로 수렴 판정이 나지 않아야 한다
    assert not is_converged(make_initialpose_cov(0.25, 0.3), 0.05, 0.1)


def test_build_status_keeps_korean():
    data = json.loads(build_status('FAILED', '없는 지점'))
    assert data == {'state': 'FAILED', 'detail': '없는 지점'}
    assert '없는 지점' in build_status('FAILED', '없는 지점')


def test_build_status_default_detail():
    assert json.loads(build_status('CONVERGED')) == {'state': 'CONVERGED', 'detail': ''}
