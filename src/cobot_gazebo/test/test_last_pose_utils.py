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

import glob
import json
import os

from cobot_gazebo.last_pose_utils import POSE_FILE_NAME, write_last_pose
import pytest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATROL_SRC = os.path.join(PKG, '..', 'cobot_navigation', 'cobot_pinky_patrol',
                          'cobot_pinky_patrol')


def test_write_creates_dir_and_overwrites(tmp_path):
    home = tmp_path / 'pinky2'
    write_last_pose(str(home), 0.6, 0.5, -1.3)
    path = write_last_pose(str(home), 0.0, -0.2, 0.0)
    with open(path, encoding='utf-8') as f:
        assert json.load(f) == {'x': 0.0, 'y': -0.2, 'yaw': 0.0}


def test_file_name_matches_patrol_node():
    """순찰 노드가 읽는 파일 이름이 바뀌면 시뮬 초기화가 조용히 안 먹으므로 원본과 맞는지 본다."""
    sources = glob.glob(os.path.join(PATROL_SRC, 'pinky_patrol_node_pinky*.py'))
    if not sources:
        pytest.skip('cobot_pinky_patrol 소스가 이 워크스페이스에 없음')
    for src in sources:
        with open(src, encoding='utf-8') as f:
            assert f"'~/{POSE_FILE_NAME}'" in f.read(), src
