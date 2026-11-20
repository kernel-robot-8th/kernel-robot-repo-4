#!/usr/bin/env python3
"""
토크를 켜지 않고 팔 관절 값을 읽는 도구 (쓰기 없음, 팔을 움직이지 않음).

왜: 쉬는 자세(rest_pose)를 재려면 팔을 손으로 그 자세에 놓아야 하는데, 실행기를 켜면 토크가 켜져
손으로 옮길 수 없고 시작 자세로 옮겨진다. 이 도구는 포트를 잠깐 열어 Present_Position 만 읽고 닫는다.
값은 실행기와 같은 lerobot omx_follower 단위다 (몸 -100..100, 그리퍼 0..100, 그 팔의 보정 파일 기준).

  # 실행기(팔 노드 worker)가 꺼져 있을 때만. 같은 포트를 두 프로그램이 열면 통신이 깨진다.
  ~/venv/il/bin/python read_pose.py --port /dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00
  ~/venv/il/bin/python read_pose.py --port ... --arm omx2 --save ~/il_ws/poses/rest_pose_omx2.json

  --robot-id: 보정 파일 이름 (fleet_arms.yaml 의 robot_id, 기본 omx_follower)
              ~/.cache/huggingface/lerobot/calibration/robots/omx_follower/<robot_id>.json
  --save: init_pose.json 과 같은 {"pose": {...}} 형식으로 저장 (arm_console.py saverest 와 같은 칸).
          fleet_arms.yaml 의 arms.<팔>.rest_pose 를 이 경로로 바꾸고 팔 노드를 다시 켜면 적용된다.

출력 (한 줄 JSON): {"pose": {관절: 값}, "torque": {관절: 0|1}, "robot_id": "...", "saved": 경로|null}
"""

import argparse
import json
from pathlib import Path
import sys
import time

GRIPPER = 'gripper'


def to_pose(positions):
    """{관절: 값} → 소수 둘째 자리 (init_pose.json 과 같은 모양)."""
    return {name: round(float(value), 2) for name, value in positions.items()}


def pose_file(pose, arm, robot_id, now=None):
    """저장할 내용. arm_console.py saverest 와 같은 칸에 source 만 다르다."""
    return {'source': 'read_pose (토크를 켜지 않고 읽음)', 'arm': arm, 'robot_id': robot_id,
            'saved_at': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now)),
            'units': 'lerobot omx_follower (body -100..100, gripper 0..100)', 'pose': pose}


def read(port, robot_id):
    """보정 파일로 단위를 맞춰 관절 값과 토크 상태를 읽는다. 모터에 쓰지 않는다."""
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    # 로봇 객체는 보정 파일을 읽고 버스를 만들기만 한다. robot.connect() 는 부르지 않는다:
    # configure() 가 토크를 끄고 동작 모드를 쓰기 때문이다. 버스만 열어 읽는다.
    robot = OmxFollower(OmxFollowerConfig(port=port, id=robot_id))
    if not robot.calibration:
        raise ValueError(f'보정 파일이 없음: {robot.calibration_fpath}')
    bus = robot.bus
    bus.connect(handshake=True)    # 모터 ID 확인 (ping, 읽기만)
    try:
        positions = bus.sync_read('Present_Position')
        torque = bus.sync_read('Torque_Enable', normalize=False)
    finally:
        bus.disconnect(disable_torque=False)    # 토크를 건드리지 않고 포트만 닫는다
    return to_pose(positions), {name: int(value) for name, value in torque.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument('--port', required=True)
    p.add_argument('--robot-id', default='omx_follower',
                   help='보정 파일 이름 (fleet_arms.yaml robot_id)')
    p.add_argument('--arm', default='', help='저장 파일에 적을 팔 이름 (예: omx2)')
    p.add_argument('--save', default='', help='쉬는 자세 파일로 저장할 경로')
    args = p.parse_args(argv)
    try:
        pose, torque = read(args.port, args.robot_id)
    except (ConnectionError, OSError, ValueError, RuntimeError, ImportError) as error:
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}, ensure_ascii=False),
              flush=True)
        return 1
    saved = None
    if args.save:
        target = Path(args.save).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(pose_file(pose, args.arm, args.robot_id),
                                     ensure_ascii=False, indent=2) + '\n')
        saved = str(target)
    if any(torque.values()):
        print('주의: 토크가 켜진 모터가 있다. 손으로 놓은 자세가 아닐 수 있다', file=sys.stderr)
    print(json.dumps({'pose': pose, 'torque': torque, 'robot_id': args.robot_id, 'saved': saved},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
