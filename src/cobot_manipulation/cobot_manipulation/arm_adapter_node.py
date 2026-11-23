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
팔 1대의 관제 어댑터 노드.

관제 fleet_control 이 /fleet/work_request 로 보내는 요청 중 target 이 내 arm_id 인 것만
받아 백엔드에 맡기고, 실측 최종 결과를 /fleet/work_result 로 돌려준다.
팔 3대는 같은 실행 파일을 arm_id 만 바꿔 3번 띄운다 (한 대가 죽어도 나머지는 계속).

팔 켜기·끄기는 관제가 ArmCommand(/control_center/<omx_n>/command) 의 CMD_START·CMD_RESET 으로 한다.
노드는 꺼짐(DISARMED) 으로 시작하고, 판정 결과는 CommandAck, 상태는 ArmStatus 로 낸다 (arm_power_utils).
"""

import math
import os
import sys
import time
import uuid

from builtin_interfaces.msg import Time
from cobot_interfaces.msg import ArmCommand, ArmStatus, CommandAck
from cobot_manipulation import arm_backend_utils as backends
from cobot_manipulation import arm_info_utils as info_utils
from cobot_manipulation import arm_power_utils as power
from cobot_manipulation import arm_registry_utils as registry_utils
from cobot_manipulation import work_contract_utils as contract
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

# docs/fms_interfaces.md QoS 표: 명령·이벤트는 RELIABLE, 텔레메트리는 BEST_EFFORT KEEP_LAST 1
COMMAND_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
EVENT_QOS = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.VOLATILE)
TELEMETRY_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                           durability=DurabilityPolicy.VOLATILE)
# 설정성 정보: 늦게 붙은 관제도 마지막 값을 받게 TRANSIENT_LOCAL (CLAUDE.md §7)
INFO_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)
GRIPPER_KEY = 'gripper.pos'


def to_time(seconds):
    """[s] float → builtin_interfaces/Time."""
    sec = int(seconds)
    return Time(sec=sec, nanosec=int((seconds - sec) * 1e9))


class AdapterConfigError(Exception):
    """노드 설정이 틀려 시작할 수 없음."""


class ArmAdapterNode(Node):
    """팔 1대: 탐지 → 요청 검사 → 백엔드 실행 → 결과 발행."""

    def __init__(self):
        super().__init__('arm_adapter')
        params = {
            'arm_id': '',
            'registry_file': '',
            'serial_by_id_dir': '/dev/serial/by-id',
            'request_topic': '/fleet/work_request',
            'result_topic': '/fleet/work_result',
            'backend': 'none',
            'fake_duration_sec': 2.0,
            'worker_command': '',
            'worker_timeout_sec': 300.0,
            # 실행기가 없을 때 모터 토크를 읽는 명령. 비우면 worker_command 의 omx_fleet_worker.py 옆
            # torque_probe.py 를 같은 python 으로 쓴다 (arm_backend_utils.torque_probe_argv).
            'torque_probe_command': '',
            'dedupe_size': 256,
            'detect_period_sec': 1.0,
            'tick_sec': 0.1,
            # 명세 토픽 이름(omx_1). 비우면 arm_id(omx1) 에서 만든다.
            'interface_arm_id': '',
            'command_topic': '',
            'status_topic': '',
            'ack_topic': '',
            'info_topic': '',
            'info_period_sec': 5.0,
            'auto_start': False,
            'status_period_sec': 0.1,
            'state_poll_sec': 1.0,
            'release_timeout_sec': 5.0,
        }
        for name, default in params.items():
            self.declare_parameter(name, default)
        value = {name: self.get_parameter(name).value for name in params}

        self.arm_id = value['arm_id']
        if not registry_utils.ARM_ID_PATTERN.fullmatch(self.arm_id or ''):
            raise AdapterConfigError('arm_id 파라미터가 필요합니다 (예: omx1)')
        try:
            self.registry = registry_utils.load_registry(value['registry_file'])
        except registry_utils.RegistryError as error:
            raise AdapterConfigError(str(error)) from error
        try:
            self.backend = backends.make_backend(
                value['backend'], value['fake_duration_sec'], {
                    'arm_id': self.arm_id,
                    'command': value['worker_command'],
                    'timeout_sec': value['worker_timeout_sec'],
                    'probe_command': value['torque_probe_command'],
                    'log': self.get_logger().info,
                })
        except ValueError as error:
            raise AdapterConfigError(str(error)) from error
        if self.backend.name == 'fake':
            ok, message = backends.check_domain(os.environ)
            if not ok:
                raise AdapterConfigError(message)
            self.get_logger().warning(f'fake 백엔드: 실제 팔은 움직이지 않습니다 ({message})')
        if self.backend.name == 'worker':
            if not self.backend.argv:
                raise AdapterConfigError('backend=worker 에는 worker_command 가 필요합니다')
            self.get_logger().warning(
                'worker 백엔드: CMD_START 를 받으면 실행기가 팔에 연결해 토크를 켭니다 (실제 팔). '
                f'명령={self.backend.argv[0]}')

        self.by_id_dir = value['serial_by_id_dir']
        self.filter = contract.RequestFilter(self.arm_id, value['dedupe_size'])
        self.state, self.port, self.reason = None, None, ''
        self.held = False
        # 실행기가 없을 때 모터 토크를 한 번 잴 차례인지. 노드가 뜰 때·보드를 다시 찾을 때·끈 뒤에 잰다.
        # 실행기가 강제로 꺼지면 토크가 켜진 채 남는데, 새 노드는 그것을 모르기 때문이다 (2026-11-21 omx2).
        self.probe_due = True

        self.iid = value['interface_arm_id'] or power.interface_arm_id(self.arm_id)
        self.gate = power.CommandGate(self.iid)
        self.power = power.DISARMED
        self.auto_start = value['auto_start']
        self.boot_id = str(uuid.uuid4())
        self.retract = (False, False)   # (retract_safe, retract_safe_measured)
        self.pending_reset = None       # 끄기 결과를 기다리는 RESET: (ack 재료, 기한, 이전 상태)
        self.release_ok = False
        self.release_acked = False      # 쉬는 자세로 옮기기 시작해 RESET ACK 를 먼저 보냄
        self.state_poll_sec = value['state_poll_sec']
        self.release_timeout_sec = value['release_timeout_sec']
        self.last_state_poll = 0.0
        topics = {
            'command': value['command_topic'] or f'/control_center/{self.iid}/command',
            'status': value['status_topic'] or f'/manipulation/{self.iid}/status',
            'ack': value['ack_topic'] or f'/manipulation/{self.iid}/command_ack',
            'info': value['info_topic'] or f'/manipulation/{self.iid}/info',
        }
        self.info_period_sec = value['info_period_sec']
        self.last_info, self.last_info_at = None, 0.0

        self.result_pub = self.create_publisher(String, value['result_topic'], 50)
        self.status_pub = self.create_publisher(ArmStatus, topics['status'], TELEMETRY_QOS)
        self.ack_pub = self.create_publisher(CommandAck, topics['ack'], EVENT_QOS)
        self.info_pub = self.create_publisher(String, topics['info'], INFO_QOS)
        self.create_subscription(String, value['request_topic'], self._on_request, 50)
        self.create_subscription(ArmCommand, topics['command'], self._on_command, COMMAND_QOS)
        self._detect()
        self.create_timer(value['detect_period_sec'], self._detect)
        self.create_timer(value['tick_sec'], self._tick)
        self.create_timer(value['status_period_sec'], self._publish_status)
        self.get_logger().info(
            f'{self.arm_id} 시작: backend={self.backend.name}, 전원 {self.power} '
            f'(auto_start={self.auto_start}), 요청 {value["request_topic"]} → 결과 '
            f'{value["result_topic"]}, 명령 {topics["command"]}, 상태 {topics["status"]}, '
            f'정보 {topics["info"]}')

    def _detect(self):
        state, port, reason = registry_utils.detect(
            self.arm_id, self.registry, registry_utils.list_by_id(self.by_id_dir),
            self.by_id_dir)
        if (state, port) == (self.state, self.port):
            return
        logger = self.get_logger()
        log = logger.info if state == registry_utils.READY else logger.warning
        log(f'{self.arm_id} 탐지 {state}: {reason}')
        lost = self.state == registry_utils.READY and state != registry_utils.READY
        self.state, self.port, self.reason = state, port, reason
        if state == registry_utils.READY:
            self.probe_due = True
        if state == registry_utils.READY and self.auto_start and self.power == power.DISARMED:
            self._connect('auto_start')
        if lost and self.backend.busy():
            # 작업 중 보드가 사라지면 팔 자세를 모른다. 멈추고 재시도 금지 실패로 끝낸다.
            self._publish_finished(self.backend.hold(time.time()), '작업 중 팔 연결 끊김')

    def _on_request(self, message):
        try:
            request = contract.decode(message.data)
        except ValueError as error:
            self.get_logger().warning(f'요청 무시: {error}')
            return
        now = time.time()
        verdict, reason, retry_safe = self.filter.check(request, now)
        if verdict == contract.IGNORE:
            if reason != '다른 장치 요청':
                self.get_logger().warning(f'요청 무시 ({request.get("request_id")}): {reason}')
            return
        if verdict == contract.REJECT:
            self._reject(request, reason, retry_safe)
            return
        action = request['action']
        if action == 'hold':
            self.held = True
            self.get_logger().warning(f'{self.arm_id} 정지 (hold, order={request.get("order_id")})')
            self._publish_finished(self.backend.hold(now), '')
            return
        if action == 'release_hold':
            self.held = False
            self.backend.release_hold(now)
            self.get_logger().info(f'{self.arm_id} 정지 해제 (release_hold)')
            return
        # 아래 거절은 모두 팔을 움직이기 전이라 다시 해도 안전하다.
        if self.power != power.ARMED:
            hint = {power.LATCHED: '잠금 해제(CMD_UNLATCH) 필요',
                    power.FAULT: 'CMD_RESET 필요'}.get(self.power, '관제 CMD_START 필요')
            self._reject(request, f'팔 전원 {self.power} ({hint})', True)
        elif self.state != registry_utils.READY:
            self._reject(request, f'팔 탐지 안 됨: {self.reason}', True)
        elif self.held:
            self._reject(request, '정지 유지 중 (release_hold 필요)', True)
        else:
            error = self.backend.start(request, self.port, now)
            if error:
                self._reject(request, error, True)
            else:
                self.retract = (False, False)  # 움직이기 시작했으니 지난 퇴피 측정은 무효
                self.get_logger().info(
                    f'{self.arm_id} 작업 시작: {request["stage"]}/{action} '
                    f'(order={request.get("order_id")}, request={request["request_id"]})')

    def _connect(self, why):
        self.backend.attach(self.port, time.time())
        self.power = power.CONNECTING
        self.retract = (False, False)  # 새 연결: 지난 퇴피 측정은 이 연결의 것이 아니다
        self.get_logger().warning(f'{self.arm_id} 팔 연결 시작 ({why}): 토크가 켜집니다')

    def _on_command(self, message):
        rx_mono, now = time.monotonic(), time.time()
        h = message.header
        header = {'command_id': h.command_id, 'robot_id': h.robot_id, 'epoch': h.epoch,
                  'seq': h.seq, 'ttl_ms': h.ttl_ms,
                  'issued_at': h.issued_at.sec + h.issued_at.nanosec * 1e-9}
        command = message.command
        name = power.COMMAND_NAMES.get(command, str(command))
        ack = (header, rx_mono, self.get_clock().now().to_msg())
        result, reason = self.gate.check(header, command, now)
        if command in power.STOP_COMMANDS:
            # 정지 계열은 판정이 거부여도 정지한다.
            self._stop(command == power.CMD_SOFT_LATCH, f'관제 {name}')
            if result == power.ACCEPTED:
                self.gate.accept(header, command)
            self._ack(ack, result, reason, True)
            return
        if result != power.ACCEPTED:
            self.get_logger().warning(f'{self.arm_id} {name} 거부: {reason}')
            self._ack(ack, result, reason, False)
            return
        ok, why, todo = power.decide(self.power, command, self.backend.busy(), self.backend.name)
        if ok and todo == 'connect' and self.state != registry_utils.READY:
            ok, why = False, f'팔 탐지 안 됨: {self.reason}'
        if not ok:
            self.get_logger().warning(f'{self.arm_id} {name} 거부: {why}')
            self._ack(ack, power.REJECTED_STATE, why, False)
            return
        self.gate.accept(header, command)
        if todo == 'connect':
            self._connect('관제 START')
        elif todo == 'release_hold':
            self.held = False
            self.backend.release_hold(now)
            self.get_logger().info(f'{self.arm_id} 정지 해제 (관제 RELEASE_HOLD)')
        elif todo == 'unlatch':
            # 사람이 현장을 보고 푸는 리셋이라 일반 정지(held)도 같이 푼다. 전체 비상정지는 fleet 이
            # 경로 팔에 hold 를 함께 보내므로, 남기면 잠금 해제 뒤에 정지 해제를 또 눌러야 한다.
            # 팔은 움직이지 않고 다음 작업 요청부터 받는다.
            self.power = power.ARMED
            self.held = False
            self.backend.release_hold(now)
            self.get_logger().warning(f'{self.arm_id} 잠금 해제 (관제 UNLATCH): 일을 받습니다')
        elif todo == 'clear' or (todo == 'release' and not self.backend.running()):
            self._disarm('관제 RESET')
        elif todo == 'release':
            # 결과는 실행기가 쉬는 자세를 본 뒤에 안다. ACK 는 그때 보낸다.
            self.backend.release(now)
            self.pending_reset = (ack, time.monotonic() + self.release_timeout_sec, self.power)
            self.release_ok = False
            self.release_acked = False
            self.power = power.RELEASING
            self.get_logger().info(f'{self.arm_id} 끄기 요청 (관제 RESET): 쉬는 자세 확인 중')
            return
        self._ack(ack, power.ACCEPTED, '', False)

    def _disarm(self, why):
        """실행기를 정리하고 꺼짐(DISARMED). 지난 HOLD 도 함께 지운다 (power.keep_hold)."""
        self.backend.reset()
        self.power = power.DISARMED
        self.probe_due = True
        held = power.keep_hold(self.power, self.held)
        cleared, self.held = self.held and not held, held
        note = ', 정지(HOLD) 해제' if cleared else ''
        self.get_logger().info(f'{self.arm_id} 꺼짐 (DISARMED): {why}{note}')

    def _stop(self, latch, why):
        self.held = self.held or not latch
        if latch and self.power != power.FAULT:
            self.power = power.LATCHED
        self.get_logger().warning(f'{self.arm_id} 정지 ({why})')
        self._publish_finished(self.backend.hold(time.time()), why)

    def _ack(self, ack, result, reason, stop_executed):
        header, rx_mono, rx_stamp = ack
        self.ack_pub.publish(CommandAck(
            command_id=header['command_id'], robot_id=self.iid, epoch=header['epoch'],
            seq=header['seq'], result=result, stop_executed=stop_executed, reason=reason,
            rx_to_ack_ms=int((time.monotonic() - rx_mono) * 1000), robot_rx_stamp=rx_stamp))

    def _tick(self):
        now = time.time()
        finished = self.backend.poll(now)
        for _, _, data, _ in finished:
            # 실행기가 안전 자세로 옮겨 잰 결과만 '측정' 이다 (hold·가짜 결과는 미측정)
            self.retract = (data.get('arm_safe') is True, bool(data.get('pose_error')))
        self._publish_finished(finished, '')
        if self.power == power.CONNECTING and self.backend.ready:
            self.power = power.ARMED
            self.get_logger().info(f'{self.arm_id} 켜짐 (ARMED): 일을 받습니다')
        if self.power == power.RELEASING:
            self._tick_release()
        elif (self.power in (power.CONNECTING, power.ARMED, power.LATCHED)
              and self.backend.dead):
            self.power = power.FAULT
            self.get_logger().error(
                f'{self.arm_id} 고장 (FAULT): {self.backend.dead}. 팔 상태 확인 뒤 RESET')
        if (self.power == power.ARMED and not self.backend.busy()
                and now - self.last_state_poll >= self.state_poll_sec):
            self.last_state_poll = now
            self.backend.request_state(now)
        self._probe_torque(now)
        self._publish_info(now)

    def _probe_torque(self, now):
        """꺼짐(DISARMED) 이고 실행기가 끝났을 때 모터 토크를 한 번 잰다. 실행기가 포트를 쓰면 기다린다."""
        if (not self.probe_due or self.state != registry_utils.READY
                or self.power != power.DISARMED or self.backend.running()):
            return
        self.probe_due = False
        self.backend.probe_torque(self.port, now)

    def _publish_info(self, now):
        """백엔드·탐지·실행기 정보. 바뀌면 바로, 아니면 info_period_sec 마다 낸다."""
        info = info_utils.make_info(
            self.arm_id, self.iid, self.boot_id, self.backend.name, self.backend.ready,
            self.backend.worker_info, (self.state, self.reason, self.port), self.power,
            self.backend.dead, now, self.backend.torque)
        if (not info_utils.info_changed(self.last_info, info)
                and now - self.last_info_at < self.info_period_sec):
            return
        self.last_info, self.last_info_at = info, now
        self.info_pub.publish(String(data=info_utils.encode(info)))

    def _tick_release(self):
        ack, deadline, before = self.pending_reset
        moving = self.backend.take_release_moving()
        if moving is not None and not self.release_acked:
            # 실행기가 쉬는 자세로 옮기기 시작했다 (fleet_arms.yaml release_move). 이동이 관제의
            # ACK 대기(8 s)보다 길 수 있어 RESET 은 지금 받아들였다고 답하고, 끝은 ArmStatus 로 보인다.
            deadline = time.monotonic() + moving + self.release_timeout_sec
            self.pending_reset = (ack, deadline, before)
            self.release_acked = True
            why = f'쉬는 자세로 이동 중 (약 {moving:.0f}s), 도착하면 토크 끔'
            self.get_logger().warning(f'{self.arm_id} {why}')
            self._ack(ack, power.ACCEPTED, why, False)
        result = self.backend.take_release()
        if result is not None and not result[0]:
            self.power, self.pending_reset = before, None
            self.get_logger().warning(f'{self.arm_id} 끄기 거절: {result[1]}')
            self._ack_release(ack, power.REJECTED_STATE, result[1])
            return
        if result is not None:
            self.release_ok = True
        if self.release_ok and not self.backend.running():
            self.pending_reset = None
            self._disarm('실행기가 연결을 끊어 토크를 껐습니다')
            self._ack_release(ack, power.ACCEPTED, '')
        elif self.backend.dead:
            self.power, self.pending_reset = power.FAULT, None
            self._ack_release(ack, power.REJECTED_STATE, f'끄는 중 고장: {self.backend.dead}')
        elif time.monotonic() > deadline:
            self.power, self.pending_reset = before, None
            self._ack_release(ack, power.REJECTED_STATE, '실행기가 끄기에 답하지 않음')

    def _ack_release(self, ack, result, reason):
        """RESET 의 최종 ACK. 이동을 시작할 때 이미 답했으면 다시 보내지 않고 로그만 남긴다."""
        if not self.release_acked:
            self._ack(ack, result, reason, False)
        elif result != power.ACCEPTED:
            self.get_logger().error(f'{self.arm_id} 이동 뒤 끄지 못함 (토크 상태는 ArmStatus): {reason}')
        self.release_acked = False

    def _publish_status(self):
        joints = self.backend.joints or {}
        body = {k: v for k, v in joints.items() if k != GRIPPER_KEY}
        idle = self.power == power.ARMED and not self.backend.busy()
        # header.stamp 은 측정 시각이다. 작업 중에는 관절을 읽지 못해 마지막 값과 그 시각을 낸다.
        stamp = self.backend.joints_at if joints else time.time()
        hold_active, hold_reason = power.hold_status(self.power, self.held)
        status = ArmStatus(
            arm_id=self.iid, robot_boot_id=self.boot_id,
            joint_unit='',  # lerobot -100..100 단위는 명세 열거(RAD, 0..4095)에 없다: '모름'
            joint_names=[k.removesuffix('.pos') for k in body],
            joint_positions=[float(v) for v in body.values()],
            gripper_position=float(joints.get(GRIPPER_KEY, math.nan)),
            # 실행기 상태로 정한 값이다. 관제는 이 값으로 켜짐·꺼짐 화면 상태를 정하므로 실측을 섞지 않는다.
            # 실행기가 없을 때 모터에서 잰 값은 info 토픽 torque 칸으로 따로 낸다.
            torque_enabled=self.backend.running() and self.power in power.WORKER_STATES,
            retract_safe=self.retract[0], retract_safe_measured=self.retract[1],
            hold_active=hold_active, hold_reason=hold_reason,
            power_present=False,  # 측정 수단 없음 (D6)
            epoch_accepted=self.gate.epoch_accepted, last_seq_accepted=self.gate.last_seq,
            work_step=ArmStatus.WORK_STEP_IDLE if idle else '')
        status.header.stamp = to_time(stamp)
        self.status_pub.publish(status)

    def _reject(self, request, detail, retry_safe):
        self.get_logger().warning(f'{self.arm_id} 요청 거절 ({request.get("stage")}): {detail}')
        self._publish(contract.reject_result(request, self.arm_id, detail, retry_safe))

    def _publish_finished(self, finished, default_detail):
        for request, success, data, detail in finished:
            self._publish(contract.make_result(
                request, self.arm_id, success, data, detail or default_detail))

    def _publish(self, result):
        self.result_pub.publish(String(data=contract.encode(result)))
        self.get_logger().info(
            f'{self.arm_id} 결과: {result["stage"]} success={result["success"]} '
            f'request={result["request_id"]}')


def main(args=None):
    rclpy.init(args=args)
    try:
        node = ArmAdapterNode()
    except AdapterConfigError as error:
        get_logger('arm_adapter').fatal(f'시작 거부: {error}')
        rclpy.try_shutdown()
        sys.exit(1)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # Ctrl+C 면 rclpy 가 먼저 꺼져 노드 로거로는 rosout 에 못 쓴다. 실행기 마지막 로그는 노드 밖 로거로.
        if hasattr(node.backend, 'log'):
            node.backend.log = get_logger('arm_adapter_shutdown').info
        node.backend.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
