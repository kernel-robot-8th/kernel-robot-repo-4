"""천장 카메라 픽셀을 로봇 map 좌표로 바꾼다. 확신할 수 없으면 좌표를 내지 않는다."""

import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

from cobot_amcl_corrector.vision_ingest import transform_xy
import numpy as np
import yaml

POINTS = ('center', 'bottom_center')
FRAME_MODES = {'v9': 'identity', 'canonical': 'canonical_to_v9'}
MIN_REFERENCES = 4
MEASURED = 'MEASURED'
REQUIRED = ('camera_id', 'image_size', 'plane_height_m', 'reference', 'limits', 'classes',
            'homography', 'check_error_m', 'sha256')


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _pair(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(item) for item in value))


def _normalizer(points):
    """평균 거리가 √2가 되도록 옮긴다. 픽셀과 미터의 크기 차이로 해가 흔들리는 것을 막는다."""
    center = points.mean(axis=0)
    spread = np.linalg.norm(points - center, axis=1).mean()
    if spread < 1e-12:
        raise ValueError('기준점이 한 점에 모여 있습니다')
    scale = math.sqrt(2.0) / spread
    return np.array([[scale, 0.0, -scale * center[0]], [0.0, scale, -scale * center[1]],
                     [0.0, 0.0, 1.0]])


def solve_homography(pixels, maps):
    """4개 이상 대응점으로 픽셀→map 호모그래피를 구한다."""
    source = np.asarray(pixels, dtype=float)
    target = np.asarray(maps, dtype=float)
    if len(source) < MIN_REFERENCES or source.shape != target.shape:
        raise ValueError('대응점은 4개 이상이고 픽셀과 map 수가 같아야 합니다')
    from_pixel, from_map = _normalizer(source), _normalizer(target)
    rows = []
    for (u, v), (x, y) in zip(_apply(from_pixel, source), _apply(from_map, target)):
        rows.append([-u, -v, -1.0, 0.0, 0.0, 0.0, u * x, v * x, x])
        rows.append([0.0, 0.0, 0.0, -u, -v, -1.0, u * y, v * y, y])
    _, singular, vectors = np.linalg.svd(np.asarray(rows))
    # 해 공간이 한 차원보다 넓으면 점이 한 직선에 놓인 경우다.
    if singular[7] < 1e-9 * singular[0]:
        raise ValueError('기준점이 한 직선에 가까워 호모그래피를 정할 수 없습니다')
    homography = np.linalg.inv(from_map) @ vectors[-1].reshape(3, 3) @ from_pixel
    if abs(homography[2, 2]) < 1e-12 or abs(np.linalg.det(homography)) < 1e-15:
        raise ValueError('호모그래피가 퇴화했습니다')
    return (homography / homography[2, 2]).tolist()


def _apply(matrix, points):
    stacked = np.column_stack([points, np.ones(len(points))]) @ matrix.T
    return stacked[:, :2] / stacked[:, 2:3]


def project(homography, pixel):
    """픽셀 한 점을 기준면 map 좌표로 바꾼다. 무한대로 가면 None이다."""
    u, v = pixel
    x, y, w = (row[0] * u + row[1] * v + row[2] for row in homography)
    if abs(w) < 1e-12:
        return None
    result = (x / w, y / w)
    return result if all(math.isfinite(value) for value in result) else None


def lift(point, height_m, calibration):
    """기준면에서 읽은 점을 실제 높이의 위치로 옮긴다. 시선은 카메라에서 곧게 뻗는다."""
    plane = calibration['plane_height_m']
    if height_m == plane:
        return point
    camera = calibration.get('camera')
    if not camera:
        return None
    x, y = camera['map_xy']
    scale = (camera['height_m'] - height_m) / (camera['height_m'] - plane)
    return (x + (point[0] - x) * scale, y + (point[1] - y) * scale)


def digest(calibration):
    """측정값 전체의 지문을 만든다. 손으로 고친 파일을 쓰지 않기 위해서다."""
    body = {key: value for key, value in calibration.items() if key != 'sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode('utf-8')).hexdigest()


def _to_v9(xy, mode):
    return list(transform_xy(xy[0], xy[1], mode))


def _validate_measured(measured):
    if measured.get('frame') not in FRAME_MODES:
        raise ValueError('frame: v9 또는 canonical')
    if not _pair(measured.get('image_size')) or min(measured['image_size']) <= 0:
        raise ValueError('image_size: [폭, 높이] 필요')
    if not _number(measured.get('plane_height_m')):
        raise ValueError('plane_height_m 필요')
    limits = measured.get('limits') or {}
    if not all(_number(limits.get(key)) and limits[key] > 0 for key in (
            'min_markers', 'max_marker_shift_px', 'max_check_error_m')):
        raise ValueError('limits의 세 값은 사용자가 정한 양수여야 합니다')
    if not measured.get('check_points'):
        raise ValueError('check_points 필요: 마커가 아닌 지점으로 검증합니다')


def build_calibration(measured):
    """측정값에서 보정 파일 내용을 만든다. 검증점 오차가 상한을 넘으면 만들지 않는다."""
    _validate_measured(measured)
    mode = FRAME_MODES[measured['frame']]
    reference = [{'id': int(row['id']), 'pixel': [float(value) for value in row['pixel']],
                  'map': _to_v9(row['map'], mode)} for row in measured.get('reference') or []]
    calibration = {
        'status': MEASURED, 'camera_id': measured['camera_id'], 'frame': 'v9',
        'image_size': list(measured['image_size']),
        'plane_height_m': measured['plane_height_m'], 'reference': reference,
        'limits': dict(measured['limits']), 'classes': dict(measured.get('classes') or {}),
        'camera': None,
    }
    if measured.get('camera'):
        camera = measured['camera']
        if camera['height_m'] <= max(row.get('height_m') or 0.0 for row in
                                     calibration['classes'].values()):
            raise ValueError('카메라 높이는 물체 높이보다 높아야 합니다')
        calibration['camera'] = {'map_xy': _to_v9(camera['map_xy'], mode),
                                 'height_m': camera['height_m']}
    homography = solve_homography([row['pixel'] for row in reference],
                                  [row['map'] for row in reference])
    calibration['homography'] = homography
    errors = []
    for row in measured['check_points']:
        point = lift(project(homography, row['pixel']), row['height_m'], calibration)
        if point is None:
            raise ValueError('검증점을 계산할 수 없습니다: 높이가 다르면 camera 필요')
        errors.append(math.dist(point, _to_v9(row['map'], mode)))
    calibration['check_error_m'] = max(errors)
    if calibration['check_error_m'] > measured['limits']['max_check_error_m']:
        raise ValueError(f"검증점 오차 {calibration['check_error_m']:.3f} m가 상한을 넘습니다")
    calibration['sha256'] = digest(calibration)
    return calibration


def load_calibration(path):
    """파일을 읽는다. 없거나 깨져도 멈추지 않고 좌표를 내지 않는 상태로 둔다."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as error:
        return {'status': 'UNREADABLE', 'detail': str(error)}
    return data if isinstance(data, dict) else {'status': 'UNREADABLE', 'detail': '형식 오류'}


def calibration_problem(calibration):
    """쓸 수 없는 이유를 돌려준다. 쓸 수 있으면 빈 문자열이다."""
    if calibration.get('status') != MEASURED:
        return '보정값 없음: ' + str(calibration.get('status'))
    missing = [key for key in REQUIRED if calibration.get(key) is None]
    if missing:
        return '보정값 누락: ' + ', '.join(missing)
    if calibration['sha256'] != digest(calibration):
        return '보정값 지문 불일치'
    return ''


def marker_problem(calibration, observed):
    """고정한 호모그래피가 지금 화면에도 맞는지 기준 마커로 확인한다."""
    if not isinstance(observed, dict):
        return '기준 마커 관측 없음'
    limits = calibration['limits']
    seen = [row for row in calibration['reference'] if str(row['id']) in observed]
    if len(seen) < limits['min_markers']:
        return f'기준 마커 부족: {len(seen)}개'
    for row in seen:
        pixel = observed[str(row['id'])]
        if not _pair(pixel):
            return f"기준 마커 {row['id']} 값 오류"
        if math.dist(pixel, row['pixel']) > limits['max_marker_shift_px']:
            return f"기준 마커 {row['id']} 이동"
    return ''


def _bbox_point(bbox, name):
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2 if name == 'bottom_center' else (y1 + y2) / 2.0)


def to_map(calibration, vision_class, bbox, image_size, markers):
    """
    검출 상자 하나를 map 좌표로 바꾼다.

    :return: ((x, y) 또는 None, 좌표를 못 낸 이유)
    """
    problem = calibration_problem(calibration)
    if problem:
        return None, problem
    if list(image_size or ()) != calibration['image_size']:
        return None, '프레임 크기 불일치'
    width, height = calibration['image_size']
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
            or not all(_number(value) for value in bbox)
            or not 0 <= bbox[0] < bbox[2] <= width or not 0 <= bbox[1] < bbox[3] <= height):
        return None, 'bbox 오류'
    rule = calibration['classes'].get(vision_class) or {}
    if rule.get('point') not in POINTS or not _number(rule.get('height_m')):
        return None, f'클래스 기준 없음: {vision_class}'
    problem = marker_problem(calibration, markers)
    if problem:
        return None, problem
    point = project(calibration['homography'], _bbox_point(bbox, rule['point']))
    if point is None:
        return None, '투영 실패'
    point = lift(point, rule['height_m'], calibration)
    return (point, '') if point else (None, '카메라 위치 없음')


def to_vision_event(raw, calibration):
    """
    검출 한 건을 판정 입력 이벤트로 바꾼다. 위치를 못 내도 이벤트는 그대로 낸다.

    :param raw: stream_id, event_type, confidence, timestamp, bbox, image_size,
                reference_markers. bbox와 마커 좌표는 image_size 원본 프레임 픽셀이다.
    :return: (이벤트, 좌표를 못 낸 이유)
    """
    if not isinstance(raw, dict):
        raise ValueError('검출은 JSON 객체')
    for name in ('stream_id', 'event_type'):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ValueError(f'{name} 필요')
    if raw['stream_id'] == calibration.get('camera_id'):
        point, reason = to_map(calibration, raw['event_type'], raw.get('bbox'),
                               raw.get('image_size'), raw.get('reference_markers'))
    else:
        point, reason = None, '다른 카메라의 보정값'
    x, y = point or (None, None)
    return {'event_id': raw.get('event_id') or uuid.uuid4().hex, 'camera_id': raw['stream_id'],
            'vision_class': raw['event_type'], 'confidence': raw.get('confidence', 0.0),
            'detected_at': raw.get('timestamp'), 'zone_id': '', 'map_x': x, 'map_y': y,
            'bbox': raw.get('bbox')}, reason


def main(args=None):
    """측정 파일로 보정 파일을 만든다."""
    args = sys.argv[1:] if args is None else args
    if len(args) != 2:
        print('사용법: build_camera_calibration <측정 yaml> <보정 yaml>', file=sys.stderr)
        return 2
    measured = yaml.safe_load(Path(args[0]).read_text(encoding='utf-8'))
    calibration = build_calibration(measured)
    Path(args[1]).write_text(yaml.safe_dump(calibration, allow_unicode=True, sort_keys=False),
                             encoding='utf-8')
    print(f"검증점 최대 오차 {calibration['check_error_m']:.4f} m, "
          f"지문 {calibration['sha256'][:16]}")
    return 0
