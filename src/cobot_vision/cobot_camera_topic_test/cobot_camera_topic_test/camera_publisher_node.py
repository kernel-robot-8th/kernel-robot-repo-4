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

"""Publish Pinky Pro camera frames as raw ROS images using Best Effort QoS."""

from dataclasses import fields

from rclpy.node import Node
from sensor_msgs.msg import Image

from cobot_camera_topic_test.camera_runtime import camera_qos, run_node
from cobot_camera_topic_test.camera_utils import CameraSettings, frame_payload, synthetic_payload
from cobot_camera_topic_test.pinky_camera_source import PinkyCameraSource


class CameraPublisherNode(Node):
    """Wrap Pinky's existing camera API in the official camera topic contract."""

    def __init__(self, **kwargs):
        """Validate startup parameters before opening the vendor camera."""
        super().__init__('camera_publisher', **kwargs)
        self.source = None
        try:
            defaults = CameraSettings()
            values = {
                field.name: self.declare_parameter(
                    field.name, getattr(defaults, field.name)).value
                for field in fields(defaults)
            }
            self.settings = CameraSettings(**values).validate()
            topic = self.declare_parameter('topic', '/camera/image_raw').value
            self.publisher = self.create_publisher(Image, topic, camera_qos())
            self.sequence = 0
            self.read_failures = 0
            if self.settings.source == 'pinky':
                self.source = PinkyCameraSource()
            self.timer = self.create_timer(1.0 / self.settings.fps, self.publish_frame)
            self.get_logger().info(
                f'source={self.settings.source}, topic={self.publisher.topic_name}, '
                'QoS=BEST_EFFORT / VOLATILE / KEEP_LAST(1)')
        except Exception:
            self.destroy_node()
            raise

    def publish_frame(self):
        """Read a vendor frame or build a pattern and publish an uncompressed image."""
        settings = self.settings
        if self.source is None:
            width, height, step, data = synthetic_payload(
                settings.width, settings.height, settings.encoding, self.sequence)
        else:
            frame = self.source.read()
            if frame is None:
                self.read_failures += 1
                if self.read_failures == 1:
                    self.get_logger().warning('pinkylib returned no frame; retrying')
                if self.read_failures >= settings.max_read_failures:
                    raise RuntimeError('Camera read failure limit reached; check vendor camera')
                return
            self.read_failures = 0
            width, height, step, data = frame_payload(frame, settings.encoding)
        message = Image()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = settings.frame_id
        message.height = height
        message.width = width
        message.encoding = settings.encoding
        message.is_bigendian = 0
        message.step = step
        message.data = data
        self.publisher.publish(message)
        self.sequence += 1

    def destroy_node(self):
        """Close the vendor camera on shutdown and startup errors."""
        if self.source is not None:
            try:
                self.source.close()
            except Exception as error:
                self.get_logger().warning(f'Camera cleanup failed: {error}')
            self.source = None
        return super().destroy_node()


def main(args=None):
    """Start the Pinky Pro camera topic publisher."""
    run_node(CameraPublisherNode, args)
