"""격리 도메인에서 실제 fleet_control 노드와 왕복한다. 실제 로봇에는 접속하지 않는다."""

import json
import math
import os
from pathlib import Path
import threading
import time
from urllib import error, request

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
FLEET = PACKAGE.parent / 'cobot_navigation/cobot_fleet_control'
PATROL = PACKAGE.parent / 'cobot_navigation/cobot_pinky_patrol'
SHARE = {'cobot_fleet_control': FLEET, 'cobot_anomaly_monitor': PACKAGE,
         'cobot_pinky_patrol': PATROL}
ZONES = {'ZA': 'A', 'ZB': 'B', 'ZC': 'C'}


class Console:
    """HTTP 호출은 실행기를 막지 않도록 작업 스레드에서만 쓴다."""

    def __init__(self, port):
        self.url = f'http://127.0.0.1:{port}/api/fms/'

    def get(self):
        with request.urlopen(self.url + 'live_state', timeout=5) as reply:
            return json.loads(reply.read())

    def post(self, path, **body):
        item = request.Request(self.url + path, data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
        try:
            with request.urlopen(item, timeout=5) as reply:
                return reply.status, json.loads(reply.read())
        except error.HTTPError as reply:
            return reply.code, json.loads(reply.read())

    def wait(self, predicate, seconds=40):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            live = self.get()
            found = predicate(live)
            if found:
                return found
            time.sleep(0.1)
        raise AssertionError('시간 초과: ' + json.dumps(self.get(), ensure_ascii=False)[:800])

    def mission(self, live, order_id):
        return next((m for m in live.get('missions', []) if m['mission_id'] == order_id), None)

    def run_order(self, order_id, stop_at=None):
        """승인을 이어 가다가 stop_at 단계의 요청이 오면 멈춘다."""
        status, _ = self.post('control', type='order',
                              order={'order_id': order_id, 'sku': 'SHOE42',
                                     'route': 'wh_a_to_store'})
        assert status == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            live = self.get()
            mission = self.mission(live, order_id)
            if mission and mission['mission_state'] == 'COMPLETED':
                return mission
            for work in live.get('work', []):
                if work['order_id'] != order_id:
                    continue
                if work['stage'] == stop_at:
                    return work
                assert self.post('work/' + work['request_id'], decision='approve',
                                 operator='kgh')[0] == 200
            if mission and mission['current_stage'] == 'CUSTOMER':
                self.post('control', type='received', order_id=order_id)
            time.sleep(0.05)
        raise AssertionError('주문 시간 초과: ' + json.dumps(self.get(), ensure_ascii=False)[:800])


@pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '77' or os.environ.get('ROS_LOCALHOST_ONLY') != '1',
    reason='requires isolated ROS_DOMAIN_ID=77 and ROS_LOCALHOST_ONLY=1')
def test_order_and_cctv_pause_over_dds(tmp_path, monkeypatch):
    rclpy = pytest.importorskip('rclpy')
    from cobot_anomaly_monitor import monitor_node
    from cobot_fleet_control import fleet_control_node
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav_msgs.msg import Odometry
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import Float32, String

    for module in (fleet_control_node, monitor_node):
        monkeypatch.setattr(module, 'get_package_share_directory',
                            lambda name: str(SHARE[name]))
    dev = PACKAGE / 'config/scenario_relay_dev.yaml'
    site = PATROL / 'config/sites/lab.yaml'
    points = yaml.safe_load(site.read_text(encoding='utf-8'))[
        'pinky_patrol_node']['ros__parameters']['points']
    rclpy.init(args=[
        '--ros-args',
        '-p', f'fleet_control:db_path:={tmp_path / "fleet.sqlite3"}',
        '-p', f'fleet_control:scenario_config:={dev}',
        '-p', f'anomaly_monitor:db_path:={tmp_path / "monitor.sqlite3"}',
        '-p', 'anomaly_monitor:console_port:=0'])
    fleet, monitor, robot, executor = None, None, None, None
    try:
        fleet = fleet_control_node.FleetControlNode()
        monitor = monitor_node.AnomalyMonitorNode()
        robot = Node('isolated_fake_robot')
        commands = []
        state = {'state': 'IDLE', 'central_controlled': True, 'busy': False, 'detail': ''}
        status_pub = robot.create_publisher(String, '/pinky1/patrol_status', 10)
        battery_pub = robot.create_publisher(Float32, '/pinky1/battery/percent', 10)
        pose_pub = robot.create_publisher(PoseWithCovarianceStamped, '/pinky1/amcl_pose', 10)
        odom_pub = robot.create_publisher(Odometry, '/pinky1/odom', 10)
        event_pub = robot.create_publisher(String, '/anomaly_monitor/vision_event', 50)

        def publish_pose(point):
            message = PoseWithCovarianceStamped()
            message.pose.pose.position.x, message.pose.pose.position.y = point[0], point[1]
            message.pose.pose.orientation.z = math.sin(point[2] / 2)
            message.pose.pose.orientation.w = math.cos(point[2] / 2)
            pose_pub.publish(message)

        def receive(message):
            payload = json.loads(message.data)
            commands.append(payload)
            command = payload['command']
            if command.startswith('zone:'):
                point = command.split(':')[1]
                state.update(state='HOLDING_ZONE', held_zone=ZONES[point], detail=point)
                publish_pose(points[point])
            elif command in ('leave', 'home'):
                state.update(state='IDLE', held_zone=None, detail='')
            elif command == 'emergency_stop':
                state.update(central_latched=True)
                return
            elif command == 'control_reset':
                state.update(central_latched=False)
                return
            status_pub.publish(String(data=json.dumps(dict(
                state, command_id=payload['command_id'], task_finished=True) | {'state': 'DONE'})))

        def beat():
            status_pub.publish(String(data=json.dumps(state)))
            battery_pub.publish(Float32(data=80.0))
            odom_pub.publish(Odometry())

        robot.create_subscription(String, '/pinky1/patrol_cmd', receive, 10)
        robot.create_timer(0.2, beat)
        executor = SingleThreadedExecutor()
        for node in (fleet, monitor, robot):
            executor.add_node(node)
        console = Console(monitor.server.server_address[1])
        outcome = {}

        def scenario():
            assert console.wait(lambda live: live.get('adapter', {}).get('enabled')
                                and not live['adapter']['blocked'])
            assert console.post('control', type='arm', armed=True, source='test')[0] == 200
            assert console.post('control', type='inventory', sku='SHOE42', available=5)[0] == 200
            outcome['completed'] = console.run_order('order1')
            outcome['steps'] = console.wait(lambda live: console.mission(live, 'order1'))
            outcome['load'] = console.run_order('order2', stop_at='LOAD')
            assert console.post('mode', mode='AUTO_HOLD')[0] == 200
            for event_id, camera in (('e_sim', 'sim_ceil_cam'), ('e_real', 'ceil_cam')):
                event_pub.publish(String(data=json.dumps({
                    'event_id': event_id, 'camera_id': camera,
                    'vision_class': 'box_perched_on_rim', 'confidence': 0.9,
                    'detected_at': time.time(), 'map_x': points['ZA'][0],
                    'map_y': points['ZA'][1]})))
            outcome['paused'] = console.wait(
                lambda live: (console.mission(live, 'order2') or {}).get('mission_state')
                == 'PAUSED' and live)

        def guarded():
            try:
                scenario()
            except BaseException as failure:
                outcome['error'] = failure

        worker = threading.Thread(target=guarded, daemon=True)
        worker.start()
        deadline = time.monotonic() + 120
        while worker.is_alive():
            executor.spin_once(timeout_sec=0.02)
            assert time.monotonic() < deadline
        if 'error' in outcome:
            raise outcome['error']
        assert outcome['completed']['current_step_seq'] == 7
        assert [c['command'] for c in commands[:5]] == [
            'zone:ZA', 'leave', 'zone:ZC', 'leave', 'home']
        paused = outcome['paused']
        events = {row['event_id']: row for row in paused['anomalies']}
        assert 'e_sim' not in events
        assert events['e_real']['judgment'] == 'LOAD_FAIL_PERCHED'
        assert events['e_real']['linked_mission_id'] == 'order2'
        assert any(c['command'] == 'emergency_stop' for c in commands)
        assert fleet.count_publishers('/pinky1/patrol_cmd') == 1
        assert fleet.count_subscribers('/control_center/task_request') == 1
        assert fleet.count_publishers('/control_center/tasks') == 1
    finally:
        if executor:
            executor.shutdown()
        for node in (monitor, fleet, robot):
            if node:
                node.destroy_node()
        rclpy.shutdown()
