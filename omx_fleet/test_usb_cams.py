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

"""usb_cams 시험: 가짜 /sys·/dev 트리 (8-OMEN 실측 모양)."""

import os

import pytest
import usb_cams

JIELI, INNO = '4c4a:4a55', '0c45:6367'
WANTS = {'top': JIELI, 'wrist': INNO}
BUS = 'devices/pci0000:80/0000:80:14.0/usb3'


def _usb_dev(sys_root, hub, port, model=None):
    """sys_root/BUS/3-<hub>/3-<hub>.<port> 장치 폴더를 만든다."""
    path = sys_root / BUS / f'3-{hub}' / f'3-{hub}.{port}'
    (path / f'3-{hub}.{port}:1.0').mkdir(parents=True)
    if model:
        vid, pid = model.split(':')
        (path / 'idVendor').write_text(vid + '\n')
        (path / 'idProduct').write_text(pid + '\n')
    return path / f'3-{hub}.{port}:1.0'


def _board(root, hub, port, tty):
    sys_root, dev = root / 'sys', root / 'dev'
    iface = _usb_dev(sys_root, hub, port)
    (sys_root / 'class' / 'tty' / tty).mkdir(parents=True)
    os.symlink(iface, sys_root / 'class' / 'tty' / tty / 'device')
    (dev / 'serial' / 'by-id').mkdir(parents=True, exist_ok=True)
    (dev / tty).write_text('')
    link = dev / 'serial' / 'by-id' / f'usb-ROBOTIS_OpenRB-150_{tty}-if00'
    os.symlink(dev / tty, link)
    return str(link)


def _camera(root, hub, port, model, video):
    sys_root, dev = root / 'sys', root / 'dev'
    iface = _usb_dev(sys_root, hub, port, model)
    for offset, index in ((0, '0'), (1, '1')):   # 장치마다 캡처(0)·메타데이터(1) 노드
        node = sys_root / 'class' / 'video4linux' / f'video{video + offset}'
        node.mkdir(parents=True)
        os.symlink(iface, node / 'device')
        (node / 'index').write_text(index + '\n')
        (dev / f'video{video + offset}').write_text('')
    (dev / 'v4l' / 'by-path').mkdir(parents=True, exist_ok=True)
    os.symlink(dev / f'video{video}',
               dev / 'v4l' / 'by-path' / f'usb-0:{hub}.{port}:1.0-video-index0')


@pytest.fixture
def two_arms(tmp_path):
    """omx1 = 허브 10 (보드 10.4), omx2 = 허브 4 (보드 4.4). 카메라 기종은 같다."""
    ports = {'omx1': _board(tmp_path, 10, 4, 'ttyACM1'), 'omx2': _board(tmp_path, 4, 4, 'ttyACM0')}
    _camera(tmp_path, 10, 1, JIELI, 8)
    _camera(tmp_path, 10, 2, INNO, 10)
    _camera(tmp_path, 4, 1, JIELI, 6)   # 4.3 에서 4.1 로 다시 잡힌 경우
    _camera(tmp_path, 4, 2, INNO, 4)
    return tmp_path, ports


def _find(root, port):
    return usb_cams.find_cameras(port, WANTS, str(root / 'sys'), str(root / 'dev'))


def test_each_arm_gets_cameras_on_its_own_hub(two_arms):
    root, ports = two_arms
    omx1, omx2 = _find(root, ports['omx1']), _find(root, ports['omx2'])
    assert omx1['top'].endswith('usb-0:10.1:1.0-video-index0')
    assert omx1['wrist'].endswith('usb-0:10.2:1.0-video-index0')
    assert omx2['top'].endswith('usb-0:4.1:1.0-video-index0')
    assert omx2['wrist'].endswith('usb-0:4.2:1.0-video-index0')


def test_missing_camera_is_error(tmp_path):
    port = _board(tmp_path, 4, 4, 'ttyACM0')
    _camera(tmp_path, 4, 2, INNO, 4)
    with pytest.raises(usb_cams.CameraError, match='top.*없음'):
        _find(tmp_path, port)


def test_two_same_model_on_hub_is_error(two_arms):
    root, ports = two_arms
    _camera(root, 4, 3, JIELI, 20)
    with pytest.raises(usb_cams.CameraError, match='2대'):
        _find(root, ports['omx2'])
