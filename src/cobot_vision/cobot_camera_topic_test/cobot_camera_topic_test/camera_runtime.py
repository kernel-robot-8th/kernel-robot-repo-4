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

"""Provide sensor QoS and consistent ROS process cleanup."""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


def camera_qos():
    """Prefer the latest frame on both endpoints without retransmission."""
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )


def run_node(factory, args=None):
    """Run a camera node and release its resources on shutdown or failure."""
    rclpy.init(args=args)
    node = None
    failed = False
    try:
        node = factory()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as error:
        rclpy.logging.get_logger('camera_test').error(str(error))
        failed = True
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
    if failed:
        raise SystemExit(1)
