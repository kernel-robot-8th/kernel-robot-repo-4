"""ROS-only roundtrip in an explicitly isolated domain; never runs against real robots."""

import json
import os
from pathlib import Path
import time

import pytest


@pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '77' or os.environ.get('ROS_LOCALHOST_ONLY') != '1',
    reason='requires isolated ROS_DOMAIN_ID=77 and ROS_LOCALHOST_ONLY=1')
def test_ros_web_request_navigation_result_and_snapshot(tmp_path, monkeypatch):
    """Exercise the real node with DDS and a fake robot, without HTTP or MQTT."""
    rclpy = pytest.importorskip('rclpy')
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import Float32, String
    from cobot_fleet_control import fleet_control_node as module

    package = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(module, 'get_package_share_directory', lambda name: str(package))
    rclpy.init(args=['--ros-args', '-p', f'db_path:={tmp_path / "fleet.sqlite3"}'])
    server, robot, executor = None, None, None
    try:
        server = module.FleetControlNode()
        robot = Node('isolated_fake_robot')
        commands, replies = [], []
        status = robot.create_publisher(String, '/pinky1/patrol_status', 10)
        battery = robot.create_publisher(Float32, '/pinky1/battery/percent', 10)
        requests = robot.create_publisher(String, '/control_center/task_request', 50)

        def receive(message):
            payload = json.loads(message.data)
            commands.append(payload)
            status.publish(String(data=json.dumps(dict(
                command_id=payload['command_id'], state='DONE', task_finished=True,
                central_controlled=True))))

        robot.create_subscription(String, '/pinky1/patrol_cmd', receive, 10)
        robot.create_subscription(String, '/control_center/task_events',
                                  lambda m: replies.append(json.loads(m.data)), 50)
        executor = SingleThreadedExecutor()
        executor.add_node(server)
        executor.add_node(robot)

        def spin_until(predicate):
            deadline = time.monotonic() + 10
            while not predicate():
                executor.spin_once(timeout_sec=0.02)
                assert time.monotonic() < deadline

        spin_until(lambda: server.publishers_by_robot['pinky1'].get_subscription_count() == 1
                   and requests.get_subscription_count() == 1
                   and battery.get_subscription_count() == 1)
        status.publish(String(data=json.dumps(dict(state='IDLE', central_controlled=True))))
        battery.publish(Float32(data=80.0))
        spin_until(lambda: server.scenario._fresh('pinky1'))
        requests.publish(String(data=json.dumps(dict(type='arm', armed=True, request_id='arm1'))))
        spin_until(lambda: server.scenario.armed)
        request = dict(type='create', request_id='web1', client_request_id='job1',
                       robot_id='pinky1', operation='goto', points=['P1'])
        requests.publish(String(data=json.dumps(request)))
        spin_until(lambda: server.repository.get('job1') is not None
                   and server.repository.get('job1')['state'] == 'SUCCEEDED')
        requests.publish(String(data=json.dumps(request)))
        spin_until(lambda: len([r for r in replies if r.get('request_id') == 'web1']) == 2)
        assert len(commands) == 1
        assert server.api.snapshot()['tasks'][0]['state'] == 'SUCCEEDED'
    finally:
        if executor:
            executor.shutdown()
        if server:
            server.destroy_node()
        if robot:
            robot.destroy_node()
        rclpy.shutdown()
