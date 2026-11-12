"""픽셀 검출을 /anomaly_monitor/vision_event 이벤트로 바꾸는 노드."""

import json
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from .pixel_map import calibration_problem, load_calibration, to_vision_event


class PixelEventNode(Node):
    """보정값이 없으면 좌표 없는 이벤트를 낸다. 판정은 NO_POSITION이 된다."""

    def __init__(self):
        super().__init__('pixel_event')
        share = Path(get_package_share_directory('cobot_anomaly_monitor'))
        defaults = {
            'calibration_path': str(share / 'config/camera_calibration.yaml'),
            'input_topic': '/anomaly_monitor/pixel_event',
            'output_topic': '/anomaly_monitor/vision_event',
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        self.calibration = load_calibration(config['calibration_path'])
        self.publisher = self.create_publisher(String, config['output_topic'], 50)
        self.create_subscription(String, config['input_topic'], self._detection, 50)
        problem = calibration_problem(self.calibration)
        if problem:
            self.get_logger().warning(f'좌표를 내지 않습니다: {problem}')

    def _detection(self, message):
        try:
            event, reason = to_vision_event(json.loads(message.data), self.calibration)
        except ValueError as error:
            self.get_logger().warning(f'검출 무시: {error}')
            return
        if reason:
            self.get_logger().warning(f"좌표 없음 {event['event_id']}: {reason}")
        self.publisher.publish(String(data=json.dumps(event, ensure_ascii=False)))


def main(args=None):
    """변환 노드를 시작한다."""
    rclpy.init(args=args)
    node = PixelEventNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
