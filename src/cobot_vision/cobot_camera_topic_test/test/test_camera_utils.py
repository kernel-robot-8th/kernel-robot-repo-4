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

"""Test parameter failures and receive-rate calculations without ROS."""

from dataclasses import replace
import unittest

from cobot_camera_topic_test.camera_utils import CameraSettings, StreamStats


class TestCameraSettings(unittest.TestCase):
    """Reject settings that cannot produce a valid timer or frame."""

    def test_default_and_camera_sources(self):
        """Accept the two supported source modes."""
        for source in ('synthetic', 'camera'):
            self.assertEqual(CameraSettings(source=source).validate().source, source)

    def test_invalid_parameters(self):
        """Reject invalid sizes, rates, encodings and identifiers."""
        invalid = [
            {'source': 'unknown'}, {'width': 0}, {'height': -1}, {'width': True},
            {'fps': 0.0}, {'fps': -1.0}, {'fps': float('inf')}, {'fps': float('nan')},
            {'jpeg_quality': 0}, {'jpeg_quality': 101}, {'jpeg_quality': 75.5},
            {'device': ''}, {'frame_id': ' '}, {'max_read_failures': 0},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CameraSettings(), **changes).validate()


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
