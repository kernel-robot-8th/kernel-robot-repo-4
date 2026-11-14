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
MQTT 학습 4단계 (갈래 B): 두 장비 사이 왕복 시간(RTT)을 ping/pong 으로 재는 스크립트.

왜 필요한가: 3a 에서는 두 PC 의 시계가 달라서 단방향 지연을 정확히 못 쟀다. ping 이 보낸
시각을 pong 이 그대로 돌려주면, ping 쪽 한 시계로만 재므로 시계 오차가 끼지 않는다.

역할:
  ping: --rate-hz 로 메시지를 보내고, 돌아온 메시지에서 RTT(ms)를 계산한다.
  pong: 받은 메시지를 내용 그대로 되돌려 보낸다. 그 외에는 아무것도 하지 않는다.

전송 방식 (--transport):
  mqtt: 브로커를 거친다 (paho-mqtt 1.6.x).
  ros:  ROS 2 DDS 로 직접 연결한다 (브릿지 없음). std_msgs/String 을 쓴다.

결과는 로그 한 줄 'RESULT {json}' 으로도 남긴다.

종료 코드: 0 = 정상, 1 = ping 이 한 건도 돌려받지 못함, 2 = 설정·접속 오류.

안전:
  - ROS 토픽 이름은 /bench/ 로 시작해야 한다. 구동 토픽에는 쓰지 않는다.
  - ROS_DOMAIN_ID 는 바꾸지 않는다. 호출한 셸의 값을 그대로 쓰고 시작할 때 로그로 남긴다.
  - 항상 --duration 이 있어 무한히 돌지 않는다.

실행 (ROS 2 Jazzy 환경, paho-mqtt 1.6.x 기준):
    python3 scripts/spikes/mqtt/tools/mqtt_bench_rtt.py --transport mqtt --role pong --duration 40
    python3 scripts/spikes/mqtt/tools/mqtt_bench_rtt.py --transport mqtt --role ping --duration 20
"""

import argparse
import json
import logging
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt

EXIT_OK = 0
EXIT_NO_REPLY = 1
EXIT_SETUP_FAILED = 2

ROS_TOPIC_PREFIX = '/bench/'
SPIN_TIMEOUT_SEC = 0.01
DRAIN_SEC = 1.5
MS_PER_SEC = 1000.0
DISCOVERY_WAIT_SEC = 15.0

LOGGER = logging.getLogger('mqtt_bench_rtt')


def parse_args(argv=None):
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='ping/pong RTT 측정')
    parser.add_argument('--transport', choices=('mqtt', 'ros'), required=True)
    parser.add_argument('--role', choices=('ping', 'pong'), required=True)
    parser.add_argument('--rate-hz', type=float, default=5.0, help='ping 발행율 [Hz]')
    parser.add_argument('--duration', type=float, default=20.0, help='실행 시간 [s]')
    parser.add_argument('--payload-bytes', type=int, default=64, help='메시지 채움 크기')
    parser.add_argument('--warmup', type=float, default=3.0, help='ping 시작 전 대기 [s]')
    parser.add_argument('--host', default='127.0.0.1', help='MQTT 브로커 주소')
    parser.add_argument('--port', type=int, default=1883, help='MQTT 브로커 포트')
    parser.add_argument('--keepalive', type=int, default=30, help='MQTT keepalive [s]')
    parser.add_argument('--mqtt-qos', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--mqtt-ping-topic', default='mqtt_learning/bench/ping')
    parser.add_argument('--mqtt-pong-topic', default='mqtt_learning/bench/pong')
    parser.add_argument('--ros-ping-topic', default='/bench/ping')
    parser.add_argument('--ros-pong-topic', default='/bench/pong')
    return parser.parse_args(argv)


def percentile(sorted_values, fraction):
    """정렬된 값에서 fraction(0~1) 위치의 값을 돌려준다. 비어 있으면 0 이다."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def make_payload(seq, payload_bytes):
    """보낸 시각과 순번을 담은 JSON 문자열을 만든다. 시각은 ping 프로세스의 단조 시계다."""
    return json.dumps({'seq': seq, 't0': time.perf_counter(), 'pad': 'x' * payload_bytes})


class Stats:
    """ping 이 받은 RTT 를 모으는 작은 클래스. 콜백 스레드와 메인이 함께 쓰므로 잠근다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rtts_ms = []
        self.sent = 0

    def add_reply(self, text):
        """돌아온 메시지에서 RTT 를 계산해 저장한다. 깨진 메시지는 무시한다."""
        arrived = time.perf_counter()
        try:
            t0 = float(json.loads(text)['t0'])
        except (ValueError, KeyError, TypeError):
            return
        with self._lock:
            self._rtts_ms.append((arrived - t0) * MS_PER_SEC)

    def result(self, args):
        """결과 사전을 만든다."""
        with self._lock:
            values = sorted(self._rtts_ms)
        received = len(values)
        return {
            'transport': args.transport, 'sent': self.sent, 'received': received,
            'lost': self.sent - received,
            'p50_ms': round(percentile(values, 0.50), 3),
            'p95_ms': round(percentile(values, 0.95), 3),
            'max_ms': round(values[-1], 3) if values else 0.0,
            'mean_ms': round(sum(values) / received, 3) if received else 0.0,
        }


def run_mqtt(args, stats):
    """MQTT 로 ping 또는 pong 을 실행한다. 접속에 실패하면 False 를 돌려준다."""
    listen = args.mqtt_pong_topic if args.role == 'ping' else args.mqtt_ping_topic
    connected = threading.Event()
    state = {'rc': None}
    client = mqtt.Client(clean_session=True)

    def on_connect(cli, userdata, flags, rc):
        """접속(재접속 포함) 때마다 구독을 건다."""
        state['rc'] = rc
        if rc == 0:
            cli.subscribe(listen, qos=args.mqtt_qos)
        connected.set()

    def on_message(cli, userdata, msg):
        """받은 메시지 처리. ping 은 RTT 를 기록하고, pong 은 내용을 그대로 돌려보낸다."""
        if args.role == 'ping':
            stats.add_reply(msg.payload.decode('utf-8', errors='replace'))
        else:
            cli.publish(args.mqtt_pong_topic, msg.payload, qos=args.mqtt_qos)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, args.keepalive)
    except OSError as error:
        LOGGER.error('브로커에 닿지 않음: %s', error)
        return False
    client.loop_start()
    if not connected.wait(5.0) or state['rc'] != 0:
        LOGGER.error('MQTT 접속 실패')
        client.loop_stop()
        return False
    if args.role == 'ping':
        time.sleep(args.warmup)
        end = time.monotonic() + args.duration
        interval = 1.0 / args.rate_hz
        while time.monotonic() < end:
            client.publish(args.mqtt_ping_topic, make_payload(stats.sent, args.payload_bytes),
                           qos=args.mqtt_qos)
            stats.sent += 1
            time.sleep(interval)
        time.sleep(DRAIN_SEC)
    else:
        time.sleep(args.duration)
    client.disconnect()
    client.loop_stop()
    return True


def run_ros(args, stats):
    """ROS 2 DDS 로 ping 또는 pong 을 실행한다. 설정 오류면 False 를 돌려준다."""
    import rclpy
    from std_msgs.msg import String

    for topic in (args.ros_ping_topic, args.ros_pong_topic):
        if not topic.startswith(ROS_TOPIC_PREFIX):
            LOGGER.error('ROS 토픽은 %s 로 시작해야 한다: %s', ROS_TOPIC_PREFIX, topic)
            return False
    rclpy.init()
    node = rclpy.create_node(f'bench_rtt_{args.role}')
    try:
        if args.role == 'ping':
            publisher = node.create_publisher(String, args.ros_ping_topic, 10)
            node.create_subscription(
                String, args.ros_pong_topic, lambda msg: stats.add_reply(msg.data), 10)
            # 상대(pong)가 발견될 때까지 기다린다. 안 기다리면 첫 메시지들이 허공으로 간다.
            wait_end = time.monotonic() + DISCOVERY_WAIT_SEC
            while (publisher.get_subscription_count() == 0 and time.monotonic() < wait_end):
                rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
            if publisher.get_subscription_count() == 0:
                LOGGER.error('pong 을 찾지 못함 (%.0f s)', DISCOVERY_WAIT_SEC)
                return False
            time.sleep(args.warmup)
            end = time.monotonic() + args.duration
            interval = 1.0 / args.rate_hz
            next_send = time.monotonic()
            while rclpy.ok() and time.monotonic() < end:
                if time.monotonic() >= next_send:
                    publisher.publish(String(data=make_payload(stats.sent, args.payload_bytes)))
                    stats.sent += 1
                    next_send += interval
                rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
            drain_end = time.monotonic() + DRAIN_SEC
            while time.monotonic() < drain_end:
                rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
        else:
            publisher = node.create_publisher(String, args.ros_pong_topic, 10)
            node.create_subscription(
                String, args.ros_ping_topic, lambda msg: publisher.publish(msg), 10)
            end = time.monotonic() + args.duration
            while rclpy.ok() and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return True


def main(argv=None):
    """역할에 맞게 실행하고 종료 코드를 돌려준다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    LOGGER.info('시작 transport=%s role=%s ROS_DOMAIN_ID=%s', args.transport, args.role,
                os.environ.get('ROS_DOMAIN_ID', '(없음)'))
    stats = Stats()
    runner = run_mqtt if args.transport == 'mqtt' else run_ros
    if not runner(args, stats):
        return EXIT_SETUP_FAILED
    if args.role == 'pong':
        LOGGER.info('pong 종료')
        return EXIT_OK
    result = stats.result(args)
    LOGGER.info('RESULT %s', json.dumps(result))
    return EXIT_OK if result['received'] else EXIT_NO_REPLY


if __name__ == '__main__':
    sys.exit(main())
