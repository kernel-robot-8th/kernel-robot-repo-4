"""
순찰 지점 좌표의 파싱·검증 (ROS 비의존 순수 함수).

좌표는 코드에 박지 않고 ``config/pinkyN.yaml`` 의 ``points`` 파라미터로 받는다.
노드는 파라미터를 읽어 이 모듈에 넘기기만 하고, 형식 규칙은 여기 한곳에서 고친다.
ROS 를 import 하지 않으므로 로봇·Nav2 없이 단위 테스트할 수 있다.

좌표 형식: ``[x, y]`` 또는 ``[x, y, yaw]`` (x, y 는 m, yaw 는 rad, map 좌표계).
"""
import math

# 구역과 무관하게 반드시 있어야 하는 지점 이름 (goto 허용 지점 P1~P7).
# 구역별 진입/출구 지점(ZONE_<구역>_ENTRY / ZONE_<구역>_EXIT)은 구역 이름에 따라 달라지므로
# required_names(zone_names) 가 덧붙인다. 이름 자체는 코드가 참조하므로 좌표와 달리 코드에 남긴다.
REQUIRED_POINTS = ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7')


class PointsConfigError(ValueError):
    """좌표 설정이 잘못되었을 때 발생. 메시지에 키 이름과 고치는 방법을 담는다."""


def parse_point(name, value):
    """
    지점 하나를 ``(x, y)`` 또는 ``(x, y, yaw)`` 튜플로 변환한다.

    :param name: 지점 이름 (오류 메시지용)
    :param value: YAML 에서 읽은 값 (list/tuple)
    :raises PointsConfigError: 길이가 2·3 이 아니거나, 숫자가 아니거나, NaN/inf 일 때
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, '__len__'):
        raise PointsConfigError(
            f'points.{name}: 리스트여야 합니다 ([x, y] 또는 [x, y, yaw]). 받은 값: {value!r}')
    if len(value) not in (2, 3):
        raise PointsConfigError(
            f'points.{name}: 값은 2개([x, y]) 또는 3개([x, y, yaw])여야 합니다. '
            f'현재 {len(value)}개: {list(value)!r}')
    out = []
    for i, v in enumerate(value):
        # bool 은 int 의 하위 타입이라 True 가 1.0 으로 통과하므로 명시적으로 막는다
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PointsConfigError(
                f'points.{name}[{i}]: 숫자가 아닙니다 ({v!r}).')
        if not math.isfinite(v):
            raise PointsConfigError(
                f'points.{name}[{i}]: NaN/inf 는 쓸 수 없습니다 ({v!r}).')
        out.append(float(v))
    return tuple(out)


def parse_points(raw):
    """``{이름: 값}`` 전체를 ``{이름: 튜플}`` 로 변환한다 (첫 오류에서 예외)."""
    return {name: parse_point(name, value) for name, value in raw.items()}


def validate_points(points, required, home_name):
    """
    필수 지점과 홈 지점이 모두 있는지 확인한다.

    :param points: ``parse_points`` 결과
    :param required: 있어야 하는 지점 이름들 (보통 ``REQUIRED_POINTS``)
    :param home_name: goto 완료 후 복귀할 지점 이름 (``points`` 안에 있어야 함)
    :raises PointsConfigError: 누락된 이름을 한꺼번에 알려 준다 (하나씩 고치며 재시작하지 않게)
    """
    missing = [n for n in required if n not in points]
    if missing:
        raise PointsConfigError(
            f'필수 지점이 없습니다: {missing}. config/pinkyN.yaml 의 points 에 '
            f'[x, y] 또는 [x, y, yaw] 로 추가하세요 (YAML 을 지정했는지도 확인: launch 또는 --params-file).')
    if not home_name:
        raise PointsConfigError(
            'home_name 이 비어 있습니다. config/pinkyN.yaml 에 home_name: P1 처럼 지점 이름을 쓰세요.')
    if home_name not in points:
        raise PointsConfigError(
            f"home_name '{home_name}' 이(가) points 에 없습니다. 있는 지점: {sorted(points)}")


# ---------------------------------------------------------------------------
# 위험구역 (구역마다 진입/출구 좌표 한 쌍과 소속 지점 목록을 가진다)
# ---------------------------------------------------------------------------
def entry_name(zone):
    """구역 ``zone`` 의 진입(토큰 요청·획득) 지점 이름. 예: ``A`` -> ``ZONE_A_ENTRY``."""
    return f'ZONE_{zone}_ENTRY'


def exit_name(zone):
    """구역 ``zone`` 의 출구(토큰 반납) 지점 이름. 예: ``A`` -> ``ZONE_A_EXIT``."""
    return f'ZONE_{zone}_EXIT'


def required_names(zone_names):
    """P1~P7 과 구역별 ENTRY/EXIT 를 합친, ``points`` 에 반드시 있어야 하는 이름 목록."""
    names = list(REQUIRED_POINTS)
    for zone in zone_names:
        names += [entry_name(zone), exit_name(zone)]
    return names


def parse_zone_names(raw):
    """
    구역 이름 목록을 검증해 튜플로 돌려준다.

    이름은 ZONE_<이름>_ENTRY 지점 이름과 매니저 메시지(``<구역>:...``)에 그대로 쓰이므로
    영문·숫자로만 짓고(``:`` 불가) 중복을 허용하지 않는다.
    """
    if isinstance(raw, (str, bytes)) or not hasattr(raw, '__len__') or len(raw) == 0:
        raise PointsConfigError(
            f'zone_names: 구역 이름 목록이 필요합니다 (예: [A, B]). 받은 값: {raw!r}')
    names = []
    for z in raw:
        if not isinstance(z, str) or not z.isalnum():
            raise PointsConfigError(
                f'zone_names: 구역 이름은 영문·숫자만 쓸 수 있습니다 (받은 값: {z!r}).')
        if z in names:
            raise PointsConfigError(f'zone_names: 구역 이름이 중복되었습니다: {z!r}')
        names.append(z)
    return tuple(names)


def parse_zone_points(raw):
    """``{구역: [지점 이름, ...]}`` 를 ``{구역: (지점 이름, ...)}`` 로 변환한다."""
    out = {}
    for zone, names in raw.items():
        if isinstance(names, (str, bytes)) or not hasattr(names, '__len__'):
            raise PointsConfigError(
                f'zone_points.{zone}: 지점 이름 리스트여야 합니다 (예: [P3, P4]). 받은 값: {names!r}')
        for n in names:
            if not isinstance(n, str) or not n:
                raise PointsConfigError(
                    f'zone_points.{zone}: 지점 이름은 문자열이어야 합니다 (받은 값: {n!r}).')
        out[zone] = tuple(names)
    return out


def validate_zones(zone_points, points, home_name):
    """
    구역 소속 지점이 모순 없이 정의되었는지 확인한다.

    - 모든 구역에 소속 지점이 1개 이상 있고, 그 지점이 ``points`` 에 존재한다
    - 한 지점이 두 구역에 동시에 속하지 않는다 (속하면 어느 토큰이 필요한지 정할 수 없다)
    - 홈 지점은 구역 밖이어야 한다 (goto 가 끝나면 토큰을 반납하고 홈으로 가므로)
    - ENTRY/EXIT 는 구역 안 지점이 아니다 (경로 지점으로 직접 지정하지 못하게)

    :raises PointsConfigError: 문제를 한꺼번에 모아 알려 준다
    """
    problems = []
    owner = {}
    for zone, members in zone_points.items():
        if not members:
            problems.append(f'zone_points.{zone}: 소속 지점이 비어 있습니다.')
        for n in members:
            if n not in points:
                problems.append(f'zone_points.{zone}: {n} 가 points 에 없습니다.')
            if n in (entry_name(z) for z in zone_points) or n in (exit_name(z) for z in zone_points):
                problems.append(f'zone_points.{zone}: {n} 는 진입/출구 지점이라 소속 지점이 될 수 없습니다.')
            if n in owner:
                problems.append(f'{n} 가 구역 {owner[n]} 와 {zone} 에 동시에 속합니다.')
            owner[n] = zone
    if home_name in owner:
        problems.append(f'home_name {home_name} 가 구역 {owner[home_name]} 안에 있습니다. 홈은 구역 밖 지점이어야 합니다.')
    if problems:
        raise PointsConfigError('구역 설정 오류: ' + ' / '.join(problems))


def zone_of(zone_points, name):
    """지점 ``name`` 이 속한 구역 이름. 구역 밖이면 ``None``."""
    for zone, members in zone_points.items():
        if name in members:
            return zone
    return None
