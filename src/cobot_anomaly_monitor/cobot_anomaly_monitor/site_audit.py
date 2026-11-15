"""gate67 정본 맵에 순찰 지점과 구역 대기 슬롯 중심을 겹쳐 검사한다."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image
import yaml


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def audit(map_path, site_path, queue_path, offset):
    config = read_yaml(map_path)
    origin_x, origin_y, yaw = config['origin']
    if config['mode'] != 'trinary' or yaw != 0:
        raise ValueError('축이 회전하지 않은 trinary 지도만 지원합니다')
    points = read_yaml(site_path)['pinky_patrol_node']['ros__parameters']['points']
    queues = read_yaml(queue_path)['zone_manager_node']['ros__parameters']
    locations = {name: pose[:2] for name, pose in points.items()}
    for zone in queues['zone_names']:
        queue = queues['zone_' + zone]
        x, y = queue['queue_anchor'][:2]
        dx, dy = queue['queue_back_dir']
        norm = math.hypot(dx, dy)
        if not norm:
            raise ValueError(f'{zone} 대기 방향이 0입니다')
        for k in range(queues['queue_max']):
            distance = k * queues['queue_spacing'] / norm
            locations[f'queue_{zone}_{k}'] = (x + distance * dx, y + distance * dy)

    missing = sorted(set('I1 I2 I3 ZA ZB ZC ZA_EXIT ZB_EXIT ZC_EXIT'.split()) - points.keys())
    blocked = {}
    with Image.open(map_path.parent / config['image']) as source:
        pixels = source.convert('L')
        for name, (x, y) in locations.items():
            x, y = x + offset[0], y + offset[1]
            col = math.floor((x - origin_x) / config['resolution'])
            row = pixels.height - 1 - math.floor((y - origin_y) / config['resolution'])
            if not (0 <= col < pixels.width and 0 <= row < pixels.height):
                reason = 'OUTSIDE'
            else:
                gray = pixels.getpixel((col, row)) / 255
                occupancy = gray if config['negate'] else 1 - gray
                if occupancy < config['free_thresh']:
                    continue
                reason = 'OCCUPIED' if occupancy > config['occupied_thresh'] else 'UNKNOWN'
            blocked[name] = dict(x=round(x, 4), y=round(y, 4), reason=reason)
    return dict(checked_centers=len(locations), offset=list(offset), missing=missing, blocked=blocked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('map', 'site', 'queues'):
        parser.add_argument('--' + option, type=Path, required=True)
    parser.add_argument('--offset', nargs=2, type=float, default=(0, 0), metavar=('DX', 'DY'))
    args = parser.parse_args()
    report = audit(args.map, args.site, args.queues, args.offset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report['blocked'] or report['missing']))


if __name__ == '__main__':
    raise SystemExit(main())
