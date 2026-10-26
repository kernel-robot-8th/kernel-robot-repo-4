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
S1 스파이크: 한 프로세스에서 rclpy Context 두 개(ROS_DOMAIN_ID 10, 12)를 쓸 수 있는지 본다.

왜 필요한가: D2 추천안은 핑키 온보드 가드 하나가 도메인 10(관제 명령·상태)과
도메인 12(Nav2)를 동시에 잇는 것이다. 그러려면 한 프로세스가 rclpy Context 를 두 개 열고,
두 도메인이 서로 섞이지 않아야 한다. 이 스크립트가 그것을 로봇 없이 확인한다.

하는 일:
  1. 가드 역할 Context 두 개(도메인 10, 12)와, 도메인마다 상대 역할 Context 하나씩을 연다.
     모두 한 프로세스 안이다. 상대 역할은 fms_core(도메인 10)·Nav2(도메인 12) 자리다.
  2. 모두 같은 토픽 이름으로 발행·구독한다. 내용에 '도메인:역할' 표시를 넣는다.
  3. 몇 초 동안 돌린다.
  4. 판정: 각자 같은 도메인의 상대 메시지를 받았고, 다른 도메인 메시지는 0건이어야 통과다.

종료 코드: 0 = 통과, 1 = 실패(새거나 못 받음), 2 = 환경 오류(rclpy 없음 등).

안전:
  - 로봇·장치를 열지 않는다. 로봇 토픽을 발행하지 않는다 (토픽 이름은 /spike/... 이다).
  - 기본으로 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST 로 돈다. 그래서 현장 망에 패킷을
    내보내지 않는다. 망을 거쳐 보려면 --allow-network 를 준다 (팀 확인 뒤에만).
  - 셸의 ROS_DOMAIN_ID 를 바꾸지 않는다. 도메인 번호는 이 프로세스의 Context 에만 준다.
  - 기본 도메인은 개발 전용 번호 100·101 이다 (초안). 실물 번호 10·12 는 인자로 적을 때만
    쓴다. 실물 번호와 --allow-network 를 함께 주면 돌지 않는다 (종료 코드 2).

자리: 팀 규칙 CLAUDE.md §2 의 scripts/(보조 스크립트). ROS 노드 패키지가 아니다.
  scripts/spikes/ 를 구조도에 적을지는 docs/fms_interfaces.md §20 열린 질문이다.

실행 (ROS 2 Jazzy 환경):
    source /opt/ros/jazzy/setup.bash
    python3 scripts/spikes/two_domain_context_check.py
    echo $?
D2 의 실물 번호로 확인할 때 (한 PC 안, LOCALHOST):
    python3 scripts/spikes/two_domain_context_check.py --domain-a 10 --domain-b 12
"""

import argparse
import json
import logging
import os
import sys
import time

LOGGER = logging.getLogger('two_domain_context_check')

TOPIC = '/spike/two_domain/ping'
ROLES = ('guard', 'peer')
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV = 2
# SR-19 의 실물 도메인 (10: 실물 구동, 12: Nav2). 기본값으로 쓰지 않는다.
PHYSICAL_DOMAINS = (10, 12)
# 개발 전용 기본값 (초안). 100 은 D2 추천안의 '개발·시뮬 전용', 101 은 이 스파이크에서만 쓴다.
DEFAULT_DOMAIN_A = 100
DEFAULT_DOMAIN_B = 101


def parse_args(argv):
    """명령줄 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='rclpy Context 두 개(도메인 2개) 격리 스파이크')
    parser.add_argument('--domain-a', type=int, default=DEFAULT_DOMAIN_A,
                        help='첫 도메인. D2 실물 확인은 10 (SR-19: 실물 구동)')
    parser.add_argument('--domain-b', type=int, default=DEFAULT_DOMAIN_B,
                        help='둘째 도메인. D2 실물 확인은 12 (SR-19: Nav2)')
    parser.add_argument('--timeout', type=float, default=8.0, help='최대 대기 [s]')
    parser.add_argument('--min-messages', type=int, default=5,
                        help='같은 도메인 상대에게서 받아야 할 수 [개]')
    parser.add_argument('--settle', type=float, default=1.0,
                        help='모두 다 받은 뒤 누수를 더 지켜볼 시간 [s]')
    parser.add_argument('--period', type=float, default=0.1, help='발행 주기 [s]')
    parser.add_argument('--allow-network', action='store_true',
                        help='LOCALHOST 제한을 풀고 망으로도 발견한다 (팀 확인 뒤에만)')
    return parser.parse_args(argv)


class Probe:
    """Context 하나와 그 안의 노드·발행자·구독자를 묶는다."""

    def __init__(self, ros, domain_id, role):
        self.domain_id = domain_id
        self.role = role
        self.sent = 0
        self.same_domain_peer = 0
        self.self_echo = 0
        self.foreign = 0
        self.unknown = 0
        self._ros = ros
        self.context = ros['Context']()
        ros['rclpy'].init(context=self.context, domain_id=domain_id)
        self.node = ros['rclpy'].create_node(
            'two_domain_{}_d{}'.format(role, domain_id), context=self.context,
            enable_rosout=False, start_parameter_services=False)
        self.publisher = self.node.create_publisher(ros['String'], TOPIC, 10)
        self.subscription = self.node.create_subscription(
            ros['String'], TOPIC, self._on_message, 10)
        self.executor = ros['Executor'](context=self.context)
        self.executor.add_node(self.node)

    def publish(self):
        """'도메인:역할:번호' 표시를 넣은 메시지를 하나 낸다."""
        message = self._ros['String']()
        message.data = '{}:{}:{}'.format(self.domain_id, self.role, self.sent)
        self.publisher.publish(message)
        self.sent += 1

    def spin_once(self, timeout_sec):
        """한 번 돌린다."""
        self.executor.spin_once(timeout_sec=timeout_sec)

    def _on_message(self, message):
        parts = message.data.split(':')
        if len(parts) != 3 or not parts[0].isdigit():
            self.unknown += 1
        elif int(parts[0]) != self.domain_id:
            self.foreign += 1
        elif parts[1] == self.role:
            self.self_echo += 1
        else:
            self.same_domain_peer += 1

    def summary(self):
        """판정에 쓸 숫자를 사전으로 돌려준다."""
        return {
            'domain_id': self.domain_id,
            'role': self.role,
            'reported_domain_id': self.context.get_domain_id(),
            'sent': self.sent,
            'same_domain_peer_received': self.same_domain_peer,
            'self_echo_received': self.self_echo,
            'foreign_received': self.foreign,
            'unknown_received': self.unknown,
        }

    def close(self):
        """만든 것을 정리한다."""
        self.executor.shutdown()
        self.node.destroy_node()
        if self.context.ok():
            self._ros['rclpy'].shutdown(context=self.context)


def run(args, ros):
    """Context 넷(도메인 둘 × 역할 둘)을 열고 돌려 결과 사전을 돌려준다."""
    probes = []
    try:
        for domain_id in (args.domain_a, args.domain_b):
            for role in ROLES:
                probes.append(Probe(ros, domain_id, role))
        start = time.monotonic()
        next_publish = start
        done_at = None
        while time.monotonic() - start < args.timeout:
            now = time.monotonic()
            if now >= next_publish:
                for probe in probes:
                    probe.publish()
                next_publish = now + args.period
            for probe in probes:
                probe.spin_once(timeout_sec=0.005)
            enough = all(probe.same_domain_peer >= args.min_messages for probe in probes)
            if enough and done_at is None:
                done_at = time.monotonic()
            if done_at is not None and time.monotonic() - done_at >= args.settle:
                break
        return {
            'elapsed_s': round(time.monotonic() - start, 3),
            'discovery_range': os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE', ''),
            'rmw': os.environ.get('RMW_IMPLEMENTATION', '(기본값)'),
            'probes': [probe.summary() for probe in probes],
        }
    finally:
        for probe in reversed(probes):
            probe.close()


def judge(result, min_messages):
    """결과를 판정해 (통과 여부, 이유 목록) 을 돌려준다."""
    reasons = []
    for item in result['probes']:
        name = 'domain {} {}'.format(item['domain_id'], item['role'])
        if item['reported_domain_id'] != item['domain_id']:
            reasons.append('{}: Context 가 도메인 {} 을 쓴다'.format(
                name, item['reported_domain_id']))
        if item['same_domain_peer_received'] < min_messages:
            reasons.append('{}: 같은 도메인 상대 메시지를 {}건만 받았다 (필요 {}건)'.format(
                name, item['same_domain_peer_received'], min_messages))
        if item['foreign_received'] or item['unknown_received']:
            reasons.append('{}: 다른 도메인 메시지 {}건, 알 수 없는 메시지 {}건이 들어왔다'.format(
                name, item['foreign_received'], item['unknown_received']))
    return not reasons, reasons


def main(argv=None):
    """스파이크를 돌리고 종료 코드를 돌려준다."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.domain_a == args.domain_b:
        LOGGER.error('두 도메인 번호가 같다: %d', args.domain_a)
        return EXIT_ENV
    physical = [d for d in (args.domain_a, args.domain_b) if d in PHYSICAL_DOMAINS]
    if args.allow_network and physical:
        LOGGER.error('실물 도메인 %s 에서는 --allow-network 를 쓰지 않는다. '
                     '현장 망 확인은 실측(D18) 계획으로 따로 한다.', physical)
        return EXIT_ENV
    if not args.allow_network:
        # rcl 이 Context 를 열 때 이 값을 읽는다. 그래서 init 전에 이 프로세스 안에서만 바꾼다.
        os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
        os.environ.pop('ROS_STATIC_PEERS', None)
    try:
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from std_msgs.msg import String
    except ImportError as error:
        LOGGER.error('rclpy 를 불러오지 못했다. ROS 2 Jazzy 를 source 했는지 본다: %s', error)
        return EXIT_ENV
    ros = {'rclpy': rclpy, 'Context': Context, 'Executor': SingleThreadedExecutor,
           'String': String}
    try:
        result = run(args, ros)
    except Exception as error:  # 환경 문제(초기화 실패 등)를 실패(누수)와 나눈다.
        LOGGER.error('Context 를 열거나 돌리지 못했다: %r', error)
        return EXIT_ENV
    passed, reasons = judge(result, args.min_messages)
    result['passed'] = passed
    result['reasons'] = reasons
    LOGGER.info('결과 %s', json.dumps(result, ensure_ascii=False))
    if passed:
        LOGGER.info('통과: 도메인마다 주고받았고, 두 도메인이 서로 새지 않았다.')
        return EXIT_PASS
    for reason in reasons:
        LOGGER.error('실패: %s', reason)
    return EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
