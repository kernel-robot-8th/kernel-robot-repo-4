"""
핑키 장애물 회피 노드.

Nav2(velocity_smoother) 출력과 구동부(cmd_vel) 사이에 끼어 속도를 그대로 넘기거나
감속·정지·회피·후진 속도로 바꿔 낸다.

  velocity_smoother ─ cmd_vel_avoid_in ─▶ [이 노드] ─ cmd_vel ─▶ pinky_bringup

- 순찰 노드(cobot_pinky_patrol)의 patrol_status 가 주행 상태(MOVING 등)일 때만 회피한다.
  그 밖의 상태(대기열 QUEUEING, 구역 점유 HOLDING_ZONE 등)에서는 Nav2 속도를 그대로 넘긴다.
- 센서: 라이다(scan) 주 센서, 초음파(us_sensor/range) 정면 보조.
- 판단 로직은 scan_utils / tracker_utils / avoidance_utils 에 있고 이 파일은 입출력만 맡는다.
"""
import json
import math

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import LaserScan, Range
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from .avoidance_utils import AvoidanceController, AvoidanceParams, PASS, Perception
from .scan_utils import (centroid, cluster_extent, cluster_points, corridor_clearance,
                         polar_histogram, scan_to_points)
from .tracker_utils import min_ttc, ObstacleTracker, to_world


def _yaw_from_quat(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class ObstacleAvoidanceNode(Node):
    """scan·초음파·odom·patrol_status 를 받아 cmd_vel 을 결정하는 노드."""

    def __init__(self):
        """파라미터 선언, 구독·발행 생성."""
        super().__init__('obstacle_avoidance_node')

        # --- 토픽·frame ---
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('control_rate', 20.0)              # [Hz]
        self.declare_parameter('cmd_timeout', 0.5)                # [s] Nav2 명령이 끊겼다고 볼 시간
        self.declare_parameter('scan_timeout', 0.5)               # [s] 라이다가 끊겼다고 볼 시간

        # --- 회피를 켜는 조건 ---
        self.declare_parameter('use_patrol_gate', True)           # False 면 항상 회피 (시뮬 시험용)
        self.declare_parameter('active_states',
                               ['STARTING', 'MOVING', 'RETURNING', 'RETREATING', 'LEAVING_ZONE'])

        # --- 로봇 형상 ---
        self.declare_parameter('robot_front_x', 0.06)             # [m] 로봇 앞면 x
        self.declare_parameter('robot_rear_x', 0.06)              # [m] 로봇 뒷면 -x
        self.declare_parameter('corridor_half_width', 0.10)       # [m] 앞·뒤 통로 반폭 (여유 포함)

        # --- 초음파 ---
        self.declare_parameter('use_ultrasonic', False)           # 실물에서만 True (Gazebo 에 없음)
        self.declare_parameter('ultrasonic_x', 0.0267)            # [m] ultrasonic_link 의 x
        self.declare_parameter('ultrasonic_timeout', 0.5)         # [s]

        # --- 움직이는 장애물 추적 ---
        self.declare_parameter('track_range', 1.5)                # [m] 이 안의 덩어리만 추적
        self.declare_parameter('cluster_gap', 0.08)               # [m] 같은 덩어리로 묶는 점 간격
        self.declare_parameter('cluster_min_points', 3)
        self.declare_parameter('cluster_max_extent', 0.5)         # [m] 이보다 큰 덩어리(벽)는 추적 안 함
        self.declare_parameter('track_match_dist', 0.25)          # [m]
        self.declare_parameter('track_max_age', 0.5)              # [s]
        self.declare_parameter('track_alpha', 0.4)
        self.declare_parameter('track_min_hits', 3)
        self.declare_parameter('moving_min_speed', 0.08)          # [m/s] 이 이상이면 움직이는 물체
        self.declare_parameter('collision_radius', 0.25)          # [m] TTC 계산용 로봇+물체 반경

        # --- 회피 판단 ---
        self.declare_parameter('histogram_sectors', 72)
        self.declare_parameter('histogram_range', 1.5)            # [m]
        defaults = AvoidanceParams()
        for name in AvoidanceParams.__dataclass_fields__:
            self.declare_parameter(name, float(getattr(defaults, name)))

        gp = self.get_parameter
        self.base_frame = gp('base_frame').value
        self.cmd_timeout = gp('cmd_timeout').value
        self.scan_timeout = gp('scan_timeout').value
        self.use_patrol_gate = gp('use_patrol_gate').value
        self.active_states = set(gp('active_states').value)
        self.front_x = gp('robot_front_x').value
        self.rear_x = gp('robot_rear_x').value
        self.half_width = gp('corridor_half_width').value
        self.use_us = gp('use_ultrasonic').value
        self.us_x = gp('ultrasonic_x').value
        self.us_timeout = gp('ultrasonic_timeout').value
        self.track_range = gp('track_range').value
        self.cluster_gap = gp('cluster_gap').value
        self.cluster_min_points = gp('cluster_min_points').value
        self.cluster_max_extent = gp('cluster_max_extent').value
        self.moving_min_speed = gp('moving_min_speed').value
        self.collision_radius = gp('collision_radius').value
        self.n_sectors = gp('histogram_sectors').value
        self.hist_range = gp('histogram_range').value

        params = AvoidanceParams(**{n: gp(n).value
                                    for n in AvoidanceParams.__dataclass_fields__})
        self.controller = AvoidanceController(params)
        self.tracker = ObstacleTracker(gp('track_match_dist').value, gp('track_max_age').value,
                                       gp('track_alpha').value, gp('track_min_hits').value)

        # --- 상태 ---
        self.patrol_state = None
        self.enabled = not self.use_patrol_gate
        self.nav_cmd = (0.0, 0.0)
        self.nav_t = None
        self.perception = None
        self.lidar_front = math.inf
        self.scan_t = None
        self.us_clearance = math.inf
        self.us_t = None
        self.pose = None
        self.robot_vel = (0.0, 0.0)
        self.lidar_tf = None
        self.last_out_zero = True
        self.last_state = None

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.state_pub = self.create_publisher(String, 'obstacle_avoidance/state', 10)
        self.create_subscription(Twist, 'cmd_vel_avoid_in', self._cmd_cb, 10)
        self.create_subscription(LaserScan, 'scan', self._scan_cb, qos_profile_sensor_data)
        self.create_subscription(Range, 'us_sensor/range', self._us_cb, qos_profile_sensor_data)
        self.create_subscription(Odometry, 'odom', self._odom_cb, 10)
        self.create_subscription(String, 'patrol_status', self._status_cb, 10)
        self.create_timer(1.0 / gp('control_rate').value, self._control_tick)

        self.get_logger().info(
            f'obstacle_avoidance 시작 (patrol_gate={self.use_patrol_gate}, '
            f'ultrasonic={self.use_us})')

    # ------------------------------------------------------------------ 입력
    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _status_cb(self, msg):
        try:
            state = json.loads(msg.data).get('state')
        except (ValueError, AttributeError):
            self.get_logger().warn(f'patrol_status 해석 실패: {msg.data}')
            return
        self.patrol_state = state
        enabled = (not self.use_patrol_gate) or state in self.active_states
        if enabled != self.enabled:
            self.enabled = enabled
            if not enabled:
                self.controller.reset()
            self.get_logger().info(f'회피 {"켬" if enabled else "끔"} (patrol state={state})')

    def _cmd_cb(self, msg):
        self.nav_cmd = (msg.linear.x, msg.angular.z)
        self.nav_t = self._now()
        if not self.enabled:
            # 회피가 꺼져 있으면 Nav2 명령을 손대지 않고 바로 넘긴다.
            self.cmd_pub.publish(msg)
            self.last_out_zero = msg.linear.x == 0.0 and msg.angular.z == 0.0

    def _odom_cb(self, msg):
        p = msg.pose.pose
        yaw = _yaw_from_quat(p.orientation)
        self.pose = (p.position.x, p.position.y, yaw)
        v = msg.twist.twist.linear.x
        self.robot_vel = (v * math.cos(yaw), v * math.sin(yaw))

    def _us_cb(self, msg):
        if not (msg.min_range <= msg.range <= msg.max_range):
            self.us_clearance = math.inf
        else:
            # 초음파는 로봇 앞면보다 안쪽(ultrasonic_x)에 있으므로 앞면 기준 여유로 바꾼다.
            self.us_clearance = msg.range - (self.front_x - self.us_x)
        self.us_t = self._now()

    def _lookup_lidar_tf(self, frame):
        try:
            tf = self.tf_buffer.lookup_transform(self.base_frame, frame, Time())
        except TransformException as e:
            self.get_logger().warn(f'TF {self.base_frame}<-{frame} 대기 중: {e}',
                                   throttle_duration_sec=5.0)
            return None
        tr = tf.transform.translation
        return (tr.x, tr.y, _yaw_from_quat(tf.transform.rotation))

    def _scan_cb(self, msg):
        if self.lidar_tf is None:
            # 라이다는 로봇에 고정이라 한 번만 조회한다.
            self.lidar_tf = self._lookup_lidar_tf(msg.header.frame_id)
            if self.lidar_tf is None:
                return
        t = self._now()
        tx, ty, yaw = self.lidar_tf
        points = scan_to_points(msg.ranges, msg.angle_min, msg.angle_increment,
                                msg.range_min, msg.range_max, tx, ty, yaw)
        self.lidar_front = corridor_clearance(points, self.half_width, self.front_x, True)
        rear = corridor_clearance(points, self.half_width, self.rear_x, False)

        ttc = math.inf
        if self.pose is not None:
            near = [p for p in points if math.hypot(p[0], p[1]) <= self.track_range]
            centroids = [to_world(centroid(c), self.pose)
                         for c in cluster_points(near, self.cluster_gap)
                         if len(c) >= self.cluster_min_points
                         and cluster_extent(c) <= self.cluster_max_extent]
            self.tracker.update(centroids, t)
            ttc = min_ttc(self.tracker.moving_tracks(self.moving_min_speed), self.pose,
                          self.robot_vel, self.collision_radius)

        self.perception = Perception(
            front=self.lidar_front, rear=rear, ttc=ttc,
            hist=polar_histogram(points, self.n_sectors, self.hist_range))
        self.scan_t = t

    # ------------------------------------------------------------------ 제어
    def _publish(self, v, w):
        msg = Twist()
        msg.linear.x = float(v)
        msg.angular.z = float(w)
        self.cmd_pub.publish(msg)
        self.last_out_zero = v == 0.0 and w == 0.0

    def _publish_state(self, state):
        if state != self.last_state:
            self.last_state = state
            self.state_pub.publish(String(data=state))
            if state != PASS:
                self.get_logger().info(f'회피 상태: {state}')

    def _control_tick(self):
        if not self.enabled:
            return
        t = self._now()
        if self.nav_t is None or t - self.nav_t > self.cmd_timeout:
            # Nav2 가 멈췄으면 이 노드도 조용히 있는다(다른 노드의 cmd_vel 을 가리지 않게).
            if not self.last_out_zero:
                self._publish(0.0, 0.0)
            self.controller.reset()
            self._publish_state(PASS)
            return
        if self.perception is None or t - self.scan_t > self.scan_timeout:
            self.get_logger().warn('라이다 scan 이 끊겨 정지합니다', throttle_duration_sec=2.0)
            self._publish(0.0, 0.0)
            self._publish_state('NO_SCAN')
            return

        per = self.perception
        front = per.front
        if self.use_us and self.us_t is not None and t - self.us_t <= self.us_timeout:
            front = min(front, self.us_clearance)
        per = Perception(front=front, rear=per.rear, ttc=per.ttc, hist=per.hist)

        state, v, w = self.controller.step(True, self.nav_cmd[0], self.nav_cmd[1], per, t)
        self._publish(v, w)
        self._publish_state(state)


def main(args=None):
    """노드 진입점."""
    rclpy.init(args=args)
    node = ObstacleAvoidanceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
