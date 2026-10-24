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

"""Check that web/src/generated/menus.ts is generated from the registry and stays in sync."""

import json
from pathlib import Path
import re
import shutil

from cobot_gui import gen_web_menus, menu_registry

PACKAGE = Path(__file__).resolve().parents[1]
REGISTRY = PACKAGE / 'config' / 'menu_tree.yaml'
GENERATED = PACKAGE / 'web' / 'src' / 'generated' / 'menus.ts'


def _registry():
    registry, errors = menu_registry.read_registry(str(REGISTRY))
    assert errors == []
    return registry


def _constant(text, name):
    match = re.search(r'export const {}: [A-Za-z]+\[\] = (\[.*?\n\]);\n'.format(name), text, re.S)
    assert match, name
    return json.loads(match.group(1))


def test_committed_file_matches_registry():
    """Fail when the registry changed but menus.ts was not regenerated."""
    assert gen_web_menus.main(['--registry', str(REGISTRY), '--output', str(GENERATED),
                               '--check']) == 0


def test_render_is_deterministic_and_valid_json():
    """Render twice to the same bytes and keep every constant a plain JSON literal."""
    registry = _registry()
    first = gen_web_menus.render(registry)
    assert first == gen_web_menus.render(registry)
    assert '\r' not in first and first.endswith('\n') and not first.endswith('\n\n')
    menus = _constant(first, 'MENUS')
    assert len(menus) == len(registry['menus']) == 34
    ids = [menu['id'] for menu in menus]
    assert ids == sorted(ids, key=menu_registry.menu_sort_key)
    assert len(_constant(first, 'SCREENS')) == len(registry['screens'])
    assert len(_constant(first, 'DECISIONS')) == len(registry['decisions'])
    assert len(_constant(first, 'SR_CATALOG')) == 22


def test_fields_are_carried_over():
    """Keep implementation level, owners and the original SR mapping of menu 3.7."""
    menus = {m['id']: m for m in _constant(gen_web_menus.render(_registry()), 'MENUS')}
    menu = menus['3.7']
    assert menu['impl'] == 'external' and 'e78dd9a' in menu['implRef']
    assert menu['screen'] == 'screen_3' and menu['screenOwner'] == 'manipulation'
    assert menu['sr'] == [] and 'SR-09' in menu['srOriginal']
    assert menus['1.1']['impl'] == 'none' and menus['1.1']['implRef'] == ''
    assert menus['1.1']['srOriginal'] is not None
    assert menus['2.1']['srOriginal'] is None


def test_write_then_check_round_trip(tmp_path):
    """Write to a temporary file, then pass the check on it."""
    out = tmp_path / 'nested' / 'menus.ts'
    args = ['--registry', str(REGISTRY), '--output', str(out)]
    assert gen_web_menus.main(args) == 0
    assert gen_web_menus.main(args + ['--check']) == 0
    assert out.read_text(encoding='utf-8') == GENERATED.read_text(encoding='utf-8')


def test_check_fails_when_registry_changes(tmp_path):
    """A valid registry edit must make the committed file stale."""
    text = REGISTRY.read_text(encoding='utf-8')
    assert '갱신: 5 Hz.' in text
    changed = tmp_path / 'menu_tree.yaml'
    changed.write_text(text.replace('갱신: 5 Hz.', '갱신: 6 Hz.', 1), encoding='utf-8')
    assert gen_web_menus.main(['--registry', str(changed), '--output', str(GENERATED),
                               '--check']) == 1


def test_check_fails_when_file_changes_or_is_missing(tmp_path):
    """Detect a hand edit of one character and a missing file."""
    edited = tmp_path / 'menus.ts'
    shutil.copy(GENERATED, edited)
    data = edited.read_bytes()
    edited.write_bytes(data.replace('통합 관제'.encode('utf-8'), '통합 관재'.encode('utf-8'), 1))
    assert edited.read_bytes() != data
    args = ['--registry', str(REGISTRY), '--check']
    assert gen_web_menus.main(args + ['--output', str(edited)]) == 1
    assert gen_web_menus.main(args + ['--output', str(tmp_path / 'missing.ts')]) == 1


def test_invalid_registry_writes_nothing(tmp_path):
    """Refuse to generate from a registry that fails validation."""
    text = REGISTRY.read_text(encoding='utf-8')
    broken = tmp_path / 'menu_tree.yaml'
    broken.write_text(text.replace('phase: P4', 'phase: P9', 1), encoding='utf-8')
    out = tmp_path / 'menus.ts'
    assert gen_web_menus.main(['--registry', str(broken), '--output', str(out)]) == 1
    assert not out.exists()


def test_missing_registry_is_exit_2(tmp_path):
    """Report an unreadable registry as exit code 2."""
    args = ['--registry', str(tmp_path / 'none.yaml'), '--output', str(tmp_path / 'm.ts')]
    assert gen_web_menus.main(args) == 2
