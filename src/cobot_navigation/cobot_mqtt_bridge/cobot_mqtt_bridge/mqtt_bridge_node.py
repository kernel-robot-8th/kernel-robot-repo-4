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
MQTT 브릿지 노드: 로봇 한 대의 브릿지 YAML 토픽을 프로세스 1개로 중계한다.

두 역할 (side 파라미터):
  robot: up 토픽은 로봇 도메인에서 구독해 MQTT 로 보내고,
         down 토픽(enable_down:=true 일 때)은 MQTT 를 받아 로봇 도메인에 발행한다.
  pc   : up 토픽은 MQTT 를 받아 관제 도메인에 (관제 쪽 이름으로) 발행하고,
         down 토픽은 관제 도메인에서 구독해 MQTT 로 보낸다.

down(관제→로봇, 명령)은 로봇을 움직일 수 있어서 기본으로 꺼져 있다(enable_down).
로봇 쪽 발행은 시험 도메인(101/102)에서만 하고, 실제 로봇 도메인은 confirm_real_domain 과
cmd_vel 보호(워치독·속도 상한)가 모두 있어야 한다. cmd_vel 은 상한 클램프, 오래된 메시지
폐기, 워치독 정지를 거친다.

종료 코드: 0 = 한 건 이상 중계, 1 = 한 건도 중계 못 함, 2 = 설정·접속·안전 검사 오류.
"""

import json
import os
import signal
import sys
import threading
import time

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from cobot_mqtt_bridge.bridge_config import (
    BridgeSettings, DOWN, load_rules, status_topic_name, UP)
from cobot_mqtt_bridge.cmd_vel_guard import clamp_twist, is_stale, is_zero, Watchdog
from cobot_mqtt_bridge.relay_utils import (
    check_publish_domain, check_robot_publish_domain, decode_envelope, encode_envelope,
    ISOLATED_DOMAINS, RateGate)
import paho.mqtt.client as mqtt
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from rosidl_runtime_py.utilities import get_message


EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_SETUP_FAILED = 2

SIDES = ('robot', 'pc')
SPIN_TIMEOUT_SEC = 0.1
QOS_DEPTH = 10
CONNECT_TIMEOUT_SEC = 5.0
TWIST_TYPE = 'geometry_msgs/msg/Twist'
# 명령(down)은 한 번이라도 빠지면 안 되므로 MQTT QoS 1, 상태(up)는 최신 값이 중요해 QoS 0
MQTT_QOS = {UP: 0, DOWN: 1}


class TopicStats:
    """토픽 하나의 통계. 받음/중계/버림/오류."""

    def __init__(self):
        self.seen = 0
        self.relayed = 0
        self.dropped = 0
        self.errors = 0


class MqttBridge:
    """ROS 노드와 MQTT 클라이언트를 묶어 토픽을 중계한다."""

    def __init__(self, node):
        self._node = node
        self._log = node.get_logger()
        self._declare_parameters()
        self._robot = self._param('robot')
        self._side = self._param('side')
        self._lock = threading.Lock()
        self._rules = []
        self._stats = {}
        self._gates = {}
        self._by_mqtt = {}
        self._sinks = {}
        self._cmd_vel_topic = ''
        self._watchdog = None
        self._connected = threading.Event()
        self._connect_rc = None
        self._stop = threading.Event()
        self._abort_reason = ''
        self._link_up = False
        self._ever_connected = False
        self._latched_payloads = {}
        self._peer_state = ''
        self._parent_pid = os.getppid()
        self._status_topic = ''
        self._peer_status_topic = ''
        # clean_session=True: 끊긴 사이 값은 의미가 없다. 래치 토픽은 retain 으로 복구한다.
        self._client = mqtt.Client(clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_mqtt_message

    # ----- 설정 -----
    def _declare_parameters(self):
        defaults = {
            'robot': '', 'side': '', 'bridge_config': '',
            'host': '127.0.0.1', 'port': 1883, 'keepalive_sec': 30,
            'topic_prefix': 'mqtt_bridge', 'pc_domain': 100, 'robot_domain': 10,
            'exclude_patterns': [''], 'latched_topics': [''], 'rate_limits': [''],
            'load_abort': 3.0, 'load_check_sec': 15.0, 'summary_sec': 60.0,
            'duration_sec': 0.0, 'discovery_wait_sec': 3.0, 'confirm_real_domain': '',
            'enable_down': False, 'cmd_vel_topics': [''],
            'watchdog_ms': 0.0, 'max_linear': 0.0, 'max_angular': 0.0, 'max_age_ms': 0.0,
            'reconnect_min_sec': 1.0, 'reconnect_max_sec': 30.0, 'exit_on_parent_loss': False,
        }
        # 동적 타입: -p confirm_real_domain:=10 처럼 따옴표 없이 숫자로 넣어도 받는다
        descriptor = ParameterDescriptor(dynamic_typing=True)
        for name, value in defaults.items():
            self._node.declare_parameter(name, value, descriptor)

    def _param(self, name):
        return self._node.get_parameter(name).value

    def _list_param(self, name):
        """빈 문자열 자리표시자를 뺀 문자열 목록을 돌려준다."""
        return tuple(item for item in self._param(name) if item)

    def _bridge_yaml_path(self):
        """토픽 목록 YAML 경로. 비우면 이 패키지의 config/mqtt_topics_<로봇>.yaml (DDS 브릿지 YAML 과 별개)."""
        explicit = self._param('bridge_config')
        if explicit:
            return explicit
        try:
            base = os.path.join(get_package_share_directory('cobot_mqtt_bridge'), 'config')
        except PackageNotFoundError:
            # colcon 설치 없이 코드만 복사해 쓰는 경우(pinky1): 소스 배치 기준의 config/
            code_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            base = os.path.join(code_dir, 'config')
        return os.path.join(base, f'mqtt_topics_{self._robot}.yaml')

    def _is_source(self, rule):
        """이 역할이 ROS 를 구독해 MQTT 로 보내는 쪽이면 True (아니면 MQTT 를 받아 ROS 발행)."""
        return (rule.direction == UP) == (self._side == 'robot')

    def _ros_topic(self, rule):
        """이 역할이 ROS 에서 다루는 토픽 이름."""
        return rule.robot_topic if self._side == 'robot' else rule.pc_topic

    def prepare(self):
        """파라미터를 검사하고 규칙을 만든다. 문제가 있으면 사유 문장을, 없으면 빈 문자열."""
        if not self._robot:
            return 'robot 파라미터가 필요하다 (예: -p robot:=pinky1)'
        if self._side not in SIDES:
            return f'side 는 {"/".join(SIDES)} 중 하나여야 한다 (현재 {self._side!r})'
        settings = BridgeSettings(
            pc_domain=int(self._param('pc_domain')),
            topic_prefix=self._param('topic_prefix'),
            exclude_patterns=self._list_param('exclude_patterns'),
            latched_topics=self._list_param('latched_topics'),
            rate_limits=self._list_param('rate_limits'),
        )
        try:
            all_rules = load_rules(self._bridge_yaml_path(), self._robot, settings)
        except (OSError, ValueError, KeyError) as error:
            return f'MQTT 토픽 YAML 을 읽지 못함: {error}'
        enable_down = bool(self._param('enable_down'))
        if not enable_down:
            self._log.info('enable_down:=false 라 down(관제→로봇) 토픽은 중계하지 않는다')
        self._rules = [rule for rule in all_rules if enable_down or rule.direction == UP]
        if not self._rules:
            return '중계할 토픽이 없다'
        for rule in self._rules:
            self._stats[rule.mqtt_topic] = TopicStats()
            self._gates[rule.mqtt_topic] = RateGate(rule.max_rate_hz)
            self._by_mqtt[rule.mqtt_topic] = rule
        prefix, peer = self._param('topic_prefix'), 'pc' if self._side == 'robot' else 'robot'
        self._status_topic = status_topic_name(prefix, self._robot, self._side)
        self._peer_status_topic = status_topic_name(prefix, self._robot, peer)
        return self._check_safety()

    def _check_safety(self):
        """역할에 맞는 발행 도메인 검사와 cmd_vel 보호 검사를 한다."""
        domain = os.environ.get('ROS_DOMAIN_ID', '')
        confirm = str(self._param('confirm_real_domain'))
        sinks = [rule for rule in self._rules if not self._is_source(rule)]
        if self._side == 'pc':
            return check_publish_domain(domain, confirm, self._param('pc_domain'))
        if not sinks:
            return ''
        problem = check_robot_publish_domain(domain, confirm, self._param('robot_domain'))
        if problem:
            return problem
        return self._check_cmd_vel_guard(domain)

    def _check_cmd_vel_guard(self, domain):
        """cmd_vel 중계가 있으면 보호 파라미터를 확인한다. 실제 도메인은 모두 필수."""
        topics = self._list_param('cmd_vel_topics') or ('/cmd_vel',)
        for rule in self._rules:
            if (rule.direction == DOWN and rule.msg_type == TWIST_TYPE
                    and rule.robot_topic in topics):
                self._cmd_vel_topic = rule.mqtt_topic
        if not self._cmd_vel_topic:
            return ''
        watchdog_ms = float(self._param('watchdog_ms'))
        missing = [name for name in ('watchdog_ms', 'max_linear', 'max_angular')
                   if float(self._param(name)) <= 0]
        if missing and domain not in ISOLATED_DOMAINS:
            return ('cmd_vel 보호 파라미터가 없어 실제 로봇 도메인에서는 시작하지 않는다: '
                    + ', '.join(missing))
        if missing:
            names = ', '.join(missing)
            self._log.warning(f'cmd_vel 보호가 꺼져 있다(시험 도메인만 허용): {names}')
        self._watchdog = Watchdog(watchdog_ms)
        return ''

    # ----- ROS -----
    def _qos(self, rule):
        latched = rule.latched
        # 명령(down)은 놓치면 안 되고, 상태(up)의 수신 쪽(발행자)은 reliable, 구독 쪽은 호환 우선
        reliable = latched or rule.direction == DOWN or not self._is_source(rule)
        return QoSProfile(
            depth=QOS_DEPTH,
            reliability=(ReliabilityPolicy.RELIABLE if reliable
                         else ReliabilityPolicy.BEST_EFFORT),
            durability=(DurabilityPolicy.TRANSIENT_LOCAL if latched
                        else DurabilityPolicy.VOLATILE))

    def build_ros(self):
        """역할에 맞는 구독(source)과 발행(sink)을 만든다. 실패 사유를 돌려준다."""
        classes = {}
        for rule in self._rules:
            try:
                classes[rule.mqtt_topic] = get_message(rule.msg_type)
            except (ValueError, AttributeError, ModuleNotFoundError) as error:
                return f'메시지 타입을 불러오지 못함 {rule.msg_type}: {error}'
        if self._side == 'pc':
            problem = self._refuse_existing_publishers()
            if problem:
                return problem
        for rule in self._rules:
            msg_class = classes[rule.mqtt_topic]
            topic = self._ros_topic(rule)
            if self._is_source(rule):
                self._node.create_subscription(
                    msg_class, topic, lambda msg, r=rule: self._on_ros_message(r, msg),
                    self._qos(rule))
            else:
                self._sinks[rule.mqtt_topic] = (
                    self._node.create_publisher(msg_class, topic, self._qos(rule)), msg_class)
        return ''

    def _refuse_existing_publishers(self):
        """실제 도메인에서 up 토픽을 이미 발행하는 쪽이 있으면 이중 발행이 되므로 거부한다."""
        if os.environ.get('ROS_DOMAIN_ID', '') in ISOLATED_DOMAINS:
            return ''
        time.sleep(float(self._param('discovery_wait_sec')))
        taken = [rule.pc_topic for rule in self._rules
                 if rule.direction == UP and self._node.count_publishers(rule.pc_topic) > 0]
        if taken:
            return ('이미 발행자가 있는 토픽이 있어 중단한다 (DDS 브릿지가 켜져 있나?): '
                    + ', '.join(taken))
        return ''

    def _on_ros_message(self, rule, msg):
        """ROS 메시지를 JSON 으로 바꿔 MQTT 로 보낸다 (source 역할)."""
        stats = self._stats[rule.mqtt_topic]
        with self._lock:
            stats.seen += 1
            if not self._gates[rule.mqtt_topic].allow(time.monotonic()):
                stats.dropped += 1
                return
        try:
            payload = encode_envelope(
                rule.msg_type, time.time(), message_to_ordereddict(msg))
        except TypeError as error:
            with self._lock:
                stats.errors += 1
            self._log.error(f'직렬화 실패 {self._ros_topic(rule)}: {error}')
            return
        if rule.latched:
            self._latched_payloads[rule.mqtt_topic] = payload
        if not self._link_up:
            # 끊긴 사이 명령이 쌓였다가 재접속 뒤 한꺼번에 나가면 위험하므로 보내지 않고 버린다
            with self._lock:
                stats.dropped += 1
            return
        self._client.publish(
            rule.mqtt_topic, payload, qos=MQTT_QOS[rule.direction],
            retain=rule.latched)
        with self._lock:
            stats.relayed += 1

    # ----- MQTT -----
    def _status_payload(self, state):
        return json.dumps({'state': state, 'sent_at': time.time(), 'pid': os.getpid()})

    def _on_connect(self, client, userdata, flags, rc):
        self._connect_rc = rc
        if rc == 0:
            reconnected = self._ever_connected
            self._ever_connected = True
            self._link_up = True
            self._log.info(
                f'MQTT {"재접속" if reconnected else "접속"} 성공 '
                f'{self._param("host")}:{self._param("port")}')
            for mqtt_topic, rule in self._by_mqtt.items():
                if not self._is_source(rule):
                    client.subscribe(mqtt_topic, qos=MQTT_QOS[rule.direction])
            client.subscribe(self._peer_status_topic, qos=1)
            client.publish(self._status_topic, self._status_payload('online'), qos=1, retain=True)
            if reconnected:
                # 브로커가 재시작되면 보관 메시지가 사라지므로 래치 토픽의 마지막 값을 다시 올린다
                for mqtt_topic, payload in self._latched_payloads.items():
                    client.publish(mqtt_topic, payload, qos=0, retain=True)
        else:
            self._log.error(f'MQTT 접속 거부 rc={rc} ({mqtt.connack_string(rc)})')
        self._connected.set()

    def _on_disconnect(self, client, userdata, rc):
        self._link_up = False
        if rc != 0:
            self._log.warning(f'MQTT 예기치 않게 끊김 rc={rc}. 재접속을 시도한다')

    def _on_peer_status(self, payload):
        """상대 역할의 상태가 바뀌면 로그에 남긴다."""
        try:
            state = json.loads(payload).get('state', '')
        except (ValueError, AttributeError):
            return
        if state != self._peer_state:
            self._peer_state = state
            # rclpy 로거는 같은 호출 위치에서 로그 수준을 바꿀 수 없어 호출을 나눈다
            if state == 'online':
                self._log.info('상대 역할 상태: online')
            else:
                self._log.warning(f'상대 역할 상태: {state or "알 수 없음"}')

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT 의 JSON 을 ROS 메시지로 되돌려 발행한다 (sink 역할)."""
        if msg.topic == self._peer_status_topic:
            self._on_peer_status(msg.payload)
            return
        entry = self._sinks.get(msg.topic)
        stats = self._stats.get(msg.topic)
        if entry is None or stats is None:
            return
        publisher, msg_class = entry
        rule = self._by_mqtt[msg.topic]
        with self._lock:
            stats.seen += 1
        try:
            data, sent_at = decode_envelope(msg.payload.decode('utf-8'), rule.msg_type)
            if msg.topic == self._cmd_vel_topic:
                data = self._guard_cmd_vel(data, sent_at, stats)
                if data is None:
                    return
            ros_msg = msg_class()
            set_message_fields(ros_msg, data)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            with self._lock:
                stats.errors += 1
            self._log.error(f'수신 변환 실패 {msg.topic}: {error}')
            return
        publisher.publish(ros_msg)
        with self._lock:
            stats.relayed += 1

    def _guard_cmd_vel(self, data, sent_at, stats):
        """cmd_vel 에 오래된 메시지 폐기와 속도 상한을 적용한다. 버리면 None."""
        if is_stale(sent_at, time.time(), float(self._param('max_age_ms'))):
            with self._lock:
                stats.dropped += 1
            self._log.warning('오래된 cmd_vel 을 버렸다')
            return None
        data, clamped = clamp_twist(
            data, float(self._param('max_linear')), float(self._param('max_angular')))
        if clamped:
            self._log.warning('cmd_vel 이 속도 상한을 넘어 줄였다')
        with self._lock:
            self._watchdog.feed(time.monotonic(), not is_zero(data))
        return data

    def connect(self):
        """브로커에 접속하고 네트워크 스레드를 시작한다. 성공하면 True."""
        self._client.reconnect_delay_set(
            min_delay=int(max(1, float(self._param('reconnect_min_sec')))),
            max_delay=int(max(1, float(self._param('reconnect_max_sec')))))
        self._client.will_set(
            self._status_topic, json.dumps({'state': 'offline', 'cause': 'will'}),
            qos=1, retain=True)
        try:
            self._client.connect(
                self._param('host'), int(self._param('port')), int(self._param('keepalive_sec')))
        except OSError as error:
            self._log.error(f'브로커에 닿지 않음: {error}')
            return False
        self._client.loop_start()
        if not self._connected.wait(CONNECT_TIMEOUT_SEC):
            self._log.error('MQTT 접속 확인 시간 초과')
            return False
        return self._connect_rc == 0

    # ----- 안전 정지 -----
    def _publish_zero_cmd_vel(self, reason):
        """cmd_vel 로 0 속도를 한 번 발행한다."""
        publisher, msg_class = self._sinks[self._cmd_vel_topic]
        publisher.publish(msg_class())
        self._log.warning(f'cmd_vel 0 속도 발행: {reason}')

    def _check_watchdog(self, now):
        """워치독이 만료됐으면 0 속도를 발행한다."""
        if self._watchdog is None:
            return
        with self._lock:
            expired = self._watchdog.expired(now)
        if expired:
            self._publish_zero_cmd_vel('워치독 만료')

    def _check_link_safety(self):
        """연결이 끊겼는데 움직이는 중이면 워치독을 기다리지 않고 바로 0 속도를 발행한다."""
        if self._watchdog is None or self._link_up:
            return
        with self._lock:
            moving = self._watchdog.armed
            self._watchdog.disarm()
        if moving:
            self._publish_zero_cmd_vel('MQTT 연결 끊김')

    def _parent_lost(self):
        """exit_on_parent_loss 가 켜져 있고 부모 프로세스가 바뀌었으면 True."""
        return bool(self._param('exit_on_parent_loss')) and os.getppid() != self._parent_pid

    def stop_commands(self):
        """종료 직전에 움직이는 중일 수 있으면 0 속도를 한 번 보낸다."""
        if self._watchdog is not None and self._watchdog.armed:
            self._publish_zero_cmd_vel('종료')
            self._watchdog.disarm()

    # ----- 실행 -----
    def request_stop(self):
        """종료를 요청한다 (시그널 처리용)."""
        self._stop.set()

    def run(self):
        """duration_sec 동안(0 이면 계속) 실행하며 워치독, 부하 감시, 통계 로그를 처리한다."""
        duration = float(self._param('duration_sec'))
        started = time.monotonic()
        next_load = started + float(self._param('load_check_sec'))
        next_summary = started + float(self._param('summary_sec'))
        while rclpy.ok() and not self._stop.is_set():
            now = time.monotonic()
            if duration > 0 and now - started >= duration:
                break
            self._check_watchdog(now)
            self._check_link_safety()
            if self._parent_lost():
                self._log.warning('부모 프로세스가 사라져 종료한다')
                break
            if self._side == 'robot' and now >= next_load:
                next_load = now + float(self._param('load_check_sec'))
                if os.getloadavg()[0] > float(self._param('load_abort')):
                    self._abort_reason = f'1분 load {os.getloadavg()[0]:.2f} 가 한계를 넘어 중단'
                    self._log.error(self._abort_reason)
                    break
            if now >= next_summary:
                next_summary = now + float(self._param('summary_sec'))
                self.log_summary('중간')
            rclpy.spin_once(self._node, timeout_sec=SPIN_TIMEOUT_SEC)

    def log_summary(self, label):
        """토픽별 통계를 남기고 중계한 총 건수를 돌려준다."""
        total = 0
        with self._lock:
            for rule in self._rules:
                stats = self._stats[rule.mqtt_topic]
                total += stats.relayed
                self._log.info(
                    f'요약({label}) {self._side} {rule.direction} {self._ros_topic(rule)} '
                    f'받음 {stats.seen} 중계 {stats.relayed} 버림 {stats.dropped} '
                    f'오류 {stats.errors}')
        if self._watchdog is not None:
            self._log.info(f'요약({label}) cmd_vel 워치독 정지 {self._watchdog.trips}회')
        return total

    def close(self):
        """상태를 offline 으로 알리고 MQTT 연결을 닫는다."""
        if self._link_up:
            info = self._client.publish(
                self._status_topic, json.dumps({'state': 'offline', 'cause': 'exit'}),
                qos=1, retain=True)
            info.wait_for_publish(2.0)
        self._client.disconnect()
        self._client.loop_stop()

    @property
    def abort_reason(self):
        """부하 등으로 스스로 멈춘 사유 (정상 종료면 빈 문자열)."""
        return self._abort_reason


def main(args=None):
    """노드를 실행하고 종료 코드를 돌려준다."""
    rclpy.init(args=args)
    node = Node('mqtt_bridge')
    bridge = MqttBridge(node)
    log = node.get_logger()
    try:
        problem = bridge.prepare() or bridge.build_ros()
        if problem:
            log.error(problem)
            return EXIT_SETUP_FAILED
        log.info(f'시작 ROS_DOMAIN_ID={os.environ.get("ROS_DOMAIN_ID", "(없음)")}')
        signal.signal(signal.SIGTERM, lambda *_: bridge.request_stop())
        if not bridge.connect():
            return EXIT_SETUP_FAILED
        try:
            bridge.run()
        except KeyboardInterrupt:
            log.info('중단 요청. 정리한다')
        bridge.stop_commands()
        total = bridge.log_summary('최종')
        return EXIT_OK if total and not bridge.abort_reason else EXIT_NOTHING
    finally:
        bridge.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
