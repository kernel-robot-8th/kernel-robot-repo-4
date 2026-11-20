"""
카메라 사람 bbox 와 라이다 점을 이어 붙이는 순수 로직 (ROS 의존 없음).

YOLO 는 '사람이 어느 방향에 있는지'만 알고 거리를 모른다. 라이다는 거리를 알지만 사람인지 모른다.
bbox 좌우 끝을 카메라 기준 방향 각도로 바꾼 뒤, 그 각도 안에 들어오는 라이다 점을 '사람 점'으로 본다.
"""
import math


def camera_intrinsics(fx, cx, width, hfov):
    """camera_info 의 (fx, cx) 가 있으면 그대로, 없으면 수평 화각·영상 폭으로 근사한다."""
    if fx and fx > 0.0:
        return fx, cx
    return (width / 2.0) / math.tan(hfov / 2.0), width / 2.0


def bbox_bearing_interval(u_center, box_width, fx, cx, margin):
    """
    사람 bbox 좌우 끝의 카메라 기준 방향 각도 [rad] 구간 (작은 값, 큰 값).

    영상 오른쪽(u 증가)이 로봇 오른쪽(각도 감소)이다. margin 만큼 양쪽을 넓힌다.
    """
    left = math.atan2(cx - (u_center - box_width / 2.0), fx)
    right = math.atan2(cx - (u_center + box_width / 2.0), fx)
    return right - margin, left + margin


def person_points(points, intervals, cam_pose, max_range):
    """
    로봇 기준 점 중 사람 bbox 방향 구간에 들어오는 점만 고른다.

    cam_pose = (x, y, yaw): 로봇 기준 카메라 위치·방향. max_range[m] 보다 먼 점은 무시.
    """
    if not intervals:
        return []
    cx, cy, cyaw = cam_pose
    out = []
    for x, y in points:
        dx = x - cx
        dy = y - cy
        if math.hypot(dx, dy) > max_range:
            continue
        a = math.atan2(dy, dx) - cyaw
        a = math.atan2(math.sin(a), math.cos(a))
        if any(lo <= a <= hi for lo, hi in intervals):
            out.append((x, y))
    return out
