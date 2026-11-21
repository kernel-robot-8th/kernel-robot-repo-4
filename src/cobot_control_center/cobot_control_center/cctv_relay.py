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
현장영상(천장 CCTV) 중계: 다른 장치가 내는 MJPEG(HTTP)을 받아 마지막 장면 1장만 보관한다 (ROS·fastapi 없음).

왜 중계하나: 영상 장치(예: 192.168.0.7:18086)는 관제 PC 유선망에만 있어서, 무선망·원격으로 관제 웹을
연 브라우저는 직접 닿지 못한다. 백엔드가 받아서 /api/cctv 로 다시 내면 관제 웹이 열리는 곳이면 보인다.
화면을 여러 개 열어도 원본에는 연결 1개만 만든다.

보는 사람이 있을 때만 원본에 붙는다 (장면 1장이 약 250 KB, 초당 약 3 MB 라 아무도 안 볼 때는 받지 않는다).
마지막 사람이 닫고 idle_sec 가 지나면 연결을 끊는다. 끊기면 reconnect_sec 마다 다시 붙는다.
"""

import threading
import time
import urllib.request

SOI = b'\xff\xd8'   # JPEG 시작 표시
EOI = b'\xff\xd9'   # JPEG 끝 표시


class MjpegSplitter:
    """
    MJPEG(multipart/x-mixed-replace) 바이트를 조금씩 받아 JPEG 장면으로 자른다.

    조각 머리에 Content-Length 가 있으면 그 길이만큼 자른다 (JPEG 안에 끝 표시와 같은 바이트가 있어도 안전).
    없으면 시작·끝 표시(FFD8 … FFD9)로 자른다. 버퍼가 max_buffer 를 넘으면 버린다 (깨진 스트림 방지).
    """

    def __init__(self, max_buffer=8 * 1024 * 1024):
        self.max_buffer = max_buffer
        self._buf = b''

    def feed(self, chunk):
        """받은 바이트를 더하고, 다 모인 JPEG 장면 목록을 돌려준다."""
        self._buf += chunk
        frames = []
        while True:
            start = self._buf.find(SOI)
            if start < 0:
                # 머리(텍스트)만 있는 상태. 끝 1바이트는 FF 일 수 있어 남긴다.
                self._buf = self._buf[-1:] if len(self._buf) > 4096 else self._buf
                break
            length = _content_length(self._buf[:start])
            if length is not None and length >= 4:
                if len(self._buf) - start < length:
                    break
                frame = self._buf[start:start + length]
                self._buf = self._buf[start + length:]
            else:
                end = self._buf.find(EOI, start + 2)
                if end < 0:
                    break
                frame = self._buf[start:end + 2]
                self._buf = self._buf[end + 2:]
            if frame.endswith(EOI):
                frames.append(frame)
        if len(self._buf) > self.max_buffer:
            self._buf = b''
        return frames


def _content_length(head):
    """조각 머리 바이트의 마지막 Content-Length 값. 없거나 숫자가 아니면 None."""
    value = None
    for line in head.split(b'\n'):
        name, sep, rest = line.partition(b':')
        if sep and name.strip().lower() == b'content-length':
            try:
                value = int(rest.strip())
            except ValueError:
                value = None
    return value


def open_http_stream(url, timeout):
    """URL 을 열어 read(n) 할 수 있는 응답을 돌려준다 (파이썬 기본 urllib, 새 의존성 없음)."""
    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 (설정 파일의 http 주소만)


class CctvRelay:
    """
    현장영상 원본 1개를 받아 마지막 장면을 보관하고, 보는 사람 수에 맞춰 연결을 켜고 끈다.

    acquire()/release() 로 보는 사람을 센다. latest()·wait_newer() 는 CameraStore 와 같은 모양이다.
    open_stream·clock 은 시험에서 바꿔 끼운다.
    """

    def __init__(self, url, idle_sec=10.0, reconnect_sec=2.0, timeout_sec=5.0,
                 chunk_bytes=65536, open_stream=open_http_stream, clock=time.monotonic):
        self.url = url
        self.idle_sec = idle_sec
        self.reconnect_sec = reconnect_sec
        self.timeout_sec = timeout_sec
        self.chunk_bytes = chunk_bytes
        self.open_stream = open_stream
        self.clock = clock
        self._cond = threading.Condition()
        self._frame = None          # (seq, bytes, 받은 시각)
        self._frames = 0
        self._viewers = 0
        self._last_release = None
        self._connected = False
        self._error = ''
        self._thread = None
        self._stop = False

    # ---------- 보는 사람 ----------

    def acquire(self):
        """보는 사람 1명 추가. 연결 스레드가 없으면 시작한다."""
        with self._cond:
            self._viewers += 1
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._thread = threading.Thread(target=self._run, name='cctv_relay', daemon=True)
                self._thread.start()

    def release(self):
        """보는 사람 1명 뺀다. 0 명이 되고 idle_sec 가 지나면 연결 스레드가 스스로 끝난다."""
        with self._cond:
            self._viewers = max(0, self._viewers - 1)
            if self._viewers == 0:
                self._last_release = self.clock()

    def shutdown(self, timeout=2.0):
        """연결을 끊고 스레드를 끝낸다 (백엔드 종료 때)."""
        with self._cond:
            self._stop = True
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ---------- 장면 ----------

    def put(self, jpeg):
        """장면을 넣는다 (연결 스레드가 부름). 빈 바이트면 False."""
        if not jpeg:
            return False
        with self._cond:
            seq = self._frame[0] + 1 if self._frame else 1
            self._frame = (seq, bytes(jpeg), self.clock())
            self._frames += 1
            self._cond.notify_all()
        return True

    def latest(self):
        """(순번, JPEG 바이트). 받은 적이 없으면 None."""
        with self._cond:
            return None if self._frame is None else self._frame[:2]

    def wait_newer(self, seq, timeout):
        """순번이 seq 보다 큰 장면이 올 때까지 최대 timeout 초 기다린다. 새 장면이 있으면 True."""
        with self._cond:
            return self._cond.wait_for(
                lambda: self._frame is not None and self._frame[0] > seq, timeout)

    def health(self):
        """화면 표시용 상태: 연결·보는 사람 수·마지막 장면 뒤 지난 시간·받은 수·마지막 오류."""
        now = self.clock()
        with self._cond:
            return {'url': self.url, 'connected': self._connected, 'viewers': self._viewers,
                    'age_sec': None if self._frame is None else round(now - self._frame[2], 3),
                    'frames': self._frames, 'error': self._error}

    # ---------- 연결 스레드 ----------

    def _wanted(self):
        # lock 안에서 부른다. 보는 사람이 있거나, 마지막 사람이 닫은 뒤 idle_sec 안이면 계속 받는다.
        if self._stop:
            return False
        if self._viewers > 0:
            return True
        return (self._last_release is not None
                and self.clock() - self._last_release < self.idle_sec)

    def _run(self):
        while True:
            with self._cond:
                if not self._wanted():
                    self._thread = None
                    self._connected = False
                    return
            try:
                self._pump()
            except Exception as exc:  # noqa: BLE001 (네트워크 오류는 종류와 상관없이 다시 붙는다)
                with self._cond:
                    self._error = f'{type(exc).__name__}: {exc}'[:200]
            with self._cond:
                self._connected = False
                self._cond.wait_for(lambda: not self._wanted(), self.reconnect_sec)

    def _pump(self):
        splitter = MjpegSplitter()
        stream = self.open_stream(self.url, self.timeout_sec)
        try:
            with self._cond:
                self._connected = True
                self._error = ''
            while True:
                with self._cond:
                    if not self._wanted():
                        return
                chunk = stream.read1(self.chunk_bytes) if hasattr(stream, 'read1') \
                    else stream.read(self.chunk_bytes)
                if not chunk:
                    raise ConnectionError('원본이 연결을 닫음')
                for frame in splitter.feed(chunk):
                    self.put(frame)
        finally:
            stream.close()
