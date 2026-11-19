"""단방향 MQTT 구역·상자 근거 수신기. 로봇 및 fleet 결과 토픽을 발행하지 않는다.

YOLO 프로그램이 ROS 로 직접 발행하게 되면 이 수신기는 없앤다.
"""

import argparse
import json
import os

import rclpy
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=1883)
    parser.add_argument('--field-domain', default='',
                        help='격리 도메인 밖에서 돌릴 때 그 ROS 도메인 번호를 적는다')
    args = parser.parse_args(argv)
    domain = os.environ.get('ROS_DOMAIN_ID')
    isolated = (domain in ('77', '140')
                and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST')
    if not isolated and (not args.field_domain or args.field_domain != domain):
        parser.error('격리 도메인 77/140 이 아니면 --field-domain 에 지금 ROS_DOMAIN_ID 를 적어야 합니다')
    import paho.mqtt.client as mqtt

    rclpy.init()
    node = rclpy.create_node('mqtt_zone_evidence')
    pubs = {
        'relay/evidence/zones': node.create_publisher(
            String, '/anomaly_monitor/zone_evidence', 10),
        'relay/evidence/boxes': node.create_publisher(
            String, '/anomaly_monitor/box_evidence', 10),
    }
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def connected(client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            for topic in pubs:
                client.subscribe(topic, qos=1)

    def received(client, userdata, msg):
        if msg.retain or len(msg.payload) > 16384:
            return
        try:
            frame = json.loads(msg.payload)
            if isinstance(frame, dict):
                pubs[msg.topic].publish(String(data=json.dumps(frame)))
        except (ValueError, UnicodeError, KeyError):
            node.get_logger().warning('근거 JSON 무시')

    client.on_connect = connected
    client.on_message = received
    try:
        client.connect_async(args.broker, args.port)
        client.loop_start()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        client.disconnect()
        client.loop_stop()
        node.destroy_node()
        rclpy.try_shutdown()
