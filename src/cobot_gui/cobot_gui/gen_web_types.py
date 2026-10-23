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
cobot_interfaces 의 msg·srv·action 정의에서 web/src/generated/messages.ts 를 만든다.

웹 화면은 메시지 이름과 필드 이름을 인터페이스 패키지와 똑같이 쓴다. 이 도구가 정의 파일을 읽어
TypeScript 타입을 만들고, 모의 데이터(web/src/mock/<메시지>.json)가 정의와 맞는지 검사한다.
정의 파일은 읽기만 한다. 같은 정의에서는 늘 같은 바이트가 나온다 (시각·경로·환경 값 없음, 줄 끝 LF).
float 필드는 NaN(미측정)이 JSON 에서 null 이 되므로 null 을 허용하는 Float 로 만든다.
"""

import argparse
import copy
import json
import logging
import os
import re
import sys
import tempfile

from cobot_gui import menu_registry

LOGGER = logging.getLogger(__name__)

INTERFACES_RELPATH = os.path.join('src', 'cobot_interfaces')
TS_RELPATH = os.path.join('src', 'cobot_gui', 'web', 'src', 'generated', 'messages.ts')
MOCK_RELPATH = os.path.join('src', 'cobot_gui', 'web', 'src', 'mock')
REGEN_COMMAND = 'PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types'

# ROS 표준 메시지는 이 표가 정본이다 (타입 생성과 모의 데이터 검사가 같이 쓴다).
STD_TYPES = {
    'Time': [('int32', 'sec'), ('uint32', 'nanosec')],
    'Header': [('Time', 'stamp'), ('string', 'frame_id')],
    'Point': [('float64', 'x'), ('float64', 'y'), ('float64', 'z')],
    'Quaternion': [('float64', 'x'), ('float64', 'y'), ('float64', 'z'), ('float64', 'w')],
    'Pose': [('Point', 'position'), ('Quaternion', 'orientation')],
}
STD_PACKAGES = {
    'builtin_interfaces/Time': 'Time',
    'std_msgs/Header': 'Header',
    'geometry_msgs/Point': 'Point',
    'geometry_msgs/Quaternion': 'Quaternion',
    'geometry_msgs/Pose': 'Pose',
}
INT_RANGES = {
    'int8': (-2**7, 2**7 - 1), 'uint8': (0, 2**8 - 1),
    'int16': (-2**15, 2**15 - 1), 'uint16': (0, 2**16 - 1),
    'int32': (-2**31, 2**31 - 1), 'uint32': (0, 2**32 - 1),
    'int64': (-2**63, 2**63 - 1), 'uint64': (0, 2**64 - 1),
}
FLOATS = ('float32', 'float64')
FIELD_RE = re.compile(r'^([A-Za-z0-9_/]+)(\[(\d*)\])?\s+([a-z][a-z0-9_]*)$')
CONST_RE = re.compile(r'^([A-Za-z0-9_/]+)\s+([A-Z][A-Z0-9_]*)\s*=\s*(.+)$')
ENUM_RE = re.compile(r'위\s+([A-Z][A-Z0-9_]*)_\*\s*(중 하나|또는 "")')


class DefinitionError(Exception):
    """정의 파일을 읽지 못했다."""


def _split_comment(line):
    """따옴표 밖의 첫 # 로 본문과 주석을 나눈다."""
    quote = False
    for index, char in enumerate(line):
        if char == '"':
            quote = not quote
        elif char == '#' and not quote:
            return line[:index].strip(), line[index + 1:].strip()
    return line.strip(), ''


def _literal(type_name, text):
    text = text.strip()
    if type_name == 'string':
        if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
            return text[1:-1]
        return text
    if type_name == 'bool':
        return text.lower() in ('true', '1')
    if type_name in FLOATS:
        return float(text)
    return int(text, 0)


def parse_sections(text, label):
    """
    msg/srv/action 정의 한 파일을 구역 목록으로 바꾼다.

    구역은 --- 줄로 나뉜다 (msg 는 1개, srv 는 2개, action 은 3개).

    :param text: 파일 내용
    :param label: 오류 문구에 쓸 파일 이름
    :return: [{'constants': [(타입, 이름, 값, 주석)], 'fields': [(타입, 배열, 이름, 주석)]}]
    """
    sections = [{'constants': [], 'fields': []}]
    for number, raw in enumerate(text.replace('\r\n', '\n').split('\n'), 1):
        body, comment = _split_comment(raw)
        if raw.strip() == '---':
            sections.append({'constants': [], 'fields': []})
            continue
        if not body:
            continue
        const = CONST_RE.match(body)
        if const:
            value = _literal(const.group(1), const.group(3))
            sections[-1]['constants'].append((const.group(1), const.group(2), value, comment))
            continue
        field = FIELD_RE.match(body)
        if not field:
            raise DefinitionError('{}:{}: 읽을 수 없는 줄: {!r}'.format(label, number, raw))
        array = None
        if field.group(2):
            array = field.group(3) or ''
        sections[-1]['fields'].append((field.group(1), array, field.group(4), comment))
    return sections


def load_definitions(interfaces_dir):
    """
    인터페이스 패키지에서 msg·srv·action 정의를 모두 읽는다.

    :param interfaces_dir: src/cobot_interfaces 경로
    :return: {'msg': {이름: 구역 목록}, 'srv': {...}, 'action': {...}}
    :raises DefinitionError: 폴더가 없거나 정의에 오류가 있을 때
    """
    result = {}
    for kind, suffix in (('msg', '.msg'), ('srv', '.srv'), ('action', '.action')):
        folder = os.path.join(interfaces_dir, kind)
        if not os.path.isdir(folder):
            raise DefinitionError('폴더가 없다: {}'.format(folder))
        items = {}
        for name in sorted(os.listdir(folder)):
            if not name.endswith(suffix):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding='utf-8') as stream:
                items[name[:-len(suffix)]] = parse_sections(stream.read(), name)
        result[kind] = items
    if not result['msg']:
        raise DefinitionError('msg 정의가 하나도 없다: {}'.format(interfaces_dir))
    return result


def type_table(definitions):
    """타입 이름 → 필드 목록 [(타입, 배열, 이름, 주석)] 표를 만든다. 구역은 이름 뒤에 접미사를 붙인다."""
    table = {}
    for name, fields in STD_TYPES.items():
        table[name] = [(t, None, n, '') for t, n in fields]
    for name, sections in definitions['msg'].items():
        table[name] = sections[0]['fields']
    for name, sections in definitions['srv'].items():
        table[name + 'Request'] = sections[0]['fields']
        table[name + 'Response'] = sections[1]['fields']
    for name, sections in definitions['action'].items():
        for suffix, section in zip(('Goal', 'Result', 'Feedback'), sections):
            table[name + suffix] = section['fields']
    return table


def resolve(type_name, table):
    """필드 타입 이름을 표의 이름으로 바꾼다. 모르는 타입이면 DefinitionError."""
    if type_name in STD_PACKAGES:
        return STD_PACKAGES[type_name]
    if type_name in INT_RANGES or type_name in FLOATS or type_name in ('bool', 'string'):
        return type_name
    short = type_name.split('/', 1)[1] if type_name.startswith('cobot_interfaces/') else type_name
    if short in table:
        return short
    raise DefinitionError('알 수 없는 타입: {}'.format(type_name))


def _ts_type(type_name, array, table):
    name = resolve(type_name, table)
    if name in INT_RANGES:
        base = 'number'
    elif name in FLOATS:
        base = 'Float'
    elif name == 'bool':
        base = 'boolean'
    elif name == 'string':
        base = 'string'
    else:
        base = name
    return base + ('[]' if array is not None else '')


def _doc(comment):
    text = comment.replace('*/', '* /').strip()
    return '  /** {} */\n'.format(text) if text else ''


def _interface(name, fields, table, title):
    lines = ['/** {} */\n'.format(title), 'export interface {} {{\n'.format(name)]
    for type_name, array, field, comment in fields:
        lines.append(_doc(comment))
        lines.append('  {}: {};\n'.format(field, _ts_type(type_name, array, table)))
    lines.append('}\n')
    return ''.join(lines)


def _constants(name, constants):
    if not constants:
        return ''
    lines = ['export const {}Const = {{\n'.format(name)]
    for _, const_name, value, comment in constants:
        lines.append(_doc(comment))
        lines.append('  {}: {},\n'.format(const_name, json.dumps(value, ensure_ascii=False)))
    lines.append('} as const;\n')
    return ''.join(lines)


def render(definitions):
    """
    정의에서 TypeScript 파일 문자열을 만든다.

    :param definitions: load_definitions() 결과
    :return: 파일 전체 문자열 (줄 끝 LF, 마지막 줄바꿈 1개)
    """
    table = type_table(definitions)
    out = [
        '// 자동 생성 파일이다. 직접 고치지 말 것.\n',
        '// 원본: src/cobot_interfaces 의 msg, srv, action 정의.\n',
        '// 재생성: {}\n'.format(REGEN_COMMAND),
        '// 확인: {} --check\n\n'.format(REGEN_COMMAND),
        '/** float 필드. NaN(미측정)은 JSON 에서 null 이 된다. 0 으로 바꿔 보이지 않는다. */\n',
        'export type Float = number | null;\n\n',
    ]
    for name in STD_TYPES:
        out.append(_interface(name, table[name], table, '표준 메시지 {}'.format(name)) + '\n')
    for name, sections in definitions['msg'].items():
        out.append(_interface(name, sections[0]['fields'], table, '{}.msg'.format(name)))
        out.append(_constants(name, sections[0]['constants']) + '\n')
    for name, sections in definitions['srv'].items():
        for suffix, section in zip(('Request', 'Response'), sections):
            out.append(_interface(name + suffix, section['fields'], table,
                                  '{}.srv {}'.format(name, suffix)))
            out.append(_constants(name + suffix, section['constants']) + '\n')
    for name, sections in definitions['action'].items():
        for suffix, section in zip(('Goal', 'Result', 'Feedback'), sections):
            out.append(_interface(name + suffix, section['fields'], table,
                                  '{}.action {}'.format(name, suffix)))
            out.append(_constants(name + suffix, section['constants']) + '\n')
    msgs = list(definitions['msg'])
    out.append('/** 메시지 이름 → 타입. useMessages(이름) 이 이 표로 타입을 정한다. */\n')
    out.append('export interface MessageMap {\n')
    out.extend('  {0}: {0};\n'.format(name) for name in msgs)
    out.append('}\n\n')
    out.append('export type MessageName = keyof MessageMap;\n\n')
    out.append('export const MESSAGE_NAMES: MessageName[] = {};\n\n'.format(
        json.dumps(msgs, indent=2)))
    out.append('/** 메시지·서비스·액션 이름 전부. 메뉴의 데이터 원천이 계약에 있는지 볼 때 쓴다. */\n')
    out.append('export const CONTRACT_NAMES: string[] = {};\n'.format(
        json.dumps(msgs + list(definitions['srv']) + list(definitions['action']), indent=2)))
    return ''.join(out)


def _enum_values(fields, constants):
    """주석의 '위 PREFIX_* 중 하나' 를 PREFIX_ 로 시작하는 상수 값 목록으로 바꾼다."""
    values = {}
    for item in fields:
        match = ENUM_RE.search(item[3])
        if match:
            prefix = match.group(1) + '_'
            found = [c[2] for c in constants if c[1].startswith(prefix)]
            values[item[2]] = (found, match.group(2) != '중 하나')
    return values


def validate_instance(table, enums, type_name, value, path):
    """
    모의 데이터 값 하나를 타입 정의와 대조한다.

    키 이름이 정확히 같은지, 값 종류와 정수 범위가 맞는지, '위 X_* 중 하나' 주석의 상수 값인지 본다.

    :param table: type_table() 결과
    :param enums: {타입 이름: {필드: (허용 값 목록, 빈 값 허용)}}
    :param type_name: 대조할 타입 이름
    :param value: JSON 에서 읽은 값
    :param path: 문제 문구에 쓸 위치
    :return: 문제 문구 목록 (비면 통과)
    """
    problems = []
    if not isinstance(value, dict):
        return ['{}: 객체여야 한다'.format(path)]
    fields = table[type_name]
    expected = [f[2] for f in fields]
    for key in expected:
        if key not in value:
            problems.append('{}: 필드가 없다: {}'.format(path, key))
    for key in value:
        if key not in expected:
            problems.append('{}: 정의에 없는 필드: {}'.format(path, key))
    for type_text, array, field, _ in fields:
        if field not in value:
            continue
        where = '{}.{}'.format(path, field)
        name = resolve(type_text, table)
        items = value[field]
        if array is not None:
            if not isinstance(items, list):
                problems.append('{}: 배열이어야 한다'.format(where))
                continue
            if array and len(items) != int(array):
                problems.append('{}: 길이가 {} 이어야 한다'.format(where, array))
            elements = list(enumerate(items))
        else:
            elements = [(None, items)]
        for index, item in elements:
            spot = where if index is None else '{}[{}]'.format(where, index)
            problems.extend(_validate_scalar(table, enums, type_name, field, name, item, spot))
    return problems


def _validate_scalar(table, enums, owner, field, name, item, spot):
    if name in INT_RANGES:
        low, high = INT_RANGES[name]
        if isinstance(item, bool) or not isinstance(item, int):
            return ['{}: 정수여야 한다 ({})'.format(spot, name)]
        if not low <= item <= high:
            return ['{}: {} 범위 밖: {}'.format(spot, name, item)]
        return []
    if name in FLOATS:
        if item is None or (isinstance(item, (int, float)) and not isinstance(item, bool)):
            return []
        return ['{}: 숫자 또는 null(미측정)이어야 한다'.format(spot)]
    if name == 'bool':
        return [] if isinstance(item, bool) else ['{}: true/false 여야 한다'.format(spot)]
    if name == 'string':
        if not isinstance(item, str):
            return ['{}: 문자열이어야 한다'.format(spot)]
        allowed = enums.get(owner, {}).get(field)
        if allowed and not (item == '' and allowed[1]) and item not in allowed[0]:
            return ['{}: 정의의 상수 값이 아니다: {!r}'.format(spot, item)]
        return []
    return validate_instance(table, enums, name, item, spot)


def enum_table(definitions):
    """메시지별 {필드: (허용 값, 빈 값 허용)} 표를 만든다."""
    result = {}
    for name, sections in definitions['msg'].items():
        found = _enum_values(sections[0]['fields'], sections[0]['constants'])
        if found:
            result[name] = found
    return result


def default_value(table, enums, owner, type_text, array, field):
    """모의 데이터의 영(零) 값. float 는 미측정(null), 상수 값을 꼭 골라야 하는 필드는 첫 상수를 쓴다."""
    if array is not None:
        if not array:
            return []
        one = default_value(table, enums, owner, type_text, None, field)
        return [copy.deepcopy(one) for _ in range(int(array))]
    name = resolve(type_text, table)
    if name in INT_RANGES:
        return 0
    if name in FLOATS:
        return None
    if name == 'bool':
        return False
    if name == 'string':
        allowed = enums.get(owner, {}).get(field)
        if allowed and allowed[0] and not allowed[1]:
            return allowed[0][0]
        return ''
    return {f[2]: default_value(table, enums, name, f[0], f[1], f[2]) for f in table[name]}


def _write_atomic(text, path, prefix):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, tmp_path = tempfile.mkstemp(prefix=prefix, suffix='.tmp', dir=directory)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(text.encode('utf-8'))
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def check_mocks(definitions, mock_dir):
    """
    모의 데이터 폴더를 정의와 대조한다.

    메시지마다 <이름>.json 이 있어야 하고, 내용은 그 메시지의 배열이어야 한다.

    :param definitions: load_definitions() 결과
    :param mock_dir: web/src/mock 경로
    :return: 문제 문구 목록 (비면 통과)
    """
    table = type_table(definitions)
    enums = enum_table(definitions)
    problems = []
    for name in definitions['msg']:
        path = os.path.join(mock_dir, name + '.json')
        if not os.path.isfile(path):
            problems.append('{}.json 이 없다'.format(name))
            continue
        try:
            with open(path, encoding='utf-8') as stream:
                data = json.load(stream)
        except ValueError as error:
            problems.append('{}.json 을 읽지 못했다: {}'.format(name, error))
            continue
        if not isinstance(data, list) or not data:
            problems.append('{}.json 은 비어 있지 않은 배열이어야 한다'.format(name))
            continue
        for index, item in enumerate(data):
            problems.extend(validate_instance(
                table, enums, name, item, '{}.json[{}]'.format(name, index)))
    known = {name + '.json' for name in definitions['msg']}
    if os.path.isdir(mock_dir):
        for name in sorted(os.listdir(mock_dir)):
            if name.endswith('.json') and name not in known:
                problems.append('{}: 정의에 없는 메시지의 모의 데이터'.format(name))
    return problems


def init_mocks(definitions, mock_dir):
    """없는 모의 데이터 파일만 영 값으로 만든다. 있는 파일은 건드리지 않는다. 만든 이름 목록을 돌려준다."""
    table = type_table(definitions)
    enums = enum_table(definitions)
    created = []
    for name, sections in definitions['msg'].items():
        path = os.path.join(mock_dir, name + '.json')
        if os.path.exists(path):
            continue
        item = {f[2]: default_value(table, enums, name, f[0], f[1], f[2])
                for f in sections[0]['fields']}
        _write_atomic(json.dumps([item], ensure_ascii=False, indent=2) + '\n', path, '.mock.')
        created.append(name)
    return created


def main(argv=None):
    """
    gen_web_types 명령의 진입점.

    정의에 오류가 있거나 --check 에서 차이가 있거나 모의 데이터가 정의와 다르면 1,
    경로를 찾지 못하면 2, 정상이면 0 을 돌려준다.

    :param argv: 명령행 인자 (None 이면 sys.argv)
    :return: 종료 코드
    """
    parser = argparse.ArgumentParser(
        description='인터페이스 정의에서 web/src/generated/messages.ts 를 만든다.')
    parser.add_argument('--root', help='레포 루트 (기본: 현재 폴더에서 위로 찾는다)')
    parser.add_argument('--interfaces', help='cobot_interfaces 경로 (기본: <root>/{})'.format(
        INTERFACES_RELPATH))
    parser.add_argument('--output', help='파일 경로 (기본: <root>/{})'.format(TS_RELPATH))
    parser.add_argument('--mocks', help='모의 데이터 폴더 (기본: <root>/{})'.format(MOCK_RELPATH))
    parser.add_argument('--check', action='store_true',
                        help='파일을 쓰지 않는다. 파일이 다르거나 모의 데이터가 정의와 다르면 1')
    parser.add_argument('--init-mocks', action='store_true',
                        help='없는 모의 데이터 파일을 영 값으로 만든다 (있는 파일은 그대로)')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = args.root
    if root is None and not (args.interfaces and args.output and args.mocks):
        root = menu_registry.find_repo_root()
        if root is None:
            LOGGER.error('레포 루트를 찾지 못했다. --root 를 준다.')
            return 2
    interfaces = args.interfaces or os.path.join(root, INTERFACES_RELPATH)
    output = args.output or os.path.join(root, TS_RELPATH)
    mock_dir = args.mocks or os.path.join(root, MOCK_RELPATH)
    try:
        definitions = load_definitions(interfaces)
        text = render(definitions)
    except DefinitionError as error:
        LOGGER.error('%s', error)
        return 2
    if args.init_mocks:
        created = init_mocks(definitions, mock_dir)
        LOGGER.info('모의 데이터를 만들었다: %d개', len(created))
    problems = check_mocks(definitions, mock_dir)
    if args.check:
        try:
            with open(output, 'rb') as stream:
                same = stream.read() == text.encode('utf-8')
        except OSError:
            same = False
        for problem in problems:
            LOGGER.error('%s', problem)
        if not same:
            LOGGER.error('불일치: %s 가 정의와 다르다. 재생성: %s', output, REGEN_COMMAND)
        if same and not problems:
            LOGGER.info('일치: %s (모의 데이터 %d개 통과)', output, len(definitions['msg']))
            return 0
        return 1
    _write_atomic(text, output, '.messages.')
    LOGGER.info('썼다: %s (메시지 %d, 서비스 %d, 액션 %d)', output, len(definitions['msg']),
                len(definitions['srv']), len(definitions['action']))
    for problem in problems:
        LOGGER.error('%s', problem)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
