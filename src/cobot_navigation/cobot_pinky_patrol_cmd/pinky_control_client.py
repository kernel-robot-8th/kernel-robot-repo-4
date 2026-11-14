import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import sys
import time


ACTIONS = 'start|stop|emergency_stop|monitor|goto|zone|leave|home'


def build_command(action, points):
    """
    동작 이름과 포인트 목록을 로봇에 보낼 명령 문자열로 바꾼다 (ROS 와 무관한 순수 함수).

    :return: (명령 문자열, 오류 메시지). 성공이면 오류 메시지는 None, 실패면 명령이 None.
    """
    pts = [p.upper() for p in points]
    if action in ('start', 'stop', 'emergency_stop'):
        return action, None
    if action == 'goto':
        if not pts:
            return None, '포인트가 필요합니다. 예: pinky1 goto P1 P2  (구역 지점은 zone 으로 보내세요)'
        return 'goto:' + ','.join(pts), None
    if action == 'zone':
        if len(pts) != 1:
            return None, 'zone 은 구역 지점 1개가 필요합니다. 예: pinky1 zone ZA'
        return 'zone:' + pts[0], None
    if action in ('leave', 'home'):
        if pts:
            return None, f'{action} 는 포인트를 받지 않습니다. 예: pinky1 {action}'
        return action, None
    return None, '알 수 없는 명령: ' + action


class PatrolClient(Node):
    """
    관제 PC에서 실행하는 노드.
    - 로봇에게 명령(start / stop / emergency_stop / goto / zone / leave)을 보낸다.   (publisher)
      (v3 순찰 노드용: stop 은 구역 밖으로 후퇴해 토큰 반납, emergency_stop 은 그 자리 정지 + 토큰 유지)
    - 로봇의 상태(status)를 구독해서 화면에 출력한다. (subscriber)
    """

    def __init__(self, namespace):
        # 노드 이름 = 'patrol_client_' + 로봇 이름
        # 예) namespace가 'pinky1' → 'patrol_client_pinky1'
        # (로봇마다 이름이 달라야 여러 개를 동시에 실행해도 충돌하지 않음)
        super().__init__('patrol_client_' + namespace)

        # [Publisher] 로봇에게 명령을 보내는 통로
        # 예) '/pinky1/patrol_cmd'  (String 타입, 큐 크기 10)
        topic_cmd = '/' + namespace + '/patrol_cmd'
        self.cmd_pub = self.create_publisher(String, topic_cmd, 10)

        # [Subscriber] 로봇이 보내는 상태를 받는 통로
        # 예) '/pinky1/patrol_status'
        # 메시지가 도착하면 self.status_callback 이 자동 호출됨
        topic_status = '/' + namespace + '/patrol_status'
        self.create_subscription(String, topic_status, self.status_callback, 10)

    def status_callback(self, msg):
        # 로봇이 상태를 보낼 때마다 자동 실행 (우리가 직접 호출하지 않음)
        print('상태 수신:', msg.data)

    def send_command(self, cmd):
        # 노드가 켜진 직후에는 로봇과 연결(discovery)이 안 됐을 수 있음
        # → 1초 기다린 뒤 보내야 메시지가 유실되지 않음
        time.sleep(1.0)

        msg = String()             # 1) 빈 메시지 상자 생성
        msg.data = cmd             # 2) 상자(.data)에 명령 문자열 담기
        self.cmd_pub.publish(msg)  # 3) 토픽으로 전송

        # [설계 이유]
        # start / stop / emergency_stop / goto / zone / leave 마다 함수를 따로 만들지 않고,
        # 문자열만 바꿔 넣는 하나의 함수로 통합 → 명령이 늘어나도 코드 수정이 적음


def main():
    # 실행 형식: python3 pinky_control_client.py <pinky1|pinky2|pinky3> <동작> [포인트...]
    # sys.argv[0]=파일명, [1]=로봇 이름, [2]=동작, [3:]=포인트들
    # → 최소 3개(파일명, 로봇, 동작)가 없으면 사용법 출력 후 종료
    if len(sys.argv) < 3:
        print(f'사용법: python3 pinky_control_client.py <pinky1|pinky2|pinky3> <{ACTIONS}> [포인트]')
        print('예시  : python3 pinky_control_client.py pinky1 goto P1 P2     (구역 밖 지점으로 이동, 홈으로 가지 않음)')
        print('        python3 pinky_control_client.py pinky1 zone ZA        (구역 지점으로 이동, 토큰 유지)')
        print('        python3 pinky_control_client.py pinky1 leave          (구역 EXIT 로 나가 토큰 반납)')
        print('        python3 pinky_control_client.py pinky1 home           (초기 위치 I<n> 으로 복귀)')
        print('        python3 pinky_control_client.py pinky1 emergency_stop')
        return

    namespace = sys.argv[1]   # 예) 'pinky1'
    action = sys.argv[2]      # 예) 'zone'

    # ── monitor 가 아니면 명령을 먼저 만들어 본다 (잘못된 입력은 ROS 를 켜지 않고 안내) ──
    #   stop           : 멈춘 뒤 구역 안이면 그 구역 EXIT 로 나와 토큰 반납
    #   emergency_stop : 그 자리 정지 + 토큰 유지 (max_hold_sec 뒤 자동 해제)
    #   goto 'goto P1 P2' → 'goto:P1,P2' / zone 'zone ZA' → 'zone:ZA' / leave → 'leave'
    #   마지막 명령 뒤 idle_return_sec(기본 120초) 동안 새 명령이 없으면 로봇이 스스로 홈으로 복귀한다.
    cmd = None
    if action != 'monitor':
        cmd, error = build_command(action, sys.argv[3:])
        if error:
            print(error)
            return

    rclpy.init()                    # ROS2 통신 시작 (노드 만들기 전에 필수)
    node = PatrolClient(namespace)

    if cmd is not None:
        node.send_command(cmd)
        print(namespace, '에게', cmd, '명령 전송 완료')

    # ── monitor : 종료 전까지 계속 상태 수신 ──
    else:
        print(namespace, '상태 모니터링 시작 (Ctrl+C로 종료)')
        rclpy.spin(node)   # 계속 대기하며 status_callback 실행

    # 뒷정리 (노드 삭제 → ROS2 종료)
    node.destroy_node()
    rclpy.shutdown()


# 이 파일을 직접 실행했을 때만 main() 호출
# (다른 파일에서 import 할 때는 실행되지 않음)
if __name__ == '__main__':
    main()