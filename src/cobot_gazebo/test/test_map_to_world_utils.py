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

import os
import xml.etree.ElementTree as ET

from cobot_gazebo.map_to_world_utils import (map_yaml_to_sdf, MapFormatError, merge_rectangles,
                                             occupied_mask, read_pgm, rect_to_box)
import pytest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_YAML = os.path.join(PKG, 'config', 'map', 'cobot_map_v9.yaml')


def _pgm(rows, header=b'P5\n'):
    h, w = len(rows), len(rows[0])
    return header + f'{w} {h}\n255\n'.encode() + bytes(v for row in rows for v in row)


def test_read_pgm_with_comment():
    data = _pgm([[0, 254]], header=b'P5\n# made by slam\n')
    assert read_pgm(data) == (2, 1, 255, bytes([0, 254]))


def test_read_pgm_rejects_ascii_and_short():
    with pytest.raises(MapFormatError):
        read_pgm(b'P2\n1 1\n255\n0')
    with pytest.raises(MapFormatError):
        read_pgm(b'P5\n2 2\n255\n\x00')


def test_occupied_mask_follows_map_server_rule():
    # 0 = 점유, 254 = 빈 곳, 205 = 모름 (trinary)
    assert occupied_mask(bytes([0, 254, 205]), 255, 0.65) == [True, False, False]
    assert occupied_mask(bytes([0, 254]), 255, 0.65, negate=1) == [False, True]


def test_merge_rectangles_l_shape():
    # ##.
    # ##.
    # ###
    mask = [True, True, False,
            True, True, False,
            True, True, True]
    rects = merge_rectangles(mask, 3, 3)
    assert rects == [(0, 0, 1, 1), (0, 2, 2, 2)]
    covered = {(c, r) for c0, r0, c1, r1 in rects
               for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
    assert covered == {(i % 3, i // 3) for i, m in enumerate(mask) if m}


def test_rect_to_box_flips_rows_to_map_y():
    # 높이 10 셀, 해상도 0.1, origin (-1, -2). 맨 윗줄 왼쪽 셀 하나
    cx, cy, sx, sy = rect_to_box((0, 0, 0, 0), 10, 0.1, (-1.0, -2.0))
    assert (sx, sy) == pytest.approx((0.1, 0.1))
    assert cx == pytest.approx(-0.95)
    assert cy == pytest.approx(-2.0 + 0.95)


def test_v9_world_matches_committed_file():
    """worlds/ 의 월드는 지도에서 다시 만든 것과 같아야 한다 (지도만 바꾸고 잊는 것 방지)."""
    sdf, count = map_yaml_to_sdf(MAP_YAML)
    assert count > 0
    ET.fromstring(sdf)
    with open(os.path.join(PKG, 'worlds', 'cobot_map_v9.sdf'), encoding='utf-8') as f:
        assert f.read() == sdf
