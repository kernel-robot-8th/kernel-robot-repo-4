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
메뉴 레지스트리에서 docs/fms_menu_tree.md 를 만든다.

같은 레지스트리에서는 늘 같은 바이트가 나온다. 시각·경로·환경 값을 넣지 않고,
줄 끝은 LF 다. --check 를 주면 파일을 쓰지 않고 차이만 본다.
레포 루트(또는 그 아래 폴더)에서 돌린다. 다른 곳에서는 --root 를 준다.
"""

import argparse
import logging
import os
import sys
import tempfile

from cobot_gui import menu_registry

LOGGER = logging.getLogger(__name__)

DOC_RELPATH = os.path.join('docs', 'fms_menu_tree.md')
REGISTRY_DISPLAY_PATH = 'src/cobot_gui/config/menu_tree.yaml'
REGEN_COMMAND = 'PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_menu_doc'
ROS_REGEN_COMMAND = 'ros2 run cobot_gui gen_menu_doc'
EMPTY = '—'
CHANGED_MARK = '✱'
REMOVED_TITLE = '없앰 (removed)'


def _phase_titles(registry):
    # 단계 제목은 레지스트리 phases 에서 읽는다. 없앤 메뉴 줄만 여기서 붙인다.
    titles = [
        (phase['id'], '{} {} (로드맵 {})'.format(
            phase['id'], phase['title'], phase['roadmap_stage']))
        for phase in registry['phases']
    ]
    titles.append((menu_registry.REMOVED, REMOVED_TITLE))
    return titles


def _cell(value):
    # 표 칸 안에서 | 와 줄바꿈이 표를 깨지 않게 한다.
    text = str(value).replace('\r', ' ').replace('\n', ' ').strip()
    return text.replace('|', '\\|') if text else EMPTY


def _join(items):
    return ', '.join(items) if items else EMPTY


def _role_name(roles, key):
    if menu_registry.is_blank(key):
        return '(빈 칸)'
    return roles[key]['name']


def _screen_label(screens, screen_id):
    if menu_registry.is_blank(screen_id):
        return EMPTY
    return screens[screen_id]['label']


def _sorted_menus(registry):
    return sorted(registry['menus'], key=lambda menu: menu_registry.menu_sort_key(menu['id']))


def _decision_refs(registry, decision_ids):
    # 메뉴 표의 결정 칸. 결정마다 지금 상태를 붙인다 (예: D3 (proposed)).
    status = {d['id']: d['status'] for d in registry['decisions']}
    return _join(['{} ({})'.format(d, status[d]) for d in decision_ids])


def _decision_status_cell(decision):
    # decided 면 결정자와 날짜를 상태 칸에 함께 보인다.
    if decision['status'] != menu_registry.DECISION_DECIDED:
        return decision['status']
    return '{} ({}, {})'.format(
        decision['status'], decision['decided_by'], decision['decided_on'])


def _record_link(record):
    # record 는 레포 루트 기준(docs/...)이다. 생성 문서도 docs/ 에 있으므로 docs/ 를 뗀다.
    prefix = 'docs/'
    target = record[len(prefix):] if record.startswith(prefix) else record
    return '[`{}`]({})'.format(record, target)


def _impl_cell(menu):
    if menu['status'] == menu_registry.REMOVED:
        return EMPTY
    return menu_registry.IMPL_LABELS[menu.get('impl', menu_registry.IMPL_NONE)]


def _sr_cell(menu):
    # 확인이 필요한 ID 도 표에 보이고, 원문과 매핑이 다르면 표시를 붙인다.
    items = list(menu['sr'])
    items.extend('{} (확인 필요)'.format(sr_id) for sr_id in menu['sr_unconfirmed'])
    text = _join(items)
    if 'sr_original' in menu:
        text = '{} {}'.format(text, CHANGED_MARK)
    return text


def _render_header(registry, add):
    add('<!-- 자동 생성 파일. 직접 고치지 말 것. 원본: {} -->'.format(REGISTRY_DISPLAY_PATH))
    add('')
    add('# FMS 메뉴 트리')
    add('')
    add('> **자동 생성 문서다. 직접 고치지 말 것.**')
    add('>')
    add('> - 원본: `{}`'.format(REGISTRY_DISPLAY_PATH))
    add('> - 재생성 (레포 루트에서): `{}`'.format(REGEN_COMMAND))
    add('>   - ROS 환경 (`colcon build` 뒤): `{}`'.format(ROS_REGEN_COMMAND))
    add('> - 검사: 위 명령 뒤에 `--check` 를 붙인다. 차이가 있으면 종료코드 1 이다.')
    add('> - 고치는 순서와 규칙: `docs/fms_dev_rules.md`, 단계: `docs/fms_roadmap.md`')
    add('> - schema_version: {}'.format(registry['schema_version']))
    add('')
    add('## 출처')
    add('')
    for key, value in registry['source'].items():
        add('- {}: {}'.format(key, value))
    add('')
    add('## 읽는 법')
    add('')
    add('- 메뉴 하나 = 작업 단위 하나다. 레지스트리에 없는 화면·도구는 만들지 않는다.')
    add('- 단계(phase)는 그 메뉴 작업이 처음 시작되는 단계다. 뒤 단계 범위는 메모에 있다.')
    add("- 메모에서 '초안:' 으로 시작하는 줄은 판단이 들어간 값이다. 팀 확인 전이다.")
    add('- SR 칸의 {} 는 메뉴 트리 원문과 SR 매핑이 다른 메뉴다. 원문 값과 이유는 그 메뉴의 '
        '상세에 있다.'.format(CHANGED_MARK))
    add('- 결정 상태: `open` 은 미결, `proposed` 는 추천안이 있고 공지 전, `decided` 는 공지했고 '
        '결정자·날짜를 적은 것이다. `decided` 만 정해진 것으로 본다. 기록: `{}`'.format(
            menu_registry.DECISION_RECORD_DOC))
    for note in registry.get('notes', []):
        add('- {}'.format(note))
    add('')


def _render_summary(registry, add):
    menus = registry['menus']
    removed = [m for m in menus if m['status'] == menu_registry.REMOVED]
    add('## 요약')
    add('')
    add('| 구분 | 수 |')
    add('|---|---|')
    add('| 메뉴 전체 | {} |'.format(len(menus)))
    add('| 활성 | {} |'.format(len(menus) - len(removed)))
    for phase, title in _phase_titles(registry):
        count = len([m for m in menus if m['phase'] == phase])
        add('| {} | {} |'.format(title, count))
    for status in menu_registry.STATUSES:
        count = len([m for m in menus if m['status'] == status])
        add('| 상태 {} | {} |'.format(status, count))
    for level in menu_registry.IMPL_LEVELS:
        count = len([m for m in menus if m.get('impl', menu_registry.IMPL_NONE) == level
                     and m['status'] != menu_registry.REMOVED])
        add('| 구현도 {} | {} |'.format(menu_registry.IMPL_LABELS[level], count))
    add('| 원문과 SR 매핑이 다른 메뉴 ({}) | {} |'.format(
        CHANGED_MARK, len([m for m in menus if 'sr_original' in m])))
    add('| 화면 | {} |'.format(len(registry['screens'])))
    for status in menu_registry.DECISION_STATUSES:
        count = len([d for d in registry['decisions'] if d['status'] == status])
        add('| 결정 {} | {} |'.format(status, count))
    add('')


def _render_screens(registry, add):
    menus = _sorted_menus(registry)
    add('## 화면별 메뉴')
    add('')
    add('| 화면 | 이름 | 단계 | 주 화면인 메뉴 | 함께 보이는 메뉴 | 메모 |')
    add('|---|---|---|---|---|---|')
    for screen in registry['screens']:
        own = [m['id'] for m in menus if m['screen'] == screen['id']]
        also = [m['id'] for m in menus if screen['id'] in m.get('also_shown_in', [])]
        add('| {} | {} | {} | {} | {} | {} |'.format(
            _cell(screen['label']), _cell(screen['name']), _cell(screen['phase_note']),
            _cell(_join(own)), _cell(_join(also)), _cell(' '.join(screen.get('notes', [])))))
    add('')


def _render_phases(registry, add):
    menus = _sorted_menus(registry)
    add('## 단계별 메뉴')
    add('')
    add('| 단계 | 메뉴 |')
    add('|---|---|')
    for phase, title in _phase_titles(registry):
        ids = [m['id'] for m in menus if m['phase'] == phase]
        add('| {} | {} |'.format(_cell(title), _cell(_join(ids))))
    add('')


def _render_menu_detail(registry, menu, add):
    screens = {s['id']: s for s in registry['screens']}
    add('#### {} {}'.format(menu['id'], menu['name']))
    add('')
    add('- 데이터 원천: {}'.format(_join(menu['data_sources'])))
    add('- 명령: {}'.format(_join(menu['commands']) if menu['commands'] else '없음'))
    also = menu.get('also_shown_in', [])
    if also:
        add('- 함께 보이는 화면: {}'.format(_join([screens[s]['label'] for s in also])))
    if menu['sr_unconfirmed']:
        add('- SR 확인 필요 ({} 에 없음): {}'.format(
            menu_registry.SR_VERSION, _join(menu['sr_unconfirmed'])))
    if 'sr_original' in menu:
        original = _join(menu['sr_original']) if menu['sr_original'] else '없음'
        add('- {} 원문 SR: {} (지금 매핑과 다르다. 이유는 아래 메모)'.format(
            CHANGED_MARK, original))
    if not menu_registry.is_blank(menu.get('branch')):
        add('- 작업 브랜치: `{}`'.format(menu['branch']))
    if menu.get('impl', menu_registry.IMPL_NONE) != menu_registry.IMPL_NONE:
        add('- 구현도: {} — {}'.format(_impl_cell(menu), menu['impl_ref']))
    for note in menu['notes']:
        add('- {}'.format(note))
    add('')


def _render_menus(registry, add):
    roles = registry['roles']
    screens = {s['id']: s for s in registry['screens']}
    menus = _sorted_menus(registry)
    add('## 메뉴')
    add('')
    groups = []
    for menu in menus:
        if menu['depth1'] not in groups:
            groups.append(menu['depth1'])
    for group in groups:
        members = [m for m in menus if m['depth1'] == group]
        add('### {}'.format(group))
        add('')
        add('| ID | 이름 | 화면 | 단계 | 상태 | 구현도 | SR | 화면 담당 | 데이터 담당 | 결정 | 관제 영역 | 관제 구현 담당 |')
        add('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for menu in members:
            add('| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
                _cell(menu['id']), _cell(menu['name']),
                _cell(_screen_label(screens, menu['screen'])), _cell(menu['phase']),
                _cell(menu['status']), _cell(_impl_cell(menu)), _cell(_sr_cell(menu)),
                _cell(_role_name(roles, menu['screen_owner'])),
                _cell(_role_name(roles, menu['data_owner'])),
                _cell(_decision_refs(registry, menu['decisions'])),
                menu_registry.CONTROL_AREAS[menu['control_area']],
                _cell(_role_name(roles, menu['control_owner']))))
        add('')
        for menu in members:
            _render_menu_detail(registry, menu, add)


def _render_reference(registry, add):
    menus = _sorted_menus(registry)
    add('## 담당 칸 경고')
    add('')
    warnings = menu_registry.find_warnings(registry)
    if warnings:
        for warning in warnings:
            add('- {}'.format(warning))
    else:
        add('- 없음')
    add('')
    add('## 역할')
    add('')
    add('| 키 | 역할 | 담당 패키지 | 담당자 | 메모 |')
    add('|---|---|---|---|---|')
    for key, role in registry['roles'].items():
        add('| `{}` | {} | {} | {} | {} |'.format(
            key, _cell(role['name']), _cell(_join(role['packages'])),
            _cell(_join(role['members'])), _cell(' '.join(role.get('notes', [])))))
    add('')
    add('## SR 목록 (사본)')
    add('')
    add('- 출처: {}'.format(registry['sr_catalog']['source']))
    add('- 검사: 이 표는 `menu_registry.py` 의 고정 사본(`SR_CANON`)과 ID·이름·우선순위·순서가 '
        '같아야 한다.')
    add('')
    add('| ID | 이름 | 우선순위 | 연결된 메뉴 |')
    add('|---|---|---|---|')
    for item in registry['sr_catalog']['items']:
        linked = [m['id'] for m in menus if item['id'] in m['sr']]
        add('| {} | {} | {} | {} |'.format(
            item['id'], _cell(item['name']), item['priority'], _cell(_join(linked))))
    add('')
    add('## 결정 목록')
    add('')
    add("- 상태 뜻은 위 '읽는 법' 에 있다. 질문·선택지·이유는 결정 기록(`{}`)에 있다.".format(
        menu_registry.DECISION_RECORD_DOC))
    add('')
    add('| ID | 결정 | 상태 | 막는 것 | 기다리는 메뉴 |')
    add('|---|---|---|---|---|')
    for decision in registry['decisions']:
        waiting = [m['id'] for m in menus if decision['id'] in m['decisions']]
        add('| {} | {} | {} | {} | {} |'.format(
            decision['id'], _cell(decision['title']), _cell(_decision_status_cell(decision)),
            _cell(decision['blocks']), _cell(_join(waiting))))
    proposed = [d for d in registry['decisions'] if d['status'] != menu_registry.DECISION_OPEN]
    if not proposed:
        return
    add('')
    add('### 추천안·결정 내용')
    add('')
    for decision in proposed:
        add('- {} ({}): {} — 기록: {}'.format(
            decision['id'], _decision_status_cell(decision), decision['proposal'],
            _record_link(decision['record'])))


def render(registry):
    """
    검사를 통과한 레지스트리를 Markdown 문자열로 바꾼다.

    메뉴는 ID 숫자 순서로 정렬하므로 YAML 안의 메뉴 순서와 무관하다.

    :param registry: validate() 가 빈 목록을 돌려준 레지스트리
    :return: 문서 전체 문자열 (줄 끝 LF, 마지막 줄바꿈 1개)
    """
    lines = []
    add = lines.append
    _render_header(registry, add)
    _render_summary(registry, add)
    _render_screens(registry, add)
    _render_phases(registry, add)
    _render_menus(registry, add)
    _render_reference(registry, add)
    while lines and lines[-1] == '':
        lines.pop()
    return '\n'.join(lines) + '\n'


def is_up_to_date(text, path):
    """
    주어진 path 의 파일이 text 와 바이트 단위로 같으면 True 를 돌려준다.

    :param text: render() 결과
    :param path: 비교할 문서 경로
    :return: 같으면 True, 다르거나 파일이 없으면 False
    """
    try:
        with open(path, 'rb') as stream:
            current = stream.read()
    except OSError:
        return False
    return current == text.encode('utf-8')


def write_doc(text, path):
    """
    주어진 text 를 UTF-8, LF 로 path 에 쓴다.

    임시 파일에 쓴 뒤 바꿔 넣어서, 중간에 멈춰도 반쯤 쓴 문서가 남지 않게 한다.

    :param text: render() 결과
    :param path: 쓸 문서 경로
    """
    directory = os.path.dirname(os.path.abspath(path))
    handle, tmp_path = tempfile.mkstemp(prefix='.fms_menu_tree.', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(text.encode('utf-8'))
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def main(argv=None):
    """
    gen_menu_doc 명령의 진입점.

    레지스트리에 오류가 있거나 --check 에서 차이가 있으면 1, 경로를 찾지 못하면 2,
    정상이면 0 을 돌려준다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(
        description='메뉴 레지스트리에서 docs/fms_menu_tree.md 를 만든다.')
    parser.add_argument('--root', help='레포 루트 (기본: 현재 폴더에서 위로 찾는다)')
    parser.add_argument('--registry', help='menu_tree.yaml 경로 (기본: <root>/{})'.format(
        menu_registry.REGISTRY_RELPATH))
    parser.add_argument('--output', help='문서 경로 (기본: <root>/{})'.format(DOC_RELPATH))
    parser.add_argument(
        '--check', action='store_true',
        help='파일을 쓰지 않는다. 문서가 레지스트리와 다르면 종료코드 1')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = args.root
    if root is None and (args.registry is None or args.output is None):
        root = menu_registry.find_repo_root()
        if root is None:
            LOGGER.error('레포 루트를 찾지 못했다. --root 를 준다.')
            return 2
    registry_path = args.registry or os.path.join(root, menu_registry.REGISTRY_RELPATH)
    output_path = args.output or os.path.join(root, DOC_RELPATH)
    registry, errors = menu_registry.read_registry(registry_path)
    if registry is None:
        for error in errors:
            LOGGER.error(error)
        return 2
    errors = menu_registry.validate(registry)
    if errors:
        for error in errors:
            LOGGER.error(error)
        LOGGER.error('레지스트리 오류 %d건. 문서를 만들지 않았다.', len(errors))
        return 1
    text = render(registry)
    if args.check:
        if is_up_to_date(text, output_path):
            LOGGER.info('일치: %s', output_path)
            return 0
        LOGGER.error('불일치: %s 가 레지스트리와 다르다. 재생성: %s', output_path, REGEN_COMMAND)
        return 1
    write_doc(text, output_path)
    LOGGER.info('썼다: %s (메뉴 %d개)', output_path, len(registry['menus']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
