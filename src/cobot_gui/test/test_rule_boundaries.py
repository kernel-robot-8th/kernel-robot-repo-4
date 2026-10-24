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


def test_control_split_covers_all_menus_without_reassigning_robot_functions():
    """Keep two control deliverables distinct from device/data ownership."""
    registry = _registry()
    menus = {menu['id']: menu for menu in registry['menus']}
    assert len(menus) == 34
    assert {m['control_area'] for m in menus.values()} == {'operational', 'anomaly'}
    assert sum(m['control_area'] == 'operational' for m in menus.values()) == 19
    assert sum(m['control_area'] == 'anomaly' for m in menus.values()) == 15
    assert menus['2.1']['control_owner'] == 'operation_control'
    assert menus['2.1']['data_owner'] == 'navigation'
    assert 'overhead pose' not in menus['2.1']['data_sources']
    assert menus['4.3']['control_owner'] == 'anomaly_monitoring'
    assert menus['4.3']['data_owner'] == 'vision'
    assert menus['4.3']['commands'] == []
    assert menus['3.7']['control_owner'] == 'operation_control'
    assert menus['3.7']['screen_owner'] == 'manipulation'
    assert registry['roles']['operation_control']['members'] == []
    assert registry['roles']['anomaly_monitoring']['members'] == []


@pytest.mark.parametrize('field,value', [
    ('control_area', 'robot_development'), ('control_area', None),
    ('control_area', []), ('control_owner', 'navigation'),
    ('control_owner', ''),
])
def test_invalid_or_crossed_control_responsibility_is_rejected(field, value):
    """A wrong control lane must fail rather than silently assign robot developers."""
    registry = _registry()
    menu = next(m for m in registry['menus'] if m['id'] == '1.1')
    menu[field] = value
    assert menu_registry.validate(registry)
