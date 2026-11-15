#!/usr/bin/env python3
"""edge_view.py 시험. 모델과 openvino 없이 돈다(가짜 검출기). 합성 프레임만 쓴다.

    python test_edge_view.py     # 끝 줄이 [view_test] N/N PASS, exit 0 이어야 한다
"""
import http.client
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import zipfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import edge_view as ev  # noqa: E402

NAMES = {0: "box_on_floor", 1: "box_perched_on_rim", 2: "box_run_over", 3: "lid_detached", 4: "box_on_tray", 5: "box_stock"}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def det(name, conf=0.9, bbox=(100, 100, 140, 140)):
    return {"class_id": 0, "event_type": name, "confidence": conf, "bbox": [float(v) for v in bbox]}


class FakeDetector:
    names = NAMES

    def __init__(self, out=None, raises=0):
        self.out, self.raises, self.calls = out or [], raises, 0

    def detect(self, frame, conf=0.25, iou=0.7):
        self.calls += 1
        if self.calls <= self.raises:
            raise RuntimeError("boom")
        return [dict(d, bbox=list(d["bbox"])) for d in self.out if d["confidence"] > conf]


class FakeCapture:
    source, kind, connected, reconnects, bad_frames = "http://u:p@10.0.0.9:18086/v?k=1", "stream", True, 0, 0

    def __init__(self):
        self.frame, self.seq, self.t, self.rotation, self.lens = None, 0, 0.0, None, None

    def feed(self, frame):
        self.frame, self.seq, self.t = frame, self.seq + 1, time.time()

    def peek(self):
        return self.seq, self.t

    def latest(self):
        return self.frame, self.seq, self.t

    def info(self):
        return {"transport": "http-multipart", "http_status": 200, "fps_received": 0.0, "rotation": self.rotation, "lens": self.lens,
                "zoom": None, "session_changes": 0, "capture_lag_ms": None}


def frame(w=1080, h=1440):
    return np.full((h, w, 3), 90, np.uint8)


def viewer(out=None, log=None, raises=0, **kw):
    cap = FakeCapture()
    return ev.Viewer(FakeDetector(out, raises), cap, event_log=log, model_label="fake 00000000", **kw), cap


def expect_raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def run_frames(v, dets, n, t0=1000.0, dt=0.2):
    for i in range(n):
        v.process(frame(), [dict(d, bbox=list(d["bbox"])) for d in dets], 0.01, t0 + i * dt)


def test_sources(tmp):
    for bad in ("/dev/video0", "0", "2", "/dev/video12"):
        check(f"device refused {bad}", expect_raises(lambda b=bad: ev.source_kind(b)))
    check("missing file refused", expect_raises(lambda: ev.source_kind(os.path.join(tmp, "none.mp4"))))
    check("rtsp is stream", ev.source_kind("rtsp://127.0.0.1:8554/x") == "stream")
    check("http is stream", ev.source_kind("http://10.0.0.2:18086/v") == "stream")
    check("label drops account and query", ev.safe_label("http://u:p@10.0.0.9:18086/v?k=1") == "http://10.0.0.9:18086/v")
    check("nonlocal bind refused", expect_raises(lambda: ev.check_bind("0.0.0.0", False)))
    check("tailnet bind refused", expect_raises(lambda: ev.check_bind("100.69.41.81", False)))
    ev.check_bind("127.0.0.1", False)
    ev.check_bind("0.0.0.0", True)
    check("loopback and explicit bind pass", True)


def test_debounce():
    d = ev.Debounce(3)
    a = [det("box_on_floor")]
    check("two frames do not confirm", not d.update(a, 0.0) and not d.update(a, 0.2))
    check("third frame confirms", len(d.update(a, 0.4)) == 1)
    d = ev.Debounce(3)
    two = [det("box_on_floor", .8), det("box_on_floor", .9, (300, 300, 340, 340))]
    r = [d.update(two, t) for t in (0.0, 0.2, 0.4)]
    check("two boxes count once per frame", not r[0] and not r[1] and r[2] and r[2][0]["confidence"] == .9)
    d = ev.Debounce(3)
    d.update(a, 0.0)
    d.update(a, 0.2)
    check("gap over 1 s resets", not d.update(a, 2.0))


def test_alarm_rules(tmp):
    log = os.path.join(tmp, "ev.jsonl")
    v, _ = viewer(log=log)
    run_frames(v, [det("box_on_floor")], 3)
    check("alarm class confirmed at frame 3", len(v.events) == 1)
    run_frames(v, [det("box_on_floor")], 10, t0=1000.6)
    check("cooldown holds 5 s", len(v.events) == 1, len(v.events))
    run_frames(v, [det("box_on_floor")], 3, t0=1006.0)
    check("next event after cooldown", len(v.events) == 2, len(v.events))
    rows = [json.loads(x) for x in open(log, encoding="utf-8")]
    keys = {"timestamp", "iso_time", "stream_id", "event_type", "confidence", "bbox", "action_required", "mode", "consecutive_frames", "model"}
    check("event log is numbers only", len(rows) == 2 and set(rows[0]) == keys, rows[:1])
    check("event stays observe only", all(r["action_required"] == "NONE" and r["mode"] == "observe_only" for r in rows))
    v, _ = viewer()
    run_frames(v, [det("box_stock", .99), det("box_on_tray", .99)], 10)
    check("stock and tray never become events", not v.events and v.seen_alarm_conf["box_stock"] == 10)
    v, _ = viewer()
    run_frames(v, [det("box_on_floor", .49)], 10)
    check("below alarm conf is shown, not an event", not v.events and v.seen_display["box_on_floor"] == 10)
    v, _ = viewer()
    run_frames(v, [det("lid_detached", .9, (420, 600, 440, 620))], 10)
    check("inside exclusion ROI is no event", not v.events and v.current[0]["in_roi"])
    v, _ = viewer()
    for i in range(5):
        v.process(frame(1440, 1080), [det("lid_detached", .9, (420, 600, 440, 620))], 0.01, 1000 + i * .2)
    check("other frame size skips ROI and says so", v.events and not v.roi_on and not v.snapshot()["roi_applied"])


def test_replay(tmp):
    z = os.path.join(tmp, "rec.zip")
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("rec/session.json", "{}")
        f.writestr("rec/frames.jsonl", "")
        for i in (2, 1, 3):
            ok, b = cv2.imencode(".jpg", np.full((40, 30, 3), i * 60, np.uint8))
            f.writestr(f"rec/frames/{i:06d}.jpg", b.tobytes())
    check("zip is recording", ev.source_kind(z) == "zip")
    r = ev.ReplayFrames(z, "zip")
    vals = [int(r.next().mean()) for _ in range(4)]
    r.close()
    check("frames play in name order and loop", all(abs(a - b) < 6 for a, b in zip(vals, (60, 120, 180, 60))), vals)
    empty = os.path.join(tmp, "empty.zip")
    with zipfile.ZipFile(empty, "w") as f:
        f.writestr("a.txt", "x")
    check("zip without images refused", expect_raises(lambda: ev.ReplayFrames(empty, "zip")))
    c = ev.Capture(z, replay_fps=50)
    c.start()
    time.sleep(0.4)
    _, seq, _ = c.latest()
    c.halt.set()
    c.join(2)
    check("capture thread delivers frames", seq >= 3 and not c.is_alive(), seq)


def test_loop_errors():
    v, cap = viewer([det("box_stock", .9)], raises=1, max_fps=0)
    t = threading.Thread(target=v.loop, daemon=True)
    t.start()
    for _ in range(3):
        cap.feed(frame())
        time.sleep(0.15)
    v.stop.set()
    t.join(2)
    check("one bad frame is skipped", v.errors_total == 1 and v.frames >= 1 and v.fatal is None, (v.errors_total, v.frames))
    v, cap = viewer([], raises=99, max_fps=0, max_errors=3)
    t = threading.Thread(target=v.loop, daemon=True)
    t.start()
    for _ in range(5):
        cap.feed(frame())
        time.sleep(0.1)
    t.join(2)
    check("repeated failure stops loudly", v.fatal and v.stop.is_set(), v.fatal)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(port, path, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path)
    r = c.getresponse()
    if "multipart" in (r.getheader("Content-Type") or ""):  # 스트림은 끝나지 않는다. 상태만 본다.
        c.close()
        return r.status, r.getheader("Content-Type"), b""
    return r.status, r.getheader("Content-Type"), r.read()


def wait_until(fn, sec):
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return bool(fn())


def test_http():
    v, cap = viewer([det("box_on_floor", .9), det("box_stock", .8, (500, 500, 540, 540))], max_fps=0, stale_sec=0.5)
    port = free_port()
    srv = ev.Server(("127.0.0.1", port), ev.make_handler(v))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    t = threading.Thread(target=v.loop, daemon=True)
    t.start()
    st = json.loads(get(port, "/api/state")[2])
    check("no frame yet is stale", st["stale"] and st["frame_age_sec"] is None, st)
    feeding = threading.Event()

    def feed():
        while not feeding.is_set():
            cap.feed(frame())
            time.sleep(0.05)

    f = threading.Thread(target=feed, daemon=True)
    f.start()
    time.sleep(0.5)
    code, ctype, body = get(port, "/")
    check("page served", code == 200 and "text/html" in ctype and "관측 전용".encode() in body)
    code, _, body = get(port, "/api/state")
    st = json.loads(body)
    check("state reports frames", code == 200 and st["frames_processed"] > 0 and st["observe_only"] and not st["stale"], st)
    check("state hides account and query", st["source"] == "http://10.0.0.9:18086/v", st["source"])
    check("state lists six classes", [c["name"] for c in st["classes"]] == list(NAMES.values()))
    check("state shows alarm-class boxes", any(c["name"] == "box_on_floor" and c["frames_alarm_conf"] > 0 for c in st["classes"]))
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /stream.mjpg HTTP/1.0\r\n\r\n")
    buf = b""
    while buf.count(b"--frame") < 2 and len(buf) < 4_000_000:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    m = re.search(rb"Content-Length: (\d+)\r\n\r\n", buf)
    jpg = buf[m.end():m.end() + int(m.group(1))]
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    check("stream gives a JPEG at view width", img is not None and img.shape[1] == 720, None if img is None else img.shape)
    check("stream draws the box colour", img is not None and (np.abs(img.astype(int) - np.array(ev.COLOR["box_on_floor"])).sum(2) < 60).sum() > 50)
    check("POST refused", get(port, "/api/state", "POST")[0] == 405)
    check("unknown path 404", get(port, "/nope")[0] == 404)
    check("closed viewer frees its slot", wait_until(lambda: v.clients == 0, 4), v.clients)
    socks = []
    for _ in range(ev.MAX_CLIENTS):
        x = socket.create_connection(("127.0.0.1", port), timeout=5)
        x.sendall(b"GET /stream.mjpg HTTP/1.0\r\n\r\n")
        x.recv(64)
        socks.append(x)
    check("viewer limit answers 503", get(port, "/stream.mjpg")[0] == 503)
    for x in socks:
        x.close()
    feeding.set()
    f.join(1)
    time.sleep(0.8)
    st = json.loads(get(port, "/api/state")[2])
    check("stopped input turns stale", st["stale"] and st["frame_age_sec"] >= 0.5, st["frame_age_sec"])
    v.stop.set()
    srv.shutdown()


def test_stuck_viewer():
    """읽기를 멈춘 브라우저는 쓰기 시간 제한으로 슬롯을 돌려준다. 무늬 프레임이라 JPEG 이 커서 버퍼가 금방 찬다."""
    noise = np.random.default_rng(0).integers(0, 255, (1440, 1080, 3), dtype=np.uint8)
    v, cap = viewer([], max_fps=0, view_width=1080, jpeg_quality=95)
    keep, ev.WRITE_TIMEOUT_SEC = ev.WRITE_TIMEOUT_SEC, 1.0
    port = free_port()
    srv = ev.Server(("127.0.0.1", port), ev.make_handler(v))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=v.loop, daemon=True).start()
    done = threading.Event()

    def feed():
        while not done.is_set():
            cap.feed(noise)
            time.sleep(0.02)

    threading.Thread(target=feed, daemon=True).start()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.connect(("127.0.0.1", port))
    s.sendall(b"GET /stream.mjpg HTTP/1.0\r\n\r\n")
    check("stuck viewer holds a slot first", wait_until(lambda: v.clients == 1, 3), v.clients)
    check("stuck viewer is released by write timeout", wait_until(lambda: v.clients == 0, 12), v.clients)
    s.close()
    done.set()
    v.stop.set()
    srv.shutdown()
    ev.WRITE_TIMEOUT_SEC = keep


def test_no_frame_files(tmp):
    src = open(os.path.join(HERE, "edge_view.py"), encoding="utf-8").read()
    check("source has no imwrite", "imwrite(" not in src)
    check("source opens no binary file for writing", not re.search(r"open\([^)]*[\"'][wax]b", src))
    check("source has no mqtt or ros", not re.search(r"^\s*(import|from)\s+(paho|rclpy|mqtt)", src, re.M))
    before = set(os.listdir(tmp))
    v, _ = viewer([det("box_on_floor")], log=None)
    cwd = os.getcwd()
    os.chdir(tmp)
    run_frames(v, [det("box_on_floor")], 5)
    os.chdir(cwd)
    check("processing writes no file", set(os.listdir(tmp)) == before)


def part(body=b"abc", extra=b"", boundary=b"--raasframe"):
    return boundary + b"\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n" % len(body) + extra + b"\r\n" + body + b"\r\n"


def raises(exc, data):
    try:
        ev.read_part(io.BytesIO(data))
    except Exception as e:
        if type(e) is exc:
            return True
        print("  other exception", type(e).__name__, e)
    return False


def test_read_part():
    body = b"\xff\xd8--raasframe\r\n\r\n\xff\xd9"  # 본문 안의 경계 글자는 길이로 건너뛴다.
    data = part(body, b"X-Camera-Rotation: 90\r\nX-Frame-Seq: 7\r\n") + part(b"second")
    fp = io.BytesIO(data)
    h, b = ev.read_part(fp)
    check("part body is cut by length", b == body)
    check("part header names are lower case", h.get("x-camera-rotation") == "90" and h.get("x-frame-seq") == "7")
    check("next part follows", ev.read_part(fp)[1] == b"second")
    check("leading noise before a boundary is skipped", ev.read_part(io.BytesIO(b"\r\n\r\n" + part(b"x")))[1] == b"x")
    check("no boundary is refused", raises(ValueError, b"x" * (ev.MAX_LINE * 3)))
    check("missing length is told apart", raises(ev.NoContentLength, b"--f\r\nContent-Type: image/jpeg\r\n\r\nabc"))
    check("zero length is refused", raises(ValueError, b"--f\r\nContent-Length: 0\r\n\r\n"))
    check("oversized length is refused", raises(ValueError, b"--f\r\nContent-Length: %d\r\n\r\n" % (ev.MAX_PART + 1)))
    check("cut body is an end of stream", raises(EOFError, b"--f\r\nContent-Length: 10\r\n\r\nabc"))
    check("empty input is an end of stream", raises(EOFError, b""))
    check("closing boundary is an end of stream", raises(EOFError, b"--raasframe--\r\n\r\n"))


def test_lazy_decode():
    c = ev.Capture("http://127.0.0.1:9/video")  # 시작하지 않는다.
    good = cv2.imencode(".jpg", frame(64, 48))[1].tobytes()
    head = {"x-camera-rotation": "90", "x-camera-lens": "ULTRA_WIDE", "x-publisher-session": "a", "x-capture-clock": "1000"}
    c._put_raw(good, head)
    check("peek does not decode", c.peek()[0] == 1 and c.frame is None)
    f, seq, _ = c.latest()
    check("latest decodes the newest frame", f is not None and f.shape[:2] == (48, 64) and seq == 1)
    c._put_raw(b"not a jpeg", head)
    f, seq, _ = c.latest()
    check("a bad jpeg is counted and gives no frame", f is None and seq == 2 and c.bad_frames == 1)
    check("last good frame stays", c.latest()[0] is not None)
    good_t = c.peek()[1]
    time.sleep(0.05)  # 윈도우 시계 해상도보다 길게 둔다.
    c._put_raw(b"bad again", head)
    c.latest()
    check("a bad jpeg does not refresh the frame age", c.peek()[1] == good_t)
    i = c.info()
    check("input info carries the app headers", i["rotation"] == 90 and i["lens"] == "ULTRA_WIDE" and i["capture_lag_ms"] > 0)
    c._put_raw(good, dict(head, **{"x-publisher-session": "b"}))
    check("session change is counted", c.info()["session_changes"] == 1)


def test_rotation_gate():
    for rot, want in ((None, True), (90, True), (270, False), (0, False)):
        cap = FakeCapture()
        cap.rotation = rot
        v = ev.Viewer(FakeDetector(), cap)
        cands = v.judge([det("box_on_floor", 0.9, (420, 600, 440, 620))], (1080, 1440))
        check(f"rotation {rot} sets the exclusion zone to {want}", v.roi_on is want and bool(cands) is (not want))


def test_lens_gate():
    for lens, want in ((None, True), ("ULTRA_WIDE", True), ("BACK", False)):
        cap = FakeCapture()
        cap.lens = lens
        v = ev.Viewer(FakeDetector(), cap)
        v.judge([], (1080, 1440))
        check(f"lens {lens} sets the exclusion zone to {want}", v.roi_on is want)


def test_received_rate():
    c = ev.Capture("http://127.0.0.1:9/video")
    now = time.monotonic()
    c.arrivals.extend([now - 30.0, now - 29.5, now - 29.0])
    check("received rate falls to zero when frames stop", c.info()["fps_received"] == 0.0)
    c.arrivals.extend([now - 1.0, now - 0.5, now])
    check("received rate uses recent frames", abs(c.info()["fps_received"] - 2.0) < 0.01)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_read_part()
        test_lens_gate()
        test_received_rate()
        test_rotation_gate()
        test_sources(tmp)
        test_debounce()
        test_alarm_rules(tmp)
        test_replay(tmp)
        test_lazy_decode()
        test_loop_errors()
        test_http()
        test_stuck_viewer()
        test_no_frame_files(tmp)
    print(f"[view_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
