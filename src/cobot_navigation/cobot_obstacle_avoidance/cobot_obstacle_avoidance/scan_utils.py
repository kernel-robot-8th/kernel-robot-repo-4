"""
LaserScan 가공 순수 로직 (ROS 의존 없음).

좌표는 모두 로봇 기준(base_footprint): x 앞(+), y 왼쪽(+), 각도는 x축에서 반시계(+).
"""
import math


def scan_to_points(ranges, angle_min, angle_increment, range_min, range_max,
                   tx=0.0, ty=0.0, yaw=0.0):
    """
    스캔 거리 배열을 로봇 기준 (x, y) 점 목록으로 바꾼다.

    tx, ty, yaw 는 라이다 frame 이 로봇 frame 에서 놓인 위치·방향.
    핑키의 rplidar_link 는 yaw=pi 로 뒤집혀 달려 있으므로 TF 값을 그대로 넘겨야 한다.
    유효하지 않은 값(inf, nan, 범위 밖)은 버리되 스캔 순서는 유지한다(군집화가 순서에 의존).
    """
    cos_y = math.cos(yaw)
    sin_y = math.sin(yaw)
    points = []
    for i, r in enumerate(ranges):
        if not math.isfinite(r) or r < range_min or r > range_max:
            continue
        a = angle_min + i * angle_increment
        lx = r * math.cos(a)
        ly = r * math.sin(a)
        points.append((tx + cos_y * lx - sin_y * ly, ty + sin_y * lx + cos_y * ly))
    return points


def corridor_clearance(points, half_width, front_x, forward=True):
    """
    진행 방향 통로(|y| <= half_width) 안 가장 가까운 점까지의 여유 거리 [m].

    forward=True 이면 앞쪽(x > front_x)에서 (x - front_x),
    False 이면 뒤쪽(x < -front_x)에서 (-x - front_x) 를 본다. 통로가 비면 inf.
    """
    best = math.inf
    for x, y in points:
        if abs(y) > half_width:
            continue
        d = (x - front_x) if forward else (-x - front_x)
        if d >= 0.0 and d < best:
            best = d
    return best


def cluster_points(points, gap):
    """
    스캔 순서상 이웃 점 간 거리가 gap 이하인 점들을 한 덩어리로 묶는다.

    360° 스캔은 처음과 끝이 이어지므로 양 끝 덩어리가 가까우면 합친다.
    """
    if not points:
        return []
    clusters = [[points[0]]]
    for p in points[1:]:
        q = clusters[-1][-1]
        if math.hypot(p[0] - q[0], p[1] - q[1]) <= gap:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    if len(clusters) > 1:
        first, last = clusters[0], clusters[-1]
        if math.hypot(first[0][0] - last[-1][0], first[0][1] - last[-1][1]) <= gap:
            clusters[0] = last + first
            clusters.pop()
    return clusters


def centroid(cluster):
    """덩어리 점들의 평균 위치."""
    n = len(cluster)
    return (sum(p[0] for p in cluster) / n, sum(p[1] for p in cluster) / n)


def cluster_extent(cluster):
    """덩어리 양 끝 점 사이 거리 [m]. 벽처럼 큰 덩어리를 추적 대상에서 빼는 데 쓴다."""
    return math.hypot(cluster[0][0] - cluster[-1][0], cluster[0][1] - cluster[-1][1])


def polar_histogram(points, n_sectors, max_range):
    """
    로봇 둘레를 n_sectors 칸으로 나눠 칸마다 가장 가까운 점 거리를 담는다 (없으면 max_range).

    칸 i 의 중심 각도는 sector_angle(i, n_sectors).
    """
    hist = [max_range] * n_sectors
    width = 2.0 * math.pi / n_sectors
    for x, y in points:
        d = math.hypot(x, y)
        if d >= max_range:
            continue
        i = int(((math.atan2(y, x) + math.pi) // width)) % n_sectors
        if d < hist[i]:
            hist[i] = d
    return hist


def sector_angle(i, n_sectors):
    """칸 i 의 중심 각도 [rad], 범위 (-pi, pi]."""
    width = 2.0 * math.pi / n_sectors
    return -math.pi + (i + 0.5) * width


def choose_free_direction(hist, clearance, robot_radius, max_angle, prefer_sign=0.0):
    """
    빈 방향(VFH 방식)을 골라 각도 [rad] 를 돌려준다. 없으면 None.

    - 칸 거리가 clearance 이상이어야 '빈 칸'.
    - 로봇 폭만큼 옆 칸도 비어 있어야 통과 가능: 거리 d 에서 로봇 반경이 차지하는 각도
      asin(r/d) 안의 칸을 함께 검사한다 (가까울수록 넓게 본다).
    - |각도| <= max_angle 인 후보 중 정면(0)에 가장 가까운 방향을 고른다.
      동률이면 prefer_sign(Nav2 가 돌던 방향) 쪽을 고른다.
    """
    n = len(hist)
    width = 2.0 * math.pi / n
    best = None
    best_key = None
    for i in range(n):
        a = sector_angle(i, n)
        if abs(a) > max_angle or hist[i] < clearance:
            continue
        half = math.asin(min(1.0, robot_radius / max(hist[i], robot_radius)))
        k = int(math.ceil(half / width))
        if any(hist[(i + j) % n] < clearance for j in range(-k, k + 1)):
            continue
        tie = 0 if prefer_sign == 0.0 else (0 if a * prefer_sign >= 0.0 else 1)
        key = (round(abs(a), 6), tie)
        if best_key is None or key < best_key:
            best_key = key
            best = a
    return best
