"""
순찰 지점 좌표의 파싱·검증 (ROS 비의존 순수 함수).

좌표는 코드에 박지 않고 ``config/pinkyN.yaml`` 의 ``points`` 파라미터로 받는다.
노드는 파라미터를 읽어 이 모듈에 넘기기만 하고, 형식 규칙은 여기 한곳에서 고친다.
ROS 를 import 하지 않으므로 로봇·Nav2 없이 단위 테스트할 수 있다.

좌표 형식: ``[x, y]`` 또는 ``[x, y, yaw]`` (x, y 는 m, yaw 는 rad, map 좌표계).
"""
import math

# 이름 규칙 (모두 대문자):  P = 일반 지점, Z = 구역 지점(ZA/ZB/ZC), I = 초기 위치(홈, I1/I2/I3),
#                           Z<구역>_EXIT = 구역 출구. (대기 앵커·슬롯 좌표는 매니저 zone_params.yaml 의 queue_anchor)
# 구역과 무관하게 반드시 있어야 하는 일반 지점 이름 (goto 허용 지점).
# 구역 지점(Z<구역>)과 홈(I<n>)은 zone_points / home_name 이 가리키고 validate_* 가 존재를 검사한다.
# 구역별 출구 지점(Z<구역>_EXIT)은 구역 이름에 따라 달라지므로
# required_names(zone_names) 가 덧붙인다. 이름 자체는 코드가 참조하므로 좌표와 달리 코드에 남긴다.
REQUIRED_POINTS = ('P1', 'P2')
# 일반 지점은 P1~P50 까지 쓸 수 있다. P3~P50 은 선택이라 YAML 에 좌표가 있는 것만 goto 로 갈 수 있다
# (좌표를 모르는 지점을 (0,0,0) 으로 채우면 goto 때 원점으로 가므로 아예 정의하지 않는다).
MAX_GENERAL_POINTS = 50


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
    :param home_name: 유휴 복귀할 홈 지점 이름 (I<n>) (``points`` 안에 있어야 함)
    :raises PointsConfigError: 누락된 이름을 한꺼번에 알려 준다 (하나씩 고치며 재시작하지 않게)
    """
    missing = [n for n in required if n not in points]
    if missing:
        raise PointsConfigError(
            f'필수 지점이 없습니다: {missing}. config/pinkyN.yaml 의 points 에 '
            f'[x, y] 또는 [x, y, yaw] 로 추가하세요 (YAML 을 지정했는지도 확인: launch 또는 --params-file).')
    if not home_name:
        raise PointsConfigError(
            'home_name 이 비어 있습니다. config/pinkyN.yaml 에 home_name: I1 처럼 지점 이름을 쓰세요.')
    if home_name not in points:
        raise PointsConfigError(
            f"home_name '{home_name}' 이(가) points 에 없습니다. 있는 지점: {sorted(points)}")


# ---------------------------------------------------------------------------
# 위험구역 (구역마다 출구 좌표 하나와 소속 지점 목록을 가진다)
# ---------------------------------------------------------------------------
def exit_name(zone):
    """구역 ``zone`` 의 출구(토큰 반납) 지점 이름. 예: ``A`` -> ``ZA_EXIT``."""
    return f'Z{zone}_EXIT'


def optional_general_names():
    """선택 일반 지점 이름 ``['P3', ..., 'P50']`` (YAML 에 있으면 읽고, 없으면 건너뛴다)."""
    return [f'P{i}' for i in range(len(REQUIRED_POINTS) + 1, MAX_GENERAL_POINTS + 1)]


def general_names(points):
    """``points`` 안의 일반 지점(P1~P50) 이름만 번호순으로 돌려준다."""
    allowed = {f'P{i}' for i in range(1, MAX_GENERAL_POINTS + 1)}
    return sorted((n for n in points if n in allowed), key=lambda n: int(n[1:]))


def required_names(zone_names):
    """일반 지점(P1, P2)과 구역별 출구(Z_EXIT)를 합친, ``points`` 에 반드시 있어야 하는 이름 목록."""
    names = list(REQUIRED_POINTS)
    for zone in zone_names:
        names.append(exit_name(zone))
    return names


def parse_zone_names(raw):
    """
    구역 이름 목록을 검증해 튜플로 돌려준다.

    이름은 Z<이름>_EXIT 지점 이름과 매니저 메시지(``<구역>:...``)에 그대로 쓰이므로
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
                f'zone_points.{zone}: 지점 이름 리스트여야 합니다 (예: [ZA, ZB]). 받은 값: {names!r}')
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
    - 출구(Z_EXIT) 는 구역 안 지점이 아니다 (경로 지점으로 직접 지정하지 못하게)

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
            if n in (exit_name(z) for z in zone_points):
                problems.append(f'zone_points.{zone}: {n} 는 출구 지점이라 소속 지점이 될 수 없습니다.')
            if n in owner:
                problems.append(f'{n} 가 구역 {owner[n]} 와 {zone} 에 동시에 속합니다.')
            owner[n] = zone
    if home_name in owner:
        problems.append(
            f'home_name {home_name} 가 구역 {owner[home_name]} 안에 있습니다. '
            '홈은 구역 밖 지점이어야 합니다.')
    if problems:
        raise PointsConfigError('구역 설정 오류: ' + ' / '.join(problems))


def zone_of(zone_points, name):
    """지점 ``name`` 이 속한 구역 이름. 구역 밖이면 ``None``."""
    for zone, members in zone_points.items():
        if name in members:
            return zone
    return None


# ---------------------------------------------------------------------------
# 명령 문자열 해석 (노드는 결과만 보고 동작을 정한다)
# ---------------------------------------------------------------------------
_NO_ARG_COMMANDS = ('leave', 'home', 'stop', 'emergency_stop', 'start')
_POINT_COMMANDS = ('goto', 'zone')


def parse_command(raw):
    """
    명령 문자열을 ``(kind, points)`` 로 해석한다. 예외는 던지지 않는다.

    - ``goto:<P>[,<P>...]`` / ``zone:<P>`` : kind 는 ``goto`` / ``zone``, points 는 대문자 이름 튜플
      (쉼표·공백 모두 구분자, 명령어는 대소문자 무시)
    - ``leave`` / ``home`` / ``stop`` / ``emergency_stop`` / ``start`` : 해당 kind, points 는 ``()``
    - 그 밖 (빈 문자열, 알 수 없는 명령, 문자열이 아닌 값) : ``('unknown', ())``

    형식만 본다. 지점이 비었는지·존재하는지·구역 지점인지·zone 에 1개만 왔는지는
    ``points`` 와 구역 설정을 아는 노드가 판단해 FAILED 로 응답한다.
    """
    if not isinstance(raw, str):
        return 'unknown', ()
    text = raw.strip()
    head, sep, tail = text.partition(':')
    head = head.strip().lower()
    if sep:
        if head in _POINT_COMMANDS:
            return head, tuple(tail.replace(',', ' ').upper().split())
        return 'unknown', ()
    if head in _NO_ARG_COMMANDS:
        return head, ()
    return 'unknown', ()
