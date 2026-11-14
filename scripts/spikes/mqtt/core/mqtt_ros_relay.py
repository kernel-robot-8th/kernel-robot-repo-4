#!/usr/bin/env python3
# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
MQTT 학습 3단계: ROS 토픽 하나를 MQTT 로 중계하는 학습용 스파이크.

왜 필요한가: 기존 cobot_domain_bridge(DDS 복사)와 달리 MQTT 브로커를 거치면 도메인이
서로 다른 장비 사이를 어떻게 잇는지, 메시지가 JSON 으로 바뀔 때 무엇이 달라지는지 본다.
cobot_domain_bridge 는 수정하지 않는다.

방향 두 가지 (한 스크립트, --direction 으로 고른다):
  ros2mqtt: ROS 토픽을 구독해 JSON 으로 바꿔 MQTT 로 발행한다. ROS 쪽은 읽기 전용이다.
            pinky1(도메인 10)에서는 이 방향만 쓴다.
  mqtt2ros: MQTT 를 구독해 ROS 메시지로 되돌려 발행한다. 관제 PC(도메인 100)에서만 쓴다.
            발행 토픽은 반드시 /mqtt_test/ 로 시작해야 한다 (기존 브릿지·실제 토픽과 섞이지
            않게 하는 안전장치다. 어기면 실행하지 않는다).

메시지: {"type": "<pkg/msg/Type>", "sent_at": <발행 시각>, "data": {필드...}} 형태의 JSON.
직렬화는 rosidl_runtime_py 의 message_to_ordereddict / set_message_fields 를 쓴다.

종료 코드: 0 = 한 건 이상 중계, 1 = 한 건도 중계 못 함, 2 = 설정·접속 오류.

안전:
  - 구동 토픽(cmd_vel, goal_pose, initialpose 등)에는 쓰지 않는다. 이 스크립트는 ROS 에
    쓰는 일을 mqtt2ros 의 /mqtt_test/ 토픽으로만 한다.
  - 중계율 상한(--max-rate-hz)과 실행 시간(--duration)이 항상 있어 무한히 돌지 않는다.
  - ROS_DOMAIN_ID 는 바꾸지 않는다. 호출한 셸의 값을 그대로 쓰고 시작할 때 로그로 남긴다.
  - MQTT 는 기본으로 retained 없이 발행한다 (--mqtt-retain 을 준 토픽만 보관).

실행 (ROS 2 Jazzy 환경, paho-mqtt 1.6.x 기준):
    # 격리 드라이런 (로봇 없음). CYCLONEDDS_URI 가 Wi-Fi 를 지정한 PC 에서는
    # ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST 만으로 LAN 유출이 막히지 않는다.
    # mqtt_bench_net.py 의 LO_ONLY_URI 처럼 CYCLONEDDS_URI 를 loopback 전용으로 바꿔서 돌린다.
    ROS_DOMAIN_ID=77 CYCLONEDDS_URI='<loopback 전용 설정>' \
      python3 scripts/spikes/mqtt/core/mqtt_ros_relay.py \
      --direction ros2mqtt --ros-topic /spike/value --msg-type std_msgs/msg/Float32 \
      --mqtt-topic mqtt_learning/relay/value
"""

import argparse
import json
import logging
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from rosidl_runtime_py.utilities import get_message

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_SETUP_FAILED = 2

OUT_TOPIC_PREFIX = '/mqtt_test/'
# --allow-any-out-topic 은 이 격리 시험 도메인에서만 허용한다. 실제 도메인(10, 100 등)은 거부.
ISOLATED_DOMAINS = ('101', '102')
# 실제 관제 도메인. --confirm-real-domain 100 을 명시했을 때만 발행을 허용한다 (도메인 10 은 항상 거부).
REAL_DOMAIN = '100'
SPIN_TIMEOUT_SEC = 0.1

LOGGER = logging.getLogger('mqtt_ros_relay')


def parse_args(argv=None):
    """명령행 인자를 읽는다. 값은 코드에 박아 두지 않고 모두 여기서 받는다."""
    parser = argparse.ArgumentParser(description='ROS 토픽 <-> MQTT 학습용 중계')
    parser.add_argument('--direction', choices=('ros2mqtt', 'mqtt2ros'), required=True)
    parser.add_argument('--msg-type', required=True, help='예: std_msgs/msg/Float32')
    parser.add_argument('--mqtt-topic', required=True, help='MQTT 토픽')
    parser.add_argument('--ros-topic', default='', help='ros2mqtt: 구독할 ROS 토픽')
    parser.add_argument('--ros-out-topic', default='',
                        help=f'mqtt2ros: 발행할 ROS 토픽 ({OUT_TOPIC_PREFIX} 로 시작해야 함)')
    parser.add_argument('--allow-any-out-topic', action='store_true',
                        help='mqtt2ros: /mqtt_test/ 제한을 풀고 원래 토픽 이름으로 발행 '
                             '(ROS_DOMAIN_ID 가 101·102 일 때만 허용)')
    parser.add_argument('--confirm-real-domain', default='',
                        help='실제 관제 도메인 100 에 발행하려면 100 을 적는다 '
                             '(--allow-any-out-topic 과 함께, 도메인 100 에서만 유효)')
    parser.add_argument('--ros-durability', choices=('volatile', 'transient_local'),
                        default='volatile',
                        help='ROS QoS 내구성. transient_local 이면 마지막 값을 보관하는 '
                             '(래치) 토픽을 받거나 늦게 붙는 구독자에게 건넨다')
    parser.add_argument('--mqtt-retain', action='store_true',
                        help='ros2mqtt: MQTT 브로커가 마지막 값을 보관하게 한다 '
                             '(늦게 켜진 mqtt2ros 도 값을 받음). 끝나면 직접 지워야 한다')
    parser.add_argument('--ros-qos', choices=('reliable', 'best_effort'), default='',
                        help='ROS QoS 신뢰성 (기본: 구독은 best_effort, 발행은 reliable)')
    parser.add_argument('--ros-depth', type=int, default=10, help='ROS QoS depth')
    parser.add_argument('--mqtt-qos', type=int, choices=(0, 1, 2), default=0, help='MQTT QoS')
    parser.add_argument('--host', default='127.0.0.1', help='브로커 주소')
    parser.add_argument('--port', type=int, default=1883, help='브로커 포트')
    parser.add_argument('--keepalive', type=int, default=30, help='MQTT keepalive [s]')
    parser.add_argument('--max-rate-hz', type=float, default=2.0,
                        help='ros2mqtt 중계율 상한 [Hz]. 0 이면 제한 없음')
    parser.add_argument('--duration', type=float, default=30.0, help='최대 실행 시간 [s]')
    parser.add_argument('--connect-timeout', type=float, default=5.0, help='접속 대기 [s]')
    return parser.parse_args(argv)


def validate_args(args):
    """안전 조건을 검사한다. 어긋나면 사유 문장을, 괜찮으면 빈 문자열을 돌려준다."""
    if args.direction == 'ros2mqtt' and not args.ros_topic:
        return 'ros2mqtt 는 --ros-topic 이 필요하다'
    if args.direction == 'mqtt2ros':
        if args.allow_any_out_topic:
            domain = os.environ.get('ROS_DOMAIN_ID', '')
            confirmed = domain == REAL_DOMAIN and args.confirm_real_domain == REAL_DOMAIN
            if domain not in ISOLATED_DOMAINS and not confirmed:
                return (f'--allow-any-out-topic 은 ROS_DOMAIN_ID 가 {"/".join(ISOLATED_DOMAINS)} '
                        f'일 때만 허용된다 (현재 {domain or "없음"}). 실제 관제 도메인 '
                        f'{REAL_DOMAIN} 은 --confirm-real-domain {REAL_DOMAIN} 도 함께 줘야 한다')
            if not args.ros_out_topic.startswith('/'):
                return '--ros-out-topic 은 / 로 시작해야 한다'
        elif not args.ros_out_topic.startswith(OUT_TOPIC_PREFIX):
            # 실제 토픽이나 기존 브릿지 토픽에 쓰지 못하게 접두사를 강제한다.
            return f'mqtt2ros 의 --ros-out-topic 은 {OUT_TOPIC_PREFIX} 로 시작해야 한다'
    return ''


def to_json_default(value):
    """직렬화기가 모르는 타입(numpy 배열, array.array 등)을 리스트로 바꾼다."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError(f'JSON 으로 바꿀 수 없는 타입: {type(value)}')


def make_qos(args, default_reliability):
    """인자로 QoSProfile 을 만든다. 구독은 best_effort 가 어떤 발행자와도 호환된다."""
    latched = args.ros_durability == 'transient_local'
    # transient_local 은 reliable 이어야 마지막 값이 전달되므로 따로 지정하지 않으면 reliable.
    name = args.ros_qos or ('reliable' if latched else default_reliability)
    reliability = (
        ReliabilityPolicy.RELIABLE if name == 'reliable' else ReliabilityPolicy.BEST_EFFORT)
    durability = DurabilityPolicy.TRANSIENT_LOCAL if latched else DurabilityPolicy.VOLATILE
    return QoSProfile(depth=args.ros_depth, reliability=reliability, durability=durability)


class Relay:
    """ROS 노드와 MQTT 클라이언트를 묶어 한 방향으로 중계하는 클래스."""

    def __init__(self, args, msg_class):
        self._args = args
        self._msg_class = msg_class
        self._node = Node(f'mqtt_relay_{args.direction}')
        self._min_interval = 1.0 / args.max_rate_hz if args.max_rate_hz > 0 else 0.0
        self._last_sent = 0.0
        self._lock = threading.Lock()
        self._seen = 0
        self._relayed = 0
        self._dropped = 0
        self._errors = 0
        self._connected = threading.Event()
        self._connect_rc = None
        # clean_session=True: 중계는 상태를 남기지 않는다. 끊긴 사이 값은 의미가 없다.
        self._client = mqtt.Client(clean_session=True)
        self._client.on_connect = self._on_mqtt_connect
        self._client.on_disconnect = self._on_mqtt_disconnect
        self._publisher = None
        if args.direction == 'ros2mqtt':
            self._node.create_subscription(
                msg_class, args.ros_topic, self._on_ros_message, make_qos(args, 'best_effort'))
        else:
            self._publisher = self._node.create_publisher(
                msg_class, args.ros_out_topic, make_qos(args, 'reliable'))
            self._client.on_message = self._on_mqtt_message

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """접속(재접속 포함) 때마다 불린다. mqtt2ros 의 구독은 여기서 걸어 재접속에 대비한다."""
        self._connect_rc = rc
        if rc == 0:
            LOGGER.info('MQTT 접속 성공 %s:%d', self._args.host, self._args.port)
            if self._args.direction == 'mqtt2ros':
                client.subscribe(self._args.mqtt_topic, qos=self._args.mqtt_qos)
        else:
            LOGGER.error('MQTT 접속 거부 rc=%d (%s)', rc, mqtt.connack_string(rc))
        self._connected.set()

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """끊길 때 불린다. rc 0 이 아니면 예기치 않은 끊김이라 paho 가 재접속을 시도한다."""
        if rc != 0:
            LOGGER.warning('MQTT 예기치 않게 끊김 rc=%d', rc)

    def _on_ros_message(self, msg):
        """ROS 메시지를 JSON 으로 바꿔 MQTT 로 발행한다. 중계율 상한을 넘으면 버린다."""
        now = time.monotonic()
        with self._lock:
            self._seen += 1
            if now - self._last_sent < self._min_interval:
                self._dropped += 1
                return
            self._last_sent = now
        envelope = {
            'type': self._args.msg_type,
            'sent_at': time.time(),
            'data': message_to_ordereddict(msg),
        }
        try:
            payload = json.dumps(envelope, default=to_json_default)
        except TypeError as error:
            with self._lock:
                self._errors += 1
            LOGGER.error('직렬화 실패: %s', error)
            return
        self._client.publish(
            self._args.mqtt_topic, payload, qos=self._args.mqtt_qos,
            retain=self._args.mqtt_retain)
        with self._lock:
            self._relayed += 1

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT 의 JSON 을 ROS 메시지로 되돌려 발행한다. 깨진 입력은 세고 건너뛴다."""
        with self._lock:
            self._seen += 1
        try:
            envelope = json.loads(msg.payload.decode('utf-8'))
            if envelope.get('type') != self._args.msg_type:
                raise ValueError(f"타입 불일치: {envelope.get('type')}")
            ros_msg = self._msg_class()
            set_message_fields(ros_msg, envelope['data'])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            with self._lock:
                self._errors += 1
            LOGGER.error('수신 변환 실패: %s', error)
            return
        self._publisher.publish(ros_msg)
        with self._lock:
            self._relayed += 1
            relayed = self._relayed
        # 메시지마다 INFO 로그를 남기면 고주파에서 로그 쓰기가 병목이 된다. 첫 건만 INFO 로 남긴다.
        level = logging.INFO if relayed == 1 else logging.DEBUG
        LOGGER.log(level, '재발행 %s (MQTT 도착-발행 시각 차 %.1f ms, 장비 간이면 시계 오차 포함)',
                   self._args.ros_out_topic, (time.time() - envelope.get('sent_at', 0)) * 1000)

    def connect(self):
        """브로커에 접속하고 네트워크 스레드를 시작한다. 성공하면 True 를 돌려준다."""
        try:
            self._client.connect(self._args.host, self._args.port, self._args.keepalive)
        except OSError as error:
            LOGGER.error('브로커에 닿지 않음: %s', error)
            return False
        self._client.loop_start()
        if not self._connected.wait(self._args.connect_timeout):
            LOGGER.error('MQTT 접속 확인 시간 초과')
            return False
        return self._connect_rc == 0

    def run(self):
        """--duration 동안 ROS 콜백을 처리한다."""
        deadline = time.monotonic() + self._args.duration
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self._node, timeout_sec=SPIN_TIMEOUT_SEC)

    def close(self):
        """정상 종료한다. 클라이언트와 노드를 정리한다."""
        self._client.disconnect()
        self._client.loop_stop()
        self._node.destroy_node()

    def summary(self):
        """중계 요약을 남기고 중계한 건수를 돌려준다."""
        with self._lock:
            seen, relayed = self._seen, self._relayed
            dropped, errors = self._dropped, self._errors
        LOGGER.info('요약(%s): 받음 %d, 중계 %d, 상한으로 버림 %d, 오류 %d',
                    self._args.direction, seen, relayed, dropped, errors)
        return relayed


def main(argv=None):
    """중계를 실행하고 종료 코드를 돌려준다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    problem = validate_args(args)
    if problem:
        LOGGER.error(problem)
        return EXIT_SETUP_FAILED
    try:
        msg_class = get_message(args.msg_type)
    except (ValueError, AttributeError, ModuleNotFoundError) as error:
        LOGGER.error('메시지 타입을 불러오지 못함 %s: %s', args.msg_type, error)
        return EXIT_SETUP_FAILED
    LOGGER.info('시작 direction=%s ROS_DOMAIN_ID=%s 최대 %.0f s',
                args.direction, os.environ.get('ROS_DOMAIN_ID', '(없음)'), args.duration)
    rclpy.init()
    relay = Relay(args, msg_class)
    try:
        if not relay.connect():
            return EXIT_SETUP_FAILED
        relay.run()
        return EXIT_OK if relay.summary() else EXIT_NOTHING
    finally:
        relay.close()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
