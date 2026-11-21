#!/usr/bin/env python3
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
팔 보드가 꽂힌 USB 허브에서 모델 ID 로 카메라를 찾는다 (sysfs 만 읽고 장치는 열지 않음).

왜: 두 팔의 카메라가 같은 기종(Jieli 4c4a:4a55, Innomaker 0c45:6367 SN0001)이라
/dev/v4l/by-id 이름이 겹치고, by-path 는 다시 꽂으면 바뀐다. 팔마다 허브 하나에 보드와
카메라를 같이 꽂으므로, 시리얼로 찾은 보드의 허브를 기준으로 삼으면 어느 팔 카메라인지 알 수 있다.

확인: python usb_cams.py <ROBOT_PORT> top=4c4a:4a55 wrist=0c45:6367
"""

import glob
import os
import re
import sys

MODEL_PATTERN = re.compile(r'^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')
BUS_PATTERN = re.compile(r'^usb\d+$')


class CameraError(Exception):
    """카메라를 하나로 정하지 못함."""


def _read(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return ''


def _hub_key(usb_dev):
    """
    USB 장치 폴더의 부모 허브를 (컨트롤러 경로, 포트 경로) 로 돌려준다.

    버스 번호(3-10 의 3)는 뺀다. USB3 허브는 USB2·USB3 두 버스에 짝으로 잡혀서,
    USB2 보드와 USB3 카메라가 같은 허브여도 버스 번호가 다를 수 있기 때문이다.
    """
    hub = os.path.dirname(usb_dev)
    name = os.path.basename(hub)
    if BUS_PATTERN.match(name) or '-' not in name:
        return None   # 허브 없이 PC 에 바로 꽂힘
    controller = os.path.dirname(os.path.dirname(hub))
    parts = hub.split(os.sep)
    for index, part in enumerate(parts):
        if BUS_PATTERN.match(part):
            controller = os.sep.join(parts[:index])
            break
    return controller, name.split('-', 1)[1]


def board_hub(port, sys_root='/sys'):
    """보드 포트(/dev/serial/by-id/...)가 꽂힌 허브의 키와 사람용 이름."""
    tty = os.path.basename(os.path.realpath(port))
    device = os.path.join(sys_root, 'class', 'tty', tty, 'device')
    if not os.path.exists(device):
        raise CameraError(f'보드 포트를 찾지 못함: {port}')
    usb_dev = os.path.dirname(os.path.realpath(device))
    key = _hub_key(usb_dev)
    if key is None:
        raise CameraError(f'보드({tty})가 허브 없이 PC 에 바로 꽂혀 있어 카메라를 구별할 수 없음')
    return key, os.path.basename(os.path.dirname(usb_dev))


def list_cameras(sys_root='/sys', dev_root='/dev'):
    """영상 캡처 노드(index 0)마다 (허브 키, 'vid:pid', 장치 경로)."""
    by_path = {}
    # 같은 장치에 usb-0:… 와 usbv2-0:… 이름이 함께 있으면 정렬상 앞인 usb-0 을 쓴다
    for link in sorted(glob.glob(os.path.join(dev_root, 'v4l', 'by-path', '*-video-index0'))):
        by_path.setdefault(os.path.basename(os.path.realpath(link)), link)
    cameras = []
    for node in sorted(glob.glob(os.path.join(sys_root, 'class', 'video4linux', 'video*'))):
        if _read(os.path.join(node, 'index')) != '0':
            continue   # index 1 은 메타데이터 노드
        usb_dev = os.path.dirname(os.path.realpath(os.path.join(node, 'device')))
        model = (_read(os.path.join(usb_dev, 'idVendor')) + ':'
                 + _read(os.path.join(usb_dev, 'idProduct'))).lower()
        name = os.path.basename(node)
        cameras.append((_hub_key(usb_dev), model,
                        by_path.get(name, os.path.join(dev_root, name))))
    return cameras


def find_cameras(port, wants, sys_root='/sys', dev_root='/dev'):
    """
    {역할: 'vid:pid'} 마다 보드와 같은 허브의 카메라 경로를 돌려준다.

    역할마다 정확히 1대일 때만 정한다. 0대·2대 이상은 짐작하지 않고 CameraError.
    """
    key, hub_name = board_hub(port, sys_root)
    cameras = [cam for cam in list_cameras(sys_root, dev_root) if cam[0] == key]
    found = {}
    for role, model in wants.items():
        model = str(model).lower()
        paths = [path for _, cam_model, path in cameras if cam_model == model]
        if len(paths) != 1:
            what = '없음' if not paths else f'{len(paths)}대 ({", ".join(paths)})'
            raise CameraError(f'{role}({model}): 보드 허브 {hub_name} 에 {what}')
        found[role] = paths[0]
    return found


def main(argv):
    """현장 확인용: 찾은 경로만 출력한다."""
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    wants = dict(arg.split('=', 1) for arg in argv[1:])
    try:
        for role, path in find_cameras(argv[0], wants).items():
            print(f'{role}: {path}')
    except CameraError as error:
        print(f'실패: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
