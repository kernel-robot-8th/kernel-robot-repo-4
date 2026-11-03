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

"""Validate camera settings and measure throughput without ROS dependencies."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CameraSettings:
    """Startup settings shared by real and synthetic sources."""

    source: str = 'synthetic'
    device: str = '/dev/video0'
    width: int = 640
    height: int = 480
    fps: float = 10.0
    jpeg_quality: int = 75
    frame_id: str = 'camera_optical_frame'
    max_read_failures: int = 30

    def validate(self):
        """Reject invalid settings before opening a device or creating a timer."""
        if self.source not in ('camera', 'synthetic'):
            raise ValueError('source must be camera or synthetic')
        for name in ('width', 'height', 'max_read_failures'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError('fps must be finite and positive')
        if type(self.jpeg_quality) is not int or not 1 <= self.jpeg_quality <= 100:
            raise ValueError('jpeg_quality must be an integer from 1 to 100')
        if not self.device.strip() or not self.frame_id.strip():
            raise ValueError('device and frame_id must not be empty')
        return self


class StreamStats:
    """Measure successfully decoded frames using local monotonic time."""

    def __init__(self, now):
        """Start an empty measurement window."""
        self.started = now
        self.frames = 0
        self.bytes = 0

    def record(self, size):
        """Record one valid received frame."""
        self.frames += 1
        self.bytes += size

    def sample(self, now):
        """Return count, frames/s and KiB/s, then reset the measurement window."""
        elapsed = now - self.started
        if elapsed <= 0:
            raise ValueError('measurement time must advance')
        result = (self.frames, self.frames / elapsed, self.bytes / elapsed / 1024)
        self.started = now
        self.frames = 0
        self.bytes = 0
        return result
