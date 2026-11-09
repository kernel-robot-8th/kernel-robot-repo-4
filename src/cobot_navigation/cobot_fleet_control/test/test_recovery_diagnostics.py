"""웹 현장 확인 해제의 거절 원인을 구분하고 거절 시 잠금을 보존한다."""

from types import SimpleNamespace

from cobot_fleet_control.contracts import Command
from cobot_fleet_control.control_api import ControlAPI
from cobot_fleet_control.repository import SqliteRepository
import pytest


@pytest.mark.parametrize('fresh, changes, detail', [
    (False, {}, '배터리 수신'),
    (True, {'busy': True}, 'busy=false'),
    (True, {'busy': None}, 'busy=false'),
    # 구역 안에서 잠긴 로봇도 해제한다. 해제 뒤 leave 로 나가고 토큰은 그때까지 유지된다
    (True, {'held_zone': 'A'}, None),
    # 재부팅으로 래치가 풀린 로봇도 멈춰 있으면(busy=false) 해제한다
    (True, {'central_latched': False}, None),
    (True, {'central_latched': None}, None),
    (True, {}, None),
])
def test_web_resolve_reports_blocker_and_only_releases_when_ready(
        tmp_path, fresh, changes, detail):
    repo = SqliteRepository(str(tmp_path / 'fleet.sqlite3'))
    released, cleared = [], []
    status = {'busy': False, 'held_zone': None, 'central_latched': True}
    status.update(changes)
    store = SimpleNamespace(orders=lambda: [], clear_hold=cleared.append)
    scenario = SimpleNamespace(store=store, _fresh=lambda robot: fresh,
                               health={'pinky2': {'status': status}})
    fleet = SimpleNamespace(repository=repo)
    api = ControlAPI(scenario, fleet, SimpleNamespace(release=released.append))
    try:
        repo.create(Command('stop1', 'pinky2', 'emergency_stop'))
        repo.transition('stop1', 'UNKNOWN', '정지 확인 필요')
        # 메모는 선택 (화면 확인 창 한 번)
        reply = api.handle({'type': 'resolve', 'task_id': 'stop1', 'result': 'FAILED'})
        if detail:
            assert reply['status'] == 409
            assert detail in reply['body']['detail']
            assert released == cleared == []
            assert repo.get('stop1')['state'] == 'UNKNOWN'
        else:
            assert reply['status'] == 200
            assert released == cleared == ['pinky2']
            assert repo.get('stop1')['state'] == 'FAILED'
    finally:
        repo.close()
