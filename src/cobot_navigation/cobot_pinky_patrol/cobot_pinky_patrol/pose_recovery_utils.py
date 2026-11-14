"""
waypoint 기반 초기 위치 재설정용 순수 로직 (ROS 비의존).

노드(pinky_pose_recovery_node)는 ROS 입출력만 하고, 수렴 판정·좌표 읽기·스캔 계획은 여기 한곳에서 고친다.
ROS 를 import 하지 않으므로 로봇·Nav2 없이 단위 테스트할 수 있다.
설계는 docs/prd/[진행] pose_reset_by_waypoint_prd.md 를 따른다.

공분산은 geometry_msgs/PoseWithCovariance 의 6x6 행렬을 편 길이 36 배열이다.
x 분산 = cov[0], y 분산 = cov[7], yaw 분산 = cov[35].
"""
import json
import math
import os

from cobot_pinky_patrol.patrol_points_utils import parse_points, PointsConfigError

import yaml

COV_XX = 0
COV_YY = 7
COV_YAW = 35

# config/pinkyN.yaml 에서 points 가 들어 있는 노드 이름 (순찰 노드의 파라미터 파일을 그대로 재사용하기 위해 안다)
PATROL_NODE_KEY = 'pinky_patrol_node'

# 좌우 스캔 방향 부호 (+ = 반시계, 왼쪽)
LEFT = 1
RIGHT = -1

# 한 바퀴 스캔의 회전량 [rad]
FULL_TURN_RAD = 2.0 * math.pi


class UnknownWaypointError(ValueError):
    """points 에 없는 waypoint 이름을 요청했을 때 발생."""


def cov_xy(cov):
    """x, y 분산 중 큰 값 [m^2]."""
    return max(cov[COV_XX], cov[COV_YY])


def is_converged(cov, max_cov_xy, max_cov_yaw):
    """위치(x, y)와 방향(yaw) 분산이 모두 기준 이하이면 수렴한 것으로 본다."""
    return cov_xy(cov) <= max_cov_xy and cov[COV_YAW] <= max_cov_yaw


def yaw_from_quat(z, w):
    """쿼터니언(z, w) -> yaw [rad]. 2D 로봇이라 z축 회전만 쓴다."""
    return 2.0 * math.atan2(z, w)


def quat_from_yaw(yaw):
    """Yaw [rad] -> 쿼터니언 (z, w)."""
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def make_initialpose_cov(var_xy, var_yaw):
    """/initialpose 에 실을 공분산(길이 36)을 만든다. 위치는 x, y 에 같은 분산, 방향은 yaw 분산만 채운다."""
    cov = [0.0] * 36
    cov[COV_XX] = var_xy
    cov[COV_YY] = var_xy
    cov[COV_YAW] = var_yaw
    return cov


def build_status(state, detail=''):
    """pose_recovery_status 토픽에 실을 JSON 문자열 ``{"state": ..., "detail": ...}``."""
    return json.dumps({'state': state, 'detail': detail}, ensure_ascii=False)


def load_waypoints(path):
    """
    points_file(순찰 노드의 pinkyN.yaml)에서 waypoint 를 읽어 ``{이름: (x, y[, yaw])}`` 로 돌려준다.

    :raises PointsConfigError: 파일이 없거나, yaml 이 깨졌거나, points 가 없거나, 좌표 형식이 잘못되었을 때
    """
    path = os.path.expanduser(path)
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except OSError as e:
        raise PointsConfigError(f'points_file 을 읽을 수 없습니다 ({path}): {e}') from e
    except yaml.YAMLError as e:
        raise PointsConfigError(f'points_file 이 올바른 yaml 이 아닙니다 ({path}): {e}') from e

    try:
        raw = data[PATROL_NODE_KEY]['ros__parameters']['points']
    except (KeyError, TypeError):
        raise PointsConfigError(
            f'{path}: {PATROL_NODE_KEY}.ros__parameters.points 가 없습니다.') from None
    if not isinstance(raw, dict) or not raw:
        raise PointsConfigError(f'{path}: points 는 {{이름: [x, y, yaw]}} 형태여야 합니다.')
    return parse_points(raw)


def get_waypoint(points, name):
    """
    Waypoint 이름으로 ``(x, y, yaw)`` 를 돌려준다. 이름은 앞뒤 공백을 지우고 대문자로 맞춘다.

    yaw 가 없는 점(``[x, y]``)은 0.0 으로 채운다.

    :raises UnknownWaypointError: points 에 없는 이름일 때
    """
    key = name.strip().upper() if isinstance(name, str) else ''
    if key not in points:
        raise UnknownWaypointError(f'unknown waypoint: {name!r} (있는 지점: {sorted(points)})')
    value = points[key]
    yaw = value[2] if len(value) == 3 else 0.0
    return value[0], value[1], yaw


def angle_delta(prev, cur):
    """두 yaw [rad] 의 차이 ``cur - prev`` 를 (-pi, pi] 로 접어서 돌려준다 (pi 경계를 넘어도 작은 회전으로 본다)."""
    d = cur - prev
    return math.atan2(math.sin(d), math.cos(d))


class RotationTracker:
    """오도메트리 yaw 를 받을 때마다 부호 있는 누적 회전량(왼쪽 +)을 ``total`` [rad] 에 쌓는다."""

    def __init__(self, yaw):
        self._prev = yaw
        self.total = 0.0

    def update(self, yaw):
        """새 yaw 를 반영하고 누적 회전량을 돌려준다."""
        self.total += angle_delta(self._prev, yaw)
        self._prev = yaw
        return self.total


def _require_positive(name, value):
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} 은 0 보다 큰 유한한 값이어야 합니다 (받은 값: {value!r}).')


def plan_lr_scan(half_angle):
    """
    좌우 스캔 계획을 ``[(방향, 회전량[rad]), ...]`` 로 돌려준다.

    순서: 왼쪽 half_angle -> 오른쪽 2*half_angle(왼쪽 끝에서 오른쪽 끝까지) -> 왼쪽 half_angle(정면 복귀).
    노드는 구간마다 오도메트리로 회전량을 재고, 수렴하면 계획을 끊고 즉시 멈춘다.
    방향은 ``LEFT``(+1) / ``RIGHT``(-1) 이다.

    :raises ValueError: half_angle 이 0 이하이거나 유한하지 않을 때
    """
    _require_positive('half_angle', half_angle)
    return [(LEFT, half_angle), (RIGHT, 2.0 * half_angle), (LEFT, half_angle)]


def segment_timeout_sec(angle, angular_speed, factor):
    """한 구간의 시간 초과 [s]: 계획 시간(angle / angular_speed) 의 factor 배. 이 안에 못 닿으면 로봇이 안 움직이는 것으로 본다."""
    _require_positive('angle', angle)
    _require_positive('angular_speed', angular_speed)
    _require_positive('factor', factor)
    return angle / angular_speed * factor


def validate_scan_params(half_angle, angular_speed, tolerance, stale_sec, factor):
    """
    스캔 파라미터를 시작할 때 한꺼번에 검사한다 (명령을 받고 나서야 터지지 않게).

    :raises ValueError: 하나라도 0 이하이거나 유한하지 않을 때, 또는 tolerance 가 half_angle 이상일 때
    """
    values = (
        ('scan_half_angle_rad', half_angle),
        ('scan_angular_speed', angular_speed),
        ('scan_angle_tolerance_rad', tolerance),
        ('scan_odom_stale_sec', stale_sec),
        ('scan_timeout_factor', factor),
    )
    for name, value in values:
        _require_positive(name, value)
    if tolerance >= half_angle:
        raise ValueError(
            f'scan_angle_tolerance_rad({tolerance}) 는 '
            f'scan_half_angle_rad({half_angle}) 보다 작아야 합니다.')
