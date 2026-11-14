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
MQTT 학습 4단계 (갈래 A): 합성 메시지를 발행하고(source) 받은 쪽에서 지연을 재는(sink) 스크립트.

왜 필요한가: DDS 브릿지와 MQTT 중계의 지연·수신율을 같은 조건에서 비교하려면, 같은 메시지를
일정한 속도로 흘려 보내고 도착 시각을 재야 한다. 한 PC 안에서 돌리면 시계가 하나라서
header.stamp 와 수신 시각의 차이가 곧 단방향 지연이다.

역할:
  source: header.stamp 에 발행 시각을, header.frame_id 에 순번을 넣어 --rate-hz 로 발행한다.
  sink:   받을 때마다 지연(ms)을 기록하고, 끝나면 p50/p95/최대, 수신 건수, 누락, 중복을 낸다.

메시지: twist = geometry_msgs/msg/TwistStamped (/cmd_vel 모양, 작음),
        laser = sensor_msgs/msg/LaserScan (/scan 모양, 크기는 --laser-points 로 정함),
        odom = nav_msgs/msg/Odometry (/odom 모양, 공분산 포함).

결과는 로그 한 줄 'RESULT {json}' 으로도 남겨서 러너가 읽는다.

종료 코드: 0 = 정상, 2 = 설정 오류. 항상 --duration 이 있어 무한히 돌지 않는다.

안전:
  - 로봇·장치를 열지 않는다. 토픽 이름은 --topic 이 /bench/ 나 /mqtt_test/bench/ 로
    시작하지 않으면 실행하지 않는다.
  - ROS_DOMAIN_ID 는 바꾸지 않는다. 호출한 셸의 값을 그대로 쓴다.

실행 (ROS 2 Jazzy 환경):
    ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
      python3 scripts/spikes/mqtt/tools/mqtt_bench_stream.py --role sink --msg twist \
      --topic /bench/twist --duration 10
"""

import argparse
import json
import logging
import math
import os
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

EXIT_OK = 0
EXIT_SETUP_FAILED = 2

MSG_TYPES = {
    'twist': 'geometry_msgs/msg/TwistStamped',
    'laser': 'sensor_msgs/msg/LaserScan',
    'odom': 'nav_msgs/msg/Odometry',
}
ALLOWED_PREFIXES = ('/bench/', '/mqtt_test/bench/')
SPIN_TIMEOUT_SEC = 0.01
NS_PER_MS = 1.0e6
NS_PER_SEC = 1.0e9
TWIST_LINEAR_X = 0.1
LASER_RANGE_MIN = 0.1
LASER_RANGE_MAX = 10.0
LASER_RANGE_VALUE = 1.0

LOGGER = logging.getLogger('mqtt_bench_stream')


def parse_args(argv=None):
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='중계 비교용 합성 메시지 source/sink')
    parser.add_argument('--role', choices=('source', 'sink'), required=True)
    parser.add_argument('--msg', choices=tuple(MSG_TYPES), required=True)
    parser.add_argument('--topic', required=True, help='/bench/... 또는 /mqtt_test/bench/...')
    parser.add_argument('--rate-hz', type=float, default=10.0, help='source 발행율 [Hz]')
    parser.add_argument('--duration', type=float, default=10.0, help='실행 시간 [s]')
    parser.add_argument('--laser-points', type=int, default=360, help='laser 의 점 개수')
    parser.add_argument('--qos', choices=('reliable', 'best_effort'), default='reliable')
    parser.add_argument('--depth', type=int, default=10, help='QoS depth')
    return parser.parse_args(argv)


def percentile(sorted_values, fraction):
    """정렬된 값에서 fraction(0~1) 위치의 값을 돌려준다. 비어 있으면 0 이다."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def make_qos(args):
    """인자로 QoSProfile 을 만든다."""
    reliability = (
        ReliabilityPolicy.RELIABLE if args.qos == 'reliable' else ReliabilityPolicy.BEST_EFFORT)
    return QoSProfile(depth=args.depth, reliability=reliability)


class Source(Node):
    """일정한 속도로 합성 메시지를 발행하는 노드."""

    def __init__(self, args):
        super().__init__('bench_source')
        self._args = args
        self._msg_class = get_message(MSG_TYPES[args.msg])
        self._publisher = self.create_publisher(self._msg_class, args.topic, make_qos(args))
        self.published = 0
        self._started = None
        self.elapsed = 0.0
        self.create_timer(1.0 / args.rate_hz, self._tick)

    def _tick(self):
        """타이머마다 한 건 발행한다. 발행 시각은 메시지 헤더에 넣는다."""
        if self._started is None:
            self._started = time.monotonic()
        msg = self._msg_class()
        msg.header.stamp = self.get_clock().now().to_msg()
        # 순번을 frame_id 에 넣는다. JSON 중계를 거쳐도 문자열은 그대로 보존된다.
        msg.header.frame_id = str(self.published)
        if self._args.msg == 'twist':
            msg.twist.linear.x = TWIST_LINEAR_X
        elif self._args.msg == 'odom':
            msg.child_frame_id = 'base_footprint'
            msg.twist.twist.linear.x = TWIST_LINEAR_X
        else:
            points = self._args.laser_points
            msg.angle_min = 0.0
            msg.angle_max = 2.0 * math.pi
            msg.angle_increment = 2.0 * math.pi / points
            msg.range_min = LASER_RANGE_MIN
            msg.range_max = LASER_RANGE_MAX
            msg.ranges = [LASER_RANGE_VALUE] * points
        self._publisher.publish(msg)
        self.published += 1
        self.elapsed = time.monotonic() - self._started


class Sink(Node):
    """받은 메시지의 지연을 기록하는 노드."""

    def __init__(self, args):
        super().__init__('bench_sink')
        self._msg_class = get_message(MSG_TYPES[args.msg])
        self.latencies_ms = []
        self.seq_counts = {}
        self.create_subscription(self._msg_class, args.topic, self._on_message, make_qos(args))

    def _on_message(self, msg):
        """수신 시각에서 헤더 발행 시각을 빼 지연을 구한다."""
        now_ns = self.get_clock().now().nanoseconds
        stamp_ns = msg.header.stamp.sec * NS_PER_SEC + msg.header.stamp.nanosec
        self.latencies_ms.append((now_ns - stamp_ns) / NS_PER_MS)
        try:
            seq = int(msg.header.frame_id)
        except ValueError:
            return
        self.seq_counts[seq] = self.seq_counts.get(seq, 0) + 1


def source_result(node):
    """발행 쪽(source) 결과를 사전으로 만든다."""
    rate = node.published / node.elapsed if node.elapsed > 0 else 0.0
    return {'role': 'source', 'published': node.published,
            'elapsed_s': round(node.elapsed, 3), 'achieved_hz': round(rate, 2)}


def sink_result(node):
    """수신 쪽(sink) 결과를 사전으로 만든다."""
    values = sorted(node.latencies_ms)
    received = len(values)
    unique = len(node.seq_counts)
    expected = (max(node.seq_counts) + 1) if node.seq_counts else 0
    return {
        'role': 'sink', 'received': received, 'unique': unique,
        'duplicates': received - unique, 'missing': expected - unique,
        'p50_ms': round(percentile(values, 0.50), 3),
        'p95_ms': round(percentile(values, 0.95), 3),
        'max_ms': round(values[-1], 3) if values else 0.0,
        'mean_ms': round(sum(values) / received, 3) if received else 0.0,
    }


def main(argv=None):
    """역할에 맞게 실행하고 결과를 로그로 남긴다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    if not args.topic.startswith(ALLOWED_PREFIXES):
        LOGGER.error('--topic 은 %s 중 하나로 시작해야 한다', ALLOWED_PREFIXES)
        return EXIT_SETUP_FAILED
    LOGGER.info('시작 role=%s msg=%s ROS_DOMAIN_ID=%s', args.role, args.msg,
                os.environ.get('ROS_DOMAIN_ID', '(없음)'))
    rclpy.init()
    node = Source(args) if args.role == 'source' else Sink(args)
    deadline = time.monotonic() + args.duration
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
        result = source_result(node) if args.role == 'source' else sink_result(node)
        LOGGER.info('RESULT %s', json.dumps(result))
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
