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

"""현장영상 중계(cctv_relay.py)와 /api/cctv 경로를 네트워크·ROS 없이 검사한다."""

import threading
import time

from cobot_control_center.cctv_relay import CctvRelay, MjpegSplitter
from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import SnapshotStore
from fastapi.testclient import TestClient

JPEG_A = b'\xff\xd8AAAA\xff\xd9'
# 안에 끝 표시(FFD9)와 같은 바이트가 있는 장면: Content-Length 가 있으면 끝까지 잘려야 한다.
JPEG_B = b'\xff\xd8B\xff\xd9BB\xff\xd9'


def part(jpeg, length=True):
    head = b'--raasframe\r\nContent-Type: image/jpeg\r\n'
    if length:
        head += f'Content-Length: {len(jpeg)}\r\n'.encode()
    return head + b'X-Frame-Seq: 1\r\n\r\n' + jpeg + b'\r\n'


def test_splitter_uses_content_length():
    splitter = MjpegSplitter()
    assert splitter.feed(part(JPEG_A) + part(JPEG_B)) == [JPEG_A, JPEG_B]


def test_splitter_without_length_uses_markers():
    splitter = MjpegSplitter()
    assert splitter.feed(part(JPEG_A, length=False)) == [JPEG_A]


def test_splitter_handles_byte_by_byte_chunks():
    splitter = MjpegSplitter()
    data = part(JPEG_B) + part(JPEG_A)
    frames = []
    for i in range(len(data)):
        frames += splitter.feed(data[i:i + 1])
    assert frames == [JPEG_B, JPEG_A]


def test_splitter_drops_oversized_buffer():
    splitter = MjpegSplitter(max_buffer=64)
    assert splitter.feed(b'\xff\xd8' + b'x' * 100) == []
    assert splitter.feed(part(JPEG_A)) == [JPEG_A]


class FakeStream:
    """read(n) 로 정해 둔 바이트를 주고, 다 주면 닫힌 연결처럼 b'' 를 준다."""

    def __init__(self, data, hold=None):
        self.data = data
        self.hold = hold
        self.closed = False

    def read(self, size):
        if not self.data:
            if self.hold is not None:
                self.hold.wait(1.0)   # 연결은 살아 있고 새 장면만 없는 상태
            return b''
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk

    def close(self):
        self.closed = True


def test_relay_connects_only_while_watched():
    opened = []
    hold = threading.Event()

    def open_stream(url, timeout):
        stream = FakeStream(part(JPEG_A) + part(JPEG_B), hold)
        opened.append(stream)
        return stream

    relay = CctvRelay('http://cam/x', idle_sec=0.0, reconnect_sec=0.05,
                      chunk_bytes=7, open_stream=open_stream)
    assert relay.latest() is None
    assert opened == []          # 아무도 안 보면 원본에 붙지 않는다
    relay.acquire()
    assert relay.wait_newer(1, 2.0) is True
    assert relay.latest() == (2, JPEG_B)
    assert relay.health()['frames'] == 2
    assert relay.health()['viewers'] == 1
    relay.release()
    hold.set()
    deadline = time.monotonic() + 2.0
    while relay._thread is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert relay._thread is None
    assert all(stream.closed for stream in opened)
    assert relay.health()['connected'] is False


def test_relay_reports_error_and_retries():
    calls = []

    def open_stream(url, timeout):
        calls.append(url)
        raise OSError('no route to host')

    relay = CctvRelay('http://cam/x', reconnect_sec=0.01, open_stream=open_stream)
    relay.acquire()
    deadline = time.monotonic() + 2.0
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(calls) >= 2
    assert 'no route to host' in relay.health()['error']
    relay.shutdown()


def test_cctv_routes():
    store = SnapshotStore(3.0)
    without = TestClient(create_app(store))
    assert without.get('/api/health').json()['cctv'] is None
    assert without.get('/api/cctv').status_code == 404
    assert without.get('/api/cctv.jpg').status_code == 404

    relay = CctvRelay('http://cam/x', open_stream=lambda url, timeout: FakeStream(b''))
    client = TestClient(create_app(store, cctv=relay))
    health = client.get('/api/health').json()['cctv']
    assert health['url'] == 'http://cam/x'
    assert health['frames'] == 0
    assert client.get('/api/cctv.jpg').status_code == 404
    relay.put(JPEG_A)
    frame = client.get('/api/cctv.jpg')
    assert frame.status_code == 200
    assert frame.headers['content-type'] == 'image/jpeg'
    assert frame.content == JPEG_A
