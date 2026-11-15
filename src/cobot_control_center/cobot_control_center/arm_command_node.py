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
로봇팔 명령 노드: 웹 요청을 ArmCommand 로 바꿔 팔 노드에 내고, 응답·상태를 웹 백엔드에 돌려준다.

fleet_api_node 는 로봇 토픽에 발행하지 않는다. 팔 켜기·끄기·정지는 이 노드가 받아
/control_center/<arm>/command (ArmCommand) 로 낸다. 받는 쪽은 Station PC 의 팔 노드
(cobot_manipulation arm_adapter_node) 이고, 판정 결과는 CommandAck, 상태는 ArmStatus 로 온다.

  /control_center/arm_request (String JSON) ← fleet_api_node
  /control_center/arm_events  (String JSON) → fleet_api_node  (요청 응답)
  /control_center/arms        (String JSON, transient_local) → fleet_api_node  (팔 상태 모음)

START 는 실제 팔에 연결해 토크를 켠다. 관제는 팔 모션을 시작하지 않는다 (ArmCommand.msg).
"""

import json
import time

from builtin_interfaces.msg import Time
from cobot_control_center import arm_command_utils as arms
from cobot_interfaces.msg import ArmCommand, ArmStatus, CommandAck, CommandHeader
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

# 팔 노드(arm_adapter_node)와 같은 QoS: 명령·이벤트 RELIABLE, 텔레메트리 BEST_EFFORT KEEP_LAST 1
COMMAND_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
EVENT_QOS = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.VOLATILE)
TELEMETRY_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                           durability=DurabilityPolicy.VOLATILE)
# 웹 백엔드와의 요청·응답 (fleet_api_node 의 task_request 와 같은 QoS)
BACKEND_QOS = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
SNAPSHOT_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                          durability=DurabilityPolicy.TRANSIENT_LOCAL)


def to_time(seconds):
    """[s] float → builtin_interfaces/Time."""
    sec = int(seconds)
    return Time(sec=sec, nanosec=int((seconds - sec) * 1e9))


def stamp_seconds(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


def status_to_dict(msg):
    """팔 상태 메시지(ArmStatus) → JSON 으로 낼 dict (NaN 은 None)."""
    return {
        'stamp': stamp_seconds(msg.header.stamp), 'robot_boot_id': msg.robot_boot_id,
        'joint_unit': msg.joint_unit, 'joint_names': list(msg.joint_names),
        'joint_positions': [arms.clean_float(v) for v in msg.joint_positions],
        'gripper_position': arms.clean_float(msg.gripper_position),
        'present_current_ma': [arms.clean_float(v) for v in msg.present_current_ma],
        'torque_enabled': msg.torque_enabled, 'retract_safe': msg.retract_safe,
        'retract_safe_measured': msg.retract_safe_measured,
        'hold_active': msg.hold_active, 'hold_reason': msg.hold_reason,
        'power_present': msg.power_present, 'epoch_accepted': msg.epoch_accepted,
        'last_seq_accepted': msg.last_seq_accepted, 'work_step': msg.work_step}


def ack_to_dict(msg):
    return {'command_id': msg.command_id, 'robot_id': msg.robot_id, 'epoch': msg.epoch,
            'seq': msg.seq, 'result': msg.result, 'stop_executed': msg.stop_executed,
            'reason': msg.reason, 'rx_to_ack_ms': msg.rx_to_ack_ms}


class ArmCommandNode(Node):
    """팔 여러 대: 웹 요청 → ArmCommand, CommandAck → 웹 응답, ArmStatus → 상태 모음."""

    def __init__(self):
        super().__init__('arm_command_node')
        params = {
            'arm_ids': ['omx_1', 'omx_2', 'omx_3'],
            'command_topic_format': '/control_center/{arm}/command',
            'status_topic_format': '/manipulation/{arm}/status',
            'ack_topic_format': '/manipulation/{arm}/command_ack',
            'request_topic': '/control_center/arm_request',
            'events_topic': '/control_center/arm_events',
            'arms_topic': '/control_center/arms',
            'ttl_ms': 5000,
            'ack_timeout_sec': 8.0,
            'status_stale_sec': 1.0,
            'snapshot_period_sec': 0.2,
        }
        for name, default in params.items():
            self.declare_parameter(name, default)
        value = {name: self.get_parameter(name).value for name in params}

        self.commander = arms.ArmCommander(
            [a for a in value['arm_ids'] if a], value['ttl_ms'], value['ack_timeout_sec'],
            value['status_stale_sec'])
        self.command_pubs = {}
        for arm_id in self.commander.arm_ids:
            self.command_pubs[arm_id] = self.create_publisher(
                ArmCommand, value['command_topic_format'].format(arm=arm_id), COMMAND_QOS)
            self.create_subscription(
                ArmStatus, value['status_topic_format'].format(arm=arm_id),
                lambda msg, arm_id=arm_id: self._on_status(arm_id, msg), TELEMETRY_QOS)
            self.create_subscription(
                CommandAck, value['ack_topic_format'].format(arm=arm_id), self._on_ack,
                EVENT_QOS)
        self.events_pub = self.create_publisher(String, value['events_topic'], BACKEND_QOS)
        self.arms_pub = self.create_publisher(String, value['arms_topic'], SNAPSHOT_QOS)
        self.create_subscription(String, value['request_topic'], self._on_request, BACKEND_QOS)
        self.create_timer(value['snapshot_period_sec'], self._tick)
        self.get_logger().info(
            f'arm_command_node 시작: 로봇팔 {", ".join(self.commander.arm_ids) or "없음"}, '
            f'명령 {value["command_topic_format"]}, ttl {value["ttl_ms"]} ms, '
            f'응답 기한 {value["ack_timeout_sec"]} s')

    def _on_status(self, arm_id, msg):
        self.commander.put_status(arm_id, status_to_dict(msg), time.monotonic())

    def _on_ack(self, msg):
        ack = ack_to_dict(msg)
        out = self.commander.put_ack(ack, time.time())
        result = arms.ACK_RESULTS.get(ack['result'], str(ack['result']))
        if out is None:
            self.get_logger().info(
                f'{ack["robot_id"]} 응답 (이 노드가 낸 명령 아님): {result} {ack["reason"]}')
            return
        text = (f'{ack["robot_id"]} {out["body"]["command"]} → {result} '
                f'{ack["reason"]} (stop_executed={ack["stop_executed"]})')
        # rclpy 는 한 호출 자리에서 심각도가 바뀌면 ValueError 를 낸다. 그래서 자리를 나눈다.
        if out['status'] == 200:
            self.get_logger().info(text)
        else:
            self.get_logger().warning(text)
        self._send_event(out)

    def _on_request(self, msg):
        try:
            request = arms.parse_request(msg.data)
        except ValueError as error:
            self.get_logger().warning(f'로봇팔 요청 무시: {error}')
            return
        if request.get('type') != 'command':
            self._send_event(arms.reply(request['request_id'], 400, {
                'detail': f'모르는 요청 종류: {request.get("type")}'}))
            return
        try:
            header, command = self.commander.make_command(
                request, time.time(), time.monotonic())
        except arms.CommandError as error:
            self._send_event(arms.reply(request['request_id'], error.status,
                                        {'detail': error.detail}))
            return
        message = ArmCommand(command=command, header=CommandHeader(
            command_id=header['command_id'], tx_id=header['tx_id'],
            robot_id=header['robot_id'], epoch=header['epoch'], seq=header['seq'],
            issued_at=to_time(header['issued_at']), ttl_ms=header['ttl_ms'],
            issued_by=header['issued_by']))
        name = request['command'].lower()
        text = (f'{header["robot_id"]} {name} 발행 (epoch {header["epoch"]}, '
                f'seq {header["seq"]}, 요청자 {request.get("source") or "?"})')
        if name == arms.START:
            self.get_logger().warning(f'{text}: 실제 팔이면 토크가 켜집니다')
        else:
            self.get_logger().info(text)
        self.command_pubs[header['robot_id']].publish(message)

    def _tick(self):
        for out in self.commander.expire(time.monotonic()):
            self.get_logger().warning(out['body']['detail'])
            self._send_event(out)
        snapshot = self.commander.snapshot(time.monotonic(), time.time())
        self.arms_pub.publish(String(data=json.dumps(snapshot, ensure_ascii=False,
                                                     allow_nan=False)))

    def _send_event(self, event):
        self.events_pub.publish(String(data=json.dumps(event, ensure_ascii=False)))


def main(args=None):
    rclpy.init(args=args)
    node = ArmCommandNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
