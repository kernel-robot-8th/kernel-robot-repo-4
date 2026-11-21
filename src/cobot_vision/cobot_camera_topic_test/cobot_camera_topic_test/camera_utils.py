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

"""Validate camera settings, encode JPEG images and measure receive throughput."""

from dataclasses import dataclass
import math


CHANNELS = {'mono8': 1, 'bgr8': 3, 'rgb8': 3, 'bgra8': 4, 'rgba8': 4}


@dataclass(frozen=True)
class CameraSettings:
    """Startup settings for Pinky's existing camera API or a hardware-free pattern."""

    source: str = 'pinky'
    width: int = 640
    height: int = 480
    fps: float = 10.0
    encoding: str = 'bgr8'
    frame_id: str = 'front_camera_link'
    max_read_failures: int = 30
    jpeg_quality: int = 85
    transport: str = 'compressed'

    def validate(self):
        """Reject invalid settings before opening a camera or creating a timer."""
        if self.source not in ('pinky', 'synthetic'):
            raise ValueError('source must be pinky or synthetic')
        if self.transport not in ('compressed', 'raw'):
            raise ValueError('transport must be compressed or raw')
        if type(self.jpeg_quality) is not int or not 1 <= self.jpeg_quality <= 100:
            raise ValueError('jpeg_quality must be an integer from 1 to 100')
        for name in ('width', 'height', 'max_read_failures'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError('fps must be finite and positive')
        if self.encoding not in CHANNELS:
            raise ValueError('encoding must be mono8, bgr8, rgb8, bgra8 or rgba8')
        if not self.frame_id.strip():
            raise ValueError('frame_id must not be empty')
        return self


def transport_topic(topic, transport):
    """Resolve a base image topic to the selected ROS image transport."""
    if transport not in ('compressed', 'raw'):
        raise ValueError('transport must be compressed or raw')
    if not isinstance(topic, str) or not topic.strip() or not topic.rstrip('/'):
        raise ValueError('topic must be a nonempty base image topic')
    topic = topic.rstrip('/')
    if topic.endswith('/compressed'):
        raise ValueError('topic must be the base topic without /compressed')
    return f'{topic}/compressed' if transport == 'compressed' else topic


def jpeg_payload(width, height, step, encoding, data, quality):
    """Encode vendor pixels as JPEG while preserving the actual frame dimensions."""
    import cv2
    import numpy as np

    validate_image(width, height, step, encoding, data)
    channels = CHANNELS[encoding]
    frame = np.ndarray((height, width, channels), dtype=np.uint8,
                       buffer=data, strides=(step, channels, 1))
    conversions = {
        'rgb8': cv2.COLOR_RGB2BGR,
        'bgra8': cv2.COLOR_BGRA2BGR,
        'rgba8': cv2.COLOR_RGBA2BGR,
    }
    if encoding in conversions:
        frame = cv2.cvtColor(frame, conversions[encoding])
    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError('JPEG encoding failed')
    pixels = 'mono8' if channels == 1 else 'bgr8'
    return f'{pixels}; jpeg compressed {pixels}', encoded.tobytes()


def jpeg_shape(image_format, data):
    """Decode JPEG to reject corrupt frames and return the received dimensions."""
    import cv2
    import numpy as np

    if ('jpeg' not in image_format.lower() or len(data) < 4
            or bytes(data[:2]) != b'\xff\xd8' or bytes(data[-2:]) != b'\xff\xd9'):
        raise ValueError('Expected a complete JPEG image')
    try:
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error as error:
        raise ValueError('JPEG decoding failed') from error
    if frame is None:
        raise ValueError('JPEG decoding failed')
    return frame.shape[:2]


def validate_image(width, height, step, encoding, data):
    """Check 8-bit image dimensions, row padding and payload length."""
    for name, value in (('width', width), ('height', height), ('step', step)):
        if type(value) is not int or value <= 0:
            raise ValueError(f'{name} must be a positive integer')
    channels = CHANNELS.get(encoding)
    if channels is None:
        raise ValueError(f'Unsupported image encoding: {encoding}')
    if step < width * channels or len(data) != height * step:
        raise ValueError('Image payload length or row stride does not match dimensions')


def frame_payload(frame, encoding):
    """Pack the uint8 array returned by pinkylib without importing OpenCV or NumPy."""
    shape = tuple(frame.shape)
    channels = CHANNELS.get(encoding)
    if channels is None:
        raise ValueError(f'Unsupported image encoding: {encoding}')
    expected_channels = shape[2] if len(shape) == 3 else 1
    if len(shape) not in (2, 3) or expected_channels != channels:
        raise ValueError('Camera frame shape does not match encoding')
    if str(frame.dtype) != 'uint8':
        raise ValueError('Camera frame must contain uint8 pixels')
    height, width = int(shape[0]), int(shape[1])
    data = frame.tobytes()
    step = width * channels
    validate_image(width, height, step, encoding, data)
    return width, height, step, data


def synthetic_payload(width, height, encoding, sequence):
    """Make a moving stripe using only Python's standard library."""
    channels = CHANNELS[encoding]
    row = bytearray(width * channels)
    for pixel in range(sequence % width, min(sequence % width + 10, width)):
        start = pixel * channels
        if channels == 1:
            row[start] = 255
        else:
            row[start + 1] = 255
        if channels == 4:
            row[start + 3] = 255
    if channels == 4:
        row[3::4] = bytes([255]) * width
    return width, height, width * channels, bytes(row) * height


class StreamStats:
    """Measure valid frames using local monotonic time."""

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
