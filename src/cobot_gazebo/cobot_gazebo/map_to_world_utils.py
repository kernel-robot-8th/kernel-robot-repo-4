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
Nav2 지도(pgm + yaml)를 가제보 월드(SDF)로 바꾼다 (ROS 없는 순수 로직).

지도의 점유 셀을 벽 상자로 세운다. 셀 하나마다 상자를 만들면 1 cm 지도에서 수천 개가 되므로
가로로 이어진 셀을 한 줄로 묶고, 위아래 줄의 시작·끝이 같으면 하나의 직사각형으로 합친다.
월드 좌표 = 지도(map) 좌표라서 순찰 설정(config/pinkyN.yaml)의 지점이 그대로 맞는다.

실행: ros2 run cobot_gazebo make_world <map.yaml> <out.sdf> [--wall-height 0.25]
"""

import argparse
import os

from rclpy.logging import get_logger
import yaml

DEFAULT_WALL_HEIGHT_M = 0.25
WORLD_NAME = 'cobot_sim'


class MapFormatError(Exception):
    """지도 파일을 읽지 못함."""


def _pgm_tokens(data):
    """P5 머리말 토큰 4개(magic, 폭, 높이, 최대값)와 픽셀 시작 위치를 돌려준다. 주석(#)은 건너뛴다."""
    tokens, i = [], 0
    while len(tokens) < 4:
        while i < len(data) and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b'#':
            while i < len(data) and data[i:i + 1] not in (b'\n', b'\r'):
                i += 1
            continue
        start = i
        while i < len(data) and not data[i:i + 1].isspace():
            i += 1
        if start == i:
            raise MapFormatError('pgm 머리말이 끝나기 전에 파일이 끝남')
        tokens.append(data[start:i])
    return tokens, i + 1   # 최대값 뒤 공백 한 칸 다음부터 픽셀


def read_pgm(data):
    """바이너리 P5 pgm 을 읽어 (폭, 높이, 최대값, 픽셀 bytes) 를 돌려준다. 행 0 이 이미지 맨 위."""
    tokens, offset = _pgm_tokens(data)
    if tokens[0] != b'P5':
        raise MapFormatError(f'P5(바이너리) pgm 만 지원: {tokens[0]!r}')
    width, height, maxval = (int(t) for t in tokens[1:])
    if maxval > 255:
        raise MapFormatError('16비트 pgm 은 지원하지 않음')
    pixels = data[offset:offset + width * height]
    if len(pixels) != width * height:
        raise MapFormatError(f'픽셀 수가 모자람: {len(pixels)} / {width * height}')
    return width, height, maxval, pixels


def occupied_mask(pixels, maxval, occupied_thresh, negate=0):
    """
    map_server 와 같은 규칙으로 점유 셀을 고른다. mask[i] = True 면 벽.

    negate=0 일 때 점유 확률 = (maxval - 값) / maxval. 이 값이 occupied_thresh 를 넘으면 점유.
    """
    mask = []
    for p in pixels:
        occ = p / maxval if negate else (maxval - p) / maxval
        mask.append(occ > occupied_thresh)
    return mask


def merge_rectangles(mask, width, height):
    """
    점유 셀을 직사각형으로 합친다. [(col0, row0, col1, row1)] (끝 포함) 를 돌려준다.

    한 줄의 연속 구간을 찾고, 바로 윗줄에서 열린 같은 구간(col0, col1)이 있으면 아래로 늘린다.
    """
    done, open_runs = [], {}
    for row in range(height):
        runs, col = [], 0
        while col < width:
            if mask[row * width + col]:
                start = col
                while col + 1 < width and mask[row * width + col + 1]:
                    col += 1
                runs.append((start, col))
            col += 1
        next_open = {}
        for run in runs:
            row0 = open_runs.pop(run, row)
            next_open[run] = row0
        for (c0, c1), row0 in open_runs.items():
            done.append((c0, row0, c1, row - 1))
        open_runs = next_open
    for (c0, c1), row0 in open_runs.items():
        done.append((c0, row0, c1, height - 1))
    return sorted(done, key=lambda r: (r[1], r[0]))


def rect_to_box(rect, height, resolution, origin):
    """직사각형(셀 번호)을 map 좌표의 (중심 x, 중심 y, 크기 x, 크기 y) [m] 로 바꾼다."""
    c0, r0, c1, r1 = rect
    size_x = (c1 - c0 + 1) * resolution
    size_y = (r1 - r0 + 1) * resolution
    # 이미지 행 0 이 맨 위(최대 y), origin 은 왼쪽 아래 셀의 모서리
    cx = origin[0] + (c0 + c1 + 1) / 2.0 * resolution
    cy = origin[1] + (height - (r0 + r1 + 1) / 2.0) * resolution
    return cx, cy, size_x, size_y


def _box_xml(index, box, wall_height):
    cx, cy, sx, sy = box
    geom = f'<geometry><box><size>{sx:.4f} {sy:.4f} {wall_height:.3f}</size></box></geometry>'
    pose = f'<pose>{cx:.4f} {cy:.4f} {wall_height / 2.0:.4f} 0 0 0</pose>'
    return (f'        <collision name="c{index}">{pose}{geom}</collision>\n'
            f'        <visual name="v{index}">{pose}{geom}'
            '<material><ambient>0.45 0.45 0.5 1</ambient><diffuse>0.6 0.6 0.65 1</diffuse>'
            '</material></visual>\n')


def boxes_to_sdf(boxes, wall_height=DEFAULT_WALL_HEIGHT_M, source=''):
    """벽 상자 목록으로 월드 SDF 문자열을 만든다. 라이다를 쓰려면 Sensors(ogre2) 시스템이 필요하다."""
    walls = ''.join(_box_xml(i, b, wall_height) for i, b in enumerate(boxes))
    plane = '<geometry><plane><normal>0 0 1</normal><size>20 20</size></plane></geometry>'
    floor = ('<material><ambient>0.85 0.85 0.8 1</ambient>'
             '<diffuse>0.85 0.85 0.8 1</diffuse></material>')
    return f"""<?xml version="1.0"?>
<!-- make_world 로 생성 ({source}). 손으로 고치지 말고 지도를 바꾼 뒤 다시 만든다. -->
<sdf version="1.9">
  <world name="{WORLD_NAME}">
    <physics name="1ms" type="ignored">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <direction>-0.3 0.2 -0.9</direction>
    </light>
    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="c">{plane}</collision>
        <visual name="v">{plane}{floor}</visual>
      </link>
    </model>
    <model name="map_walls">
      <static>true</static>
      <link name="walls">
{walls}      </link>
    </model>
  </world>
</sdf>
"""


def map_yaml_to_sdf(map_yaml_path, wall_height=DEFAULT_WALL_HEIGHT_M):
    """지도 yaml 경로를 받아 (SDF 문자열, 상자 수) 를 돌려준다."""
    with open(map_yaml_path, encoding='utf-8') as f:
        meta = yaml.safe_load(f)
    image = os.path.join(os.path.dirname(map_yaml_path), meta['image'])
    with open(image, 'rb') as f:
        width, height, maxval, pixels = read_pgm(f.read())
    mask = occupied_mask(pixels, maxval, float(meta.get('occupied_thresh', 0.65)),
                         int(meta.get('negate', 0)))
    rects = merge_rectangles(mask, width, height)
    res, origin = float(meta['resolution']), [float(v) for v in meta['origin'][:2]]
    boxes = [rect_to_box(r, height, res, origin) for r in rects]
    return boxes_to_sdf(boxes, wall_height, os.path.basename(map_yaml_path)), len(boxes)


def main(argv=None):
    """명령줄: 지도 yaml → 월드 sdf 파일."""
    parser = argparse.ArgumentParser(description='Nav2 지도를 가제보 월드로 바꾼다')
    parser.add_argument('map_yaml')
    parser.add_argument('out_sdf')
    parser.add_argument('--wall-height', type=float, default=DEFAULT_WALL_HEIGHT_M)
    args = parser.parse_args(argv)
    sdf, count = map_yaml_to_sdf(args.map_yaml, args.wall_height)
    with open(args.out_sdf, 'w', encoding='utf-8') as f:
        f.write(sdf)
    get_logger('make_world').info(f'{args.out_sdf}: 벽 상자 {count}개')


if __name__ == '__main__':
    main()
