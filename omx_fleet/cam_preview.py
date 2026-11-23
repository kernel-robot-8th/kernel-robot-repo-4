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
팔 카메라 미리보기: 실행기가 붙잡은 카메라 장면을 MJPEG(HTTP)으로 낸다 (관제 팔 상세화면용).

왜 실행기 안에서 내나: 카메라는 실행기가 켜기(연결)부터 끄기까지 열어 두므로 다른 프로세스가 열 수 없다.
장면은 lerobot 카메라 읽기 스레드가 보관한 마지막 장면을 엿보기만 한다 (get_frame). 작업 제어 루프가 쓰는
async_read 의 '새 장면' 신호를 건드리지 않으므로 팔 동작에 영향이 없다.

보는 사람이 있을 때만 JPEG 으로 바꾼다. 같은 장면은 한 번만 바꿔 여러 연결이 나눠 쓴다.
경로: /top, /wrist (multipart MJPEG), /<역할>.jpg (한 장), /health (JSON).
관제 백엔드(cobot_control_center cctv_relay)가 받아 /api/arms/<팔>/camera/<역할> 로 다시 낸다.

가짜 장면으로 띄워 보기 (팔 없음): python cam_preview.py --port 8091 --fake
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

BOUNDARY = 'frame'


def encode_jpeg(rgb, quality, max_width):
    """RGB 장면(높이·너비·3) → JPEG 바이트. 너비가 max_width 보다 크면 줄인다. 실패면 None."""
    import cv2

    height, width = rgb.shape[:2]
    if max_width and width > max_width:
        rgb = cv2.resize(rgb, (max_width, int(height * max_width / width)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                           [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None


class FrameCache:
    """
    역할(top·wrist)마다 마지막 JPEG 을 보관한다. 보는 사람이 부를 때만 새로 바꾼다.

    get_frame(role) 이 같은 장면(같은 객체)을 돌려주면 다시 바꾸지 않는다. 바꾸는 간격은 1/fps 이상.
    encode·clock 은 시험에서 바꿔 끼운다.
    """

    def __init__(self, get_frame, roles, fps=10.0, quality=70, max_width=640,
                 encode=encode_jpeg, clock=time.monotonic):
        self.get_frame = get_frame
        self.roles = tuple(roles)
        self.period = 1.0 / fps if fps > 0 else 0.0
        self.quality = quality
        self.max_width = max_width
        self.encode = encode
        self.clock = clock
        self._lock = threading.Lock()
        self._jpeg = {}      # role → (seq, bytes, 바꾼 시각)
        self._source = {}    # role → 마지막으로 바꾼 원본 장면 id (같은 장면이면 다시 안 바꿈)
        self._viewers = {role: 0 for role in self.roles}
        self.encoded = 0     # 바꾼 횟수 (시험·health)

    def viewer(self, role, delta):
        with self._lock:
            self._viewers[role] = max(0, self._viewers[role] + delta)

    def latest(self, role):
        """
        마지막 JPEG (seq, bytes, 시각) 또는 None.

        간격이 지났으면 새 장면을 받아 바꾼다.
        """
        with self._lock:
            now = self.clock()
            have = self._jpeg.get(role)
            if have is not None and now - have[2] < self.period:
                return have
            try:
                frame = self.get_frame(role)
            except Exception:  # noqa: BLE001 — 카메라 쪽 오류로 서버가 죽지 않게
                frame = None
            if frame is None or self._source.get(role) is frame:
                return have
            jpeg = self.encode(frame, self.quality, self.max_width)
            if not jpeg:
                return have
            self.encoded += 1
            self._source[role] = frame
            seq = have[0] + 1 if have else 1
            self._jpeg[role] = (seq, jpeg, now)
            return self._jpeg[role]

    def health(self):
        with self._lock:
            now = self.clock()
            return {role: {'viewers': self._viewers[role],
                           'age_sec': (round(now - self._jpeg[role][2], 2)
                                       if role in self._jpeg else None)}
                    for role in self.roles}


def _make_handler(cache, period):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 연결마다 stderr 로그를 남기지 않는다 (실행기 로그를 덮지 않게)
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?', 1)[0].strip('/')
            if path == 'health':
                body = json.dumps({'roles': cache.health()}).encode()
                return self._send(200, body, 'application/json')
            if path.endswith('.jpg') and path[:-4] in cache.roles:
                got = cache.latest(path[:-4])
                if got is None:
                    return self._send(503, b'no frame', 'text/plain')
                return self._send(200, got[1], 'image/jpeg')
            if path in cache.roles:
                return self._stream(path)
            return self._send(404, b'not found', 'text/plain')

        def _stream(self, role):
            self.send_response(200)
            self.send_header('Content-Type', f'multipart/x-mixed-replace; boundary={BOUNDARY}')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            cache.viewer(role, +1)
            sent = 0
            try:
                while True:
                    got = cache.latest(role)
                    if got is not None and got[0] != sent:
                        sent = got[0]
                        self.wfile.write(
                            f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n'
                            f'Content-Length: {len(got[1])}\r\n\r\n'.encode() + got[1] + b'\r\n')
                        self.wfile.flush()
                    time.sleep(period)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass   # 보는 쪽이 닫음
            finally:
                cache.viewer(role, -1)

    return Handler


class PreviewServer:
    """FrameCache 를 HTTP 로 내는 데몬 스레드 서버. start() 가 포트를 못 열면 OSError."""

    def __init__(self, get_frame, port, bind='127.0.0.1', roles=('top', 'wrist'),
                 fps=10.0, quality=70, max_width=640):
        self.cache = FrameCache(get_frame, roles, fps=fps, quality=quality, max_width=max_width)
        period = max(0.02, 1.0 / fps / 2) if fps > 0 else 0.05
        self._server = ThreadingHTTPServer((bind, int(port)), _make_handler(self.cache, period))
        self._server.daemon_threads = True
        self._thread = None

    @property
    def address(self):
        return self._server.server_address

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, name='cam_preview',
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


def lerobot_frame_getter(robot):
    """
    Lerobot 로봇의 카메라 마지막 장면을 엿보는 get_frame(role).

    async_read 를 부르지 않고 latest_frame 만 잠금 안에서 읽는다 (작업 루프의 새 장면 신호를 건드리지 않음).
    """
    def get_frame(role):
        cam = robot.cameras.get(role)
        if cam is None:
            return None
        with cam.frame_lock:
            return cam.latest_frame

    return get_frame


def _fake_getter():
    """팔 없이 화면을 볼 때 쓰는 움직이는 색 막대 장면."""
    import numpy as np

    def get_frame(role):
        shift = int(time.monotonic() * 40) % 640
        base = np.zeros((360, 640, 3), dtype=np.uint8)
        ramp = np.roll(np.linspace(0, 255, 640, dtype=np.uint8), shift)
        base[:, :, 0 if role == 'top' else 2] = ramp[None, :]
        base[150:210, 40:600, 1] = 200
        return base

    return get_frame


def main(argv=None):
    p = argparse.ArgumentParser(description='팔 카메라 미리보기 서버 (시험용 단독 실행)')
    p.add_argument('--port', type=int, default=8091)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--fake', action='store_true', help='카메라 대신 가짜 장면')
    args = p.parse_args(argv)
    if not args.fake:
        p.error('단독 실행은 --fake 만 된다 (실제 카메라는 실행기가 연다)')
    server = PreviewServer(_fake_getter(), args.port, args.bind).start()
    print(f'미리보기: http://{args.bind}:{args.port}/top · /wrist', flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == '__main__':
    main()
