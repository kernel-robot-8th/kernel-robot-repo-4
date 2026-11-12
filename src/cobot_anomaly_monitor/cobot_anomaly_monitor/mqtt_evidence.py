"""시뮬용 단방향 MQTT 구역 근거 수신기. 로봇 및 fleet 결과 토픽을 발행하지 않는다."""

import argparse
import json
import os

import rclpy
from std_msgs.msg import String


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=1883)
    args = parser.parse_args(argv)
    if (os.environ.get('ROS_DOMAIN_ID') not in ('77', '140')
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        parser.error('격리된 홈랩 도메인 77/140 전용')
    import paho.mqtt.client as mqtt

    rclpy.init()
    node = rclpy.create_node('mqtt_zone_evidence')
    pub = node.create_publisher(String, '/anomaly_monitor/zone_evidence', 10)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def connected(client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            client.subscribe('relay/evidence/zones', qos=1)

    def received(client, userdata, msg):
        if msg.retain or len(msg.payload) > 16384:
            return
        try:
            frame = json.loads(msg.payload)
            if isinstance(frame, dict):
                pub.publish(String(data=json.dumps(frame)))
        except (ValueError, UnicodeError):
            node.get_logger().warning('구역 근거 JSON 무시')

    client.on_connect = connected
    client.on_message = received
    try:
        client.connect_async(args.broker, args.port)
        client.loop_start()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        client.loop_stop()
        node.destroy_node()
        rclpy.try_shutdown()
