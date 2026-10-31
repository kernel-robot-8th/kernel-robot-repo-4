"""pinky2의 기존 실행 이름을 유지하는 호환 진입점."""

from cobot_pinky_patrol.pinky_patrol_node import main as run_node
from cobot_pinky_patrol.pinky_patrol_node import PinkyPatrolNode as BasePatrolNode


class PinkyPatrolNode(BasePatrolNode):
    """로봇 차이는 기본 ID와 YAML 설정으로만 전달한다."""

    def __init__(self):
        super().__init__(default_robot_id='pinky2')


def main(args=None):
    """기존 ros2 run/launch 명령을 그대로 지원한다."""
    run_node(args=args, node_class=PinkyPatrolNode)


if __name__ == '__main__':
    main()
