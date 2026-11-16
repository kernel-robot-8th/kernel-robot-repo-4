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

"""Monitor raw Pinky Pro camera topics without OpenCV or NumPy dependencies."""

import math
import time

from rclpy.node import Node
from sensor_msgs.msg import Image

from cobot_camera_topic_test.camera_runtime import camera_qos, run_node
from cobot_camera_topic_test.camera_utils import StreamStats, validate_image


class CameraSubscriberNode(Node):
    """Check image metadata and payload size and report receive throughput."""

    def __init__(self, **kwargs):
        """Subscribe to the official raw topic with explicit Best Effort QoS."""
        super().__init__('camera_subscriber', **kwargs)
        try:
            topic = self.declare_parameter('topic', '/camera/image_raw').value
            interval = self.declare_parameter('report_interval', 2.0).value
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError('report_interval must be finite and positive')
            self.stats = StreamStats(time.monotonic())
            self.total_frames = 0
            self.invalid_frames = 0
            self.last_shape = None
            self.subscription = self.create_subscription(
                Image, topic, self.receive_frame, camera_qos())
            self.timer = self.create_timer(interval, self.report)
            self.get_logger().info(
                f'topic={self.subscription.topic_name}, '
                'QoS=BEST_EFFORT / VOLATILE / KEEP_LAST(1)')
        except Exception:
            self.destroy_node()
            raise

    def receive_frame(self, message):
        """Count structurally valid images without loading image-processing libraries."""
        try:
            validate_image(message.width, message.height, message.step,
                           message.encoding, message.data)
        except ValueError:
            self.invalid_frames += 1
            return
        self.stats.record(len(message.data))
        self.total_frames += 1
        self.last_shape = (message.height, message.width)

    def report(self):
        """Report local receive rates and warn about missing valid frames."""
        frames, fps, kib_per_second = self.stats.sample(time.monotonic())
        if frames == 0:
            self.get_logger().warning(
                f'No valid frames: total={self.total_frames}, invalid={self.invalid_frames}; '
                'check publisher, topic, domain, network and QoS')
            return
        height, width = self.last_shape
        self.get_logger().info(
            f'received={self.total_frames}, fps={fps:.1f}, '
            f'KiB/s={kib_per_second:.1f}, size={width}x{height}, '
            f'invalid={self.invalid_frames}')


def main(args=None):
    """Start the raw camera subscriber."""
    run_node(CameraSubscriberNode, args)
