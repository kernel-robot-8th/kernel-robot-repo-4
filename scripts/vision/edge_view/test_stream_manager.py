#!/usr/bin/env python3
"""스트림 관리자 시험. 모델과 장치 없이 돈다. 임시 폴더에만 쓴다."""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(1 << 25))

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_view as ev
import resources as rs
import stream_manager as sm

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}{' ' + str(detail) if detail and not ok else ''}")


class FakeCapture:
    def __init__(self, source, replay_fps=5.0):
        self.source, self.kind = source, ev.source_kind(source)
        self.halt = threading.Event()
        self.seq, self.good_time = 0, 0.0
        self.connected, self.reconnects, self.bad_frames, self.started = True, 0, 0, False
        self.frame = np.zeros((40, 60, 3), np.uint8)
        self.name = ""
        self.fps_received, self.broken = 30.0, None

    def start(self):
        self.started = True

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass

    def feed(self):
        self.seq += 1
        self.good_time = time.time()

    def peek(self):
        return self.seq, self.good_time

    def latest(self):
        if self.broken:
            raise self.broken
        return self.frame, self.seq, time.time()

    def info(self):
        return {"transport": "fake", "fps_received": self.fps_received, "http_status": None, "rotation": None, "lens": None}


class FakeDetector:
    names = {0: "box_on_floor", 1: "box_stock"}

    def __init__(self):
        self.calls, self.fail_for, self.dets = [], None, []

    def detect(self, frame, conf=0.25, iou=0.7):
        self.calls.append(frame)
        return [dict(d) for d in self.dets]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def entry(camera_id, fps=5, source="rtsp://127.0.0.1:8554/x", **kw):
    return dict({"id": camera_id, "name": camera_id, "source": source, "max_fps": fps}, **kw)


def manager(cameras, path=None, detector=None, clock=None):
    config = {"cameras": cameras}
    m = sm.StreamManager(config, detector or FakeDetector(), "test", capture_factory=FakeCapture, config_path=path,
                         clock=clock or Clock())
    for c in cameras:
        m.start_camera(c["id"])
    return m


def refuses(config):
    try:
        sm.validate_config(config)
    except ValueError:
        return True
    return False


def test_config():
    ok = sm.validate_config({"cameras": [entry("a"), entry("usb", source=ev.USB_WEBCAM)]})
    check("valid config passes", len(ok["cameras"]) == 2)
    check("duplicate id refused", refuses({"cameras": [entry("a"), entry("a")]}))
    check("bad id refused", refuses({"cameras": [entry("../a")]}))
    for bad in ("/dev/video0", "/dev/video1", "/dev/video2", "0",
                "/dev/v4l/by-id/usb-Chicony_Electronics_Co._Ltd._LG_Camera_0001-video-index0"):
        check(f"device refused {bad[-24:]}", refuses({"cameras": [entry("a", source=bad)]}))
    for fps in (0, -1, 31, True, "5"):
        check(f"fps refused {fps!r}", refuses({"cameras": [entry("a", fps=fps)]}))
    check("too many cameras refused", refuses({"cameras": [entry(f"c{i}") for i in range(sm.MAX_CAMERAS + 1)]}))
    check("cameras must be a list", refuses({"cameras": {}}))
    check("port typo refused", refuses({"cameras": [entry("a", source="http://127.0.0.1:18o86/x")]}))
    for bad in ([], "x", 5, None, {"cameras": [1]}, {"cameras": ["a"]}, {"cameras": [None]}):
        check(f"wrong shape refused {bad!r}", refuses(bad))
    for key, value in (("cooldown", float("nan")), ("conf", float("inf")), ("conf", 5), ("iou", -1)):
        check(f"bad number refused {key}={value}", refuses({key: value, "cameras": [entry("a")]}))
    check("empty name falls back to id", sm.Camera(entry("a", name=None)).name == "a")
    for key, value in (("view_width", "720"), ("debounce", "3"), ("cooldown", "5"), ("alarm_conf", "0.5"), ("threads", True)):
        check(f"bad {key} refused", refuses({key: value, "cameras": [entry("a")]}))


def test_scheduling():
    clock = Clock()
    detector = FakeDetector()
    m = manager([entry("a", 5), entry("b", 5)], detector=detector, clock=clock)
    s = m.scheduler
    a, b = m.cameras["a"], m.cameras["b"]
    check("no new frame means no work", not s.step())
    a.capture.feed()
    check("new frame runs once", s.step() and len(detector.calls) == 1)
    check("same frame is not run twice", not s.step())
    a.capture.feed()
    check("rate cap holds a camera back", not s.step())
    clock.now += 0.2
    check("cap opens after the period", s.step())
    order = []
    for _ in range(40):
        a.capture.feed()
        b.capture.feed()
        clock.now += 0.05
        before = (a.viewer.frames, b.viewer.frames)
        if s.step():
            order.append("a" if a.viewer.frames > before[0] else "b")
    gap = abs(order.count("a") - order.count("b"))
    check("overload is shared evenly", gap <= 1 and len(order) >= 18, order)
    check("no camera runs twice in a row while both wait", all(x != y for x, y in zip(order, order[1:])), order)


def test_uneven_rates():
    clock = Clock()
    m = manager([entry("fast", 5), entry("slow", 1)], clock=clock)
    fast, slow = m.cameras["fast"], m.cameras["slow"]
    for _ in range(100):
        fast.capture.feed()
        slow.capture.feed()
        clock.now += 0.1
        while m.scheduler.step():
            pass
    check("each camera keeps its own limit", 45 <= fast.viewer.frames <= 51 and 9 <= slow.viewer.frames <= 11,
          (fast.viewer.frames, slow.viewer.frames))


def test_failure_isolated():
    clock = Clock()

    class Selective(FakeDetector):
        def detect(self, frame, conf=0.25, iou=0.7):
            if frame is bad_frame:
                raise RuntimeError("boom")
            return super().detect(frame)

    detector = Selective()
    m = manager([entry("bad"), entry("good")], detector=detector, clock=clock)
    bad, good = m.cameras["bad"], m.cameras["good"]
    bad_frame = bad.capture.frame
    for _ in range(sm.MAX_ERRORS * 2):
        bad.capture.feed()
        good.capture.feed()
        clock.now += 0.3
        while m.scheduler.step():
            pass
    check("broken camera stops with a reason", bad.state == "error" and "연속 실패" in str(bad.error), bad.state)
    check("broken camera capture is halted", bad.capture.halt.is_set())
    check("other camera keeps running", good.state == "running" and good.viewer.frames >= sm.MAX_ERRORS * 2 - 1,
          good.viewer.frames)
    check("failed camera can be started again", m.start_camera("bad").state == "running" and bad.error is None)


def test_broken_input_does_not_kill_inference():
    clock = Clock()
    m = manager([entry("bad"), entry("good")], clock=clock)
    bad, good = m.cameras["bad"], m.cameras["good"]
    bad.capture.broken = RuntimeError("cv2.error")
    for _ in range(sm.MAX_ERRORS * 2):
        bad.capture.feed()
        good.capture.feed()
        clock.now += 0.3
        while m.scheduler.step():
            pass
    check("broken frame stops only that camera", bad.state == "error" and good.state == "running", bad.state)
    check("good camera kept working", good.viewer.frames >= sm.MAX_ERRORS * 2 - 1, good.viewer.frames)

    class Render(sm.CameraViewer):
        def process(self, *a, **k):
            raise TypeError("bad render")

    m2 = manager([entry("a")], clock=clock)
    cam = m2.cameras["a"]
    cam.viewer.__class__ = Render
    cam.capture.feed()
    clock.now += 0.3
    check("process error is caught", m2.scheduler.step() and cam.errors == 1 and cam.viewer.errors_total == 1)


def test_scheduler_survives_a_bug():
    clock = Clock()
    m = manager([entry("a")], clock=clock)
    s = m.scheduler
    real, calls = s.step, []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        s.halt.set()
        return False

    s.step = flaky
    s.start()
    s.join(timeout=3)
    check("loop keeps going after a bug", len(calls) == 2 and s.faults == 1, (len(calls), s.faults))
    s.step = real


def test_stop_during_detect():
    clock = Clock()

    class Stopper(FakeDetector):
        def detect(self, frame, conf=0.25, iou=0.7):
            m.stop_camera("a")
            return []

    m = manager([entry("a")], detector=Stopper(), clock=clock)
    cam = m.cameras["a"]
    cam.capture.feed()
    clock.now += 0.3
    m.scheduler.step()
    check("stop during detect drops the result", cam.viewer.frames == 0 and cam.state == "stopped", cam.viewer.frames)
    old = cam.viewer
    m.start_camera("a")
    m.fail(cam, old, "late")
    check("late failure leaves the new run alone", cam.state == "running" and cam.error is None)
    m.stop_camera("a")
    m.fail(cam, cam.viewer, "late")
    check("failure does not overwrite a user stop", cam.state == "stopped")


def test_debounce_follows_real_interval():
    clock = Clock()
    m = manager([entry("a", 5)], clock=clock)
    cam = m.cameras["a"]
    for _ in range(3):
        cam.capture.feed()
        clock.now += 1.2
        m.scheduler.step()
    check("reset follows the real gap", abs(cam.viewer.debounce.reset_sec - 3.6) < 1e-6, cam.viewer.debounce.reset_sec)


def test_oversized_jpeg_is_a_bad_frame():
    ok, buf = ev.cv2.imencode(".jpg", np.zeros((32, 32, 3), np.uint8))
    data = bytearray(buf.tobytes())
    i = data.index(b"\xff\xc0")
    data[i + 5:i + 9] = (16000).to_bytes(2, "big") * 2
    capture = ev.Capture("rtsp://127.0.0.1:8554/x")
    capture._put_raw(bytes(data), {})
    start = time.perf_counter()
    frame, _, _ = capture.latest()
    check("huge fake size is refused quickly", frame is None and capture.bad_frames == 1 and time.perf_counter() - start < 0.3,
          (frame is None, capture.bad_frames))
    good = np.zeros((1440, 1080, 3), np.uint8)
    capture._put_raw(ev.cv2.imencode(".jpg", good)[1].tobytes(), {})
    check("normal frame still decodes", capture.latest()[0].shape == (1440, 1080, 3))


def test_replay_skips_links_and_bad_files(tmp):
    folder = os.path.join(tmp, "frames")
    os.makedirs(folder)
    jpeg = ev.cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))[1].tobytes()
    bad = bytearray(jpeg)
    i = bad.index(b"\xff\xc0")
    bad[i + 5:i + 9] = (16000).to_bytes(2, "big") * 2
    with open(os.path.join(folder, "1.jpg"), "wb") as f:
        f.write(bad)
    with open(os.path.join(folder, "2.jpg"), "wb") as f:
        f.write(jpeg)
    os.symlink("/dev/null", os.path.join(folder, "0.jpg"))
    replay = ev.ReplayFrames(folder, "dir")
    check("device link is not listed", replay.names == ["1.jpg", "2.jpg"], replay.names)
    check("bad file gives no frame and moves on", replay.next() is None and replay.next() is not None)


def test_stopped_capture_drops_its_frame(tmp):
    folder = os.path.join(tmp, "one")
    os.makedirs(folder)
    with open(os.path.join(folder, "1.jpg"), "wb") as f:
        f.write(ev.cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))[1].tobytes())
    capture = ev.Capture(folder, replay_fps=50.0)
    capture.start()
    deadline = time.monotonic() + 3
    while capture.peek()[0] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    check("replay delivered a frame", capture.peek()[0] > 0)
    capture.halt.set()
    capture.join(timeout=3)
    check("stopped capture holds no frame", capture.frame is None and capture.raw is None)


def test_failure_counter_resets():
    clock = Clock()

    class Flaky(FakeDetector):
        def detect(self, frame, conf=0.25, iou=0.7):
            self.n = getattr(self, "n", 0) + 1
            if self.n % 2:
                raise RuntimeError("boom")
            return []

    m = manager([entry("a")], detector=Flaky(), clock=clock)
    cam = m.cameras["a"]
    for _ in range(sm.MAX_ERRORS * 3):
        cam.capture.feed()
        clock.now += 0.3
        m.scheduler.step()
    check("occasional errors do not stop a camera", cam.state == "running")


def test_lifecycle():
    clock = Clock()
    m = manager([entry("a"), entry("b")], clock=clock)
    a = m.cameras["a"]
    first = a.capture
    check("capture thread gets a camera name", first.name == "capture-a")
    m.stop_camera("a")
    check("stop halts capture and viewer", first.halt.is_set() and a.viewer.stop.is_set() and a.state == "stopped")
    first.feed()
    clock.now += 1
    check("stopped camera is not scheduled", not m.scheduler.step())
    check("start twice keeps one capture", m.start_camera("b").capture is m.start_camera("b").capture)
    m.start_camera("a")
    check("restart makes a new capture", a.capture is not first and a.capture.started)
    check("unknown camera raises KeyError", raises(KeyError, lambda: m.stop_camera("none")))


def raises(kind, fn):
    try:
        fn()
    except kind:
        return True
    return False


def test_reload(tmp):
    path = os.path.join(tmp, "c.json")

    def write(cameras):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cameras": cameras}, f)

    write([entry("a"), entry("b")])
    m = manager([entry("a"), entry("b")], path=path)
    a, b = m.cameras["a"], m.cameras["b"]
    keep = a.capture
    write([entry("a"), entry("b", 2), entry("c")])
    m.reload()
    check("unchanged camera keeps running", m.cameras["a"].capture is keep and not keep.halt.is_set())
    check("changed camera restarts", m.cameras["b"] is not b and m.cameras["b"].max_fps == 2.0 and b.capture.halt.is_set())
    check("new camera starts", m.cameras["c"].state == "running")
    write([entry("a"), entry("c", enabled=False)])
    m.reload()
    check("removed camera stops", "b" not in m.cameras)
    check("disabled camera stays stopped", m.cameras["c"].state == "stopped")
    write([entry("a", source="/dev/video0")])
    check("bad file is refused", raises(ValueError, m.reload))
    check("bad file changes nothing", sorted(m.cameras) == ["a", "c"] and m.cameras["a"].capture is keep)
    write([entry("a", source="http://127.0.0.1:18o86/x"), entry("b")])
    check("port typo changes nothing", raises(ValueError, m.reload) and "b" not in m.cameras and m.cameras["a"].capture is keep)
    check("state still works after a bad file", len(m.snapshot()["cameras"]) == 2)
    m.capture_factory = lambda *a, **k: (_ for _ in ()).throw(OSError("no input"))
    write([entry("a"), entry("c"), entry("d")])
    m.reload()
    check("start failure stays on that camera", m.cameras["d"].state == "error" and "시작 실패" in m.cameras["d"].error)
    check("other cameras keep running", m.cameras["a"].state == "running")
    m.capture_factory = FakeCapture
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cameras": [entry("a"), entry("c")], "alarm_conf": 0.9, "view_width": 320}, f)
    reply = m.reload()
    check("settings needing a restart are named", reply["restart_needed"] == ["alarm_conf", "view_width"], reply)
    check("running settings stay as they were", m.config.get("alarm_conf") is None and m.alarm_conf == 0.5)
    m.stop_camera("a")
    m.stop_camera("a")
    m.stop_camera("a")
    check("repeated stop keeps one retired entry", sum(c is m.cameras["a"].capture for c in m.retired) == 1)

    class NoThread(FakeCapture):
        def start(self):
            raise RuntimeError("can't start new thread")

    m.capture_factory = NoThread
    before = m.cameras["a"].capture
    check("thread failure leaves state alone", raises(RuntimeError, lambda: m.start_camera("a")))
    check("no running camera without a thread", m.cameras["a"].state == "stopped" and m.cameras["a"].capture is before)
    m._start_safely("a")
    check("safe start records thread failure", m.cameras["a"].state == "error")
    m.capture_factory = FakeCapture


def test_viewers():
    clock = Clock()
    detector = FakeDetector()
    detector.dets = [{"event_type": "box_on_floor", "confidence": 0.9, "bbox": [1.0, 1.0, 9.0, 9.0], "class_id": 0}]
    m = manager([entry("a", 30), entry("b", 30)], detector=detector, clock=clock)
    a, b = m.cameras["a"], m.cameras["b"]
    for _ in range(3):
        a.capture.feed()
        clock.now += 0.1
        m.scheduler.step()
    check("no viewer means no drawing", a.viewer.jpeg is None and a.viewer.frames == 3)
    check("judging still runs without a viewer", a.viewer.event_total["box_on_floor"] == 1)
    check("events stay per camera", b.viewer.event_total["box_on_floor"] == 0 and b.viewer.frames == 0)
    a.viewer.client_enter()
    a.capture.feed()
    clock.now += 0.1
    m.scheduler.step()
    check("a viewer gets a picture", a.viewer.jpeg is not None)
    a.viewer.client_leave()
    check("last viewer leaving drops the picture", a.viewer.jpeg is None)
    a.viewer.publish(np.zeros((8, 8, 3), np.uint8))
    check("late publish with no viewer keeps nothing", a.viewer.jpeg is None)
    slow = manager([entry("s", 1)], clock=clock).cameras["s"]
    check("low rate keeps debounce alive", slow.viewer.debounce.reset_sec == 3.0)
    check("low rate keeps stale limit fair", manager([entry("t", 0.25)], clock=clock).cameras["t"].viewer.stale_sec == 8.0)
    check("normal rate keeps the original rule", a.viewer.debounce.reset_sec == 1.0)
    a.viewer.recent_t.extend([time.monotonic() - 20.0, time.monotonic() - 19.8])
    snap = a.snapshot()
    check("old fps is not shown", snap["fps_processed"] == 0.0 and snap["detect_ms_recent"] is None, snap["fps_processed"])
    a.viewer.snapshot = lambda: 1 / 0
    check("one bad camera cannot break state", "상태 읽기 실패" in m.snapshot()["cameras"][0]["error"])


def test_capacity():
    clock = Clock()
    m = manager([entry("a", 5), entry("b", 5)], clock=clock)
    s = m.scheduler
    for _ in range(20):
        s.record(clock.now, 0.25, 0.1)
        clock.now += 0.25
    snap = s.snapshot()
    check("capacity comes from cycle time", snap["capacity_fps"] == 4.0 and snap["cycle_ms"] == 250.0, snap)
    check("overload is flagged", snap["overloaded"] and snap["requested_fps"] == 10.0, snap)
    s.work.clear()
    for _ in range(20):
        s.record(clock.now, 0.05, 0.0)
        clock.now += 0.1
    snap = s.snapshot()
    check("spare capacity is not flagged", not snap["overloaded"] and snap["capacity_fps"] == 20.0, snap)
    check("busy ratio is the time spent working", 0.1 <= snap["busy_ratio"] <= 0.6, snap)
    s.record(clock.now + 100, 0.05, 0.0)
    check("old samples leave the window", len(s.work) == 1)
    check("stall limit follows the slowest camera", s.snapshot()["stall_after_sec"] == 5.0)
    clock.now += 500
    snap = s.snapshot()
    check("values clear when work stops", snap["capacity_fps"] is None and not snap["overloaded"] and snap["busy_ratio"] == 0.0, snap)
    check("idle time is reported", snap["last_work_age_sec"] is not None and snap["last_work_age_sec"] > 300, snap)
    fresh = manager([entry("a", 0.1)], clock=clock).scheduler
    clock.now += 7
    snap = fresh.snapshot()
    check("no first frame still shows idle time", snap["last_work_age_sec"] >= 7, snap)
    check("slow camera gets a longer stall limit", snap["stall_after_sec"] == 20.0, snap)
    m.cameras["b"].capture.fps_received = 0.0
    m.cameras["a"].capture.fps_received = 2.0
    for _ in range(20):
        s.record(clock.now, 0.2, 0.0)
        clock.now += 0.2
    snap = s.snapshot()
    check("demand counts real input", snap["demand_fps"] == 2.0 and snap["requested_fps"] == 10.0, snap)
    check("no input is not overload", not snap["overloaded"], snap)
    check("scheduler reports it is not running", snap["alive"] is False)


def test_lag_excludes_waiting_for_input():
    clock = Clock()
    m = manager([entry("a", 5)], clock=clock)
    cam, s = m.cameras["a"], m.scheduler
    cam.capture.feed()
    s.step()
    clock.now += 5.0
    cam.capture.feed()
    s.step()
    check("waiting for input is not lag", s.work[-1][2] == 0.0, s.work[-1][2])
    cam.capture.feed()
    other = manager([entry("b", 5), entry("c", 5)], clock=clock)
    b, c = other.cameras["b"], other.cameras["c"]
    b.capture.feed()
    c.capture.feed()
    other.scheduler.step()
    clock.now += 0.1
    other.scheduler.step()
    check("waiting for the scheduler is lag", abs(other.scheduler.work[-1][2] - 0.1) < 1e-6, other.scheduler.work[-1][2])


def test_resources(tmp):
    check("stat with odd thread name", rs.parse_task_stat("12 (a b) c) S " + " ".join(["0"] * 10) + " 7 5 0") == 12)
    names = {1: "capture-a", 2: "inference", 3: "Thread-9 (process_request_thread)"}
    before, after = {1: 0, 2: 0, 3: 0, 4: 0}, {1: rs.CLK_TCK, 2: rs.CLK_TCK // 2, 3: 0, 4: rs.CLK_TCK * 3, 5: 10}
    groups = rs.cpu_by_group(before, after, 2.0, names)
    check("threads are grouped", groups["capture-a"] == 50.0 and groups["inference"] == 25.0 and groups["http"] == 0.0, groups)
    check("unnamed threads count as native", groups["native"] == 150.0, groups)
    check("no time means no value", rs.cpu_by_group(before, after, 0, names) == {})
    monitor = rs.ResourceMonitor(period_sec=0.05)
    first, state = monitor.sample(None)
    time.sleep(0.05)
    second, _ = monitor.sample(state)
    check("first sample has memory", first["process_rss_mb"] and first["mem_available_mb"])
    check("second sample has cpu", "process_cpu_pct" in second and "system_cpu_pct" in second)
    check("real values look real", second["threads"] >= 1 and len(second["load_avg"]) == 3)
    with open(os.path.join(tmp, "stat"), "w", encoding="utf-8") as f:
        f.write("cpu 1000 0 0 1000 0 0 0 0 1000 0\n")
    check("guest ticks are not counted twice", rs.read_system_ticks(os.path.join(tmp, "stat")) == (1000, 2000))
    check("missing sensor is None", rs.read_cpu_temp_c(os.path.join(tmp, "none")) is None and rs.read_cpu_mhz(os.path.join(tmp, "none")) is None)
    os.makedirs(os.path.join(tmp, "hwmon0"))
    with open(os.path.join(tmp, "hwmon0", "name"), "w", encoding="utf-8") as f:
        f.write("coretemp\n")
    check("sensor without a value is None", rs.read_cpu_temp_c(tmp) is None)


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(method, path, body=body, headers=headers or {})
    reply = conn.getresponse()
    data = reply.read(4096)
    conn.close()
    return reply.status, data


def raw(port, data):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(data)
        return sock.recv(64)


def test_http(tmp):
    path = os.path.join(tmp, "h.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cameras": [entry("a")]}, f)
    m = manager([entry("a")], path=path)
    server = ev.Server(("127.0.0.1", 0), sm.make_handler(m))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    js = {"Content-Type": "application/json"}
    try:
        status, data = request(port, "GET", "/api/state")
        state = json.loads(data)
        check("state lists cameras", status == 200 and state["cameras"][0]["id"] == "a" and state["observe_only"] is True)
        check("page is served", request(port, "GET", "/")[0] == 200)
        check("unknown path is 404", request(port, "GET", "/etc/passwd")[0] == 404)
        check("foreign host refused", request(port, "GET", "/api/state", headers={"Host": "evil.example"})[0] == 403)
        check("foreign host refused on stream", request(port, "GET", "/cameras/a/stream.mjpg", headers={"Host": "evil.example:8893"})[0] == 403)
        check("tunnel port is accepted", request(port, "GET", "/api/state", headers={"Host": "127.0.0.1:18893"})[0] == 200)
        check("form post refused", request(port, "POST", "/api/cameras/a/stop", "x=1", {"Content-Type": "text/plain"})[0] == 415)
        for kind in ("text/plain; application/json", "text/plain; x=application/json", "application/json-x", ""):
            check(f"content type refused [{kind}]", request(port, "POST", "/api/cameras/a/stop", "{}", {"Content-Type": kind})[0] == 415)
        check("json with charset passes the type check", request(port, "POST", "/api/cameras/none/stop", "{}", {"Content-Type": "Application/JSON; charset=utf-8"})[0] == 404)
        check("foreign origin refused", request(port, "POST", "/api/cameras/a/stop", "{}", dict(js, Origin="http://evil.example"))[0] == 403)
        check("cross site fetch refused", request(port, "POST", "/api/cameras/a/stop", "{}", dict(js, **{"Sec-Fetch-Site": "cross-site"}))[0] == 403)
        check("same site fetch refused", request(port, "GET", "/cameras/a/stream.mjpg", headers={"Sec-Fetch-Site": "same-site"})[0] == 403)
        check("own page origin passes", request(port, "POST", "/api/cameras/none/stop", "{}", dict(js, Origin="http://127.0.0.1:18893", **{"Sec-Fetch-Site": "same-origin"}))[0] == 404)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/")
        headers = dict(conn.getresponse().getheaders())
        conn.close()
        check("page cannot be framed", headers.get("X-Frame-Options") == "DENY" and "frame-ancestors" in headers.get("Content-Security-Policy", ""))
        check("no sniffing, same origin only", headers.get("X-Content-Type-Options") == "nosniff" and headers.get("Cross-Origin-Resource-Policy") == "same-origin")
        check("still running after refused post", m.cameras["a"].state == "running")
        check("foreign host cannot post", request(port, "POST", "/api/cameras/a/stop", "{}", dict(js, Host="evil.example"))[0] == 403)
        check("big post refused", request(port, "POST", "/api/reload", " " * 5000, js)[0] == 413)
        check("negative length refused", raw(port, b"POST /api/reload HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: -1\r\n\r\n").startswith(b"HTTP/1.0 413"))
        for host in (b"[", b"[::1", b"[]"):
            check(f"bad host answered {host!r}", raw(port, b"GET /api/state HTTP/1.0\r\nHost: " + host + b"\r\n\r\n").startswith(b"HTTP/1.0 403"))
        check("broken path answered", raw(port, b"GET //[x HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").startswith(b"HTTP/1.0 404"))
        check("broken post path answered", raw(port, b"POST //[x HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 0\r\n\r\n").startswith(b"HTTP/1.0 404"))
        check("link can open the page", request(port, "GET", "/", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})[0] == 200)
        check("link cannot open the stream", request(port, "GET", "/cameras/a/stream.mjpg", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})[0] == 403)
        check("link cannot read state", request(port, "GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})[0] == 403)
        check("unknown camera post", request(port, "POST", "/api/cameras/none/stop", "{}", js)[0] == 404)
        check("unknown action post", request(port, "POST", "/api/cameras/a/delete", "{}", js)[0] == 404)
        check("put refused", request(port, "PUT", "/api/state", "{}", js)[0] == 405)
        check("stop works", request(port, "POST", "/api/cameras/a/stop", "{}", js)[0] == 200 and m.cameras["a"].state == "stopped")
        check("stream of stopped camera is 404", request(port, "GET", "/cameras/a/stream.mjpg")[0] == 404)
        check("start works", request(port, "POST", "/api/cameras/a/start", "{}", js)[0] == 200 and m.cameras["a"].state == "running")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken")
        check("broken config is a 400", request(port, "POST", "/api/reload", "{}", js)[0] == 400)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[1]")
        check("wrong shape config is a 400", request(port, "POST", "/api/reload", "{}", js)[0] == 400)
        check("broken config keeps cameras", m.cameras["a"].state == "running")
        viewer = m.cameras["a"].viewer
        socks = []
        for _ in range(ev.MAX_CLIENTS):
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            sock.sendall(b"GET /cameras/a/stream.mjpg HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            socks.append(sock)
        time.sleep(0.3)
        check("viewers are counted", viewer.clients == ev.MAX_CLIENTS, viewer.clients)
        for sock in socks:
            sock.close()
        time.sleep(2.6)
        check("closed viewers leave a camera without frames", viewer.clients == 0, viewer.clients)
    finally:
        server.shutdown()
        server.server_close()


def test_guards():
    here = os.path.dirname(os.path.abspath(__file__))
    source = "".join(open(os.path.join(here, f), encoding="utf-8").read() for f in ("stream_manager.py", "resources.py"))
    check("core dumps are turned off", "PR_SET_DUMPABLE" in source and "prctl" in source)
    for word in ("imwrite", "mqtt", "rclpy", "patrol_cmd", "pixel_event"):
        check(f"no {word}", word not in source.replace("MQTT, ROS", ""))
    check("nonlocal bind refused", raises(ValueError, lambda: ev.check_bind("0.0.0.0", False)))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_config()
        test_scheduling()
        test_uneven_rates()
        test_failure_isolated()
        test_broken_input_does_not_kill_inference()
        test_scheduler_survives_a_bug()
        test_stop_during_detect()
        test_debounce_follows_real_interval()
        test_oversized_jpeg_is_a_bad_frame()
        test_replay_skips_links_and_bad_files(tmp)
        test_stopped_capture_drops_its_frame(tmp)
        test_lag_excludes_waiting_for_input()
        test_failure_counter_resets()
        test_lifecycle()
        test_reload(tmp)
        test_viewers()
        test_capacity()
        test_resources(tmp)
        test_http(tmp)
        test_guards()
    passed = sum(RESULTS)
    print(f"[manager_test] {passed}/{len(RESULTS)} {'PASS' if passed == len(RESULTS) else 'FAIL'}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
