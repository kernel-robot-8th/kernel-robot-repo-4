"""MJPEG/HTTP 영상을 OpenCV 로 읽는 스레드. 가장 새 프레임 한 장만 메모리에 둔다. 디스크에 쓰지 않는다."""
import threading
import time

import cv2


class FrameSource(threading.Thread):
    def __init__(self, url, stop, open_timeout_ms=5000, read_timeout_ms=5000, backoff_max=10.0, log=print):
        super().__init__(name="frame-source", daemon=True)
        self.url, self.stop_event, self.log = url, stop, log
        self.open_timeout_ms, self.read_timeout_ms, self.backoff_max = open_timeout_ms, read_timeout_ms, backoff_max
        self._lock = threading.Lock()
        self._latest = None                 # (frame, capture_time, seq)
        self.connected = False
        self.frames_received = 0
        self.connect_attempts = 0
        self.connect_failures = 0
        self.last_frame_time = 0.0
        self.last_size = None

    def latest(self):
        with self._lock:
            return self._latest

    def is_live(self, now=None, stale_sec=3.0):
        now = time.time() if now is None else now
        return bool(self.connected and now - self.last_frame_time <= stale_sec)

    def run(self):
        backoff = 1.0
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms]
        while not self.stop_event.is_set():
            self.connect_attempts += 1
            cap = None
            try:
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG, params)
                opened = cap.isOpened()
            except Exception as e:  # noqa: BLE001
                opened = False
                self.log("source_open_error", {"error": type(e).__name__})
            if not opened:
                self.connected = False
                self.connect_failures += 1
                if cap is not None:
                    cap.release()
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, self.backoff_max)
                continue
            self.log("source_connected", {"attempt": self.connect_attempts})
            got_any = False
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                now = time.time()
                self.frames_received += 1
                self.last_frame_time = now
                self.last_size = (int(frame.shape[1]), int(frame.shape[0]))
                with self._lock:
                    self._latest = (frame, now, self.frames_received)
                if not got_any:
                    got_any, backoff = True, 1.0
                    self.connected = True
            self.connected = False
            with self._lock:
                self._latest = None
            cap.release()
            if not self.stop_event.is_set():
                self.log("source_disconnected", {"frames_received": self.frames_received})
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, self.backoff_max)
