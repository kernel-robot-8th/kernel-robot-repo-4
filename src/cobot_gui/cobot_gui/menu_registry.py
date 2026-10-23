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
메뉴 레지스트리(config/menu_tree.yaml)를 읽고 검사한다.

ROS 에 의존하지 않는다. 검사 함수는 오류 문자열 목록을 돌려준다.
빈 목록이면 통과다. 화면을 만들지도, 토픽을 발행하지도 않는다.
레포 루트(또는 그 아래 폴더)에서 돌린다. 다른 곳에서는 --registry 로 경로를 준다.
"""

import argparse
import logging
import os
import re
import sys

import yaml

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
REGISTRY_RELPATH = os.path.join('src', 'cobot_gui', 'config', 'menu_tree.yaml')

# 원문 고정 사본. YAML 과 따로 둔다.
# YAML 만 고쳐서는 메뉴·SR 을 늘리거나 줄이거나 이름을 바꿀 수 없게 하려는 것이다.
# 원문이 개정되면 이 표, YAML, test/test_menu_registry.py 의 표를 같은 PR 에서 고친다.

# 메뉴 트리 원문 v0.1 (Confluence 6783015 v2) 의 2Depth 34개 (ID, 이름).
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

# System Requirements v5.0 §2 표의 (ID, 이름, 우선순위). 이름 앞의 [신규] 표시는 뺐다.
SR_VERSION = 'SR v5.0'
SR_V5 = (
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

ACTIVE_PHASES = ('P1', 'P2', 'P3', 'P4', 'P5')
REMOVED = 'removed'
IN_PROGRESS = 'in_progress'
STATUSES = ('planned', IN_PROGRESS, 'done', REMOVED)
DECISION_STATUSES = ('open', 'decided')

TOP_KEYS = (
    'schema_version', 'source', 'sr_catalog', 'roles', 'screens', 'phases', 'decisions',
    'menus',
)
OPTIONAL_TOP_KEYS = ('notes',)
MENU_KEYS = (
    'id', 'name', 'depth1', 'screen', 'phase', 'status', 'sr', 'sr_unconfirmed',
    'data_sources', 'commands', 'screen_owner', 'data_owner', 'decisions', 'notes',
)
OPTIONAL_MENU_KEYS = ('also_shown_in', 'branch', 'sr_original')
MENU_LIST_KEYS = (
    'sr', 'sr_unconfirmed', 'data_sources', 'commands', 'decisions', 'notes',
)
OWNER_KEYS = ('screen_owner', 'data_owner')
SCREEN_KEYS = ('id', 'label', 'name', 'phase_note')
PHASE_KEYS = ('id', 'title', 'roadmap_stage')
ROLE_KEYS = ('name', 'packages', 'members')
DECISION_KEYS = ('id', 'title', 'status', 'blocks')
SR_KEYS = ('id', 'name', 'priority')

MENU_ID_RE = re.compile(r'^([1-9][0-9]*)\.([1-9][0-9]*)$')
DEPTH1_RE = re.compile(r'^([0-9]{2})\. \S')
SR_ID_RE = re.compile(r'^SR-[0-9]{2}$')
ORIGINAL_REF_RE = re.compile(r'^(SR|UR)-[0-9]{2}$')
STAGE_RE = re.compile(r'^S[0-9]+$')
DECISION_ID_RE = re.compile(r'^D[1-9][0-9]*$')
KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')
BRANCH_RE = re.compile(r'^(feature|fix)/[A-Za-z0-9._/-]+$')


def _construct_unique_mapping(loader, node, deep=False):
    # PyYAML 은 같은 키가 두 번 나오면 뒤 값을 조용히 쓴다.
    # 병합 충돌을 풀다 생긴 중복 키를 놓치지 않으려고 오류로 바꾼다.
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicated = key in mapping
        except TypeError:
            raise yaml.constructor.ConstructorError(
                'mapping', node.start_mark, '키로 쓸 수 없는 값', key_node.start_mark)
        if duplicated:
            raise yaml.constructor.ConstructorError(
                'mapping', node.start_mark, '중복 키: {}'.format(key), key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


# class 문 대신 type() 으로 SafeLoader 를 복제한다. 전역 SafeLoader 는 건드리지 않는다.
_UNIQUE_KEY_LOADER = type('UniqueKeyLoader', (yaml.SafeLoader,), {})
_UNIQUE_KEY_LOADER.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_registry(path):
    """
    레지스트리 YAML 을 읽어 돌려준다.

    중복 키가 있으면 yaml.YAMLError 를 낸다.

    :param path: menu_tree.yaml 경로
    :return: 읽은 값 (정상이면 dict)
    """
    with open(path, encoding='utf-8') as stream:
        return yaml.load(stream, Loader=_UNIQUE_KEY_LOADER)


def read_registry(path):
    """
    레지스트리를 읽고 (레지스트리, 오류 목록) 을 돌려준다.

    파일을 열 수 없거나, UTF-8 이 아니거나, YAML 이 깨졌으면 레지스트리 자리는 None 이다.

    :param path: menu_tree.yaml 경로
    :return: (레지스트리 또는 None, 오류 문자열 목록)
    """
    try:
        return load_registry(path), []
    except OSError as exc:
        return None, ['레지스트리를 열 수 없다: {} ({})'.format(path, exc.strerror)]
    except UnicodeDecodeError as exc:
        return None, ['레지스트리를 UTF-8 로 읽을 수 없다: {} ({}). 파일을 UTF-8 로 저장한다.'.format(
            path, exc.reason)]
    except yaml.YAMLError as exc:
        return None, ['레지스트리 YAML 오류: {}'.format(exc)]


def find_repo_root(start=None):
    """
    레지스트리가 있는 레포 루트를 찾는다.

    start 에서 위로 올라가며 src/cobot_gui/config/menu_tree.yaml 이 있는 폴더를 찾는다.
    start 가 없으면 현재 폴더, 그다음 이 파일의 위치에서 찾는다.

    :param start: 찾기 시작할 폴더
    :return: 레포 루트 경로, 못 찾으면 None
    """
    if start is not None:
        candidates = [start]
    else:
        candidates = [os.getcwd(), os.path.dirname(os.path.realpath(__file__))]
    for candidate in candidates:
        current = os.path.abspath(candidate)
        while True:
            if os.path.isfile(os.path.join(current, REGISTRY_RELPATH)):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return None


def menu_sort_key(menu_id):
    """
    메뉴 ID 를 숫자 순서(1.2 < 1.10)로 정렬하는 키를 돌려준다.

    :param menu_id: 메뉴 ID 문자열
    :return: 정렬 키
    """
    match = MENU_ID_RE.match(str(menu_id))
    if match is None:
        return (sys.maxsize, sys.maxsize, str(menu_id))
    return (int(match.group(1)), int(match.group(2)), '')


def is_blank(value):
    """값이 None 이거나 공백뿐인 문자열이면 True 를 돌려준다."""
    return value is None or (isinstance(value, str) and not value.strip())


def _is_str_list(value):
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value)


def _duplicates(items):
    seen = set()
    dups = []
    for item in items:
        if item in seen and item not in dups:
            dups.append(item)
        seen.add(item)
    return dups


def _check_keys(entry, required, optional, label, errors):
    missing = [key for key in required if key not in entry]
    unknown = [key for key in entry if key not in required and key not in optional]
    for key in missing:
        errors.append('{}: 필드 없음: {}'.format(label, key))
    for key in unknown:
        errors.append('{}: 모르는 필드: {}'.format(label, key))
    return not missing


def _collect_ids(entries, label, id_re, errors):
    ids = []
    if not isinstance(entries, list):
        errors.append('{}: 목록이어야 한다'.format(label))
        return ids
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append('{}[{}]: mapping 이어야 한다'.format(label, index))
            continue
        entry_id = entry.get('id')
        if not isinstance(entry_id, str) or not id_re.match(entry_id):
            errors.append('{}[{}]: 형식이 틀린 id: {!r}'.format(label, index, entry_id))
            continue
        ids.append(entry_id)
    for dup in _duplicates(ids):
        errors.append('{}: 중복 id: {}'.format(label, dup))
    return ids


def _compare_sr_catalog(rows, errors):
    # YAML 사본을 코드의 고정 사본(SR_V5)과 대조한다. 같은 YAML 안의 목록만 믿으면
    # 카탈로그에 SR-22 를 더하거나 SR 이름을 바꿔도 통과하기 때문이다.
    pinned = {sr_id: (name, priority) for sr_id, name, priority in SR_V5}
    found = [row[0] for row in rows]
    for sr_id, name, priority in rows:
        if sr_id not in pinned:
            errors.append('sr_catalog: {} 에 없는 ID: {}'.format(SR_VERSION, sr_id))
        elif (name, priority) != pinned[sr_id]:
            errors.append('sr_catalog {}: {} 원문과 다르다: {!r} {} (원문 {!r} {})'.format(
                sr_id, SR_VERSION, name, priority, pinned[sr_id][0], pinned[sr_id][1]))
    missing = [sr_id for sr_id, _, _ in SR_V5 if sr_id not in found]
    for sr_id in missing:
        errors.append('sr_catalog: {} 의 ID 가 빠졌다: {}'.format(SR_VERSION, sr_id))
    pinned_order = [sr_id for sr_id, _, _ in SR_V5]
    if not missing and len(found) == len(pinned_order) and found != pinned_order:
        errors.append('sr_catalog: 순서가 {} 표와 다르다'.format(SR_VERSION))


def _validate_sr_catalog(catalog, errors):
    if not isinstance(catalog, dict) or 'items' not in catalog:
        errors.append('sr_catalog: items 를 가진 mapping 이어야 한다')
        return
    if is_blank(catalog.get('source')):
        errors.append('sr_catalog: source 가 비었다')
    items = catalog['items']
    _collect_ids(items, 'sr_catalog.items', SR_ID_RE, errors)
    rows = []
    for entry in items if isinstance(items, list) else []:
        if not isinstance(entry, dict):
            continue
        label = 'sr_catalog {}'.format(entry.get('id'))
        if _check_keys(entry, SR_KEYS, (), label, errors):
            if is_blank(entry['name']):
                errors.append('{}: name 이 비었다'.format(label))
            if entry['priority'] not in ('O', 'R'):
                errors.append('{}: priority 는 O 또는 R: {!r}'.format(label, entry['priority']))
            rows.append((entry['id'], entry['name'], entry['priority']))
    _compare_sr_catalog(rows, errors)


def _validate_roles(roles, errors):
    if not isinstance(roles, dict) or not roles:
        errors.append('roles: 비어 있지 않은 mapping 이어야 한다')
        return set()
    for key, role in roles.items():
        label = 'roles {}'.format(key)
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append('{}: 키는 소문자 snake_case'.format(label))
        if not isinstance(role, dict):
            errors.append('{}: mapping 이어야 한다'.format(label))
            continue
        if not _check_keys(role, ROLE_KEYS, ('notes',), label, errors):
            continue
        if is_blank(role['name']):
            errors.append('{}: name 이 비었다'.format(label))
        for field in ('packages', 'members', 'notes'):
            value = role.get(field, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append('{}: {} 는 문자열 목록'.format(label, field))
    return {key for key in roles if isinstance(key, str)}


def _validate_screens(screens, errors):
    ids = _collect_ids(screens, 'screens', KEY_RE, errors)
    for entry in screens if isinstance(screens, list) else []:
        if not isinstance(entry, dict):
            continue
        label = 'screens {}'.format(entry.get('id'))
        if _check_keys(entry, SCREEN_KEYS, ('notes',), label, errors):
            for field in ('label', 'name', 'phase_note'):
                if is_blank(entry[field]):
                    errors.append('{}: {} 이 비었다'.format(label, field))
            if 'notes' in entry and not _is_str_list(entry['notes']):
                errors.append('{}: notes 는 문자열 목록'.format(label))
    return set(ids)


def _validate_phases(phases, errors):
    # 단계 ID(P1~P5)는 검사 규칙이라 코드에 있고, 제목과 로드맵 단계는 YAML 이 갖는다.
    if not isinstance(phases, list):
        errors.append('phases: 목록이어야 한다')
        return
    ids = []
    stages = []
    for index, entry in enumerate(phases):
        label = 'phases[{}]'.format(index)
        if not isinstance(entry, dict):
            errors.append('{}: mapping 이어야 한다'.format(label))
            continue
        if not _check_keys(entry, PHASE_KEYS, (), label, errors):
            continue
        ids.append(entry['id'])
        if is_blank(entry['title']) or not isinstance(entry['title'], str):
            errors.append('{}: title 이 비었다'.format(label))
        stage = entry['roadmap_stage']
        if not isinstance(stage, str) or not STAGE_RE.match(stage):
            errors.append('{}: roadmap_stage 형식은 S<숫자>: {!r}'.format(label, stage))
        else:
            stages.append(stage)
    if ids != list(ACTIVE_PHASES):
        errors.append('phases: id 는 {} 순서여야 한다: {}'.format(
            ', '.join(ACTIVE_PHASES), ids))
    for dup in _duplicates(stages):
        errors.append('phases: 중복 roadmap_stage: {}'.format(dup))


def _validate_decisions(decisions, errors):
    ids = _collect_ids(decisions, 'decisions', DECISION_ID_RE, errors)
    for entry in decisions if isinstance(decisions, list) else []:
        if not isinstance(entry, dict):
            continue
        label = 'decisions {}'.format(entry.get('id'))
        if _check_keys(entry, DECISION_KEYS, (), label, errors):
            if is_blank(entry['title']):
                errors.append('{}: title 이 비었다'.format(label))
            if entry['status'] not in DECISION_STATUSES:
                errors.append('{}: status 는 {} 중 하나'.format(label, DECISION_STATUSES))
    return set(ids)


def _validate_sr_original(menu, label, errors):
    # sr_original 은 메뉴 트리 원문의 매핑이다. 있으면 '원문과 다르다' 는 표시다.
    if 'sr_original' not in menu:
        return
    original = menu['sr_original']
    if not _is_str_list(original):
        errors.append('{}: sr_original 은 문자열 목록이어야 한다 ([] 가능)'.format(label))
        return
    for item in original:
        if not ORIGINAL_REF_RE.match(item):
            errors.append('{}: sr_original 형식이 틀렸다: {}'.format(label, item))
    for dup in _duplicates(original):
        errors.append('{}: sr_original 중복: {}'.format(label, dup))
    if set(original) == set(menu['sr']) | set(menu['sr_unconfirmed']):
        errors.append('{}: sr_original 이 지금 매핑과 같다. sr_original 을 지운다'.format(label))


def _validate_menu_lists(menu, label, ctx, errors):
    lists_ok = True
    for key in MENU_LIST_KEYS:
        value = menu[key]
        if not isinstance(value, list):
            errors.append('{}: {} 는 목록이어야 한다 ([] 가능)'.format(label, key))
            lists_ok = False
            continue
        if not _is_str_list(value):
            errors.append('{}: {} 에 빈 값이나 문자열이 아닌 값이 있다'.format(label, key))
            lists_ok = False
            continue
        for dup in _duplicates(value):
            errors.append('{}: {} 중복: {}'.format(label, key, dup))
    if not lists_ok:
        return
    for sr_id in menu['sr']:
        if sr_id not in ctx['sr']:
            errors.append('{}: sr 에 {} 목록에 없는 ID: {}'.format(label, SR_VERSION, sr_id))
    for sr_id in menu['sr_unconfirmed']:
        if not SR_ID_RE.match(sr_id):
            errors.append('{}: sr_unconfirmed 형식이 틀렸다: {}'.format(label, sr_id))
        if sr_id in ctx['sr']:
            errors.append('{}: {} 는 {} 에 있으므로 sr 로 옮긴다'.format(
                label, sr_id, SR_VERSION))
        if sr_id in menu['sr']:
            errors.append('{}: {} 가 sr 과 sr_unconfirmed 에 함께 있다'.format(label, sr_id))
    for decision_id in menu['decisions']:
        if decision_id not in ctx['decisions']:
            errors.append('{}: decisions 에 없는 결정 ID: {}'.format(label, decision_id))
    _validate_sr_original(menu, label, errors)


def _validate_menu_placement(menu, label, ctx, errors):
    phase = menu['phase']
    status = menu['status']
    screen = menu['screen']
    also = menu.get('also_shown_in', [])
    if phase not in ACTIVE_PHASES + (REMOVED,):
        errors.append('{}: phase 는 P1~P5 또는 removed: {!r}'.format(label, phase))
    if status not in STATUSES:
        errors.append('{}: status 는 {} 중 하나: {!r}'.format(label, STATUSES, status))
    if (phase == REMOVED) != (status == REMOVED):
        errors.append('{}: phase 와 status 는 함께 removed 이거나 함께 아니어야 한다'.format(label))
    if not isinstance(also, list) or not all(isinstance(s, str) for s in also):
        errors.append('{}: also_shown_in 은 문자열 목록'.format(label))
        also = []
    if status == REMOVED or phase == REMOVED:
        if not is_blank(screen):
            errors.append('{}: 없앤 메뉴는 화면이 없어야 한다: {!r}'.format(label, screen))
        if also:
            errors.append('{}: 없앤 메뉴는 also_shown_in 이 없어야 한다'.format(label))
        return
    if not isinstance(screen, str) or screen not in ctx['screens']:
        errors.append('{}: 활성 메뉴는 화면 하나에 속해야 한다: {!r}'.format(label, screen))
    for other in also:
        if other not in ctx['screens']:
            errors.append('{}: also_shown_in 에 없는 화면: {}'.format(label, other))
        if other == screen:
            errors.append('{}: also_shown_in 에 주 화면을 다시 적었다'.format(label))
    for dup in _duplicates(also):
        errors.append('{}: also_shown_in 중복: {}'.format(label, dup))


def _validate_menu_owners(menu, label, ctx, errors):
    for key in OWNER_KEYS:
        value = menu[key]
        if value is None:
            continue
        if not isinstance(value, str):
            errors.append('{}: {} 는 문자열 (역할 키)'.format(label, key))
        elif value.strip() and value not in ctx['roles']:
            errors.append('{}: {} 가 roles 키가 아니다: {}'.format(label, key, value))
    branch = menu.get('branch')
    if menu['status'] == IN_PROGRESS and is_blank(branch):
        errors.append('{}: in_progress 메뉴는 branch 가 있어야 한다'.format(label))
    if not is_blank(branch) and (not isinstance(branch, str) or not BRANCH_RE.match(branch)):
        errors.append('{}: branch 형식이 틀렸다 (feature/... 또는 fix/...): {!r}'.format(
            label, branch))


def _validate_menu(menu, index, ctx, errors):
    if not isinstance(menu, dict):
        errors.append('menus[{}]: mapping 이어야 한다'.format(index))
        return None
    menu_id = menu.get('id')
    label = 'menu {}'.format(menu_id if menu_id is not None else '#{}'.format(index))
    if not _check_keys(menu, MENU_KEYS, OPTIONAL_MENU_KEYS, label, errors):
        return None
    if not isinstance(menu_id, str):
        errors.append('{}: id 는 따옴표로 감싼 문자열이어야 한다: {!r}'.format(label, menu_id))
        return None
    match = MENU_ID_RE.match(menu_id)
    if match is None:
        errors.append('{}: id 형식은 <숫자>.<숫자>'.format(label))
        return None
    if is_blank(menu['name']):
        errors.append('{}: name 이 비었다'.format(label))
    depth1 = menu['depth1']
    depth1_match = DEPTH1_RE.match(depth1) if isinstance(depth1, str) else None
    if depth1_match is None:
        errors.append('{}: depth1 형식은 "NN. 이름": {!r}'.format(label, depth1))
    elif int(depth1_match.group(1)) != int(match.group(1)):
        errors.append('{}: depth1 번호가 메뉴 ID 앞자리와 다르다: {}'.format(label, depth1))
    _validate_menu_lists(menu, label, ctx, errors)
    _validate_menu_placement(menu, label, ctx, errors)
    _validate_menu_owners(menu, label, ctx, errors)
    return menu_id


def _compare_menus(names_by_id, errors):
    # 메뉴 목록을 코드의 고정 사본(AGREED_MENUS)과 대조한다. YAML 에서 메뉴를 지우고
    # 문서를 다시 만들어도 이 검사가 걸린다.
    pinned = dict(AGREED_MENUS)
    for menu_id, _ in AGREED_MENUS:
        if menu_id not in names_by_id:
            errors.append('menus: 빠진 메뉴 ID: {}'.format(menu_id))
    for extra in sorted(set(names_by_id) - set(pinned), key=menu_sort_key):
        errors.append('menus: 합의 목록에 없는 메뉴 ID: {}'.format(extra))
    for menu_id, name in AGREED_MENUS:
        if menu_id in names_by_id and names_by_id[menu_id] != name:
            errors.append('menu {}: 이름이 합의 목록과 다르다: {!r} (합의 {!r})'.format(
                menu_id, names_by_id[menu_id], name))


def validate(registry):
    """
    레지스트리를 검사하고 오류 목록을 돌려준다.

    메뉴 목록과 SR 사본은 이 모듈의 고정 사본(AGREED_MENUS, SR_V5)과도 대조한다.
    빈 담당 칸은 오류가 아니다. find_warnings() 가 따로 돌려준다.

    :param registry: load_registry() 가 돌려준 값
    :return: 오류 문자열 목록 (빈 목록이면 통과)
    """
    errors = []
    if not isinstance(registry, dict):
        return ['레지스트리 최상위가 mapping 이 아니다']
    if not _check_keys(registry, TOP_KEYS, OPTIONAL_TOP_KEYS, '최상위', errors):
        return errors
    if registry['schema_version'] != SCHEMA_VERSION:
        errors.append('schema_version 은 {} 이어야 한다: {!r}'.format(
            SCHEMA_VERSION, registry['schema_version']))
    if not isinstance(registry['source'], dict) or not registry['source']:
        errors.append('source: 비어 있지 않은 mapping 이어야 한다')
    if 'notes' in registry and not _is_str_list(registry['notes']):
        errors.append('notes: 문자열 목록이어야 한다')
    _validate_sr_catalog(registry['sr_catalog'], errors)
    _validate_phases(registry['phases'], errors)
    ctx = {
        # 메뉴의 sr 은 YAML 사본이 아니라 고정 사본에 대고 본다.
        'sr': {sr_id for sr_id, _, _ in SR_V5},
        'roles': _validate_roles(registry['roles'], errors),
        'screens': _validate_screens(registry['screens'], errors),
        'decisions': _validate_decisions(registry['decisions'], errors),
    }
    menus = registry['menus']
    if not isinstance(menus, list) or not menus:
        errors.append('menus: 비어 있지 않은 목록이어야 한다')
        return errors
    menu_ids = []
    names_by_id = {}
    for index, menu in enumerate(menus):
        menu_id = _validate_menu(menu, index, ctx, errors)
        if menu_id is not None:
            menu_ids.append(menu_id)
            names_by_id[menu_id] = menu['name']
    for dup in _duplicates(menu_ids):
        errors.append('menus: 중복 메뉴 ID: {}'.format(dup))
    _compare_menus(names_by_id, errors)
    return errors


def find_warnings(registry):
    """
    활성 메뉴의 빈 담당 칸(screen_owner, data_owner)을 경고 목록으로 돌려준다.

    없앤(removed) 메뉴는 보지 않는다. 결과는 메뉴 ID 순서다.

    :param registry: load_registry() 가 돌려준 값
    :return: 경고 문자열 목록
    """
    warnings = []
    menus = registry.get('menus') if isinstance(registry, dict) else None
    if not isinstance(menus, list):
        return warnings
    active = []
    for menu in menus:
        if not isinstance(menu, dict):
            continue
        if REMOVED in (menu.get('status'), menu.get('phase')):
            continue
        active.append(menu)
    for menu in sorted(active, key=lambda item: menu_sort_key(item.get('id'))):
        for key in OWNER_KEYS:
            if is_blank(menu.get(key)):
                warnings.append('menu {}: {} 빈 칸'.format(menu.get('id'), key))
    return warnings


def main(argv=None):
    """
    check_menu_tree 명령의 진입점.

    오류가 있으면 1, 레지스트리를 찾거나 읽지 못하면 2, 통과하면 0 을 돌려준다.
    빈 담당 칸은 경고로만 남긴다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(description='메뉴 레지스트리(menu_tree.yaml)를 검사한다.')
    parser.add_argument('--registry', help='menu_tree.yaml 경로 (기본: 레포 루트에서 찾는다)')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    path = args.registry
    if path is None:
        root = find_repo_root()
        if root is None:
            LOGGER.error('레포 루트를 찾지 못했다. --registry 로 경로를 준다.')
            return 2
        path = os.path.join(root, REGISTRY_RELPATH)
    registry, errors = read_registry(path)
    if registry is None:
        for error in errors:
            LOGGER.error(error)
        return 2
    errors = validate(registry)
    for warning in find_warnings(registry):
        LOGGER.warning(warning)
    for error in errors:
        LOGGER.error(error)
    if errors:
        LOGGER.error('실패: 오류 %d건', len(errors))
        return 1
    LOGGER.info('통과: 메뉴 %d개, 오류 0건', len(registry['menus']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
