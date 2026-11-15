"""웹 현장 확인 해제의 거절 원인을 구분하고 거절 시 잠금을 보존한다."""

from cobot_fleet_control.contracts import Command
import pytest
from test_scenario import Environment


@pytest.mark.parametrize('fresh, changes, detail', [
    (False, {}, '배터리 수신'),
    (True, {'busy': True}, 'busy=false'),
    (True, {'busy': None}, 'busy=false'),
    # 구역 안에서 잠긴 로봇도 해제한다. 해제 뒤 leave 로 나가고 토큰은 그때까지 유지된다
    (True, {'held_zone': 'A'}, None),
    # 재부팅으로 래치가 풀린 로봇도 멈춰 있으면(busy=false) 해제한다
    (True, {'central_latched': False}, None),
    (True, {'central_latched': None}, '래치 상태'),
    (True, {}, None),
])
def test_web_resolve_reports_blocker_and_only_releases_when_ready(
        tmp_path, fresh, changes, detail):
    env = Environment(tmp_path / 'fleet.sqlite3')
    repo, api = env.repo, env.api
    status = {'busy': False, 'held_zone': None, 'central_latched': True,
              'central_controlled': True}
    status.update(changes)
    env.scenario.telemetry('pinky2', status)
    if not fresh:
        env.now += 20
    try:
        repo.create(Command('stop1', 'pinky2', 'emergency_stop'))
        repo.transition('stop1', 'UNKNOWN', '정지 확인 필요')
        # 메모는 선택 (화면 확인 창 한 번)
        reply = api.handle({'type': 'resolve', 'task_id': 'stop1', 'result': 'FAILED'})
        if detail:
            assert reply['status'] == 409
            assert detail in reply['body']['detail']
            assert env.gateway.releases == []
            assert repo.get('stop1')['state'] == 'UNKNOWN'
        else:
            assert reply['status'] == 202
            assert env.gateway.releases == [('pinky2', None)]
            assert repo.get('stop1')['state'] == 'UNKNOWN'
            assert 'pinky2' in env.scenario.store.holds()
            env.scenario.telemetry('pinky2', dict(
                status, central_latched=False, control_reset_id='reset-1'))
            assert repo.get('stop1')['state'] == 'FAILED'
            assert 'pinky2' not in env.scenario.store.holds()
    finally:
        repo.close()
