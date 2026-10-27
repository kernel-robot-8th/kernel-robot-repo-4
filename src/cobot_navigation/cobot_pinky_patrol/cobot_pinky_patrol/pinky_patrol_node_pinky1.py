"""
Pinky 순찰 노드

[v3 변경점] 위험구역 진입을 "대기열 슬롯" 방식으로 처리 (zone_manager_node / zone_gate_client)
  - 진입 요청을 먼저 보내고, 점유 중이면 매니저가 알려 준 슬롯에서 줄 서서 대기 (상태 QUEUEING)
  - goto 경로와 start 경로가 같은 _queue_and_enter 를 사용
  - 로봇 코드에는 대기 좌표가 없고 구역별 진입 앵커(W<구역>)와 반납 출구(Z<구역>_EXIT)만 유지

[v1.2 변경점] 위험구역 2개 지원 (구역마다 토큰·대기열이 따로, zone_names / zone_points 파라미터)
  - 구역 A 에 있는 동안 구역 B 는 막히지 않고, 같은 구역에서만 한 대씩 진입
  - 구역이 바뀌는 경로는 이전 구역 EXIT 에서 토큰을 반납한 뒤 다음 구역 ENTRY 에서 요청

[지원 명령]  (토픽: patrol_cmd)
  start                : (v1.1.0 비활성) 받으면 FAILED(detail=start disabled) 응답. 순회 코드는 주석으로 보관
  goto:<P>[,<P>,...]   : 구역 밖 지점들을 순서대로 방문. 도착 후 홈으로 가지 않고 대기한다
                         예) goto:P1          (1개 지점)
                             goto:P1,P2       (여러 지점 경로)
                         구역 토큰을 쥐고 있으면 먼저 그 구역 EXIT 에서 반납한 뒤 출발
  zone:<P>             : 구역 지점 1개로 이동 (토큰 발급 -> 이동 -> 도착 후 토큰 유지). 예) zone:ZA
  leave                : 보유 중인 구역의 EXIT 로 이동해 도착한 뒤 토큰 반납
  stop                 : 현재 작업 즉시 중단 (구역 안이면 EXIT 로 나와 반납)
  emergency_stop       : 그 자리 정지 + 토큰 유지 (max_hold_sec 뒤 매니저가 해제)
  [유휴 복귀] 마지막 명령을 마친 뒤 idle_return_sec(기본 120초, 파라미터) 동안 새 명령이 없으면
              (구역 안이면 EXIT 반납 후) 홈으로 복귀한다. 0 이하이면 자동 복귀를 끈다.

[상태 발행]  (토픽: patrol_status, JSON)
  IDLE / STARTING / MOVING / QUEUEING / WAITING_ZONE / ARRIVED /
  LEAVING_ZONE / RETURNING / DONE / HOLDING_ZONE(detail=구역) / IDLE_WAIT(detail=남은 초) /
  STOPPED / FAILED / RETRY
  (goto 경로 중에는 waypoint = 경로 안에서의 순번, detail = 지점 이름)

[파일 구성]
  1. IMPORT
  2. 경로 상수 (좌표는 config/pinky1.yaml 파라미터, WAYPOINTS 는 v1.1.0 비활성·주석 보관)
  3. 위험 구역(ZONE) 상수
  4. goto 상수
  5. LED 상수
  6. 초기화 (__init__)
  7. LED 제어
  8. 통신 (상태 발행 / 명령 수신)
  9. 좌표 변환 / 위치 저장 / 초기 위치 보정
  10. 주행 (Nav2 이동 헬퍼)
  11. 위험 구역 (zone mutex + 대기열 헬퍼)
  12. 작업: goto / zone / leave / 유휴 복귀
  13. 작업: 전체 순찰 (v1.1.0 비활성, 주석 보관)
  14. main
"""

# ==============================================================================
# 1. IMPORT
# ==============================================================================
import rclpy
from rclpy.signals import SignalHandlerOptions
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.exceptions import InvalidParameterTypeException, ParameterUninitializedException
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from std_msgs.msg import String
from pinky_interfaces.srv import SetLed
import json, math, os, time, threading, subprocess

# 같은 패키지의 좌표 파싱·검증 (ROS 비의존)
from cobot_pinky_patrol.patrol_points_utils import (PointsConfigError, entry_name, exit_name,
                                                    general_names, optional_general_names, parse_command, parse_points, parse_zone_names,
                                                    parse_zone_points, required_names,
                                                    validate_points, validate_zones, zone_of)

# cobot_zone_traffic_control 패키지가 설치되어 있어야 합니다.
from cobot_zone_traffic_control.zone_gate_client import (ZoneGateClient,
                                                         choose_entry_target)


class PinkyPatrolNode(Node):
    """
    [설계 핵심]
    - Nav2 액션은 전부 로컬(BasicNavigator)로 처리 -> 도메인 브릿지 불필요
    - 관제 PC와는 patrol_cmd(수신) / patrol_status(송신) String 토픽만 사용
    - 콜백은 즉시 리턴하고, 실제 작업은 별도 스레드에서 수행
    - waypoints는 로봇마다 다르므로 로봇별 파일에서 따로 관리
    """

    # ==========================================================================
    # 2. 좌표 / 경로 상수
    # ==========================================================================

    # 재시작해도 마지막 위치를 기억하기 위한 저장 파일 경로
    POSE_FILE = os.path.expanduser('~/.pinky_last_pose.json')

    # [v1.1.0 R3] 지점 좌표(POINTS)는 코드에서 제거하고 config/pinky1.yaml 의 points 파라미터로 옮겼다.
    #   - 형식: (x, y) 또는 (x, y, yaw[rad]), map 좌표계 [m]. 읽기/검증은 _load_points() 와 patrol_points_utils.py.
    #   - 코드에는 좌표가 아닌 "이름"만 남긴다. 좌표는 self.points[이름] 으로 쓴다.
    #   - 위험구역은 여러 개(zone_names, 예: A, B)이고 구역마다 ENTRY/EXIT 한 쌍을 가진다.
    #     이름 규칙은 patrol_points_utils.entry_name / exit_name (W<구역> / Z<구역>_EXIT).
    #   - W<구역> 는 zone_params.yaml 의 zone_<구역>.queue_anchor 와 같아야 한다 (테스트가 두 YAML 을 비교).
    #   - 옛 위험 구역 문(RED LINE) 좌표는 이미 미사용이라 이전하지 않았다 (git 이력 참고).

    # [비활성: v1.1.0 순회 중단]
    # 순회(start) 경로. v1.1.0 은 goto/stop 만 쓰므로 껐다.
    # 좌표가 클래스 상수가 아니라 인스턴스 속성(self.points)이 되었으므로 WAYPOINTS 는 좌표가 아닌
    # "지점 이름" 리스트로 둔다. 되살릴 때 아래 "# " 를 풀고, _run_patrol 에서 self.points[이름] 으로 변환한다.
    # # start 명령의 순찰 경로: P2 -> ZONE_ENTRY -> P3 -> P6 -> ZONE_EXIT -> P1
    # WAYPOINTS = [
        # "P2",       # 0: 중간 경유점
        # "ZONE_ENTRY",   # 1: 앵커 (도착 후 진입 허가 요청)
        # "P3",       # 2: 우측 아래 끝 (위험 구역 안)
        # "P6",       # 3: 우측 위 끝   (위험 구역 안)
        # "ZONE_EXIT",  # 4: 출구 (도착 시 락 반납)
        # "P1",       # 5: 시작점 복귀
    # ]

    # ==========================================================================
    # 3. 위험 구역(ZONE) 상수
    # ==========================================================================
    # [비활성: v1.1.0 순회 중단]
    # 순회(start) 전용 순번 상수. goto 경로는 이름(ZONE_ENTRY_NAME/ZONE_EXIT_NAME)을 쓰므로 영향 없음.
    # 되살릴 때: 아래 "# " 를 풀고 WAYPOINTS 와 순번이 맞는지 test_waypoint_indexes_match_door_names 로 확인.
    # # [순찰(start)용] WAYPOINTS 리스트의 "순번(index)"이며 좌표 값이 아닙니다.
    # #   ZONE_ENTRY_INDEX: 이 waypoint 도착 직후, 다음으로 출발하기 전에 진입 허가 요청
    # #   ZONE_EXIT_INDEX : 이 waypoint 도착 시 구역을 벗어난 것으로 보고 락 반납
    # ZONE_ENTRY_INDEX = 1   # WAYPOINTS[1] = ZONE_ENTRY
    # ZONE_EXIT_INDEX = 4    # WAYPOINTS[4] = ZONE_EXIT

    # [goto용] 위험구역의 이름과 소속 지점은 코드가 아니라 파라미터(zone_names, zone_points)로 받는다.
    #   self.zone_names : 구역 이름들 (예: ('A', 'B'))
    #   self.zone_points: {구역: 소속 지점 이름들}. 지점이 어느 구역인지는 zone_of(self.zone_points, 이름)
    #   구역별 진입(토큰 요청)/출구(토큰 반납) 지점은 entry_name(구역) / exit_name(구역). stop 후퇴도 그 구역의 출구로 간다.

    # ==========================================================================
    # 4. goto 상수
    # ==========================================================================
    # 복귀 지점 이름은 파라미터 home_name (config/pinky1.yaml, self.home_name)
    NAV_RETRIES = 3                                   # 진입 절차 중 한 목표에 대한 이동 최대 시도 횟수
    # goto 허용 지점 = YAML 에 좌표가 있는 일반 지점(P1~P10) + 자기 홈(I<n>). 구역 지점(Z*)은 zone 명령 전용, W*/Z*_EXIT 는 직접 이동 금지
    IDLE_TICK_SEC = 1.0                               # 유휴 복귀 타이머 확인 주기(초). 복귀까지의 시간은 파라미터 idle_return_sec

    # ==========================================================================
    # 5. LED 상수
    # ==========================================================================
    # 대기(IDLE): 초록 깜박임 / 주행: 초록 고정 점등(깜박임 없음)
    IDLE_BLINK_PERIOD = 1.0

    # ==========================================================================
    # 6. 초기화
    # ==========================================================================
    def __init__(self):
        super().__init__('pinky_patrol_node')

        # 실행 시 --ros-args -p robot_id:=pinky1
        # zone_manager_node의 robot_ids 파라미터 값과 정확히 같아야 함
        self.declare_parameter('robot_id', 'pinky1')
        self.robot_id = self.get_parameter('robot_id').value

        # --- 지점 좌표 / 홈 이름 (config/pinkyN.yaml, launch 또는 --params-file 로 전달) ---
        # 좌표를 코드에 두지 않는 이유: 맵이 바뀌면 코드 수정·재배포 없이 YAML 만 고치기 위해서이고,
        # 로봇 3대 코드의 유일한 차이(좌표·홈)를 설정으로 옮기기 위해서이다.
        # 잘못되면 로그를 남기고 예외를 올려 노드를 시작하지 않는다 (잘못된 좌표로 주행하는 것보다 안전).
        try:
            self.points, self.home_name, self.zone_names, self.zone_points = self._load_points()
        except PointsConfigError as e:
            self.get_logger().error(f'좌표 설정 오류 -- 노드를 시작하지 않습니다: {e}')
            raise
        # 구역 소속 지점은 zone 명령으로만 가고, goto 는 그 밖의 허용 지점만 받는다
        self.zone_allowed = {p for ms in self.zone_points.values() for p in ms}
        self.goto_allowed = (set(general_names(self.points)) | {self.home_name}) - self.zone_allowed

        # 유휴 복귀: 마지막 명령을 마친 뒤 이 시간 동안 새 명령이 없으면 홈으로 돌아간다 (0 이하 = 끔)
        self.declare_parameter('idle_return_sec', 120.0)
        self.idle_return_sec = float(self.get_parameter('idle_return_sec').value)

        # Nav2 액션 클라이언트 + 퍼블리셔 생성 헬퍼 역할 겸용
        self.navigator = BasicNavigator()

        # 위험 구역 허가 클라이언트 (navigator를 넘겨 executor 충돌 방지)
        self.gate = ZoneGateClient(self.navigator, robot_id=self.robot_id)

        # 통신: 상태 송신 / 명령 수신
        self.status_pub = self.create_publisher(String, 'patrol_status', 10)
        self.create_subscription(String, 'patrol_cmd', self._cmd_cb, 10)

        # 스레드 간 공유 상태
        self._running = False         # 작업(순찰/goto) 수행 중 여부
        self._stop_requested = False  # stop / emergency_stop 명령 수신 여부
        self._emergency_requested = False  # emergency_stop 수신 여부 (True 면 후퇴/락 반납 없이 현재 동작 유지)
        self._thread = None           # 작업 스레드 핸들
        self._pose_initialized = False  # 초기 위치 보정을 이미 했는지 (노드 실행 후 1회만)
        self._held_zone = None        # 토큰을 보유 중인 구역 이름 (None = 구역 밖). 명령 사이에도 유지된다
        self._idle_deadline = None    # 이 시각(time.monotonic)이 지나면 홈 복귀 (None = 타이머 없음)
        self._last_point = None       # 마지막으로 도착한 지점 이름 (홈에 있는지 판단용)
        self.create_timer(self.IDLE_TICK_SEC, self._idle_tick)

        # LED
        self._led_proc = None         # 직접 띄운 led_server 프로세스
        self._blink_stop = None       # 깜박임 중단용 Event
        self._blink_thread = None
        self.led_cli = self.create_client(SetLed, 'set_led')
        self.set_idle_led()           # 시작 시 대기 LED

        self.publish_status('IDLE', -1)

    def _load_points(self):
        """
        config/pinkyN.yaml 의 구역·좌표 설정을 읽어 검증한다.
        (zone_names, zone_points.<구역>, points.*, home_name)

        왜 declare 를 여기서 하나: rclpy 는 선언한 이름만 읽을 수 있고, 기본값 없는 선언
        (Type 만 지정)은 YAML 에 값이 없을 때 ParameterUninitializedException 을 낸다.
        이를 "누락"으로 모아 한 번에 알려 주려고 선언·읽기·검증을 한 메서드에 둔다.
        (YAML 없이 ros2 run 만 하면 전부 누락 -> 시작 거부. 조용히 기본 좌표로 움직이지 않는다.)
        구역이 몇 개이고 이름이 무엇인지는 YAML(zone_names)이 정하므로, 필요한 지점 이름
        (W<구역> / Z<구역>_EXIT)은 zone_names 를 읽은 뒤에 결정해 선언한다.

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
        for name in optional_general_names():      # P3~P10: 값이 있는 것만 사용 (없으면 goto 불가)
            try:
                raw[name] = self.get_parameter(f'points.{name}').value
            except ParameterUninitializedException:
                pass

        points = parse_points(raw)
        validate_points(points, required, home_name)
        zone_points = parse_zone_points(raw_zone_points)
        validate_zones(zone_points, points, home_name)
        return points, home_name, zone_names, zone_points

    # ==========================================================================
    # 7. LED 제어
    # ==========================================================================
    # LED 상태표
    #   명령 대기       : 초록 깜박임        set_idle_led()
    #   주행 중         : 초록 고정 점등     set_drive_led()
    #   허가 대기       : 빨강 깜박임        start_blink(255, 0, 0)
    #   도착 후 대기    : 노랑 깜박임        start_blink(255, 255, 0)
    # 색을 바꿀 때는 start_blink()가 이전 깜박임을 먼저 멈추므로 별도 stop 불필요.

    def set_led(self, command, r=0, g=0, b=0):
        """LED 서비스 호출. led_server가 없으면 직접 실행 (실패해도 작업은 계속)."""
        if not self.led_cli.wait_for_service(timeout_sec=1.0):
            if self._led_proc is None:
                self.get_logger().info('led_server 자동 실행')
                # 깜박임마다 찍히는 INFO 로그("Filled/Cleared all LEDs")를 숨기기 위해
                # led_server 로그 레벨을 WARN으로 올려서 실행 (경고/에러만 출력)
                # start_new_session=True: 별도 세션으로 실행해 터미널 Ctrl+C(SIGINT)가
                # led_server에 직접 전달되지 않게 함 (종료는 main()의 finally에서 처리)
                self._led_proc = subprocess.Popen(
                    ['ros2', 'run', 'pinky_led', 'led_server',
                     '--ros-args', '--log-level', 'warn'],
                    start_new_session=True)    # ros2 run pinky_led led_server --ros-args --log-level warn 을 실행 시킨 결과와 같다
            if not self.led_cli.wait_for_service(timeout_sec=10.0):
                self.get_logger().warn('/set_led 서비스 없음 - LED 설정 생략')
                return
        req = SetLed.Request()
        req.command, req.r, req.g, req.b = command, r, g, b
        self.led_cli.call_async(req)

    def start_blink(self, r, g, b, period=1.0):
        """별도 스레드에서 (r,g,b) <-> 소등 반복. 이전 깜박임은 자동 중단."""
        self.stop_blink()
        stop = threading.Event()

        def loop():
            on = True
            while not stop.is_set():
                if on:
                    self.set_led('fill', r, g, b)   # 켜짐
                else:
                    self.set_led('clear')           # 꺼짐
                on = not on
                stop.wait(period)

        self._blink_stop = stop
        self._blink_thread = threading.Thread(target=loop, daemon=True)
        self._blink_thread.start()

    def stop_blink(self):
        """깜박임 스레드 정지."""
        if self._blink_stop is not None:
            self._blink_stop.set()
            self._blink_thread.join(timeout=3.0)
            self._blink_stop = None
            self._blink_thread = None

    def set_idle_led(self):
        """명령 대기: 초록 느린 깜박임."""
        self.start_blink(0, 255, 0, period=self.IDLE_BLINK_PERIOD)

    def set_drive_led(self):
        """주행 중: 초록 고정 점등. 깜박임 스레드를 먼저 멈춰야 덮어써지지 않음."""
        self.stop_blink()
        self.set_led('fill', 0, 255, 0)

    def clear_led(self):
        """노드 종료 시 LED 끄기 (서비스 응답까지 잠깐 spin)."""
        self.stop_blink()
        if not self.led_cli.service_is_ready():
            return
        req = SetLed.Request()
        req.command = 'clear'
        future = self.led_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)

    # ==========================================================================
    # 8. 통신 (상태 발행 / 명령 수신)
    # ==========================================================================
    def publish_status(self, state, wp_index, detail=''):
        """상태를 JSON 문자열로 직렬화해 patrol_status로 발행."""
        payload = json.dumps({'state': state, 'waypoint': wp_index,
                              'detail': detail, 'time': time.time()})
        self.status_pub.publish(String(data=payload))

    def _cmd_cb(self, msg):
        """
        명령 수신 콜백. 오래 걸리는 작업은 하지 않고 스레드에 위임한 뒤 즉시 리턴.
        (콜백이 막히면 stop 명령을 받을 수 없음)
        """
        kind, names = parse_command(msg.data)   # 형식만 해석. 지점/구역 검증은 아래에서

        # --- start: 비활성 (v1.1.0) ---
        # 순회를 껐으므로 '알 수 없는 명령' 경고로 떨어뜨리지 않고, 관제 쪽이 왜 안 움직이는지
        # 알 수 있게 FAILED 상태로 응답한다. 작업 스레드는 시작하지 않아 노드는 IDLE 을 유지한다.
        if kind == 'start':
            self.get_logger().warn('순회 비활성화(v1.1.0): start 명령을 무시합니다.')
            self.publish_status('FAILED', -1, 'start disabled')

        # [비활성: v1.1.0 순회 중단] 원래 start 분기 (되살릴 때 위 if 블록을 지우고 아래 주석을 푼다)
        # if cmd == 'start':
            # if self._running:
                # self.get_logger().warn('이미 순찰 중입니다. 명령 무시.')
                # return
            # self._stop_requested = False
            # self._emergency_requested = False
            # self._running = True   # 스레드 시작 전에 세팅 (연타 시 중복 실행 방지)
            # self._thread = threading.Thread(target=self._run_patrol, daemon=True)
            # self._thread.start()

        # --- goto:<P>[,<P>,...] / zone:<P> / leave: 지점 단위 독립 이동 (끝나도 홈으로 가지 않음) ---
        #   goto : 구역 밖 지점만. 구역 지점은 zone 으로 보내야 한다 (토큰 절차가 다르기 때문)
        #   zone : 구역 지점 1개. 토큰 발급 -> 이동 -> 도착 후 토큰 유지
        #   leave: 보유 중인 구역 EXIT 로 이동 -> 토큰 반납
        elif kind in ('goto', 'zone', 'leave'):
            if kind == 'leave':
                if self._running:
                    self.get_logger().warn('작업 중입니다. 명령 무시.')
                    return
                if self._held_zone is None:
                    self.get_logger().warn('보유 중인 구역이 없어 leave 를 무시합니다.')
                    self.publish_status('FAILED', -1, 'no zone held')
                    return
                self._start_task(self._run_leave)
                return

            if not names:
                self.get_logger().warn(f'{kind} 포인트가 비어 있습니다.')
                self.publish_status('FAILED', -1, 'no point given')
                return
            unknown = [n for n in names if n not in self.points]
            if unknown:
                self.get_logger().warn(f'알 수 없는 포인트: {unknown}')
                self.publish_status('FAILED', -1, f'unknown point: {unknown}')
                return
            if kind == 'goto':
                in_zone = [n for n in names if n in self.zone_allowed]
                if in_zone:
                    self.get_logger().warn(f'구역 지점은 zone 명령으로 보내세요: {in_zone}')
                    self.publish_status('FAILED', -1, f'use zone: {in_zone}')
                    return
                denied = [n for n in names if n not in self.goto_allowed]
                if denied:
                    self.get_logger().warn(f'goto 불가 포인트: {denied}')
                    self.publish_status('FAILED', -1, f'not allowed: {denied}')
                    return
            elif len(names) != 1 or names[0] not in self.zone_allowed:
                self.get_logger().warn(f'zone 은 구역 지점 1개만 가능합니다: {list(names)}')
                self.publish_status('FAILED', -1, f'zone needs one zone point: {list(names)}')
                return
            if self._running:
                self.get_logger().warn('작업 중입니다. 명령 무시.')
                return

            if kind == 'goto':
                self._start_task(self._run_goto, list(names))
            else:
                self._start_task(self._run_zone, names[0])

        # --- stop / emergency_stop: 현재 작업 중단 ---
        #   stop           : 멈춘 뒤, 구역 안에서 락을 들고 있으면 그 구역의 EXIT 로 나와 락을 반납한다
        #   emergency_stop : 그 자리 정지 + 락 유지 (락은 zone_manager 의 max_hold_sec 뒤에 자동 해제)
        elif kind in ('stop', 'emergency_stop'):
            if not self._running:
                self.get_logger().warn('순찰 중이 아닙니다. 명령 무시.')
                return
            # 콜백(executor 스레드)에서 navigator.cancelTask() 를 부르면 작업 스레드가 같은 executor 를 spin 중이라
            # 'Executor is already spinning' 으로 노드가 죽는다. 플래그만 세우고 취소는 작업 스레드가 한다
            # (_navigate / _queue_and_enter / 순찰 루프가 매 0.1초 _stop_requested 를 확인해 goal 을 취소함).
            if kind == 'emergency_stop':
                self._emergency_requested = True
            self._stop_requested = True

        else:
            self.get_logger().warn(f'알 수 없는 명령: {msg.data!r}')

    # ==========================================================================
    # 9. 좌표 변환 / 위치 저장 / 초기 위치 보정
    # ==========================================================================
    def quat_to_yaw(self, q):
        """쿼터니언 -> yaw(rad). atan2로 -pi~pi 전 구간을 정확히 복원."""
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny_cosp, cosy_cosp)

    def make_pose(self, x, y, yaw=0.0):
        """(x, y, yaw) -> PoseStamped. 2D 로봇이라 z축 회전만 사용."""
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.navigator.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def get_current_pose(self):
        """Nav2 feedback에서 현재 위치 추출. 이동 중이 아니면 None."""
        feedback = self.navigator.getFeedback()
        if feedback is None:
            return None
        cp = feedback.current_pose.pose
        return (cp.position.x, cp.position.y, self.quat_to_yaw(cp.orientation))

    def save_last_pose(self, x, y, yaw=0.0):
        """다음 실행 시 이어서 시작할 수 있도록 마지막 위치를 파일에 저장."""
        with open(self.POSE_FILE, 'w') as f:
            json.dump({'x': x, 'y': y, 'yaw': yaw}, f)

    def load_last_pose(self):
        """저장된 마지막 위치 로드. 없으면 None."""
        if os.path.exists(self.POSE_FILE):
            with open(self.POSE_FILE) as f:
                data = json.load(f)
                data.setdefault('yaw', 0.0)   # 구버전 파일 호환
                return data
        return None

    def publish_initial_pose(self, x, y, yaw):
        """
        AMCL 초기 위치 발행. 구독자가 붙을 때까지 대기해야 메시지 유실이 없음
        (initialpose는 1회성이라 유실되면 위치 추정이 틀어짐).
        """
        pub = self.navigator.create_publisher(PoseWithCovarianceStamped, 'initialpose', 10)
        deadline = time.time() + 5.0
        while pub.get_subscription_count() == 0 and time.time() < deadline:
            time.sleep(0.1)

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.navigator.get_clock().now().to_msg()
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        # covariance: 6x6 행렬을 1차원으로 편 배열. 대각 성분만 채움
        # 위치를 잘 못 잡으면 값을 키워볼 것 (x,y: 0.25 -> 0.5 / yaw: 0.3 -> 0.5~1.0)
        msg.pose.covariance[0] = 0.25    # x 분산
        msg.pose.covariance[7] = 0.25    # y 분산
        msg.pose.covariance[35] = 0.3    # yaw 분산 (6*5+5)
        pub.publish(msg)

    def spin_in_place(self, duration=12.6, angular_speed=0.5):
        """제자리 회전으로 AMCL 방향 보정. 위치를 잘 못 잡으면 duration을 늘려볼 것."""
        cmd_pub = self.navigator.create_publisher(Twist, 'cmd_vel', 10)
        deadline = time.time() + 5.0
        while cmd_pub.get_subscription_count() == 0 and time.time() < deadline:
            time.sleep(0.1)

        twist = Twist()
        twist.angular.z = angular_speed
        end_time = time.time() + duration
        while time.time() < end_time:
            cmd_pub.publish(twist)
            time.sleep(0.1)
        cmd_pub.publish(Twist())   # 정지 명령으로 마무리
        time.sleep(0.5)

    def _init_pose_once(self):
        """
        노드 실행 후 첫 작업(start/goto)에서만 초기 위치 보정을 수행.
        저장된 마지막 위치를 AMCL에 알려주고 제자리 회전으로 방향을 잡는다.
        이미 했거나 저장된 위치가 없으면 아무것도 하지 않음.
        """
        if self._pose_initialized:
            return
        self._pose_initialized = True   # 실패/없음이어도 다시 시도하지 않음

        last = self.load_last_pose()
        if last is None:
            self.get_logger().info('저장된 위치 없음 - 초기 위치 보정 생략')
            return
        self.publish_initial_pose(last['x'], last['y'], last['yaw'])
        self.get_logger().info('초기 방향 보정을 위해 제자리 회전을 시작합니다...')
        self.spin_in_place(duration=4.0, angular_speed=0.5)
        self.get_logger().info('초기 방향 보정 완료.')

    # ==========================================================================
    # 10. 주행 (Nav2 이동 헬퍼)
    # ==========================================================================
    def _navigate(self, wp, retries=3):
        """
        한 지점으로 이동. 성공 True / 실패·중단 False.
        이동 중에는 초록 고정 점등. 실패 시 retries회까지 재시도.
        """
        pose = self.make_pose(*wp)
        self.set_drive_led()
        for attempt in range(retries):
            self.navigator.goToPose(pose)
            # goToPose는 비동기이므로 완료될 때까지 폴링
            while not self.navigator.isTaskComplete():
                if self._stop_requested:
                    self.navigator.cancelTask()
                    break
                time.sleep(0.1)
            if self._stop_requested:
                return False

            result = self.navigator.getResult()

            # 마지막 위치 저장 (다음 노드 실행 시 초기 위치 보정에 사용)
            current = self.get_current_pose()
            if current is None and result == TaskResult.SUCCEEDED:
                current = (wp[0], wp[1], wp[2] if len(wp) > 2 else 0.0)
            if current is not None:
                self.save_last_pose(*current)

            if result == TaskResult.SUCCEEDED:
                return True
            self.get_logger().warn(f'이동 실패({result}), 재시도 {attempt+1}/{retries}')
        return False

    def _wait_interruptible(self, sec):
        """sec초 대기. 도중에 stop이 오면 즉시 False."""
        end = time.time() + sec
        while time.time() < end:
            if self._stop_requested:
                return False
            time.sleep(0.1)
        return True

    # ==========================================================================
    # 11. 위험 구역 (zone mutex 헬퍼)
    # ==========================================================================
    def _end_state(self):
        """이동이 끝난 이유: stop 요청이면 STOPPED, 아니면 FAILED."""
        return 'STOPPED' if self._stop_requested else 'FAILED'

    def _queue_and_enter(self, idx, name, zone):
        """
        위험 구역 ``zone`` 진입 절차 전체 (goto 경로와 start 경로가 함께 쓴다).
        요청을 "먼저" 보내고, 매니저 응답(허가 / 대기 슬롯)에 따라 목표를 계속 바꿔 가며 이동한다.

          1) request_entry(구역 ``zone`` 의 토큰) 발송 후 일단 그 구역 문(ENTRY)으로 출발 (빈 구역이면 v2처럼 곧바로 진행)
          2) 점유 중이라 슬롯(queue_slot)이 오면 -> 문 대신 그 슬롯 좌표로 이동하고 정지 (QUEUEING)
          3) 슬롯이 바뀌면(앞 로봇 이탈/취소) -> 현재 goal 취소 후 새 슬롯으로 재이동
          4) 허가(grant)가 오면 -> 진행 중인 goal 만 취소하고 즉시 반환 (슬롯/앵커를 거치지 않고 호출자가 목적지로 직행)
          5) 대기 중 재전송(1초)으로 매니저에게 "아직 기다린다"고 알린다 (끊기면 5초 뒤 큐에서 제거됨)
        로봇 코드에는 대기 좌표가 없다. 구역별 앵커 좌표(W<구역>)만 self.points 에 있고 슬롯은 항상 매니저가 준다.

        True  : 허가를 받음 (락 보유). 앵커에 도착하지 않았어도 반환
        False : stop / 이동 최종 실패 / 대기열 가득 (락 없음. 허가를 이미 받았다면 반납함)
        """
        door = self.points[entry_name(zone)]
        gate = self.gate
        gate.reset(zone)                        # 이후 요청/취소/이탈 통보는 이 구역 기준
        gate.send_request()                     # 슬롯 이동 "전에" 먼저 요청 (순번 확보)

        target = None       # 현재 목표 (kind, pose). kind: 'door' | 'slot'
        moving = False      # Nav2 goal 이 진행 중인가
        arrived = False     # 현재 목표에 도착했는가
        fails = 0           # 현재 목표의 연속 이동 실패 횟수
        phase = None        # 마지막으로 발행한 상태 (같은 상태를 반복 발행하지 않기 위함)

        while rclpy.ok():
            # --- stop: 진행 중인 goal 취소 + 매니저에 대기 포기/락 반납 ---
            if self._stop_requested:
                if moving:
                    self._cancel_goal()
                self._abort_entry(idx, name, 'STOPPED')
                return False

            # 허가 전에는 1초마다 같은 토큰으로 재전송 (stale 제거 방지)
            if not gate.granted():
                gate.resend_if_due()

            # --- 허가(토큰)를 받았으면 대기열/앵커로 가지 않는다: 진행 중인 goal 만 취소하고 바로 반환 ---
            #     (호출한 쪽이 곧바로 다음 목표(ZB 등)로 출발하므로 슬롯·앵커를 거치지 않고 직행)
            if gate.granted():
                if moving:
                    self._cancel_goal()
                self.stop_blink()
                self.set_drive_led()
                return True

            kind, pose = choose_entry_target(gate.granted(), gate.current_slot, door)
            if kind == 'full':
                self.get_logger().warn(f'[{self.robot_id}] 대기열이 가득 차서 진입을 포기합니다')
                if moving:
                    self._cancel_goal()
                self._abort_entry(idx, name, 'FAILED', 'queue_full')
                return False

            # --- 목표가 바뀌었으면 현재 goal 을 취소하고 새 목표로 출발 ---
            if (kind, pose) != target:
                if moving:
                    self._cancel_goal()
                target, arrived, fails = (kind, pose), False, 0
                self._start_goal(pose)
                moving = True
            # --- 이동 중: goal 완료 여부 확인 (isTaskComplete 가 navigator 를 spin 해서 콜백도 처리됨) ---
            elif moving:
                if self.navigator.isTaskComplete():
                    moving = False
                    if self._stop_requested:        # stop 으로 취소된 것이면 실패로 세지 않음
                        continue
                    result = self.navigator.getResult()
                    self._record_pose(pose, result)
                    if result == TaskResult.SUCCEEDED:
                        arrived = True
                    else:
                        fails += 1
                        self.get_logger().warn(
                            f'이동 실패({result}), 재시도 {fails}/{self.NAV_RETRIES}')
                        if fails >= self.NAV_RETRIES:
                            self._abort_entry(idx, name, 'FAILED', target[0])
                            return False
                        self._start_goal(pose)      # 같은 목표로 재시도
                        moving = True
            # --- 도착해서 대기 중: navigator 를 직접 spin 해야 grant/queue_slot 콜백이 처리됨 ---
            else:
                rclpy.spin_once(self.navigator, timeout_sec=0.1)

            # --- 상태 / LED (바뀔 때만) ---
            if kind == 'slot':
                new_phase = 'QUEUEING'
            elif arrived:
                new_phase = 'WAITING_ZONE'          # 문 앞인데 아직 허가가 없음
            else:
                new_phase = 'MOVING'
            if new_phase != phase:
                phase = new_phase
                if phase == 'MOVING':
                    self.set_drive_led()
                    self.publish_status('MOVING', idx, entry_name(zone))
                else:
                    self.start_blink(255, 0, 0)     # 대기: 빨강 깜박임
                    detail = f'slot{gate.current_slot[0]}' if kind == 'slot' else name
                    self.publish_status(phase, idx, detail)

        return False    # rclpy 종료

    def _start_goal(self, pose):
        """Nav2 에 pose(x, y, yaw) goal 을 보낸다 (비동기, 완료는 isTaskComplete 로 확인)."""
        self.navigator.goToPose(self.make_pose(*pose))

    def _cancel_goal(self):
        """진행 중인 goal 을 취소하고 취소가 반영될 때까지 잠깐 기다린다 (새 goal 과 겹침 방지)."""
        self.navigator.cancelTask()
        end = time.time() + 2.0
        while not self.navigator.isTaskComplete() and time.time() < end:
            pass    # isTaskComplete 가 0.1초씩 spin 하므로 busy loop 아님

    def _record_pose(self, wp, result):
        """이동 결과와 무관하게 마지막 위치를 저장 (_navigate 와 같은 규칙)."""
        current = self.get_current_pose()
        if current is None and result == TaskResult.SUCCEEDED:
            current = (wp[0], wp[1], wp[2] if len(wp) > 2 else 0.0)
        if current is not None:
            self.save_last_pose(*current)

    def _abort_entry(self, idx, name, state, detail=None):
        """
        진입 절차 중단 정리. 허가를 이미 받았다면 구역 밖이므로 락을 반납하고(notify_exit),
        아직 대기 중이면 대기열에서 빠진다(cancel_entry). 상태를 발행하고 깜박임을 멈춘다.
        """
        if self.gate.granted():
            self.gate.notify_exit()
        else:
            self.gate.cancel_entry()
        self.stop_blink()
        self.publish_status(state, idx, detail or name)

    def _retreat_after_stop(self, zone):
        """
        stop 으로 멈췄을 때 구역 ``zone`` 안에서 락을 들고 있다면: 그 구역의 EXIT 로 나가 락을 반납한다.
        _navigate 는 _stop_requested 면 곧바로 취소하므로 여기서는 별도 이동 루프를 쓴다.
        emergency_stop 이면(이동 중에 들어와도) 즉시 멈추고 락을 유지한다 (max_hold_sec 뒤 자동 해제).
        True : 도착해서 락을 반납함 / False : emergency 이거나 도달 실패 (락 유지)
        """
        if self._emergency_requested:
            self.get_logger().warn('emergency_stop: 후퇴/락 반납 없이 현재 위치 유지 (max_hold_sec 뒤 락 자동 해제)')
            return False
        wp = self.points[exit_name(zone)]
        self.publish_status('RETREATING', -1, exit_name(zone))
        self.set_drive_led()
        for attempt in range(self.NAV_RETRIES):
            self.navigator.goToPose(self.make_pose(*wp))
            while not self.navigator.isTaskComplete():
                if self._emergency_requested:           # 후퇴 중 emergency_stop: 즉시 정지, 락 유지
                    self.navigator.cancelTask()
                    self.get_logger().warn('emergency_stop: 후퇴 중단, 락 유지')
                    return False
                time.sleep(0.1)
            if self._emergency_requested:
                return False
            if self.navigator.getResult() == TaskResult.SUCCEEDED:
                self.gate.notify_exit()
                self.get_logger().info(f'stop: {exit_name(zone)} 도착, 락 반납 완료')
                return True
            self.get_logger().warn(f'후퇴 이동 실패, 재시도 {attempt+1}/{self.NAV_RETRIES}')
        self.get_logger().warn('후퇴 실패 - 락 유지 (max_hold_sec 타임아웃 대기)')
        return False

    def _leave_zone(self, zone):
        """
        구역 ``zone`` 의 이탈 문(Z<구역>_EXIT)으로 이동 -> 락 반납.
        True  : 도착해서 락을 반납함
        False : 도달 실패 (락 유지, max_hold_sec 타임아웃 대기)
        """
        door = self.points[exit_name(zone)]

        arrived = self._navigate(door)                              # 실제 이동 명령
        if not arrived:
            self.get_logger().warn(
                f'{exit_name(zone)} 도달 실패 - 락 유지 (max_hold_sec 타임아웃 대기)')
            return False

        self.gate.notify_exit()                                     # 도착했을 때만 락 반납
        self.get_logger().info('위험 구역 이탈, 락 반납 완료')
        return True

    # ==========================================================================
    # 12. 작업: goto / zone / leave / 유휴 복귀
    # ==========================================================================
    def _start_task(self, target, *args):
        """작업 스레드 시작 (콜백에서는 이것만 호출 -- Nav2 는 스레드에서만 다룬다)."""
        self._idle_deadline = None          # 새 명령이 오면 유휴 복귀 타이머 취소
        self._stop_requested = False
        self._emergency_requested = False
        self._running = True                # 스레드 시작 전에 세팅 (연타 시 중복 실행 방지)
        self._thread = threading.Thread(target=target, args=args, daemon=True)
        self._thread.start()

    def _exit_held_zone(self, idx):
        """
        보유 중인 구역의 EXIT 로 이동 -> 도착한 뒤에만 토큰 반납 -> ``_held_zone = None``.
        True : 반납 완료 / False : 도달 실패 또는 stop (토큰·``_held_zone`` 유지, FAILED/STOPPED 발행)
        """
        zone = self._held_zone
        self.publish_status('LEAVING_ZONE', idx, exit_name(zone))
        if not self._leave_zone(zone):
            self.publish_status(self._end_state(), idx, exit_name(zone))
            return False
        self._held_zone = None
        return True

    def _arm_idle(self):
        """
        명령을 마친 뒤 호출: 구역 안이면 HOLDING_ZONE 을 알리고, 유휴 복귀 타이머를 건다.
        이미 홈에 있고 구역도 쥐지 않았다면 돌아갈 곳이 없으므로 타이머를 걸지 않는다.
        stop / 실패 뒤에는 호출하지 않는다 (임의로 홈으로 가지 않기 위해).
        """
        if self._held_zone is not None:
            self.publish_status('HOLDING_ZONE', -1, self._held_zone)
        if self.idle_return_sec <= 0:
            return
        if self._held_zone is None and self._last_point == self.home_name:
            return
        self._idle_deadline = time.monotonic() + self.idle_return_sec
        self.publish_status('IDLE_WAIT', -1, f'{self.idle_return_sec:g}')

    def _idle_tick(self):
        """
        [타이머 콜백] 유휴 시간이 지났으면 복귀 스레드를 시작한다.
        콜백(executor 스레드)에서 Nav2 를 부르면 작업 스레드와 spin 이 겹치므로 스레드만 띄운다.
        """
        if self._running or self._idle_deadline is None or self.idle_return_sec <= 0:
            return
        if time.monotonic() < self._idle_deadline:
            return
        self._start_task(self._run_idle_return)

    def _finish_task(self):
        """
        모든 작업 스레드의 마무리 (finally).
        stop 으로 끝났고 구역 안에서 토큰을 들고 있으면 그 구역 EXIT(구역 밖)로 나와 반납한다.
        emergency_stop 이면 현재 위치/토큰을 유지하되, 노드는 구역을 쥔 것으로 기억하지 않는다
        (남은 토큰은 max_hold_sec 뒤 매니저가 해제하므로, 다음 zone 명령은 토큰을 다시 요청해야 한다).
        """
        held = self._held_zone
        if held is not None and self._stop_requested:
            if self._retreat_after_stop(held):
                self._held_zone = None
                self.publish_status('STOPPED', -1, 'retreated')
            elif self._emergency_requested:
                self._held_zone = None
        self.set_idle_led()     # 어떤 경우든 종료 시 대기 LED로 복귀
        self._running = False

    def _prepare_nav(self, detail):
        """작업 시작 공통: 상태 발행, 최초 1회 초기 위치 보정, Nav2 활성 대기."""
        self.publish_status('STARTING', -1, detail)
        self._init_pose_once()   # 최초 1회만 초기 위치 보정
        self.navigator.waitUntilNav2Active()

    def _run_goto(self, names):
        """
        [별도 스레드] 구역 밖 지점들을 순서대로 방문한다. 끝나도 홈으로 가지 않는다 (유휴 타이머만 홈 복귀를 맡는다).
        구역 토큰을 쥐고 있으면 먼저 그 구역 EXIT 에 도착해 반납한 뒤 출발한다.
        """
        try:
            self._prepare_nav(','.join(names))
            if self._held_zone is not None and not self._exit_held_zone(-1):
                return                                      # 반납 실패/stop -> 작업 종료 (토큰 유지)
            for idx, name in enumerate(names):
                if self._stop_requested:
                    self.publish_status('STOPPED', idx, name)
                    return
                self.publish_status('MOVING', idx, name)
                if not self._navigate(self.points[name]):   # 이동 실패 (stop 포함)
                    self.publish_status(self._end_state(), idx, name)
                    return
                self._last_point = name
                self.publish_status('ARRIVED', idx, name)
            self.publish_status('DONE', -1, f'arrived {names[-1]}')
            self._arm_idle()
        finally:
            self._finish_task()

    def _run_zone(self, name):
        """
        [별도 스레드] 구역 지점 ``name`` 으로 이동. 도착 후 토큰을 유지한다 (반납은 leave / goto / 다른 구역 zone / 유휴 복귀).

          다른 구역 토큰을 쥐고 있음 -> 그 구역 EXIT 도착 후 반납
          토큰 없음                  -> request_entry -> (슬롯 대기) -> grant 를 받은 뒤에만 구역 지점으로 출발
          같은 구역 토큰을 이미 쥠   -> 재요청 없이 바로 이동
        한 번에 한 구역의 토큰만 쥔다 (다른 구역 줄에서 기다리며 토큰을 쥐면 교착이 생길 수 있음).
        """
        target = zone_of(self.zone_points, name)
        try:
            self._prepare_nav(name)
            if self._held_zone is not None and self._held_zone != target:
                if not self._exit_held_zone(0):
                    return
            if self._held_zone is None:
                if not self._queue_and_enter(0, name, target):  # 허가를 못 받았으면 (이동 실패 / stop / 대기열 가득)
                    return
                self._held_zone = target                        # 허가받음 -> "그 구역 토큰 보유 중"
            self.publish_status('MOVING', 0, name)
            if not self._navigate(self.points[name]):
                if not self._stop_requested:                    # stop 이 아닌 "실패": EXIT 로 후퇴 시도
                    if self._leave_zone(self._held_zone):
                        self._held_zone = None
                self.publish_status(self._end_state(), 0, name)
                return
            self._last_point = name
            self.publish_status('ARRIVED', 0, name)
            self.publish_status('DONE', -1, f'arrived {name}')
            self._arm_idle()
        finally:
            self._finish_task()

    def _run_leave(self):
        """[별도 스레드] 보유 중인 구역의 EXIT 로 이동해 도착한 뒤 토큰을 반납한다 (홈으로 가지 않음)."""
        try:
            self._prepare_nav('leave')
            if not self._exit_held_zone(-1):
                return
            self._last_point = None                 # EXIT 에 서 있으므로 홈이 아님
            self.publish_status('DONE', -1, 'left zone')
            self._arm_idle()
        finally:
            self._finish_task()

    def _run_idle_return(self):
        """[별도 스레드] 유휴 시간이 지났을 때: 구역 안이면 EXIT 반납 후, 홈으로 복귀."""
        try:
            self._prepare_nav('idle return')
            if self._held_zone is not None and not self._exit_held_zone(-1):
                return
            if self._last_point != self.home_name:
                self.publish_status('RETURNING', -1, self.home_name)
                if not self._navigate(self.points[self.home_name]):
                    self.publish_status(self._end_state(), -1, 'return')
                    return
                self._last_point = self.home_name
            self.publish_status('DONE', -1, 'returned home')
        finally:
            self._finish_task()

    # ==========================================================================
    # 13. 작업: 전체 순찰
    # ==========================================================================
    # [비활성: v1.1.0 순회 중단]
    # 이유: v1.1.0 은 순회(start) 없이 goto/stop 만 운용한다. 삭제하지 않고 보관해
    #       나중에 순회를 되살릴 때 주석만 풀면 되게 한다.
    # 되살리는 절차:
    #   1) 아래 메서드의 "# " 를 모두 푼다 (들여쓰기는 그대로 유지).
    #   2) 2번 섹션의 WAYPOINTS(이름 리스트), 3번 섹션의 ZONE_ENTRY_INDEX / ZONE_EXIT_INDEX 주석을 푼다.
    #   3) _cmd_cb 의 'start' 분기를 "start disabled" 응답 대신 원래 스레드 시작 코드로 되돌린다.
    #   4) test/test_patrol_queue.py 에서 skip 처리한 start 경로 테스트를 되살린다.
    #   5) 아래 주석 코드는 위험구역이 1개이던 시절 기준이다 (ZONE_ENTRY_NAME / ZONE_EXIT_NAME / ZONE_STOP_EXIT).
    #      되살릴 때는 구역을 지정해 entry_name(zone) / exit_name(zone) 을 쓰고, _queue_and_enter / _leave_zone /
    #      _retreat_after_stop 에 zone 인자를 넘기도록 고친다 (zone 경로 _run_zone 이 같은 방식의 본보기).
    # 의존: _init_pose_once, _queue_and_enter, make_pose, _retreat_after_stop, self.gate
    #       (모두 goto 경로가 계속 사용하므로 그대로 남아 있다).
    # def _run_patrol(self):
        # """[별도 스레드] WAYPOINTS 전체 순회. rclpy.spin()을 막지 않아 stop을 받을 수 있음."""
        # self._running = True
        # holding = False   # True = 허가(락) 보유 중 (stop 시 후퇴/반납 판단용)
        # self.publish_status('STARTING', -1)
        # try:
            # # 1) 최초 1회만 초기 위치 보정 (이후 start/goto에서는 생략)
            # self._init_pose_once()

            # # 2) Nav2 활성화 대기
            # self.navigator.waitUntilNav2Active()

            # # 3) 웨이포인트 순회
            # for i, wp in enumerate(self.WAYPOINTS):
                # if self._stop_requested:
                    # self.publish_status('STOPPED', i)
                    # break

                # # 구역 진입 waypoint: 일반 이동 대신 goto 경로와 같은 _queue_and_enter 사용
                # # (요청 -> 슬롯 대기 -> 허가 -> 문 이동 까지 한 곳에서 처리)
                # if i == self.ZONE_ENTRY_INDEX:
                    # if not self._queue_and_enter(i, self.ZONE_ENTRY_NAME):
                        # break   # 중단/실패 상태는 _queue_and_enter 가 이미 발행함 (DONE 건너뜀)
                    # holding = True
                    # self.publish_status('MOVING', i + 1)
                    # continue

                # pose = self.make_pose(*wp)
                # self.set_drive_led()   # 주행 중: 초록 고정 점등

                # # 최대 3회 재시도 (일시적 장애물 / 로컬라이제이션 튐 대응)
                # for attempt in range(3):
                    # self.navigator.goToPose(pose)

                    # while not self.navigator.isTaskComplete():
                        # if self._stop_requested:
                            # self.navigator.cancelTask()
                            # break
                        # time.sleep(0.1)

                    # if self._stop_requested:
                        # break

                    # result = self.navigator.getResult()

                    # # 도착 여부와 무관하게 현재 위치 저장 (다음 재시작 대비)
                    # current = self.get_current_pose()
                    # if current is None:
                        # current = (pose.pose.position.x, pose.pose.position.y, 0.0)
                    # self.save_last_pose(*current)

                    # if result == TaskResult.SUCCEEDED:
                        # self.get_logger().info(f'{i+1}번째 목표 도착 성공 ({attempt+1}번째 시도)')
                        # self.publish_status('MOVING', i + 1)

                        # # 구역 이탈 waypoint 도착 -> 락 반납
                        # if i == self.ZONE_EXIT_INDEX:
                            # self.gate.notify_exit()
                            # holding = False

                        # break  # 성공 -> 재시도 루프 탈출 (else 스킵)
                    # else:
                        # self.get_logger().warn(
                            # f'{i+1}번째 목표 {attempt+1}번째 시도 실패: {result}, 재시도합니다')
                        # self.publish_status('RETRY', i + 1, str(result))
                # else:
                    # # for-else: 3회 모두 실패
                    # self.get_logger().error(f'{i+1}번째 목표 최종 실패 (3회 모두 실패)')
                    # self.publish_status('FAILED', i + 1)

                # if self._stop_requested:
                    # # 구역 안에서 멈춘 경우: 여기서는 notify_exit 를 보내지 않고 finally 에서
                    # # stop 이면 ZONE_STOP_EXIT 로 후퇴 후 반납, emergency_stop 이면 락 유지(max_hold_sec 뒤 해제)
                    # self.publish_status('STOPPED', i)
                    # break
            # else:
                # # for-else: 바깥 루프가 끝까지 돌았을 때 = 전체 완주
                # self.publish_status('DONE', len(self.WAYPOINTS))
        # finally:
            # # stop 으로 끝났고 구역 안에서 락을 들고 있으면 ZONE_STOP_EXIT 로 나와 락을 반납 (emergency_stop 이면 유지)
            # if holding and self._stop_requested:
                # if self._retreat_after_stop():
                    # self.publish_status('STOPPED', -1, 'retreated')
            # self.set_idle_led()     # 순찰 종료(DONE/STOPPED/FAILED/예외) -> 대기 LED
            # self._running = False


# ==============================================================================
# 14. main
# ==============================================================================
def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = PinkyPatrolNode()

    # rclpy.spin(node) 대신 전용 executor를 명시적으로 사용
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()   # patrol_cmd 명령을 계속 기다림
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        try:
            node.clear_led()
        except Exception:
            pass
        if node._led_proc is not None:
            # terminate(SIGTERM)는 led_server 내부 rclpy 핸들러를 거쳐
            # 이중 shutdown 에러를 내므로, 이미 LED를 끈 뒤에 kill()로 바로 종료
            node._led_proc.kill()
            try:
                node._led_proc.wait(timeout=2.0)
            except Exception:
                pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()