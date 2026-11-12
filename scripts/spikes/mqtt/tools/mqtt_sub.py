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
MQTT 학습 2단계: paho-mqtt 로 메시지를 구독하는 스크립트.

왜 필요한가: 재접속과 QoS 차이를 코드로 관찰한다. 특히 지속 세션(--persistent-session)이면
구독자가 끊겨 있던 사이 발행된 QoS 1 메시지를 재접속 뒤에 받는지 볼 수 있다.

하는 일:
  1. 브로커에 접속하고, on_connect 안에서 구독한다 (재접속 때 구독이 다시 걸리도록).
  2. 수신한 메시지의 'seq=<순번>' 을 읽어 누락·중복을 센다.
  3. --count 건을 받거나 --duration 초가 지나면 요약을 남기고 끝낸다.
     항상 시간 제한이 있어서 백그라운드에 남지 않는다.

종료 코드: 0 = 정상 종료, 1 = --count 만큼 받지 못함, 2 = 접속 실패.

안전:
  - ROS 와 로봇을 쓰지 않는다. 기본 토픽은 mqtt_learning/ 아래의 학습용 이름이다.
  - 기본 브로커는 127.0.0.1 이다. 공개 브로커나 LAN 주소는 인자로 적을 때만 쓴다.
  - 지속 세션은 브로커에 세션을 남긴다. 시험이 끝나면 같은 --client-id 로
    --persistent-session 없이 한 번 접속해서 세션을 지운다.

실행 (paho-mqtt 1.6.x 기준):
    python3 scripts/spikes/mqtt/tools/mqtt_sub.py --count 10 --qos 1
    # 지속 세션 (1) 구독만 걸고 종료 → (2) 그 사이 발행 → (3) 다시 접속해 밀린 것 받기
    python3 scripts/spikes/mqtt/tools/mqtt_sub.py --persistent-session \
        --client-id spike_sub --duration 2
"""

import argparse
import logging
import re
import sys
import threading

import paho.mqtt.client as mqtt

EXIT_OK = 0
EXIT_SHORT = 1
EXIT_CONNECT_FAILED = 2

SEQ_PATTERN = re.compile(r'seq=(\d+)')

LOGGER = logging.getLogger('mqtt_sub')


def parse_args(argv=None):
    """명령행 인자를 읽는다. 값은 코드에 박아 두지 않고 모두 여기서 받는다."""
    parser = argparse.ArgumentParser(description='MQTT 학습용 구독기')
    parser.add_argument('--host', default='127.0.0.1', help='브로커 주소')
    parser.add_argument('--port', type=int, default=1883, help='브로커 포트')
    parser.add_argument('--topic', default='mqtt_learning/spike/data', help='구독 토픽')
    parser.add_argument('--qos', type=int, choices=(0, 1, 2), default=0, help='구독 QoS')
    parser.add_argument('--keepalive', type=int, default=30, help='keepalive [s]')
    parser.add_argument('--client-id', default='', help='클라이언트 ID (지속 세션이면 필수)')
    parser.add_argument('--count', type=int, default=0,
                        help='이만큼 받으면 끝냄 (0 이면 건수로는 끝내지 않음)')
    parser.add_argument('--duration', type=float, default=10.0,
                        help='최대 실행 시간 [s]. 백그라운드에 남지 않게 항상 제한한다')
    parser.add_argument('--persistent-session', action='store_true',
                        help='clean_session=False. 끊긴 동안의 QoS 1·2 메시지를 브로커가 보관')
    parser.add_argument('--reconnect-min', type=float, default=1.0, help='재접속 최소 대기 [s]')
    parser.add_argument('--reconnect-max', type=float, default=10.0, help='재접속 최대 대기 [s]')
    parser.add_argument('--will-topic', default='', help='유언(LWT) 토픽. 비우면 사용 안 함')
    parser.add_argument('--will-payload', default='offline', help='유언 내용')
    parser.add_argument('--connect-timeout', type=float, default=5.0,
                        help='첫 접속 확인을 기다리는 시간 [s]')
    args = parser.parse_args(argv)
    if args.persistent_session and not args.client_id:
        # 지속 세션은 client-id 로 세션을 찾는다. 자동 생성 ID 는 매번 달라 세션을 못 이어 받는다.
        parser.error('--persistent-session 은 --client-id 가 필요하다')
    return args


class Subscriber:
    """paho 클라이언트를 감싸 수신 통계를 모아 두는 작은 클래스."""

    def __init__(self, args):
        self._args = args
        self._client = mqtt.Client(
            client_id=args.client_id, clean_session=not args.persistent_session)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        # 끊겼을 때 paho 가 알아서 다시 붙게 하되, 대기 시간은 인자로 조절한다.
        self._client.reconnect_delay_set(args.reconnect_min, args.reconnect_max)
        if args.will_topic:
            # 유언은 connect 전에 등록해야 한다. 비정상 종료일 때만 브로커가 대신 발행한다.
            self._client.will_set(args.will_topic, args.will_payload, qos=1)
        self._connected = threading.Event()
        self._connect_rc = None
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._seq_counts = {}
        self._received = 0

    def _on_connect(self, client, userdata, flags, rc):
        """접속(재접속 포함)할 때마다 불린다. 구독은 여기서 걸어야 재접속 뒤에도 유지된다."""
        self._connect_rc = rc
        if rc == 0:
            # session present 가 1 이면 브로커가 이전 세션(구독·밀린 메시지)을 기억하고 있다.
            LOGGER.info('접속 성공 session_present=%s', flags.get('session present'))
            client.subscribe(self._args.topic, qos=self._args.qos)
        else:
            LOGGER.error('접속 거부 rc=%d (%s)', rc, mqtt.connack_string(rc))
        self._connected.set()

    def _on_disconnect(self, client, userdata, rc):
        """끊길 때 불린다. rc 0 이면 우리가 끊은 것이고, 아니면 예기치 않은 끊김이라 재접속을 시도한다."""
        if rc == 0:
            LOGGER.info('정상 종료')
        else:
            LOGGER.warning('예기치 않게 끊김 rc=%d, 재접속 시도 중', rc)

    def _on_message(self, client, userdata, msg):
        """메시지가 오면 불린다. 네트워크 스레드를 막지 않게 세기만 하고 바로 돌아간다."""
        text = msg.payload.decode('utf-8', errors='replace')
        found = SEQ_PATTERN.search(text)
        with self._lock:
            self._received += 1
            if found:
                seq = int(found.group(1))
                self._seq_counts[seq] = self._seq_counts.get(seq, 0) + 1
            received = self._received
        LOGGER.info('수신 %s qos=%d retain=%d: %s', msg.topic, msg.qos, msg.retain, text)
        if self._args.count and received >= self._args.count:
            self._done.set()

    def connect(self):
        """접속하고 네트워크 스레드를 시작한다. 성공하면 True 를 돌려준다."""
        try:
            self._client.connect(self._args.host, self._args.port, self._args.keepalive)
        except OSError as error:
            LOGGER.error('브로커에 닿지 않음: %s', error)
            return False
        self._client.loop_start()
        if not self._connected.wait(self._args.connect_timeout):
            LOGGER.error('접속 확인 시간 초과')
            return False
        return self._connect_rc == 0

    def wait(self):
        """끝낼 조건(건수 또는 시간)을 기다린다."""
        self._done.wait(self._args.duration)

    def close(self):
        """정상 종료한다. disconnect 를 불러야 브로커가 유언(LWT)을 보내지 않는다."""
        self._client.disconnect()
        self._client.loop_stop()

    def summary(self):
        """수신 요약을 남기고 (받은 수, 누락 수, 중복 수)를 돌려준다."""
        with self._lock:
            seqs = sorted(self._seq_counts)
            duplicates = sum(count - 1 for count in self._seq_counts.values())
            received = self._received
        # 누락은 '받은 것 중 가장 작은~큰 순번 사이의 빈 곳' 으로 센다. 끝쪽 누락은 알 수 없다.
        missing = [n for n in range(seqs[0], seqs[-1] + 1) if n not in self._seq_counts] \
            if seqs else []
        LOGGER.info('요약: 수신 %d건, 순번 범위 %s, 누락 %s, 중복 %d건',
                    received, f'{seqs[0]}~{seqs[-1]}' if seqs else '없음', missing, duplicates)
        return received, len(missing), duplicates


def main(argv=None):
    """구독기를 실행하고 종료 코드를 돌려준다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    subscriber = Subscriber(args)
    if not subscriber.connect():
        subscriber.close()
        return EXIT_CONNECT_FAILED
    subscriber.wait()
    subscriber.close()
    received, _, _ = subscriber.summary()
    if args.count and received < args.count:
        return EXIT_SHORT
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
