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
가짜 핑키 로직(mock_pinky_sim.py)을 ROS 없이 검사한다.

지점·구역은 실제 순찰·zone_manager 설정 파일을 읽는다. 그 파일 형식이 바뀌면 여기서 먼저 깨진다.
"""

import json
import os
import random

from cobot_mock.mock_pinky_sim import (ack_for, central_command, CentralGuard, check_domain,
                                       choose_auto_command, load_robot_configs,
                                       load_zone_params, parse_command, RobotSim, v2_to_v1,
                                       ZoneBook)
import pytest

NAV = os.path.join(os.path.dirname(__file__), '..', '..', 'cobot_navigation')
POINTS_DIR = os.path.join(NAV, 'cobot_pinky_patrol', 'config')
ZONE_PARAMS = os.path.join(NAV, 'cobot_zone_traffic_control', 'config', 'zone_params.yaml')
ROBOTS = ['pinky1', 'pinky2', 'pinky3']


@pytest.fixture
def fleet():
    configs = load_robot_configs(POINTS_DIR, ROBOTS)
    book = ZoneBook(load_zone_params(ZONE_PARAMS))
    # 유휴 복귀는 길게 둔다 (다른 시험 중에 홈으로 가 버리지 않게). 복귀 시험만 따로 줄인다.
    sims = {r: RobotSim(r, configs[r], book, speed_mps=1.0, idle_return_sec=60.0) for r in ROBOTS}
    return sims, book


def run(sims, seconds, start=0.0, dt=0.1):
    """모든 로봇을 seconds 동안 진행하고 로봇별 이벤트를 돌려준다."""
    events = {r: [] for r in sims}
    t = start
    for _ in range(int(round(seconds / dt))):
        t += dt
        for name, sim in sims.items():
            events[name] += sim.step(t, dt)
    return events, t


def states(events):
    return [(e['state'], e['detail']) for e in events]


def test_configs_match_real_files():
    configs = load_robot_configs(POINTS_DIR, ROBOTS)
    assert [configs[r]['home'] for r in ROBOTS] == ['I1', 'I2', 'I3']
    assert configs['pinky1']['zone_points'] == {'A': ['ZA'], 'B': ['ZB'], 'C': ['ZC']}
    assert 'ZA_EXIT' in configs['pinky1']['points']
    assert 'P36' not in configs['pinky1']['points']       # (0,0,0) 예비 점은 뺀다
    zones = load_zone_params(ZONE_PARAMS)
    assert set(zones['zones']) == {'A', 'B', 'C'}
    assert zones['queue_max'] == 3


@pytest.mark.parametrize('domain,ok', [('', False), ('0', False), ('10', False), ('12', False),
                                       ('20', False), ('30', False), ('100', False),
                                       ('101', True), ('77', True), ('abc', False)])
def test_check_domain(domain, ok):
    assert check_domain({'ROS_DOMAIN_ID': domain})[0] is ok


def test_parse_command():
    assert parse_command('goto:P1, P2') == ('goto', ['P1', 'P2'], None)
    assert parse_command('leave') == ('leave', [], None)
    assert parse_command('{"command_id": "job-1", "command": "zone:ZA"}') == (
        'zone', ['ZA'], 'job-1')
    assert parse_command('dance')[0] is None
    assert parse_command('{"command": "goto:P1"}')[0] is None


def test_goto_sequence(fleet):
    sims, _ = fleet
    ev = sims['pinky1'].command('goto:P1,P2', 0.0)
    more, _ = run(sims, 10)
    seq = states(ev + more['pinky1'])
    assert seq[:3] == [('STARTING', 'P1,P2'), ('MOVING', 'P1'), ('ARRIVED', 'P1')]
    assert seq[3:6] == [('MOVING', 'P2'), ('ARRIVED', 'P2'), ('DONE', 'arrived P2')]
    assert seq[6] == ('IDLE_WAIT', '60')
    assert sims['pinky1'].pose == sims['pinky1'].points['P2']


def test_validation_failures_match_real_node(fleet):
    sim = fleet[0]['pinky1']
    assert states(sim.command('goto:P99', 0)) == [('FAILED', "unknown point: ['P99']")]
    assert states(sim.command('goto:ZA', 0)) == [('FAILED', "use zone: ['ZA']")]
    assert states(sim.command('goto:I2', 0)) == [('FAILED', "not allowed: ['I2']")]
    assert states(sim.command('zone:P1', 0)) == [('FAILED', "zone needs one zone point: ['P1']")]
    assert states(sim.command('goto', 0)) == [('FAILED', 'no point given')]
    assert states(sim.command('leave', 0)) == [('FAILED', 'no zone held')]
    assert states(sim.command('start', 0)) == [('FAILED', 'start disabled')]


def test_busy_robot_ignores_new_command(fleet):
    sim = fleet[0]['pinky1']
    sim.command('goto:P3', 0.0)
    assert sim.command('goto:P1', 0.1) == []


def test_zone_hold_queue_and_leave(fleet):
    sims, book = fleet
    sims['pinky1'].command('zone:ZA', 0.0)
    ev, t = run(sims, 10)
    assert ('HOLDING_ZONE', 'A') in states(ev['pinky1'])
    assert book.status_lines()[0] == 'A:occupied_by:pinky1'

    # 두 번째 로봇은 대기 슬롯 0 에서 기다린다
    first = sims['pinky2'].command('zone:ZA', t)
    ev, t = run(sims, 10, t)
    # 실제 노드처럼 슬롯으로 MOVING(slot) 한 뒤 QUEUEING(slot0)
    assert states(first + ev['pinky2'])[:3] == [
        ('STARTING', 'ZA'), ('MOVING', 'slot'), ('QUEUEING', 'slot0')]
    assert sims['pinky2'].pose[:2] == pytest.approx(book.slot_pose('A', 0)[:2])
    assert sims['pinky2'].running
    # 대기 슬롯도 zone_manager 와 같은 형식으로 낸다: "<zone>:<robot>:<k>:<x>,<y>,<yaw>"
    x, y, yaw = book.slot_pose('A', 0)
    assert book.slot_lines() == [f'A:pinky2:0:{x:.3f},{y:.3f},{yaw:.3f}']

    # 점유자가 나가면 대기자가 들어간다
    leave = sims['pinky1'].command('leave', t)
    ev, t = run(sims, 10, t)
    assert ('LEAVING_ZONE', 'ZA_EXIT') in states(leave + ev['pinky1'])
    assert ('DONE', 'left zone') in states(ev['pinky1'])
    assert ('HOLDING_ZONE', 'A') in states(ev['pinky2'])
    assert book.owner['A'] == 'pinky2'
    assert book.slot_lines() == []


def test_queue_full(fleet):
    sims, book = fleet
    for i, r in enumerate(['a', 'b', 'c']):
        book.queue['A'].append(r)
    book.owner['A'] = 'x'
    book.granted_at['A'] = 0.0
    ev = sims['pinky1'].command('zone:ZA', 0.0)
    more, _ = run(sims, 1)
    assert ('FAILED', 'queue_full') in states(ev + more['pinky1'])
    assert not sims['pinky1'].running


def test_stop_in_zone_retreats(fleet):
    sims, book = fleet
    sims['pinky1'].command('zone:ZA', 0.0)        # 비어 있어 바로 허가 -> ZA 로 가는 중
    _, t = run(sims, 0.2)
    assert sims['pinky1'].held_zone == 'A' and sims['pinky1'].running
    ev = sims['pinky1'].command('stop', t)
    more, _ = run(sims, 10, t)
    seq = states(ev + more['pinky1'])
    assert seq[0] == ('STOPPED', 'ZA')
    assert ('RETREATING', 'ZA_EXIT') in seq
    assert seq[-1] == ('STOPPED', 'retreated')
    assert book.owner['A'] is None


def test_emergency_stop_keeps_token(fleet):
    sims, book = fleet
    sims['pinky1'].command('zone:ZA', 0.0)
    run(sims, 0.3)
    ev = sims['pinky1'].command('emergency_stop', 0.3)
    assert states(ev)[0][0] == 'STOPPED'
    assert book.owner['A'] == 'pinky1'            # 매니저 쪽 토큰은 남는다
    # 실제 노드처럼 로봇도 보유 구역을 기억한다 (복구 뒤 leave 로 나감)
    assert sims['pinky1'].held_zone == 'A'
    ev = sims['pinky1'].command('leave', 0.4)
    run(sims, 30, start=0.4)
    assert sims['pinky1'].held_zone is None and book.owner['A'] is None


def test_stop_while_idle_in_zone(fleet):
    # 실제 patrol_controller.stop(): 쉬는 중이어도 구역을 잡고 있으면 정지를 처리하고 유휴 복귀를 지운다
    sims, book = fleet
    for name, emergency in (('pinky1', False), ('pinky2', True)):
        sim = sims[name]
        sim.command('zone:ZA' if name == 'pinky1' else 'zone:ZB', 0.0)
    run(sims, 60)
    assert sims['pinky1'].held_zone == 'A' and sims['pinky2'].held_zone == 'B'
    assert sims['pinky1'].idle_deadline is not None
    ev = sims['pinky1'].command('stop', 60.0)
    assert states(ev)[0][0] == 'RETREATING'
    ev = sims['pinky2'].command('emergency_stop', 60.0)
    assert states(ev)[0][0] == 'STOPPED'
    more, _ = run(sims, 30, start=60.0)
    assert states(more['pinky1'])[-1] == ('STOPPED', 'retreated')
    assert sims['pinky1'].held_zone is None and book.owner['A'] is None
    # 비상정지는 제자리, 토큰 유지, 유휴 복귀도 안 함 (30초 지나도 그대로)
    assert more['pinky2'] == []
    assert sims['pinky2'].held_zone == 'B' and book.owner['B'] == 'pinky2'
    assert sims['pinky2'].idle_deadline is None and sims['pinky1'].idle_deadline is None


def test_command_id_and_task_finished(fleet):
    sims, _ = fleet
    ev = sims['pinky1'].command('{"command_id": "job-7", "command": "goto:P1"}', 0.0)
    more, _ = run(sims, 5)
    all_ev = ev + more['pinky1']
    task = [e for e in all_ev if 'command_id' in e]
    assert task and all(e['command_id'] == 'job-7' for e in task)
    assert [e['state'] for e in task if e['task_finished']] == ['DONE']
    after = [e for e in all_ev if e['state'] == 'IDLE_WAIT']
    assert after and 'command_id' not in after[0]

    rejected = sims['pinky1'].command('{"command_id": "job-8", "command": "goto:P99"}', 5.0)
    assert rejected[0]['task_finished'] is True and rejected[0]['command_id'] == 'job-8'


def test_idle_return_goes_home(fleet):
    sims, _ = fleet
    sims['pinky1'].idle_return_sec = 5.0
    sims['pinky1'].command('goto:P1', 0.0)
    ev, _ = run(sims, 15)
    seq = states(ev['pinky1'])
    assert ('RETURNING', 'I1') in seq
    assert seq[-1] == ('DONE', 'returned home')
    assert sims['pinky1'].pose == sims['pinky1'].points['I1']


def test_battery_drains_and_charges(fleet):
    sim = fleet[0]['pinky1']
    sim.battery = 50.0
    sim.step(1.0, 60.0)
    assert sim.battery == pytest.approx(50.0 - sim.drain_idle)
    sim.battery = 10.0
    sim.step(2.0, 60.0)                           # 홈에서 쉬는 중이면 충전
    assert sim.battery == pytest.approx(10.0 + sim.charge_per_min)


def test_v2_to_v1():
    raw, reason = v2_to_v1('t1', 'goto', ['P1', 'P2'])
    assert reason is None and parse_command(raw) == ('goto', ['P1', 'P2'], 't1')
    assert parse_command(v2_to_v1('t2', 'leave', [])[0]) == ('leave', [], 't2')
    assert v2_to_v1('', 'goto', ['P1']) == (None, 'bad task_id')
    assert v2_to_v1('t3', 'start', []) == (None, 'unknown operation')


def v2(sim, task_id, operation, points, now):
    """v2 명령 하나를 가짜 노드와 같은 순서로 처리한다."""
    raw, reason = v2_to_v1(task_id, operation, points)
    events = sim.command(raw, now)
    return ack_for(operation, events), events


def test_v2_ack_accept_busy_and_validation(fleet):
    sim = fleet[0]['pinky1']
    assert v2(sim, 't1', 'goto', ['P99'], 0.0)[0] == (False, "unknown point: ['P99']")
    assert v2(sim, 't2', 'goto', ['P3'], 0.0)[0] == (True, '')
    assert v2(sim, 't3', 'goto', ['P1'], 0.1)[0] == (False, 'busy')
    assert v2(sim, 't4', 'stop', [], 0.2)[0] == (True, '')
    assert v2(sim, 't5', 'stop', [], 0.3)[0] == (False, 'not running')


def test_v2_state_carries_task(fleet):
    sims, _ = fleet
    sim = sims['pinky1']
    _, events = v2(sim, 't1', 'zone', ['ZA'], 0.0)
    moving = sim.v2_state(events[-1])
    assert (moving['task_id'], moving['task_finished']) == ('t1', False)
    run(sims, 10)
    last = sim.v2_state()                         # 1초 주기 발행과 같은 호출
    assert last['task_id'] == 't1' and last['task_finished'] is True
    assert last['held_zone'] == 'A'
    # 관제가 보내지 않은 작업(유휴 복귀)은 task_id 가 비어 있다
    sim.idle_return_sec = 0.5
    sim.idle_deadline = 10.0
    run(sims, 1, start=10.0)
    assert sim.v2_state()['task_id'] == ''


def test_auto_command_is_always_valid(fleet):
    sims, _ = fleet
    rng = random.Random(1)
    sim = sims['pinky1']
    for _ in range(50):
        cmd = choose_auto_command(sim, rng)
        events = sim.command(cmd, 0.0)
        assert not any(e['state'] == 'FAILED' for e in events), cmd
        sim.steps.clear()
        sim.running = False


def test_load_robot_configs_reads_split_patrol_config():
    configs = load_robot_configs(POINTS_DIR, ROBOTS)
    assert [configs[r]['home'] for r in ROBOTS] == ['I1', 'I2', 'I3']
    assert configs['pinky2']['robot_id'] == 'pinky2'
    assert configs['pinky1']['zone_points']['A'] == ['ZA']


def test_load_robot_configs_prefers_flat_profile(tmp_path):
    (tmp_path / 'pinky1.yaml').write_text(
        'pinky_patrol_node:\n  ros__parameters:\n    robot_id: pinky1\n    home_name: H\n'
        '    points:\n      H: [1.0, 2.0, 0.0]\n', encoding='utf-8')
    assert load_robot_configs(str(tmp_path), ['pinky1'])['pinky1']['home'] == 'H'


# ---------- 중앙 관제(fleet_control) 규칙 ----------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def guard():
    clock = Clock()
    return CentralGuard(timeout_sec=3.0, clock=clock), clock


def beat(clock, seq, session='s1', ttl=3.0):
    return {'session_id': session, 'seq': seq, 'issued_at': clock.now, 'ttl_sec': ttl}


def envelope(clock, seq, command='goto:P1', session='s1', ttl=5.0):
    return json.dumps({'command_id': f'c{seq}', 'command': command, 'session_id': session,
                       'seq': seq, 'issued_at': clock.now, 'ttl_sec': ttl})


def test_central_guard_accepts_only_current_session_increasing(guard):
    g, clock = guard
    # 하트비트 전에는 아무 명령도 받지 않는다
    assert central_command(g, envelope(clock, 1)) == (None, 'rejected')
    assert g.heartbeat(beat(clock, 1)) is False
    raw, result = central_command(g, envelope(clock, 1))
    assert result == 'accepted' and json.loads(raw)['command'] == 'goto:P1'
    # 같은·작은 순번, 다른 세션, 봉투 없는 글자는 거절
    assert central_command(g, envelope(clock, 1))[1] == 'rejected'
    assert central_command(g, envelope(clock, 2, session='other'))[1] == 'rejected'
    assert central_command(g, 'goto:P1')[1] == 'rejected'
    # PC 끼리 시계를 비교하지 않는다: 보낸 시각이 어긋나도 순번이 늘면 받는다
    skewed = json.loads(envelope(clock, 3))
    skewed['issued_at'] = clock.now - 300
    assert central_command(g, json.dumps(skewed))[1] == 'accepted'
    # 하트비트가 끊기면 명령을 받지 않는다 (받는 쪽 시계 워치독)
    clock.now += 4.0
    assert central_command(g, envelope(clock, 4))[1] == 'rejected'


def test_central_guard_stop_latches_until_reset(guard):
    g, clock = guard
    g.heartbeat(beat(clock, 1))
    # 정지는 봉투가 없어도 늘 받고 잠근다
    assert central_command(g, '{"command_id": "x", "command": "emergency_stop"}')[1] == 'stop'
    assert g.latched
    assert central_command(g, envelope(clock, 1))[1] == 'rejected'
    assert central_command(g, envelope(clock, 2, command='control_reset')) == (None, 'reset')
    assert not g.latched
    assert central_command(g, envelope(clock, 3))[1] == 'accepted'


def test_central_guard_session_change_and_heartbeat_loss_latch(guard):
    g, clock = guard
    g.heartbeat(beat(clock, 1))
    # 움직이던 중 서버가 다시 켜져 세션이 바뀌면 정지해야 한다
    assert g.heartbeat(beat(clock, 1, session='s2'), busy=True) is True and g.latched
    # 예전 세션의 하트비트는 다시 받지 않는다
    assert g.heartbeat(beat(clock, 5, session='s1')) is False
    central_command(g, envelope(clock, 1, command='control_reset', session='s2'))
    assert not g.latched and g.expired(busy=True) is False
    clock.now += 3.5
    assert g.expired(busy=True) is True and g.latched
    assert g.expired(busy=True) is False      # 한 번만 알린다


def test_central_guard_idle_robot_is_not_latched(guard):
    # 놀던 로봇은 관제 재시작·통신 끊김에도 잠그지 않는다 (실물 순찰 노드와 같음)
    g, clock = guard
    g.heartbeat(beat(clock, 1))
    assert g.heartbeat(beat(clock, 1, session='s2'), busy=False) is False and not g.latched
    assert central_command(g, envelope(clock, 1, session='s2'))[1] == 'accepted'
    assert central_command(g, envelope(clock, 2, session='s1'))[1] == 'rejected'
    clock.now += 3.5
    assert g.expired(busy=False) is False and not g.latched
    assert central_command(g, envelope(clock, 2, session='s2'))[1] == 'rejected'
    g.heartbeat(beat(clock, 2, session='s2'))
    assert central_command(g, envelope(clock, 2, session='s2'))[1] == 'accepted'


def test_status_carries_zone_and_busy_fields(fleet):
    sims, _ = fleet
    sim = sims['pinky1']
    assert sim.status() == dict(sim.last_event, task_finished=False, held_zone=None,
                                arrived_zone=None, busy=False)
    sim.command('{"command_id": "job-z", "command": "zone:ZA"}', 0.0)
    status = sim.status()
    assert status['busy'] is True and status['command_id'] == 'job-z'
    assert status['task_finished'] is False
    run(sims, 10)
    status = sim.status()
    # 구역 목표에 도착해야 arrived_zone 이 생긴다. 주기 상태는 끝난 작업을 다시 완료로 알리지 않는다
    assert status['held_zone'] == 'A' and status['arrived_zone'] == 'A'
    assert status['busy'] is False and status['task_finished'] is False
    assert 'command_id' not in status
    sim.command('leave', 20.0)
    assert sim.arrived_zone is None and sim.held_zone == 'A'
    run(sims, 10, start=20.0)
    assert sim.held_zone is None and sim.arrived_zone is None


def test_central_guard_plain_stop_does_not_latch(guard):
    g, clock = guard
    g.heartbeat(beat(clock, 1))
    # 일반 정지는 늘 받지만 잠그지 않는다 (비상정지만 잠금, 실물 순찰 노드와 같음)
    assert central_command(g, '{"command_id": "x", "command": "stop"}')[1] == 'stop'
    assert not g.latched
    assert central_command(g, envelope(clock, 1))[1] == 'accepted'
