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
메뉴 레지스트리에서 웹 화면이 쓰는 web/src/generated/menus.ts 를 만든다.

메뉴 이름·순서·화면·단계는 레지스트리(menu_tree.yaml)만 고친다. 이 파일은 거기서 생성한다.
같은 레지스트리에서는 늘 같은 바이트가 나온다. 시각·경로·환경 값을 넣지 않고, 줄 끝은 LF 다.
--check 를 주면 파일을 쓰지 않고 차이만 본다. 레포 루트(또는 그 아래 폴더)에서 돌린다.
"""

import argparse
import json
import logging
import os
import sys
import tempfile

from cobot_gui import menu_registry

LOGGER = logging.getLogger(__name__)

TS_RELPATH = os.path.join('src', 'cobot_gui', 'web', 'src', 'generated', 'menus.ts')
REGEN_COMMAND = 'PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_menus'
ROS_REGEN_COMMAND = 'ros2 run cobot_gui gen_web_menus'
HEADER = (
    '// 자동 생성 파일이다. 직접 고치지 말 것.\n'
    '// 원본: src/cobot_gui/config/menu_tree.yaml\n'
    '// 재생성: {}\n'
    '// 확인: {} --check\n'
)


def _menu(menu):
    """레지스트리 메뉴 한 개를 웹 화면이 쓰는 이름(camelCase)으로 바꾼다."""
    out = {
        'id': menu['id'],
        'name': menu['name'],
        'depth1': menu['depth1'],
        'screen': menu['screen'] or '',
        'alsoShownIn': list(menu.get('also_shown_in', [])),
        'phase': menu['phase'],
        'status': menu['status'],
        'impl': menu.get('impl', menu_registry.IMPL_NONE),
        'implRef': menu.get('impl_ref', ''),
        'sr': list(menu['sr']),
        'srOriginal': list(menu['sr_original']) if 'sr_original' in menu else None,
        'srUnconfirmed': list(menu['sr_unconfirmed']),
        'dataSources': list(menu['data_sources']),
        'commands': list(menu['commands']),
        'controlArea': menu['control_area'],
        'controlOwner': menu['control_owner'],
        'screenOwner': menu['screen_owner'] or '',
        'dataOwner': menu['data_owner'] or '',
        'decisions': list(menu['decisions']),
        'notes': list(menu['notes']),
        'branch': menu.get('branch', ''),
    }
    return out


def _decision(decision):
    return {
        'id': decision['id'],
        'title': decision['title'],
        'status': decision['status'],
        'blocks': decision['blocks'],
        'proposal': decision.get('proposal', ''),
        'record': decision.get('record', ''),
        'decidedBy': decision.get('decided_by', ''),
        'decidedOn': str(decision.get('decided_on', '')),
    }


def _const(name, type_name, value):
    body = json.dumps(value, ensure_ascii=False, indent=2)
    return 'export const {}: {} = {};\n'.format(name, type_name, body)


def render(registry):
    """
    검사를 통과한 레지스트리를 TypeScript 파일 문자열로 바꾼다.

    메뉴는 ID 숫자 순서로 정렬하므로 YAML 안의 메뉴 순서와 무관하다.

    :param registry: validate() 가 빈 목록을 돌려준 레지스트리
    :return: 파일 전체 문자열 (줄 끝 LF, 마지막 줄바꿈 1개)
    """
    menus = sorted(registry['menus'], key=lambda m: menu_registry.menu_sort_key(m['id']))
    parts = [
        HEADER.format(REGEN_COMMAND, REGEN_COMMAND),
        'import type { Decision, Menu, Phase, Role, Screen, SrItem } from "../shell/types";\n',
        _const('SCREENS', 'Screen[]', [
            {'id': s['id'], 'label': s['label'], 'name': s['name'],
             'phaseNote': s.get('phase_note', '')} for s in registry['screens']]),
        _const('PHASES', 'Phase[]', [
            {'id': p['id'], 'title': p['title'], 'roadmapStage': p['roadmap_stage']}
            for p in registry['phases']]),
        _const('ROLES', 'Role[]', [
            {'key': key, 'name': role['name'], 'members': list(role['members'])}
            for key, role in registry['roles'].items()]),
        _const('SR_CATALOG', 'SrItem[]', [
            {'id': i['id'], 'name': i['name'], 'priority': i['priority']}
            for i in registry['sr_catalog']['items']]),
        _const('DECISIONS', 'Decision[]', [_decision(d) for d in registry['decisions']]),
        _const('MENUS', 'Menu[]', [_menu(m) for m in menus]),
    ]
    return '\n'.join(parts)


def is_up_to_date(text, path):
    """
    주어진 path 의 파일이 text 와 바이트 단위로 같으면 True 를 돌려준다.

    :param text: render() 결과
    :param path: 비교할 파일 경로
    :return: 같으면 True, 다르거나 파일이 없으면 False
    """
    try:
        with open(path, 'rb') as stream:
            current = stream.read()
    except OSError:
        return False
    return current == text.encode('utf-8')


def write_ts(text, path):
    """
    주어진 text 를 UTF-8, LF 로 path 에 쓴다.

    임시 파일에 쓴 뒤 바꿔 넣어서, 중간에 멈춰도 반쯤 쓴 파일이 남지 않게 한다.

    :param text: render() 결과
    :param path: 쓸 파일 경로
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, tmp_path = tempfile.mkstemp(prefix='.menus.', suffix='.tmp', dir=directory)
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
    gen_web_menus 명령의 진입점.

    레지스트리에 오류가 있거나 --check 에서 차이가 있으면 1, 경로를 찾지 못하면 2,
    정상이면 0 을 돌려준다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(
        description='메뉴 레지스트리에서 web/src/generated/menus.ts 를 만든다.')
    parser.add_argument('--root', help='레포 루트 (기본: 현재 폴더에서 위로 찾는다)')
    parser.add_argument('--registry', help='menu_tree.yaml 경로 (기본: <root>/{})'.format(
        menu_registry.REGISTRY_RELPATH))
    parser.add_argument('--output', help='파일 경로 (기본: <root>/{})'.format(TS_RELPATH))
    parser.add_argument(
        '--check', action='store_true',
        help='파일을 쓰지 않는다. 파일이 레지스트리와 다르면 종료코드 1')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = args.root
    if root is None and (args.registry is None or args.output is None):
        root = menu_registry.find_repo_root()
        if root is None:
            LOGGER.error('레포 루트를 찾지 못했다. --root 를 준다.')
            return 2
    registry_path = args.registry or os.path.join(root, menu_registry.REGISTRY_RELPATH)
    output_path = args.output or os.path.join(root, TS_RELPATH)
    registry, errors = menu_registry.read_registry(registry_path)
    if registry is None:
        for error in errors:
            LOGGER.error(error)
        return 2
    errors = menu_registry.validate(registry)
    if errors:
        for error in errors:
            LOGGER.error(error)
        LOGGER.error('레지스트리 오류 %d건. 파일을 만들지 않았다.', len(errors))
        return 1
    text = render(registry)
    if args.check:
        if is_up_to_date(text, output_path):
            LOGGER.info('일치: %s', output_path)
            return 0
        LOGGER.error('불일치: %s 가 레지스트리와 다르다. 재생성: %s', output_path, REGEN_COMMAND)
        return 1
    write_ts(text, output_path)
    LOGGER.info('썼다: %s (메뉴 %d개)', output_path, len(registry['menus']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
