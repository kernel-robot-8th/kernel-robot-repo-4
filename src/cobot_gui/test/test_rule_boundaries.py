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

"""Reject branch ownership/menu mismatches and preserve unusual canonical SR values."""

import copy
from pathlib import Path

from cobot_gui import menu_registry
import pytest


def _registry():
    path = Path(__file__).resolve().parents[1] / 'config' / 'menu_tree.yaml'
    registry, errors = menu_registry.read_registry(str(path))
    assert errors == []
    return registry


@pytest.mark.parametrize('branch', [
    'feature/gui-1.1-cards', 'fix/control_center-1.1-state',
    'feature/common-common-command-header', 'feature/gui-registry-menu-tree',
])
def test_registered_role_and_matching_unit_are_accepted(branch):
    """Allow the owning menu or explicitly shared units with registered roles."""
    registry = _registry()
    menu = next(m for m in registry['menus'] if m['id'] == '1.1')
    menu.update(status='in_progress', branch=branch)
    assert menu_registry.validate(registry) == []


@pytest.mark.parametrize('branch', [
    'feature/unknown-1.1-cards', 'feature/gui-2.2-wrong-menu',
    'feature/gui-cards', 'feature/gui-1.1-', 'feature/gui-1.1-cards/extra',
])
def test_wrong_role_or_menu_cannot_claim_work(branch):
    """Do not equate a feature prefix with a valid work reservation."""
    registry = _registry()
    menu = next(m for m in registry['menus'] if m['id'] == '1.1')
    menu.update(status='in_progress', branch=branch)
    assert menu_registry.validate(registry)


def test_sr_22_and_unresolved_priorities_are_preserved():
    """Keep real SR-22 and raw RO(DB)/empty priorities from SR_v2 version 13."""
    registry = _registry()
    items = {row['id']: row for row in registry['sr_catalog']['items']}
    assert len(items) == 22
    assert items['SR-02']['priority'] == 'RO(DB)'
    assert items['SR-15']['priority'] == ''
    menu = next(m for m in registry['menus'] if m['id'] == '6.5')
    assert menu['sr'] == ['SR-22']
    assert menu['sr_unconfirmed'] == []
    broken = copy.deepcopy(registry)
    broken['sr_catalog']['items'][14]['priority'] = 'R'
    assert menu_registry.validate(broken)
