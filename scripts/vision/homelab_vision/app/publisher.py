"""MQTT 발행기. PUBLISH=true 일 때만 import 된다(false 면 paho 도, 소켓도 만들지 않는다).

추론 루프는 offer() 만 부른다. offer() 는 기다리지 않는다: 큐가 차면 가장 오래된 것을 버리고 센다.
브로커가 없으면 큐에 쌓였다가 밀려 버려진다. 촬영(프레임 수신) 뒤 2초가 넘은 근거는 paho 에 넘기지 않는다(모니터가 3초 넘은 프레임을 버린다).

끊기면 paho 클라이언트를 버리고 새로 만든다. paho 2.2.0 은 다시 붙을 때 확인(PUBACK) 못 받은 QoS 1 메시지를 전부 DUP 로
다시 보내는데(_messages_reconnect_reset_out), 그 메시지는 이미 오래된 근거다. 새 클라이언트에는 미확인 메시지가 없다.
남는 한계: 연결이 살아 있는 동안 브로커가 읽기를 멈추면, 끊김을 알아챌 때까지(keepalive 5 기준 약 8초) 이미 넘긴 메시지는 늦게 갈 수 있다.
"""
import collections
import threading
import time

import socket

import paho.mqtt.client as mqtt

from config import TOPIC_STATUS


def _unix_socketpair():
    a, b = socket.socketpair()              # AF_UNIX 쌍: 포트를 열지 않는다
    a.setblocking(False)
    b.setblocking(False)
    return a, b


# paho 2.2.0 은 내부 깨움용 소켓 쌍을 만들 때 127.0.0.1 임의 포트를 잠깐 listen 한다(_socketpair_compat).
# 이 앱은 듣는 포트를 하나도 열지 않아야 하므로 유닉스 소켓 쌍으로 바꾼다. 이름이 바뀐 판이면 바꾸지 않고 False 로 남는다.
SOCKETPAIR_PATCHED = hasattr(mqtt, "_socketpair_compat")
if SOCKETPAIR_PATCHED:
    mqtt._socketpair_compat = _unix_socketpair

# 확인 못 받은 QoS 1 메시지 상한. paho 의 대기 한도(max_queued)도 같은 값으로 둔다: paho 안에서 안 보내진 채
# 기다리는 메시지가 없어야 나이 검사가 뜻이 있다. 한도를 넘으면 publish 가 거절되고 drops_rc 로 센다.
INFLIGHT_MAX = 20


def _is_published(info):
    try:
        return info.is_published()
    except (ValueError, RuntimeError):
        return False


class Publisher:
    def __init__(self, broker, port, client_id, queue_max=20, max_age_sec=2.0, keepalive=5, log=print):
        self.log, self.queue_max, self.max_age_sec = log, queue_max, max_age_sec
        self._q = collections.deque()
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self.connected = False
        self.connects = 0
        self.disconnects = 0
        self.published = 0
        self.drops_overflow = 0
        self.drops_stale = 0
        self.drops_rc = 0
        self.published_acked = 0     # 브로커가 PUBACK 으로 확인한 수
        self.unacked_lost = 0        # paho 에 넘겼지만 확인 전에 끊겨서 버린 수(재전송하지 않는다)
        self.renewals = 0
        self._infos = collections.deque()   # 확인을 기다리는 발행(작업 스레드만 바꾼다)
        self._renew = False
        self._conn = (broker, port, client_id, keepalive)
        log("mqtt_client_created", {"no_listen_socketpair": SOCKETPAIR_PATCHED, "keepalive": keepalive, "queue_max": queue_max,
                                    "inflight_max": INFLIGHT_MAX})
        self._new_client()
        self._worker = threading.Thread(target=self._run, name="mqtt-publisher", daemon=True)
        self._worker.start()

    def _new_client(self):
        broker, port, client_id, keepalive = self._conn
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        c.will_set(TOPIC_STATUS, "offline", qos=1, retain=False)
        c.max_inflight_messages_set(INFLIGHT_MAX)
        c.max_queued_messages_set(INFLIGHT_MAX)
        c.reconnect_delay_set(min_delay=1, max_delay=5)
        c.connect_timeout = 3.0
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        self.client = c                      # 콜백이 "지금 클라이언트인지" 보므로 루프를 띄우기 전에 넣는다
        c.connect_async(broker, port, keepalive=keepalive)
        c.loop_start()

    @property
    def drops(self):
        return self.drops_overflow + self.drops_stale + self.drops_rc

    def queue_len(self):
        return len(self._q)

    def inflight(self):
        return len(self._infos)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if client is self.client and not reason_code.is_failure:
            self.connects += 1
            with self._cond:
                self.connected = True
                self._cond.notify_all()
            self.log("mqtt_connected", {"connects": self.connects})

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if client is not self.client:
            return
        with self._cond:
            was, self.connected, self._renew = self.connected, False, True
            self._cond.notify_all()
        if was:
            self.disconnects += 1
            self.log("mqtt_disconnected", {"disconnects": self.disconnects})
        # 이 클라이언트가 스스로 다시 붙으면 미확인 메시지를 재전송한다. 그 전에 루프를 끝낸다.
        # 루프 스레드 안에서 부르는 loop_stop() 은 기다리지 않고 종료 표시만 한다(재접속 대기 1초보다 먼저 선다).
        client.loop_stop()
        client.disconnect()

    def _reap(self):
        """확인된 발행을 센다(작업 스레드에서만 부른다)."""
        if self._infos:
            left = collections.deque(i for i in self._infos if not _is_published(i))
            self.published_acked += len(self._infos) - len(left)
            self._infos = left

    def _renew_client(self):
        self.client.loop_stop()              # on_disconnect 에서 종료 표시를 했다. 스레드가 끝났는지만 기다린다.
        self._reap()
        self.unacked_lost += len(self._infos)
        self._infos = collections.deque()
        with self._cond:
            self._renew = False
        self.renewals += 1
        self._new_client()
        self.log("mqtt_client_renewed", {"renewals": self.renewals, "unacked_lost": self.unacked_lost})

    def offer(self, topic, payload, age_sec=0.0):
        """추론 루프용. 절대 기다리지 않는다. age_sec 는 이 근거가 이미 먹은 나이(촬영부터 지금까지)다."""
        with self._cond:
            if len(self._q) >= self.queue_max:
                self._q.popleft()
                self.drops_overflow += 1
            self._q.append((time.monotonic() - max(0.0, age_sec), topic, payload))
            self._cond.notify()

    def _run(self):
        while not self._stop.is_set():
            self._reap()
            with self._cond:
                renew = self._renew
                if not renew:
                    if not self._q or not self.connected:
                        self._cond.wait(0.2)
                        continue
                    born, topic, payload = self._q.popleft()
            if renew:
                self._renew_client()
                continue
            if time.monotonic() - born > self.max_age_sec:
                self.drops_stale += 1
                continue
            info = self.client.publish(topic, payload, qos=1, retain=False)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self.published += 1
                self._infos.append(info)
            else:
                self.drops_rc += 1

    def heartbeat(self, payload):
        if self.connected:
            self.client.publish(TOPIC_STATUS, payload, qos=0, retain=False)

    def close(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._worker.join(timeout=4.0)       # 클라이언트를 새로 만드는 중이면 끝나길 기다린다
        c = self.client
        try:
            if self.connected:
                c.publish(TOPIC_STATUS, "offline", qos=1, retain=False).wait_for_publish(1.0)
            c.disconnect()
        except Exception:  # noqa: BLE001
            pass
        c.loop_stop()
        self._reap()
