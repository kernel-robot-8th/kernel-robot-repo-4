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
가짜 핑키 노드: 핑키 여러 대를 흉내 내 관제 PC 쪽 토픽 이름 그대로 발행한다.

관제 PC 에서 브릿지를 지난 뒤의 이름(/pinkyN/..., /zone_manager/status)을 쓰므로 관제 코드는
진짜와 구분하지 못한다. 그래서 실물 도메인(0·10·12·20·30·100)에서는 시작을 거부한다.
장치·Nav2·cmd_vel 은 쓰지 않는다. 로직은 mock_pinky_sim 에 있고 여기서는 발행·구독만 한다.
"""

import contextlib
import json
import math
import os
import random
import sys
import time
import uuid

from cobot_mock.mock_pinky_sim import (ack_for, central_command, CentralGuard, check_domain,
                                       choose_auto_command, load_robot_configs,
                                       load_zone_params, MockConfigError, RobotSim, v2_to_v1,
                                       ZoneBook)
from cobot_patrol_interfaces.msg import PatrolCommand, PatrolCommandAck, PatrolState
from geometry_msgs.msg import PoseWithCovarianceStamped
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, String

TICK_SEC = 0.1
POSE_PERIOD_SEC = 0.2
BATTERY_PERIOD_SEC = 1.0
ZONE_PERIOD_SEC = 1.0
STATE_PERIOD_SEC = 1.0
STATUS_PERIOD_SEC = 1.0   # v1 상태 주기 발행 (실제 순찰 노드 status_period_sec 와 같은 역할)


def battery_voltage(percent):
    """2S 리튬 배터리 근사: 0 % = 6.0 V, 100 % = 8.4 V."""
    return 6.0 + 2.4 * percent / 100.0


class MockPinkyNode(Node):
    """RobotSim 여러 대를 0.1초마다 진행시키고 이벤트를 토픽으로 낸다."""

    def __init__(self):
        super().__init__('mock_pinky_node')
        p = {
            'robots': ['pinky1', 'pinky2', 'pinky3'],
            'points_dir': '', 'site': 'lab', 'zone_params': '',
            'speed_mps': 0.15, 'idle_return_sec': 40.0,
            'auto_patrol': True, 'auto_interval_sec': 8.0, 'auto_pause_after_cmd_sec': 60.0,
            'drain_moving_per_min': 1.0, 'drain_idle_per_min': 0.2, 'charge_per_min': 5.0,
            'dropout_robot': 'pinky3', 'dropout_period_sec': 60.0, 'dropout_sec': 12.0,
            'seed': 0, 'spec_versions': ['v1'],
            # 중앙 관제(fleet_control) 규칙: 하트비트·세션·순번을 통과한 명령만 받는다 (시계 비교·TTL 없음).
            'central_controlled': True, 'heartbeat_timeout_sec': 3.0,
        }
        for name, value in p.items():
            self.declare_parameter(name, value)
        cfg = {name: self.get_parameter(name).value for name in p}
        robots = list(cfg['robots'])
        self.cfg = cfg
        self.central = bool(cfg['central_controlled'])
        if self.central and cfg['auto_patrol']:
            # 중앙 모드에서는 fleet 만 명령한다. 로봇이 스스로 움직이면 배정과 어긋난다.
            self.get_logger().warning('central_controlled 라 auto_patrol 을 끈다')
            cfg['auto_patrol'] = False
        self.boot_id = uuid.uuid4().hex
        # rclpy Node 에 guards 속성이 있어 이름을 central_guards 로 둔다
        self.central_guards = {
            name: CentralGuard(cfg['heartbeat_timeout_sec'])
            for name in robots}

        configs = load_robot_configs(cfg['points_dir'], robots, cfg['site'])
        self.book = ZoneBook(load_zone_params(cfg['zone_params']))
        self.sims = {}
        for i, name in enumerate(robots):
            self.sims[name] = RobotSim(
                name, configs[name], self.book, cfg['speed_mps'], cfg['idle_return_sec'],
                battery=100.0 - 12.0 * i, drain_moving=cfg['drain_moving_per_min'],
                drain_idle=cfg['drain_idle_per_min'], charge_per_min=cfg['charge_per_min'])
        self.rng = random.Random(cfg['seed'])
        self.manual_until = {name: 0.0 for name in robots}
        self.next_auto = {name: None for name in robots}

        # zone_manager·순찰 노드와 같은 설정이어야 관제 구독과 맞는다.
        reliable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                              history=HistoryPolicy.KEEP_LAST)
        self.v1 = 'v1' in cfg['spec_versions']
        self.v2 = 'v2' in cfg['spec_versions']
        self.pub = {}
        for name in robots:
            self.pub[name] = {
                'pose': self.create_publisher(
                    PoseWithCovarianceStamped, f'/{name}/amcl_pose', 10),
                'percent': self.create_publisher(Float32, f'/{name}/battery/percent', 10),
                'voltage': self.create_publisher(Float32, f'/{name}/battery/voltage', 10),
            }
            # 규격 v1: String 명령·JSON 상태 (지금 주행 코드)
            if self.v1:
                self.pub[name]['status'] = self.create_publisher(
                    String, f'/{name}/patrol_status', 10)
                self.create_subscription(String, f'/{name}/patrol_cmd',
                                         lambda msg, r=name: self._on_cmd(r, msg), 10)
            if self.central:
                self.create_subscription(String, f'/{name}/fleet_heartbeat',
                                         lambda msg, r=name: self._on_heartbeat(r, msg), 10)
            # 규격 v2: 작업 ID 메시지 (cobot_patrol_interfaces). v1 과 다른 이름이라 겹치지 않는다
            if self.v2:
                self.pub[name]['state'] = self.create_publisher(
                    PatrolState, f'/{name}/patrol_state', reliable)
                self.pub[name]['ack'] = self.create_publisher(
                    PatrolCommandAck, f'/{name}/patrol_command_ack', reliable)
                self.create_subscription(PatrolCommand, f'/{name}/patrol_command',
                                         lambda msg, r=name: self._on_command_v2(r, msg),
                                         reliable)
        self.zone_pub = self.create_publisher(String, '/zone_manager/status', reliable)
        self.slot_pub = self.create_publisher(String, '/zone_manager/queue_slot', reliable)

        self.start = time.monotonic()
        self.last = self.start
        self.next_pose = self.next_battery = self.next_zone = self.next_state = self.start
        self.next_status = self.start
        self.zone_lines = None
        self.create_timer(TICK_SEC, self._tick)

        for name, sim in self.sims.items():
            self._emit(name, [{'state': 'IDLE', 'waypoint': -1, 'detail': ''}])
            self.get_logger().info(f'{name}: 홈 {sim.home} {sim.pose[:2]}')
        self.get_logger().info(
            f'가짜 핑키 시작 (robots={robots}, central={self.central}, '
            f'auto_patrol={cfg["auto_patrol"]}, dropout={cfg["dropout_robot"] or "없음"})')

    # ---------- 입력 ----------

    def _on_cmd(self, robot, msg):
        now = time.monotonic()
        self.manual_until[robot] = now + self.cfg['auto_pause_after_cmd_sec']
        raw = msg.data
        if self.central:
            raw, result = central_command(self.central_guards[robot], msg.data)
            if result == 'reset':
                self.get_logger().info(f'{robot}: 정지 잠금 해제 (control_reset)')
                self._emit(robot, [{'state': 'IDLE', 'waypoint': -1, 'detail': 'control reset'}])
                return
            if raw is None:
                self.get_logger().warning(
                    f'{robot}: 명령 거절 (하트비트·세션·순번·비상정지 잠금): {msg.data!r}')
                return
        events = self.sims[robot].command(raw, now)
        self.get_logger().info(f'{robot}: 명령 {msg.data!r} -> {len(events)}개 이벤트')
        self._emit(robot, events)

    def _on_heartbeat(self, robot, msg):
        """서버 세션이 바뀌면 움직이던 로봇만 비상정지한다. 놀던 로봇은 잠그지 않는다."""
        try:
            changed = self.central_guards[robot].heartbeat(
                json.loads(msg.data), self.sims[robot].running)
        except (ValueError, TypeError):
            self.get_logger().warning(f'{robot}: 잘못된 중앙 하트비트')
            return
        if changed:
            self.get_logger().warning(f'{robot}: 관제 세션 바뀜 -> 비상정지·잠금')
            self._emit(robot, self.sims[robot].command('emergency_stop', time.monotonic()))

    def _on_command_v2(self, robot, msg):
        """v2 명령은 v1 명령으로 바꿔 같은 로봇을 움직이고, 받음/거절을 ack 로 알린다."""
        now = time.monotonic()
        self.manual_until[robot] = now + self.cfg['auto_pause_after_cmd_sec']
        raw, reason = v2_to_v1(msg.task_id, msg.operation, list(msg.points))
        events = []
        if raw is None:
            accepted = False
        else:
            events = self.sims[robot].command(raw, now)
            accepted, reason = ack_for(msg.operation, events)
        self.get_logger().info(f'{robot}: v2 명령 {msg.task_id} {msg.operation} '
                               f'{list(msg.points)} -> {"받음" if accepted else reason}')
        if not self._silent(robot, now):
            ack = PatrolCommandAck(robot_id=robot, task_id=msg.task_id,
                                   accepted=accepted, reason=reason)
            ack.header.stamp = self.get_clock().now().to_msg()
            self.pub[robot]['ack'].publish(ack)
        # 거절은 v1 처럼 FAILED 상태를 내지 않는다 (ack 가 그 역할). 받은 명령의 상태만 낸다.
        self._emit(robot, events if accepted else [])

    # ---------- 진행 ----------

    def _tick(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        self.book.tick(now)
        for name, sim in self.sims.items():
            if self.central and self.central_guards[name].expired(sim.running):
                self.get_logger().warning(f'{name}: 관제 하트비트 끊김 -> 비상정지·잠금')
                self._emit(name, sim.command('emergency_stop', now))
            if self.cfg['auto_patrol'] and not sim.running and now >= self.manual_until[name]:
                if self.next_auto[name] is None:
                    # 로봇마다 쉬는 시간을 0.5~1.5배로 흩어 3대가 같은 박자로 움직이지 않게 한다
                    self.next_auto[name] = now + self.cfg['auto_interval_sec'] * (
                        0.5 + self.rng.random())
                elif now >= self.next_auto[name]:
                    # 유휴 복귀를 기다리지 않고 다음 일을 준다 (시연에 활동이 계속 보이게).
                    # 명령을 받은 로봇은 auto_pause_after_cmd_sec 동안 자동 명령을 쉰다.
                    self.next_auto[name] = None
                    sim.idle_deadline = None
                    self._emit(name, sim.command(choose_auto_command(sim, self.rng), now))
            self._emit(name, sim.step(now, dt))
        self._publish_periodic(now)

    def _silent(self, robot, now):
        """끊김 흉내 대상 로봇이 지금 끊긴 구간이면 True (화면의 '끊김' 시험용)."""
        if robot != self.cfg['dropout_robot'] or self.cfg['dropout_period_sec'] <= 0:
            return False
        return (now - self.start) % self.cfg['dropout_period_sec'] >= (
            self.cfg['dropout_period_sec'] - self.cfg['dropout_sec'])

    # ---------- 출력 ----------

    def _emit(self, robot, events):
        for ev in events:
            if self._silent(robot, time.monotonic()):
                continue        # 끊긴 동안의 상태는 실제 네트워크처럼 잃는다
            if self.v1:
                self._publish_status(robot, self.sims[robot].status(ev))
            if self.v2:
                self._publish_state(robot, ev)

    def _publish_status(self, robot, payload):
        payload = dict(payload, time=time.time(), central_controlled=self.central,
                       central_latched=self.central_guards[robot].latched, boot_id=self.boot_id)
        self.pub[robot]['status'].publish(String(data=json.dumps(payload)))

    def _publish_state(self, robot, ev=None):
        msg = PatrolState(robot_id=robot, **self.sims[robot].v2_state(ev))
        msg.header.stamp = self.get_clock().now().to_msg()
        self.pub[robot]['state'].publish(msg)

    def _publish_periodic(self, now):
        stamp = self.get_clock().now().to_msg()
        if now >= self.next_pose:
            self.next_pose = now + POSE_PERIOD_SEC
            for name, sim in self.sims.items():
                if self._silent(name, now):
                    continue
                msg = PoseWithCovarianceStamped()
                msg.header.stamp = stamp
                msg.header.frame_id = 'map'
                x, y, yaw = sim.pose
                msg.pose.pose.position.x = float(x)
                msg.pose.pose.position.y = float(y)
                msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
                msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
                self.pub[name]['pose'].publish(msg)
        if now >= self.next_battery:
            self.next_battery = now + BATTERY_PERIOD_SEC
            for name, sim in self.sims.items():
                if self._silent(name, now):
                    continue
                self.pub[name]['percent'].publish(Float32(data=float(sim.battery)))
                self.pub[name]['voltage'].publish(
                    Float32(data=float(battery_voltage(sim.battery))))
        if self.v1 and now >= self.next_status:
            # 실제 순찰 노드처럼 상태를 주기적으로 낸다. fleet 은 3초 안에 상태가 와야 배정한다
            self.next_status = now + STATUS_PERIOD_SEC
            for name, sim in self.sims.items():
                if not self._silent(name, now):
                    self._publish_status(name, sim.status())
        if self.v2 and now >= self.next_state:
            # v2 상태는 바뀔 때 + 1초마다 (수신 간격으로 연결을 판단할 수 있게)
            self.next_state = now + STATE_PERIOD_SEC
            for name in self.sims:
                if not self._silent(name, now):
                    self._publish_state(name)
        lines = self.book.status_lines()
        slots = self.book.slot_lines()
        if (lines, slots) != self.zone_lines or now >= self.next_zone:
            # 실제 zone_manager 처럼 바뀔 때 + 1초마다 다시 낸다 (상태와 대기 슬롯 모두)
            self.next_zone = now + ZONE_PERIOD_SEC
            self.zone_lines = (lines, slots)
            for line in lines:
                self.zone_pub.publish(String(data=line))
            for line in slots:
                self.slot_pub.publish(String(data=line))


def main(args=None):
    # 도메인 검사는 rclpy.init 전에 한다. 실물 도메인에는 참가자로도 나타나지 않게 하기 위해서다.
    logger = get_logger('mock_pinky_node')
    ok, message = check_domain(os.environ)
    if not ok:
        logger.fatal(f'시작 거부: {message}')
        sys.exit(1)
    if os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        logger.warning('ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST 가 아님. '
                       '같은 망의 다른 PC 에서도 가짜 토픽이 보일 수 있습니다.')
    rclpy.init(args=args)
    try:
        node = MockPinkyNode()
    except MockConfigError as error:
        logger.fatal(f'설정 오류: {error}')
        rclpy.try_shutdown()
        sys.exit(1)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # launch 의 Ctrl+C 는 정리 도중 인터럽트가 한 번 더 올 수 있다. 끄는 중이므로 무시한다.
        with contextlib.suppress(KeyboardInterrupt):
            node.destroy_node()
            rclpy.try_shutdown()
