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

"""Publish JPEG camera frames or a moving test pattern with Best Effort QoS."""

from dataclasses import fields

import cv2
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from cobot_camera_topic_test.camera_runtime import camera_qos, run_node
from cobot_camera_topic_test.camera_utils import CameraSettings


class CameraPublisherNode(Node):
    """Read one camera source and publish a standard compressed image topic."""

    def __init__(self, **kwargs):
        """Validate all startup parameters before accessing the camera."""
        super().__init__('camera_publisher', **kwargs)
        self.capture = None
        try:
            defaults = CameraSettings()
            values = {
                field.name: self.declare_parameter(
                    field.name, getattr(defaults, field.name)).value
                for field in fields(defaults)
            }
            self.settings = CameraSettings(**values).validate()
            topic = self.declare_parameter('topic', 'camera/image_raw/compressed').value
            self.publisher = self.create_publisher(CompressedImage, topic, camera_qos())
            self.sequence = 0
            self.read_failures = 0
            if self.settings.source == 'camera':
                device = self.settings.device
                self.capture = cv2.VideoCapture(int(device) if device.isdecimal() else device)
                if not self.capture.isOpened():
                    raise RuntimeError(f'Cannot open camera: {device}')
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.width)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height)
                self.capture.set(cv2.CAP_PROP_FPS, self.settings.fps)
            self.timer = self.create_timer(1.0 / self.settings.fps, self.publish_frame)
            self.get_logger().info(
                f'source={self.settings.source}, topic={self.publisher.topic_name}, '
                'QoS=BEST_EFFORT / VOLATILE / KEEP_LAST(1)')
        except Exception:
            self.destroy_node()
            raise

    def publish_frame(self):
        """Capture and timestamp a frame, then encode it as JPEG."""
        settings = self.settings
        if self.capture is None:
            frame = np.zeros((settings.height, settings.width, 3), dtype=np.uint8)
            position = self.sequence % settings.width
            frame[:, position:position + 10] = (0, 255, 0)
            cv2.putText(frame, f'ROS 2 camera test: {self.sequence}', (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        else:
            ok, frame = self.capture.read()
            if not ok or frame is None:
                self.read_failures += 1
                if self.read_failures == 1:
                    self.get_logger().warning('Camera read failed; retrying')
                if self.read_failures >= settings.max_read_failures:
                    raise RuntimeError('Camera read failure limit reached; check device')
                return
            self.read_failures = 0
        stamp = self.get_clock().now().to_msg()
        if frame.shape[:2] != (settings.height, settings.width):
            frame = cv2.resize(frame, (settings.width, settings.height))
        ok, encoded = cv2.imencode(
            '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality])
        if not ok:
            raise RuntimeError('JPEG encoding failed')
        message = CompressedImage()
        message.header.stamp = stamp
        message.header.frame_id = settings.frame_id
        message.format = 'bgr8; jpeg compressed bgr8'
        message.data = encoded.tobytes()
        self.publisher.publish(message)
        self.sequence += 1

    def destroy_node(self):
        """Release the camera on normal shutdown and startup errors."""
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        return super().destroy_node()


def main(args=None):
    """Start the camera publisher."""
    run_node(CameraPublisherNode, args)
