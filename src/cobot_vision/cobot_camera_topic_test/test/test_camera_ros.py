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

"""Exercise actual raw-image DDS traffic only in an explicitly isolated ROS test."""

import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


HAS_ROS = all(importlib.util.find_spec(name) is not None for name in ('rclpy', 'sensor_msgs'))
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
    from sensor_msgs.msg import Image

    from cobot_camera_topic_test.camera_publisher_node import CameraPublisherNode
    from cobot_camera_topic_test.camera_subscriber_node import CameraSubscriberNode


@unittest.skipUnless(HAS_ROS and ISOLATED, 'requires ROS and isolated opt-in')
class TestCameraRos(unittest.TestCase):
    """Test the synthetic source over DDS without vendor or imaging packages."""

    def setUp(self):
        """Create an independent ROS context without opening camera hardware."""
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

    def test_synthetic_roundtrip_and_qos(self):
        """Receive valid raw frames through actual Best Effort DDS endpoints."""
        topic = '/camera_test/image_raw'
        subscriber = self.add_node(CameraSubscriberNode, parameter_overrides=[
            Parameter('topic', value=topic),
        ])
        publisher = self.add_node(CameraPublisherNode, parameter_overrides=[
            Parameter('source', value='synthetic'), Parameter('topic', value=topic),
            Parameter('width', value=96), Parameter('height', value=64),
        ])
        deadline = time.monotonic() + 10.0
        while subscriber.total_frames < 3 and time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.1)
        self.assertGreaterEqual(subscriber.total_frames, 3)
        self.assertEqual(subscriber.last_shape, (64, 96))
        self.assertEqual(subscriber.invalid_frames, 0)
        self.assertIsNone(publisher.source)
        for qos in (publisher.publisher.qos_profile, subscriber.subscription.qos_profile):
            self.assertEqual(qos.reliability, ReliabilityPolicy.BEST_EFFORT)
            self.assertEqual(qos.durability, DurabilityPolicy.VOLATILE)
            self.assertEqual(qos.history, HistoryPolicy.KEEP_LAST)
            self.assertEqual(qos.depth, 1)

    def test_truncated_frame_does_not_count(self):
        """Reject a raw frame whose bytes do not match its shape."""
        subscriber = self.add_node(CameraSubscriberNode)
        message = Image(height=2, width=3, step=9, encoding='bgr8', data=bytes(17))
        subscriber.receive_frame(message)
        self.assertEqual(subscriber.total_frames, 0)
        self.assertEqual(subscriber.invalid_frames, 1)

    def test_namespaced_yaml_parameters(self):
        """Apply package settings to namespaced nodes without opening vendor hardware."""
        import yaml

        config = Path(__file__).resolve().parents[1] / 'config/camera.yaml'
        values = yaml.safe_load(config.read_text())
        parameters = values['/**/camera_publisher']['ros__parameters']
        parameters.update(source='synthetic', width=96)
        values['/**/camera_subscriber']['ros__parameters']['report_interval'] = 0.5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'camera.yaml'
            path.write_text(yaml.safe_dump(values))
            arguments = ['--ros-args', '--params-file', str(path)]
            publisher = self.add_node(CameraPublisherNode, cli_args=arguments)
            subscriber = self.add_node(CameraSubscriberNode, cli_args=arguments)
        self.assertEqual(publisher.settings.width, 96)
        self.assertEqual(subscriber.get_parameter('report_interval').value, 0.5)
        self.assertEqual(publisher.publisher.topic_name, '/camera/image_raw')

    def test_camera_start_failure_exits(self):
        """Propagate vendor startup errors after ROS node cleanup."""
        name = 'cobot_camera_topic_test.camera_publisher_node.PinkyCameraSource'
        with patch(name, side_effect=RuntimeError('vendor camera busy')):
            with self.assertRaisesRegex(RuntimeError, 'vendor camera busy'):
                CameraPublisherNode(context=self.context)
