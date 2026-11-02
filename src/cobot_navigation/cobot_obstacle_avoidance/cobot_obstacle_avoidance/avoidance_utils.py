"""장애물 회피 상태 머신 (ROS 의존 없음).

Nav2 가 낸 속도(nav_v, nav_w)와 센서 판단 결과를 받아 실제로 낼 속도를 정한다.

상태
  PASS   : 앞이 비어 있음 -> Nav2 속도 그대로
  SLOW   : 장애물이 가까움 -> Nav2 속도를 줄여서
  STOP   : 정지 장애물이 너무 가까움 -> 정지. block_time 넘게 막히면 AVOID
  WAIT   : 움직이는 장애물과 곧 부딪힘(TTC 짧음) -> 정지 후 지나가길 기다림.
           wait_timeout 넘게 안 비키면 AVOID
  AVOID  : 빈 방향(VFH)으로 돌아 나간다. 앞이 트이면 PASS 로 Nav2 에 넘긴다
  BACKUP : 빈 방향이 없으면 뒤로 물러난 뒤 다시 AVOID
"""
from dataclasses import dataclass, field
import math

from .scan_utils import choose_free_direction

PASS = 'PASS'
SLOW = 'SLOW'
STOP = 'STOP'
WAIT = 'WAIT'
AVOID = 'AVOID'
BACKUP = 'BACKUP'


@dataclass
class AvoidanceParams:
    """상태 머신 파라미터. 기본값은 config/obstacle_avoidance.yaml 과 같다."""

    stop_dist: float = 0.12           # [m] 앞 여유가 이보다 작으면 정지
    resume_dist: float = 0.20         # [m] 정지 후 이보다 커져야 다시 출발 (떨림 방지)
    slow_dist: float = 0.40           # [m] 이보다 작으면 감속 시작
    min_slow_scale: float = 0.3       # 감속 시 최소 배율
    block_time: float = 2.0           # [s] 정지가 이만큼 이어지면 회피 시작
    rear_stop_dist: float = 0.10      # [m] 뒤 여유가 이보다 작으면 후진 금지
    ttc_stop: float = 2.0             # [s] 움직이는 장애물 TTC 가 이보다 작으면 대기
    ttc_slow: float = 4.0             # [s] 이보다 작으면 감속
    wait_timeout: float = 5.0         # [s] 대기가 이만큼 이어지면 회피로 전환
    avoid_clearance: float = 0.35     # [m] 이 거리 안에 점이 없는 방향만 '빈 방향'
    robot_radius: float = 0.10        # [m] 빈 방향 폭 검사에 쓰는 로봇 반경(여유 포함)
    avoid_max_angle: float = 1.75     # [rad] 회피 방향 탐색 범위 (정면 기준 ±)
    avoid_linear_speed: float = 0.06  # [m/s] 회피 중 전진 속도
    avoid_angular_gain: float = 1.5   # 회피 방향 각도 -> 회전 속도 비례 이득
    max_angular_speed: float = 1.0    # [rad/s] 회피 중 최대 회전 속도
    align_tol: float = 0.35           # [rad] 이 각도 안으로 맞춰지면 전진
    avoid_clear_dist: float = 0.40    # [m] 회피 중 앞 여유가 이 이상이면 Nav2 로 복귀
    avoid_min_time: float = 1.0       # [s] 회피를 최소 이만큼은 유지 (바로 되돌아오기 방지)
    avoid_timeout: float = 8.0        # [s] 회피가 이보다 길면 Nav2 로 넘긴다(재계획 맡김)
    backup_speed: float = 0.05        # [m/s] 후진 속도
    backup_time: float = 2.0          # [s] 한 번 후진하는 시간


@dataclass
class Perception:
    """한 주기의 센서 판단 결과."""

    front: float = math.inf           # [m] 앞 통로 여유 (라이다·초음파 중 작은 값)
    rear: float = math.inf            # [m] 뒤 통로 여유
    ttc: float = math.inf             # [s] 움직이는 장애물과의 최소 TTC
    hist: list = field(default_factory=list)  # 극좌표 히스토그램 (scan_utils.polar_histogram)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


class AvoidanceController:
    """회피 상태 머신. step() 을 제어 주기마다 부른다."""

    def __init__(self, params):
        """params: AvoidanceParams."""
        self.p = params
        self.state = PASS
        self.state_t = 0.0
        self.maneuver_t = 0.0   # STOP/WAIT 에서 회피를 시작한 시각 (AVOID<->BACKUP 반복 포함)

    def reset(self):
        """회피를 끌 때 상태를 초기화한다."""
        self.state = PASS
        self.state_t = 0.0
        self.maneuver_t = 0.0

    def _enter(self, state, t):
        if self.state != state:
            if state == AVOID and self.state not in (AVOID, BACKUP):
                self.maneuver_t = t
            self.state = state
            self.state_t = t

    def step(self, enabled, nav_v, nav_w, per, t):
        """이번 주기에 낼 (상태, v, w) 를 돌려준다."""
        p = self.p
        if not enabled:
            self.reset()
            return PASS, nav_v, nav_w

        # Nav2 가 직접 후진 중(복구 동작 등)이면 뒤만 본다.
        if nav_v < 0.0 and self.state not in (AVOID, BACKUP):
            if per.rear < p.rear_stop_dist:
                self._enter(STOP, t)
                return STOP, 0.0, 0.0
            self._enter(PASS, t)
            return PASS, nav_v, nav_w

        if self.state == BACKUP:
            if per.rear >= p.rear_stop_dist and t - self.state_t < p.backup_time:
                return BACKUP, -p.backup_speed, 0.0
            self._enter(AVOID, t)

        if self.state == AVOID:
            return self._avoid(nav_w, per, t)

        if per.ttc < p.ttc_stop:
            self._enter(WAIT, t)
            if t - self.state_t < p.wait_timeout:
                return WAIT, 0.0, 0.0
            self._enter(AVOID, t)
            return self._avoid(nav_w, per, t)

        blocked = per.front < p.stop_dist or (self.state == STOP and per.front < p.resume_dist)
        if blocked:
            self._enter(STOP, t)
            if t - self.state_t < p.block_time:
                return STOP, 0.0, 0.0
            self._enter(AVOID, t)
            return self._avoid(nav_w, per, t)

        scale = 1.0
        if per.front < p.slow_dist:
            scale = (per.front - p.stop_dist) / (p.slow_dist - p.stop_dist)
        if per.ttc < p.ttc_slow:
            scale = min(scale, (per.ttc - p.ttc_stop) / (p.ttc_slow - p.ttc_stop))
        if scale < 1.0:
            self._enter(SLOW, t)
            return SLOW, nav_v * _clamp(scale, p.min_slow_scale, 1.0), nav_w
        self._enter(PASS, t)
        return PASS, nav_v, nav_w

    def _avoid(self, nav_w, per, t):
        p = self.p
        elapsed = t - self.state_t
        if t - self.maneuver_t > p.avoid_timeout:
            self._enter(PASS, t)
            return PASS, 0.0, 0.0
        if (elapsed >= p.avoid_min_time and per.front >= p.avoid_clear_dist
                and per.ttc >= p.ttc_stop):
            self._enter(PASS, t)
            return PASS, 0.0, 0.0
        direction = choose_free_direction(per.hist, p.avoid_clearance, p.robot_radius,
                                          p.avoid_max_angle, prefer_sign=nav_w)
        if direction is None:
            if per.rear >= p.rear_stop_dist:
                self._enter(BACKUP, t)
                return BACKUP, -p.backup_speed, 0.0
            return AVOID, 0.0, 0.0
        w = _clamp(p.avoid_angular_gain * direction, -p.max_angular_speed, p.max_angular_speed)
        v = p.avoid_linear_speed if (abs(direction) < p.align_tol
                                     and per.front > p.stop_dist) else 0.0
        return AVOID, v, w
