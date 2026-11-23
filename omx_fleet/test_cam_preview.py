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

"""cam_preview 시험: 가짜 장면·가짜 인코더 (카메라·cv2 없이)."""

import json
import threading
import urllib.request

import cam_preview
import omx_fleet_worker
import pytest


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def fake_encode(frame, quality, max_width):
    return b'\xff\xd8' + frame['id'].encode() + b'\xff\xd9'


def test_cache_encodes_only_new_frames_and_respects_fps():
    frames = {'top': {'id': 'a'}}
    calls = []
    clock = Clock()

    def get(role):
        calls.append(role)
        return frames.get(role)

    cache = cam_preview.FrameCache(get, ('top', 'wrist'), fps=10, encode=fake_encode, clock=clock)
    assert cache.encoded == 0   # 아무도 안 부르면 바꾸지 않는다
    first = cache.latest('top')
    assert first[0] == 1 and b'a' in first[1]
    assert cache.latest('top') is first     # 간격(0.1 s) 안이면 카메라도 안 읽는다
    assert calls == ['top']
    clock.now = 0.2
    assert cache.latest('top') is first     # 같은 장면이면 다시 바꾸지 않는다
    assert cache.encoded == 1
    frames['top'] = {'id': 'b'}
    clock.now = 0.4
    second = cache.latest('top')
    assert second[0] == 2 and b'b' in second[1]
    assert cache.latest('wrist') is None    # 장면 없는 카메라
    health = cache.health()
    assert health['wrist']['age_sec'] is None and health['top']['age_sec'] == 0.0


def test_cache_survives_camera_error():
    def get(role):
        raise RuntimeError('camera gone')

    cache = cam_preview.FrameCache(get, ('top',), encode=fake_encode, clock=Clock())
    assert cache.latest('top') is None


def test_lerobot_getter_reads_latest_frame_only():
    class Cam:
        frame_lock = threading.Lock()
        latest_frame = 'frame'

        def async_read(self):  # 부르면 안 됨 (작업 루프의 새 장면 신호를 빼앗음)
            raise AssertionError

    class Robot:
        cameras = {'top': Cam()}

    get = cam_preview.lerobot_frame_getter(Robot())
    assert get('top') == 'frame'
    assert get('wrist') is None


def test_server_serves_jpeg_stream_and_health():
    np = pytest.importorskip('numpy')
    pytest.importorskip('cv2')
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    server = cam_preview.PreviewServer(lambda role: frame if role == 'top' else None, 0,
                                       roles=('top', 'wrist')).start()
    host, port = server.address
    base = f'http://{host}:{port}'
    try:
        with urllib.request.urlopen(f'{base}/top.jpg', timeout=3) as res:
            assert res.headers['Content-Type'] == 'image/jpeg'
            assert res.read().startswith(b'\xff\xd8')
        with urllib.request.urlopen(f'{base}/top', timeout=3) as res:
            assert 'multipart/x-mixed-replace' in res.headers['Content-Type']
            head = res.read(200)
            assert b'--frame' in head and b'Content-Length:' in head
        with urllib.request.urlopen(f'{base}/health', timeout=3) as res:
            body = json.loads(res.read())
            assert set(body['roles']) == {'top', 'wrist'}
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f'{base}/wrist.jpg', timeout=3)
        assert err.value.code == 503
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f'{base}/side', timeout=3)
        assert err.value.code == 404
    finally:
        server.stop()


@pytest.mark.parametrize('value, expected', [
    (None, None),
    ({'port': 8091}, {'port': 8091, 'bind': '127.0.0.1'}),
    ({'port': 8093, 'bind': '0.0.0.0'}, {'port': 8093, 'bind': '0.0.0.0'}),
])
def test_preview_config_ok(value, expected):
    assert omx_fleet_worker.preview_config(value, 'omx1') == expected


@pytest.mark.parametrize('value', [8091, {'port': 0}, {'port': True}, {'port': '8091'},
                                   {'port': 8091, 'bind': ''}])
def test_preview_config_bad(value):
    with pytest.raises(ValueError):
        omx_fleet_worker.preview_config(value, 'omx1')
