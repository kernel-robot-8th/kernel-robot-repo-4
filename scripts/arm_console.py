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
팔 어댑터 노드에 명령을 하나씩 보내는 시험 콘솔 (관제 대신).

관제 웹에는 켜기·끄기·정지만 있고 작업(pick·load)은 주문 시나리오가 PICK 단계에 이르러야 나간다.
이 콘솔은 관제와 같은 토픽·같은 JSON 으로 둘 다 보내, 팔 하나만으로 전체 흐름을 시험한다.

실행 (어댑터는 scripts/run_arm_adapter.sh 로 띄운다):
  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST   # 어댑터와 같게
  python3 scripts/arm_console.py            # 팔 이름 바꾸려면: ... arm_console.py omx_1 omx1

명령 (한 줄에 하나):
  start          CMD_START (새 epoch)        → 팔 연결, 토크 켜짐
  pick | load    작업 요청 (/fleet/work_request) → 팔이 실제로 움직인다
  hold           CMD_HOLD                    → 정지 (토크 유지)
  unhold         CMD_RELEASE_HOLD            → 정지 해제
  latch          CMD_SOFT_LATCH              → 소프트 정지 잠금 (unlatch 또는 reset 으로 풀림)
  unlatch        CMD_UNLATCH                 → 잠금 해제 (팔은 안 움직임, 다음 작업부터 받음)
  reset          CMD_RESET                   → 쉬는 자세면 토크 끔, 아니면 거절
  status | s     최근 ArmStatus 한 번 출력
  saverest [경로] 지금 관절을 쉬는 자세 파일로 저장 (init_pose.json 형식, 녹화기 'Rest 저장' 과 같음)
                 기본 경로: ~/il_ws/poses/rest_pose_<target>.json (모델 번들 규격)
                 그 뒤 fleet_arms.yaml 의 rest_pose 를 이 경로로 바꾸고 어댑터를 다시 켜면 적용된다
  wait N         N 초 기다림 (파이프로 넣을 때)
  quit | q       끝
ACK·작업 결과는 오는 대로 찍힌다.
"""

import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from cobot_interfaces.msg import ArmCommand, ArmStatus, CommandAck
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

ARM = sys.argv[1] if len(sys.argv) > 1 else 'omx_1'        # 명세 이름 (토픽·헤더)
TARGET = sys.argv[2] if len(sys.argv) > 2 else 'omx1'      # 작업 요청 target (시나리오 이름)
TTL_MS = 5000               # [ms] 관제 arm_command_node 기본값과 같게
WORK_TIMEOUT_SEC = 150.0    # [s] pick 90 s + 시작·안전 자세 이동
# CLAUDE.md 7절: 10·12 는 실물 구동용 설계 제안(D2). 확정 전에는 시험 도구로 쓰지 않는다
BLOCKED_DOMAINS = {'10', '12'}
RESULT_NAMES = {v: k for k, v in vars(CommandAck).items()
                if k.startswith(('ACCEPTED', 'REJECTED')) and isinstance(v, int)}
STALE_SEC = 3.0             # [s] 이보다 오래된 관절 값이면 저장할 때 경고
# 쉬는 자세 파일 자리 (omx_fleet README '모델 번들 규격': ~/il_ws/poses/rest_pose_<팔>.json).
# 쉬는 자세는 번들이 아니라 팔에 딸린 값이라 실행기 폴더(git worktree) 밖에 둔다.
POSES_DIR = Path('~/il_ws/poses').expanduser()
COMMANDS = {'start': ArmCommand.CMD_START, 'reset': ArmCommand.CMD_RESET,
            'hold': ArmCommand.CMD_HOLD, 'unhold': ArmCommand.CMD_RELEASE_HOLD,
            'latch': ArmCommand.CMD_SOFT_LATCH, 'unlatch': ArmCommand.CMD_UNLATCH}


def say(text):
    print(f'\r{time.strftime("%H:%M:%S")} {text}', flush=True)


class Console:
    """명령 번호(epoch·seq)를 매기고 ACK·결과·상태를 받는다."""

    def __init__(self, node):
        self.node = node
        self.epoch = 0
        self.seq = 0
        self.work_seq = 0
        self.status = None
        self.cmd_pub = node.create_publisher(ArmCommand, f'/control_center/{ARM}/command', 10)
        self.work_pub = node.create_publisher(String, '/fleet/work_request', 10)
        node.create_subscription(CommandAck, f'/manipulation/{ARM}/command_ack', self.on_ack, 50)
        node.create_subscription(String, '/fleet/work_result', self.on_result, 50)
        node.create_subscription(ArmStatus, f'/manipulation/{ARM}/status', self.on_status,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))

    def on_ack(self, m):
        name = RESULT_NAMES.get(m.result, m.result)
        stop = ' (정지 실행됨)' if m.stop_executed else ''
        say(f'  ◀ ACK seq={m.seq} {name}{stop} {m.reason}')

    def on_result(self, m):
        try:
            data = json.loads(m.data)
        except ValueError:
            say(f'  ◀ RESULT (JSON 아님) {m.data[:200]}')
            return
        brief = {k: data[k] for k in ('stage', 'success', 'detail') if k in data}
        say(f'  ◀ RESULT {json.dumps(brief, ensure_ascii=False)}')
        say(f'           data {json.dumps(data.get("data", {}), ensure_ascii=False)[:400]}')

    def on_status(self, m):
        self.status = m

    def command(self, word):
        cmd = COMMANDS[word]
        if cmd == ArmCommand.CMD_START:
            # 팔이 받아들인 epoch 보다 커야 한다. 팔 노드를 다시 켜도 되게 시각으로 만든다.
            self.epoch, self.seq = max(self.epoch + 1, int(time.time())), 0
        elif self.status is not None:
            # 관제 웹이 START 를 냈을 수도 있다: 팔이 받아들인 번호를 따른다
            self.epoch = self.status.epoch_accepted
            self.seq = max(self.seq, self.status.last_seq_accepted)
        self.seq += 1
        m = ArmCommand(command=cmd)
        now = time.time()
        h = m.header
        h.command_id, h.robot_id = str(uuid.uuid4()), ARM
        h.epoch, h.seq, h.ttl_ms = self.epoch, self.seq, TTL_MS
        h.issued_at.sec, h.issued_at.nanosec = int(now), int((now % 1) * 1e9)
        h.issued_by = 'arm_console'
        self.cmd_pub.publish(m)
        say(f'▶ {word.upper()} epoch={self.epoch} seq={self.seq}')

    def work(self, action):
        self.work_seq += 1
        req = {'request_id': uuid.uuid4().hex, 'order_id': 'console', 'robot_id': 'pinky1',
               'stage': action.upper(), 'target': TARGET, 'action': action,
               'session_id': 'console', 'seq': self.work_seq, 'issued_at': time.time(),
               'ttl_sec': TTL_MS / 1000.0, 'timeout_sec': WORK_TIMEOUT_SEC}
        self.work_pub.publish(String(data=json.dumps(req)))
        say(f'▶ 작업 {action} (최대 {WORK_TIMEOUT_SEC:.0f}s)')

    def save_rest(self, path):
        m = self.status
        if m is None or not m.joint_names:
            say('  관절 값이 없음: start 로 켠 뒤 다시 (상태에 관절이 실려야 한다)')
            return
        age = time.time() - (m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)
        if not m.torque_enabled:
            say('  ⚠ 토크가 꺼진 상태의 값이다 (켠 뒤 저장하는 게 정확하다)')
        if age > STALE_SEC:
            say(f'  ⚠ 관절 값이 {age:.0f}s 전 것이다 (작업 중이면 끝난 뒤 다시)')
        pose = {n: round(float(p), 2) for n, p in zip(m.joint_names, m.joint_positions)}
        if not math.isnan(m.gripper_position):
            pose['gripper'] = round(float(m.gripper_position), 2)
        target = Path(path).expanduser() if path else POSES_DIR / f'rest_pose_{TARGET}.json'
        data = {'source': 'arm_console saverest', 'arm': TARGET,
                'saved_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'units': 'lerobot omx_follower (body -100..100, gripper 0..100)', 'pose': pose}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        except OSError as error:
            say(f'  저장 실패: {error}')
            return
        say(f'  쉬는 자세 저장: {target}')
        say(f'       {json.dumps(pose, ensure_ascii=False)}')
        say(f'  → fleet_arms.yaml 의 arms.{TARGET}.rest_pose 를 이 경로로 바꾸고 어댑터를 다시 켠다')

    def show(self):
        m = self.status
        if m is None:
            say('  상태 아직 못 받음 (노드가 떠 있나? 같은 ROS_DOMAIN_ID 인가?)')
            return
        joints = ', '.join(f'{n}={p:.1f}' for n, p in zip(m.joint_names, m.joint_positions))
        say(f'  상태 토크={m.torque_enabled} 정지={m.hold_active}({m.hold_reason}) '
            f'퇴피={m.retract_safe}/실측={m.retract_safe_measured} '
            f'epoch={m.epoch_accepted} seq={m.last_seq_accepted}')
        say(f'       관절 {joints or "(없음)"} 그리퍼={m.gripper_position:.1f} '
            f'stamp={m.header.stamp.sec}')


def main():
    domain = os.environ.get('ROS_DOMAIN_ID', '0')
    if domain in BLOCKED_DOMAINS:
        say(f'도메인 {domain} 은 실물 구동용 설계 제안(D2). 이 콘솔로 쓰지 않는다')
        sys.exit(1)
    scope = os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') or 'SUBNET'
    rclpy.init()
    node = rclpy.create_node('arm_console')
    console = Console(node)
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass

    spinner = threading.Thread(target=spin, daemon=True)
    spinner.start()
    time.sleep(1.5)     # 노드와 서로 찾을 틈. 바로 보내면 첫 메시지가 사라진다
    say(f'팔 {ARM} (작업 target {TARGET}), 도메인 {domain} {scope}')
    say('명령: start pick load hold unhold latch reset s saverest wait q')
    if scope != 'LOCALHOST':
        say('⚠ 같은 망 공개: 이 도메인의 다른 관제·노드도 이 명령을 본다')
    try:
        for line in sys.stdin:
            words = line.split()
            if not words:
                continue
            word = words[0].lower()
            if word in ('quit', 'q'):
                break
            if word in COMMANDS:
                console.command(word)
            elif word in ('pick', 'load'):
                console.work(word)
            elif word in ('status', 's'):
                console.show()
            elif word == 'saverest':
                console.save_rest(words[1] if len(words) > 1 else None)
            elif word == 'wait':
                time.sleep(float(words[1]) if len(words) > 1 else 1.0)
            else:
                say(f'  모르는 명령: {word}')
    except KeyboardInterrupt:
        pass
    time.sleep(0.3)     # 마지막 ACK 받을 틈
    rclpy.shutdown()    # spin 스레드를 먼저 멈춘 뒤 정리 (반대 순서면 종료 때 abort)
    spinner.join(timeout=2.0)
    executor.shutdown()
    node.destroy_node()


if __name__ == '__main__':
    main()
