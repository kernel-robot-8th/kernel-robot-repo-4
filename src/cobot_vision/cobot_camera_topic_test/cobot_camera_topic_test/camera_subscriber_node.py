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

"""Subscribe to Image topic and display or save frames."""

import cv2
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

from cobot_camera_topic_test.camera_runtime import camera_qos, run_node


class CameraSubscriberNode(Node):
    """Subscribe to camera topic and display frames."""

    def __init__(self, **kwargs):
        """Subscribe to camera topic."""
        super().__init__('camera_subscriber', **kwargs)
        topic = self.declare_parameter('topic', 'camera/image_raw').value
        self.display = self.declare_parameter('display', False).value
        self.report_interval = self.declare_parameter('report_interval', 2.0).value

        self.bridge = CvBridge()
        self.subscription = self.create_subscription(
            Image, topic, self.image_callback, camera_qos())
        self.frame_count = 0
        self.last_report_time = self.get_clock().now().nanoseconds / 1e9

        self.get_logger().info(f'Subscribed to {topic}, display={self.display}')

    def image_callback(self, msg):
        """Process received image."""
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

            if frame is None:
                self.get_logger().warning('Failed to convert image')
                return

            self.frame_count += 1

            if self.display:
                cv2.imshow('Camera Feed', frame)
                cv2.waitKey(1)

            current_time = self.get_clock().now().nanoseconds / 1e9
            if current_time - self.last_report_time >= self.report_interval:
                self.get_logger().info(f'Received {self.frame_count} frames')
                self.last_report_time = current_time

        except Exception as e:
            self.get_logger().error(f'Error processing image: {e}')

    def destroy_node(self):
        """Clean up on shutdown."""
        cv2.destroyAllWindows()
        return super().destroy_node()


def main(args=None):
    """Start the camera subscriber."""
    run_node(CameraSubscriberNode, args)
