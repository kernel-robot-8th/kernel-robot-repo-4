"""비동기 Nav2 액션과 타이머를 단일 executor에서 처리하는 Pinky 실행 노드."""

import json
import math
import os
import time

from cobot_zone_traffic_control.zone_gate_client import ZoneGateClient
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from pinky_interfaces.srv import SetLed
import rclpy
from rclpy.action import ActionClient
from rclpy.exceptions import InvalidParameterTypeException, ParameterUninitializedException
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String

from .async_navigation import AsyncNavigation
from .patrol_controller import PatrolController
from .patrol_points_utils import (optional_general_names, parse_points, parse_zone_names,
                                  parse_zone_points, PointsConfigError, required_names,
                                  validate_points, validate_zones)


class PinkyPatrolNode(Node):
    """입출력만 담당한다. 작업 정책은 PatrolController가 소유한다."""

    def __init__(self, default_robot_id='pinky1'):
        super().__init__('pinky_patrol_node')
        defaults = {
            'robot_id': default_robot_id, 'idle_return_sec': 120.0,
            'tick_sec': 0.05, 'nav_retries': 3, 'nav_ready_timeout_sec': 60.0,
            'lifecycle_nodes': ['amcl', 'bt_navigator'], 'lifecycle_poll_sec': 0.5,
            'lifecycle_response_timeout_sec': 2.0,
            'pose_file': '~/.pinky_last_pose.json', 'restore_pose': True,
            'initialpose_timeout_sec': 5.0, 'initialpose_settle_sec': 0.5,
            'initial_rotation_sec': 4.0, 'initial_rotation_speed': 0.5,
            'led_blink_sec': 1.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        self.config = {name: self.get_parameter(name).value for name in defaults}
        positive = ('tick_sec', 'nav_retries', 'nav_ready_timeout_sec',
                    'lifecycle_poll_sec', 'lifecycle_response_timeout_sec',
                    'initialpose_timeout_sec', 'led_blink_sec')
        if any(not math.isfinite(self.config[key]) or self.config[key] <= 0
               for key in positive):
            raise ValueError('주기·타임아웃·재시도 횟수는 양수여야 합니다')
        if self.config['initial_rotation_sec'] < 0 or self.config['initialpose_settle_sec'] < 0:
            raise ValueError('초기화 시간은 0 이상이어야 합니다')
        self.robot_id = self.config['robot_id']
        self.points, self.home_name, self.zone_names, self.zone_points = self._load_points()
        self.pose_file = os.path.expanduser(self.config['pose_file'])
        self.status_pub = self.create_publisher(String, 'patrol_status', 10)
        self.command_sub = self.create_subscription(String, 'patrol_cmd', self._cmd_cb, 10)
        self.initial_pub = self.create_publisher(PoseWithCovarianceStamped, 'initialpose', 10)
        self.velocity_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.pose_sub = self.create_subscription(
            PoseWithCovarianceStamped, 'amcl_pose', self._pose_cb, 10)
        self._current_pose = None
        self._lifecycle = {name: self.create_client(GetState, name + '/get_state')
                           for name in self.config['lifecycle_nodes']}
        self._states = {name: False for name in self._lifecycle}
        self._state_futures = {}
        self._state_sent = {}
        self._next_poll = 0.0
        self.action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.navigation = AsyncNavigation(self.action_client, self._make_goal, self._feedback)
        self.gate = ZoneGateClient(self, self.robot_id, clock=time.monotonic)
        self._pose_initialized = not self.config['restore_pose']
        self._restore_stage = 'WAIT_NAV'
        self._prepare_requested = False
        self._saved_pose = self._load_pose()
        self.led_cli = self._create_led_client()
        self._led_future = None
        self._led_sent = None
        self._led_color = (0, 255, 0)
        self._led_blink = True
        self._led_on = True
        self._next_blink = 0.0
        self.controller = PatrolController(
            self.points, self.home_name, self.zone_points, self.navigation, self.gate,
            self._emit, self._prepare, self._ready, self._abort_preparation,
            idle_return_sec=self.config['idle_return_sec'], retries=self.config['nav_retries'],
            ready_timeout_sec=self.config['nav_ready_timeout_sec'])
        self.timer = self.create_timer(self.config['tick_sec'], self._tick)
        self._emit({'state': 'IDLE', 'waypoint': -1, 'detail': '', 'time': time.time()})

    def _load_points(self):
        """
        config/pinkyN.yaml 의 구역·좌표 설정을 읽어 검증한다.

        (zone_names, zone_points.<구역>, points.*, home_name)

        왜 declare 를 여기서 하나: rclpy 는 선언한 이름만 읽을 수 있고, 기본값 없는 선언
        (Type 만 지정)은 YAML 에 값이 없을 때 ParameterUninitializedException 을 낸다.
        이를 "누락"으로 모아 한 번에 알려 주려고 선언·읽기·검증을 한 메서드에 둔다.
        (YAML 없이 ros2 run 만 하면 전부 누락 -> 시작 거부. 조용히 기본 좌표로 움직이지 않는다.)
        구역이 몇 개이고 이름이 무엇인지는 YAML(zone_names)이 정하므로, 필요한 지점 이름
        (Z<구역>_EXIT)은 zone_names 를 읽은 뒤에 결정해 선언한다.

        :return: (points, home_name, zone_names, zone_points)
                 points 는 {이름: (x, y) 또는 (x, y, yaw)} (m, rad), zone_points 는 {구역: (지점 이름, ...)}
        :raises PointsConfigError: 누락 / 길이·숫자 오류 / NaN·inf / 타입 불일치(정수 배열 등) / 구역 소속 모순
        """
        try:
            self.declare_parameter('zone_names', Parameter.Type.STRING_ARRAY)
            self.declare_parameter('home_name', Parameter.Type.STRING)
            zone_names_raw = self.get_parameter('zone_names').value
        except InvalidParameterTypeException as e:
            raise PointsConfigError(f'zone_names 타입 오류: {e}. 문자열 리스트(예: [A, B])로 쓰세요.') from e
        except ParameterUninitializedException:
            raise PointsConfigError(
                'zone_names 가 없습니다. config/pinkyN.yaml 에 zone_names: [A, B] 처럼 구역 이름을 쓰세요 '
                '(YAML 을 지정했는지도 확인: launch 또는 --params-file).') from None
        zone_names = parse_zone_names(zone_names_raw)

        # 구역 지점(Z<구역>)과 홈(I<n>)의 이름도 YAML 이 정하므로, 이름을 먼저 읽은 뒤 좌표를 선언한다
        try:
            for zone in zone_names:
                self.declare_parameter(f'zone_points.{zone}', Parameter.Type.STRING_ARRAY)
        except InvalidParameterTypeException as e:
            raise PointsConfigError(f'zone_points 타입 오류: {e}. 지점 이름 문자열 리스트로 쓰세요.') from e
        raw_zone_points = {}
        for zone in zone_names:
            try:
                raw_zone_points[zone] = list(self.get_parameter(f'zone_points.{zone}').value)
            except ParameterUninitializedException:
                raise PointsConfigError(
                    f'zone_points.{zone} 가 없습니다. 구역 {zone} 에 속한 지점 이름을 '
                    f'zone_points: {zone}: [ZA, ZB] 처럼 쓰세요.') from None
        try:
            home_name = self.get_parameter('home_name').value
        except ParameterUninitializedException:
            home_name = ''

        required = required_names(zone_names)
        for members in raw_zone_points.values():
            required += [n for n in members if isinstance(n, str) and n and n not in required]
        if home_name and home_name not in required:
            required.append(home_name)

        try:
            for name in required + optional_general_names():
                self.declare_parameter(f'points.{name}', Parameter.Type.DOUBLE_ARRAY)
        except InvalidParameterTypeException as e:
            # 대표 사례: YAML 에 [0, 0] 처럼 정수로 쓴 경우 (소수점 [0.0, 0.0] 으로 써야 함)
            raise PointsConfigError(f'좌표 파라미터 타입 오류: {e}. 값을 소수점(0.0)으로 쓰세요.') from e
        raw = {}
        for name in required:
            try:
                raw[name] = self.get_parameter(f'points.{name}').value
            except ParameterUninitializedException:
                pass   # 누락은 validate_points 가 이름을 모아 한꺼번에 보고한다
        for name in optional_general_names():      # P3~P50: 값이 있는 것만 사용 (없으면 goto 불가)
            try:
                raw[name] = self.get_parameter(f'points.{name}').value
            except ParameterUninitializedException:
                pass

        points = parse_points(raw)
        validate_points(points, required, home_name)
        zone_points = parse_zone_points(raw_zone_points)
        validate_zones(zone_points, points, home_name)
        return points, home_name, zone_names, zone_points

    def _create_led_client(self):
        """로봇 드라이버와 테스트 대체 경계를 분리한다."""
        return self.create_client(SetLed, 'set_led')

    def _cmd_cb(self, message):
        """명령을 검증·등록하고 즉시 반환한다."""
        raw, command_id = message.data, None
        try:
            if raw.lstrip().startswith('{'):
                envelope = json.loads(raw)
                command_id, raw = envelope['command_id'], envelope['command']
                if not isinstance(command_id, str) or not command_id or not isinstance(raw, str):
                    raise ValueError('명령 봉투 형식 오류')
            self.controller.submit(raw, command_id)
        except (ValueError, KeyError, TypeError) as error:
            self.get_logger().warning(f'잘못된 명령: {error}')

    def _emit(self, payload):
        """상태 발행과 LED 표시를 같은 executor에서 갱신한다."""
        self.status_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        if (payload.get('command_id') and self.controller.busy
                and payload['command_id'] != self.controller.command_id):
            return
        if payload.get('task_finished'):
            self._save_pose()
        state = payload['state']
        if state in ('MOVING', 'RETURNING', 'LEAVING_ZONE', 'RETREATING'):
            self._set_led((0, 255, 0), False)
        elif state == 'QUEUEING':
            self._set_led((255, 0, 0), True)
        elif state in ('ARRIVED', 'HOLDING_ZONE'):
            self._set_led((255, 255, 0), True)
        elif state in ('IDLE', 'DONE', 'STOPPED', 'FAILED'):
            self._set_led((0, 255, 0), True)

    def _set_led(self, color, blink):
        self._led_color, self._led_blink = color, blink
        self._led_on, self._next_blink = True, time.monotonic() + self.config['led_blink_sec']

    def _tick(self):
        """라이프사이클·초기화·업무·LED를 짧게 진행한다."""
        now = time.monotonic()
        if self.controller.busy:
            self._poll_lifecycle(now)
            self._advance_preparation(now)
        self.controller.tick()
        self._advance_led(now)

    def _poll_lifecycle(self, now):
        if now < self._next_poll:
            return
        self._next_poll = now + self.config['lifecycle_poll_sec']
        for name, client in self._lifecycle.items():
            previous = self._state_futures.get(name)
            if previous is not None and not previous.done():
                if now - self._state_sent[name] < self.config['lifecycle_response_timeout_sec']:
                    continue
                del self._state_futures[name]
                previous.cancel()
            if not client.service_is_ready():
                self._states[name] = False
                continue
            self._states[name] = False
            future = client.call_async(GetState.Request())
            self._state_futures[name] = future
            self._state_sent[name] = now
            future.add_done_callback(lambda done, name=name: self._state_received(name, done))

    def _state_received(self, name, future):
        if self._state_futures.get(name) is not future:
            return
        try:
            self._states[name] = future.result().current_state.id == 3
        except Exception as error:
            self._states[name] = False
            self.get_logger().warning(f'{name} 상태 조회 실패: {error}')

    def _prepare(self):
        self._prepare_requested = True
        self._restore_stage = 'WAIT_NAV'
        self._restore_deadline = None

    def _ready(self):
        return (self._prepare_requested and self._pose_initialized
                and all(self._states.values()) and self.action_client.server_is_ready())

    def _advance_preparation(self, now):
        if not self._prepare_requested or self._pose_initialized:
            return
        if self._restore_stage == 'WAIT_NAV':
            if not all(self._states.values()) or not self.action_client.server_is_ready():
                return
            if self._saved_pose is None:
                self._pose_initialized = True
                return
            self._restore_stage = 'WAIT_POSE_SUBSCRIBER'
            self._restore_deadline = now + self.config['initialpose_timeout_sec']
        if self._restore_stage == 'WAIT_POSE_SUBSCRIBER':
            if self.initial_pub.get_subscription_count() == 0:
                if now >= self._restore_deadline:
                    self._abort_preparation()
                    self.controller.preparation_failed('initialpose 구독자 없음')
                return
            message = PoseWithCovarianceStamped()
            message.header.frame_id = 'map'
            message.header.stamp = self.get_clock().now().to_msg()
            message.pose.pose = self._pose_message(self._saved_pose).pose
            message.pose.covariance[0] = message.pose.covariance[7] = 0.25
            message.pose.covariance[35] = 0.3
            self.initial_pub.publish(message)
            self._restore_stage = 'SETTLING'
            self._restore_deadline = now + self.config['initialpose_settle_sec']
        elif self._restore_stage == 'SETTLING' and now >= self._restore_deadline:
            self._restore_stage = 'ROTATING'
            self._restore_deadline = now + self.config['initial_rotation_sec']
        elif self._restore_stage == 'ROTATING':
            if now >= self._restore_deadline:
                self.velocity_pub.publish(Twist())
                self._pose_initialized = True
                self._restore_stage = 'DONE'
            else:
                message = Twist()
                message.angular.z = self.config['initial_rotation_speed']
                self.velocity_pub.publish(message)

    def _abort_preparation(self):
        if self._restore_stage == 'ROTATING':
            self.velocity_pub.publish(Twist())
        self._prepare_requested = False
        self._restore_stage = 'WAIT_NAV'

    def _pose_message(self, pose):
        message = PoseStamped()
        message.header.frame_id = 'map'
        message.header.stamp = self.get_clock().now().to_msg()
        message.pose.position.x, message.pose.position.y = float(pose[0]), float(pose[1])
        yaw = pose[2] if len(pose) > 2 else 0.0
        message.pose.orientation.z = math.sin(yaw / 2)
        message.pose.orientation.w = math.cos(yaw / 2)
        return message

    def _make_goal(self, pose):
        goal = NavigateToPose.Goal()
        goal.pose = self._pose_message(pose)
        return goal

    def _feedback(self, message):
        self._update_pose(message.feedback.current_pose.pose)

    def _pose_cb(self, message):
        self._update_pose(message.pose.pose)

    def _update_pose(self, pose):
        q = pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y ** 2 + q.z ** 2))
        self._current_pose = (pose.position.x, pose.position.y, yaw)

    def _load_pose(self):
        try:
            with open(self.pose_file, encoding='utf-8') as stream:
                value = json.load(stream)
            pose = (value['x'], value['y'], value['yaw'])
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pose):
                raise ValueError('유한한 숫자 좌표가 필요합니다')
            return pose
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.get_logger().warning(f'저장 위치 복원 생략: {error}')
            return None

    def _advance_led(self, now):
        if self._led_blink and now >= self._next_blink:
            self._led_on = not self._led_on
            self._next_blink = now + self.config['led_blink_sec']
        desired = ('fill', *self._led_color) if self._led_on else ('clear', 0, 0, 0)
        if self._led_future is not None or desired == self._led_sent:
            return
        if not self.led_cli.service_is_ready():
            return
        request = SetLed.Request()
        request.command, request.r, request.g, request.b = desired
        self._led_sent = desired
        self._led_future = self.led_cli.call_async(request)
        self._led_future.add_done_callback(self._led_done)

    def _led_done(self, future):
        self._led_future = None
        try:
            future.result()
        except Exception as error:
            self._led_sent = None
            self.get_logger().warning(f'LED 응답 실패: {error}')

    def _save_pose(self):
        if self._current_pose is None:
            return
        try:
            x, y, yaw = self._current_pose
            with open(self.pose_file, 'w', encoding='utf-8') as stream:
                json.dump({'x': x, 'y': y, 'yaw': yaw}, stream)
        except OSError as error:
            self.get_logger().warning(f'위치 저장 실패: {error}')

    def close(self):
        """종료 시 비동기 취소·회전 정지를 요청한다. 물리 정지 확인을 대신하지 않는다."""
        self.navigation.cancel()
        self._abort_preparation()
        self.velocity_pub.publish(Twist())
        self._set_led((0, 0, 0), False)
        self._advance_led(time.monotonic())
        self._save_pose()


def main(args=None, node_class=PinkyPatrolNode):
    """ROS 콜백과 타이머를 단일 executor에서 처리한다."""
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = node_class()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
