"""외부 입력을 검증하고 로봇 실행 계약으로 변환한다."""

from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Command:
    """재전송에도 유지되는 명령 ID와 업무 입력."""

    command_id: str
    robot_id: str
    operation: str
    points: tuple[str, ...] = ()
    timeout_sec: float = 300.0

    @classmethod
    def parse(cls, data, robots):
        """임의 ROS 토픽이나 문자열 명령 주입을 경계에서 차단한다."""
        if not isinstance(data, dict):
            raise ValueError('명령은 JSON 객체여야 합니다')
        allowed = {'command_id', 'robot_id', 'operation', 'points', 'timeout_sec'}
        if set(data) - allowed:
            raise ValueError('알 수 없는 명령 필드')
        command_id = data.get('command_id')
        robot_id = data.get('robot_id')
        operation = data.get('operation')
        points = data.get('points', [])
        timeout = data.get('timeout_sec', 300.0)
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
        return cls(command_id, robot_id, operation, tuple(points), float(timeout))

    def wire(self):
        """기존 문자열 명령을 JSON 봉투에 넣어 점진적 배포를 지원한다."""
        suffix = ':' + ','.join(self.points) if self.points else ''
        return {'command_id': self.command_id, 'command': self.operation + suffix}

    def payload(self):
        """DB 중복 검사에 쓸 정규화된 입력."""
        return {'command_id': self.command_id, 'robot_id': self.robot_id,
                'operation': self.operation, 'points': list(self.points),
                'timeout_sec': self.timeout_sec}
