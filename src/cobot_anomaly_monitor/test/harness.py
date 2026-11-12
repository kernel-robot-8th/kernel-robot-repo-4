"""실제 ScenarioService·ControlAPI에 기록 코어와 수동 어댑터를 연결한 시험 환경."""

from pathlib import Path

from cobot_anomaly_monitor.console_api import ConsoleApi
from cobot_anomaly_monitor.manual_adapter import ManualAdapter
from cobot_anomaly_monitor.monitor_core import MonitorCore
from cobot_anomaly_monitor.monitor_store import MonitorStore
from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.scenario import ScenarioService
from cobot_fleet_control.scenario_contracts import NAVIGATION
from cobot_fleet_control.service import FleetService
import yaml

ROBOTS = ['pinky1', 'pinky2', 'pinky3']
TARGETS = ['vision', 'navigation', 'omx1', 'omx2', 'omx3', 'omx4']
POINTS = {'ZA': [0.6, 0.5, -1.5], 'ZB': [0.6, -0.15, -1.5], 'ZC': [-0.5, 0.3, 1.5],
          'ZD': [-0.5, -0.5, 1.5]}
ZONE = {'ZA': 'A', 'ZB': 'B', 'ZC': 'C', 'ZD': 'D'}
DEV_CONFIG = Path(__file__).resolve().parents[1] / 'config/scenario_relay_dev.yaml'
# 개발 경로 둘은 ZC와 주행 통로를 함께 써서 동시에 달리지 않는다. 동시 주행 시험에만 쓴다.
SIDE_ROUTE = {'pickup': 'ZB', 'dropoff': 'ZD', 'pickup_arm': 'omx2', 'dropoff_arm': 'omx4',
              'lane': 'side'}
WALL_START = 1000.0


class Gateway:
    """fleet_control_node의 ROS 출력 자리. 장치 요청에는 실제와 같은 봉투를 씌운다."""

    def __init__(self, stack):
        self.stack = stack
        self.sent, self.halts, self.releases = [], [], []
        self.sequences = {}

    def send(self, robot, payload):
        self.sent.append((robot, payload))

    def work(self, payload):
        target = payload['target']
        self.sequences[target] = self.sequences.get(target, 0) + 1
        self.stack.adapter.on_request(dict(
            payload, session_id='s1', seq=self.sequences[target],
            issued_at=self.stack.wall(), ttl_sec=5.0))

    def halt(self, robot, route, order_id):
        self.halts.append(robot)

    def release(self, robot, route=None):
        self.releases.append(robot)


class Stack:
    """관제 한 벌과 모니터 한 벌을 같은 시계로 돌린다."""

    def __init__(self, path):
        self.now = 0.0
        self.config = yaml.safe_load(DEV_CONFIG.read_text(encoding='utf-8'))
        self.routes = dict(self.config['routes'], side=SIDE_ROUTE)
        self.gateway = Gateway(self)
        self.repo = SqliteRepository(str(path / 'fleet.sqlite3'))
        self.fleet = FleetService(self.repo, self.gateway, ROBOTS, lambda: self.now)
        self.scenario = ScenarioService(self.repo, self.fleet, self.gateway,
                                        **dict(self.config, routes=self.routes),
                                        clock=lambda: self.now)
        self.api = ControlAPI(self.scenario, self.fleet, self.gateway)
        self.requests = []
        self.store = MonitorStore(path / 'monitor.sqlite3')
        self.core = MonitorCore(self.store, self.routes, ROBOTS, self._request, clock=self.wall)
        self.adapter = ManualAdapter(self.store, self.scenario.result, TARGETS, POINTS,
                                     self.core._robot_view, clock=self.wall)
        self.adapter.on_heartbeat({'session_id': 's1'})
        self.console = ConsoleApi(self.core, self.adapter, lambda job: job(),
                                  self.core.replies.get, clock=self.wall, commands=True)
        self.status = {r: {'state': 'IDLE', 'central_controlled': True} for r in ROBOTS}
        self.scenario.armed = True
        self.scenario.store.set_stock('SHOE42', 10)
        self.event_count = 0
        self.history = []

    def close(self):
        self.store.close()
        self.repo.close()

    def wall(self):
        return WALL_START + self.now

    def _request(self, payload):
        self.requests.append(payload)
        self.core.on_task_event(self.api.handle(payload))

    def control(self, **request):
        return self.console.handle('POST', '/api/fms/control', request)

    def stop_requests(self):
        return [r for r in self.requests if r['type'] in ('pause', 'estop')]

    def tick(self, seconds=0.1):
        self.now += seconds
        for robot in ROBOTS:
            self.scenario.telemetry(robot, self.status[robot], 80.0)
            self.core.on_status(robot, self.status[robot])
        self.scenario.tick()
        self.fleet.tick(allow_dispatch=self.scenario.armed)
        self.core.on_tasks(self.api.snapshot())
        self.history.append(self.core.robots_view())

    def wait(self, seconds):
        for _ in range(int(seconds)):
            self.tick(1.0)

    def order(self, order_id='order1', route='wh_a_to_store'):
        return self.scenario.submit({'order_id': order_id, 'sku': 'SHOE42', 'route': route})

    def current(self, order_id='order1'):
        return self.scenario.store.get(order_id)

    def move(self, robot, state, detail=''):
        self.status[robot].update(state=state, detail=detail)
        self.tick()

    def arrive(self, order):
        """주행 명령을 끝낸다. 구역 도착이면 자세와 구역 토큰을 맞춘다."""
        robot, stage = order['robot_id'], order['stage']
        route = self.core._route(order)
        status = self.status[robot]
        if stage.startswith('MOVE_'):
            point = route['pickup' if stage == 'MOVE_PICKUP' else 'dropoff']
            self.core.on_pose(robot, POINTS[point][0] + 0.01, POINTS[point][1],
                              POINTS[point][2] + 0.02)
            status.update(state='HOLDING_ZONE', held_zone=ZONE[point], detail=point)
        elif stage == 'RETURN_HOME':
            status.update(state='IDLE', held_zone=None, detail='')
        else:
            status.update(state='IDLE_WAIT', held_zone=None, detail='')
        self.core.on_speed(robot, 0.0)
        self.fleet.tick(allow_dispatch=self.scenario.armed)
        self.fleet.on_status(robot, {'command_id': order['request_id'], 'state': 'DONE',
                                     'task_finished': True})
        self.fleet.tick(allow_dispatch=self.scenario.armed)

    def drive(self, order):
        robot, stage = order['robot_id'], order['stage']
        if stage.startswith('MOVE_'):
            route = self.core._route(order)
            self.move(robot, 'QUEUEING', 'slot0')
            self.move(robot, 'MOVING', route['pickup' if stage == 'MOVE_PICKUP' else 'dropoff'])
        else:
            self.move(robot, 'RETURNING' if stage == 'RETURN_HOME' else 'LEAVING_ZONE', 'EXIT')
        self.arrive(order)

    def approve(self, order):
        self.adapter.approve(order['request_id'], 'kgh')

    def step(self, order_id='order1'):
        self.tick()
        self.advance(order_id)

    def advance(self, order_id):
        order = self.current(order_id)
        if order['state'] != 'RUNNING' or not order['request_id'] and (
                order['stage'] != 'CUSTOMER'):
            return
        if order['stage'] == 'CUSTOMER':
            self.scenario.received(order_id)
        elif order['stage'] in NAVIGATION:
            self.drive(order)
        else:
            self.approve(order)

    def until(self, stage, order_id='order1'):
        for _ in range(300):
            self.tick()
            order = self.current(order_id)
            if order['stage'] == stage and order['request_id']:
                return order
            self.advance(order_id)
        raise AssertionError('stage not reached: ' + stage)

    def vision(self, vision_class, xy, event_id=None, confidence=0.9):
        self.event_count += 1
        return self.core.on_vision_event({
            'event_id': event_id or f'event{self.event_count}', 'camera_id': 'ceil_cam',
            'vision_class': vision_class, 'confidence': confidence, 'detected_at': self.wall(),
            'map_x': xy[0], 'map_y': xy[1]})

    def live_mission(self, order_id='order1'):
        return next(m for m in self.core.live()['missions'] if m['mission_id'] == order_id)
