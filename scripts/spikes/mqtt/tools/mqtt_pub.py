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
MQTT 학습 2단계: paho-mqtt 로 메시지를 발행하는 스크립트.

왜 필요한가: 1단계에서 mosquitto_pub 으로 본 QoS·retained 동작을 코드로 직접 구현해,
콜백 구조와 "브로커가 받았다"는 확인(on_publish)이 어떻게 이어지는지 익힌다.

하는 일:
  1. 브로커에 접속한다 (on_connect 에서 결과 코드 확인).
  2. 메시지를 --count 건, --interval 초 간격으로 발행한다.
     내용은 '<접두사> seq=<순번> t=<시각>' 이라서 구독기가 누락·중복을 셀 수 있다.
  3. 발행마다 확인(QoS 0 은 전송 직후, 1·2 는 PUBACK/PUBCOMP)까지 걸린 시간을 남기고,
     확인 못 받은 건수를 센다.

종료 코드: 0 = 전부 발행·확인, 1 = 확인 못 받은 메시지가 있음, 2 = 접속 실패.

안전:
  - ROS 와 로봇을 쓰지 않는다. 기본 토픽은 mqtt_learning/ 아래의 학습용 이름이다.
  - 기본 브로커는 127.0.0.1 이다. 공개 브로커나 LAN 주소는 인자로 적을 때만 쓴다.
  - --retain 은 기본으로 꺼져 있다. retained 메시지는 브로커 디스크에 남아
    나중에 구독하는 쪽에 낡은 값을 주기 때문이다. 켰다면 끝나고 빈 retained 로 지운다.

실행 (paho-mqtt 1.6.x 기준):
    python3 scripts/spikes/mqtt/tools/mqtt_pub.py --count 10 --qos 1
"""

import argparse
import logging
import sys
import threading
import time

import paho.mqtt.client as mqtt

EXIT_OK = 0
EXIT_UNCONFIRMED = 1
EXIT_CONNECT_FAILED = 2

LOGGER = logging.getLogger('mqtt_pub')


def parse_args(argv=None):
    """명령행 인자를 읽는다. 값은 코드에 박아 두지 않고 모두 여기서 받는다."""
    parser = argparse.ArgumentParser(description='MQTT 학습용 발행기')
    parser.add_argument('--host', default='127.0.0.1', help='브로커 주소')
    parser.add_argument('--port', type=int, default=1883, help='브로커 포트')
    parser.add_argument('--topic', default='mqtt_learning/spike/data', help='발행 토픽')
    parser.add_argument('--qos', type=int, choices=(0, 1, 2), default=0, help='발행 QoS')
    parser.add_argument('--keepalive', type=int, default=30,
                        help='keepalive 초. 이 시간 안에 신호가 없으면 브로커가 끊김으로 본다')
    parser.add_argument('--client-id', default='', help='클라이언트 ID (비우면 자동 생성)')
    parser.add_argument('--count', type=int, default=10, help='발행할 메시지 수')
    parser.add_argument('--interval', type=float, default=0.5, help='발행 간격 [s]')
    parser.add_argument('--payload-prefix', default='msg', help='메시지 앞에 붙일 글자')
    parser.add_argument('--retain', action='store_true', help='retained 로 발행 (기본 꺼짐)')
    parser.add_argument('--connect-timeout', type=float, default=5.0,
                        help='접속 확인을 기다리는 시간 [s]')
    parser.add_argument('--confirm-timeout', type=float, default=5.0,
                        help='QoS 1·2 발행 확인을 기다리는 시간 [s]')
    return parser.parse_args(argv)


class Publisher:
    """paho 클라이언트를 감싸 콜백 결과를 모아 두는 작은 클래스."""

    def __init__(self, args):
        self._args = args
        # clean_session=True: 이 발행기는 상태를 남기지 않는다. 구독 쪽만 세션을 유지한다.
        self._client = mqtt.Client(client_id=args.client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish
        # 콜백은 paho 의 네트워크 스레드에서 불리므로 메인 스레드와 Event 로 신호를 주고받는다.
        self._connected = threading.Event()
        self._connect_rc = None
        self._lock = threading.Lock()
        self._confirmed_mids = set()

    def _on_connect(self, client, userdata, flags, rc):
        """접속 결과를 기록한다. rc 0 이 성공이다."""
        self._connect_rc = rc
        if rc == 0:
            LOGGER.info('접속 성공 %s:%d', self._args.host, self._args.port)
        else:
            LOGGER.error('접속 거부 rc=%d (%s)', rc, mqtt.connack_string(rc))
        # 실패해도 Event 는 켠다. 안 켜면 메인이 시간 초과까지 헛되이 기다린다.
        self._connected.set()

    def _on_disconnect(self, client, userdata, rc):
        """끊길 때 불린다. rc 0 이면 우리가 끊은 것이고, 아니면 예기치 않은 끊김이다."""
        if rc == 0:
            LOGGER.info('정상 종료')
        else:
            LOGGER.warning('예기치 않게 끊김 rc=%d', rc)

    def _on_publish(self, client, userdata, mid):
        """브로커 확인이 도착하면 불린다. QoS 0 은 보낸 즉시, 1·2 는 PUBACK/PUBCOMP 뒤다."""
        with self._lock:
            self._confirmed_mids.add(mid)

    def connect(self):
        """접속하고 네트워크 스레드를 시작한다. 성공하면 True 를 돌려준다."""
        try:
            self._client.connect(self._args.host, self._args.port, self._args.keepalive)
        except OSError as error:
            LOGGER.error('브로커에 닿지 않음: %s', error)
            return False
        # loop_start: 네트워크 처리를 별도 스레드가 맡아서 메인은 발행 순서만 신경 쓴다.
        self._client.loop_start()
        if not self._connected.wait(self._args.connect_timeout):
            LOGGER.error('접속 확인 시간 초과')
            return False
        return self._connect_rc == 0

    def publish_all(self):
        """메시지를 발행하고, 확인 못 받은 건수를 돌려준다."""
        args = self._args
        unconfirmed = 0
        for seq in range(args.count):
            payload = f'{args.payload_prefix} seq={seq} t={time.time():.6f}'
            started = time.monotonic()
            info = self._client.publish(args.topic, payload, qos=args.qos, retain=args.retain)
            # on_publish 는 비동기라 바로 확인하면 아직 False 일 수 있다. 그래서 항상 기다린다.
            # QoS 0 은 전송 직후, QoS 1·2 는 브로커 확인(PUBACK/PUBCOMP) 뒤에 끝나므로
            # 걸린 시간 차이로 QoS 의 비용을 볼 수 있다.
            info.wait_for_publish(timeout=args.confirm_timeout)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if info.is_published():
                LOGGER.info('발행 seq=%d mid=%d qos=%d 확인까지 %.2f ms',
                            seq, info.mid, args.qos, elapsed_ms)
            else:
                unconfirmed += 1
                LOGGER.warning('확인 못 받음 seq=%d mid=%d', seq, info.mid)
            time.sleep(args.interval)
        return unconfirmed

    def close(self):
        """정상 종료한다. disconnect 를 불러야 브로커가 유언(LWT)을 보내지 않는다."""
        self._client.disconnect()
        self._client.loop_stop()


def main(argv=None):
    """발행기를 실행하고 종료 코드를 돌려준다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    publisher = Publisher(args)
    if not publisher.connect():
        publisher.close()
        return EXIT_CONNECT_FAILED
    unconfirmed = publisher.publish_all()
    publisher.close()
    LOGGER.info('요약: 발행 %d건, 확인 못 받음 %d건', args.count, unconfirmed)
    return EXIT_UNCONFIRMED if unconfirmed else EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
