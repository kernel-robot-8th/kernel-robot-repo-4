"""로컬 실제 MQTT 브로커와 ROS 노드, SQLite를 연결하는 격리 통합 시험."""

import json
import os
from pathlib import Path
from queue import Empty, Queue
import socket
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '77' or os.environ.get('ROS_LOCALHOST_ONLY') != '1',
    reason='격리 도메인 77과 localhost 환경에서만 실행')
def test_real_mqtt_ros_sqlite_roundtrip(tmp_path):
    """외부 명령의 중복 수신부터 실제 ROS 왕복·DB·MQTT 결과까지 검증한다."""
    pytest.importorskip('amqtt')
    import paho.mqtt.client as mqtt
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String

    from cobot_fleet_control.fleet_control_node import FleetControlNode

    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    broker_code = """
import asyncio
import sys
from amqtt.broker import Broker
async def main():
    broker = Broker({'listeners': {'default': {'type': 'tcp', 'bind':
                     '127.0.0.1:' + sys.argv[1]}},
                     'plugins': {'amqtt.plugins.authentication.AnonymousAuthPlugin':
                                 {'allow_anonymous': True}}})
    await broker.start()
    print('ready', flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
    broker = subprocess.Popen([sys.executable, '-u', '-c', broker_code, str(port)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    server = robot = client = executor = None
    try:
        # 파이프 readline 대신 제한된 시간 동안 소켓 연결로 기동을 확인한다.
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail('테스트 브로커 기동 실패')
                time.sleep(0.05)
        rclpy.init(args=['--ros-args', '-p', f'mqtt_port:={port}',
                         '-p', f'db_path:={tmp_path / "fleet.sqlite3"}',
                         '-p', 'mqtt_client_id:=fleet_integration_test'])
        server = FleetControlNode()
        robot = Node('fake_pinky')
        status_pub = robot.create_publisher(String, '/pinky1/patrol_status', 10)
        commands = []

        def receive(message):
            payload = json.loads(message.data)
            commands.append(payload)
            status_pub.publish(String(data=json.dumps({
                'command_id': payload['command_id'], 'state': 'DONE',
                'task_finished': True, 'detail': 'fake navigator completed'})))

        subscription = robot.create_subscription(String, '/pinky1/patrol_cmd', receive, 10)
        executor = SingleThreadedExecutor()
        executor.add_node(server)
        executor.add_node(robot)
        received = Queue()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = lambda c, *_: c.subscribe('cobot/fleet/#', qos=1)
        client.on_message = lambda c, u, m: received.put((m.topic, json.loads(m.payload)))
        client.connect('127.0.0.1', port)
        client.loop_start()
        deadline = time.monotonic() + 10
        while (not client.is_connected() or not server.mqtt.is_connected()
               or server.publishers_by_robot['pinky1'].get_subscription_count() == 0):
            executor.spin_once(timeout_sec=0.05)
            assert time.monotonic() < deadline
        # SUBACK과 DDS discovery가 완료될 시간을 executor를 돌리며 확보한다.
        for _ in range(20):
            executor.spin_once(timeout_sec=0.05)
        payload = json.dumps({'command_id': 'integration_job', 'robot_id': 'pinky1',
                              'operation': 'goto', 'points': ['P1']})
        client.publish('cobot/fleet/commands', payload, qos=1).wait_for_publish(timeout=2)
        client.publish('cobot/fleet/commands', payload, qos=1).wait_for_publish(timeout=2)
        succeeded = False
        tree_succeeded = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
            try:
                while True:
                    topic, event = received.get_nowait()
                    if topic.endswith('/events') and event.get('state') == 'SUCCEEDED':
                        succeeded = True
                    if (topic.endswith('/events') and event.get('type') == 'bt_snapshot'
                            and event.get('job_state') == 'SUCCEEDED'):
                        tree_succeeded = True
            except Empty:
                pass
            if succeeded and tree_succeeded:
                break
        assert succeeded and tree_succeeded
        assert len(commands) == 1
        assert server.repository.get('integration_job')['state'] == 'SUCCEEDED'
        assert Path(tmp_path / 'fleet.sqlite3').is_file()
        robot.destroy_subscription(subscription)
    finally:
        if client:
            client.disconnect()
            client.loop_stop()
        if executor:
            executor.shutdown()
        if server:
            server.destroy_node()
        if robot:
            robot.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        broker.terminate()
        broker.communicate(timeout=5)
