"""홈 초기위치 때 다시 켜져 잊은 구역만 푼다."""

import json
from types import SimpleNamespace

from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
from cobot_fleet_control.scenario_repository import ScenarioRepository
from cobot_fleet_control.web_profiles import PointRules
from cobot_fleet_control.zone_reclaim import ZoneReclaim
import pytest

RULES = PointRules({'pinky1': {'home_name': 'I1', 'points': {'I1': [0.0, 0.0, 0.0]}}})


@pytest.fixture
def env(tmp_path):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    store = ScenarioRepository(repo)
    store.claim_zone('A', 'pinky1', 'boot1')
    e = SimpleNamespace(now=0.0, fresh=True, zone=('occupied_by:pinky1', 0.5),
                        sent=[], poses=[], store=store, repo=repo, orders=[])
    e.status = {'busy': False, 'held_zone': None, 'boot_id': 'boot2'}
    store.orders = lambda: e.orders
    scenario = SimpleNamespace(store=store, _fresh=lambda r: e.fresh, armed=False,
                               health={'pinky1': {'status': e.status}}, clock=lambda: e.now)
    fleet = SimpleNamespace(repository=repo, robots=['pinky1'])
    gateway = SimpleNamespace(
        zone_state=lambda z: e.zone if z == 'A' else (None, None),
        release_zone=lambda *a: e.sent.append(a),
        set_initial_pose=lambda *a: e.poses.append(a))
    e.reclaim = ZoneReclaim(scenario, fleet, gateway)
    e.api = ControlAPI(scenario, fleet, gateway, point_rules=RULES, reclaim=e.reclaim)
    yield e
    repo.close()


def ask(env, **extra):
    return env.api.handle(dict({'type': 'initial_pose', 'robot_id': 'pinky1',
                                'release_zones': ['A'], 'source': '10.0.0.5'}, **extra))


def event_types(env):
    return [json.loads(r['payload'])['type'] for r in env.repo.pending()]


def test_releases_once_after_amcl_reaches_home(env):
    body = ask(env)['body']
    assert body['zones_pending'] == ['A'] and body['zones_skipped'] == {}
    assert env.poses and env.sent == []      # 초기위치를 낸 것만으로는 풀지 않는다
    env.reclaim.observe_pose('pinky1', 0.1, 0.0)
    env.reclaim.observe_pose('pinky1', 0.1, 0.0)
    assert env.sent == [('A', 'pinky1')]
    assert 'zone_release' in event_types(env)


def test_without_release_zones_behaves_as_before(env):
    body = ask(env, release_zones=None)['body']
    assert 'zones_pending' not in body
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.poses and env.sent == []


def make_unsafe(env, case):
    if case == 'same_boot':
        env.status['boot_id'] = 'boot1'
    elif case == 'no_boot':
        env.status['boot_id'] = None
    elif case == 'no_claim':
        env.repo.db.execute('DELETE FROM zone_claims')
    elif case == 'other_claim':
        env.store.claim_zone('A', 'pinky2', 'boot1')
    elif case == 'held':
        env.status['held_zone'] = 'A'
    elif case == 'held_other':
        env.status['held_zone'] = 'C'
    elif case == 'no_held':
        del env.status['held_zone']
    elif case == 'other_owner':
        env.zone = ('occupied_by:pinky2', 0.5)
    elif case == 'old_zone':
        env.zone = ('occupied_by:pinky1', 4.0)
    elif case == 'no_zone':
        env.zone = (None, None)
    elif case == 'offline':
        env.fresh = False
    elif case == 'busy':
        env.status['busy'] = True
    elif case == 'order':
        env.orders = [{'robot_id': 'pinky1', 'state': 'UNKNOWN'}]


CASES = ['same_boot', 'no_boot', 'no_claim', 'other_claim', 'held', 'held_other', 'no_held',
         'other_owner', 'old_zone', 'no_zone', 'offline', 'busy', 'order']


@pytest.mark.parametrize('case', CASES)
def test_refuses_when_unsafe_at_request(env, case):
    make_unsafe(env, case)
    assert env.reclaim.refusal('pinky1', 'A')
    reply = ask(env)
    if reply['status'] == 202:
        assert reply['body']['zones_pending'] == [] and 'A' in reply['body']['zones_skipped']
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.sent == []


@pytest.mark.parametrize('case', CASES)
def test_refuses_when_state_changes_while_waiting(env, case):
    assert ask(env)['body']['zones_pending'] == ['A']
    make_unsafe(env, case)
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.sent == [] and 'zone_reclaim_skipped' in event_types(env)


def test_new_reboot_while_waiting_drops_request(env):
    ask(env)
    env.status['boot_id'] = 'boot3'
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.sent == [] and env.reclaim.pending == {}


@pytest.mark.parametrize('x, y', [(0.5, 0.0), (float('nan'), 0.0)])
def test_pose_away_from_home_does_not_release(env, x, y):
    ask(env)
    env.reclaim.observe_pose('pinky1', x, y)
    assert env.sent == [] and 'pinky1' in env.reclaim.pending


@pytest.mark.parametrize('by_tick', [True, False])
def test_timeout_keeps_zone(env, by_tick):
    ask(env)
    env.now = 10.0
    if by_tick:
        env.reclaim.tick()
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.sent == [] and env.reclaim.pending == {}
    assert 'zone_reclaim_skipped' in event_types(env)


def test_manual_pose_cannot_release_and_cancels_waiting(env):
    pose = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}
    assert ask(env, pose=pose)['status'] == 400 and env.poses == []
    ask(env)
    assert ask(env, pose=pose, release_zones=None)['status'] == 202
    env.reclaim.observe_pose('pinky1', 0.0, 0.0)
    assert env.sent == []


@pytest.mark.parametrize('zones', ['A', [1], ['A:pinky2'], ['']])
def test_bad_zone_names(env, zones):
    assert ask(env, release_zones=zones)['status'] == 400 and env.poses == []


def test_claim_survives_restart(tmp_path):
    path = str(tmp_path / 'fleet.sqlite3')
    repo = SqliteRepository(path)
    ScenarioRepository(repo).claim_zone('A', 'pinky1', 'boot1')
    repo.close()
    repo = SqliteRepository(path)
    assert ScenarioRepository(repo).zone_claim('A') == ('pinky1', 'boot1')
    repo.close()
