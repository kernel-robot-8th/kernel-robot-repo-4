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

"""Check the documented vendor camera lifecycle without opening hardware."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cobot_camera_topic_test.pinky_camera_source import PinkyCameraSource


MODULE = 'cobot_camera_topic_test.pinky_camera_source.import_module'


class TestPinkyCameraSource(unittest.TestCase):
    """Use start, get_frame and close exactly as the Pinky Pro guide specifies."""

    def test_vendor_lifecycle(self):
        """Keep the vendor frame intact and close the camera once."""
        camera = Mock()
        frame = object()
        camera.get_frame.return_value = frame
        factory = Mock(return_value=camera)
        with patch(MODULE, return_value=SimpleNamespace(Camera=factory)) as module:
            source = PinkyCameraSource()
            self.assertIs(source.read(), frame)
            source.close()
            source.close()
        module.assert_called_once_with('pinkylib')
        factory.assert_called_once_with()
        camera.start.assert_called_once_with()
        camera.get_frame.assert_called_once_with()
        camera.close.assert_called_once_with()

    def test_missing_vendor_environment(self):
        """Fail clearly without trying to install or replace any camera package."""
        with patch(MODULE, side_effect=ModuleNotFoundError('pinkylib')):
            with self.assertRaisesRegex(RuntimeError, 'vendor environment'):
                PinkyCameraSource()

    def test_failed_start_closes_camera(self):
        """Release hardware if the vendor start call raises an error."""
        camera = Mock()
        camera.start.side_effect = RuntimeError('camera busy')
        with patch(MODULE, return_value=SimpleNamespace(Camera=lambda: camera)):
            with self.assertRaisesRegex(RuntimeError, 'camera busy'):
                PinkyCameraSource()
        camera.close.assert_called_once_with()

    def test_cleanup_preserves_start_error(self):
        """Keep the startup error visible even if closing an unstarted camera fails."""
        camera = Mock()
        camera.start.side_effect = RuntimeError('camera busy')
        camera.close.side_effect = RuntimeError('not started')
        with patch(MODULE, return_value=SimpleNamespace(Camera=lambda: camera)):
            with self.assertRaisesRegex(RuntimeError, 'camera busy'):
                PinkyCameraSource()
