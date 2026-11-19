"""
핑키 장애물 회피 노드.

Nav2(velocity_smoother) 출력과 구동부(cmd_vel) 사이에 끼어 속도를 그대로 넘기거나
감속·정지·회피·후진 속도로 바꿔 낸다.

  velocity_smoother ─ cmd_vel_avoid_in ─▶ [이 노드] ─ cmd_vel ─▶ pinky_bringup

- 순찰 노드(cobot_pinky_patrol)의 patrol_status 가 주행 상태(MOVING 등)일 때만 회피한다.
  그 밖의 상태(대기열 QUEUEING, 구역 점유 HOLDING_ZONE 등)에서는 Nav2 속도를 그대로 넘긴다.
- 센서: 라이다(scan) 주 센서, 초음파(us_sensor/range) 정면 보조.
- use_person_detection 이 켜져 있으면 cobot_person_detector 의 사람 bbox(person_detections)를
  라이다 점과 이어 붙여, 앞 구역의 사람에게는 회피 대신 정지(PERSON_WAIT) 후 재출발한다.
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
from sensor_msgs.msg import CameraInfo, LaserScan, Range
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from .avoidance_utils import AvoidanceController, AvoidanceParams, PASS, Perception
from .person_utils import bbox_bearing_interval, camera_intrinsics, person_points
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

        # --- 사람 인식(YOLO) 연동 ---
        self.declare_parameter('use_person_detection', False)
        self.declare_parameter('person_topic', 'person_detections')
        self.declare_parameter('camera_info_topic', 'camera/camera_info')
        self.declare_parameter('camera_frame', 'front_camera_link')
        self.declare_parameter('camera_hfov', 1.1519)             # [rad] camera_info 없을 때
        self.declare_parameter('camera_image_width', 640)         # [px] camera_info 없을 때
        self.declare_parameter('person_min_score', 0.5)
        self.declare_parameter('person_timeout', 1.0)             # [s] 인식 결과 유효 시간
        self.declare_parameter('person_bearing_margin', 0.05)     # [rad] bbox 방향 여유
        self.declare_parameter('person_max_range', 3.0)           # [m]
        self.declare_parameter('person_half_width', 0.30)         # [m] 사람 정지 구역 반폭
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
        self.use_person = gp('use_person_detection').value
        self.camera_frame = gp('camera_frame').value
        self.camera_hfov = gp('camera_hfov').value
        self.camera_width = gp('camera_image_width').value
        self.person_min_score = gp('person_min_score').value
        self.person_timeout = gp('person_timeout').value
        self.person_margin = gp('person_bearing_margin').value
        self.person_max_range = gp('person_max_range').value
        self.person_half_width = gp('person_half_width').value

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
        self.camera_tf = None
        self.cam_fx = 0.0
        self.cam_cx = 0.0
        self.person_boxes = []      # [(u_center, width), ...] 마지막 인식 결과
        self.person_t = None        # 마지막 인식 결과 수신 시각
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
        if self.use_person:
            # 사람 기능을 쓸 때만 불러온다 (로봇에 vision_msgs 가 없어도 기본 회피는 동작).
            from vision_msgs.msg import Detection2DArray
            self.create_subscription(Detection2DArray, gp('person_topic').value,
                                     self._person_cb, 10)
            self.create_subscription(CameraInfo, gp('camera_info_topic').value,
                                     self._camera_info_cb, qos_profile_sensor_data)
        self.create_subscription(String, 'patrol_status', self._status_cb, 10)
        self.create_timer(1.0 / gp('control_rate').value, self._control_tick)

        self.get_logger().info(
            f'obstacle_avoidance 시작 (patrol_gate={self.use_patrol_gate}, '
            f'ultrasonic={self.use_us}, person_detection={self.use_person})')

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

    def _person_cb(self, msg):
        boxes = []
        for det in msg.detections:
            score = max((r.hypothesis.score for r in det.results), default=1.0)
            if score >= self.person_min_score:
                boxes.append((det.bbox.center.position.x, det.bbox.size_x))
        self.person_boxes = boxes
        # 다른 PC 에서 오므로 영상 시각이 아니라 받은 시각으로 유효 시간을 잰다.
        self.person_t = self._now()

    def _camera_info_cb(self, msg):
        self.cam_fx = msg.k[0]
        self.cam_cx = msg.k[2]
        if msg.width:
            self.camera_width = msg.width

    def _person_points(self, points, t):
        """이번 scan 점 중 사람 bbox 방향에 있는 점. 인식 결과가 없거나 오래됐으면 빈 목록."""
        if (not self.use_person or not self.person_boxes or self.person_t is None
                or t - self.person_t > self.person_timeout):
            return []
        if self.camera_tf is None:
            self.camera_tf = self._lookup_tf(self.camera_frame)
            if self.camera_tf is None:
                return []
        fx, cx = camera_intrinsics(self.cam_fx, self.cam_cx, self.camera_width, self.camera_hfov)
        intervals = [bbox_bearing_interval(u, w, fx, cx, self.person_margin)
                     for u, w in self.person_boxes]
        return person_points(points, intervals, self.camera_tf, self.person_max_range)

    def _lookup_tf(self, frame):
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
            self.lidar_tf = self._lookup_tf(msg.header.frame_id)
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
            hist=polar_histogram(points, self.n_sectors, self.hist_range),
            person_front=corridor_clearance(self._person_points(points, t),
                                            self.person_half_width, self.front_x, True))
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
            if state not in (PASS, 'IDLE'):
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
            self._publish_state('IDLE')   # Nav2 명령 없음 (속도 발행 안 함)
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
        per = Perception(front=front, rear=per.rear, ttc=per.ttc, hist=per.hist,
                         person_front=per.person_front)

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
