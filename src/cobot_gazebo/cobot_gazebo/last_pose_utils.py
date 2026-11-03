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

"""
순찰 노드의 '마지막 위치' 파일을 시뮬 소환 위치로 다시 쓴다 (ROS 없는 순수 로직).

순찰 노드는 마지막 위치를 ~/.pinky_last_pose.json 에 저장하고, 첫 명령 때 그 위치를 AMCL 초기 위치로 낸다.
실물은 로봇마다 PC 가 따로라 괜찮지만 시뮬은 3대가 한 PC 에서 같은 파일을 쓰고, 지난 실행에서 남은 위치도 읽는다.
그러면 AMCL 이 엉뚱한 곳에서 시작해 위치를 못 잡는다. 그래서 launch 가 로봇마다 HOME 을 따로 주고
(sim_robot.launch.xml), 시뮬은 매번 홈에 소환되므로 띄울 때마다 그 파일을 소환 위치로 다시 쓴다.

실행: ros2 run cobot_gazebo reset_last_pose <home_dir> <x> <y> <yaw>
"""

import argparse
import json
import os

from rclpy.logging import get_logger

# cobot_pinky_patrol 의 POSE_FILE ('~/.pinky_last_pose.json') 과 같아야 한다
POSE_FILE_NAME = '.pinky_last_pose.json'


def write_last_pose(home_dir, x, y, yaw):
    """home_dir/.pinky_last_pose.json 에 위치를 쓰고 경로를 돌려준다. 폴더가 없으면 만든다."""
    os.makedirs(home_dir, exist_ok=True)
    path = os.path.join(home_dir, POSE_FILE_NAME)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'x': float(x), 'y': float(y), 'yaw': float(yaw)}, f)
    return path


def main(argv=None):
    """명령줄: 시뮬 로봇의 HOME 폴더와 소환 위치."""
    parser = argparse.ArgumentParser(description='순찰 노드 마지막 위치 파일을 소환 위치로 다시 쓴다')
    parser.add_argument('home_dir')
    parser.add_argument('x', type=float)
    parser.add_argument('y', type=float)
    parser.add_argument('yaw', type=float)
    # launch 의 executable 은 --ros-args 를 붙이지 않지만, ros2 run 으로 부를 때를 위해 모르는 인자는 버린다
    args, _ = parser.parse_known_args(argv)
    path = write_last_pose(args.home_dir, args.x, args.y, args.yaw)
    get_logger('reset_last_pose').info(f'{path}: ({args.x}, {args.y}, {args.yaw})')


if __name__ == '__main__':
    main()
