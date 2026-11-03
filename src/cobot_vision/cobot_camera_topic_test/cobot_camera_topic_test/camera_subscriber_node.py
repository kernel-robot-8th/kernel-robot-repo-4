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

"""Receive and decode compressed camera images with Best Effort QoS."""

import math
import time

import cv2
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from cobot_camera_topic_test.camera_runtime import camera_qos, run_node
from cobot_camera_topic_test.camera_utils import StreamStats


class CameraSubscriberNode(Node):
    """Check decoded frames and report receive throughput without a GUI by default."""

    def __init__(self, **kwargs):
        """Subscribe to the configured topic with explicit sensor QoS."""
        super().__init__('camera_subscriber', **kwargs)
        self.window_open = False
        try:
            topic = self.declare_parameter('topic', 'camera/image_raw/compressed').value
            self.display = self.declare_parameter('display', False).value
            interval = self.declare_parameter('report_interval', 2.0).value
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError('report_interval must be finite and positive')
            if self.display:
                cv2.namedWindow('ROS 2 camera test', cv2.WINDOW_NORMAL)
                self.window_open = True
            self.stats = StreamStats(time.monotonic())
            self.total_frames = 0
            self.invalid_frames = 0
            self.last_shape = None
            self.subscription = self.create_subscription(
                CompressedImage, topic, self.receive_frame, camera_qos())
            self.timer = self.create_timer(interval, self.report)
            self.get_logger().info(
                f'topic={self.subscription.topic_name}, '
                'QoS=BEST_EFFORT / VOLATILE / KEEP_LAST(1)')
        except Exception:
            self.destroy_node()
            raise

    def receive_frame(self, message):
        """Count only decodable images as successful communication."""
        try:
            data = np.frombuffer(message.data, dtype=np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        except cv2.error:
            frame = None
        if frame is None:
            self.invalid_frames += 1
            return
        self.stats.record(len(message.data))
        self.total_frames += 1
        self.last_shape = frame.shape[:2]
        if self.display:
            cv2.imshow('ROS 2 camera test', frame)
            cv2.waitKey(1)

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

    def destroy_node(self):
        """Close the optional preview window."""
        if self.window_open:
            cv2.destroyWindow('ROS 2 camera test')
            self.window_open = False
        return super().destroy_node()


def main(args=None):
    """Start the camera subscriber."""
    run_node(CameraSubscriberNode, args)
