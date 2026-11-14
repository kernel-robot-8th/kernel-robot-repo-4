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
매장 배치 파일(cobot_bringup/config/store_layout.yaml)을 읽는다 (보조 A 고객 주문).

ROS 없이 돈다. 선반 행 수, 열 -> 웨이포인트, 자리 QR 위치 ID -> 이름·웨이포인트.
cobot_gui 의 customer_gateway_utils.load_locations 도 같은 파일의 locations 를 읽는다
(패키지끼리 import 하지 않아서 읽는 코드를 따로 둔다, CLAUDE.md §3-6).
"""

import re

import yaml

_ID_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')


class StoreLayout:
    """선반과 자리 배치."""

    def __init__(self, rows, columns, locations):
        """rows: 행 수. columns: {열 번호: 웨이포인트}. locations: {위치 ID: {name, waypoint}}."""
        self.rows = int(rows)
        self.columns = dict(columns)
        self.locations = dict(locations)

    def has_slot(self, row, col):
        """(행, 열) 칸이 선반에 있는가."""
        return 1 <= row <= self.rows and col in self.columns

    def column_waypoint(self, col):
        """열 앞 정차 웨이포인트. 없는 열이면 ''."""
        return self.columns.get(col, '')

    def location_waypoints(self):
        """{위치 ID: 배송 웨이포인트}."""
        return {loc: info['waypoint'] for loc, info in self.locations.items()}


def load_store_layout(path):
    """배치 YAML 을 읽고 검사한다. 틀리면 ValueError."""
    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}
    return parse_store_layout(data)


def parse_store_layout(data):
    """배치 dict 를 검사해 StoreLayout 으로 바꾼다. 틀리면 ValueError."""
    errors = []
    shelf = data.get('shelf') or {}
    rows = shelf.get('rows')
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        errors.append('shelf.rows 는 1 이상의 정수여야 한다: {!r}'.format(rows))
    columns = {}
    for col, waypoint in (shelf.get('columns') or {}).items():
        if isinstance(col, bool) or not isinstance(col, int) or col < 1:
            errors.append('shelf.columns 의 열 번호는 1 이상의 정수여야 한다: {!r}'.format(col))
        elif not waypoint or not _ID_RE.match(str(waypoint)):
            errors.append('{}열의 웨이포인트가 비었거나 형식이 아니다: {!r}'.format(col, waypoint))
        else:
            columns[col] = str(waypoint)
    if not columns:
        errors.append('shelf.columns 가 비었다')

    locations = {}
    for loc, info in (data.get('locations') or {}).items():
        if not _ID_RE.match(str(loc)):
            errors.append('위치 ID 형식이 아니다: {!r}'.format(loc))
            continue
        if not isinstance(info, dict) or not info.get('waypoint'):
            errors.append('locations.{} 에 waypoint 가 없다'.format(loc))
            continue
        locations[str(loc)] = {'name': str(info.get('name') or loc),
                               'waypoint': str(info['waypoint'])}
    if errors:
        raise ValueError('; '.join(errors))
    return StoreLayout(rows, columns, locations)
