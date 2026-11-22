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
/control_center/<arm>/command (ArmCommand) 로 낸다. 받는 쪽은 그 팔이 꽂힌 PC 의 팔 노드
(cobot_manipulation arm_adapter_node) 이고, 판정 결과는 CommandAck, 상태는 ArmStatus 로 온다.

  /control_center/arm_request (String JSON) ← fleet_api_node
  /control_center/arm_events  (String JSON) → fleet_api_node  (요청 응답, 알람 기록 {type: event})
  /control_center/arms        (String JSON, transient_local) → fleet_api_node  (팔 상태 모음)

  /fleet/work_request (String JSON) → 팔 노드  (작업 시험 한 건, 실제 팔이 움직인다)
  /fleet/work_request (String JSON) ← fleet_control  (주문 작업, 듣기만 해서 카드 작업 칸·기록에 표시)
  /fleet/work_result  (String JSON) ← 팔 노드  (작업 시험·주문 작업 결과를 request_id 로 짝지어 기록)

START 는 실제 팔에 연결해 토크를 켠다. 팔 모션은 ArmCommand 로 시작하지 않는다 (ArmCommand.msg).
작업 시험은 개발 대시보드용이다. 주행 관제(fleet_control_node)도 같은 작업 토픽을 쓰므로
주문 진행 중에는 쓰지 않는다.
"""

import json
import time

from builtin_interfaces.msg import Time
from cobot_control_center import arm_command_utils as arms
from cobot_control_center.site_arms_utils import load_site_arms
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
# 작업 요청·결과: fleet_control_node 의 work_pub(depth 50, 기본 RELIABLE·VOLATILE)과 같게
WORK_QOS = 50
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
            'info_topic_format': '/manipulation/{arm}/info',
            'request_topic': '/control_center/arm_request',
            'events_topic': '/control_center/arm_events',
            'arms_topic': '/control_center/arms',
            'ttl_ms': 5000,
            'ack_timeout_sec': 8.0,
            'status_stale_sec': 1.0,
            'snapshot_period_sec': 0.2,
            'site_arms_file': '',
            'work_request_topic': '/fleet/work_request',
            'work_result_topic': '/fleet/work_result',
            'work_stage': 'MANUAL_TEST',
            'work_timeout_sec': 300.0,
            'work_result_margin_sec': 15.0,
        }
        for name, default in params.items():
            self.declare_parameter(name, default)
        value = {name: self.get_parameter(name).value for name in params}

        site = self._load_site(value['site_arms_file'])
        self.commander = arms.ArmCommander(
            list(site) if site else [a for a in value['arm_ids'] if a],
            value['ttl_ms'], value['ack_timeout_sec'],
            value['status_stale_sec'], value['work_timeout_sec'],
            value['work_result_margin_sec'], value['work_stage'], site=site)
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
            # 팔 노드 설정·실행기 정보 (String JSON, transient_local: 늦게 켜져도 마지막 값을 받는다)
            self.create_subscription(
                String, value['info_topic_format'].format(arm=arm_id),
                lambda msg, arm_id=arm_id: self._on_info(arm_id, msg), SNAPSHOT_QOS)
        self.work_pub = self.create_publisher(String, value['work_request_topic'], WORK_QOS)
        self.create_subscription(String, value['work_result_topic'], self._on_work_result,
                                 WORK_QOS)
        # 주문(fleet_control)이 보내는 작업 요청을 듣기만 한다. 내가 낸 작업 시험도 여기로 다시 오는데,
        # request_id 로 걸러 두 번 세지 않는다.
        self.create_subscription(String, value['work_request_topic'], self._on_other_work_request,
                                 WORK_QOS)
        self.events_pub = self.create_publisher(String, value['events_topic'], BACKEND_QOS)
        self.arms_pub = self.create_publisher(String, value['arms_topic'], SNAPSHOT_QOS)
        self.create_subscription(String, value['request_topic'], self._on_request, BACKEND_QOS)
        self.create_timer(value['snapshot_period_sec'], self._tick)
        self.get_logger().info(
            f'arm_command_node 시작: 로봇팔 {", ".join(self.commander.arm_ids) or "없음"}, '
            f'명령 {value["command_topic_format"]}, ttl {value["ttl_ms"]} ms, '
            f'응답 기한 {value["ack_timeout_sec"]} s, 작업 시험 {value["work_request_topic"]} '
            f'(stage {value["work_stage"]}, session {self.commander.session_id[:8]})')

    def _load_site(self, path):
        """현장 팔 배치 파일. 없거나 틀리면 오류를 남기고 arm_ids 로 계속한다 (관제가 멈추지 않게)."""
        if not path:
            return {}
        try:
            site = load_site_arms(path)
        except ValueError as error:
            self.get_logger().error(f'현장 팔 배치 파일을 못 읽음 ({path}): {error}. arm_ids 를 씀')
            return {}
        self.get_logger().info('현장 팔 배치: ' + ', '.join(
            f'{arm_id}={info["station"] or "?"}/{info["host"] or "PC 미정"}'
            for arm_id, info in site.items()))
        return site

    def _on_status(self, arm_id, msg):
        self.commander.put_status(arm_id, status_to_dict(msg), time.monotonic(), time.time())

    def _on_info(self, arm_id, msg):
        try:
            info = json.loads(msg.data)
        except ValueError as error:
            self.get_logger().warning(f'{arm_id} info 무시 (JSON 아님): {error}')
            return
        self.commander.put_info(arm_id, info, time.monotonic(), time.time())

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
        self._log(out['status'] == 200, text)
        self._send_event(out)

    def _on_request(self, msg):
        try:
            request = arms.parse_request(msg.data)
        except ValueError as error:
            self.get_logger().warning(f'로봇팔 요청 무시: {error}')
            return
        if request.get('type') == 'work':
            self._on_work_request(request)
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
        self._log(name != arms.START, text if name != arms.START
                  else f'{text}: 실제 팔이면 토크가 켜집니다')
        self.command_pubs[header['robot_id']].publish(message)

    def _on_work_request(self, request):
        try:
            payload = self.commander.make_work(request, time.time(), time.monotonic())
        except arms.CommandError as error:
            self._send_event(arms.reply(request['request_id'], error.status,
                                        {'detail': error.detail}))
            return
        arm_id = arms.interface_arm_id(payload['target'])
        self.get_logger().warning(
            f'{arm_id} 작업 시험 {payload["action"]} 발행 (request {payload["request_id"]}, '
            f'seq {payload["seq"]}, 요청자 {request.get("source") or "?"}): 실제 팔이 움직입니다')
        self.work_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        # 작업은 수십 초 걸린다. 웹에는 '보냈다' 까지만 답하고 결과는 스냅샷(arm.work)으로 보인다.
        self._send_event(arms.reply(request['request_id'], 202, {
            'arm_id': arm_id, 'action': payload['action'], 'work_id': payload['request_id'],
            'client_request_id': request.get('client_request_id')}))

    def _on_other_work_request(self, msg):
        try:
            request = json.loads(msg.data)
        except (TypeError, ValueError):
            return
        arm_id = self.commander.put_other_request(request, time.time(), time.monotonic())
        if arm_id is not None:
            self.get_logger().info(
                f'{arm_id} 주문 작업 요청: {request.get("stage")} {request.get("action")} '
                f'(order {request.get("order_id") or "-"}, '
                f'robot {request.get("robot_id") or "-"}, '
                f'request {request.get("request_id")})')

    def _on_work_result(self, msg):
        try:
            result = json.loads(msg.data)
        except (TypeError, ValueError):
            return
        record = self.commander.put_work_result(result, time.time())
        if record is None:
            return   # 짝지을 작업이 없는 결과(노드를 켜기 전 요청)이거나 이미 받은 결과
        text = (f'{record["arm_id"]} {arms.work_label(record)} → {record["state"]} '
                f'({record["duration"]} s) {record["detail"]}')
        self._log(record['state'] == arms.WORK_SUCCEEDED, text)

    def _tick(self):
        self.commander.check_links(time.monotonic(), time.time())
        for out in self.commander.expire(time.monotonic(), time.time()):
            self.get_logger().warning(out['body']['detail'])
            self._send_event(out)
        for record in self.commander.expire_works(time.monotonic(), time.time()):
            self.get_logger().warning(
                f'{record["arm_id"]} {arms.work_label(record)}: {record["detail"]}')
        # 알람 기록은 스냅샷(depth 1)이 아니라 응답 토픽(RELIABLE depth 50)으로 보내 빠지지 않게 한다.
        for event in self.commander.take_events():
            self._send_event({'type': 'event', 'event': event})
        snapshot = self.commander.snapshot(time.monotonic(), time.time())
        self.arms_pub.publish(String(data=json.dumps(snapshot, ensure_ascii=False,
                                                     allow_nan=False)))

    def _log(self, ok, text):
        """
        성공(ok)이면 info, 아니면 warning 으로 남긴다.

        rclpy 는 한 호출 자리에서 심각도가 바뀌면 ValueError 를 낸다. 그래서 두 자리를 따로 둔다.
        """
        if ok:
            self.get_logger().info(text)
        else:
            self.get_logger().warning(text)

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
