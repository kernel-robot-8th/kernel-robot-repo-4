"""중계 장비의 기록·판정 노드. patrol_cmd는 발행하지 않고 관제 요청 토픽만 쓴다."""

from concurrent.futures import Future
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import time

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, qos_profile_sensor_data, QoSProfile
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import Float32, String
import yaml

from .console_api import ConsoleApi, serve
from .load_complete import LoadComplete
from .load_evidence import LoadEvidence
from .manual_adapter import arm_node_warning, arm_presence, ManualAdapter
from .monitor_core import camera_allowed, MonitorCore
from .monitor_store import MonitorStore

REPLY_WAIT_SEC = 3.0
ADAPTER_CHECK_SEC = 2.0
# 관제 _layout 의 지점 자리 회수 설정 칸(origin/sakim scenario.py).
CUSTOMER_RETURN_KEYS = {'arrange', 'arrange_arm', 'restock', 'restock_arm'}


def layout_routes(config):
    """
    감시 경로 표를 관제와 같이 만든다(origin/sakim 1b0cb08 scenario.py ScenarioService._layout).

    routes 에 shelf 열 × destinations 자리마다 col<열>__<자리> 경로를 더한다. 값은 관제와 같다.
    - 지점 자리 {point, lane}: customer=지점, dropoff/dropoff_arm=회수 정리, restock/restock_arm=선반 반환.
    - 하차 구역 자리 {dropoff, dropoff_arm, lane}: 하차 팔이 내려놓는 기존 경로.
    관제 패키지는 import 하지 않는다. 관제라면 거절할 칸은 건너뛰고 (경로 표, 문제 목록)으로 돌려준다.
    """
    routes = {name: dict(route) for name, route in (config.get('routes') or {}).items()}
    shelf = config.get('shelf') or {}
    columns = (shelf.get('columns') if isinstance(shelf, dict) else None) or {}
    destinations = config.get('destinations') or {}
    back = config.get('customer_return') or {}
    problems = []
    if not isinstance(columns, dict) or not isinstance(destinations, dict):
        return routes, ['shelf.columns·destinations 형식 오류: 자리 경로를 만들지 않음']
    for name, target in destinations.items():
        keys = set(target) - {'name'} if isinstance(target, dict) else None
        if keys not in ({'dropoff', 'dropoff_arm', 'lane'}, {'point', 'lane'}):
            problems.append(f'자리 {name}: dropoff, dropoff_arm, lane 또는 point, lane 필요')
            continue
        if 'point' in keys and set(back) != CUSTOMER_RETURN_KEYS:
            problems.append(f'자리 {name}: customer_return(arrange·restock) 설정 없음')
            continue
        for column, pickup in columns.items():
            route = f'col{column}__{name}'
            if route in routes:
                problems.append(f'{route}: routes 의 이름과 겹침')
                continue
            if not isinstance(pickup, dict) or set(pickup) != {'pickup', 'pickup_arm'}:
                problems.append(f'shelf.columns {column}: pickup, pickup_arm 필요')
                continue
            if 'point' in keys:
                routes[route] = dict(pickup, customer=target['point'],
                                     dropoff=back['arrange'], dropoff_arm=back['arrange_arm'],
                                     restock=back['restock'], restock_arm=back['restock_arm'],
                                     lane=target['lane'])
            else:
                routes[route] = dict(pickup, dropoff=target['dropoff'],
                                     dropoff_arm=target['dropoff_arm'], lane=target['lane'])
    return routes, problems


def dock_tolerance_of(config):
    """scenario_config 의 정차 공차 {'dock_xy_m', 'dock_yaw_deg'}. 없는 키는 뺀다. 둘 다 없으면 None."""
    found = {key: config[key] for key in ('dock_xy_m', 'dock_yaw_deg')
             if isinstance(config, dict) and key in config}
    return found or None


def load_site(path):
    """진단 화면의 해시와 실제 사용한 지점을 같은 파일 내용에서 읽는다."""
    content = Path(path).read_bytes()
    points = yaml.safe_load(content)['pinky_patrol_node']['ros__parameters']['points']
    return points, hashlib.sha256(content).hexdigest()


def yaw_of(orientation):
    """쿼터니언에서 평면 방향을 구한다."""
    return math.atan2(2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
                      1.0 - 2.0 * (orientation.y ** 2 + orientation.z ** 2))


class AnomalyMonitorNode(Node):
    """저장소는 실행기 스레드에서만 만지고 HTTP 스레드는 작업 큐로 넘긴다."""

    def __init__(self):
        super().__init__('anomaly_monitor')
        share = Path(get_package_share_directory('cobot_anomaly_monitor'))
        patrol = Path(get_package_share_directory('cobot_pinky_patrol'))
        defaults = {
            'robot_ids': ['pinky1', 'pinky2', 'pinky3'],
            'db_path': '~/.cobot/anomaly_monitor.sqlite3',
            'scenario_config': str(share / 'config/scenario_relay_dev.yaml'),
            'site_config': str(patrol / 'config/sites/lab.yaml'),
            'cctv_control_mode': 'OBSERVE_ONLY',
            'console_host': '127.0.0.1', 'console_port': 8083,
            'manual_adapter': True, 'verify_load_join': False,
            'evidence_stream': 'ceiling', 'calibration_id': 'replay-v1',
            'load_model': 'pinky-v1', 'evidence_topic': '/anomaly_monitor/zone_evidence',
            'manual_targets': ['vision', 'navigation', 'omx1', 'omx2', 'omx3'],
            # 판정 없이 바로 성공으로 답할 대상. 빈 문자열만 있으면 끔(ROS 는 빈 목록 타입을 못 정한다)
            'auto_targets': [''],
            # 비전 판정(세 조건). off: 지금처럼 자동 응답, shadow: 판정을 참고값으로만 싣는다,
            # enforce: 판정이 통과해야 답한다. 대상이 auto_targets 에 있어야 쓰인다.
            'judge_mode': 'off', 'judge_stages': ['VERIFY_LOAD'],
            'box_evidence_topic': '/anomaly_monitor/box_evidence',
            'judge_hold_sec': 1.0, 'judge_still_ratio': 0.15, 'judge_drop_frames': 3,
            'judge_shadow_wait_sec': 5.0,
            'judge_fresh_sec': 2.0, 'judge_gap_sec': 1.0,
            'judge_min_frames': 3, 'judge_drop_reach': 1.0,
            'judge_drop_tray_iou_max': -1.0,
            'judge_require_tray_marker_absent': False,
            'judge_min_tray_box_frames': 0,
            'judge_latch_drop': False,
            'judge_max_wait_sec': 30.0,
            # 그리퍼 닫힘 상한·열림 하한. 음수면 그리퍼 값을 보지 않고 arm_safe 만 본다
            'gripper_closed_max': -1.0, 'gripper_open_min': -1.0,
            # 같은 결과 토픽에 함께 있어도 되는 노드와, 그 노드가 맡는 대상
            'peer_result_nodes': ['arm_adapter', 'omx1_adapter', 'omx2_adapter', 'omx3_adapter'],
            'peer_targets': ['omx1', 'omx2', 'omx3'],
            'allow_mock_events': True,
            'console_commands': False, 'observation_only': False,
            'camera_policy': 'field',
            'event_topic': '/anomaly_monitor/vision_event',
            'request_topic': '/control_center/task_request',
            'events_topic': '/control_center/task_events',
            'tasks_topic': '/control_center/tasks',
            'work_request_topic': '/fleet/work_request',
            'work_result_topic': '/fleet/work_result',
            'heartbeat_topic': '/fleet/heartbeat',
            'zone_status_topic': '/zone_manager/status',
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        self.config = config
        camera_allowed('', config['camera_policy'])
        # 자리 주문 경로(col1__P22 등)도 관제처럼 만들어야 기록에 팔 이름이 남는다(11-21 S5).
        scenario = yaml.safe_load(Path(config['scenario_config']).read_text(encoding='utf-8'))
        if 'routes' not in scenario:
            raise KeyError('routes')  # 예전처럼 routes 가 없는 설정으로는 시작하지 않는다
        routes, problems = layout_routes(scenario)
        for problem in problems:
            self.get_logger().warning('경로 표: ' + problem)
        # 추적표 정차 행의 공차 비교(S10·G6). 관제 scenario.yaml 과 같은 키다.
        self.dock_tolerance = dock_tolerance_of(scenario)
        self.store = MonitorStore(config['db_path'])
        if config['observation_only'] and (config['manual_adapter'] or config['console_commands']
                                           or config['cctv_control_mode'] != 'OBSERVE_ONLY'):
            raise ValueError('관측 전용 프로필에 제어·수동 어댑터를 함께 사용할 수 없습니다')
        self.request_pub = (None if config['observation_only'] else
                            self.create_publisher(String, config['request_topic'], 50))
        self.points, site_hash = load_site(config['site_config'])
        self.core = MonitorCore(self.store, routes, config['robot_ids'], self._send_request,
                                config['cctv_control_mode'], points=self.points)
        if config['camera_policy'] == 'sim':
            self.create_subscription(
                String, '/anomaly_monitor/sim_diagnostics', self._diagnostics, 5)
        self.core.ros = {'domain_id': os.environ.get('ROS_DOMAIN_ID', '0'),
                         'rmw': get_rmw_implementation_identifier(),
                         'monitor_site': Path(config['site_config']).name,
                         'site_sha256': site_hash}
        self.join = None
        if config['verify_load_join']:
            if (not config['manual_adapter'] or config['camera_policy'] != 'sim'
                    or os.environ.get('ROS_DOMAIN_ID') not in ('77', '140')
                    or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
                raise ValueError('적재 결합 시험은 격리 시뮬 도메인 77/140에서만 허용')
            self.join = LoadEvidence(self.core, self.points, config['evidence_stream'],
                                     config['calibration_id'], config['load_model'])
            self.create_subscription(String, config['evidence_topic'], self._zone_frame, 10)
        self._judge_warning_at = {}
        self.judge = None
        if config['judge_mode'] != 'off':
            if not config['manual_adapter'] or self.join:
                raise ValueError('비전 판정은 수동 어댑터가 켜져 있고 적재 결합 시험이 꺼져 있을 때만 씁니다')
            if 'vision' not in config['auto_targets']:
                self.get_logger().warning(
                    'judge_mode가 켜져 있지만 auto_targets에 vision이 없어 판정 응답이 실행되지 않습니다')
            grip = (config['gripper_closed_max'], config['gripper_open_min'])
            tray_iou = config['judge_drop_tray_iou_max']
            self.judge = LoadComplete(
                config['evidence_stream'], config['load_model'], config['calibration_id'],
                hold_sec=config['judge_hold_sec'], still_ratio=config['judge_still_ratio'],
                drop_frames=config['judge_drop_frames'],
                fresh_sec=config['judge_fresh_sec'], gap_sec=config['judge_gap_sec'],
                min_frames=config['judge_min_frames'], drop_reach=config['judge_drop_reach'],
                gripper_closed_max=grip[0] if min(grip) >= 0 else None,
                gripper_open_min=grip[1] if min(grip) >= 0 else None,
                drop_tray_iou_max=tray_iou if tray_iou > 0 else None,
                require_tray_marker_absent=config['judge_require_tray_marker_absent'],
                min_tray_box_frames=config['judge_min_tray_box_frames'],
                latch_drop=config['judge_latch_drop'])
            self.create_subscription(
                String, config['evidence_topic'],
                lambda m: self._judge_frame(m, self.judge.on_zones, '구역 근거'), 10)
            self.create_subscription(
                String, config['box_evidence_topic'],
                lambda m: self._judge_frame(m, self.judge.on_boxes, '상자 근거'), 10)
        self.adapter = self._create_adapter() if config['manual_adapter'] else None
        self.jobs = queue.Queue()
        self.console = ConsoleApi(
            self.core, self.adapter, self._run, self._wait_reply,
            config['allow_mock_events'], commands=config['console_commands'],
            observation_only=config['observation_only'], dock_tolerance=self.dock_tolerance)
        for robot in config['robot_ids']:
            self.create_subscription(Float32, f'/{robot}/battery/percent',
                                     lambda m, r=robot: self.core.on_battery(r, m.data), 10)
            self.create_subscription(String, f'/{robot}/patrol_status',
                                     lambda m, r=robot: self._status(r, m), 10)
            # 브리지가 맞춘 QoS와 상관없이 받도록 best effort로 구독한다.
            self.create_subscription(PoseWithCovarianceStamped, f'/{robot}/amcl_pose',
                                     lambda m, r=robot: self._pose(r, m),
                                     qos_profile_sensor_data)
            self.create_subscription(Odometry, f'/{robot}/odom',
                                     lambda m, r=robot: self._odom(r, m),
                                     qos_profile_sensor_data)
        self.create_subscription(
            String, config['tasks_topic'], self._tasks,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(String, config['work_request_topic'], self._work_request, 50)
        self.create_subscription(String, config['work_result_topic'], self._observed_result, 50)
        self.create_subscription(String, config['events_topic'], self._task_event, 50)
        self.create_subscription(String, config['event_topic'], self._vision, 50)
        self.create_subscription(String, config['zone_status_topic'],
                                 lambda m: self.core.on_zone_status(m.data), 10)
        self.create_timer(0.02, self._drain)
        self.create_timer(1.0, self._refresh)
        self.console.refresh()
        self.server = serve(self.console, config['console_host'], config['console_port'])
        self.get_logger().info(
            f'이상 감지 기록 시작: {self.core.mode}, 콘솔 '
            f"{config['console_host']}:{config['console_port']}")

    def _create_adapter(self):
        config = self.config
        self.result_pub = self.create_publisher(String, config['work_result_topic'], 50)
        adapter = ManualAdapter(self.store, self._publish_result, config['manual_targets'],
                                self.points, self.core._robot_view, join=self.join,
                                exclusive=lambda: not self._foreign_publishers()[0],
                                auto_targets=[t for t in config['auto_targets'] if t],
                                judge=self.judge, judge_mode=config['judge_mode'],
                                judge_stages=config['judge_stages'],
                                # 프레임을 이 주문의 로봇에 잇는 검사는 적재 결합과 같은 것을 쓴다.
                                attribute=(LoadEvidence(self.core, self.points, '', '', '')
                                           .attribution if self.judge else None),
                                shadow_wait_sec=config['judge_shadow_wait_sec'],
                                max_wait_sec=config['judge_max_wait_sec'],
                                warn=lambda text: self.get_logger().warning(text))
        adapter.blocked = '기동 검사 전'
        self.create_subscription(String, config['heartbeat_topic'], self._heartbeat, 10)
        self.adapter_check = self.create_timer(ADAPTER_CHECK_SEC, self._check_adapter)
        return adapter

    def _check_adapter(self):
        """다른 어댑터와 함께 돌면 같은 요청에 답이 둘 나가므로 답하지 않는다.

        우리가 먼저 떠도 뒤늦게 올라온 어댑터를 잡아야 하므로 계속 확인한다.
        """
        before = self.adapter.blocked
        foreign, peers = self._foreign_publishers()
        # 팀 팔 노드가 있으면 팔 대상은 그쪽에 맡기고 나머지 대상에만 답한다.
        self.adapter.yielded = set(self.config['peer_targets']) if peers else set()
        self.adapter.blocked = ('work_result 다른 발행자 ' + ', '.join(foreign)) if foreign else ''
        if self.adapter.blocked and self.adapter.blocked != before:
            self.get_logger().error('수동 어댑터 꺼짐: ' + self.adapter.blocked)
        elif before and not self.adapter.blocked:
            self.get_logger().info('수동 어댑터 다시 켜짐: 다른 발행자가 사라졌습니다')

    def _foreign_publishers(self):
        """결과 토픽의 다른 발행자를 (모르는 노드, 허용한 팔 노드)로 나눈다."""
        names = [info.node_name for info in
                 self.get_publishers_info_by_topic(self.config['work_result_topic'])]
        if self.get_name() in names:
            names.remove(self.get_name())  # 자기 발행자 하나. 같은 이름이 더 있으면 남겨서 막는다
        allowed = set(self.config['peer_result_nodes'])
        return (sorted(n for n in names if n not in allowed),
                sorted(n for n in names if n in allowed))

    def _send_request(self, payload):
        if self.request_pub is None:
            raise RuntimeError('관측 전용 프로필에는 관제 명령 발행자가 없습니다')
        self.request_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _publish_result(self, result):
        self.result_pub.publish(String(data=json.dumps(result, ensure_ascii=False)))

    def _run(self, job):
        """HTTP 스레드의 작업을 실행기 스레드에서 돌리고 결과를 기다린다."""
        future = Future()
        self.jobs.put((job, future))
        return future.result(timeout=REPLY_WAIT_SEC)

    def _drain(self):
        while True:
            try:
                job, future = self.jobs.get_nowait()
            except queue.Empty:
                return
            try:
                future.set_result(job())
            except Exception as error:
                future.set_exception(error)

    def _wait_reply(self, request_id):
        deadline = time.monotonic() + REPLY_WAIT_SEC
        while time.monotonic() < deadline:
            reply = self.core.replies.get(request_id)
            if reply is not None:
                return reply
            time.sleep(0.02)
        return None

    def _link(self, topic):
        pubs = self.get_publishers_info_by_topic(topic)
        subs = self.get_subscriptions_info_by_topic(topic)
        return {'publishers': self.count_publishers(topic),
                'publisher_nodes': sorted(i.node_name for i in pubs),
                'subscriber_nodes': sorted(i.node_name for i in subs),
                'subscribers': self.count_subscribers(topic)}

    def _read_graph(self):
        """토픽 연결 수와 scan 발행 QoS를 읽는다. 데이터를 구독하지 않는다."""
        robots = {}
        for robot in self.config['robot_ids']:
            scan = f'/{robot}/scan'
            robots[robot] = {name: self._link(f'/{robot}/{name}')
                             for name in ('patrol_cmd', 'patrol_status', 'amcl_pose', 'odom')}
            robots[robot]['scan'] = dict(self._link(scan), reliability=sorted({
                info.qos_profile.reliability.name
                for info in self.get_publishers_info_by_topic(scan)}))
        return {'request': self._link(self.config['request_topic']),
                'tasks': self._link(self.config['tasks_topic']), 'robots': robots}

    def _update_arm_nodes(self):
        """
        팔 대상별 팀 팔 노드가 보이는지 core 에 넘긴다(live 의 arm_nodes).

        양보 규칙은 그대로다(_check_adapter). 팔 단계에는 우리가 답하지 않는다. 표시와 경고에만 쓴다.
        """
        nodes = arm_presence(self._foreign_publishers()[1], self.config['peer_targets'])
        if nodes != self.core.arm_nodes:
            missing = sorted(target for target, present in nodes.items() if not present)
            self.get_logger().info('팔 노드 없음: ' + ', '.join(missing) if missing
                                   else '팔 노드 모두 보임')
        self.core.set_arm_nodes(nodes)

    def _refresh(self):
        self.core.graph = self._read_graph()
        self._update_arm_nodes()
        if self.adapter and self.adapter.auto:
            self.adapter.retry_auto()
        self.core.flush()
        self.console.refresh()

    def _decode(self, message, label):
        try:
            data = json.loads(message.data)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self.get_logger().warning(f'{label} 무시: JSON 객체 아님')
            return None
        return data

    def _status(self, robot, message):
        status = self._decode(message, '순찰 상태')
        if status is not None:
            self.core.on_status(robot, status)

    def _pose(self, robot, message):
        pose = message.pose.pose
        self.core.on_pose(robot, pose.position.x, pose.position.y, yaw_of(pose.orientation))

    def _odom(self, robot, message):
        linear = message.twist.twist.linear
        self.core.on_speed(robot, math.hypot(linear.x, linear.y))

    def _tasks(self, message):
        snapshot = self._decode(message, '관제 스냅샷')
        if snapshot is not None:
            self.core.on_tasks(snapshot)

    def _task_event(self, message):
        event = self._decode(message, '관제 이벤트')
        if event is not None:
            self.core.on_task_event(event)

    def _vision(self, message):
        event = self._decode(message, '이상 이벤트')
        if event is None:
            return
        if not camera_allowed(event.get('camera_id', ''), self.config['camera_policy']):
            self.get_logger().warning(f"이상 이벤트 거절: 카메라 {event.get('camera_id')}")
            return
        try:
            row = self.core.on_vision_event(event)
            self.get_logger().info(f"판정 {row['judgment']} 조치 {row['control_action']}")
        except ValueError as error:
            self.get_logger().warning(f'이상 이벤트 무시: {error}')

    def _heartbeat(self, message):
        heartbeat = self._decode(message, '관제 심박')
        if heartbeat is not None:
            self.adapter.on_heartbeat(heartbeat)

    def _diagnostics(self, message):
        data = self._decode(message, '브리지 진단')
        if data and isinstance(data.get('links'), list) and isinstance(data.get('warnings'), list):
            self.core.diagnostics = data

    def _zone_frame(self, message):
        frame = self._decode(message, '구역 근거')
        if self.adapter and frame is not None:
            self.adapter.on_evidence(frame)

    def _judge_frame(self, message, intake, label):
        frame = self._decode(message, label)
        if frame is not None:
            try:
                intake(frame, time.time())
            except (TypeError, OverflowError) as error:
                self.get_logger().warning(f'{label} 무시: {error}')
                return
            kind = 'zones' if label == '구역 근거' else 'boxes'
            problem = self.judge.problem[kind]
            now = time.monotonic()
            if problem == '시각·스트림·모델·보정 불일치':
                if now - self._judge_warning_at.get(kind, float('-inf')) >= 30.0:
                    self.get_logger().warning(f'{label} 전부 폐기: {problem}')
                    self._judge_warning_at[kind] = now
            else:
                self._judge_warning_at.pop(kind, None)

    def _work_request(self, message):
        request = self._decode(message, '작업 요청')
        if request is not None:
            now = time.time()
            self.store.observe_work('request', request, now)
            self._warn_arm_node(request, now)
            if self.adapter:
                self.adapter.on_request(request)

    def _warn_arm_node(self, request, now):
        """팔 대상 요청에 응답할 팀 팔 노드가 안 보이면 주문 기록에 남긴다. 대신 답하지는 않는다."""
        warning = arm_node_warning(request, self.core.arm_nodes)
        if not warning:
            return
        order_id, request_id = request.get('order_id'), request.get('request_id')
        if isinstance(order_id, str) and order_id and isinstance(request_id, str) and request_id:
            self.store.record_control('arm_node_missing', order_id, request_id, {
                'code': 'ARM_NODE_MISSING', 'detail': warning, 'target': request['target'],
                'stage': request.get('stage'), 'robot_id': request.get('robot_id')}, now)
        self.get_logger().warning(f"{warning} · {request.get('stage')} 요청 {request_id}")

    def _observed_result(self, message):
        result = self._decode(message, '작업 결과')
        if result is not None:
            self.store.observe_work('result', result, time.time())
            if self.judge:
                try:
                    self.judge.on_arm_result(result, time.time())
                except (TypeError, OverflowError) as error:
                    self.get_logger().warning(f'작업 결과 판정 입력 무시: {error}')

    def destroy_node(self):
        """HTTP를 먼저 멈춘 뒤 저장소를 닫는다."""
        try:
            self.server.shutdown()
        except KeyboardInterrupt:
            # Ctrl-C는 터미널과 launch에서 두 번 온다.
            pass
        finally:
            self.store.close()
        return super().destroy_node()


def main(args=None):
    """기록 노드를 시작한다."""
    rclpy.init(args=args)
    node = AnomalyMonitorNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
