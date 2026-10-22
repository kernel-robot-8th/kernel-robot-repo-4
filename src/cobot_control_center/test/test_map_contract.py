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
맵 계약(map_contract.py)과 정본 맵 파일을 검사한다.

모든 검사는 실패할 수 있다. 맵 폴더를 못 찾으면 skip 하지 않고 실패한다.
음성 대조는 맵 사본(tmp_path)을 일부러 망가뜨려 검사 함수가 오류를 내는지 본다.
아래 고정 값(SOURCE_*)은 출처 커밋 파일의 sha256 이다. 맵을 바꾸는 PR 에서 함께 고친다.
"""

import hashlib
import logging
import os
import shutil

from cobot_control_center import map_contract
import pytest
import yaml

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
MAP_YAML = 'map_shoe_store_flat.yaml'
MAP_PGM = 'map_shoe_store_flat.pgm'

# 출처: 브랜치 feature/setup-fleet-msgs-structure 커밋 9e51d4d 의 maps/ (바이트 그대로 복사).
SOURCE_PGM_SHA256 = 'c07d79f8f743295e7389709518b8a113039b1e628353e13b5e4a1062a154086b'
SOURCE_YAML_SHA256 = 'acdfcd8fccc13aff6c5545dfe8ffd98c28588f02bea6fdb654572a6066ff31e0'
# 원래 웨이포인트 중 반경 6 cm 원에 점유 셀이 걸리는 것. 아키텍처 설계서 §1.3 #8 의 두 개와
# 같은지 PGM 을 직접 계산해 확인했다 (2026-10-22).
EXPECTED_WORK_POSE_FAILURES = {'WP_UNLOAD', 'WP_BENCH_DELIVERY'}
# 웨이포인트와 연계된 팔 (초안). 맵 YAML 주석 'OMX 1/2/3' 과 같다. 팔이 없는 지점은 빠진다.
EXPECTED_ARM_IDS = {'WP_LOAD_1': 'omx_1', 'WP_LOAD_2': 'omx_2', 'WP_UNLOAD': 'omx_3'}
RADIUS_M = 0.06
FREE_PIXEL = 254
OCCUPIED_PIXEL = 0
UNKNOWN_PIXEL = 128


def _repo_root():
    # 시험 파일 위치에서 위로 올라가며 docs/ 와 src/cobot_bringup/package.xml 이 함께 있는 곳을 찾는다.
    current = TEST_DIR
    while True:
        has_docs = os.path.isdir(os.path.join(current, 'docs'))
        has_pkg = os.path.isfile(os.path.join(current, 'src', 'cobot_bringup', 'package.xml'))
        if has_docs and has_pkg:
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


@pytest.fixture
def maps_dir():
    root = _repo_root()
    assert root is not None, '레포 루트를 찾지 못했다 (docs/ 와 src/cobot_bringup/package.xml)'
    path = os.path.join(root, map_contract.MAPS_RELPATH)
    for name in (map_contract.POSES_FILENAME, MAP_YAML, MAP_PGM):
        assert os.path.isfile(os.path.join(path, name)), '맵 파일이 없다: {}'.format(
            os.path.join(path, name))
    return path


@pytest.fixture
def maps_copy(maps_dir, tmp_path):
    path = str(tmp_path / 'maps')
    shutil.copytree(maps_dir, path)
    return path


@pytest.fixture
def module_log(caplog, monkeypatch):
    # ROS 를 source 한 셸에서는 pytest 가 launch_testing 플러그인을 저절로 불러온다. 그 안의
    # launch.logging 이 그 뒤에 만들어지는 로거를 propagate=False 로 만들어서 caplog 가 이 모듈의
    # 로그를 못 받는다. 시험 동안만 propagate 를 켠다. 명령을 직접 돌릴 때는 상관없다.
    monkeypatch.setattr(map_contract.LOGGER, 'propagate', True)
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger=map_contract.LOGGER.name)
    return caplog


def _read(path):
    with open(path, 'rb') as stream:
        return stream.read()


def _write(path, data):
    with open(path, 'wb') as stream:
        stream.write(data)


def _same_dir(first, second):
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def _poses_doc(maps):
    doc, errors = map_contract.read_poses(os.path.join(maps, map_contract.POSES_FILENAME))
    assert errors == []
    return doc


def _rewrite_poses(maps, doc):
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    _write(os.path.join(maps, map_contract.POSES_FILENAME), text.encode('utf-8'))


def _reference_hash(pgm_bytes, yaml_bytes):
    # 정의의 세 번째 사본: 모듈과 따로 계산한다.
    pgm_digest = hashlib.sha256(pgm_bytes).digest()
    yaml_digest = hashlib.sha256(yaml_bytes.replace(b'\r\n', b'\n')).digest()
    return hashlib.sha256(pgm_digest + yaml_digest).hexdigest()


def _tiny_map(tmp_path, width, height, pixels, negate=0, occupied_thresh=0.65,
              free_thresh=0.196):
    header = 'P5\n# tiny\n{} {}\n255\n'.format(width, height).encode('ascii')
    _write(str(tmp_path / 'tiny.pgm'), header + bytes(pixels))
    doc = {
        'image': 'tiny.pgm', 'mode': 'trinary', 'resolution': 0.01,
        'origin': [0.0, 0.0, 0.0], 'negate': negate,
        'occupied_thresh': occupied_thresh, 'free_thresh': free_thresh,
    }
    path = str(tmp_path / 'tiny.yaml')
    _write(path, yaml.safe_dump(doc).encode('utf-8'))
    return map_contract.load_map(path).grid


def _set_pixel(pixels, width, height, mx, my, value):
    # 격자 (mx, my) 는 PGM 의 (height - 1 - my) 번째 줄이다.
    pixels[(height - 1 - my) * width + mx] = value


# --- 맵 정본 위치·출처 ---


def test_maps_dir_is_found_from_repo(maps_dir):
    path, origin = map_contract.find_maps_dir(start=TEST_DIR)
    assert origin == 'source'
    assert os.path.realpath(path) == os.path.realpath(maps_dir)


def test_map_bytes_match_source_commit(maps_dir):
    pgm = _read(os.path.join(maps_dir, MAP_PGM))
    yaml_bytes = _read(os.path.join(maps_dir, MAP_YAML))
    assert hashlib.sha256(pgm).hexdigest() == SOURCE_PGM_SHA256
    assert hashlib.sha256(yaml_bytes.replace(b'\r\n', b'\n')).hexdigest() == SOURCE_YAML_SHA256


def test_map_geometry(maps_dir):
    loaded = map_contract.load_map(os.path.join(maps_dir, MAP_YAML))
    grid = loaded.grid
    assert (grid.width, grid.height) == (240, 240)
    assert grid.resolution == pytest.approx(0.01)
    assert grid.origin_x == pytest.approx(-0.01)
    assert grid.origin_y == pytest.approx(-0.01)
    assert grid.width * grid.resolution == pytest.approx(2.4)
    assert set(grid.states) <= {map_contract.FREE, map_contract.OCCUPIED, map_contract.UNKNOWN}


# --- (a) 원래 웨이포인트(work_pose)는 실패해야 한다 ---


def test_work_poses_fail_lint(maps_dir):
    report = map_contract.run_lint(maps_dir, map_contract.WORK_POSE)
    assert set(report.failures) == EXPECTED_WORK_POSE_FAILURES
    # 매니페스트·work_pose 대조는 통과하고, 반경 원 실패 두 건만 남아야 한다.
    assert len(report.errors) == len(EXPECTED_WORK_POSE_FAILURES)
    for wp_id in EXPECTED_WORK_POSE_FAILURES:
        assert any(error.startswith(wp_id + ' work_pose') for error in report.errors), wp_id
    assert map_contract.lint_main(['--maps-dir', maps_dir, '--poses', 'work_pose']) == 1


def test_map_yaml_waypoints_fail_lint(maps_dir):
    # approach_poses.yaml 을 거치지 않고 맵 YAML 의 waypoints 를 그대로 검사해도 같은 결과다.
    loaded = map_contract.load_map(os.path.join(maps_dir, MAP_YAML))
    failures = map_contract.lint_waypoints(loaded.grid, loaded.doc['waypoints'], RADIUS_M)
    assert set(failures) == EXPECTED_WORK_POSE_FAILURES
    for wp_id in EXPECTED_WORK_POSE_FAILURES:
        pose = loaded.doc['waypoints'][wp_id]
        own = loaded.grid.state(*loaded.grid.cell_of(pose[0], pose[1]))
        assert own == map_contract.OCCUPIED, wp_id


# --- (b) 정차점(approach_pose)은 통과해야 한다 ---


def test_approach_poses_pass_lint(maps_dir):
    report = map_contract.run_lint(maps_dir)
    assert report.errors == []
    assert report.failures == {}
    assert report.radius_m == pytest.approx(RADIUS_M)
    assert len(report.poses) == len(report.loaded.doc['waypoints'])
    assert map_contract.lint_main(['--maps-dir', maps_dir]) == 0


def test_radius_is_used(maps_dir):
    # 반경을 키우면 정차점도 실패해야 한다. 반경 값이 무시되면 이 시험이 실패한다.
    report = map_contract.run_lint(maps_dir, radius_m=0.5)
    assert report.failures
    assert map_contract.lint_main(['--maps-dir', maps_dir, '--radius', '0.5']) == 1


def test_suggest_logs_candidates(maps_dir, module_log):
    argv = ['--maps-dir', maps_dir, '--poses', 'work_pose', '--suggest']
    assert map_contract.lint_main(argv) == 1
    text = module_log.text
    for wp_id in EXPECTED_WORK_POSE_FAILURES:
        assert '{}: 가장 가까운 자유 점'.format(wp_id) in text, wp_id


def test_wider_radius_fails_moved_approach_poses(maps_dir):
    # 옮긴 정차점 두 개는 반경 6 cm 에서만 통과한다. 6 cm + SR-08 1차 정차 오차 5 cm 로 보면
    # 실패한다. 문서(5.3절)의 이 설명이 맞는지 고정한다. 정차점을 고치면 이 시험도 고친다.
    report = map_contract.run_lint(maps_dir, radius_m=0.11)
    assert set(report.failures) == EXPECTED_WORK_POSE_FAILURES


def test_nearest_free_point_is_nearest(maps_dir):
    loaded = map_contract.load_map(os.path.join(maps_dir, MAP_YAML))
    grid = loaded.grid
    for wp_id in sorted(EXPECTED_WORK_POSE_FAILURES):
        x, y, _ = loaded.doc['waypoints'][wp_id]
        point = map_contract.nearest_free_point(grid, x, y, RADIUS_M)
        assert point is not None, wp_id
        assert map_contract.disk_problems(grid, point[0], point[1], RADIUS_M)[1] == []
        moved_i = round((point[0] - x) / grid.resolution)
        moved_j = round((point[1] - y) / grid.resolution)
        best = moved_i * moved_i + moved_j * moved_j
        assert best > 0
        steps = int(best ** 0.5) + 1
        for j in range(-steps, steps + 1):
            for i in range(-steps, steps + 1):
                if i * i + j * j >= best:
                    continue
                cand_x = x + i * grid.resolution
                cand_y = y + j * grid.resolution
                problems = map_contract.disk_problems(grid, cand_x, cand_y, RADIUS_M)[1]
                assert problems, '{}: 더 가까운 자유 점이 있다 ({}, {})'.format(wp_id, i, j)


def test_nearest_free_point_tie_break(tmp_path):
    # 가운데 셀 하나만 점유인 작은 맵. 한 칸 떨어진 네 점(아래·왼쪽·오른쪽·위)이 같은 거리다.
    # 규칙: y 가 가장 작은 (아래쪽) 점, 그다음 x 가 가장 작은 (왼쪽) 점.
    width = height = 41
    pixels = bytearray([FREE_PIXEL] * (width * height))
    _set_pixel(pixels, width, height, 20, 20, OCCUPIED_PIXEL)  # 셀 중심 (0.205, 0.205)
    grid = _tiny_map(tmp_path, width, height, pixels)
    radius = 0.001  # 점이 든 셀만 보는 반경
    assert map_contract.nearest_free_point(grid, 0.205, 0.205, radius) == (0.205, 0.195)
    # 아래쪽 셀도 점유면 같은 거리의 나머지 둘 (왼쪽, 오른쪽) 중 왼쪽이다.
    _set_pixel(pixels, width, height, 20, 19, OCCUPIED_PIXEL)
    grid = _tiny_map(tmp_path, width, height, pixels)
    assert map_contract.nearest_free_point(grid, 0.205, 0.205, radius) == (0.195, 0.205)


# --- (c) map_hash ---


def test_map_hash_is_deterministic_and_recorded(maps_dir, capsys):
    yaml_path = os.path.join(maps_dir, MAP_YAML)
    first = map_contract.load_map(yaml_path).map_hash
    second = map_contract.load_map(yaml_path).map_hash
    assert first == second
    assert len(first) == 64
    expected = _reference_hash(_read(os.path.join(maps_dir, MAP_PGM)), _read(yaml_path))
    assert first == expected
    assert _poses_doc(maps_dir)['map']['map_hash'] == first
    capsys.readouterr()
    assert map_contract.hash_main(['--maps-dir', maps_dir]) == 0
    assert capsys.readouterr().out == first + '\n'


def test_map_hash_changes_with_one_pgm_byte(maps_copy):
    yaml_path = os.path.join(maps_copy, MAP_YAML)
    before = map_contract.load_map(yaml_path).map_hash
    pgm_path = os.path.join(maps_copy, MAP_PGM)
    data = bytearray(_read(pgm_path))
    # 자유 픽셀 한 바이트만 바꾼다 (254 -> 253, 둘 다 자유라 린트 판정은 그대로다).
    # 머리는 ASCII 라 254 가 없으므로 rindex 는 픽셀 영역을 가리킨다.
    index = data.rindex(FREE_PIXEL)
    data[index] = FREE_PIXEL - 1
    _write(pgm_path, bytes(data))
    after = map_contract.load_map(yaml_path).map_hash
    assert after != before
    errors = map_contract.run_lint(maps_copy).errors
    assert any(error.startswith('map.pgm_sha256') for error in errors)
    assert any(error.startswith('map.map_hash') for error in errors)
    assert map_contract.lint_main(['--maps-dir', maps_copy]) == 1


def test_map_hash_changes_with_one_yaml_char(maps_copy):
    yaml_path = os.path.join(maps_copy, MAP_YAML)
    before = map_contract.load_map(yaml_path).map_hash
    data = _read(yaml_path)
    assert data.count(b'# PRD_3 Named') == 1
    _write(yaml_path, data.replace(b'# PRD_3 Named', b'# PRD_4 Named'))
    after = map_contract.load_map(yaml_path).map_hash
    assert after != before
    errors = map_contract.run_lint(maps_copy).errors
    assert any(error.startswith('map.yaml_lf_sha256') for error in errors)


def test_map_hash_ignores_crlf(maps_copy):
    yaml_path = os.path.join(maps_copy, MAP_YAML)
    lf_data = _read(yaml_path).replace(b'\r\n', b'\n')
    _write(yaml_path, lf_data)
    lf_hash = map_contract.load_map(yaml_path).map_hash
    crlf_data = lf_data.replace(b'\n', b'\r\n')
    assert crlf_data != lf_data
    _write(yaml_path, crlf_data)
    assert map_contract.load_map(yaml_path).map_hash == lf_hash
    assert map_contract.run_lint(maps_copy).errors == []


# --- (d) 못 찾으면 실패 ---


def test_missing_maps_dir_fails(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert map_contract.find_maps_dir(start=str(empty)) == (None, None)
    assert map_contract.lint_main(['--maps-dir', str(empty)]) == 2
    assert map_contract.hash_main(['--maps-dir', str(empty)]) == 2


def test_missing_pgm_fails(maps_copy):
    os.remove(os.path.join(maps_copy, MAP_PGM))
    with pytest.raises(map_contract.MapError):
        map_contract.run_lint(maps_copy)
    assert map_contract.lint_main(['--maps-dir', maps_copy]) == 2
    assert map_contract.hash_main(['--maps-dir', maps_copy]) == 2


# --- 맵 폴더 찾기: install 이 계약 입력이다 ---
# _installed_maps_dir 를 바꿔 끼워 세 경우를 만든다: ROS 없음, ROS 인데 install 없음, install 있음.


def test_ros_env_without_install_stops(maps_dir, monkeypatch, capsys):
    monkeypatch.setattr(map_contract, '_installed_maps_dir', lambda: (None, True))
    monkeypatch.chdir(_repo_root())
    path, origin = map_contract.find_maps_dir()
    assert _same_dir(path, maps_dir)
    assert origin == map_contract.ORIGIN_SOURCE_NO_INSTALL
    capsys.readouterr()
    # 소스 트리로 몰래 떨어지지 않는다. 표준 출력에 값이 나오면 안 된다.
    assert map_contract.hash_main([]) == 2
    assert map_contract.lint_main([]) == 2
    assert capsys.readouterr().out == ''


def test_allow_source_warns(maps_dir, monkeypatch, capsys, module_log):
    monkeypatch.setattr(map_contract, '_installed_maps_dir', lambda: (None, True))
    monkeypatch.chdir(_repo_root())
    capsys.readouterr()
    assert map_contract.hash_main(['--allow-source']) == 0
    expected = map_contract.load_map(os.path.join(maps_dir, MAP_YAML)).map_hash
    assert capsys.readouterr().out == expected + '\n'
    assert map_contract.lint_main(['--allow-source']) == 0
    warnings = [record for record in module_log.records if record.levelno == logging.WARNING]
    assert warnings and all('source' in record.getMessage() for record in warnings)


def test_no_ros_uses_source(maps_dir, monkeypatch, capsys, module_log):
    monkeypatch.setattr(map_contract, '_installed_maps_dir', lambda: (None, False))
    monkeypatch.chdir(_repo_root())
    path, origin = map_contract.find_maps_dir()
    assert _same_dir(path, maps_dir)
    assert origin == map_contract.ORIGIN_SOURCE
    assert map_contract.hash_main([]) == 0
    assert not [record for record in module_log.records if record.levelno >= logging.WARNING]


def test_install_is_preferred(maps_copy, monkeypatch, capsys):
    monkeypatch.setattr(map_contract, '_installed_maps_dir', lambda: (maps_copy, True))
    monkeypatch.chdir(_repo_root())
    assert map_contract.find_maps_dir() == (maps_copy, map_contract.ORIGIN_INSTALL)
    assert map_contract.hash_main([]) == 0
    # install 사본의 PGM 을 지우면 install 을 읽었다는 뜻으로 2 가 나와야 한다 (소스는 그대로다).
    os.remove(os.path.join(maps_copy, MAP_PGM))
    assert map_contract.hash_main([]) == 2


# --- approach_poses.yaml 대조 ---


def test_work_pose_must_match_map_yaml(maps_copy):
    doc = _poses_doc(maps_copy)
    doc['waypoints']['WP_HOME_1']['work_pose'][0] += 0.01
    _rewrite_poses(maps_copy, doc)
    errors = map_contract.run_lint(maps_copy).errors
    assert any(error.startswith('WP_HOME_1 work_pose') for error in errors)


def test_missing_waypoint_is_reported(maps_copy):
    doc = _poses_doc(maps_copy)
    del doc['waypoints']['WP_RETURN']
    _rewrite_poses(maps_copy, doc)
    errors = map_contract.run_lint(maps_copy).errors
    assert any('WP_RETURN' in error for error in errors)


def test_unknown_key_is_reported(maps_copy):
    doc = _poses_doc(maps_copy)
    entry = doc['waypoints']['WP_LOAD_1']
    entry['aproach_pose'] = entry.pop('approach_pose')
    _rewrite_poses(maps_copy, doc)
    errors = map_contract.run_lint(maps_copy).errors
    assert any('WP_LOAD_1' in error and 'approach_pose' in error for error in errors)
    assert any('aproach_pose' in error for error in errors)


def test_arm_ids_are_recorded(maps_dir):
    # 웨이포인트와 팔의 연계는 이 파일 하나에만 적는다 (Waypoint.msg 의 arm_id 원천).
    arm_ids = map_contract.arm_ids_of(_poses_doc(maps_dir))
    assert {wp_id: arm for wp_id, arm in arm_ids.items() if arm} == EXPECTED_ARM_IDS
    assert set(arm_ids) == set(map_contract.poses_of(_poses_doc(maps_dir), 'work_pose'))


def test_bad_arm_id_is_reported(maps_copy):
    doc = _poses_doc(maps_copy)
    for bad in (1, '', 'omx 1', '1omx', 'omx_1\n', ['omx_1']):
        doc['waypoints']['WP_LOAD_1']['arm_id'] = bad
        _rewrite_poses(maps_copy, doc)
        errors = map_contract.run_lint(maps_copy).errors
        assert any(error.startswith('waypoints.WP_LOAD_1.arm_id') for error in errors), bad
    doc['waypoints']['WP_LOAD_1']['arm_id'] = 'omx_1'
    _rewrite_poses(maps_copy, doc)
    assert map_contract.run_lint(maps_copy).errors == []


def test_wrong_recorded_hash_is_reported(maps_copy):
    doc = _poses_doc(maps_copy)
    doc['map']['map_hash'] = '0' * 64
    _rewrite_poses(maps_copy, doc)
    errors = map_contract.run_lint(maps_copy).errors
    assert any(error.startswith('map.map_hash') for error in errors)


# --- 셀 판정·원 검사 규칙 (작은 가짜 맵) ---


def test_disk_boundary_and_outside(tmp_path):
    width = height = 41
    pixels = bytearray([FREE_PIXEL] * (width * height))
    _set_pixel(pixels, width, height, 20, 20, OCCUPIED_PIXEL)  # 셀 중심 (0.205, 0.205)
    grid = _tiny_map(tmp_path, width, height, pixels)
    assert grid.state(20, 20) == map_contract.OCCUPIED
    # 거리 = 반경이면 원 안으로 친다 (실패).
    assert map_contract.disk_problems(grid, 0.205, 0.145, RADIUS_M)[1] == [
        (20, 20, map_contract.OCCUPIED)]
    # 반경보다 조금 멀면 통과.
    assert map_contract.disk_problems(grid, 0.205, 0.1449, RADIUS_M)[1] == []
    # 원이 맵 밖으로 나가면 실패.
    problems = map_contract.disk_problems(grid, 0.39, 0.39, RADIUS_M)[1]
    assert problems
    assert {state for _, _, state in problems} == {map_contract.OUTSIDE}
    # 반경이 셀보다 작아도 점이 든 셀은 본다.
    assert map_contract.disk_problems(grid, 0.2001, 0.2001, 0.001)[1] == [
        (20, 20, map_contract.OCCUPIED)]


def test_unknown_and_negate(tmp_path):
    width = height = 41
    pixels = bytearray([FREE_PIXEL] * (width * height))
    _set_pixel(pixels, width, height, 15, 30, UNKNOWN_PIXEL)  # 셀 중심 (0.155, 0.305)
    grid = _tiny_map(tmp_path, width, height, pixels)
    assert grid.state(15, 30) == map_contract.UNKNOWN
    assert map_contract.disk_problems(grid, 0.155, 0.305, RADIUS_M)[1] == [
        (15, 30, map_contract.UNKNOWN)]
    assert map_contract.disk_problems(grid, 0.205, 0.205, RADIUS_M)[1] == []
    # negate = 1 이면 밝은 픽셀이 점유다.
    negated = _tiny_map(tmp_path, width, height, pixels, negate=1)
    assert negated.state(20, 20) == map_contract.OCCUPIED
    assert map_contract.disk_problems(negated, 0.205, 0.205, RADIUS_M)[1]


def test_threshold_boundary_is_unknown(tmp_path):
    # 문턱과 딱 같은 값은 미지로 본다 (Jazzy map_server 는 점유·자유로 본다. 린트가 더 엄격하다).
    # occupied_thresh 0.6, free_thresh 0.4 에서 픽셀 102 는 occ = 0.6, 픽셀 153 은 occ = 0.4 다.
    assert 1.0 - 102 / 255 == 0.6
    assert 1.0 - 153 / 255 == 0.4
    width = height = 41
    pixels = bytearray([FREE_PIXEL] * (width * height))
    _set_pixel(pixels, width, height, 10, 10, 102)
    _set_pixel(pixels, width, height, 11, 10, 101)  # occ 0.604 > 0.6
    _set_pixel(pixels, width, height, 30, 30, 153)
    _set_pixel(pixels, width, height, 31, 30, 154)  # occ 0.396 < 0.4
    grid = _tiny_map(tmp_path, width, height, pixels, occupied_thresh=0.6, free_thresh=0.4)
    assert grid.state(10, 10) == map_contract.UNKNOWN
    assert grid.state(11, 10) == map_contract.OCCUPIED
    assert grid.state(30, 30) == map_contract.UNKNOWN
    assert grid.state(31, 30) == map_contract.FREE
    # 자유 문턱 경계 셀이 원 안에 있으면 린트는 실패한다.
    assert map_contract.disk_problems(grid, 0.305, 0.305, 0.001)[1] == [
        (30, 30, map_contract.UNKNOWN)]
    assert map_contract.disk_problems(grid, 0.315, 0.305, 0.001)[1] == []


def test_pgm_parser():
    body = bytes([OCCUPIED_PIXEL, FREE_PIXEL, FREE_PIXEL, FREE_PIXEL, FREE_PIXEL, FREE_PIXEL])
    width, height, maxval, pixels = map_contract.parse_pgm(
        b'P5\n# comment\n3 2\n255\n' + body)
    assert (width, height, maxval, pixels) == (3, 2, 255, body)
    bad_inputs = (
        b'P2\n3 2\n255\n' + body,          # 텍스트 PGM
        b'P5\n3 2\n255\n' + body[:-1],     # 픽셀 모자람
        b'P5\n3 2\n255\n' + body + b'\0',  # 픽셀 남음
        b'P5\n3 2\n65535\n' + body,        # 16비트
        b'P5\n3 x\n255\n' + body,          # 숫자 아님
        b'P5\n3 2\n',                      # 머리 끊김
    )
    for data in bad_inputs:
        with pytest.raises(map_contract.MapError):
            map_contract.parse_pgm(data)
