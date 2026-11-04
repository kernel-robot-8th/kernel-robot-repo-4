"""업무 서비스. MQTT·ROS 콜백은 큐로 전달하고 이 객체는 한 스레드에서 사용한다."""

import time

import py_trees

from .behaviours import build_tree
from .bt_visualization import TreeTrace
from .contracts import Command
from .repository import encode


class FleetService:
    """로봇별 한 작업, 서로 다른 로봇의 BT는 독립적으로 tick한다."""

    def __init__(self, repository, gateway, robots, clock=time.monotonic):
        self.repository = repository
        self.gateway = gateway
        self.robots = robots
        self.clock = clock
        self.active = {}
        self.traces = {}
        repository.recover()

    def submit(self, payload):
        """명령 QoS 1 중복은 재실행하지 않고 같은 ID의 다른 내용은 거절한다."""
        command = Command.parse(payload, self.robots)
        previous = self.repository.get(command.command_id)
        if previous:
            if previous['payload'] != encode(command.payload()):
                raise ValueError('같은 command_id에 다른 명령을 사용할 수 없습니다')
            return previous
        if self.repository.busy(command.robot_id):
            raise ValueError('로봇 작업 중 또는 UNKNOWN: 기존 작업 확인 필요')
        self.repository.create(command)
        tree, result = build_tree(command, self.repository, self.gateway, self.clock)
        self.active[command.command_id] = (command, tree, result)
        self.traces[command.command_id] = TreeTrace(command, tree, self.repository)
        self.traces[command.command_id].capture('created')
        return self.repository.get(command.command_id)

    def tick(self):
        """통신 발행의 성공을 로봇 도착 성공으로 처리하지 않는다."""
        for command_id, (_, tree, _) in list(self.active.items()):
            try:
                tree.tick()
            except Exception:
                self.repository.transition(command_id, 'UNKNOWN', '명령 전달 중 예외: 현장 확인 필요')
                self.traces.pop(command_id).capture('tick_error')
                del self.active[command_id]
                raise
            self.traces[command_id].capture()
            if tree.root.status != py_trees.common.Status.RUNNING:
                del self.active[command_id]
                del self.traces[command_id]

    def on_status(self, robot_id, status):
        """잘못된 로봇·이전 작업·중간 DONE을 완료로 오인하지 않는다."""
        if not isinstance(status, dict):
            raise ValueError('로봇 상태는 JSON 객체여야 합니다')
        command_id = status.get('command_id')
        if not isinstance(command_id, str):
            return
        row = self.repository.get(command_id)
        if not row or row['robot_id'] != robot_id:
            return
        if (status.get('task_finished') is not True
                or status.get('state') not in {'DONE', 'FAILED', 'STOPPED'}):
            return
        if command_id in self.active:
            self.active[command_id][2].result = status
        elif row['state'] == 'UNKNOWN':
            # 지연 완료가 실제로 도착했을 때만 자동으로 점유를 해제한다.
            self.repository.transition(command_id,
                                       'SUCCEEDED' if status['state'] == 'DONE' else 'FAILED',
                                       status.get('detail', ''))
