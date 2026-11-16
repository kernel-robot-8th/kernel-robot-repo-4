#!/usr/bin/env python3
"""publisher.py 시험. 이미지 안에서, 네트워크 없이(--network none) 돈다. 가짜 브로커는 이 프로세스 안 127.0.0.1 임의 포트.

  docker run --rm --network none -v ~/homelab-vision/verify:/verify:ro --entrypoint python homelab-vision:20261110 -B /verify/test_publisher.py

보는 것:
  1. 브로커가 접속은 받고 응답만 멈췄다가(mute) 살아날 때: 다시 붙은 뒤 DUP 재전송 0, 2초 넘은 근거 0, 새 메시지 버림 0
  2. 브로커가 죽었다 살아날 때(down): 같은 조건 + offer() 가 막히지 않음
  3. 끊김 5회 반복: 스레드·파일 디스크립터가 늘지 않음
  4. 나이: 촬영 뒤 2초 넘은 근거(age_sec 로 넘김)는 연결돼 있어도 보내지 않음
  5. 로그: 여러 스레드가 함께 써도 한 줄에 JSON 하나
  6. 계수: offered = published + drops + queue_len, published = acked + unacked_lost + inflight, acked = 브로커가 보낸 PUBACK 수
끝날 때 실패 수를 종료 코드로 낸다(0 이면 통과).
"""
import argparse
import gc
import json
import os
import socket
import sys
import threading
import time

ap = argparse.ArgumentParser()
ap.add_argument("--app-dir", default="/app")
ap.add_argument("--outage-sec", type=float, default=8.0)
args = ap.parse_args()
sys.path.insert(0, args.app_dir)

from config import TOPIC_BOXES, TOPIC_STATUS, TOPIC_ZONES  # noqa: E402
from publisher import Publisher  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def wait_for(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeBroker:
    """MQTT 3.1.1 최소 구현. mode: ok | mute(읽기만 하고 응답 없음) | down(리스너와 연결을 닫음)."""

    def __init__(self):
        self.mode, self.port, self.ls = "ok", 0, None
        self.conns, self.events, self.lock = set(), [], threading.Lock()
        self._listen()

    def _listen(self):
        ls = socket.socket()
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", self.port))
        ls.listen(8)
        ls.settimeout(0.1)
        self.port, self.ls = ls.getsockname()[1], ls
        threading.Thread(target=self._accept, args=(ls,), daemon=True).start()

    def set(self, mode):
        if mode == "down":
            self.mode = "down"
            self.ls.close()
            for s in list(self.conns):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        else:
            was, self.mode = self.mode, mode
            if was == "down":
                self._listen()

    def _accept(self, ls):
        while self.mode != "down":
            try:
                s, _ = ls.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            s.settimeout(None)
            self.conns.add(s)
            threading.Thread(target=self._serve, args=(s,), daemon=True).start()

    def _ev(self, **k):
        k["t"] = time.time()
        k["mode"] = self.mode
        with self.lock:
            self.events.append(k)

    def _serve(self, s):
        buf = bytearray()
        try:
            while True:
                d = s.recv(65536)
                if not d:
                    break
                buf += d
                while True:
                    if len(buf) < 2:
                        break
                    mult, rl, i, short = 1, 0, 1, False
                    while True:
                        if i >= len(buf):
                            short = True
                            break
                        b = buf[i]
                        rl += (b & 127) * mult
                        mult *= 128
                        i += 1
                        if not b & 128:
                            break
                    if short or len(buf) < i + rl:
                        break
                    h, body = buf[0], bytes(buf[i:i + rl])
                    del buf[:i + rl]
                    self._packet(s, h, body)
        except OSError:
            pass
        finally:
            self.conns.discard(s)
            s.close()

    def _packet(self, s, h, body):
        t, ok = h >> 4, self.mode == "ok"
        if t == 1:
            self._ev(ev="CONNECT")
            if ok:
                s.sendall(b"\x20\x02\x00\x00")
        elif t == 3:
            dup, qos, retain = (h >> 3) & 1, (h >> 1) & 3, h & 1
            tl = int.from_bytes(body[0:2], "big")
            topic, p, pid = body[2:2 + tl].decode(), 2 + tl, None
            if qos:
                pid = int.from_bytes(body[p:p + 2], "big")
                p += 2
            try:
                j = json.loads(body[p:])
            except ValueError:
                j = None
            self._ev(ev="PUBLISH", topic=topic, qos=qos, dup=dup, retain=retain, j=j if isinstance(j, dict) else None, acked=bool(qos and ok))
            if qos and ok:
                s.sendall(b"\x40\x02" + pid.to_bytes(2, "big"))
        elif t == 12:
            self._ev(ev="PINGREQ")
            if ok:
                s.sendall(b"\xd0\x00")

    def publishes(self):
        with self.lock:
            return [e for e in self.events if e["ev"] == "PUBLISH" and e["topic"] in (TOPIC_ZONES, TOPIC_BOXES)]


def snap(pub):
    g = lambda n: getattr(pub, n, None)  # noqa: E731
    return {"published": pub.published, "acked": g("published_acked"), "lost": g("unacked_lost"),
            "inflight": pub.inflight() if hasattr(pub, "inflight") else None, "drops": pub.drops, "rc": pub.drops_rc,
            "overflow": pub.drops_overflow, "stale": pub.drops_stale, "qlen": pub.queue_len(), "renewals": g("renewals")}


class Feeder:
    """추론 루프 흉내: 0.25초마다 zones, boxes 한 건씩 offer."""

    def __init__(self, pub):
        self.pub, self.n, self.max_ms, self.seq, self.born = pub, 0, 0.0, 0, {}
        self.stop = threading.Event()
        self.th = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            for topic in (TOPIC_ZONES, TOPIC_BOXES):
                born = time.time()
                t = time.perf_counter()
                self.pub.offer(topic, json.dumps({"seq": self.seq, "born": born}))
                self.max_ms = max(self.max_ms, (time.perf_counter() - t) * 1000.0)
                self.n += 1
            self.born[self.seq] = born
            self.seq += 1
            self.stop.wait(0.25)


def scenario(outage):
    print(f"--- scenario {outage} ({args.outage_sec:.0f}s) ---", flush=True)
    b = FakeBroker()
    pub = Publisher("127.0.0.1", b.port, client_id=f"hv-test-{outage}", queue_max=20, max_age_sec=2.0, keepalive=2, log=lambda *a: None)
    check(f"{outage}: first connect", wait_for(lambda: pub.connected, 10))
    f = Feeder(pub)
    f.th.start()
    time.sleep(3.0)
    s0 = snap(pub)
    t_out = time.time()
    b.set(outage)
    detected = wait_for(lambda: not pub.connected, 15)
    t_det = time.time()
    time.sleep(max(0.0, t_out + args.outage_sec - time.time()))
    s1 = snap(pub)
    t_back = time.time()
    b.set("ok")
    re = wait_for(lambda: pub.connected, 12)
    t_re = time.time()
    rc_at_re = pub.drops_rc
    time.sleep(4.0)
    f.stop.set()
    f.th.join()
    t_end = time.time()
    time.sleep(1.0)
    s2 = snap(pub)
    pub.close()

    pubs = b.publishes()
    after = [e for e in pubs if e["t"] > t_back]
    ages = [e["t"] - e["j"]["born"] for e in after]
    seen, twice = set(), 0
    for e in pubs:
        k = (e["topic"], e["j"]["seq"])
        twice += k in seen
        seen.add(k)
    want = [(tp, q) for q, born in f.born.items() if t_re + 0.5 < born < t_end - 0.1 for tp in (TOPIC_ZONES, TOPIC_BOXES)]
    missing = [k for k in want if k not in seen]
    acks = sum(1 for e in pubs if e["acked"])
    print(f"  detect {t_det - t_out:.1f}s after outage, reconnect {t_re - t_back:.1f}s after recovery, offered {f.n}, broker got {len(pubs)} "
          f"(after recovery {len(after)}), offer max {f.max_ms:.3f} ms", flush=True)
    print(f"  before outage {s0}\n  end of outage {s1}\n  end           {s2}", flush=True)
    check(f"{outage}: outage detected", detected)
    check(f"{outage}: reconnected", re, f"{t_re - t_back:.1f}s")
    check(f"{outage}: no DUP resend", sum(e["dup"] for e in pubs) == 0, f"dup={sum(e['dup'] for e in pubs)}")
    check(f"{outage}: nothing delivered twice", twice == 0, f"twice={twice}")
    check(f"{outage}: nothing older than 2.5s after recovery", bool(ages) and max(ages) <= 2.5, f"max_age={max(ages):.2f}s n={len(ages)}" if ages else "no messages")
    check(f"{outage}: every message offered 0.5s after reconnect arrived", bool(want) and not missing, f"want={len(want)} missing={len(missing)}")
    check(f"{outage}: no rc drops after reconnect", s2["rc"] == rc_at_re, f"{rc_at_re}->{s2['rc']}")
    check(f"{outage}: all QoS1 retain0", all(e["qos"] == 1 and e["retain"] == 0 for e in pubs))
    check(f"{outage}: offer never blocks (<10 ms)", f.max_ms < 10.0, f"{f.max_ms:.3f} ms")
    check(f"{outage}: offered = published + drops + queue", f.n == s2["published"] + s2["drops"] + s2["qlen"],
          f"{f.n} = {s2['published']} + {s2['drops']} + {s2['qlen']}")
    ok = None not in (s2["acked"], s2["lost"], s2["inflight"])
    check(f"{outage}: published = acked + unacked_lost + inflight", ok and s2["published"] == s2["acked"] + s2["lost"] + s2["inflight"],
          f"{s2['published']} = {s2['acked']} + {s2['lost']} + {s2['inflight']}")
    check(f"{outage}: acked = PUBACKs the broker sent", ok and s2["acked"] == acks, f"app {s2['acked']} broker {acks}")
    if outage == "mute":
        check("mute: published rises while acked does not", ok and s1["published"] > s0["published"] and s1["acked"] <= s0["published"],
              f"published {s0['published']}->{s1['published']}, acked {s0['acked']}->{s1['acked']}, lost {s1['lost']}")
    return b


def flap(times=5):
    print(f"--- scenario flap x{times} ---", flush=True)
    b = FakeBroker()
    gc.collect()
    fd0, th0 = len(os.listdir("/proc/self/fd")), threading.active_count()
    pub = Publisher("127.0.0.1", b.port, client_id="hv-test-flap", queue_max=20, max_age_sec=2.0, keepalive=2, log=lambda *a: None)
    wait_for(lambda: pub.connected, 10)
    f = Feeder(pub)
    f.th.start()
    time.sleep(1.0)
    fd1, th1 = len(os.listdir("/proc/self/fd")), threading.active_count()
    okc, fds, ths = 0, [], []
    for _ in range(times):
        b.set("down")
        wait_for(lambda: not pub.connected, 10)
        time.sleep(1.5)
        b.set("ok")
        okc += wait_for(lambda: pub.connected, 12)
        time.sleep(1.0)
        gc.collect()
        fds.append(len(os.listdir("/proc/self/fd")))
        ths.append(threading.active_count())
    f.stop.set()
    f.th.join()
    time.sleep(0.5)
    s = snap(pub)
    pub.close()
    pubs = b.publishes()
    print(f"  fds idle {fd0} running {fd1} per cycle {fds}; threads idle {th0} running {th1} per cycle {ths}; end {s}", flush=True)
    check("flap: reconnected every time", okc == times, f"{okc}/{times}")
    check("flap: no DUP resend", sum(e["dup"] for e in pubs) == 0)
    check("flap: fds do not grow", max(fds) <= fd1 + 2 and fds[-1] <= fds[0] + 1, f"{fd1} -> {fds}")
    check("flap: threads do not grow", max(ths) <= th1 + 2 and ths[-1] <= ths[0] + 1, f"{th1} -> {ths}")
    check("flap: offered = published + drops + queue", f.n == s["published"] + s["drops"] + s["qlen"], f"{f.n} = {s['published']} + {s['drops']} + {s['qlen']}")


def age():
    print("--- scenario age ---", flush=True)
    b = FakeBroker()
    pub = Publisher("127.0.0.1", b.port, client_id="hv-test-age", queue_max=20, max_age_sec=2.0, keepalive=2, log=lambda *a: None)
    wait_for(lambda: pub.connected, 10)
    try:
        pub.offer(TOPIC_ZONES, json.dumps({"seq": 1, "born": time.time() - 2.5}), age_sec=2.5)
        pub.offer(TOPIC_ZONES, json.dumps({"seq": 2, "born": time.time() - 1.0}), age_sec=1.0)
        pub.offer(TOPIC_ZONES, json.dumps({"seq": 3, "born": time.time()}), age_sec=-5.0)   # 시계가 뒤로 간 경우: 0 으로 본다
    except TypeError as e:
        check("age: offer takes age_sec", False, str(e))
        pub.close()
        return
    time.sleep(1.0)
    got = sorted(e["j"]["seq"] for e in b.publishes())
    s = snap(pub)
    pub.close()
    check("age: 2.5s-old evidence is not sent, 1.0s-old and fresh are", got == [2, 3] and s["stale"] == 1, f"got={got} stale={s['stale']}")


def logcheck(threads=8, each=3000):
    """main.log 을 여러 스레드가 함께 불러도 한 줄에 JSON 하나여야 한다(임시 파일에 로그 글자만 쓴다)."""
    print("--- scenario log ---", flush=True)
    import tempfile
    import main as appmain
    import io
    raw = tempfile.TemporaryFile("w+b", buffering=0)
    # 컨테이너 표준 출력과 같은 조건(버퍼 없음): 쓰기 한 번이 시스템 호출 한 번이다.
    real, f = sys.stdout, io.TextIOWrapper(raw, encoding="utf-8", write_through=True)

    def work(i):
        for k in range(each):
            appmain.log("t", {"i": i, "k": k, "pad": "x" * 200})
    sys.stdout = f
    try:
        ths = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
    finally:
        sys.stdout = real
    f.flush()
    raw.seek(0)
    total = bad = 0
    for line in raw.read().decode("utf-8").split("\n")[:-1]:
        total += 1
        try:
            json.loads(line)
        except ValueError:
            bad += 1
    f.close()
    check("log: one JSON object per line under 8 threads", bad == 0 and total == threads * each, f"lines={total} bad={bad}")


scenario("mute")
scenario("down")
flap()
age()
logcheck()
print(f"RESULT fails={len(FAILS)} {FAILS}", flush=True)
sys.exit(min(len(FAILS), 100))
