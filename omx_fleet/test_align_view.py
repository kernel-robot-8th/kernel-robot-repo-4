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

"""align_view 시험: 순수 계산만 (카메라·영상 없이)."""

import os

import align_view as av
import numpy as np
import pytest


def _scene(seed=0, shape=(480, 640)):
    """무늬가 있는 가짜 위쪽 카메라 화면 (번진 잡음 + 사각형)."""
    import cv2
    rng = np.random.default_rng(seed)
    gray = cv2.GaussianBlur(rng.integers(0, 255, shape, dtype=np.uint8), (0, 0), 3)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(img, (250, 180), (390, 300), (255, 255, 255), -1)
    return img


def test_release_index_last_held_frame():
    assert av.release_index([0, -10, -200, -330, -160, -40, 0]) == 4


def test_release_index_never_held():
    assert av.release_index([0, -100, 20]) is None


def test_frame_time():
    assert av.frame_time(22.633333, 30, 30) == pytest.approx(23.633333)


def test_parse_at():
    assert av.parse_at('start') == 'start'
    assert av.parse_at('release') == 'release'
    assert av.parse_at('12.5') == 12.5
    with pytest.raises(ValueError):
        av.parse_at('middle')


def test_parse_box():
    assert av.parse_box('3,-2', '--shift') == (3, -2)
    with pytest.raises(ValueError):
        av.parse_box('3,a', '--shift')


def test_clip_roi_negative_drag_and_edges():
    # 오른쪽 아래 → 왼쪽 위로 끈 영역, 화면 밖은 잘린다
    assert av.clip_roi((700, 500, -200, -100), (480, 640)) == (500, 400, 140, 80)


def test_dft_size():
    assert av.dft_size(220) == 216
    assert av.dft_size(240) == 240


def test_clip_roi_too_small():
    assert av.clip_roi((10, 10, 8, 40), (480, 640)) is None


@pytest.mark.parametrize('dx,dy', [(0, 0), (6, 0), (-4, 5), (10, -7)])
def test_roi_shift_finds_known_offset(dx, dy):
    # 실제 카메라처럼 경계가 비지 않게, 큰 장면에서 자리를 옮겨 잘라 낸다
    big = _scene(shape=(520, 680))
    ref = big[20:500, 20:660]
    live = big[20 - dy:500 - dy, 20 - dx:660 - dx]
    got_dx, got_dy, response = av.roi_shift(ref, live, (200, 130, 240, 220))
    assert got_dx == pytest.approx(dx, abs=0.5)
    assert got_dy == pytest.approx(dy, abs=0.5)
    assert response > 0.1


@pytest.mark.parametrize('mode', av.MODES)
def test_compose_keeps_live_shape(mode):
    ref = _scene(shape=(240, 320))
    live = _scene(1)
    assert av.compose(ref, live, mode).shape == live.shape


def test_compose_unknown_mode():
    with pytest.raises(ValueError):
        av.compose(_scene(), _scene(), 'xray')


def test_camera_holders_reads_fake_proc(tmp_path):
    device = tmp_path / 'video7'
    device.write_text('')
    fd_dir = tmp_path / 'proc' / '4242' / 'fd'
    fd_dir.mkdir(parents=True)
    os.symlink(device, fd_dir / '51')
    (tmp_path / 'proc' / '4242' / 'cmdline').write_bytes(b'python\0omx_fleet_worker.py\0')
    other = tmp_path / 'proc' / '77' / 'fd'
    other.mkdir(parents=True)
    os.symlink(tmp_path / 'elsewhere', other / '3')
    holders = av.camera_holders(str(device), proc_root=str(tmp_path / 'proc'))
    assert holders == [(4242, 'python omx_fleet_worker.py')]
