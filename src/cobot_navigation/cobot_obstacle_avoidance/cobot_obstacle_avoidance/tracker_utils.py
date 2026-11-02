"""
움직이는 장애물 추적과 충돌 예상 시간(TTC) 계산 (ROS 의존 없음).

추적은 odom(세계) 좌표에서 한다. 로봇 기준 좌표로 추적하면 로봇이 움직일 때
멈춰 있는 물체도 움직이는 것처럼 보이기 때문이다.
"""
from dataclasses import dataclass
import math


def to_world(point, pose):
    """로봇 기준 점을 odom 좌표로 바꾼다. pose = (x, y, yaw)."""
    px, py, yaw = pose
    c = math.cos(yaw)
    s = math.sin(yaw)
    return (px + c * point[0] - s * point[1], py + s * point[0] + c * point[1])


def to_robot(point, pose):
    """Odom 좌표 점을 로봇 기준으로 바꾼다."""
    px, py, yaw = pose
    dx = point[0] - px
    dy = point[1] - py
    c = math.cos(yaw)
    s = math.sin(yaw)
    return (c * dx + s * dy, -s * dx + c * dy)


@dataclass
class Track:
    """추적 중인 장애물 하나."""

    track_id: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    last_t: float = 0.0
    hits: int = 1

    @property
    def speed(self):
        """속력 [m/s]."""
        return math.hypot(self.vx, self.vy)


class ObstacleTracker:
    """가장 가까운 이웃 매칭으로 덩어리 중심을 프레임 간 이어 붙이고 속도를 추정한다."""

    def __init__(self, match_dist, max_age, alpha, min_hits):
        """
        match_dist[m] 안에서만 같은 물체로 보고, max_age[s] 동안 안 보이면 지운다.

        alpha 는 속도 저역통과 계수(0~1, 클수록 새 측정 비중↑),
        min_hits 번 이상 이어진 track 만 속도를 믿는다.
        """
        self.match_dist = match_dist
        self.max_age = max_age
        self.alpha = alpha
        self.min_hits = min_hits
        self.tracks = []
        self._next_id = 0

    def update(self, centroids, t):
        """새 프레임의 중심점(odom 좌표) 목록으로 track 들을 갱신하고 목록을 돌려준다."""
        pairs = []
        for ti, tr in enumerate(self.tracks):
            for ci, c in enumerate(centroids):
                d = math.hypot(c[0] - tr.x, c[1] - tr.y)
                if d <= self.match_dist:
                    pairs.append((d, ti, ci))
        pairs.sort()
        used_t = set()
        used_c = set()
        for _, ti, ci in pairs:
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti)
            used_c.add(ci)
            tr = self.tracks[ti]
            dt = t - tr.last_t
            cx, cy = centroids[ci]
            if dt > 1e-3:
                mvx = (cx - tr.x) / dt
                mvy = (cy - tr.y) / dt
                tr.vx = self.alpha * mvx + (1.0 - self.alpha) * tr.vx
                tr.vy = self.alpha * mvy + (1.0 - self.alpha) * tr.vy
            tr.x, tr.y, tr.last_t = cx, cy, t
            tr.hits += 1
        for ci, c in enumerate(centroids):
            if ci not in used_c:
                self.tracks.append(Track(self._next_id, c[0], c[1], last_t=t))
                self._next_id += 1
        self.tracks = [tr for tr in self.tracks if t - tr.last_t <= self.max_age]
        return self.tracks

    def moving_tracks(self, min_speed):
        """충분히 이어졌고 min_speed[m/s] 이상으로 움직이는 track."""
        return [tr for tr in self.tracks
                if tr.hits >= self.min_hits and tr.speed >= min_speed]


def time_to_collision(rel_x, rel_y, rel_vx, rel_vy, radius):
    """
    상대 위치·속도가 일정할 때 거리가 radius 이하가 되는 가장 이른 시간 [s].

    이미 radius 안이면 0, 영영 가까워지지 않으면 inf.
    |p + v t| = radius 를 t 에 대해 푼다.
    """
    c = rel_x * rel_x + rel_y * rel_y - radius * radius
    if c <= 0.0:
        return 0.0
    a = rel_vx * rel_vx + rel_vy * rel_vy
    b = 2.0 * (rel_x * rel_vx + rel_y * rel_vy)
    if a < 1e-9 or b >= 0.0:
        return math.inf
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return math.inf
    return (-b - math.sqrt(disc)) / (2.0 * a)


def min_ttc(tracks, robot_pose, robot_vel, radius):
    """움직이는 track 들과 로봇 사이 TTC 최솟값. robot_vel = (vx, vy) odom 좌표."""
    best = math.inf
    for tr in tracks:
        ttc = time_to_collision(tr.x - robot_pose[0], tr.y - robot_pose[1],
                                tr.vx - robot_vel[0], tr.vy - robot_vel[1], radius)
        best = min(best, ttc)
    return best
