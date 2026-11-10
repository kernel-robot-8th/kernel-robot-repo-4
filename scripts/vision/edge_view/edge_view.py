#!/usr/bin/env python3
"""모델 B 관측 전용 웹 뷰어 (홈랩 2026-11-07).

영상 입력 하나에 OpenVINO 모델을 돌려 검출 박스를 그린 화면을 웹으로 보여 준다.

    python edge_view.py --source <주소 또는 녹화 파일> --model <모델 폴더>

입력: rtsp:// · http(s):// 스트림, 영상 파일, 녹화 zip(frames/*.jpg), 이미지 폴더.
장치(/dev/video*, 숫자)는 거부한다. 발행 중인 스트림이나 파일만 읽는다.

http:// multipart 는 직접 읽고 JPEG 을 cv2.imdecode 로 푼다. OpenCV FFmpeg 경로는 스트림 중간에
프레임이 90도 돌아가면 그림을 옛 크기로 늘려 돌려준다(11-07 재현). 크기가 맞아 보이면 제외 영역까지 틀린다.
Content-Length 가 없거나 multipart 가 아니면 FFmpeg 로 내려간다. rtsp 와 https 는 FFmpeg 로 읽는다.

지키는 것
- 관측 전용: MQTT, ROS, 관제 명령이 없다. 확정 이벤트는 숫자만 JSONL 로 남긴다.
- 프레임을 디스크에 쓰지 않는다(FD-16). 박스를 그린 JPEG 은 메모리에서만 내보낸다.
- 기본 바인드는 127.0.0.1 이다. 프레임에 사람이 찍힐 수 있어서다.
- 경보 판정은 중계 재생 규칙과 같다: 클래스 0~3, 0.5 이상, 제외 영역 밖, 연속 3프레임, 클래스별 5초 쿨다운.

표시 문턱(--conf, 기본 0.25)은 경보 문턱(--alarm-conf, 기본 0.5)보다 낮다. 낮은 점수도 눈으로 보려는 것이다.
"""
import argparse
import base64
from collections import Counter, defaultdict, deque
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import signal
import sys
import threading
import time
from urllib.parse import urlsplit
import zipfile

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("edge_view")

HERE = os.path.dirname(os.path.abspath(__file__))
ALARM_CLASS_NAMES = ("box_on_floor", "box_perched_on_rim", "box_run_over", "lid_detached")
# 중계 워커와 같은 제외 영역. 좌표는 1080x1440 프레임 기준이라 다른 크기에서는 적용하지 않는다.
DEFAULT_ROI = ((410, 590, 455, 630), (315, 925, 355, 965), (845, 530, 885, 570))
ROI_FRAME = (1080, 1440)
ROI_ROTATION = 90  # 녹화 session.json 의 rotationDegrees. 270 은 크기가 같아서 크기로는 못 가린다.
ROI_LENS = "ULTRA_WIDE"  # 렌즈가 바뀌면 크기와 회전이 같아도 화각이 달라 제외 영역 자리가 틀린다.
IMAGE_EXT = (".jpg", ".jpeg", ".png")
MAX_LINE = 8192
MAX_PART = 16 * 1024 * 1024
MAX_CLIENTS = 4
WRITE_TIMEOUT_SEC = 10.0  # 읽기를 멈춘 브라우저가 시청 슬롯을 계속 잡지 못하게 한다.
SHORT ={"box_on_floor": "floor", "box_perched_on_rim": "rim", "box_run_over": "runover",
         "lid_detached": "lid", "box_on_tray": "tray", "box_stock": "stock"}
COLOR = {"box_on_floor": (40, 40, 240), "box_perched_on_rim": (0, 140, 255), "box_run_over": (200, 40, 220),
         "lid_detached": (0, 220, 255), "box_on_tray": (80, 220, 80), "box_stock": (240, 170, 60)}


# 사용자가 11-07에 확인을 요청한 USB 웹캠 하나만 연다. 내장 카메라와 다른 장치는 계속 거부한다.
USB_WEBCAM = "/dev/v4l/by-id/usb-GENERAL_GENERAL_WEBCAM-video-index0"
USB_WEBCAM_SIZE = (1280, 720)
ALLOWED_DEVICES = {USB_WEBCAM: USB_WEBCAM_SIZE}
DEVICE_DECODE_FPS = 10.0


def source_kind(src):
    """입력 종류를 돌려준다. 장치는 USB_WEBCAM 하나만 받는다(다른 장치는 다른 서비스가 쓴다)."""
    s = str(src)
    if s in ALLOWED_DEVICES:
        return "device"
    if s.isdigit() or s.startswith("/dev/"):
        raise ValueError(f"장치는 직접 열지 않습니다: {s}. 발행 중인 스트림 주소나 녹화 파일을 주세요.")
    if urlsplit(s).scheme.lower() in ("rtsp", "rtsps", "http", "https"):
        return "stream"
    if os.path.isdir(s):
        return "dir"
    if os.path.isfile(s):
        return "zip" if s.lower().endswith(".zip") else "video"
    raise ValueError(f"입력을 찾을 수 없습니다: {s}")


def safe_label(src):
    """화면과 로그에 쓰는 입력 이름. 주소의 계정과 쿼리는 뺀다."""
    u = urlsplit(str(src))
    if u.scheme.lower() in ("rtsp", "rtsps", "http", "https"):
        host = u.hostname or ""
        port = f":{u.port}" if u.port else ""
        return f"{u.scheme}://{host}{port}{u.path}"
    return os.path.basename(str(src).rstrip("/\\")) or str(src)


def check_bind(host, allow_nonlocal):
    if host in ("127.0.0.1", "::1", "localhost") or allow_nonlocal:
        return
    raise ValueError(f"{host} 바인드는 거부합니다. 프레임에 사람이 찍힐 수 있습니다. 꼭 필요하면 --allow-nonlocal 을 줍니다.")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def in_roi(bbox, rois):
    cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    return any(x1 <= cx <= x2 and y1 <= cy <= y2 for x1, y1, x2, y2 in rois)


class NoContentLength(ValueError):
    """파트에 Content-Length 가 없다. 이 읽기로는 본문 끝을 알 수 없다."""


def read_part(fp):
    """multipart 파트 하나를 읽어 (헤더, 본문)을 돌려준다. 헤더 이름은 소문자다. 본문은 Content-Length 로 자른다."""
    skipped = 0
    while True:
        line = fp.readline(MAX_LINE)
        if not line:
            raise EOFError("스트림이 끝났습니다")
        if line.startswith(b"--"):
            if line.rstrip().endswith(b"--"):
                raise EOFError("닫는 경계를 받았습니다")
            break
        skipped += len(line)
        if skipped > MAX_LINE:
            raise ValueError("경계 줄을 찾지 못했습니다")
    headers = {}
    while True:
        line = fp.readline(MAX_LINE)
        if not line:
            raise EOFError("파트 헤더 중간에 끊겼습니다")
        line = line.strip()
        if not line:
            break
        key, _, value = line.partition(b":")
        headers[key.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
    if "content-length" not in headers:
        raise NoContentLength("Content-Length 가 없습니다")
    n = int(headers["content-length"])
    if not 0 < n <= MAX_PART:
        raise ValueError(f"파트 크기가 이상합니다: {n}")
    body = fp.read(n)
    if len(body) != n:
        raise EOFError("본문 중간에 끊겼습니다")
    return headers, body


class Debounce:
    """같은 클래스가 연속 N프레임 나와야 확정한다. 중계 워커의 11-02 패치와 같은 규칙이다(클래스는 프레임당 한 번만 센다)."""

    def __init__(self, frames=3, reset_sec=1.0):
        self.frames, self.reset_sec = frames, reset_sec
        self.count, self.last = defaultdict(int), defaultdict(float)

    def update(self, dets, now):
        for name in list(self.count):
            if now - self.last[name] > self.reset_sec:
                self.count[name] = 0
        best = {}
        for d in dets:
            if d["event_type"] not in best or d["confidence"] > best[d["event_type"]]["confidence"]:
                best[d["event_type"]] = d
        confirmed = []
        for name, d in best.items():
            self.count[name] += 1
            self.last[name] = now
            if self.count[name] >= self.frames:
                confirmed.append(dict(d, consecutive_frames=self.count[name]))
        for name in list(self.count):
            if name not in best:
                self.count[name] = max(0, self.count[name] - 1)
        return confirmed


class ReplayFrames:
    """녹화 zip 또는 이미지 폴더를 파일 이름 순서로 되풀이한다. 메모리에서만 푼다."""

    def __init__(self, path, kind):
        self.path, self.kind, self.i = path, kind, 0
        if kind == "zip":
            self.zip = zipfile.ZipFile(path)
            names = self.zip.namelist()
        else:
            self.zip = None
            # 이름만 .jpg 인 링크로 장치를 열지 못하게 일반 파일만 받는다.
            names = [n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))]
        self.names = sorted(n for n in names if n.lower().endswith(IMAGE_EXT))
        if not self.names:
            raise ValueError(f"이미지가 없습니다: {path}")

    def next(self):
        name = self.names[self.i % len(self.names)]
        self.i += 1
        if self.zip is not None:
            raw = self.zip.read(name)
        else:
            with open(os.path.join(self.path, name), "rb") as f:
                raw = f.read()
        try:
            return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            return None  # 한 장이 깨져도 처음으로 되돌아가지 않고 다음 파일로 넘어간다.

    def close(self):
        if self.zip is not None:
            self.zip.close()


class Capture(threading.Thread):
    """최신 프레임 하나만 들고 있는다. 끊기면 다시 붙는다."""

    def __init__(self, source, replay_fps=5.0, reconnect_sec=3.0, timeout_ms=5000):
        super().__init__(daemon=True)
        self.source, self.kind = source, source_kind(source)
        self.replay_fps, self.reconnect_sec, self.timeout_ms = replay_fps, reconnect_sec, timeout_ms
        self.halt = threading.Event()
        self.lock = threading.Lock()
        self.frame, self.raw, self.seq, self.frame_time, self.good_time = None, None, 0, 0.0, 0.0
        self.connected, self.reconnects, self.bad_frames = False, 0, 0
        self.force_ffmpeg, self.http_status = False, None
        self.transport = "file" if self.kind in ("zip", "dir", "video") else "stream"
        self.arrivals = deque(maxlen=30)
        self.rotation, self.lens, self.zoom, self.session = None, None, None, None
        self.session_changes, self.capture_lag_ms = 0, None

    def _put(self, frame):
        with self.lock:
            self.frame, self.raw, self.seq = frame, None, self.seq + 1
            self.frame_time = self.good_time = time.time()
            self.arrivals.append(time.monotonic())

    def _put_raw(self, jpeg, headers):
        """풀지 않은 JPEG 을 받아 둔다. 읽기는 폰 속도로 계속하고, 푸는 것은 추론이 가져갈 때만 한다."""
        now = time.time()
        with self.lock:
            self.raw, self.seq, self.frame_time = jpeg, self.seq + 1, now
            self.arrivals.append(time.monotonic())
            session = headers.get("x-publisher-session")
            if session and self.session and session != self.session:
                self.session_changes += 1
                logger.warning("앱 세션이 바뀌었습니다. 회전이나 카메라 설정이 바뀌었을 수 있습니다.")
            self.session = session or self.session
            self.lens = headers.get("x-camera-lens", self.lens)
            self.zoom = headers.get("x-camera-zoom", self.zoom)
            if headers.get("x-camera-rotation", "").lstrip("-").isdigit():
                self.rotation = int(headers["x-camera-rotation"])
            if headers.get("x-capture-clock", "").isdigit():
                self.capture_lag_ms = int(now * 1000) - int(headers["x-capture-clock"])

    def peek(self):
        """프레임을 풀지 않고 번호와 마지막으로 풀린 프레임의 시각을 본다. 깨진 JPEG 만 오면 시각이 안 늘어나 멈춤으로 보인다."""
        with self.lock:
            return self.seq, self.good_time

    def latest(self):
        with self.lock:
            raw, self.raw = self.raw, None
            frame, seq, t = self.frame, self.seq, self.frame_time
        if raw is None:
            return frame, seq, t
        try:
            frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            frame = None  # 크기 한도를 넘긴 JPEG 은 예외로 온다. 깨진 프레임으로 센다.
        with self.lock:
            if frame is None:
                self.bad_frames += 1
            else:
                self.frame, self.good_time = frame, t
        return frame, seq, t

    def info(self):
        with self.lock:
            now = time.monotonic()
            recent = [t for t in self.arrivals if now - t <= 5.0]  # 멈추면 0 으로 내려가야 한다.
            span = recent[-1] - recent[0] if len(recent) > 1 else 0.0
            return {"transport": self.transport, "http_status": self.http_status,
                    "fps_received": round((len(recent) - 1) / span, 2) if span > 0 else 0.0,
                    "rotation": self.rotation, "lens": self.lens, "zoom": self.zoom,
                    "session_changes": self.session_changes, "capture_lag_ms": self.capture_lag_ms}

    def run(self):
        while not self.halt.is_set():
            try:
                if self.kind in ("zip", "dir"):
                    self._replay()
                elif urlsplit(self.source).scheme.lower() == "http" and not self.force_ffmpeg:
                    self._capture_http()
                else:
                    self._capture()
            except Exception as e:  # 입력 하나가 깨져도 뷰어는 살아서 끊김을 보여 준다.
                logger.warning("입력 오류 %s: %s", type(e).__name__, e)
            self.connected = False
            if not self.halt.is_set():
                self.reconnects += 1
                self.halt.wait(self.reconnect_sec)
        with self.lock:
            self.frame, self.raw = None, None  # 멈춘 카메라가 마지막 프레임을 메모리에 쥐고 있지 않게 한다.

    def _replay(self):
        rep = ReplayFrames(self.source, self.kind)
        self.connected = True
        try:
            while not self.halt.is_set():
                frame = rep.next()
                if frame is None:
                    self.bad_frames += 1
                else:
                    self._put(frame)
                self.halt.wait(1.0 / max(self.replay_fps, 0.1))
        finally:
            rep.close()

    def _capture_http(self):
        u = urlsplit(self.source)
        logger.info("입력 연결: %s", safe_label(self.source))
        self.http_status = None
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=self.timeout_ms / 1000.0)
        resp = None
        try:
            headers = {"User-Agent": "edge-view", "Accept": "multipart/x-mixed-replace"}
            if u.username is not None:
                token = base64.b64encode(f"{u.username}:{u.password or ''}".encode()).decode()
                headers["Authorization"] = f"Basic {token}"
            conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""), headers=headers)
            resp = conn.getresponse()
            self.http_status = resp.status
            if resp.status != 200:
                logger.warning("입력이 HTTP %d 로 거절했습니다: %s", resp.status, safe_label(self.source))
                return
            ctype = (resp.getheader("Content-Type") or "").lower()
            if not ctype.startswith("multipart/"):
                logger.warning("multipart 가 아닙니다(%s). FFmpeg 로 읽습니다.", ctype.split(";")[0])
                self.force_ffmpeg = True
                return
            self.transport = "http-multipart"
            while not self.halt.is_set():
                part_headers, body = read_part(resp)
                self.connected = True  # 200 만으로는 영상이 오는 것이 아니다. 첫 프레임에서 켠다.
                self._put_raw(body, part_headers)
        except NoContentLength as e:
            logger.warning("%s. FFmpeg 로 읽습니다.", e)
            self.force_ffmpeg = True
        finally:
            # Connection: close 응답은 소켓이 resp 로 넘어간다. 안 닫으면 폰의 쓰기가 막힐 수 있다.
            if resp is not None:
                resp.close()
            conn.close()

    def _capture_device(self):
        """USB 웹캠을 V4L2로 읽는다. 프레임은 메모리에만 둔다."""
        logger.info("입력 연결: %s", safe_label(self.source))
        self.transport = "v4l2"
        cap = cv2.VideoCapture(os.path.realpath(self.source), cv2.CAP_V4L2)
        try:
            if not cap.isOpened():
                logger.warning("입력을 열지 못했습니다: %s", safe_label(self.source))
                return
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            width, height = ALLOWED_DEVICES[self.source]
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.connected = True
            next_decode = 0.0
            while not self.halt.is_set():
                if not cap.grab():
                    logger.warning("프레임을 읽지 못했습니다. 다시 연결합니다.")
                    return
                now = time.monotonic()
                if now < next_decode:  # 받기만 하고 풀지 않는다. MJPEG 풀기가 CPU 를 쓴다.
                    continue
                next_decode = now + 1.0 / DEVICE_DECODE_FPS
                ok, frame = cap.retrieve()
                if not ok:
                    logger.warning("프레임을 풀지 못했습니다. 다시 연결합니다.")
                    return
                self._put(frame)
        finally:
            cap.release()

    def _capture(self):
        if self.kind == "device":
            self._capture_device()
            return
        logger.info("입력 연결: %s", safe_label(self.source))
        self.transport = "ffmpeg" if self.kind == "stream" else "file"
        cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                               [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.timeout_ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.timeout_ms])
        try:
            if not cap.isOpened():
                logger.warning("입력을 열지 못했습니다: %s", safe_label(self.source))
                return
            self.connected = True
            fps = cap.get(cv2.CAP_PROP_FPS) if self.kind == "video" else 0
            pace = 1.0 / fps if fps and fps > 0 else (1.0 / max(self.replay_fps, 0.1) if self.kind == "video" else 0)
            while not self.halt.is_set():
                ok, frame = cap.read()
                if not ok:
                    logger.warning("프레임을 읽지 못했습니다. 다시 연결합니다.")
                    return
                self._put(frame)
                if pace:
                    self.halt.wait(pace)
        finally:
            cap.release()


class Viewer:
    """추론, 경보 판정, 화면 그리기, 상태를 맡는다."""

    def __init__(self, detector, capture, *, conf=0.25, alarm_conf=0.5, iou=0.7, debounce=3, cooldown=5.0, max_fps=5.0,
                 view_width=720, jpeg_quality=75, stale_sec=3.0, stream_id="CAM_CEILING_01", event_log=None, model_label="",
                 stats_sec=30.0, max_errors=20):
        self.det, self.capture = detector, capture
        self.conf, self.alarm_conf, self.iou, self.cooldown = conf, alarm_conf, iou, cooldown
        self.max_fps, self.view_width, self.jpeg_quality, self.stale_sec = max_fps, view_width, jpeg_quality, stale_sec
        self.stream_id, self.event_log, self.model_label = stream_id, event_log, model_label
        self.stats_sec, self.max_errors = stats_sec, max_errors
        self.debounce = Debounce(debounce)
        self.last_event = {}
        self.stop = threading.Event()
        self.fatal = None
        self.cond = threading.Condition()
        self.jpeg, self.jpeg_seq = None, 0
        self.clients = 0
        self.started = time.time()
        self.frames, self.errors_total, self.infer_s = 0, 0, 0.0
        self.recent_ms = deque(maxlen=30)
        self.recent_t = deque(maxlen=30)
        self.size, self.roi_on = None, False
        self.current = []
        self.seen_display, self.seen_alarm_conf = Counter(), Counter()
        self.max_conf = defaultdict(float)
        self.events = deque(maxlen=50)
        self.event_total = Counter()

    # 판정
    def judge(self, dets, size):
        """검출에 표시 정보를 붙이고, 경보 후보만 돌려준다."""
        info = self.capture.info()
        self.roi_on = size == ROI_FRAME and info.get("rotation") in (None, ROI_ROTATION) and info.get("lens") in (None, ROI_LENS)
        cands = []
        for d in dets:
            d["alarm_class"] = d["event_type"] in ALARM_CLASS_NAMES
            d["in_roi"] = self.roi_on and in_roi(d["bbox"], DEFAULT_ROI)
            if d["alarm_class"] and d["confidence"] >= self.alarm_conf and not d["in_roi"]:
                cands.append(d)
        return cands

    def emit(self, d, now):
        name = d["event_type"]
        if name in self.last_event and now - self.last_event[name] < self.cooldown:
            return None
        self.last_event[name] = now
        payload = {"timestamp": now, "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                   "stream_id": self.stream_id, "event_type": name, "confidence": round(float(d["confidence"]), 4),
                   "bbox": [round(float(v), 2) for v in d["bbox"]], "action_required": "NONE", "mode": "observe_only",
                   "consecutive_frames": d.get("consecutive_frames", 1), "model": self.model_label}
        self.events.appendleft(payload)
        self.event_total[name] += 1
        if self.event_log:
            try:
                with open(self.event_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except OSError as e:
                logger.error("이벤트 기록 실패: %s", e)
        return payload

    # 화면
    def render(self, frame, dets):
        h, w = frame.shape[:2]
        scale = min(1.0, self.view_width / float(w)) if self.view_width else 1.0
        if scale < 1.0:
            view = cv2.resize(frame, (max(int(w * scale), 1), max(int(h * scale), 1)), interpolation=cv2.INTER_AREA)
        else:
            view = frame.copy()
        if self.roi_on:
            for x1, y1, x2, y2 in DEFAULT_ROI:
                cv2.rectangle(view, (int(x1 * scale), int(y1 * scale)), (int(x2 * scale), int(y2 * scale)), (150, 150, 150), 1)
        for d in sorted(dets, key=lambda x: x["confidence"]):
            x1, y1, x2, y2 = (int(v * scale) for v in d["bbox"])
            color = (160, 160, 160) if d["in_roi"] else COLOR.get(d["event_type"], (255, 255, 255))
            strong = d["alarm_class"] and d["confidence"] >= self.alarm_conf and not d["in_roi"]
            cv2.rectangle(view, (x1, y1), (x2, y2), color, 3 if strong else 1)
            label = f'{SHORT.get(d["event_type"], d["event_type"])} {d["confidence"]:.2f}'
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            ty = y1 - 4 if y1 - th - 6 > 0 else y2 + th + 4
            cv2.rectangle(view, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), color, -1)
            cv2.putText(view, label, (x1 + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        return view

    def publish(self, view):
        ok, buf = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            return
        with self.cond:
            self.jpeg, self.jpeg_seq = buf.tobytes(), self.jpeg_seq + 1
            self.cond.notify_all()

    def wait_jpeg(self, seen, timeout=2.0):
        with self.cond:
            if self.jpeg_seq == seen:
                self.cond.wait(timeout)
            return self.jpeg, self.jpeg_seq

    # 한 프레임
    def process(self, frame, dets, infer_s, now):
        h, w = frame.shape[:2]
        self.size = (w, h)
        for d in self.debounce.update(self.judge(dets, (w, h)), now):
            self.emit(d, now)
        self.frames += 1
        self.infer_s += infer_s
        self.recent_ms.append(infer_s * 1000.0)
        self.recent_t.append(time.monotonic())
        for name in {d["event_type"] for d in dets}:
            self.seen_display[name] += 1
        for name in {d["event_type"] for d in dets if d["confidence"] >= self.alarm_conf}:
            self.seen_alarm_conf[name] += 1
        for d in dets:
            self.max_conf[d["event_type"]] = max(self.max_conf[d["event_type"]], d["confidence"])
        self.current = [{"event_type": d["event_type"], "confidence": round(d["confidence"], 3), "in_roi": d["in_roi"],
                         "bbox": [round(v, 1) for v in d["bbox"]]} for d in sorted(dets, key=lambda x: -x["confidence"])][:30]
        self.publish(self.render(frame, dets))

    def loop(self):
        last_seq, last_infer, errors = 0, 0.0, 0
        stats_t, stats_frames, stats_infer = time.monotonic(), 0, 0.0
        while not self.stop.is_set():
            tick = time.monotonic()
            if tick - stats_t >= self.stats_sec:
                n, s = self.frames - stats_frames, self.infer_s - stats_infer
                logger.info("[stats] %d frames in %.1fs, mean detect %s, frame %s, connected %s, frame age %s", n, tick - stats_t,
                            f"{1000.0 * s / n:.1f} ms" if n else "n/a", self.size, self.capture.connected, self.frame_age())
                stats_t, stats_frames, stats_infer = tick, self.frames, self.infer_s
            seq, _ = self.capture.peek()
            if seq == last_seq:
                self.stop.wait(0.01)
                continue
            if self.max_fps > 0 and tick - last_infer < 1.0 / self.max_fps:
                self.stop.wait(0.005)
                continue
            frame, seq, _ = self.capture.latest()
            last_seq, last_infer = seq, tick
            if frame is None:
                continue
            t0 = time.perf_counter()
            try:
                dets = self.det.detect(frame, conf=self.conf, iou=self.iou)
                errors = 0
            except Exception as e:
                errors += 1
                self.errors_total += 1
                logger.error("검출 실패 %s: %s (%d회 연속)", type(e).__name__, e, errors)
                if errors >= self.max_errors:
                    self.fatal = f"검출이 {errors}회 연속 실패했습니다: {e}"
                    self.stop.set()
                continue
            self.process(frame, dets, time.perf_counter() - t0, time.time())

    def frame_age(self):
        _, t = self.capture.peek()
        return round(time.time() - t, 1) if t else None

    def snapshot(self):
        age = self.frame_age()
        span = self.recent_t[-1] - self.recent_t[0] if len(self.recent_t) > 1 else 0.0
        names = list(getattr(self.det, "names", {}).values())
        return {
            "observe_only": True, "model": self.model_label, "source": safe_label(self.capture.source), "source_kind": self.capture.kind,
            "connected": bool(self.capture.connected), "stale": age is None or age > self.stale_sec, "frame_age_sec": age,
            "input": self.capture.info(),
            "reconnects": self.capture.reconnects, "bad_frames": self.capture.bad_frames,
            "frame_size": list(self.size) if self.size else None, "roi_applied": bool(self.roi_on),
            "frames_processed": self.frames, "fps_processed": round((len(self.recent_t) - 1) / span, 2) if span > 0 else 0.0,
            "detect_ms_recent": round(float(np.mean(self.recent_ms)), 1) if self.recent_ms else None,
            "detect_errors": self.errors_total, "conf_display": self.conf, "conf_alarm": self.alarm_conf,
            "uptime_sec": round(time.time() - self.started, 1), "clients": self.clients,
            "classes": [{"name": n, "alarm_class": n in ALARM_CLASS_NAMES, "frames_display": self.seen_display[n],
                         "frames_alarm_conf": self.seen_alarm_conf[n], "max_conf": round(self.max_conf[n], 3),
                         "events": self.event_total[n]} for n in names],
            "current": self.current, "events": list(self.events)[:20],
        }

    def client_enter(self):
        with self.cond:
            if self.clients >= MAX_CLIENTS:
                return False
            self.clients += 1
            return True

    def client_leave(self):
        with self.cond:
            self.clients -= 1


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>모델 B 인식 확인</title>
<style>
:root{color-scheme:dark;--bg:#10151b;--panel:#18202a;--line:#2b3644;--fg:#e6edf3;--mute:#93a1b0;--bad:#ff6b5e;--ok:#5fd38d;--warn:#ffc04d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Noto Sans KR","Malgun Gothic",sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}h1{font-size:18px;margin:0}
header p{margin:2px 0 0;color:var(--mute);font-size:13px}
#alert{display:none;background:var(--bad);color:#14090a;font-weight:600;padding:8px 16px}
main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:12px;padding:12px 16px}
@media(max-width:900px){main{grid-template-columns:minmax(0,1fr)}}
#video{background:#000;border:1px solid var(--line);border-radius:6px;text-align:center;min-height:240px}
#video img{display:block;margin:0 auto;max-width:100%;max-height:calc(100vh - 120px)}#video.stale img{opacity:.35}
section{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin-bottom:12px}
h2{font-size:13px;margin:0 0 6px;color:var(--mute);font-weight:600}
dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 12px;margin:0}dt{color:var(--mute)}dd{margin:0;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:2px 4px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}th{color:var(--mute);font-weight:500;font-size:12px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
ol{margin:0;padding:0;list-style:none;max-height:220px;overflow:auto;font-size:13px}li{padding:2px 0;border-bottom:1px solid var(--line)}
footer{padding:0 16px 14px;color:var(--mute);font-size:13px}
</style></head><body>
<header><h1>모델 B 인식 확인 <span class="warn">관측 전용</span></h1><p id="sub">불러오는 중</p></header>
<div id="alert"></div>
<main><div id="video"><img src="/stream.mjpg" alt="검출 박스를 그린 영상"></div>
<div>
<section><h2>상태</h2><dl id="st"></dl></section>
<section><h2>클래스별 프레임 수</h2><table><thead><tr><th>클래스</th><th>지금</th><th id="thd"></th><th id="tha"></th><th>최고</th><th>이벤트</th></tr></thead><tbody id="cl"></tbody></table></section>
<section><h2>확정 이벤트 (최근 20건)</h2><ol id="ev"></ol></section>
</div></main>
<footer>이벤트는 기록만 합니다. 경보나 관제 명령은 보내지 않습니다. 경보가 없다고 정상이라는 뜻은 아닙니다. 모델 B의 실물 재현율은 아직 측정되지 않았습니다.</footer>
<script>
const KO={box_on_floor:"바닥 상자",box_perched_on_rim:"턱 걸림",box_run_over:"깔림",lid_detached:"뚜껑 분리",box_on_tray:"접시 위 상자",box_stock:"재고 상자"};
const SW={box_on_floor:"#f02828",box_perched_on_rim:"#ff8c00",box_run_over:"#dc28c8",lid_detached:"#ffdc00",box_on_tray:"#50dc50",box_stock:"#3caaf0"};
const $=id=>document.getElementById(id);
function row(k,v,c){const t=document.createElement("dt");t.textContent=k;const d=document.createElement("dd");d.textContent=v;if(c)d.className=c;return[t,d]}
async function tick(){
 let s;try{s=await(await fetch("/api/state",{cache:"no-store"})).json()}catch(e){$("alert").style.display="block";$("alert").textContent="뷰어에 연결되지 않습니다.";$("video").className="stale";return}
 $("sub").textContent=`${s.model} · 입력 ${s.source}`;
 const msg=[];if(s.stale)msg.push(s.frame_age_sec===null?"아직 영상이 들어오지 않았습니다.":`영상이 ${s.frame_age_sec}초째 멈췄습니다. 화면은 마지막 프레임입니다.`);
 if(s.input.http_status&&s.input.http_status!==200)msg.push(`입력이 HTTP ${s.input.http_status}로 거절했습니다.`);
 if(s.frame_size&&s.frame_size.join("x")!=="1080x1440")msg.push(`프레임 크기가 ${s.frame_size.join("x")}입니다. 1080x1440이 아니라 제외 영역을 적용하지 않았습니다. 회전과 해상도를 확인해 주세요.`);
 if(s.input.rotation!==null&&s.input.rotation!==90)msg.push(`앱 회전이 ${s.input.rotation}도입니다. 90도가 아니라 제외 영역을 적용하지 않았습니다.`);
 if(s.input.lens&&s.input.lens!=="ULTRA_WIDE")msg.push(`렌즈가 ${s.input.lens}입니다. 초광각이 아니라 제외 영역을 적용하지 않았습니다.`);
 $("alert").style.display=msg.length?"block":"none";$("alert").textContent=msg.join(" ");$("video").className=s.stale?"stale":"";
 $("st").replaceChildren(...[row("입력",s.connected?"연결됨":"끊김",s.connected?"ok":"bad"),row("프레임 나이",s.frame_age_sec===null?"없음":s.frame_age_sec+"초",s.stale?"bad":""),row("입력 방식",s.input.transport),row("받는 속도",s.input.fps_received+" fps"),row("처리 속도",s.fps_processed+" fps"),row("추론",s.detect_ms_recent===null?"없음":s.detect_ms_recent+" ms"),row("처리 프레임",s.frames_processed),row("프레임 크기",s.frame_size?s.frame_size.join("x"):"없음"),row("앱 회전",s.input.rotation===null?"모름":s.input.rotation+"도"),row("렌즈",s.input.lens||"모름"),row("재연결",s.reconnects),row("앱 세션 바뀜",s.input.session_changes,s.input.session_changes?"warn":""),row("추론 오류",s.detect_errors,s.detect_errors?"bad":"")].flat());
 $("thd").textContent=`${s.conf_display} 이상`;$("tha").textContent=`${s.conf_alarm} 이상`;
 const now={};for(const d of s.current)now[d.event_type]=(now[d.event_type]||0)+1;
 $("cl").replaceChildren(...s.classes.map(c=>{const r=document.createElement("tr");const a=document.createElement("td");const w=document.createElement("span");w.className="sw";w.style.background=SW[c.name]||"#888";a.append(w,KO[c.name]||c.name);r.append(a);for(const v of[now[c.name]||0,c.frames_display,c.frames_alarm_conf,c.max_conf.toFixed(2),c.alarm_class?c.events:"-"]){const t=document.createElement("td");t.textContent=v;r.append(t)}return r}));
 $("ev").replaceChildren(...(s.events.length?s.events.map(e=>{const l=document.createElement("li");l.textContent=`${e.iso_time.slice(11)} ${KO[e.event_type]||e.event_type} ${e.confidence.toFixed(2)}`;return l}):[Object.assign(document.createElement("li"),{textContent:"아직 없습니다."})]));
}
tick();setInterval(tick,1000);
</script></body></html>"""


def make_handler(viewer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(200, json.dumps(viewer.snapshot(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif path == "/stream.mjpg":
                self._stream()
            else:
                self._send(404, b"not found\n", "text/plain")

        def _refuse(self):
            self._send(405, b"read only\n", "text/plain")

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def _stream(self):
            if not viewer.client_enter():
                self._send(503, b"too many viewers\n", "text/plain")
                return
            try:
                self.connection.settimeout(WRITE_TIMEOUT_SEC)
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seen = -1
                while not viewer.stop.is_set():
                    jpeg, seen = viewer.wait_jpeg(seen)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except OSError:
                pass
            finally:
                viewer.client_leave()

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def load_detector(model, threads):
    sys.path.insert(0, HERE)
    from yolo_ov_detector import OVYoloDetector
    return OVYoloDetector(model, threads=threads or None)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="모델 B 관측 전용 웹 뷰어")
    ap.add_argument("--source", required=True, help="rtsp/http 주소, 영상 파일, 녹화 zip, 이미지 폴더")
    ap.add_argument("--model", required=True, help="OpenVINO 모델 폴더 또는 best.xml")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8893)
    ap.add_argument("--allow-nonlocal", action="store_true", help="127.0.0.1 밖 바인드를 허용한다")
    ap.add_argument("--conf", type=float, default=0.25, help="표시 문턱")
    ap.add_argument("--alarm-conf", type=float, default=0.5, help="경보 판정 문턱")
    ap.add_argument("--iou", type=float, default=0.7)
    ap.add_argument("--debounce", type=int, default=3)
    ap.add_argument("--cooldown", type=float, default=5.0)
    ap.add_argument("--max-fps", type=float, default=5.0, help="추론 상한 (0 = 없음)")
    ap.add_argument("--threads", type=int, default=2, help="OpenVINO 스레드 (0 = 기본)")
    ap.add_argument("--replay-fps", type=float, default=5.0, help="zip, 폴더 재생 속도")
    ap.add_argument("--view-width", type=int, default=720)
    ap.add_argument("--stream-id", default="CAM_CEILING_01")
    ap.add_argument("--event-log", default=os.path.expanduser(time.strftime("~/yolo_edge/logs/view-events-%Y%m%d-%H%M%S.jsonl")),
                    help="확정 이벤트 JSONL (프레임 없음). 빈 문자열이면 끈다")
    ap.add_argument("--duration", type=float, default=0, help="N초 뒤 끝낸다 (0 = 끝내지 않음)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    check_bind(a.bind, a.allow_nonlocal)
    kind = source_kind(a.source)
    det = load_detector(a.model, a.threads)  # 모델이 틀리면 스트림을 열기 전에 끝난다.
    bin_path = os.path.join(a.model if not a.model.endswith(".xml") else os.path.dirname(a.model), "best.bin")
    label = f"{os.path.basename(os.path.normpath(os.path.dirname(bin_path)))} {file_sha256(bin_path)[:8]}"
    if a.event_log:
        os.makedirs(os.path.dirname(a.event_log) or ".", exist_ok=True)
    cap = Capture(a.source, replay_fps=a.replay_fps)
    v = Viewer(det, cap, conf=a.conf, alarm_conf=a.alarm_conf, iou=a.iou, debounce=a.debounce, cooldown=a.cooldown, max_fps=a.max_fps,
               view_width=a.view_width, stream_id=a.stream_id, event_log=a.event_log or None, model_label=label)
    server = Server((a.bind, a.port), make_handler(v))
    logger.info("OBSERVE-ONLY. 모델 %s, 입력 %s (%s), 표시 %.2f, 경보 %.2f, http://%s:%d/", label, safe_label(a.source), kind, a.conf,
                a.alarm_conf, a.bind, a.port)

    def finish(*_):
        v.stop.set()

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    cap.start()
    worker = threading.Thread(target=v.loop, daemon=True)
    worker.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.monotonic() + a.duration if a.duration else None
    while not v.stop.is_set():
        if deadline and time.monotonic() >= deadline:
            v.stop.set()
        v.stop.wait(0.2)
    cap.halt.set()
    server.shutdown()
    cap.join(timeout=7)
    logger.info("끝. 처리 %d 프레임, 이벤트 %d건", v.frames, sum(v.event_total.values()))
    if v.fatal:
        logger.error(v.fatal)
        return 1
    return 0


if __name__ == "__main__":
    # 이 복사본은 stream_manager.py 가 불러 쓴다. Host 검사와 코어 덤프 차단은 그쪽에 있다.
    sys.exit("단독 실행하지 않습니다. stream_manager.py 를 쓰세요")
