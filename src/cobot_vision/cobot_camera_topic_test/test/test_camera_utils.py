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

"""Test raw image validation and timing without ROS or imaging libraries."""

from dataclasses import replace
import unittest

from cobot_camera_topic_test.camera_utils import (
    CameraSettings, frame_payload, StreamStats, synthetic_payload, validate_image,
)


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
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CameraSettings(), **changes).validate()


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
