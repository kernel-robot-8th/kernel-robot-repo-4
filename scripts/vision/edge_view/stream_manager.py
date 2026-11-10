#!/usr/bin/env python3
"""여러 카메라의 영상 입력, 추론 순서, 자원 사용을 한 곳에서 관리한다 (관측 전용).

    python stream_manager.py --config cameras.json

    카메라 A -> 수신 스레드 --+
    카메라 B -> 수신 스레드 --+--> 추론 스케줄러 (모델 하나, 한 번에 한 프레임) -> 카메라별 화면
    카메라 C -> 수신 스레드 --+

추론은 한 스레드가 순서대로 맡는다. 프로세스를 따로 띄우면 같은 코어를 놓고 다투기 때문이다.
수신과 판정 규칙은 edge_view.py 그대로이고 여기서는 묶어서 관리만 한다.

지키는 것은 edge_view.py 와 같다. MQTT, ROS, 관제 명령이 없고 프레임을 디스크에 쓰지 않으며
127.0.0.1 에만 연다. 쓰기 요청은 카메라 시작, 정지, 설정 다시 읽기뿐이다.
"""
import os

# cv2 를 불러오기 전에 정한다. 크기만 부풀린 JPEG 한 장이 메모리와 추론 순서를 잡아먹지 못하게 한다.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(1 << 25))

import argparse  # noqa: E402
from collections import deque
import ctypes
from http.server import BaseHTTPRequestHandler
import json
import logging
import math
import re
import select
import signal
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

import edge_view as ev
from resources import ResourceMonitor

logger = logging.getLogger("stream_manager")

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_CAMERAS = 8
MAX_FPS = 30.0
MAX_ERRORS = 20
WINDOW_SEC = 10.0
OVERLOAD_RATIO = 0.9
BODY_LIMIT = 4096
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
CROSS_SITE = ("cross-site", "same-site")
PR_SET_DUMPABLE = 4
SECURITY_HEADERS = (("X-Frame-Options", "DENY"), ("Content-Security-Policy", "frame-ancestors 'none'"),
                    ("X-Content-Type-Options", "nosniff"), ("Cross-Origin-Resource-Policy", "same-origin"))
RATIO_FIELDS = ("conf", "alarm_conf", "iou")
INTEGER_FIELDS = ("debounce", "view_width", "threads")
ID_PATTERN = re.compile(r"[a-z0-9_-]{1,32}")
STATIC_FIELDS = ("name", "source", "stream_id", "max_fps", "event_log", "replay_fps")
RESTART_FIELDS = ("model", "threads", "bind", "port", "conf", "alarm_conf", "iou", "debounce", "cooldown", "view_width",
                  "event_log_dir")


def _is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_config(config):
    """설정을 검사한다. 틀리면 ValueError 를 내고 아무것도 바꾸지 않는다."""
    if not isinstance(config, dict):
        raise ValueError("설정은 JSON 객체여야 합니다")
    for key in RATIO_FIELDS:
        if key in config and (not _is_number(config[key]) or not 0 <= config[key] <= 1):
            raise ValueError(f"{key} 는 0~1 숫자여야 합니다")
    if "cooldown" in config and (not _is_number(config["cooldown"]) or config["cooldown"] < 0):
        raise ValueError("cooldown 은 0 이상 숫자여야 합니다")
    for key in INTEGER_FIELDS:
        if key in config and (not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 0):
            raise ValueError(f"{key} 는 0 이상 정수여야 합니다")
    cameras = config.get("cameras")
    if not isinstance(cameras, list) or len(cameras) > MAX_CAMERAS:
        raise ValueError(f"cameras 는 {MAX_CAMERAS}개 이하 목록이어야 합니다")
    seen = set()
    for entry in cameras:
        if not isinstance(entry, dict):
            raise ValueError("카메라 항목은 JSON 객체여야 합니다")
        camera_id = entry.get("id")
        if not isinstance(camera_id, str) or not ID_PATTERN.fullmatch(camera_id):
            raise ValueError(f"카메라 id 오류: {camera_id}")
        if camera_id in seen:
            raise ValueError(f"카메라 id 중복: {camera_id}")
        seen.add(camera_id)
        ev.source_kind(entry.get("source", ""))
        ev.safe_label(entry.get("source", ""))  # 포트 오타는 여기서 걸러야 화면이 죽지 않는다.
        fps = entry.get("max_fps", 5.0)
        if not _is_number(fps) or not 0 < fps <= MAX_FPS:
            raise ValueError(f"{camera_id}: max_fps 는 0 초과 {MAX_FPS:g} 이하")
    return config


def load_config(path):
    """설정 파일을 읽어 검사한다."""
    with open(path, encoding="utf-8") as f:
        return validate_config(json.load(f))


class CameraViewer(ev.Viewer):
    """보는 사람이 없으면 박스를 그리지 않는다. 판정과 집계는 그대로 한다."""

    def render(self, frame, dets):
        return super().render(frame, dets) if self.clients else None

    def publish(self, view):
        if view is None:
            return
        super().publish(view)
        with self.cond:
            if not self.clients:  # 그리는 사이 마지막 시청자가 나간 경우다.
                self.jpeg = None

    def client_leave(self):
        super().client_leave()
        with self.cond:
            if not self.clients:
                self.jpeg = None


class Camera:
    """카메라 하나의 설정과 현재 실행 상태."""

    def __init__(self, entry):
        self.entry = entry
        self.id = entry["id"]
        self.name = entry.get("name") or self.id
        self.max_fps = float(entry.get("max_fps", 5.0))
        self.state, self.error = "stopped", None
        self.capture, self.viewer, self.run_id = None, None, 0
        self.last_seq, self.next_at, self.ready_at, self.errors, self.last_run = 0, 0.0, None, 0, None

    def changed(self, entry):
        return any(self.entry.get(key) != entry.get(key) for key in STATIC_FIELDS)

    def snapshot(self):
        base = {"id": self.id, "name": self.name, "state": self.state, "error": self.error,
                "max_fps": self.max_fps, "enabled": self.entry.get("enabled", True), "run_id": self.run_id}
        if self.viewer is None:
            return base
        try:
            snap = dict(self.viewer.snapshot(), **base)
        except Exception as e:  # 한 카메라의 값 때문에 전체 상태가 끊기면 안 된다.
            return dict(base, error=f"상태 읽기 실패: {e}")
        recent = self.viewer.recent_t
        idle = time.monotonic() - recent[-1] if recent else None
        if self.state != "running" or idle is None or idle > max(3.0, 2.0 / self.max_fps):
            snap.update(fps_processed=0.0, detect_ms_recent=None)  # 멈췄는데 옛 값이 남으면 안 된다.
        return snap


class Scheduler(threading.Thread):
    """새 프레임이 있고 차례가 된 카메라를 하나씩 추론한다. 가장 오래 기다린 쪽이 먼저다."""

    def __init__(self, manager, detector, conf=0.25, iou=0.7, clock=time.monotonic):
        super().__init__(daemon=True, name="inference")
        self.manager, self.detector, self.conf, self.iou, self.clock = manager, detector, conf, iou, clock
        self.halt = threading.Event()
        self.work = deque()
        self.started_at = clock()
        self.last_work_at, self.faults = None, 0

    def step(self):
        """한 프레임을 처리했으면 True 를 돌려준다."""
        tick = self.clock()
        ready = []
        for camera in self.manager.running():
            if camera.capture.peek()[0] != camera.last_seq and tick >= camera.next_at:
                if camera.ready_at is None:
                    camera.ready_at = tick
                ready.append(camera)
        if not ready:
            return False
        camera = min(ready, key=lambda c: c.next_at)
        capture, viewer = camera.capture, camera.viewer  # 도중에 정지해도 이 실행으로 끝낸다.
        lag, camera.ready_at = tick - camera.ready_at, None
        # 카메라가 늘어 실제 간격이 벌어져도 연속 판정이 끊기지 않게 한다.
        if camera.last_run is not None:
            viewer.debounce.reset_sec = max(1.0, 3.0 / camera.max_fps, 3.0 * (tick - camera.last_run))
        camera.last_run = tick
        # 처리 시각이 아니라 계획 시각에 더한다. 그래야 조금씩 늦어도 지연이 쌓이지 않는다.
        camera.next_at = max((camera.next_at or tick) + 1.0 / camera.max_fps, tick)
        camera.last_seq = capture.peek()[0]
        start = time.perf_counter()
        try:
            frame, camera.last_seq, _ = capture.latest()
            if frame is not None:
                detect_start = time.perf_counter()
                dets = self.detector.detect(frame, conf=self.conf, iou=self.iou)
                detect_s = time.perf_counter() - detect_start
                if self.manager.is_current(camera, viewer):
                    viewer.process(frame, dets, detect_s, time.time())
                camera.errors = 0
        except Exception as e:
            # 입력이 깨져도 다른 카메라를 멈추면 안 된다. 그 카메라만 센다.
            viewer.errors_total += 1
            camera.errors += 1
            logger.error("%s 처리 실패 %s: %s (%d회 연속)", camera.id, type(e).__name__, e, camera.errors)
            if camera.errors >= MAX_ERRORS:
                self.manager.fail(camera, viewer, f"처리가 {camera.errors}회 연속 실패했습니다: {e}")
        self.record(tick, time.perf_counter() - start, lag)
        return True

    def record(self, tick, cycle_s, lag_s):
        self.last_work_at = tick
        self.work.append((tick, cycle_s, lag_s))
        while self.work and tick - self.work[0][0] > WINDOW_SEC:
            self.work.popleft()

    def run(self):
        while not self.halt.is_set():
            try:
                busy = self.step()
            except Exception:
                self.faults += 1
                logger.exception("스케줄러 오류. 계속 돕니다")
                busy = False
            if not busy:
                self.halt.wait(0.005)

    def snapshot(self):
        """최근 구간의 추론 여력을 돌려준다. 수요가 처리 능력을 넘으면 카메라가 나눠 진다."""
        now = self.clock()
        work = [w for w in self.work.copy() if now - w[0] <= WINDOW_SEC]
        cycle = sum(w[1] for w in work) / len(work) if work else None
        capacity = 1.0 / cycle if cycle else None
        running = self.manager.running()
        requested = sum(c.max_fps for c in running)
        # 입력이 끊겼거나 상한보다 느린 카메라는 실제 수요만큼만 센다.
        demand = sum(min(c.max_fps, c.capture.info().get("fps_received") or 0.0) for c in running)
        span = min(WINDOW_SEC, now - self.started_at)
        since = self.last_work_at if self.last_work_at is not None else self.started_at
        slowest = min((c.max_fps for c in running), default=1.0)
        return {"alive": self.is_alive(), "faults": self.faults, "last_work_age_sec": round(now - since, 1),
                "stall_after_sec": round(max(5.0, 2.0 / slowest), 1),
                "frames_in_window": len(work), "cycle_ms": round(cycle * 1000.0, 1) if cycle else None,
                "capacity_fps": round(capacity, 1) if capacity else None, "requested_fps": round(requested, 1),
                "demand_fps": round(demand, 1),
                "busy_ratio": round(min(1.0, sum(w[1] for w in work) / span), 2) if span > 0 else None,
                "lag_ms": round(1000.0 * sum(w[2] for w in work) / len(work), 1) if work else None,
                "overloaded": bool(capacity and demand > capacity * OVERLOAD_RATIO)}


class StreamManager:
    """카메라를 등록하고 시작, 정지, 설정 반영을 맡는다."""

    def __init__(self, config, detector, model_label="", event_log=None, capture_factory=ev.Capture,
                 config_path=None, clock=time.monotonic):
        self.config, self.config_path, self.model_label = config, config_path, model_label
        self.event_log, self.capture_factory = event_log, capture_factory
        self.conf, self.alarm_conf = config.get("conf", 0.25), config.get("alarm_conf", 0.5)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.cameras = {}
        self.retired = []
        self.next_run = int(time.time() * 1000)
        self.names = getattr(detector, "names", {})
        self.detector = detector
        self.scheduler = Scheduler(self, detector, self.conf, config.get("iou", 0.7), clock)
        self.resources = ResourceMonitor()
        for entry in config["cameras"]:
            self.cameras[entry["id"]] = Camera(entry)

    def running(self):
        with self.lock:
            return [c for c in self.cameras.values() if c.state == "running"]

    def is_current(self, camera, viewer):
        with self.lock:
            return camera.state == "running" and camera.viewer is viewer

    def start_camera(self, camera_id):
        with self.lock:
            if self.stop_event.is_set():
                raise ValueError("종료 중입니다")
            camera = self.cameras[camera_id]
            if camera.state == "running":
                return camera
            entry = camera.entry
            label = ev.safe_label(entry["source"])
            capture = self.capture_factory(entry["source"], replay_fps=entry.get("replay_fps", camera.max_fps))
            capture.name = f"capture-{camera.id}"
            viewer = CameraViewer(self.detector, capture, conf=self.conf, alarm_conf=self.alarm_conf,
                                  debounce=self.config.get("debounce", 3), cooldown=self.config.get("cooldown", 5.0),
                                  max_fps=camera.max_fps, view_width=self.config.get("view_width", 720),
                                  stale_sec=max(3.0, 2.0 / camera.max_fps),
                                  stream_id=entry.get("stream_id", camera.id), model_label=self.model_label,
                                  event_log=self.event_log if entry.get("event_log") else None)
            viewer.debounce.reset_sec = max(1.0, 3.0 / camera.max_fps)  # 5 fps 이상에서는 원래 1초다.
            capture.start()  # 시작에 실패하면 카메라 상태를 건드리지 않는다.
            self.next_run += 1
            camera.capture, camera.viewer, camera.run_id = capture, viewer, self.next_run
            camera.last_seq, camera.next_at, camera.ready_at, camera.errors, camera.error = 0, 0.0, None, 0, None
            camera.last_run, camera.state = None, "running"
            logger.info("카메라 시작: %s (%s, %s fps)", camera.id, label, camera.max_fps)
            return camera

    def _start_safely(self, camera_id):
        """시작 실패는 그 카메라의 오류로 남긴다. 다른 카메라는 계속 시작한다."""
        try:
            self.start_camera(camera_id)
        except Exception as e:
            camera = self.cameras[camera_id]
            camera.state, camera.error = "error", f"시작 실패: {e}"
            logger.error("카메라 시작 실패 %s: %s", camera_id, e)

    def _halt(self, camera, state, error=None):
        camera.state, camera.error = state, error
        if camera.capture is not None:
            camera.capture.halt.set()
            self.retired = [c for c in self.retired if c.is_alive() and c is not camera.capture] + [camera.capture]
        if camera.viewer is not None:
            camera.viewer.stop.set()

    def stop_camera(self, camera_id):
        with self.lock:
            camera = self.cameras[camera_id]
            self._halt(camera, "stopped")
            logger.info("카메라 정지: %s", camera.id)
            return camera

    def fail(self, camera, viewer, message):
        """한 카메라만 멈춘다. 그 사이 정지했거나 다시 시작했으면 건드리지 않는다."""
        with self.lock:
            if camera.state != "running" or camera.viewer is not viewer:
                return
            logger.error("카메라 오류로 정지: %s: %s", camera.id, message)
            self._halt(camera, "error", message)

    def reload(self):
        """설정 파일을 다시 읽어 바뀐 카메라만 반영한다. 파일이 틀리면 아무것도 안 바꾼다."""
        config = load_config(self.config_path)
        entries = {entry["id"]: entry for entry in config["cameras"]}
        ignored = [key for key in RESTART_FIELDS if config.get(key) != self.config.get(key)]
        with self.lock:
            for camera_id in [c for c in self.cameras if c not in entries]:
                self.stop_camera(camera_id)
                del self.cameras[camera_id]
            for camera_id, entry in entries.items():
                old = self.cameras.get(camera_id)
                if old is not None and not old.changed(entry) and old.entry.get("enabled", True) == entry.get("enabled", True):
                    continue
                if old is not None:
                    self.stop_camera(camera_id)
                self.cameras[camera_id] = Camera(entry)
                if entry.get("enabled", True):
                    self._start_safely(camera_id)
            self.config = dict(self.config, cameras=config["cameras"])
        return {"cameras": self.camera_ids(), "restart_needed": ignored}

    def camera_ids(self):
        with self.lock:
            return list(self.cameras)

    def start(self):
        self.resources.start()
        self.scheduler.start()
        for entry in self.config["cameras"]:
            if entry.get("enabled", True):
                self._start_safely(entry["id"])

    def shutdown(self, wait_sec=7.0):
        self.stop_event.set()
        self.scheduler.halt.set()
        self.resources.halt.set()
        with self.lock:
            for camera in self.cameras.values():
                self._halt(camera, "stopped")
            threads = list(self.retired)
        deadline = time.monotonic() + wait_sec
        for thread in [self.scheduler, *threads]:
            if thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        left = [t.name for t in threads if t.is_alive()]
        if left:
            logger.warning("끝나지 않은 스레드: %s", left)

    def snapshot(self):
        with self.lock:
            cameras = [c.snapshot() for c in self.cameras.values()]
            leftover = [c.name for c in self.retired if c.is_alive()]
        return {"observe_only": True, "model": self.model_label, "cameras": cameras, "leftover_threads": leftover,
                "scheduler": self.scheduler.snapshot(), "resources": self.resources.snapshot()}


PAGE_PATH = os.path.join(HERE, "stream_page.html")


def make_handler(manager):
    with open(PAGE_PATH, encoding="utf-8") as f:
        page = f.read().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        timeout = 5  # 본문을 안 보내는 연결이 스레드를 쥐고 있지 못하게 한다. 영상은 자기 제한을 쓴다.

        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            super().end_headers()

        def _json(self, code, value):
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def _path(self):
            try:
                return urlsplit(self.path).path
            except ValueError:
                return ""  # 어떤 경로와도 맞지 않아 404 로 끝난다.

        def _host_ok(self):
            """다른 사이트가 이름을 127.0.0.1 로 돌리거나 브라우저로 요청을 보내는 것을 막는다."""
            origin = self.headers.get("Origin")
            site = self.headers.get("Sec-Fetch-Site", "").lower()
            # 다른 페이지의 링크로 화면만 여는 것은 받는다. 이 응답에는 프레임이 없고 끼워 넣기는 막힌다.
            navigate = (self.command == "GET" and self._path() == "/"
                        and self.headers.get("Sec-Fetch-Mode") == "navigate"
                        and self.headers.get("Sec-Fetch-Dest") == "document")
            try:
                host = urlsplit("//" + self.headers.get("Host", "")).hostname
                origin_ok = origin is None or urlsplit(origin).hostname in ALLOWED_HOSTS
            except ValueError:
                host, origin_ok = None, False
            if host in ALLOWED_HOSTS and origin_ok and (navigate or site not in CROSS_SITE):
                return True
            self._json(403, {"detail": "허용하지 않는 요청"})
            return False

        def _peer_gone(self):
            """프레임이 없어 쓰지 않는 동안에도 끊긴 시청자를 찾아낸다."""
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def do_GET(self):
            if not self._host_ok():
                return
            path = self._path()
            parts = path.strip("/").split("/")
            if path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(200, manager.snapshot())
            elif len(parts) == 3 and parts[0] == "cameras" and parts[2] == "stream.mjpg":
                self._stream(parts[1])
            else:
                self._json(404, {"detail": "없는 경로"})

        def do_POST(self):
            if not self._host_ok():
                return
            # 부분 문자열로 보면 text/plain; application/json 이 사전 요청 없이 들어온다.
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._json(415, {"detail": "application/json 필요"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._json(400, {"detail": "Content-Length 오류"})
                return
            if not 0 <= length <= BODY_LIMIT:
                self._json(413, {"detail": "요청 길이 오류"})
                return
            self.rfile.read(length)
            parts = self._path().strip("/").split("/")
            try:
                if parts == ["api", "reload"]:
                    self._json(200, manager.reload())
                elif len(parts) == 4 and parts[:2] == ["api", "cameras"] and parts[3] == "start":
                    self._json(200, {"state": manager.start_camera(parts[2]).state})
                elif len(parts) == 4 and parts[:2] == ["api", "cameras"] and parts[3] == "stop":
                    self._json(200, {"state": manager.stop_camera(parts[2]).state})
                else:
                    self._json(404, {"detail": "없는 경로"})
            except KeyError:
                self._json(404, {"detail": "없는 카메라"})
            except (ValueError, OSError) as e:
                self._json(400, {"detail": str(e)})
            except Exception as e:  # 응답 없이 끊기면 화면이 실패를 알 수 없다.
                logger.exception("요청 처리 실패")
                self._json(500, {"detail": f"처리 실패: {e}"})

        def _refuse(self):
            self._json(405, {"detail": "허용하지 않는 요청"})

        do_PUT = do_DELETE = do_PATCH = _refuse

        def _stream(self, camera_id):
            with manager.lock:
                camera = manager.cameras.get(camera_id)
                viewer = camera.viewer if camera is not None and camera.state == "running" else None
            if viewer is None:
                self._json(404, {"detail": "돌고 있지 않은 카메라"})
                return
            if not viewer.client_enter():
                self._json(503, {"detail": "시청자가 너무 많습니다"})
                return
            try:
                self.connection.settimeout(ev.WRITE_TIMEOUT_SEC)
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seen = -1
                while not viewer.stop.is_set() and not manager.stop_event.is_set():
                    jpeg, seen = viewer.wait_jpeg(seen)
                    if jpeg is None:
                        if self._peer_gone():
                            break
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except OSError:
                pass
            finally:
                viewer.client_leave()

    return Handler


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="여러 카메라 관측 전용 스트림 관리자")
    ap.add_argument("--config", default=os.path.join(HERE, "cameras.json"))
    ap.add_argument("--duration", type=float, default=0, help="N초 뒤 끝낸다 (0 = 끝내지 않음)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    # 충돌 코어에 프레임이 남지 않게 한다. 프레임을 디스크에 쓰지 않는다는 약속의 일부다.
    if ctypes.CDLL(None).prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError("코어 덤프를 끄지 못했습니다")
    config = load_config(a.config)
    bind, port = config.get("bind", "127.0.0.1"), config.get("port", 8893)
    ev.check_bind(bind, False)
    model = config["model"]
    detector = ev.load_detector(model, config.get("threads", 2))
    bin_path = os.path.join(model, "best.bin")
    label = f"{os.path.basename(os.path.normpath(model))} {ev.file_sha256(bin_path)[:8]}"
    event_log = None
    if config.get("event_log_dir"):
        folder = os.path.expanduser(config["event_log_dir"])
        os.makedirs(folder, exist_ok=True)
        event_log = os.path.join(folder, time.strftime("view-events-%Y%m%d-%H%M%S.jsonl"))
    manager = StreamManager(config, detector, label, event_log, config_path=a.config)
    server = ev.Server((bind, port), make_handler(manager))
    logger.info("OBSERVE-ONLY. 모델 %s, 카메라 %d대, http://%s:%d/", label, len(config["cameras"]), bind, port)

    stopping = []

    def finish(*_):
        stopping.append(True)  # 처리기에서는 잠금을 쓰지 않는다. Event.set 은 교착할 수 있다.

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    manager.start()
    threading.Thread(target=server.serve_forever, daemon=True, name="http-server").start()
    deadline = time.monotonic() + a.duration if a.duration else None
    while not stopping and not (deadline and time.monotonic() >= deadline):
        time.sleep(0.2)
    server.shutdown()
    manager.shutdown()
    logger.info("끝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
