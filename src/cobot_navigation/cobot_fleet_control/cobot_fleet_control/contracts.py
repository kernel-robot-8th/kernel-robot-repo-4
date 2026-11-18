"""외부 입력을 검증하고 로봇 실행 계약으로 변환한다."""

from dataclasses import dataclass
import math
import re


POSE_NAME = re.compile(r'[A-Z][A-Z0-9_]{0,31}')


def parse_poses(data):
    """
    관제 웨이포인트 좌표 ``{이름: [x, y] 또는 [x, y, yaw]}`` → 정렬된 튜플 (없으면 ``()``).

    순찰 노드(patrol_points_utils.parse_poses)와 같은 규칙이다. 이름 충돌·구역 거리는 PointRules 가 본다.
    """
    if data is None:
        return ()
    if not isinstance(data, dict) or len(data) > 50:
        raise ValueError('poses 는 최대 50개의 객체')
    out = []
    for name, value in data.items():
        if not isinstance(name, str) or not POSE_NAME.fullmatch(name):
            raise ValueError('poses 지점 이름 형식 오류')
        if (not isinstance(value, (list, tuple)) or len(value) not in (2, 3)
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in value)):
            raise ValueError(f'poses.{name}: 유한한 수 2~3개 ([x, y] 또는 [x, y, yaw])')
        x, y, yaw = (list(map(float, value)) + [0.0])[:3]
        out.append((name, (x, y, yaw)))
    return tuple(sorted(out))


@dataclass(frozen=True)
class Command:
    """재전송에도 유지되는 명령 ID와 업무 입력."""

    command_id: str
    robot_id: str
    operation: str
    points: tuple[str, ...] = ()
    timeout_sec: float = 300.0
    # 관제 웨이포인트 좌표 ((이름, (x, y, yaw)), ...). goto 에만. 순찰 노드가 봉투의 poses 로 받는다.
    poses: tuple = ()

    @classmethod
    def parse(cls, data, robots):
        """임의 ROS 토픽이나 문자열 명령 주입을 경계에서 차단한다."""
        if not isinstance(data, dict):
            raise ValueError('명령은 JSON 객체여야 합니다')
        allowed = {'command_id', 'robot_id', 'operation', 'points', 'timeout_sec', 'poses'}
        if set(data) - allowed:
            raise ValueError('알 수 없는 명령 필드')
        command_id = data.get('command_id')
        robot_id = data.get('robot_id')
        operation = data.get('operation')
        points = data.get('points', [])
        timeout = data.get('timeout_sec', 300.0)
        poses = parse_poses(data.get('poses'))
        if not isinstance(command_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', command_id):
            raise ValueError('command_id 형식 오류')
        if not isinstance(robot_id, str) or robot_id not in robots:
            raise ValueError('등록되지 않은 로봇')
        if not isinstance(operation, str) or operation not in {'goto', 'zone', 'leave', 'home'}:
            raise ValueError('지원 명령: goto, zone, leave, home')
        if not isinstance(points, list) or len(points) > 50:
            raise ValueError('points는 최대 50개의 배열')
        if any(not isinstance(p, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,31}', p)
               for p in points):
            raise ValueError('지점 이름 형식 오류')
        if ((operation == 'goto' and not points)
                or (operation == 'zone' and len(points) != 1)
                or (operation in {'leave', 'home'} and points)):
            raise ValueError('명령별 지점 개수 오류')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 1 <= timeout <= 3600):
            raise ValueError('timeout_sec 범위: 1~3600초')
        if poses and operation != 'goto':
            raise ValueError('poses 는 goto 에만 쓸 수 있습니다')
        if any(name not in points for name, _ in poses):
            raise ValueError('poses 에 경로에 없는 지점이 있습니다')
        return cls(command_id, robot_id, operation, tuple(points), float(timeout), poses)

    def wire(self):
        """기존 문자열 명령을 JSON 봉투에 넣어 점진적 배포를 지원한다."""
        suffix = ':' + ','.join(self.points) if self.points else ''
        wire = {'command_id': self.command_id, 'command': self.operation + suffix}
        if self.poses:
            wire['poses'] = {name: list(pose) for name, pose in self.poses}
        return wire

    def payload(self):
        """DB 중복 검사에 쓸 정규화된 입력."""
        payload = {'command_id': self.command_id, 'robot_id': self.robot_id,
                   'operation': self.operation, 'points': list(self.points),
                   'timeout_sec': self.timeout_sec}
        # 좌표가 없는 명령은 예전과 같은 모양 (DB 의 기존 기록과 비교가 그대로 맞게)
        if self.poses:
            payload['poses'] = {name: list(pose) for name, pose in self.poses}
        return payload
