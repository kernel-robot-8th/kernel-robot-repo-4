"""ROS 중앙 실행기. 웹 통신은 cobot_control_center에서 담당한다."""

import json
from pathlib import Path
import time
import uuid

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Float32, String
import yaml

from .control_api import ControlAPI
from .repository import encode, SqliteRepository
from .scenario import ScenarioService
from .service import FleetService
from .web_profiles import load_profiles


class FleetControlNode(Node):
    """하나의 ROS 실행기에서 SQLite·주행 행동 트리·시나리오에 접근한다."""

    def __init__(self):
        super().__init__('fleet_control')
        defaults = {
            'robot_ids': ['pinky1', 'pinky2', 'pinky3'],
            'db_path': '~/.cobot/fleet_control.sqlite3', 'tick_sec': 0.1,
            'heartbeat_sec': 0.5, 'heartbeat_ttl_sec': 3.0, 'command_ttl_sec': 5.0,
            'scenario_config': str(Path(get_package_share_directory('cobot_fleet_control'))
                                   / 'config/scenario.yaml'),
            'request_topic': '/control_center/task_request',
            'events_topic': '/control_center/task_events',
            'tasks_topic': '/control_center/tasks',
            'work_request_topic': '/fleet/work_request',
            'work_result_topic': '/fleet/work_result',
            'patrol_config_dir': '', 'site': 'lab',
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        self.config = config
        robots = config['robot_ids']
        if not robots or len(set(robots)) != len(robots):
            raise ValueError('robot_ids는 중복 없는 목록이어야 합니다')
        self.publishers_by_robot = {
            robot: self.create_publisher(String, f'/{robot}/patrol_cmd', 10) for robot in robots}
        self.heartbeat_publishers = {
            robot: self.create_publisher(String, f'/{robot}/fleet_heartbeat', 10)
            for robot in robots}
        self.fleet_heartbeat_pub = self.create_publisher(String, '/fleet/heartbeat', 10)
        self.session_id = uuid.uuid4().hex
        self.sequences = {robot: 0 for robot in robots}
        self.heartbeat_seq = 0
        self.work_sequences = {}
        self.events_pub = self.create_publisher(String, config['events_topic'], 50)
        self.tasks_pub = self.create_publisher(
            String, config['tasks_topic'],
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.work_pub = self.create_publisher(String, config['work_request_topic'], 50)
        db_path = Path(config['db_path']).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.repository = SqliteRepository(str(db_path))
        self.service = FleetService(self.repository, self, robots)
        scenario_config = yaml.safe_load(
            Path(config['scenario_config']).read_text(encoding='utf-8'))
        self.scenario = ScenarioService(self.repository, self.service, self, **scenario_config)
        rules = (load_profiles(config['patrol_config_dir'], config['site'], robots)
                 if config['patrol_config_dir'] else None)
        self.api = ControlAPI(self.scenario, self.service, self, point_rules=rules)
        self.status_subscriptions = []
        for robot in robots:
            self.status_subscriptions.extend([
                self.create_subscription(String, f'/{robot}/patrol_status',
                                         lambda msg, r=robot: self._status(r, msg), 10),
                self.create_subscription(Float32, f'/{robot}/battery/percent',
                                         lambda msg, r=robot: self._battery(r, msg), 10)])
        self.create_subscription(String, config['request_topic'], self._request, 50)
        self.create_subscription(String, config['work_result_topic'], self._result, 50)
        self.create_timer(config['tick_sec'], self._tick)
        self.create_timer(1.0, self._snapshot)
        self.create_timer(config['heartbeat_sec'], self._heartbeat)
        self.get_logger().warning(
            '중앙 실행기 시작 (작업 명령 꺼짐). control-center task_manager_node와 동시 실행 금지.')

    def send(self, robot_id, payload):
        """이동 전 명령 발행자와 로봇 구독자가 각각 하나인지 확인한다."""
        publisher = self.publishers_by_robot[robot_id]
        if not self.ready(robot_id):
            raise RuntimeError('명령 실행기·발행자 중복 또는 로봇 명령 구독 연결 미확인')
        publisher.publish(String(data=encode(self._envelope(robot_id, payload))))

    def ready(self, robot_id):
        """동일 요청을 두 실행기가 동시에 받거나 명령을 중복 발행하면 이동을 거절한다."""
        return (self.publishers_by_robot[robot_id].get_subscription_count() == 1
                and self.count_publishers(f'/{robot_id}/patrol_cmd') == 1
                and self.count_subscribers(self.config['request_topic']) == 1
                and self.count_publishers(self.config['tasks_topic']) == 1)

    def _envelope(self, robot_id, payload):
        self.sequences[robot_id] += 1
        return dict(payload, session_id=self.session_id, seq=self.sequences[robot_id],
                    issued_at=time.time(), ttl_sec=self.config['command_ttl_sec'])

    def _heartbeat(self):
        self.heartbeat_seq += 1
        payload = dict(session_id=self.session_id, seq=self.heartbeat_seq,
                       issued_at=time.time(), ttl_sec=self.config['heartbeat_ttl_sec'])
        self.fleet_heartbeat_pub.publish(String(data=encode(payload)))
        for publisher in self.heartbeat_publishers.values():
            publisher.publish(String(data=encode(payload)))

    def release(self, robot_id, route=None):
        """현장 상태를 명시적으로 확인한 뒤 로봇의 정지 잠금을 해제한다."""
        self.send(robot_id, {'command_id': uuid.uuid4().hex, 'command': 'control_reset'})
        if route:
            for target in {route['pickup_arm'], route['dropoff_arm']}:
                self.work(dict(request_id=uuid.uuid4().hex, order_id='', robot_id=robot_id,
                               target=target, stage='SAFETY', action='release_hold'))

    def work(self, payload):
        """장치 어댑터는 request_id로 중복을 제거하고 실측한 최종 결과를 반환한다."""
        target = payload['target']
        self.work_sequences[target] = self.work_sequences.get(target, 0) + 1
        payload = dict(payload, session_id=self.session_id, seq=self.work_sequences[target],
                       issued_at=time.time(), ttl_sec=self.config['command_ttl_sec'])
        self.work_pub.publish(String(data=encode(payload)))

    def halt(self, robot_id, route, order_id):
        """소프트웨어 정지를 요청한다. 하드웨어 전원 차단을 보장하지는 않는다."""
        self.publishers_by_robot[robot_id].publish(String(data=encode(
            {'command_id': uuid.uuid4().hex, 'command': 'emergency_stop'})))
        routes = list(self.scenario.routes.values()) if route.get('all_arms') else [route]
        targets = {r.get(k) for r in routes for k in ('pickup_arm', 'dropoff_arm')} - {None}
        for target in targets:
            self.work(dict(request_id=uuid.uuid4().hex, order_id=order_id, robot_id=robot_id,
                           target=target, stage='SAFETY', action='hold'))

    def _decode(self, message):
        if len(message.data.encode('utf-8')) > 16384:
            raise ValueError('JSON 요청 크기는 16 KiB 이하')
        data = json.loads(message.data)
        if not isinstance(data, dict):
            raise ValueError('JSON 객체 필요')
        return data

    def _request(self, message):
        try:
            reply = self.api.handle(self._decode(message))
            self.events_pub.publish(String(data=encode(reply)))
            self._snapshot()
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f'요청 거절: {error}')

    def _status(self, robot_id, message):
        try:
            status = self._decode(message)
            self.scenario.telemetry(robot_id, status=status)
            self.service.on_status(robot_id, status)
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f'로봇 상태 무시: {error}')

    def _battery(self, robot_id, message):
        try:
            self.scenario.telemetry(robot_id, battery=message.data)
        except ValueError as error:
            self.get_logger().warning(str(error))

    def _result(self, message):
        try:
            self.scenario.result(self._decode(message))
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f'장치 결과 무시: {error}')

    def _snapshot(self):
        self.tasks_pub.publish(String(data=encode(self.api.snapshot())))

    def _tick(self):
        for robot_id in self.service.robots:
            if not self.scenario._fresh(robot_id):
                for row in list(self.repository.db.execute(
                        "SELECT command_id FROM commands WHERE robot_id=? "
                        "AND state IN ('ACCEPTED','RUNNING')", (robot_id,))):
                    self.service.quarantine(row[0], '통신·배터리 상태 수신 만료')
                    self.scenario.store.hold(robot_id, 'LINK_LOST')
                    self.halt(robot_id, {}, '')
        self.scenario.tick()
        self.service.tick(allow_dispatch=self.scenario.armed)
        for event in self.repository.pending():
            payload = json.loads(event['payload'])
            if payload['type'] == 'command_state':
                payload = dict(type='task', event_id=payload['event_id'],
                               task=self.api._task(self.repository.get(payload['command_id'])))
            self.events_pub.publish(String(data=encode(payload)))
            # 로컬 원장은 영속 저장된다. ROS 발행만으로 원격 수신·저장이 확인되지는 않는다.
            self.repository.acknowledge(event['event_id'])

    def destroy_node(self):
        """실행기가 멈춘 뒤 원장 연결을 닫는다."""
        self.repository.close()
        return super().destroy_node()


def main(args=None):
    """기존 관제 ROS 도메인에서 중앙 실행기를 시작한다."""
    rclpy.init(args=args)
    node = FleetControlNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
