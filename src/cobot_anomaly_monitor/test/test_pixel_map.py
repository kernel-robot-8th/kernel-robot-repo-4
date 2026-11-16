"""픽셀→map 변환 시험. 틀린 좌표가 조용히 나가면 실패해야 한다."""

import math

from cobot_anomaly_monitor.judgment import judge
from cobot_anomaly_monitor.pixel_map import (
    build_calibration, calibration_problem, digest, load_calibration, main, marker_problem,
    project, solve_homography, to_map, to_vision_event, undistort)
import numpy as np
import pytest
import yaml

SIZE = [1280, 720]
CENTER = (0.5, -0.5)
CAMERA_HEIGHT = 2.0
CORNERS = {40: (-1.0, 1.0), 41: (2.0, 1.0), 42: (2.0, -2.0), 43: (-1.0, -2.0)}
LIMITS = {'min_markers': 2, 'max_marker_shift_px': 5.0, 'max_check_error_m': 0.02}
ROTATION = np.array([[0.9962, 0.0, 0.0872], [0.0, -1.0, 0.0], [0.0872, 0.0, -0.9962]])
LENS = {'fx': 640.0, 'fy': 620.0, 'cx': 640.0, 'cy': 360.0, 'k1': -0.03, 'k2': -0.04}
FLAT = dict(LENS, k1=0.0, k2=0.0)
SPREAD = [(-0.3, 0.4), (1.3, 0.4), (1.3, -1.4), (-0.3, -1.4)]
ZONES = [{'name': 'ZA', 'map': [1.3, 0.2]}, {'name': 'ZC', 'map': [-0.2, -1.2]}]


def distort(lens, x, y):
    r2 = x * x + y * y
    scale = 1.0 + lens['k1'] * r2 + lens['k2'] * r2 * r2
    return [float(lens['fx'] * x * scale + lens['cx']),
            float(lens['fy'] * y * scale + lens['cy'])]


def pixel_of(x, y, z=0.0, lens=LENS):
    """시험 전용 카메라. 현장 값이 아니고 기울어지고 왜곡이 있는 렌즈를 흉내 낸다."""
    ray = ROTATION @ np.array([x - CENTER[0], y - CENTER[1], z - CAMERA_HEIGHT])
    return distort(lens, ray[0] / ray[2], ray[1] / ray[2])


def check_points(height=0.0):
    return [{'pixel': pixel_of(*xy, height), 'map': list(xy), 'height_m': height}
            for xy in SPREAD]


def measured(**changes):
    data = {
        'camera_id': 'CAM', 'image_size': SIZE, 'frame': 'v9', 'plane_height_m': 0.0,
        'lens': dict(LENS), 'required_zones': ZONES,
        'reference': [{'id': key, 'pixel': pixel_of(*xy), 'map': list(xy)}
                      for key, xy in CORNERS.items()],
        'check_points': check_points(), 'limits': dict(LIMITS),
        'camera': {'map_xy': list(CENTER), 'height_m': CAMERA_HEIGHT},
        'classes': {'box_on_floor': {'height_m': 0.0225},
                    'box_perched_on_rim': {'height_m': 0.2},
                    'lid_detached': {'height_m': None}},
    }
    data.update(changes)
    return data


def markers():
    return {str(key): pixel_of(*xy) for key, xy in CORNERS.items()}


def box(u, v, half=10.0):
    return [u - half, v - half, u + half, v + half]


def floor_box(x, y):
    """시험 상자의 bbox. 중심이 바닥 상자 중심 높이에 온다."""
    return box(*pixel_of(x, y, 0.0225))


@pytest.fixture
def calibration():
    return build_calibration(measured())


def test_round_trip_with_known_camera(calibration):
    for xy in [(0.0, 0.0), (1.3, -0.7), (-0.4, 0.6)]:
        ideal = undistort(LENS, pixel_of(*xy))
        assert project(calibration['homography'], ideal) == pytest.approx(xy, abs=1e-3)


def test_undistort_inverts_the_lens_model():
    for x, y in [(0.0, 0.0), (0.3, -0.2), (-0.6, 0.5), (0.8, 0.1)]:
        ideal = undistort(LENS, distort(LENS, x, y))
        assert ideal == pytest.approx(distort(FLAT, x, y), abs=1e-4)


def test_flat_lens_changes_nothing():
    assert undistort(FLAT, (700.0, 100.0)) == pytest.approx((700.0, 100.0))


def test_pixels_past_the_fold_of_the_lens_model_have_no_answer():
    assert undistort(LENS, (1279.0, 1.0)) is None


def test_homography_alone_would_miss_the_lens_error():
    corners = list(CORNERS.values())
    homography = solve_homography([pixel_of(*xy) for xy in corners], corners)
    errors = [math.dist(project(homography, pixel_of(*xy)), xy) for xy in SPREAD + [(1.0, 0.4)]]
    assert max(errors) > 0.03
    calibration = build_calibration(measured())
    fixed = [math.dist(project(calibration['homography'], undistort(LENS, pixel_of(*xy))), xy)
             for xy in SPREAD + [(1.0, 0.4)]]
    assert max(fixed) < 0.001


def test_wrong_lens_is_caught_by_spread_check_points():
    with pytest.raises(ValueError, match='상한'):
        build_calibration(measured(lens=dict(FLAT)))


def test_central_check_point_alone_is_refused():
    central = [{'pixel': pixel_of(*CENTER), 'map': list(CENTER), 'height_m': 0.0}]
    with pytest.raises(ValueError, match='사분면'):
        build_calibration(measured(check_points=central))


def test_every_required_zone_needs_a_check_point():
    far = ZONES + [{'name': 'ZB', 'map': [0.5, 0.9]}]
    with pytest.raises(ValueError, match='ZB'):
        build_calibration(measured(required_zones=far))


def test_template_zones_match_the_site_file():
    from pathlib import Path
    package = Path(__file__).resolve().parents[1]
    template = yaml.safe_load(
        (package / 'config/camera_measurement_template.yaml').read_text('utf-8'))
    site = yaml.safe_load((package.parent / 'cobot_navigation/cobot_pinky_patrol/config/sites'
                           / 'lab.yaml').read_text('utf-8'))
    points = site['pinky_patrol_node']['ros__parameters']['points']
    assert {row['name'] for row in template['required_zones']} == {'ZA', 'ZB', 'ZC'}
    for row in template['required_zones']:
        assert row['map'] == points[row['name']][:2]


def test_box_center_at_half_height_lands_on_the_box():
    calibration = build_calibration(measured())
    for x, y in [(1.4, 0.5), (-0.3, 0.5), (1.4, -1.4), (-0.3, -1.4), (0.5, -0.5)]:
        corners = [pixel_of(x + dx, y + dy, dz) for dx in (-0.03, 0.03) for dy in (-0.03, 0.03)
                   for dz in (0.0, 0.045)]
        bbox = [min(p[0] for p in corners), min(p[1] for p in corners),
                max(p[0] for p in corners), max(p[1] for p in corners)]
        point, reason = to_map(calibration, 'box_on_floor', bbox, SIZE, markers())
        assert reason == '' and math.dist(point, (x, y)) < 0.01, (x, y)


def test_more_points_than_needed_still_solve():
    points = [(x, y) for x in (-1.0, 0.0, 1.0) for y in (-1.0, 0.0, 1.0)]
    homography = solve_homography([pixel_of(*p, lens=FLAT) for p in points], points)
    assert project(homography, pixel_of(0.5, 0.5, lens=FLAT)) == pytest.approx((0.5, 0.5),
                                                                               abs=1e-3)


@pytest.mark.parametrize('points', [
    [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
    [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
])
def test_degenerate_references_are_refused(points):
    with pytest.raises(ValueError):
        solve_homography(points, points)


def test_three_references_are_refused():
    with pytest.raises(ValueError, match='4개'):
        solve_homography([(0, 0), (1, 0), (0, 1)], [(0, 0), (1, 0), (0, 1)])


def test_raised_point_matches_the_true_camera_model(calibration):
    u, v = pixel_of(1.0, 0.4, 0.2)
    point, reason = to_map(calibration, 'box_perched_on_rim', box(u, v), SIZE, markers())
    assert reason == '' and point == pytest.approx((1.0, 0.4), abs=1e-3)


def test_raised_point_is_wrong_without_height_correction(calibration):
    ideal = undistort(LENS, pixel_of(1.0, 0.4, 0.2))
    assert math.dist(project(calibration['homography'], ideal), (1.0, 0.4)) > 0.05


def test_marker_plane_above_the_floor_is_corrected():
    high = {key: pixel_of(*xy, 0.1) for key, xy in CORNERS.items()}
    data = measured(
        plane_height_m=0.1,
        reference=[{'id': key, 'pixel': high[key], 'map': list(CORNERS[key])} for key in high])
    observed = {str(key): value for key, value in high.items()}
    point, reason = to_map(build_calibration(data), 'box_on_floor', floor_box(1.0, 0.4), SIZE,
                           observed)
    assert reason == '' and point == pytest.approx((1.0, 0.4), abs=1e-3)


def test_floor_class_uses_the_box_center(calibration):
    point, _ = to_map(calibration, 'box_on_floor', floor_box(1.0, 0.4), SIZE, markers())
    assert point == pytest.approx((1.0, 0.4), abs=1e-3)


def test_canonical_measurements_become_v9_map_coordinates():
    shift = (1.415, 1.639)
    data = measured(
        frame='canonical',
        reference=[{'id': key, 'pixel': pixel_of(*xy), 'map': [xy[0] + shift[0], xy[1] + shift[1]]}
                   for key, xy in CORNERS.items()],
        check_points=[dict(row, map=[row['map'][0] + shift[0], row['map'][1] + shift[1]])
                      for row in check_points()],
        camera={'map_xy': [CENTER[0] + shift[0], CENTER[1] + shift[1]],
                'height_m': CAMERA_HEIGHT})
    built = build_calibration(data)
    assert built['frame'] == 'v9' and built['camera']['map_xy'] == pytest.approx(list(CENTER))
    ideal = undistort(LENS, pixel_of(1.0, 0.4))
    assert project(built['homography'], ideal) == pytest.approx((1.0, 0.4), abs=1e-3)


def test_bad_check_point_stops_the_build():
    wrong = check_points()
    wrong[0] = dict(wrong[0], map=[wrong[0]['map'][0] + 0.1, wrong[0]['map'][1]])
    with pytest.raises(ValueError, match='상한'):
        build_calibration(measured(check_points=wrong))


@pytest.mark.parametrize('changes', [
    {'frame': None}, {'frame': 'map'}, {'image_size': None}, {'plane_height_m': None},
    {'check_points': []}, {'required_zones': []}, {'lens': None},
    {'lens': dict(LENS, k2=None)}, {'lens': dict(LENS, fx=0.0)},
    {'limits': dict(LIMITS, max_check_error_m=None)},
    {'limits': dict(LIMITS, min_markers=None)}, {'limits': dict(LIMITS, max_marker_shift_px=0)},
])
def test_missing_measurements_stop_the_build(changes):
    with pytest.raises(ValueError):
        build_calibration(measured(**changes))


def test_check_point_at_another_height_needs_the_camera():
    with pytest.raises(ValueError, match='camera'):
        build_calibration(measured(check_points=check_points(0.2), camera=None))


def test_pending_file_gives_no_position(tmp_path):
    path = tmp_path / 'c.yaml'
    path.write_text('status: PENDING\n', encoding='utf-8')
    point, reason = to_map(load_calibration(path), 'box_on_floor', box(100, 100), SIZE, markers())
    assert point is None and 'PENDING' in reason


def test_shipped_calibration_stays_pending():
    from pathlib import Path
    config = Path(__file__).resolve().parents[1] / 'config'
    assert load_calibration(config / 'camera_calibration.yaml') == {'status': 'PENDING'}
    template = yaml.safe_load((config / 'camera_measurement_template.yaml').read_text('utf-8'))
    assert template['limits'] == {'min_markers': None, 'max_marker_shift_px': None,
                                  'max_check_error_m': None}
    assert template['camera'] is None and template['lens'] is None
    assert template['reference'] == []
    assert all(row['height_m'] is None for row in template['classes'].values())
    with pytest.raises(ValueError):
        build_calibration(template)


def test_missing_or_broken_file_gives_no_position(tmp_path):
    assert calibration_problem(load_calibration(tmp_path / 'none.yaml'))
    broken = tmp_path / 'b.yaml'
    broken.write_text('a: [', encoding='utf-8')
    assert calibration_problem(load_calibration(broken))


def test_saved_file_passes_and_a_hand_edit_is_caught(tmp_path, calibration):
    path = tmp_path / 'c.yaml'
    path.write_text(yaml.safe_dump(calibration, allow_unicode=True), encoding='utf-8')
    loaded = load_calibration(path)
    assert calibration_problem(loaded) == '' and digest(loaded) == calibration['sha256']
    loaded['homography'][0][2] += 0.01
    point, reason = to_map(loaded, 'box_on_floor', floor_box(1.0, 0.4), SIZE, markers())
    assert point is None and reason == '보정값 지문 불일치'


def test_build_command_writes_a_usable_file(tmp_path, capsys):
    source, target = tmp_path / 'm.yaml', tmp_path / 'c.yaml'
    source.write_text(yaml.safe_dump(measured()), encoding='utf-8')
    assert main([str(source), str(target)]) == 0
    assert calibration_problem(load_calibration(target)) == ''
    assert '지문' in capsys.readouterr().out
    assert main([]) == 2


def test_moved_marker_gives_no_position_instead_of_an_old_answer(calibration):
    moved = markers()
    moved['41'] = [moved['41'][0] + 30.0, moved['41'][1]]
    point, reason = to_map(calibration, 'box_on_floor', floor_box(1.0, 0.4), SIZE, moved)
    assert point is None and reason == '기준 마커 41 이동'


def test_too_few_markers_give_no_position(calibration):
    seen = {'40': pixel_of(*CORNERS[40])}
    point, reason = to_map(calibration, 'box_on_floor', floor_box(1.0, 0.4), SIZE, seen)
    assert point is None and '부족' in reason


def test_partly_hidden_markers_pass_when_the_limit_allows(calibration):
    seen = {'40': pixel_of(*CORNERS[40]), '42': pixel_of(*CORNERS[42])}
    assert to_map(calibration, 'box_on_floor', floor_box(1.0, 0.4), SIZE, seen)[0] is not None


@pytest.mark.parametrize('observed', [None, [], {'40': 'x', '41': [1.0, 2.0]},
                                      {'40': [float('nan'), 1.0], '41': [1.0, 2.0]}])
def test_bad_marker_input_gives_a_reason(calibration, observed):
    assert marker_problem(calibration, observed)


@pytest.mark.parametrize('bbox', [
    None, [1, 2, 3], [100, 100, 50, 150], [100, 100, 150, 50], [-5, 10, 50, 60],
    [10, 10, 1300, 60], [10, 10, 50, 800], [10, 10, float('nan'), 60], [True, 10, 50, 60],
])
def test_bad_bbox_gives_no_position(calibration, bbox):
    assert to_map(calibration, 'box_on_floor', bbox, SIZE, markers()) == (None, 'bbox 오류')


def test_box_past_the_lens_model_gives_no_position(calibration):
    point, reason = to_map(calibration, 'box_on_floor', [1260, 0, 1280, 20], SIZE, markers())
    assert point is None and reason == '렌즈 모델 범위 밖'


def test_frame_size_mismatch_gives_no_position(calibration):
    point, reason = to_map(calibration, 'box_on_floor', box(100, 100), [640, 640], markers())
    assert point is None and reason == '프레임 크기 불일치'
    assert to_map(calibration, 'box_on_floor', box(100, 100), None, markers())[0] is None


def test_class_without_a_decided_height_gives_no_position(calibration):
    for name in ('lid_detached', 'box_run_over'):
        point, reason = to_map(calibration, name, box(100, 100), SIZE, markers())
        assert point is None and name in reason


def test_raised_class_without_a_camera_gives_no_position():
    calibration = build_calibration(measured(camera=None))
    point, reason = to_map(calibration, 'box_perched_on_rim', box(100, 100), SIZE, markers())
    assert point is None and reason == '카메라 위치 없음'


def detection(**changes):
    data = {'stream_id': 'CAM', 'event_type': 'box_on_floor', 'confidence': 0.9,
            'timestamp': 12.5, 'bbox': floor_box(1.0, 0.4), 'image_size': SIZE,
            'reference_markers': markers(), 'action_required': 'LANE_HOLD'}
    data.update(changes)
    return data


def test_event_matches_the_agreed_contract(calibration):
    event, reason = to_vision_event(detection(), calibration)
    assert reason == ''
    assert set(event) == {'event_id', 'camera_id', 'vision_class', 'confidence', 'detected_at',
                          'zone_id', 'map_x', 'map_y', 'bbox'}
    assert (event['camera_id'], event['vision_class']) == ('CAM', 'box_on_floor')
    assert event['detected_at'] == 12.5 and event['zone_id'] == '' and event['event_id']
    assert (event['map_x'], event['map_y']) == pytest.approx((1.0, 0.4), abs=1e-3)


def test_event_keeps_its_own_id(calibration):
    assert to_vision_event(detection(event_id='e1'), calibration)[0]['event_id'] == 'e1'


def test_other_camera_gives_no_position(calibration):
    event, reason = to_vision_event(detection(stream_id='OTHER'), calibration)
    assert event['map_x'] is None and reason == '다른 카메라의 보정값'


@pytest.mark.parametrize('raw', [None, [], {'stream_id': 'CAM'}, {'event_type': 'box_on_floor'}])
def test_detection_without_identity_is_refused(raw, calibration):
    with pytest.raises(ValueError):
        to_vision_event(raw, calibration)


def robot():
    return {'pose_x': 1.1, 'pose_y': 0.4, 'step_seq': 4, 'cargo_state': 'LOADED', 'driving': True,
            'queue_wait': False, 'order_id': 'o1'}


def test_converted_event_is_compared_with_robot_pose(calibration):
    event, _ = to_vision_event(detection(), calibration)
    result = judge(event, {'pinky1': robot()})
    assert result['judgment'] == 'TRANSIT_DROP' and result['linked_robot_id'] == 'pinky1'


def test_uncertain_conversion_is_judged_no_position():
    event, reason = to_vision_event(detection(), {'status': 'PENDING', 'camera_id': 'CAM'})
    assert reason and judge(event, {'pinky1': robot()})['judgment'] == 'NO_POSITION'
