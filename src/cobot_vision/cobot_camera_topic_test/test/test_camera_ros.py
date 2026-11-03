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

"""Exercise real DDS and JPEG decoding only in an explicitly isolated ROS test."""

import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


HAS_ROS = all(importlib.util.find_spec(name) is not None for name in (
    'rclpy', 'sensor_msgs', 'cv2', 'numpy'))
ISOLATED = (
    os.environ.get('ROS_DOMAIN_ID') == '100'
    and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'
    and os.environ.get('CAMERA_TOPIC_TEST_ROS') == '1'
)
if HAS_ROS:
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.parameter import Parameter
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
    from sensor_msgs.msg import CompressedImage

    from cobot_camera_topic_test.camera_publisher_node import CameraPublisherNode
    from cobot_camera_topic_test.camera_subscriber_node import CameraSubscriberNode


@unittest.skipUnless(HAS_ROS and ISOLATED, 'requires ROS, OpenCV and isolated opt-in')
class TestCameraRos(unittest.TestCase):
    """Check frames across actual ROS publishers and subscribers."""

    def setUp(self):
        """Create an independent ROS context without starting camera hardware."""
        self.context = Context()
        rclpy.init(context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.nodes = []

    def tearDown(self):
        """Release all test nodes even when an assertion fails."""
        self.executor.shutdown()
        for node in reversed(self.nodes):
            node.destroy_node()
        self.context.try_shutdown()

    def add_node(self, factory, **kwargs):
        """Register a node for executor processing and cleanup."""
        node = factory(context=self.context, namespace='camera_test', **kwargs)
        self.nodes.append(node)
        self.executor.add_node(node)
        return node

    def spin_until(self, condition):
        """Wait for DDS discovery and callbacks within a bounded interval."""
        deadline = time.monotonic() + 10.0
        while not condition() and time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.1)
        self.assertTrue(condition(), 'No valid image arrived within 10 seconds')

    def test_synthetic_roundtrip_and_qos(self):
        """Decode multiple JPEG frames received through Best Effort DDS endpoints."""
        subscriber = self.add_node(CameraSubscriberNode)
        publisher = self.add_node(CameraPublisherNode, parameter_overrides=[
            Parameter('width', value=96), Parameter('height', value=64),
        ])
        self.spin_until(lambda: subscriber.total_frames >= 3)
        self.assertEqual(subscriber.last_shape, (64, 96))
        self.assertEqual(subscriber.invalid_frames, 0)
        self.assertIsNone(publisher.capture)
        for qos in (publisher.publisher.qos_profile, subscriber.subscription.qos_profile):
            self.assertEqual(qos.reliability, ReliabilityPolicy.BEST_EFFORT)
            self.assertEqual(qos.durability, DurabilityPolicy.VOLATILE)
            self.assertEqual(qos.history, HistoryPolicy.KEEP_LAST)
            self.assertEqual(qos.depth, 1)

    def test_corrupted_frame_does_not_count(self):
        """Reject an invalid payload without crashing the subscriber."""
        subscriber = self.add_node(CameraSubscriberNode)
        for data in (b'', b'not-a-jpeg'):
            message = CompressedImage()
            message.data = data
            subscriber.receive_frame(message)
        self.assertEqual(subscriber.total_frames, 0)
        self.assertEqual(subscriber.invalid_frames, 2)

    def test_namespaced_yaml_parameters(self):
        """Apply the package's wildcard selectors to namespaced nodes."""
        import yaml

        config = Path(__file__).resolve().parents[1] / 'config/camera.yaml'
        values = yaml.safe_load(config.read_text())
        values['/**/camera_publisher']['ros__parameters']['width'] = 96
        values['/**/camera_subscriber']['ros__parameters']['report_interval'] = 0.5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'camera.yaml'
            path.write_text(yaml.safe_dump(values))
            arguments = ['--ros-args', '--params-file', str(path)]
            publisher = self.add_node(CameraPublisherNode, cli_args=arguments)
            subscriber = self.add_node(CameraSubscriberNode, cli_args=arguments)
        self.assertEqual(publisher.settings.width, 96)
        self.assertEqual(subscriber.get_parameter('report_interval').value, 0.5)
        self.assertEqual(publisher.publisher.topic_name,
                         '/camera_test/camera/image_raw/compressed')

    def test_unavailable_camera_is_released(self):
        """Fail startup and release a camera that cannot be opened."""
        with patch('cobot_camera_topic_test.camera_publisher_node.cv2.VideoCapture') as capture:
            capture.return_value.isOpened.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'Cannot open camera'):
                CameraPublisherNode(context=self.context, parameter_overrides=[
                    Parameter('source', value='camera'),
                ])
            capture.return_value.release.assert_called_once()
