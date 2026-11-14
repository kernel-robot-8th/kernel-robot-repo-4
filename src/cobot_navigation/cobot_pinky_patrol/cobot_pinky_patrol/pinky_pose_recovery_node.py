"""
위치 재설정 노드 (PoseRecoveryNode).

충돌 등으로 위치가 틀어졌을 때, 사람이 로봇을 waypoint 좌표에 놓고 그 이름을 보내면
노드가 그 좌표로 AMCL 초기 위치를 다시 잡는다. 판정·좌표 읽기 규칙은 pose_recovery_utils.py,
값은 config/pose_recovery.yaml 파라미터, 설계는 docs/prd/[진행] pose_reset_by_waypoint_prd.md.

  1. pose_reset_cmd(std_msgs/String) 로 waypoint 이름(예: P3)을 받는다.
  2. points_file 에서 좌표를 읽어 /initialpose 로 발행한다.
  3. /amcl_pose 공분산이 수렴하면 CONVERGED.
  4. 수렴하지 않으면 제자리에서 좌우로 스캔하고(왼쪽 -> 오른쪽 -> 정면), 그래도 안 되면 한 바퀴 돈다.
     회전량은 시간이 아니라 오도메트리(odom)의 yaw 변화량으로 재고, 수렴하는 즉시 멈춘다.

[상태 발행]  (토픽: pose_recovery_status, JSON {"state": ..., "detail": ...})
  RESETTING / SCANNING_LR / SCANNING / CONVERGED / FAILED

[스캔 안전 감시]  아래 경우는 즉시 정지하고 FAILED 로 끝낸다 (한 바퀴 fallback 없음).
  odom 이 없다(회전 시작 전) / 스캔 중 odom 이 끊겼다 / 한 구간이 계획 시간 x 계수 안에 목표 각도에 못 닿았다.

주의: 스캔은 cmd_vel 을 직접 내므로 patrol 이동 중에는 쓰지 않는다. 노드는 이를 검사하지 않는다.
"""
import signal
import threading
import time

from cobot_pinky_patrol.patrol_points_utils import PointsConfigError
from cobot_pinky_patrol.pose_recovery_utils import (
    build_status, FULL_TURN_RAD, get_waypoint, is_converged, LEFT, load_waypoints,
    make_initialpose_cov, plan_lr_scan, quat_from_yaw, RotationTracker, segment_timeout_sec,
    UnknownWaypointError, validate_scan_params, yaw_from_quat)

from geometry_msgs.msg import PoseWithCovarianceStamped, Twist

from nav_msgs.msg import Odometry

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    qos_profile_sensor_data, QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy)
from rclpy.signals import SignalHandlerOptions

from std_msgs.msg import String

POLL_SEC = 0.1          # 구독자·수렴 확인 주기
REPEAT_GAP_SEC = 0.3    # /initialpose 재발행 간격
CMD_PERIOD_SEC = 0.1    # 회전 명령 발행 주기
STOP_REPEAT = 3         # 정지 명령 발행 횟수 (유실 대비)
STOP_GAP_SEC = 0.05     # 정지 명령 사이 간격
SPIN_PERIOD_SEC = 0.1   # 메인 루프 주기: 이 간격마다 Python 이 시그널(Ctrl+C, SIGTERM)을 처리한다
JOIN_TIMEOUT_SEC = 2.0  # 종료 때 작업 스레드를 기다리는 시간

# 스캔 결과 종류
SCAN_CONVERGED = 'converged'   # 스캔 중 수렴했다 (이미 정지)
SCAN_DONE = 'done'             # 모든 구간을 마쳤지만 수렴하지 못했다
SCAN_FAILED = 'failed'         # 안전 감시에 걸렸다 (detail 에 이유)


class PoseRecoveryNode(Node):

    def __init__(self):
        super().__init__('pinky_pose_recovery_node')

        self.declare_parameter('points_file', '')              # waypoint 를 읽을 pinkyN.yaml
        self.declare_parameter('reset_topic', 'pose_reset_cmd')
        self.declare_parameter('reset_amcl_wait_sec', 5.0)     # /initialpose 구독자 대기
        self.declare_parameter('initial_cov_xy', 0.25)         # [m^2] 보낼 위치 분산
        self.declare_parameter('initial_cov_yaw', 0.3)         # [rad^2] 보낼 방향 분산
        self.declare_parameter('initialpose_repeat', 3)        # 유실 대비 재발행 횟수
        self.declare_parameter('max_cov_xy', 0.05)             # [m^2] 수렴 위치 분산 상한
        self.declare_parameter('max_cov_yaw', 0.1)             # [rad^2] 수렴 방향 분산 상한
        self.declare_parameter('converge_timeout_sec', 5.0)    # 발행 후 수렴 대기
        self.declare_parameter('scan_angular_speed', 0.3)      # [rad/s] 스캔 회전 속도
        self.declare_parameter('scan_half_angle_rad', 1.5)     # [rad] 좌우 스캔 한쪽 각도
        self.declare_parameter('scan_full_turn_fallback', True)  # 좌우 실패 시 한 바퀴 스캔도 시도
        self.declare_parameter('odom_topic', 'odom')           # 회전량을 재는 오도메트리
        self.declare_parameter('scan_angle_tolerance_rad', 0.05)  # [rad] 목표 각도 도달 허용 오차
        self.declare_parameter('scan_odom_stale_sec', 1.0)     # [s] odom 이 이 시간 끊기면 정지
        self.declare_parameter('scan_timeout_factor', 2.0)     # 구간 계획 시간의 이 배수를 넘기면 정지

        def p(name):
            return self.get_parameter(name).value

        self.points_file = str(p('points_file'))
        self.amcl_wait = float(p('reset_amcl_wait_sec'))
        self.initial_cov_xy = float(p('initial_cov_xy'))
        self.initial_cov_yaw = float(p('initial_cov_yaw'))
        self.initialpose_repeat = max(1, int(p('initialpose_repeat')))
        self.max_cov_xy = float(p('max_cov_xy'))
        self.max_cov_yaw = float(p('max_cov_yaw'))
        self.converge_timeout = float(p('converge_timeout_sec'))
        self.scan_speed = float(p('scan_angular_speed'))
        self.half_angle = float(p('scan_half_angle_rad'))
        self.full_turn_fallback = bool(p('scan_full_turn_fallback'))
        self.angle_tolerance = float(p('scan_angle_tolerance_rad'))
        self.odom_stale = float(p('scan_odom_stale_sec'))
        self.timeout_factor = float(p('scan_timeout_factor'))
        # 명령을 받고 /initialpose 까지 보낸 뒤에야 터지지 않도록 시작할 때 검사한다
        validate_scan_params(self.half_angle, self.scan_speed, self.angle_tolerance,
                             self.odom_stale, self.timeout_factor)

        self._lock = threading.Lock()
        self._running = False          # reset 작업 스레드가 도는 중인지 (한 번에 하나만)
        self._thread = None
        self._stop_event = threading.Event()   # 노드 종료 때 스캔 루프를 끊는다
        self._latest = None            # 가장 최근 /amcl_pose 의 공분산
        self._latest_mono = 0.0        # 그 메시지를 받은 monotonic 시각
        self._odom_yaw = None          # 가장 최근 odom 의 yaw [rad]
        self._odom_mono = 0.0          # 그 메시지를 받은 monotonic 시각

        # nav2 AMCL 의 amcl_pose 발행 QoS 와 맞춘다
        amcl_qos = QoSProfile(depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
                              durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(PoseWithCovarianceStamped, 'amcl_pose', self._amcl_cb, amcl_qos)
        # best effort 구독은 reliable, best effort 발행자 모두와 연결된다
        self.create_subscription(
            Odometry, str(p('odom_topic')), self._odom_cb, qos_profile_sensor_data)
        self.create_subscription(String, str(p('reset_topic')), self._reset_cb, 10)
        self.initialpose_pub = self.create_publisher(PoseWithCovarianceStamped, 'initialpose', 10)
        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.status_pub = self.create_publisher(String, 'pose_recovery_status', 10)

        self.get_logger().info(
            f"위치 재설정 노드 시작 (points_file={self.points_file or '(없음)'}, "
            f"reset_topic={p('reset_topic')}, odom_topic={p('odom_topic')})")

    # ---------------------------------------------------------------- 상태 발행
    def publish_status(self, state, detail=''):
        self.status_pub.publish(String(data=build_status(state, detail)))
        self.get_logger().info(f'status: {state} {detail}')

    # ---------------------------------------------------------------- 수신
    def _amcl_cb(self, msg):
        with self._lock:
            self._latest = list(msg.pose.covariance)
            self._latest_mono = time.monotonic()

    def _odom_cb(self, msg):
        q = msg.pose.pose.orientation
        with self._lock:
            self._odom_yaw = yaw_from_quat(q.z, q.w)
            self._odom_mono = time.monotonic()

    def _snapshot(self):
        with self._lock:
            return self._latest, self._latest_mono

    def _odom_snapshot(self):
        with self._lock:
            return self._odom_yaw, self._odom_mono

    def _odom_alive(self):
        """오도메트리를 받은 적이 있고 scan_odom_stale_sec 안에 갱신되었으면 True."""
        yaw, t = self._odom_snapshot()
        return yaw is not None and time.monotonic() - t <= self.odom_stale

    # ---------------------------------------------------------------- 명령 수신
    def _reset_cb(self, msg):
        with self._lock:
            busy = self._running
            if not busy:
                self._running = True
        if busy:
            self.publish_status('FAILED', 'busy')
            return
        self._thread = threading.Thread(target=self._reset, args=(msg.data,), daemon=True)
        self._thread.start()

    def _reset(self, name):
        try:
            self._reset_steps(name)
        except Exception as e:  # 작업 스레드가 조용히 죽지 않게 상태로 알린다
            self.get_logger().error(f'재설정 중 오류: {e}')
            self.publish_status('FAILED', f'error: {e}')
        finally:
            with self._lock:
                self._running = False

    # ---------------------------------------------------------------- 재설정 절차
    def _reset_steps(self, name):
        if not self.points_file:
            self.publish_status('FAILED', 'points_file 이 비어 있습니다')
            return
        # 명령마다 읽는다: yaml 의 좌표를 고쳐도 노드를 다시 켜지 않아도 된다
        try:
            points = load_waypoints(self.points_file)
            x, y, yaw = get_waypoint(points, name)
        except UnknownWaypointError as e:
            self.get_logger().warn(str(e))   # 있는 지점 목록이 길어서 상태 토픽에는 싣지 않는다
            self.publish_status('FAILED', f'unknown waypoint: {name!r}')
            return
        except PointsConfigError as e:
            self.publish_status('FAILED', f'points_file: {e}')
            return
        key = name.strip().upper()
        if len(points[key]) == 2:
            self.get_logger().info(f'{key}: yaw 가 없어 0.0 으로 처리합니다')

        self.publish_status('RESETTING', f'{key} x={x:.2f} y={y:.2f} yaw={yaw:.2f}')
        if not self._wait_initialpose_subscriber():
            self.publish_status('FAILED', 'no amcl: /initialpose 구독자가 없습니다')
            return
        self._publish_initialpose(x, y, yaw)

        # 마지막 발행 이후에 받은 pose 만 본다 (발행 전의 옛 pose 가 수렴으로 보이는 것을 막는다)
        after = time.monotonic()
        if self._wait_converged(after, self.converge_timeout):
            self.publish_status('CONVERGED', key)
            return

        # ---- 수렴하지 못했다: 스캔 ----
        if not self._odom_alive():
            self.publish_status('FAILED', 'no odom: 회전하지 않습니다')
            return
        self.publish_status(
            'SCANNING_LR', f'{self.half_angle:g} rad, {self.scan_speed:g} rad/s')
        if self._finish_scan(self._scan_lr(after), after, key):
            return
        if self.full_turn_fallback:
            self.publish_status('SCANNING', f'{FULL_TURN_RAD:.2f} rad, {self.scan_speed:g} rad/s')
            if self._finish_scan(self._rotate(LEFT, FULL_TURN_RAD, after), after, key):
                return
        self.publish_status('FAILED', 'not converged')

    def _finish_scan(self, result, after, key):
        """스캔 결과를 상태로 알린다. 상태를 발행해 끝냈으면 True, 다음 단계로 넘어가야 하면 False."""
        kind, detail = result
        if kind == SCAN_CONVERGED:
            self.publish_status('CONVERGED', f'{key} scan')
            return True
        if kind == SCAN_FAILED:
            self.publish_status('FAILED', detail)
            return True
        # 모든 구간을 마쳤다: 정지한 채로 마지막 확인
        if self._wait_converged(after, self.converge_timeout):
            self.publish_status('CONVERGED', f'{key} scan')
            return True
        return False

    def _wait_initialpose_subscriber(self):
        deadline = time.monotonic() + self.amcl_wait
        while self.initialpose_pub.get_subscription_count() == 0:
            if time.monotonic() >= deadline or not rclpy.ok():
                return False
            time.sleep(POLL_SEC)
        return True

    def _publish_initialpose(self, x, y, yaw):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = quat_from_yaw(yaw)
        msg.pose.covariance = make_initialpose_cov(self.initial_cov_xy, self.initial_cov_yaw)
        for _ in range(self.initialpose_repeat):
            msg.header.stamp = self.get_clock().now().to_msg()
            self.initialpose_pub.publish(msg)
            time.sleep(REPEAT_GAP_SEC)

    def _converged_since(self, after_mono):
        """after_mono 이후에 받은 pose 가 수렴했으면 True."""
        cov, t = self._snapshot()
        return (cov is not None and t > after_mono
                and is_converged(cov, self.max_cov_xy, self.max_cov_yaw))

    def _wait_converged(self, after_mono, timeout):
        """after_mono 이후에 받은 pose 가 timeout 안에 수렴하면 True."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and rclpy.ok():
            if self._converged_since(after_mono):
                return True
            time.sleep(POLL_SEC)
        return False

    # ---------------------------------------------------------------- 스캔 (오도메트리 기반)
    def _scan_lr(self, after_mono):
        """왼쪽 -> 오른쪽 -> 정면 순으로 돈다. 구간마다 결과를 보고 수렴이나 실패면 거기서 끝낸다."""
        for direction, angle in plan_lr_scan(self.half_angle):
            result = self._rotate(direction, angle, after_mono)
            if result[0] != SCAN_DONE:
                return result
        return SCAN_DONE, ''

    def _rotate(self, direction, angle, after_mono):
        """
        direction(+1 왼쪽 / -1 오른쪽) 으로 angle [rad] 만큼 제자리 회전한다. 회전량은 odom yaw 변화로 잰다.

        :return: (SCAN_CONVERGED | SCAN_DONE | SCAN_FAILED, 이유)
        어떤 경우에도 (예외 포함) 명령을 낸 적이 있으면 빠져나올 때 정지 명령을 보낸다.
        """
        yaw, last_mono = self._odom_snapshot()
        if yaw is None or time.monotonic() - last_mono > self.odom_stale:
            return SCAN_FAILED, 'no odom: 회전하지 않습니다'
        tracker = RotationTracker(yaw)
        timeout = segment_timeout_sec(angle, self.scan_speed, self.timeout_factor)
        twist = Twist()
        twist.angular.z = direction * self.scan_speed
        start = time.monotonic()
        moved = False
        try:
            while True:
                if self._stop_event.is_set() or not rclpy.ok():
                    return SCAN_FAILED, 'aborted'
                now = time.monotonic()
                yaw, odom_mono = self._odom_snapshot()
                if now - odom_mono > self.odom_stale:
                    return SCAN_FAILED, 'odom lost'
                if odom_mono != last_mono:
                    tracker.update(yaw)
                    last_mono = odom_mono
                if self._converged_since(after_mono):
                    return SCAN_CONVERGED, ''
                if direction * tracker.total >= angle - self.angle_tolerance:
                    return SCAN_DONE, ''
                if now - start > timeout:
                    return SCAN_FAILED, 'scan timeout'
                self.cmd_pub.publish(twist)
                moved = True
                time.sleep(CMD_PERIOD_SEC)
        finally:
            if moved:
                self._stop_robot()

    def _stop_robot(self):
        for _ in range(STOP_REPEAT):
            self.cmd_pub.publish(Twist())
            time.sleep(STOP_GAP_SEC)

    # ---------------------------------------------------------------- 종료
    def stop_scan(self):
        """진행 중인 스캔을 끊고 작업 스레드가 정지 명령을 낼 때까지 기다린다. 끝까지 안 끝나면 직접 정지시킨다."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(JOIN_TIMEOUT_SEC)
            if thread.is_alive():
                self.get_logger().error('작업 스레드가 끝나지 않아 직접 정지시킵니다')
                self._stop_robot()


def _raise_interrupt(signum, frame):
    """SIGTERM(ros2 launch 가 SIGINT 뒤에 보낸다) 도 Ctrl+C 와 같은 정리 경로를 타게 한다."""
    raise KeyboardInterrupt


def main(args=None):
    # 기본 시그널 핸들러는 컨텍스트를 먼저 닫아 버려서, 정지 명령을 낼 수 없게 된다. Python 기본 처리를 쓴다.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGTERM, _raise_interrupt)
    node = None
    executor = SingleThreadedExecutor()
    try:
        node = PoseRecoveryNode()
        executor.add_node(node)
        while True:
            executor.spin_once(timeout_sec=SPIN_PERIOD_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.stop_scan()
            executor.remove_node(node)
            node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
