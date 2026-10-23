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

"""Check that messages.ts follows cobot_interfaces and that mock data follows the definitions."""

import copy
import json
from pathlib import Path
import shutil

from cobot_gui import gen_web_types as gen
import pytest

REPO = Path(__file__).resolve().parents[3]
INTERFACES = REPO / gen.INTERFACES_RELPATH
GENERATED = REPO / gen.TS_RELPATH
MOCKS = REPO / gen.MOCK_RELPATH


def _definitions():
    return gen.load_definitions(str(INTERFACES))


def _mini(tmp_path, files):
    """Write a tiny interface package and return its path."""
    root = tmp_path / 'cobot_interfaces'
    for kind in ('msg', 'srv', 'action'):
        (root / kind).mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding='utf-8')
    return root


def test_committed_files_match_definitions_and_mocks():
    """Fail when a definition changed but messages.ts or a mock was not updated."""
    assert gen.main(['--root', str(REPO), '--check']) == 0


def test_every_message_has_a_conforming_mock():
    """Require one mock file per message and no extra files."""
    definitions = _definitions()
    assert len(definitions['msg']) == 30
    assert gen.check_mocks(definitions, str(MOCKS)) == []
    assert {p.stem for p in MOCKS.glob('*.json')} == set(definitions['msg'])


def test_parser_reads_constants_arrays_and_comments():
    """Read string/number constants, array forms and trailing comments."""
    text = (
        '# header comment\n'
        'string MODE_A="A#1"   # keeps the hash inside quotes\n'
        'uint8 LIMIT=7\n'
        'bool FLAG=true\n'
        'std_msgs/Header header  # stamp\n'
        'float32[] values        # [m] list\n'
        'uint8[3] triple\n'
        'string name\n'
    )
    section = gen.parse_sections(text, 'T.msg')[0]
    assert [c[1:3] for c in section['constants']] == [
        ('MODE_A', 'A#1'), ('LIMIT', 7), ('FLAG', True)]
    assert [(f[0], f[1], f[2]) for f in section['fields']] == [
        ('std_msgs/Header', None, 'header'), ('float32', '', 'values'),
        ('uint8', '3', 'triple'), ('string', None, 'name')]
    assert section['fields'][1][3] == '[m] list'


def test_parser_splits_service_and_action_sections():
    """Count --- separated sections and reject an unreadable line."""
    assert len(gen.parse_sections('string a\n---\nbool ok\n', 'S.srv')) == 2
    assert len(gen.parse_sections('string a\n---\nbool ok\n---\nuint8 step\n', 'A.action')) == 3
    with pytest.raises(gen.DefinitionError):
        gen.parse_sections('this is not a field\n', 'Bad.msg')


def test_render_maps_types_and_is_deterministic(tmp_path):
    """Map floats to Float, arrays to T[], constants to a Const object; same input, same bytes."""
    root = _mini(tmp_path, {
        'msg/Pt.msg': 'float64 x\n',
        'msg/Box.msg': (
            'string KIND_A="A"\nstd_msgs/Header header\nPt[] points\nfloat32 w  # [m]\n'
            'uint64 seq\nbool ok\nbuiltin_interfaces/Time at\n'),
        'srv/Ask.srv': 'string q\n---\nBox[] answers\n',
        'action/Do.action': 'string a\n---\nbool done\n---\nfloat32 pct\n',
    })
    definitions = gen.load_definitions(str(root))
    text = gen.render(definitions)
    assert text == gen.render(gen.load_definitions(str(root)))
    assert '\r' not in text and text.endswith('\n') and not text.endswith('\n\n')
    assert 'points: Pt[];' in text and 'w: Float;' in text and 'seq: number;' in text
    assert 'at: Time;' in text and 'header: Header;' in text
    assert 'export const BoxConst = {' in text and 'KIND_A: "A"' in text
    assert 'export interface AskRequest' in text and 'answers: Box[];' in text
    assert 'export interface DoGoal' in text and 'export interface DoFeedback' in text
    assert 'export interface MessageMap {\n  Box: Box;\n  Pt: Pt;\n}' in text
    assert '"Ask"' in text.split('CONTRACT_NAMES')[1] and '"Do"' in text.split('CONTRACT_NAMES')[1]


def test_unknown_nested_type_is_an_error(tmp_path):
    """Stop on a field type that no definition declares."""
    root = _mini(tmp_path, {'msg/Bad.msg': 'Missing thing\n'})
    with pytest.raises(gen.DefinitionError):
        gen.render(gen.load_definitions(str(root)))


def test_check_fails_when_a_definition_changes(tmp_path):
    """Adding a field to a message makes messages.ts and its mock stale."""
    copy_root = tmp_path / 'repo'
    shutil.copytree(INTERFACES, copy_root / 'src' / 'cobot_interfaces')
    shutil.copytree(MOCKS, copy_root / 'src' / 'cobot_gui' / 'web' / 'src' / 'mock')
    out = copy_root / 'src' / 'cobot_gui' / 'web' / 'src' / 'generated'
    out.mkdir(parents=True)
    shutil.copy(GENERATED, out / 'messages.ts')
    assert gen.main(['--root', str(copy_root), '--check']) == 0
    msg = copy_root / 'src' / 'cobot_interfaces' / 'msg' / 'MediaHealth.msg'
    msg.write_text(msg.read_text(encoding='utf-8') + 'uint8 extra_field\n', encoding='utf-8')
    assert gen.main(['--root', str(copy_root), '--check']) == 1


def test_check_fails_for_missing_or_edited_output_and_stray_mock(tmp_path):
    """Detect a hand edit, a missing file and a mock without a definition."""
    edited = tmp_path / 'messages.ts'
    edited.write_text(GENERATED.read_text(encoding='utf-8').replace('Float', 'Flaot', 1),
                      encoding='utf-8')
    args = ['--interfaces', str(INTERFACES), '--mocks', str(MOCKS), '--check']
    assert gen.main(args + ['--output', str(edited)]) == 1
    assert gen.main(args + ['--output', str(tmp_path / 'none.ts')]) == 1
    stray = tmp_path / 'mock'
    shutil.copytree(MOCKS, stray)
    (stray / 'GhostMessage.json').write_text('[{}]', encoding='utf-8')
    assert gen.main(['--interfaces', str(INTERFACES), '--mocks', str(stray), '--output',
                     str(GENERATED), '--check']) == 1


def test_missing_interfaces_is_exit_2(tmp_path):
    """Report a missing interface package as exit code 2."""
    args = ['--interfaces', str(tmp_path / 'none'), '--output', str(tmp_path / 'm.ts'),
            '--mocks', str(tmp_path / 'mock')]
    assert gen.main(args) == 2


def _violations(definitions, name, item):
    table = gen.type_table(definitions)
    return gen.validate_instance(table, gen.enum_table(definitions), name, item, name)


def test_validation_negative_controls():
    """Each kind of mismatch between a mock and its definition must be reported."""
    definitions = _definitions()
    good = json.loads((MOCKS / 'RobotStatus.json').read_text(encoding='utf-8'))[0]
    assert _violations(definitions, 'RobotStatus', good) == []

    def broken(mutate):
        item = copy.deepcopy(good)
        mutate(item)
        return _violations(definitions, 'RobotStatus', item)

    assert any('필드가 없다' in p for p in broken(lambda i: i.pop('robot_id')))
    assert any('정의에 없는 필드' in p for p in broken(lambda i: i.update(extra=1)))
    assert any('정수' in p for p in broken(lambda i: i.update(epoch_accepted='3')))
    assert any('범위 밖' in p for p in broken(lambda i: i.update(nav2_action_clients=256)))
    assert any('정수' in p for p in broken(lambda i: i.update(epoch_accepted=True)))
    assert any('정수' in p for p in broken(lambda i: i.update(epoch_accepted=None)))
    assert any('숫자 또는 null' in p for p in broken(lambda i: i.update(linear_vel='fast')))
    assert any('true/false' in p for p in broken(lambda i: i.update(localized=1)))
    assert any('문자열' in p for p in broken(lambda i: i.update(robot_id=5)))
    assert any('상수 값' in p for p in broken(lambda i: i.update(state='FLYING')))
    assert any('상수 값' in p for p in broken(lambda i: i.update(hold_reason='NOT_A_REASON')))
    assert any('필드가 없다' in p for p in broken(
        lambda i: i['current_pose']['position'].pop('z')))
    assert broken(lambda i: i.update(battery_percentage=None)) == []
    assert broken(lambda i: i.update(hold_reason='')) == []


def test_array_rules():
    """Check array type, fixed length and nested elements."""
    definitions = _definitions()
    info = json.loads((MOCKS / 'MapInfo.json').read_text(encoding='utf-8'))[0]
    assert _violations(definitions, 'MapInfo', info) == []
    bad = copy.deepcopy(info)
    bad['waypoints'] = {'not': 'a list'}
    assert any('배열' in p for p in _violations(definitions, 'MapInfo', bad))
    bad = copy.deepcopy(info)
    bad['waypoints'][0].pop('work_x')
    assert any('work_x' in p for p in _violations(definitions, 'MapInfo', bad))


def test_init_mocks_creates_only_missing_files(tmp_path):
    """Create zero-value mocks that pass validation and keep existing files as they are."""
    definitions = _definitions()
    target = tmp_path / 'mock'
    target.mkdir()
    (target / 'ArmMode.json').write_text('KEEP', encoding='utf-8')
    created = gen.init_mocks(definitions, str(target))
    assert 'ArmMode' not in created and len(created) == 29
    assert (target / 'ArmMode.json').read_text(encoding='utf-8') == 'KEEP'
    (target / 'ArmMode.json').write_text(
        (MOCKS / 'ArmMode.json').read_text(encoding='utf-8'), encoding='utf-8')
    assert gen.check_mocks(definitions, str(target)) == []


def test_curated_scenario_keeps_unmeasured_values_null():
    """The mock scenario must keep unmeasured values null so screens can show 미측정."""
    robots = json.loads((MOCKS / 'RobotStatus.json').read_text(encoding='utf-8'))
    assert [r['robot_id'] for r in robots] == ['pinky_1', 'pinky_2', 'pinky_3']
    assert robots[2]['battery_percentage'] is None and robots[2]['state'] == 'HOLD'
    arms = json.loads((MOCKS / 'ArmStatus.json').read_text(encoding='utf-8'))
    assert arms[1]['retract_safe'] is False and arms[1]['retract_safe_measured'] is False
    cams = json.loads((MOCKS / 'CameraHealth.json').read_text(encoding='utf-8'))
    assert any(c['frame_age_ms'] is None for c in cams)
