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
핑키 정차 위치 맞추기: 학습 때 위쪽 카메라 화면과 지금 화면을 겹쳐 본다 (읽기만, 팔·핑키를 움직이지 않음).

왜: 팔 모델은 지도 좌표가 아니라 위쪽 카메라 화면 속 자리로 학습됐다. 핑키(또는 그 위 박스·접시)가
학습 화면과 같은 자리에 오도록 손으로 밀어 맞춘 뒤, 그때 /pinkyN/amcl_pose 를 읽어 구역 좌표로 적는다.

기준 화면 (둘 중 하나):
  --ref <이미지>   예) ~/outputs/train/omx_1119_act/reference_top_demo5.jpg
  --dataset <LeRobot v3 폴더> --episode N --at start|release|<초>
      release = 그리퍼 전류가 잡음(-150 mA 이하)이던 마지막 프레임 (박스를 놓는 순간)
      영상은 AV1 이라 OpenCV 대신 ffmpeg 로 읽는다.
지금 화면 (둘 중 하나):
  --arm omx2     fleet_arms.yaml 의 top_model + arm_registry.yaml 의 보드 시리얼로 그 팔 허브의 위쪽 카메라
  --cam <장치|영상 파일>   /dev/videoN 또는 시험용 영상 (--shift dx,dy 로 일부러 옮겨 볼 수 있음)

  ~/venv/il/bin/python align_view.py --arm omx2 \
      --dataset ~/il_ws/datasets/omx_1031_JH_v1_success --at start

창: 마우스로 끌어 맞출 영역(접시·박스 자리)을 고르면 그 안의 어긋남 dx, dy [px] 를 계속 보여 준다.
키: m 보기 바꾸기(겹치기/윤곽/차이), [ ] 투명도, r 영역 지우기, s 저장(~/il_ws/align/), q 끝.
--once 는 창 없이 한 번 재고 JSON 한 줄을 찍는다 (--roi 필요, --out 에 겹친 화면 저장).
"""

import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GRIP_CLOSED_MA = -150    # fleet_runtime success_motion 의 grip_closed_ma 와 같은 값
MODES = ('blend', 'edges', 'diff')
TOP_KEY = 'observation.images.top'


# ---------- 순수 계산 (시험 대상) ----------

def release_index(currents, closed_ma=GRIP_CLOSED_MA):
    """그리퍼가 잡고 있던(전류 ≤ closed_ma) 마지막 프레임 번호. 한 번도 안 잡았으면 None."""
    held = [i for i, value in enumerate(currents) if value <= closed_ma]
    return held[-1] if held else None


def frame_time(from_timestamp, frame_index, fps):
    """에피소드 안 프레임 번호 → 묶음 영상 파일 안의 시각 [s]."""
    return float(from_timestamp) + frame_index / float(fps)


def parse_at(at):
    """--at 값: 'start' / 'release' / 초(float)."""
    if at in ('start', 'release'):
        return at
    try:
        return float(at)
    except ValueError:
        raise ValueError(f'--at 은 start, release, 초 중 하나: {at!r}') from None


def parse_box(text, name):
    """'a,b' 또는 'a,b,c,d' 정수 목록."""
    try:
        values = tuple(int(v) for v in text.split(','))
    except ValueError:
        raise ValueError(f'{name} 형식이 틀림: {text!r}') from None
    return values


def clip_roi(roi, shape):
    """(x, y, w, h) 를 화면 안으로 자른다. 너무 작으면(16 px 미만) None."""
    x, y, w, h = roi
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    height, width = shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def dft_size(n):
    """FFT 에 알맞은 크기 (2·3·5 의 곱) 중 n 이하에서 가장 큰 것."""
    for m in range(n, 0, -1):
        if cv2.getOptimalDFTSize(m) == m:
            return m
    return n


def roi_shift(ref, live, roi):
    """
    영역 안에서 지금 화면이 기준보다 몇 픽셀 옮겨졌는지 (dx, dy, 신뢰도).

    dx > 0 이면 지금 화면의 물체가 기준보다 오른쪽, dy > 0 이면 아래에 있다.
    신뢰도(phaseCorrelate response)는 0~1, 0.1 아래면 영역에 무늬가 적거나 많이 다르다는 뜻이다.
    """
    x, y, w, h = roi
    # 크기가 FFT 에 알맞지 않으면(예: 220) phaseCorrelate 가 안에서 덧대어 0.5 px 치우친다 (실측).
    # 가운데를 기준으로 알맞은 크기로 줄인다.
    fw, fh = dft_size(w), dft_size(h)
    x, y, w, h = x + (w - fw) // 2, y + (h - fh) // 2, fw, fh
    a = cv2.cvtColor(ref[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(live[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    return float(dx), float(dy), float(response)


def compose(ref, live, mode, alpha=0.5):
    """보기 모드별 합친 화면. 두 화면 크기가 다르면 지금 화면에 맞춘다."""
    if ref.shape != live.shape:
        ref = cv2.resize(ref, (live.shape[1], live.shape[0]))
    if mode == 'blend':
        return cv2.addWeighted(ref, alpha, live, 1.0 - alpha, 0)
    if mode == 'edges':
        out = live.copy()
        edges = cv2.Canny(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), 60, 160)
        out[edges > 0] = (0, 255, 0)
        return out
    if mode == 'diff':
        return cv2.absdiff(ref, live)
    raise ValueError(f'모르는 보기: {mode}')


def shifted(frame, dx, dy):
    """시험용: 화면을 (dx, dy) 만큼 옮긴다 (빈 곳은 검정)."""
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]))


# ---------- 기준 화면 ----------

def video_frame(path, seconds):
    """영상에서 한 장을 ffmpeg 로 뽑는다 (AV1 도 됨)."""
    cmd = ['ffmpeg', '-loglevel', 'error', '-ss', f'{seconds:.3f}', '-i', str(path),
           '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-']
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    frame = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f'영상에서 {seconds:.2f}s 프레임을 못 읽음: {path}')
    return frame


def dataset_reference(root, episode, at, video_key=TOP_KEY):
    """데이터셋(LeRobot v3)에서 그 에피소드의 기준 화면과 설명."""
    import pandas as pd

    root = Path(root).expanduser()
    info = json.loads((root / 'meta' / 'info.json').read_text())
    fps = info['fps']
    files = sorted(glob.glob(str(root / 'meta' / 'episodes' / '*' / '*.parquet')))
    if not files:
        raise FileNotFoundError(f'에피소드 메타가 없음: {root}/meta/episodes')
    episodes = pd.concat([pd.read_parquet(f) for f in files])
    rows = episodes[episodes['episode_index'] == episode]
    if rows.empty:
        raise ValueError(f'에피소드 {episode} 없음 (0..{int(episodes["episode_index"].max())})')
    row = rows.iloc[0]
    prefix = f'videos/{video_key}/'
    video = root / info['video_path'].format(
        video_key=video_key, chunk_index=int(row[prefix + 'chunk_index']),
        file_index=int(row[prefix + 'file_index']))
    start = float(row[prefix + 'from_timestamp'])
    length = int(row['length'])

    if at == 'start':
        index = 0
    elif at == 'release':
        data = pd.concat([
            pd.read_parquet(f, columns=['episode_index', 'frame_index', 'aux.gripper_current'])
            for f in sorted(glob.glob(str(root / 'data' / '*' / '*.parquet')))])
        data = data[data['episode_index'] == episode].sort_values('frame_index')
        currents = [float(np.ravel(v)[0]) for v in data['aux.gripper_current']]
        index = release_index(currents)
        if index is None:
            raise ValueError(f'에피소드 {episode} 에 그리퍼가 잡은 프레임이 없음')
    else:
        index = min(int(round(at * fps)), length - 1)
    label = f'{root.name} ep{episode} f{index}/{length} ({at})'
    return video_frame(video, frame_time(start, index, fps)), label


# ---------- 지금 화면 ----------

def arm_top_camera(arm, arms_file, registry_file):
    """팔 이름 → 그 팔 보드 허브의 위쪽 카메라 경로 (usb_cams.find_cameras 재사용)."""
    import yaml
    sys.path.insert(0, str(HERE))
    import usb_cams

    arms = yaml.safe_load(Path(arms_file).expanduser().read_text())['arms']
    registry = yaml.safe_load(Path(registry_file).expanduser().read_text())['arms']
    if arm not in arms or arm not in registry:
        raise ValueError(f'{arm} 이 {arms_file} 또는 {registry_file} 에 없음')
    model = arms[arm].get('top_model')
    if not model:
        raise ValueError(f'{arm} 에 top_model 이 없음 (예전 top 경로 방식이면 --cam 으로 직접 준다)')
    port = f'/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_{registry[arm]["serial"]}-if00'
    return usb_cams.find_cameras(port, {'top': model})['top']


def camera_holders(device, proc_root='/proc'):
    """그 카메라 장치를 열고 있는 프로세스 [(pid, 명령줄)]. 실행기와 겹쳐 열지 않으려고 본다."""
    target = os.path.realpath(device)
    found = []
    for fd_dir in glob.glob(os.path.join(proc_root, '[0-9]*', 'fd')):
        pid = int(Path(fd_dir).parent.name)
        if pid == os.getpid():
            continue
        try:
            links = [os.readlink(os.path.join(fd_dir, fd)) for fd in os.listdir(fd_dir)]
        except OSError:
            continue
        if target in links:
            try:
                cmd = Path(fd_dir).parent.joinpath('cmdline').read_bytes()
                cmd = cmd.replace(b'\0', b' ').decode(errors='replace').strip()
            except OSError:
                cmd = '?'
            found.append((pid, cmd))
    return found


class CameraSource:
    """V4L 카메라. 학습 때와 같은 640x480·MJPG 로 연다."""

    def __init__(self, device, width, height, mjpg):
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if mjpg:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(f'카메라를 못 염: {device}')

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError('카메라에서 화면을 못 읽음')
        return frame

    def close(self):
        self.cap.release()


class VideoFileSource:
    """시험용: 영상 파일의 한 시각을 계속 '지금 화면' 으로 준다 (ffmpeg, AV1 가능)."""

    def __init__(self, path, seconds, shift):
        frame = video_frame(path, seconds)
        self.frame = shifted(frame, *shift) if any(shift) else frame

    def read(self):
        return self.frame.copy()

    def close(self):
        pass


# ---------- 화면 ----------

def draw_overlay(view, roi, shift, mode, alpha, label):
    """영역 사각형, 어긋남, 안내 글자를 그린다."""
    cv2.putText(view, f'{mode} a={alpha:.2f}  ref: {label}', (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    if roi:
        x, y, w, h = roi
        cv2.rectangle(view, (x, y), (x + w, y + h), (0, 200, 255), 2)
    if shift:
        dx, dy, response = shift
        good = abs(dx) <= 3 and abs(dy) <= 3 and response >= 0.1
        color = (0, 220, 0) if good else (0, 0, 255)
        cv2.putText(view, f'dx={dx:+.1f}px dy={dy:+.1f}px conf={response:.2f}', (8, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    return view


def save_pair(out_dir, live, view, label):
    """지금 화면과 겹친 화면을 시각 이름으로 저장."""
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    cv2.imwrite(str(out_dir / f'{stamp}_live.jpg'), live)
    cv2.imwrite(str(out_dir / f'{stamp}_view.jpg'), view)
    (out_dir / f'{stamp}_ref.txt').write_text(label + '\n')
    return out_dir / f'{stamp}_view.jpg'


def run_window(source, ref, label, roi, args):
    """창을 띄워 계속 비교한다."""
    state = {'roi': roi, 'drag': None, 'mode': 0, 'alpha': 0.5}

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state['drag'] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and state['drag']:
            x0, y0 = state['drag']
            state['drag'] = None
            state['roi'] = clip_roi((x0, y0, x - x0, y - y0), ref.shape)

    name = 'align_view (q 끝)'
    cv2.namedWindow(name)
    cv2.setMouseCallback(name, on_mouse)
    while True:
        live = source.read()
        if ref.shape != live.shape:
            ref = cv2.resize(ref, (live.shape[1], live.shape[0]))
        mode = MODES[state['mode']]
        shift = roi_shift(ref, live, state['roi']) if state['roi'] else None
        view = draw_overlay(compose(ref, live, mode, state['alpha']), state['roi'], shift,
                            mode, state['alpha'], label)
        cv2.imshow(name, view)
        key = cv2.waitKey(30) & 0xFF
        if key == ord('q') or cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord('m'):
            state['mode'] = (state['mode'] + 1) % len(MODES)
        elif key == ord('['):
            state['alpha'] = max(0.0, state['alpha'] - 0.1)
        elif key == ord(']'):
            state['alpha'] = min(1.0, state['alpha'] + 0.1)
        elif key == ord('r'):
            state['roi'] = None
        elif key == ord('s'):
            print(f'저장: {save_pair(args.save_dir, live, view, label)}', flush=True)
    cv2.destroyAllWindows()


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ref = p.add_mutually_exclusive_group(required=True)
    ref.add_argument('--ref', help='기준 이미지 파일')
    ref.add_argument('--dataset', help='로컬 LeRobot v3 데이터셋 폴더')
    p.add_argument('--episode', type=int, default=0)
    p.add_argument('--at', default='start', help='start | release | 초 (기본 start)')
    live = p.add_mutually_exclusive_group(required=True)
    live.add_argument('--arm', help='fleet_arms.yaml 의 팔 이름 (예: omx2)')
    live.add_argument('--cam', help='/dev/videoN 또는 시험용 영상 파일')
    p.add_argument('--cam-at', type=float, default=0.0, help='--cam 이 영상 파일일 때 시각 [s]')
    p.add_argument('--shift', default='0,0', help='시험용: 영상 파일 화면을 dx,dy 만큼 옮김')
    p.add_argument('--arms-file', default=str(HERE / 'fleet_arms.yaml'))
    p.add_argument('--registry', default=str(
        REPO / 'src' / 'cobot_manipulation' / 'config' / 'arm_registry.yaml'))
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--no-mjpg', action='store_true')
    p.add_argument('--roi', help='x,y,w,h (창에서는 마우스로 고를 수 있음)')
    p.add_argument('--once', action='store_true', help='창 없이 한 번 재고 JSON 출력')
    p.add_argument('--out', help='--once 때 겹친 화면 저장 경로')
    p.add_argument('--save-dir', default='~/il_ws/align')
    return p


def open_source(args):
    """--arm / --cam 으로 지금 화면 소스를 연다. 카메라를 다른 프로그램이 쓰고 있으면 멈춘다."""
    device = args.cam
    if args.arm:
        device = arm_top_camera(args.arm, args.arms_file, args.registry)
    if device.startswith('/dev/'):
        holders = camera_holders(device)
        if holders:
            who = '; '.join(f'pid {pid}: {cmd[:120]}' for pid, cmd in holders)
            raise RuntimeError(f'{device} 를 다른 프로그램이 쓰고 있음 → 그 팔 실행기를 끈 뒤 다시: {who}')
        return CameraSource(device, args.width, args.height, not args.no_mjpg), device
    return VideoFileSource(device, args.cam_at, parse_box(args.shift, '--shift')), device


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.ref:
            ref = cv2.imread(str(Path(args.ref).expanduser()))
            if ref is None:
                raise FileNotFoundError(f'기준 이미지를 못 읽음: {args.ref}')
            label = Path(args.ref).name
        else:
            ref, label = dataset_reference(args.dataset, args.episode, parse_at(args.at))
        roi = parse_box(args.roi, '--roi') if args.roi else None
        if roi is not None and len(roi) != 4:
            raise ValueError('--roi 는 x,y,w,h')
        source, device = open_source(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'실패: {error}', file=sys.stderr)
        return 1
    try:
        if not args.once:
            run_window(source, ref, label, clip_roi(roi, ref.shape) if roi else None, args)
            return 0
        live = source.read()
        if ref.shape != live.shape:
            ref = cv2.resize(ref, (live.shape[1], live.shape[0]))
        roi = clip_roi(roi, ref.shape) if roi else None
        shift = roi_shift(ref, live, roi) if roi else None
        if args.out:
            view = draw_overlay(compose(ref, live, 'blend'), roi, shift, 'blend', 0.5, label)
            cv2.imwrite(str(Path(args.out).expanduser()), view)
        result = {'ref': label, 'live': device, 'roi': roi}
        if shift:
            result.update(dx=round(shift[0], 2), dy=round(shift[1], 2),
                          confidence=round(shift[2], 3))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        source.close()


if __name__ == '__main__':
    sys.exit(main())
