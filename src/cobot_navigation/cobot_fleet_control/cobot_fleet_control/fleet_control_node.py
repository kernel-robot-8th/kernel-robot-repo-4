"""ROS 실행기와 Paho MQTT 사이를 큐로 연결하는 얇은 노드."""

import json
import os
from pathlib import Path
from queue import Empty, Full, Queue

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .repository import encode, SqliteRepository
from .service import FleetService


class FleetControlNode(Node):
    """DB와 BT는 ROS executor 스레드에서만 접근한다."""

    def __init__(self):
        super().__init__('fleet_control')
        defaults = {
            'robot_ids': ['pinky1', 'pinky2', 'pinky3'],
            'mqtt_host': 'localhost', 'mqtt_port': 1883,
            'mqtt_client_id': 'cobot_fleet_control', 'mqtt_prefix': 'cobot/fleet',
            'db_path': '~/.cobot/fleet_control.sqlite3',
            'tick_sec': 0.1, 'queue_capacity': 1000,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        robots = config['robot_ids']
        self.prefix = config['mqtt_prefix'].rstrip('/')
        self.inbox = Queue(maxsize=config['queue_capacity'])
        self.inflight = {}
        self.publishers_by_robot = {
            robot: self.create_publisher(String, f'/{robot}/patrol_cmd', 10)
            for robot in robots
        }
        self.status_subscriptions = [
            self.create_subscription(
                String, f'/{robot}/patrol_status',
                lambda msg, robot=robot: self._status(robot, msg), 10)
            for robot in robots
        ]
        db_path = Path(config['db_path']).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.repository = SqliteRepository(str(db_path))
        self.service = FleetService(self.repository, self, robots)
        self.mqtt = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config['mqtt_client_id'], clean_session=False, manual_ack=True)
        if os.environ.get('COBOT_MQTT_USERNAME'):
            self.mqtt.username_pw_set(os.environ['COBOT_MQTT_USERNAME'],
                                      os.environ.get('COBOT_MQTT_PASSWORD'))
        if os.environ.get('COBOT_MQTT_CA'):
            self.mqtt.tls_set(ca_certs=os.environ['COBOT_MQTT_CA'])
        self.mqtt.on_connect = self._connect
        self.mqtt.on_message = self._message
        self.mqtt.reconnect_delay_set(min_delay=1, max_delay=30)
        self.mqtt.max_queued_messages_set(config['queue_capacity'])
        self.mqtt.connect_async(config['mqtt_host'], config['mqtt_port'])
        self.mqtt.loop_start()
        self.create_timer(config['tick_sec'], self._tick)

    def send(self, robot_id, payload):
        """MQTT 수신 스레드는 ROS 발행을 직접 호출하지 않는다."""
        publisher = self.publishers_by_robot[robot_id]
        if publisher.get_subscription_count() == 0:
            raise RuntimeError('로봇 명령 구독자 없음')
        publisher.publish(String(data=encode(payload)))

    def _connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(self.prefix + '/commands', qos=1)

    def _message(self, client, userdata, message):
        # 접수 저장이 끝나기 전에는 QoS 1 PUBACK을 보내지 않는다.
        try:
            self.inbox.put_nowait(message)
        except Full:
            self.get_logger().error('MQTT 수신 큐 포화: 접수하지 않음')

    def _status(self, robot_id, message):
        try:
            status = json.loads(message.data)
            self.service.on_status(robot_id, status)
            self.repository.record_status(robot_id, status)
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f'로봇 상태 무시: {error}')

    def _consume(self, message):
        try:
            if message.retain:
                raise ValueError('retain 명령은 재실행 위험 때문에 거절합니다')
            if len(message.payload) > 16384:
                raise ValueError('명령 크기는 16 KiB 이하')
            payload = json.loads(message.payload)
            row = self.service.submit(payload)
            response = {'command_id': row['command_id'], 'state': row['state']}
        except (ValueError, UnicodeError, TypeError) as error:
            response = {'state': 'REJECTED', 'detail': str(error)}
        self.mqtt.publish(self.prefix + '/receipts', encode(response), qos=1, retain=False)
        if message.qos:
            self.mqtt.ack(message.mid, message.qos)

    def _tick(self):
        try:
            # 한 tick의 입력량을 제한해 BT 결과 처리를 굶기지 않는다.
            for _ in range(100):
                try:
                    message = self.inbox.get_nowait()
                except Empty:
                    break
                self._consume(message)
            self.service.tick()
            if not self.mqtt.is_connected():
                return
            for event_id, info in list(self.inflight.items()):
                if info.is_published():
                    self.repository.acknowledge(event_id)
                    del self.inflight[event_id]
            for event in self.repository.pending():
                event_id = event['event_id']
                if event_id in self.inflight:
                    continue
                info = self.mqtt.publish(self.prefix + '/events', event['payload'],
                                         qos=1, retain=False)
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.inflight[event_id] = info
        except Exception as error:
            # DB 장애일 때 예외를 감추고 다음 명령을 계속 실행하지 않는다.
            self.get_logger().error(f'관제 처리 중단: {error}')
            raise

    def destroy_node(self):
        """통신 스레드를 먼저 멈춘 후 저장소를 닫는다."""
        self.mqtt.disconnect()
        self.mqtt.loop_stop()
        self.repository.close()
        return super().destroy_node()


def main(args=None):
    """관제 서버 진입점."""
    rclpy.init(args=args)
    node = FleetControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
