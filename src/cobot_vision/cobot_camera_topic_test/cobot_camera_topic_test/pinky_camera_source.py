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

"""Use the Camera lifecycle documented by pinky_pro's official Pinky Pro guide."""

from importlib import import_module


class PinkyCameraSource:
    """Adapt the robot's existing pinkylib.Camera without replacing its driver."""

    def __init__(self):
        """Open the vendor camera using Camera() and start()."""
        self.camera = None
        try:
            factory = import_module('pinkylib').Camera
        except (ImportError, AttributeError) as error:
            raise RuntimeError(
                'pinkylib.Camera is unavailable in this Python environment. '
                'Use the Pinky Pro vendor environment; do not install unrelated camera packages. '
                'For PC tests use source:=synthetic.') from error
        try:
            self.camera = factory()
            self.camera.start()
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def read(self):
        """Return a frame through the documented get_frame() API."""
        return self.camera.get_frame()

    def close(self):
        """Release the vendor camera exactly once."""
        if self.camera is not None:
            camera, self.camera = self.camera, None
            camera.close()
