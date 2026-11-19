"""현재 주행 설정을 기존 control-center 지도·지점 검사 입력으로 내보낸다."""

from copy import deepcopy
import json
import math
from pathlib import Path
import re

import yaml


def read_parameters(path):
    """ROS 파라미터 파일을 읽되 다른 기능 패키지의 Python 코드를 가져오지 않는다."""
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError(f'노드 하나의 ROS 설정 파일이 필요합니다: {path}')
    node = next(iter(data.values()))
    if not isinstance(node, dict) or not isinstance(node.get('ros__parameters'), dict):
        raise ValueError(f'ros__parameters가 없습니다: {path}')
    return node['ros__parameters']


def merge_parameters(base, extra):
    """launch가 읽는 공통·현장·로봇 프로필 순서를 유지한다."""
    result = deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_parameters(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class PointRules:
    """웹 수동 요청의 지점을 실제 주행 설정에서 검증한다."""

    def __init__(self, configs, zone_keepout_m=0.0):
        self.configs = configs
        # 관제 웨이포인트(poses)가 구역 지점·출구에서 이만큼 [m] 안이면 거절 (구역 토큰 우회 방지).
        # 구역이 다각형이 아니라 지점이라 거리로만 막는다. 관제(cobot_control_center)도 같은 값으로 저장을 막는다.
        # 기본 0 = 검사 안 함 (2026-11-18, 관제 기록이 너무 자주 막혀 끔).
        self.zone_keepout_m = float(zone_keepout_m)

    def home(self, robot):
        """로봇 홈 지점 이름과 (x, y, yaw). 순찰 노드가 쓰는 같은 설정이 정본이다."""
        if robot not in self.configs:
            raise ValueError('로봇 지점 설정이 없습니다')
        params = self.configs[robot]
        name = params['home_name']
        pose = [float(v) for v in params['points'][name]]
        # 지점은 [x, y] 또는 [x, y, yaw]. yaw 가 없으면 지도 +x 방향(0)으로 본다.
        x, y, yaw = (pose + [0.0])[:3]
        return name, x, y, yaw

    def validate(self, robot, operation, points, poses=None):
        """
        수동 요청의 지점을 검사한다. poses 는 관제 웨이포인트 좌표 {이름: (x, y, yaw)} (goto 만).

        poses 이름은 이 로봇 설정에 없어야 하고, 구역 지점·출구에서 zone_keepout_m 밖이어야 한다.
        """
        if robot not in self.configs:
            raise ValueError('로봇 지점 설정이 없습니다')
        params = self.configs[robot]
        all_points = params['points']
        zones = {p for names in params['zone_points'].values() for p in names}
        poses = poses or {}
        if poses and operation != 'goto':
            raise ValueError('관제 웨이포인트 좌표는 goto 에만 쓸 수 있습니다')
        for name, pose in poses.items():
            if name in all_points:
                raise ValueError(f'관제 웨이포인트 이름이 로봇 설정과 겹칩니다: {name}')
            near = self.near_zone(robot, pose[0], pose[1])
            if near:
                raise ValueError(f'관제 웨이포인트 {name} 이 구역 지점 {near} 에 너무 가깝습니다 '
                                 f'({self.zone_keepout_m:g} m 안, 구역은 zone 명령으로)')
        if any(point not in all_points and point not in poses for point in points):
            raise ValueError('등록되지 않은 지점')
        if operation == 'zone' and any(point not in zones for point in points):
            raise ValueError('zone은 구역 지점만 허용합니다')
        if operation == 'goto':
            for point in points:
                if point in zones:
                    raise ValueError('구역 지점은 zone 명령을 사용하세요')
                if point in poses:
                    continue
                if point != params['home_name'] and not re.fullmatch(r'P[0-9]+', point):
                    raise ValueError('goto는 일반 지점과 자신의 홈만 허용합니다')
                if point.startswith('P') and all(float(v) == 0 for v in all_points[point]):
                    raise ValueError('미실측 예비 지점은 사용할 수 없습니다')

    def near_zone(self, robot, x, y):
        """구역 지점·출구에서 zone_keepout_m 안이면 그 지점 이름, 아니면 '' 를 돌려준다."""
        params = self.configs[robot]
        names = [p for members in params['zone_points'].values() for p in members]
        names += [f'Z{zone}_EXIT' for zone in params['zone_points']]   # 순찰 노드 exit_name 과 같은 규칙
        for name in names:
            pose = params['points'].get(name)
            if pose and math.hypot(float(pose[0]) - x, float(pose[1]) - y) < self.zone_keepout_m:
                return name
        return ''


def load_profiles(config_dir, site, robots):
    """현장 파일을 정본으로 삼아 웹용 평탄화 프로필을 구성한다."""
    if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', site):
        raise ValueError('site 이름 형식 오류')
    root = Path(config_dir)
    common = read_parameters(root / 'common.yaml')
    site_params = read_parameters(root / 'sites' / (site + '.yaml'))
    configs = {}
    for robot in robots:
        if not isinstance(robot, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', robot):
            raise ValueError('robot_id 형식 오류')
        params = merge_parameters(common, site_params)
        params = merge_parameters(params, read_parameters(root / 'robots' / (robot + '.yaml')))
        if (params.get('robot_id') != robot
                or params.get('home_name') not in params.get('points', {})):
            raise ValueError('로봇 ID·홈 지점 설정 불일치')
        for pose in params['points'].values():
            if (not isinstance(pose, list) or len(pose) not in (2, 3)
                    or any(isinstance(v, bool) or not isinstance(v, (float, int))
                           or not math.isfinite(v) for v in pose)):
                raise ValueError('지점 좌표는 유한한 수치 2~3개여야 합니다')
        if not isinstance(params.get('zone_points'), dict):
            raise ValueError('zone_points 설정 필요')
        configs[robot] = params
    return PointRules(configs)


def export_profiles(config_dir, site, robots, output_dir):
    """레거시 웹 백엔드의 <points_dir>/<robot>.yaml 입력을 자동 생성한다."""
    rules = load_profiles(config_dir, site, robots)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for robot, params in rules.configs.items():
        text = yaml.safe_dump({'pinky_patrol_node': {'ros__parameters': params}},
                              allow_unicode=True, sort_keys=False)
        path = output / (robot + '.yaml')
        temporary = output / (robot + '.yaml.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(path)
    (output / 'manifest.json').write_text(json.dumps(
        {'source_config_dir': str(Path(config_dir).resolve()), 'site': site,
         'robots': list(robots)}, ensure_ascii=False), encoding='utf-8')
    return rules
