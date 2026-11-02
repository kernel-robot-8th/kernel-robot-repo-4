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
관제 작업 노드: 로봇 명령 토픽에 발행하는 유일한 관제 노드.

백엔드(fleet_api_node)가 /control_center/task_request 로 요청을 보내면 검증하고 기록한 뒤
로봇에 명령을 보낸다. 결과는 /control_center/task_events(요청 응답·작업 변화)와
/control_center/tasks(최근 작업 목록) 로 알린다.

로봇 쪽은 두 규격을 받는다.
- v1 (지금 주행 코드): /pinkyN/patrol_cmd 문자열, /pinkyN/patrol_status JSON
- v2 (cobot_patrol_interfaces, 지금은 가짜 핑키만): /pinkyN/patrol_command, _ack, _state
spec_mode=auto 이면 v2 상태가 오는 로봇에만 v2 로 보낸다.

실물 로봇이 움직이는 노드다. bringup 에 넣지 않았고 따로 켜야 한다.
cmd_vel·goal_pose·initialpose 는 쓰지 않는다.

allow_raw_cmd(기본 꺼짐)를 켜면 화면의 개발용 수동 명령(type=raw)을 받아
검사·작업 기록 없이 /pinkyN/patrol_cmd 에 그대로 한 번 보낸다. 가짜 핑키 launch 만 켠다.
"""

import json
import os

from cobot_control_center.fleet_api_utils import LayerError
from cobot_control_center.task_manager_utils import (
    load_robot_points, TaskDB, TaskError, TaskManager)
from cobot_patrol_interfaces.msg import PatrolCommand, PatrolCommandAck, PatrolState
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


class TaskManagerNode(Node):
    """요청 → 검증·기록 → 로봇 명령, 로봇 상태 → 작업 상태."""

    def __init__(self):
        super().__init__('task_manager_node')
        p = {
            'robots': ['pinky1', 'pinky2', 'pinky3'],
            'db_path': '~/.ros/cobot_control_center/tasks.db',
            'points_dir': '', 'ack_timeout_sec': 3.0, 'task_timeout_sec': 300.0,
            'fleet_stale_sec': 3.0, 'retention_days': 30.0, 'spec_mode': 'auto',
            'v2_fresh_sec': 3.0, 'tick_period_sec': 0.2, 'publish_period_sec': 1.0,
            'list_limit': 50, 'allow_raw_cmd': False,
        }
        for name, value in p.items():
            self.declare_parameter(name, value)
        cfg = {name: self.get_parameter(name).value for name in p}
        robots = list(cfg['robots'])
        self.list_limit = int(cfg['list_limit'])

        db_path = os.path.expanduser(cfg['db_path'])
        self.db = TaskDB(db_path)
        pruned = self.db.prune(float(cfg['retention_days']))
        self.tm = TaskManager(
            self.db, robots, self._load_rules(cfg['points_dir'], robots),
            ack_timeout_sec=cfg['ack_timeout_sec'], task_timeout_sec=cfg['task_timeout_sec'],
            fleet_stale_sec=cfg['fleet_stale_sec'], spec_mode=cfg['spec_mode'],
            v2_fresh_sec=cfg['v2_fresh_sec'], allow_raw_cmd=cfg['allow_raw_cmd'])
        # 재시작 규칙: 끝나지 않은 작업은 다시 보내지 않고 UNKNOWN 으로 둔다.
        for task in self.db.recover():
            self.tm.changed.append(task)
            self.get_logger().warning(
                f'{task["robot_id"]} 작업 {task["task_id"]} ({task["command"]}) 를 UNKNOWN 으로: '
                f'관제 재시작 전에 끝나지 않음. 현장 확인 후 화면에서 해제')

        reliable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                              history=HistoryPolicy.KEEP_LAST)
        self.v1_pub, self.v2_pub = {}, {}
        for name in robots:
            # 순찰 노드·zone_manager 와 같이 reliable 로 맞춘다.
            self.v1_pub[name] = self.create_publisher(String, f'/{name}/patrol_cmd', reliable)
            self.v2_pub[name] = self.create_publisher(
                PatrolCommand, f'/{name}/patrol_command', reliable)
            self.create_subscription(String, f'/{name}/patrol_status',
                                     lambda msg, r=name: self._on_v1_status(r, msg), reliable)
            self.create_subscription(PatrolState, f'/{name}/patrol_state',
                                     lambda msg, r=name: self._on_v2_state(r, msg), reliable)
            self.create_subscription(PatrolCommandAck, f'/{name}/patrol_command_ack',
                                     lambda msg, r=name: self._on_v2_ack(r, msg), reliable)
        self.create_subscription(String, '/control_center/fleet_status', self._on_fleet, 10)
        self.create_subscription(String, '/control_center/task_request', self._on_request,
                                 QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE))
        self.events_pub = self.create_publisher(
            String, '/control_center/task_events',
            QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE))
        # 백엔드가 늦게 켜져도 마지막 목록을 바로 받게 transient_local 로 낸다.
        self.tasks_pub = self.create_publisher(
            String, '/control_center/tasks',
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(float(cfg['tick_period_sec']), self._tick)
        self.create_timer(float(cfg['publish_period_sec']), self._publish_tasks)
        self.get_logger().info(
            f'task_manager_node 시작 (robots={robots}, spec_mode={cfg["spec_mode"]}, '
            f'db={db_path}, 오래된 사건 {pruned}줄 정리). '
            f'도메인 {self.context.get_domain_id()} 의 로봇 명령 토픽에 발행한다')
        if cfg['allow_raw_cmd']:
            self.get_logger().warning(
                '수동 명령(allow_raw_cmd) 켜짐: 화면에서 검사 없이 patrol_cmd 에 문자열을 보낼 수 있다 (개발용)')
        self._flush()

    def _load_rules(self, points_dir, robots):
        # 지점 규칙이 없어도 로봇이 다시 검사하므로 돌 수는 있다. 하지만 미실측 지점을 못 막아 경고한다.
        if not points_dir:
            self.get_logger().warning('points_dir 가 비어 있음: 지점 검사 없이 로봇 검사에만 맡긴다')
            return {}
        try:
            rules = load_robot_points(points_dir, robots)
        except LayerError as error:
            self.get_logger().warning(f'{error}: 지점 검사 없이 로봇 검사에만 맡긴다')
            return {}
        for robot, rule in rules.items():
            self.get_logger().info(
                f'{robot}: goto {len(rule["goto"])}개, 구역 {sorted(rule["zone"])}, '
                f'미실측 {len(rule["placeholder"])}개 거절')
        return rules

    # ---------- 입력 ----------

    @staticmethod
    def _json(msg):
        try:
            data = json.loads(msg.data)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _on_fleet(self, msg):
        data = self._json(msg)
        if data is not None:
            self.tm.update_fleet(data)

    def _on_v1_status(self, robot, msg):
        data = self._json(msg)
        if data is not None:
            self.tm.on_v1_status(robot, data)
            self._flush()

    def _on_v2_state(self, robot, msg):
        self.tm.on_v2_state(robot, {'state': msg.state, 'detail': msg.detail,
                                    'task_id': msg.task_id, 'task_finished': msg.task_finished,
                                    'held_zone': msg.held_zone})
        self._flush()

    def _on_v2_ack(self, robot, msg):
        self.tm.on_v2_ack(robot, {'task_id': msg.task_id, 'accepted': msg.accepted,
                                  'reason': msg.reason})
        self._flush()

    def _on_request(self, msg):
        request = self._json(msg)
        if request is None:
            self.get_logger().warning('task_request 를 읽지 못함 (JSON 객체가 아님)')
            return
        handlers = {'create': self.tm.create, 'stop': self.tm.stop, 'resolve': self.tm.resolve,
                    'raw': self.tm.raw}
        kind = request.get('type')
        reply = {'type': 'reply', 'request_id': request.get('request_id')}
        try:
            if kind not in handlers:
                raise TaskError(400, f'알 수 없는 요청: {kind}')
            (status, body), actions = handlers[kind](request)
            reply.update(status=status, body=body)
        except TaskError as error:
            reply.update(status=error.status, body={'detail': error.detail})
            actions = []
        for action in actions:
            self._send(action)
        self._publish_event(reply)
        self._flush()

    # ---------- 출력 ----------

    def _send(self, action):
        robot = action['robot']
        if action['spec'] == 'v2':
            self.v2_pub[robot].publish(PatrolCommand(
                task_id=action['task_id'], operation=action['operation'],
                points=list(action['points'])))
        else:
            self.v1_pub[robot].publish(String(data=action['command']))
        self.get_logger().info(
            f'{robot} 에 명령 ({action["spec"]}): {action["command"]} [{action["task_id"]}]')

    def _publish_event(self, event):
        self.events_pub.publish(String(data=json.dumps(event, ensure_ascii=False)))

    def _flush(self):
        changed = self.tm.take_changed()
        for task in changed:
            self._publish_event({'type': 'task', 'task': task})
            self.get_logger().info(f'작업 {task["task_id"]} {task["robot_id"]} '
                                   f'{task["command"]}: {task["state"]} {task["detail"]}')
        if changed:
            self._publish_tasks()

    def _publish_tasks(self):
        self.tasks_pub.publish(String(data=json.dumps(self.tm.snapshot(self.list_limit),
                                                      ensure_ascii=False)))

    def _tick(self):
        self.tm.tick()
        self._flush()

    def destroy_node(self):
        self.db.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TaskManagerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
