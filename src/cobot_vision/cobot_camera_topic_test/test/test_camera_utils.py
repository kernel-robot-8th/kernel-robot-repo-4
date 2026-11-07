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

"""Test camera settings, image validation, JPEG conversion and timing."""

from dataclasses import replace
import unittest

from cobot_camera_topic_test.camera_utils import (
    CameraSettings, frame_payload, jpeg_payload, jpeg_shape, StreamStats,
    synthetic_payload, transport_topic, validate_image,
)
import cv2
import numpy as np


class TestCameraSettings(unittest.TestCase):
    """Reject invalid parameters before touching hardware."""

    def test_supported_sources(self):
        """Accept the vendor camera and the standard-library test pattern."""
        for source in ('pinky', 'synthetic'):
            self.assertEqual(CameraSettings(source=source).validate().source, source)

    def test_invalid_parameters(self):
        """Reject USB source names, invalid dimensions, rates and pixel encodings."""
        invalid = [
            {'source': 'camera'}, {'source': 'unknown'}, {'width': 0}, {'height': -1},
            {'width': True}, {'fps': 0.0}, {'fps': -1.0}, {'fps': float('inf')},
            {'fps': float('nan')}, {'encoding': 'jpeg'}, {'frame_id': ' '},
            {'max_read_failures': 0},
            {'jpeg_quality': 0}, {'jpeg_quality': 101}, {'jpeg_quality': True},
            {'jpeg_quality': 85.0}, {'transport': 'unknown'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CameraSettings(), **changes).validate()


class TestJpegImages(unittest.TestCase):
    """Exercise the actual JPEG codec and ROS topic naming."""

    def test_topic_selection(self):
        """Keep raw and compressed message types on distinct topic names."""
        self.assertEqual(transport_topic('/camera/image_raw', 'raw'), '/camera/image_raw')
        self.assertEqual(transport_topic('image/', 'compressed'), 'image/compressed')
        for topic, transport in [('', 'raw'), ('/', 'raw'), ('image', 'jpeg'),
                                 ('image/compressed', 'compressed')]:
            with self.subTest(topic=topic, transport=transport), self.assertRaises(ValueError):
                transport_topic(topic, transport)

    def test_roundtrip_color_and_dimensions(self):
        """Preserve dimensions and convert each supported pixel order correctly."""
        for encoding, pixel in [('bgr8', [0, 0, 255]), ('rgb8', [255, 0, 0]),
                                ('bgra8', [0, 0, 255, 255]),
                                ('rgba8', [255, 0, 0, 255]), ('mono8', [200])]:
            with self.subTest(encoding=encoding):
                frame = np.tile(np.array(pixel, dtype=np.uint8), (48, 64, 1))
                width, height, step, data = frame_payload(frame, encoding)
                image_format, jpeg = jpeg_payload(width, height, step, encoding, data, 85)
                self.assertEqual(jpeg_shape(image_format, jpeg), (48, 64))
                decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                expected = [200, 200, 200] if encoding == 'mono8' else [0, 0, 255]
                np.testing.assert_allclose(decoded[20, 20], expected, atol=3)
                self.assertLess(len(jpeg), len(data))

    def test_quality_changes_payload(self):
        """Use the requested quality rather than a fixed codec setting."""
        frame = np.random.default_rng(42).integers(0, 256, (64, 96, 3), dtype=np.uint8)
        width, height, step, data = frame_payload(frame, 'bgr8')
        _, low = jpeg_payload(width, height, step, 'bgr8', data, 20)
        _, high = jpeg_payload(width, height, step, 'bgr8', data, 95)
        self.assertLess(len(low), len(high))

    def test_corrupt_image(self):
        """Reject empty, mislabeled, truncated and undecodable JPEG payloads."""
        for image_format, data in [('jpeg', b''), ('png', b'\xff\xd8\xff\xd9'),
                                   ('jpeg', b'\xff\xd8bad'),
                                   ('jpeg', b'\xff\xd8bad\xff\xd9')]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                jpeg_shape(image_format, data)


class TestRawImages(unittest.TestCase):
    """Validate real payload layout rather than compressed image headers."""

    def test_padded_row(self):
        """Accept valid ROS row padding."""
        validate_image(2, 2, 8, 'rgb8', bytes(16))

    def test_invalid_payload(self):
        """Reject truncation, short strides and unknown encodings."""
        for width, height, step, encoding, data in [
            (2, 2, 6, 'rgb8', bytes(11)), (2, 2, 5, 'rgb8', bytes(10)),
            (0, 2, 6, 'rgb8', bytes(12)), (2, 2, 6, 'unknown', bytes(12)),
        ]:
            with self.subTest(encoding=encoding, step=step), self.assertRaises(ValueError):
                validate_image(width, height, step, encoding, data)

    def test_synthetic_pattern(self):
        """Produce valid, changing patterns for every supported channel layout."""
        for encoding in ('mono8', 'bgr8', 'rgb8', 'bgra8', 'rgba8'):
            first = synthetic_payload(32, 16, encoding, 0)
            second = synthetic_payload(32, 16, encoding, 1)
            width, height, step, data = first
            validate_image(width, height, step, encoding, data)
            self.assertNotEqual(data, second[3])

    def test_vendor_array_payload(self):
        """Preserve bytes and dimensions supplied by the vendor array protocol."""
        class Frame:
            shape = (2, 3, 3)
            dtype = 'uint8'

            def tobytes(self):
                return bytes(range(18))

        width, height, step, data = frame_payload(Frame(), 'bgr8')
        self.assertEqual((width, height, step), (3, 2, 9))
        self.assertEqual(data, bytes(range(18)))
        with self.assertRaises(ValueError):
            frame_payload(Frame(), 'mono8')
        Frame.dtype = 'float32'
        with self.assertRaises(ValueError):
            frame_payload(Frame(), 'bgr8')


class TestStreamStats(unittest.TestCase):
    """Keep receive rates independent of sender timestamps and clock sync."""

    def test_rates_and_window_reset(self):
        """Calculate rates over the actual interval and clear the next window."""
        stats = StreamStats(10.0)
        stats.record(1024)
        stats.record(3072)
        self.assertEqual(stats.sample(12.0), (2, 1.0, 2.0))
        self.assertEqual(stats.sample(14.0), (0, 0.0, 0.0))

    def test_invalid_measurement_time(self):
        """Preserve pending counts when time does not advance."""
        stats = StreamStats(10.0)
        stats.record(1024)
        with self.assertRaises(ValueError):
            stats.sample(10.0)
        self.assertEqual(stats.sample(11.0), (1, 1.0, 1.0))
