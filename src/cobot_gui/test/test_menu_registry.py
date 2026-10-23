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
메뉴 레지스트리와 생성 문서를 검사한다.

모든 검사는 실패할 수 있다. 음성 대조는 레지스트리 사본(메모리)을 일부러 망가뜨려
검증 함수가 오류를 내는지 본다. 레포 루트나 문서를 못 찾으면 skip 하지 않고 실패한다.
아래 고정 표(AGREED_MENUS, AGREED_SR, ORIGINAL_SR)는 YAML 과 menu_registry.py 와
따로 둔 세 번째 사본이다. 원문이 개정되면 셋을 같은 PR 에서 고친다.
"""

import copy
import os
import random
import re

from cobot_gui import gen_menu_doc
from cobot_gui import menu_registry
import yaml

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
PACKAGE_DIR = os.path.dirname(TEST_DIR)
REGISTRY_PATH = os.path.join(PACKAGE_DIR, 'config', 'menu_tree.yaml')

# 메뉴 트리 v0.1 원문(Confluence 6783015 v2)의 2Depth 34개 (ID, 이름).
AGREED_MENUS = (
    ('1.1', '전체 로봇 현황'),
    ('1.2', '작업·미션 현황'),
    ('1.3', '로봇 할당 현황'),
    ('1.4', '알림·이벤트 센터'),
    ('1.5', '운영 이력'),
    ('2.1', '통합 주행 지도'),
    ('2.2', '로봇별 주행 상태'),
    ('2.3', '목표점·경로 관리'),
    ('2.4', '주행 미션 관리'),
    ('2.5', '주행 이력·이상 상태'),
    ('3.1', '로봇팔 상태 모니터링'),
    ('3.2', '작업 시퀀스 관리'),
    ('3.3', '모방학습 데이터 수집'),
    ('3.4', '데이터셋 관리'),
    ('3.5', '작업 실행·재생'),
    ('3.6', '작업 이력'),
    ('3.7', '로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오'),
    ('4.1', '실시간 카메라 모니터링'),
    ('4.2', '카메라 선택·설정'),
    ('4.3', '비전 인식·이벤트 결과'),
    ('4.4', '이미지 캡처·영상 녹화'),
    ('4.5', '영상·이미지 기록 조회'),
    ('5.1', '제어권·운용 모드 관리'),
    ('5.2', '수동 조작 (Teleop)'),
    ('5.3', '일시정지·재개'),
    ('5.4', '정지 요청·복구 관리'),
    ('5.5', '안전·장애 상태 모니터링'),
    ('5.6', '제어 명령·ACK 이력'),
    ('6.1', '로봇·장치 연결 현황'),
    ('6.2', 'ROS 2·FMS 통신 상태'),
    ('6.3', '노드·서비스 상태'),
    ('6.4', '시스템 로그·오류 진단'),
    ('6.5', '시뮬레이션·기능 검증'),
    ('6.6', '시스템 설정'),
)
AGREED_MENU_IDS = tuple(menu_id for menu_id, _ in AGREED_MENUS)
AGREED_DEPTH1 = (
    '01. 통합 관제', '02. Pinky 주행', '03. OMX 작업',
    '04. 비전 모니터링', '05. 제어·안전', '06. 시스템·진단',
)
# System Requirements v5.0 §2 표 (ID, 이름, 우선순위). 이름 앞의 [신규] 표시는 뺐다.
AGREED_SR = (
    ('SR-01', '주문 관리 기능', 'O'),
    ('SR-02', '재고 및 대상 박스 확인 기능', 'O'),
    ('SR-03', '로봇 작업 배정 기능', 'O'),
    ('SR-04', '자율주행 및 운송 기능', 'O'),
    ('SR-05', '다중 로봇 통행 관리 기능', 'O'),
    ('SR-06', '로봇 상태 모니터링 기능', 'O'),
    ('SR-07', '비전 인식 기능', 'O'),
    ('SR-08', '정차 위치 확인 기능', 'O'),
    ('SR-09', '로봇팔 상차·하차 기능', 'O'),
    ('SR-10', '적재 및 작업 완료 확인 기능', 'O'),
    ('SR-11', '주행 안전 제어 기능', 'O'),
    ('SR-12', '로봇팔 안전 제어 기능', 'O'),
    ('SR-13', '사용자 작업 제어 기능', 'O'),
    ('SR-14', '오류 및 통신 장애 대응 기능', 'O'),
    ('SR-15', '오류 알림 기능', 'O'),
    ('SR-16', '하차 대기열 관리 기능', 'O'),
    ('SR-17', '빈 박스 및 반품 회수 관리 기능', 'R'),
    ('SR-18', '작업 흐름 및 주문 완료 관리 기능', 'O'),
    ('SR-19', '네트워크 분리 및 단일 제어권 관리 기능', 'O'),
    ('SR-20', '명령 유효성 검증 및 구 권한 차단 기능', 'O'),
    ('SR-21', '물리 완료 검증 및 이력 역추적(원장) 기능', 'O'),
)
SR_V5_IDS = tuple(sr_id for sr_id, _, _ in AGREED_SR)
# 메뉴 트리 원문 대조표의 '매핑 SR ID' 열. 'SR 미명시'·'운영 파라미터' 는 빈 목록이다.
ORIGINAL_SR = {
    '1.1': ('SR-06', 'SR-09'),
    '1.2': ('SR-01', 'SR-18'),
    '1.3': ('SR-03', 'SR-16'),
    '1.4': ('SR-11', 'SR-14', 'SR-15'),
    '1.5': ('SR-18', 'SR-21'),
    '2.1': ('SR-04', 'SR-05', 'SR-06'),
    '2.2': ('SR-06', 'SR-08'),
    '2.3': ('SR-04',),
    '2.4': ('SR-04', 'SR-17'),
    '2.5': ('SR-14', 'SR-18'),
    '3.1': ('SR-09', 'SR-10', 'SR-12'),
    '3.2': ('SR-09', 'SR-10'),
    '3.3': ('SR-09', 'SR-19', 'UR-04'),
    '3.4': ('SR-21',),
    '3.5': ('SR-09',),
    '3.6': ('SR-18', 'SR-21'),
    '3.7': ('SR-09', 'SR-10', 'SR-19', 'SR-20', 'SR-21', 'UR-04', 'UR-26'),
    '4.1': ('SR-07', 'SR-11'),
    '4.2': ('SR-07',),
    '4.3': ('SR-07', 'SR-11'),
    '4.4': (),
    '4.5': (),
    '5.1': ('SR-13', 'SR-19'),
    '5.2': ('SR-13',),
    '5.3': ('SR-13',),
    '5.4': ('SR-11', 'SR-13', 'SR-14'),
    '5.5': ('SR-11', 'SR-12', 'SR-14'),
    '5.6': ('SR-20', 'SR-21'),
    '6.1': ('SR-06', 'SR-14', 'SR-19'),
    '6.2': ('SR-19', 'SR-20'),
    '6.3': ('SR-14',),
    '6.4': ('SR-14', 'SR-15', 'SR-21'),
    '6.5': ('SR-22',),
    '6.6': (),
}
DECISION_IDS = tuple('D{}'.format(number) for number in range(1, 22))
README_ROLE_KEYS = ('vision', 'navigation', 'manipulation', 'control_center', 'gui')
ROADMAP_MENU_LINE = re.compile(r'^- \*\*포함 메뉴\*\* \(phase=(P[1-5])\): (.+)$')
ROADMAP_HEADING = re.compile(r'^### (S[0-9]+) (.+) \((P[0-9])\)$')


def _registry():
    registry, errors = menu_registry.read_registry(REGISTRY_PATH)
    assert errors == [], errors
    return registry


def _menu(registry, menu_id):
    found = [menu for menu in registry['menus'] if menu['id'] == menu_id]
    assert len(found) == 1, menu_id
    return found[0]


def _repo_root():
    # 시험 파일 위치에서 위로 올라가며 docs/ 와 src/cobot_gui/package.xml 이 함께 있는 곳을 찾는다.
    current = TEST_DIR
    while True:
        has_docs = os.path.isdir(os.path.join(current, 'docs'))
        has_pkg = os.path.isfile(os.path.join(current, 'src', 'cobot_gui', 'package.xml'))
        if has_docs and has_pkg:
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _roadmap_text():
    root = _repo_root()
    assert root is not None, '레포 루트를 찾지 못했다'
    roadmap = os.path.join(root, 'docs', 'fms_roadmap.md')
    assert os.path.isfile(roadmap), '로드맵이 없다: {}'.format(roadmap)
    with open(roadmap, encoding='utf-8') as stream:
        return stream.read()


def _errors_mentioning(errors, *needles):
    return [error for error in errors if all(needle in error for needle in needles)]


def _dump(registry):
    return yaml.safe_dump(registry, allow_unicode=True, sort_keys=False)


def _sr_original_problems(registry):
    # 원문과 매핑이 다른 메뉴에는 sr_original(원문 값)이 있어야 하고, 같은 메뉴에는 없어야 한다.
    problems = []
    for menu in registry['menus']:
        original = ORIGINAL_SR[menu['id']]
        current = set(menu['sr']) | set(menu['sr_unconfirmed'])
        if current == set(original):
            if 'sr_original' in menu:
                problems.append('{}: 원문과 같은데 sr_original 이 있다'.format(menu['id']))
        elif tuple(menu.get('sr_original', ('<없음>',))) != original:
            problems.append('{}: sr_original 이 원문 {} 과 다르다: {}'.format(
                menu['id'], original, menu.get('sr_original')))
    return problems


def _roadmap_problems(registry, text):
    # 로드맵의 단계 제목과 '포함 메뉴' 줄이 레지스트리 phases·phase 와 같은지 본다.
    problems = []
    headings = {}
    menu_lines = {}
    for line in text.splitlines():
        heading = ROADMAP_HEADING.match(line)
        if heading:
            headings[heading.group(3)] = (heading.group(1), heading.group(2))
        match = ROADMAP_MENU_LINE.match(line)
        if match:
            if match.group(1) in menu_lines:
                problems.append('포함 메뉴 줄이 두 번 있다: {}'.format(match.group(1)))
            menu_lines[match.group(1)] = [item.strip() for item in match.group(2).split(',')]
    for phase in registry['phases']:
        expected_heading = (phase['roadmap_stage'], phase['title'])
        if headings.get(phase['id']) != expected_heading:
            problems.append('{}: 로드맵 제목 {} != 레지스트리 {}'.format(
                phase['id'], headings.get(phase['id']), expected_heading))
        expected = sorted(
            (m['id'] for m in registry['menus'] if m['phase'] == phase['id']),
            key=menu_registry.menu_sort_key)
        if menu_lines.get(phase['id']) != expected:
            problems.append('{}: 로드맵 포함 메뉴 {} != 레지스트리 {}'.format(
                phase['id'], menu_lines.get(phase['id']), expected))
    return problems


# (a) 메뉴 ID 34개, 고유, 원문 목록과 같다
def test_menu_ids_match_agreed_list():
    registry = _registry()
    ids = [menu['id'] for menu in registry['menus']]
    assert len(ids) == 34
    assert len(set(ids)) == len(ids)
    assert sorted(ids, key=menu_registry.menu_sort_key) == list(AGREED_MENU_IDS)
    names = {menu['id']: menu['name'] for menu in registry['menus']}
    assert [(menu_id, names[menu_id]) for menu_id in AGREED_MENU_IDS] == list(AGREED_MENUS)


def test_pinned_copies_in_module_match_this_test():
    # 검사기의 고정 사본이 이 시험의 고정 표와 같아야 한다. 한쪽만 고치면 실패한다.
    assert menu_registry.AGREED_MENUS == AGREED_MENUS
    assert menu_registry.SR_V5 == AGREED_SR


def test_depth1_names_match_original():
    registry = _registry()
    depth1 = sorted({menu['depth1'] for menu in registry['menus']})
    assert depth1 == list(AGREED_DEPTH1)


def test_registry_has_no_errors():
    registry = _registry()
    assert menu_registry.validate(registry) == []


# (b) 활성 메뉴는 정확히 한 화면, removed 는 화면 없음, 화면 ID 는 screens 에 있다
def test_active_menus_have_exactly_one_known_screen():
    registry = _registry()
    screen_ids = {screen['id'] for screen in registry['screens']}
    for menu in registry['menus']:
        if menu['status'] == 'removed':
            assert menu['screen'] in ('', None), menu['id']
            assert menu.get('also_shown_in', []) == [], menu['id']
        else:
            assert isinstance(menu['screen'], str), menu['id']
            assert menu['screen'] in screen_ids, menu['id']
            assert menu['screen'] not in menu.get('also_shown_in', []), menu['id']


def test_approved_phase_values():
    registry = _registry()
    removed = _menu(registry, '3.7')
    assert (removed['phase'], removed['status'], removed['screen']) == ('removed', 'removed', '')
    for menu_id in ('4.4', '4.5', '5.2', '6.5'):
        assert _menu(registry, menu_id)['phase'] == 'P5', menu_id
    removed_ids = [m['id'] for m in registry['menus'] if m['status'] == 'removed']
    assert removed_ids == ['3.7']


# (c) sr[] 는 SR v5.0 목록 안에 있고, SR 사본은 SR v5.0 표와 이름·우선순위까지 같다
def test_sr_catalog_matches_sr_v5_table():
    registry = _registry()
    catalog = [
        (item['id'], item['name'], item['priority'])
        for item in registry['sr_catalog']['items']
    ]
    assert catalog == list(AGREED_SR)


def test_sr_refs_are_in_sr_v5_catalog():
    registry = _registry()
    for menu in registry['menus']:
        assert set(menu['sr']) <= set(SR_V5_IDS), menu['id']
        assert not set(menu['sr_unconfirmed']) & set(SR_V5_IDS), menu['id']
    menu_6_5 = _menu(registry, '6.5')
    assert menu_6_5['sr'] == []
    assert menu_6_5['sr_unconfirmed'] == ['SR-22']


def test_sr_original_marks_every_changed_menu():
    registry = _registry()
    assert _sr_original_problems(registry) == []
    changed = sorted(
        (m['id'] for m in registry['menus'] if 'sr_original' in m),
        key=menu_registry.menu_sort_key)
    expected = ['1.1', '1.2', '1.4', '2.4', '2.5', '3.3', '3.4', '3.7', '5.1', '5.2', '5.5']
    assert changed == expected
    for menu_id in changed:
        notes = _menu(registry, menu_id)['notes']
        assert [n for n in notes if n.startswith('초안:')], menu_id


def test_negative_control_sr_original_problems():
    registry = _registry()
    broken = copy.deepcopy(registry)
    del _menu(broken, '1.1')['sr_original']
    assert _errors_mentioning(_sr_original_problems(broken), '1.1')
    broken = copy.deepcopy(registry)
    _menu(broken, '1.3')['sr_original'] = ['SR-03']
    assert _errors_mentioning(_sr_original_problems(broken), '1.3')
    # 지금 매핑과 같은 sr_original 은 검증 함수도 오류로 본다.
    broken = copy.deepcopy(registry)
    _menu(broken, '1.3')['sr_original'] = ['SR-16', 'SR-03']
    assert _errors_mentioning(menu_registry.validate(broken), 'menu 1.3', 'sr_original')
    broken = copy.deepcopy(registry)
    _menu(broken, '1.1')['sr_original'] = ['SR-6']
    assert _errors_mentioning(menu_registry.validate(broken), 'menu 1.1', 'sr_original')


# (d) decisions[] 는 결정 목록 안에 있다
def test_decision_refs_are_known():
    registry = _registry()
    decision_ids = [decision['id'] for decision in registry['decisions']]
    assert decision_ids == list(DECISION_IDS)
    for menu in registry['menus']:
        assert set(menu['decisions']) <= set(decision_ids), menu['id']


# (e) 담당 칸은 roles 키, 빈 칸은 경고 함수가 찾는다
def test_owner_fields_are_role_keys():
    registry = _registry()
    roles = set(registry['roles'])
    assert set(README_ROLE_KEYS) <= roles
    for menu in registry['menus']:
        for key in ('screen_owner', 'data_owner'):
            value = menu[key]
            assert value == '' or value in roles, (menu['id'], key, value)


def test_warning_function_finds_blank_owner_cells():
    registry = _registry()
    baseline = menu_registry.find_warnings(registry)
    assert not [w for w in baseline if w.startswith('menu 1.1 ')]
    assert not [w for w in baseline if w.startswith('menu 2.2 ')]
    broken = copy.deepcopy(registry)
    _menu(broken, '1.1')['screen_owner'] = ''
    _menu(broken, '2.2')['data_owner'] = '   '
    _menu(broken, '3.7')['data_owner'] = ''
    warnings = menu_registry.find_warnings(broken)
    assert 'menu 1.1: screen_owner 빈 칸' in warnings
    assert 'menu 2.2: data_owner 빈 칸' in warnings
    assert not [w for w in warnings if w.startswith('menu 3.7')]
    # 빈 칸은 경고일 뿐 오류가 아니다.
    assert menu_registry.validate(broken) == []


def test_unknown_owner_is_an_error():
    registry = _registry()
    broken = copy.deepcopy(registry)
    _menu(broken, '1.1')['data_owner'] = 'pilot'
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, 'menu 1.1', 'pilot')


# (f) 생성 문서는 생성기 출력과 바이트 단위로 같다
def test_generated_doc_matches_registry_byte_for_byte():
    root = _repo_root()
    assert root is not None, '레포 루트(docs/ + src/cobot_gui/package.xml)를 찾지 못했다'
    doc_path = os.path.join(root, 'docs', 'fms_menu_tree.md')
    assert os.path.isfile(doc_path), '생성 문서가 없다: {}'.format(doc_path)
    expected = gen_menu_doc.render(_registry()).encode('utf-8')
    with open(doc_path, 'rb') as stream:
        actual = stream.read()
    assert b'\r' not in actual, '생성 문서에 CR 이 있다 (줄 끝은 LF)'
    assert actual == expected, '문서가 레지스트리와 다르다. 생성기를 다시 돌린다.'


def test_generated_doc_marks_changed_sr_rows():
    text = gen_menu_doc.render(_registry())
    assert '| 1.1 | 전체 로봇 현황 | ① | P1 | planned | SR-06, SR-10, SR-12 ✱ |' in text
    assert '| 1.3 | 로봇 할당 현황 | ① | P3 | planned | SR-03, SR-16 |' in text
    assert '| 6.5 | 시뮬레이션·기능 검증 | ⑥ | P5 | planned | SR-22 (확인 필요) |' in text
    assert '- ✱ 원문 SR: SR-06, SR-09 (지금 매핑과 다르다. 이유는 아래 메모)' in text


def test_check_option_detects_hand_edit(tmp_path):
    registry = _registry()
    text = gen_menu_doc.render(registry)
    good = tmp_path / 'good.md'
    good.write_bytes(text.encode('utf-8'))
    tampered = tmp_path / 'tampered.md'
    tampered.write_bytes(text.replace('전체 로봇 현황', '전체 로봇 상황', 1).encode('utf-8'))
    assert gen_menu_doc.is_up_to_date(text, str(good))
    assert not gen_menu_doc.is_up_to_date(text, str(tampered))
    assert not gen_menu_doc.is_up_to_date(text, str(tmp_path / 'missing.md'))
    base = ['--check', '--registry', REGISTRY_PATH, '--output']
    assert gen_menu_doc.main(base + [str(good)]) == 0
    assert gen_menu_doc.main(base + [str(tampered)]) == 1


def test_generator_writes_lf_and_is_deterministic(tmp_path):
    registry = _registry()
    first = gen_menu_doc.render(registry)
    shuffled = copy.deepcopy(registry)
    random.Random(7).shuffle(shuffled['menus'])
    assert gen_menu_doc.render(shuffled) == first
    out = tmp_path / 'out.md'
    assert gen_menu_doc.main(['--registry', REGISTRY_PATH, '--output', str(out)]) == 0
    data = out.read_bytes()
    assert data == first.encode('utf-8')
    assert b'\r\n' not in data
    assert data.endswith(b'\n') and not data.endswith(b'\n\n')


def test_generator_refuses_invalid_registry(tmp_path):
    registry = _registry()
    _menu(registry, '1.1')['sr'].append('SR-22')
    bad = tmp_path / 'bad.yaml'
    bad.write_text(_dump(registry), encoding='utf-8')
    out = tmp_path / 'out.md'
    assert gen_menu_doc.main(['--registry', str(bad), '--output', str(out)]) == 1
    assert not out.exists()
    assert menu_registry.main(['--registry', str(bad)]) == 1
    assert menu_registry.main(['--registry', REGISTRY_PATH]) == 0


def test_cli_rejects_deleted_menu_even_after_regeneration(tmp_path):
    # 메뉴를 지우고 문서까지 다시 만든 경우다. CLI 와 --check 가 모두 1 이어야 한다.
    registry = _registry()
    registry['menus'] = [menu for menu in registry['menus'] if menu['id'] != '2.3']
    bad = tmp_path / 'deleted.yaml'
    bad.write_text(_dump(registry), encoding='utf-8')
    doc = tmp_path / 'deleted.md'
    doc.write_bytes(gen_menu_doc.render(registry).encode('utf-8'))
    assert menu_registry.main(['--registry', str(bad)]) == 1
    assert gen_menu_doc.main(['--check', '--registry', str(bad), '--output', str(doc)]) == 1


def test_non_utf8_registry_is_reported(tmp_path):
    with open(REGISTRY_PATH, encoding='utf-8') as stream:
        text = stream.read()
    bad = tmp_path / 'cp949.yaml'
    bad.write_bytes(text.encode('cp949', errors='replace'))
    registry, errors = menu_registry.read_registry(str(bad))
    assert registry is None
    assert _errors_mentioning(errors, 'UTF-8')
    assert menu_registry.main(['--registry', str(bad)]) == 2


# (g) 음성 대조: 사본을 망가뜨리면 검증 함수가 오류를 낸다
def test_negative_control_sr_22_in_sr_is_an_error():
    registry = _registry()
    assert menu_registry.validate(registry) == []
    broken = copy.deepcopy(registry)
    _menu(broken, '1.1')['sr'].append('SR-22')
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, 'menu 1.1', 'SR v5.0 목록에 없는 ID: SR-22')
    # 6.5 는 SR-22 를 sr_unconfirmed 에 두고 있다. sr 에도 넣으면 두 검사가 함께 걸린다.
    broken = copy.deepcopy(registry)
    _menu(broken, '6.5')['sr'].append('SR-22')
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, 'menu 6.5', 'SR v5.0 목록에 없는 ID: SR-22')
    assert _errors_mentioning(errors, 'menu 6.5', 'sr 과 sr_unconfirmed 에 함께')


def test_negative_control_sr_catalog_edits_are_errors():
    registry = _registry()
    items = registry['sr_catalog']['items']
    # 카탈로그에 SR-22 를 더하고 6.5 sr 로 옮겨도 고정 사본이 막는다.
    broken = copy.deepcopy(registry)
    sr_22 = {'id': 'SR-22', 'name': '시뮬레이션 검증 기능', 'priority': 'O'}
    broken['sr_catalog']['items'].append(sr_22)
    _menu(broken, '6.5')['sr'] = ['SR-22']
    _menu(broken, '6.5')['sr_unconfirmed'] = []
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, 'sr_catalog', 'SR-22')
    assert _errors_mentioning(errors, 'menu 6.5', 'SR-22')
    # 이름 한 글자만 바꿔도 걸린다.
    broken = copy.deepcopy(registry)
    broken['sr_catalog']['items'][5]['name'] = items[5]['name'].replace('모니터링', '모니터')
    assert _errors_mentioning(menu_registry.validate(broken), 'sr_catalog SR-06')
    # 우선순위를 바꿔도 걸린다.
    broken = copy.deepcopy(registry)
    broken['sr_catalog']['items'][16]['priority'] = 'O'
    assert _errors_mentioning(menu_registry.validate(broken), 'sr_catalog SR-17')
    # 빼거나 순서를 바꿔도 걸린다.
    broken = copy.deepcopy(registry)
    del broken['sr_catalog']['items'][20]
    assert _errors_mentioning(menu_registry.validate(broken), 'sr_catalog', 'SR-21')
    broken = copy.deepcopy(registry)
    swapped = broken['sr_catalog']['items']
    swapped[0], swapped[1] = swapped[1], swapped[0]
    assert _errors_mentioning(menu_registry.validate(broken), 'sr_catalog', '순서')


def test_negative_control_deleted_or_renamed_menu_is_an_error():
    registry = _registry()
    assert menu_registry.validate(registry) == []
    broken = copy.deepcopy(registry)
    broken['menus'] = [menu for menu in broken['menus'] if menu['id'] != '3.2']
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, '빠진 메뉴 ID', '3.2')
    broken = copy.deepcopy(registry)
    extra = copy.deepcopy(_menu(registry, '6.6'))
    extra['id'] = '6.7'
    broken['menus'].append(extra)
    assert _errors_mentioning(menu_registry.validate(broken), '합의 목록에 없는 메뉴 ID', '6.7')
    broken = copy.deepcopy(registry)
    _menu(broken, '2.3')['name'] = '목표점 관리'
    assert _errors_mentioning(menu_registry.validate(broken), 'menu 2.3', '이름')


def test_negative_control_removed_menu_with_screen_is_an_error():
    registry = _registry()
    broken = copy.deepcopy(registry)
    _menu(broken, '3.7')['screen'] = 'screen_3'
    errors = menu_registry.validate(broken)
    assert _errors_mentioning(errors, 'menu 3.7', '화면')
    broken = copy.deepcopy(registry)
    _menu(broken, '3.7')['also_shown_in'] = ['screen_3']
    assert _errors_mentioning(menu_registry.validate(broken), 'menu 3.7', 'also_shown_in')


def test_negative_control_phase_table_edits_are_errors():
    registry = _registry()
    broken = copy.deepcopy(registry)
    del broken['phases'][4]
    assert _errors_mentioning(menu_registry.validate(broken), 'phases', 'P5')
    broken = copy.deepcopy(registry)
    broken['phases'][1]['roadmap_stage'] = 'S2'
    assert _errors_mentioning(menu_registry.validate(broken), 'phases', 'S2')
    broken = copy.deepcopy(registry)
    broken['phases'][0]['title'] = ''
    assert _errors_mentioning(menu_registry.validate(broken), 'phases[0]', 'title')


def test_negative_control_other_breakages():
    registry = _registry()
    cases = []

    def broken_copy(menu_id, key, value):
        broken = copy.deepcopy(registry)
        _menu(broken, menu_id)[key] = value
        return broken

    cases.append((broken_copy('1.1', 'decisions', ['D99']), ('menu 1.1', 'D99')))
    cases.append((broken_copy('1.1', 'screen', 'screen_9'), ('menu 1.1', 'screen_9')))
    cases.append((broken_copy('1.1', 'screen', ''), ('menu 1.1', '화면')))
    cases.append((broken_copy('1.1', 'phase', 'P0'), ('menu 1.1', 'phase')))
    cases.append((broken_copy('1.1', 'phase', 'removed'), ('menu 1.1', 'removed')))
    cases.append((broken_copy('1.1', 'depth1', '02. Pinky 주행'), ('menu 1.1', 'depth1')))
    cases.append((broken_copy('1.1', 'status', 'in_progress'), ('menu 1.1', 'branch')))
    cases.append((broken_copy('1.1', 'sr', 'SR-06'), ('menu 1.1', 'sr')))
    cases.append((broken_copy('6.5', 'sr_unconfirmed', ['SR-06']), ('menu 6.5', 'SR-06')))
    cases.append((broken_copy('5.4', 'also_shown_in', ['screen_5']), ('menu 5.4', '주 화면')))
    float_id = copy.deepcopy(registry)
    float_id['menus'][0]['id'] = 1.1
    cases.append((float_id, ('따옴표',)))
    duplicate = copy.deepcopy(registry)
    duplicate['menus'].append(copy.deepcopy(_menu(registry, '1.1')))
    cases.append((duplicate, ('중복 메뉴 ID', '1.1')))
    typo = copy.deepcopy(registry)
    _menu(typo, '1.1')['sreen'] = 'screen_1'
    cases.append((typo, ('menu 1.1', '모르는 필드', 'sreen')))
    for broken, needles in cases:
        errors = menu_registry.validate(broken)
        assert _errors_mentioning(errors, *needles), (needles, errors)


def test_in_progress_with_branch_is_accepted():
    registry = _registry()
    claimed = copy.deepcopy(registry)
    _menu(claimed, '1.1')['status'] = 'in_progress'
    _menu(claimed, '1.1')['branch'] = 'feature/gui-1.1-robot-cards'
    assert menu_registry.validate(claimed) == []
    _menu(claimed, '1.1')['branch'] = 'my work'
    assert _errors_mentioning(menu_registry.validate(claimed), 'menu 1.1', 'branch')


def test_duplicate_yaml_key_is_rejected(tmp_path):
    with open(REGISTRY_PATH, encoding='utf-8') as stream:
        text = stream.read()
    marker = "  - id: '1.1'\n"
    assert marker in text
    bad = tmp_path / 'dup.yaml'
    bad.write_text(text.replace(marker, marker + '    phase: P3\n', 1), encoding='utf-8')
    registry, errors = menu_registry.read_registry(str(bad))
    assert registry is None
    assert _errors_mentioning(errors, '중복 키', 'phase')


# (h) 로드맵의 단계 제목·단계별 메뉴 목록이 레지스트리 phases·phase 와 같다
def test_roadmap_stage_menus_match_registry():
    assert _roadmap_problems(_registry(), _roadmap_text()) == []


def test_negative_control_roadmap_mismatch_is_found():
    registry = _registry()
    text = _roadmap_text()
    renamed = copy.deepcopy(registry)
    renamed['phases'][1]['title'] = '정지·복구'
    assert _errors_mentioning(_roadmap_problems(renamed, text), 'P2', '제목')
    moved = copy.deepcopy(registry)
    _menu(moved, '1.3')['phase'] = 'P4'
    assert _errors_mentioning(_roadmap_problems(moved, text), 'P3', '포함 메뉴')
