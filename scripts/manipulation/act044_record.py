# Copyright 2026 HeoJiHyeok
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

"""Run upstream LeRobot 0.4.4 recording with an optional pre-inference Init move."""

import argparse
from importlib.metadata import version
import sys

from act044_init import install_init_pose
import act044_current_robot  # noqa: F401  Register the 7-input robot before upstream argument parsing.


def main():
    """Validate initialization, install the local hook, and invoke upstream recording."""
    if version("lerobot") != "0.4.4":
        raise ValueError("This entry point requires LeRobot 0.4.4")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--init-pose-file")
    parser.add_argument("--init-pose-duration", type=float, default=3.0)
    args, remaining = parser.parse_known_args()
    if args.init_pose_file:
        install_init_pose(args.init_pose_file, args.init_pose_duration)
    sys.argv = [sys.argv[0], *remaining]
    from lerobot.scripts.lerobot_record import main as record_main

    record_main()


if __name__ == "__main__":
    main()
