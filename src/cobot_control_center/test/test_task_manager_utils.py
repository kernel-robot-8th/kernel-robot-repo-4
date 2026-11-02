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

"""관제 작업 관리(task_manager_utils.py)를 ROS 없이 검사한다."""

from cobot_control_center.task_manager_utils import (
    check_points, load_robot_points, TaskDB, TaskError, TaskManager, v1_command)
import pytest

ROBOT_YAML = """pinky_patrol_node:
  ros__parameters:
    home_name: {home}
    zone_points:
      A: [ZA]
      B: [ZB]
    points:
      I1: [0.0, 0.0, 0.0]
      I2: [0.0, -0.2, 0.0]
      ZA: [0.6, 0.5, -1.5]
      ZB: [0.6, -0.15, -1.5]
      ZA_EXIT: [0.45, 0.2, -1.5]
      P1: [0.17, -0.6, 0.0]
      P2: [0.45, -0.6, -1.5]
      P36: [0.0, 0.0, 0.0]
"""

ONLINE_IDLE = {'online': True, 'state': 'IDLE'}


class FakeClock:
    """시험에서 시각을 직접 정한다. 2026-11-02 근처."""

    def __init__(self):
        self.now = 1793600000.0

    def __call__(self):
        return self.now


@pytest.fixture
def rules(tmp_path):
    (tmp_path / 'pinky1.yaml').write_text(ROBOT_YAML.format(home='I1'), encoding='utf-8')
    (tmp_path / 'pinky2.yaml').write_text(ROBOT_YAML.format(home='I2'), encoding='utf-8')
    return load_robot_points(str(tmp_path), ['pinky1', 'pinky2'])


def make_tm(rules, path=':memory:', clock=None, robot=None, **kwargs):
    clock = clock or FakeClock()
    db = TaskDB(path, clock=clock)
    tm = TaskManager(db, ['pinky1', 'pinky2'], rules, clock=clock, **kwargs)
    tm.update_fleet({'robots': {'pinky1': dict(robot or ONLINE_IDLE),
                                'pinky2': dict(ONLINE_IDLE)}})
    return tm, clock


def create(tm, crid='r1', robot='pinky1', operation='goto', points=('P1',)):
    return tm.create({'client_request_id': crid, 'robot_id': robot,
                      'operation': operation, 'points': list(points)})


# ---------- 지점 규칙 ----------

def test_load_robot_points(rules):
    rule = rules['pinky1']
    assert rule['goto'] == {'P1', 'P2', 'I1'}       # 다른 로봇 홈·출구·구역·미실측 제외
    assert rule['zone'] == {'ZA', 'ZB'}
    assert rule['placeholder'] == {'P36'}
    assert rules['pinky2']['goto'] == {'P1', 'P2', 'I2'}


@pytest.mark.parametrize('operation, points, reason', [
    ('goto', ['P1', 'P2'], None),
    ('goto', ['I1'], None),
    ('goto', [], 'no point given'),
    ('goto', ['P99'], "unknown point: ['P99']"),
    ('goto', ['ZA'], "use zone: ['ZA']"),
    ('goto', ['P36'], "unmeasured point: ['P36']"),
    ('goto', ['I2'], "not allowed: ['I2']"),
    ('goto', ['ZA_EXIT'], "not allowed: ['ZA_EXIT']"),
    ('zone', ['ZA'], None),
    ('zone', ['ZA', 'ZB'], "zone needs one zone point: ['ZA', 'ZB']"),
    ('zone', ['P1'], "zone needs one zone point: ['P1']"),
    ('home', [], None),
    ('leave', ['P1'], 'leave takes no point'),
])
def test_check_points(rules, operation, points, reason):
    assert check_points(rules['pinky1'], operation, points) == reason


def test_v1_command():
    assert v1_command('goto', ['P1', 'P2']) == 'goto:P1,P2'
    assert v1_command('home', []) == 'home'


# ---------- 작업 만들기 ----------

def test_create_records_then_sends(rules):
    tm, _ = make_tm(rules)
    (status, task), actions = create(tm, points=['p1', 'P2'])
    assert status == 202
    assert task['state'] == 'SENT' and task['task_id'] == 't-20261102-0001'
    assert task['points'] == ['P1', 'P2']
    assert [h['state'] for h in task['history']] == ['ACCEPTED', 'SENT']
    assert actions == [{'robot': 'pinky1', 'spec': 'v1', 'operation': 'goto',
                        'points': ['P1', 'P2'], 'task_id': task['task_id'],
                        'command': 'goto:P1,P2'}]


def test_same_client_request_id_is_not_sent_twice(rules):
    tm, _ = make_tm(rules)
    (_, first), _ = create(tm)
    (status, again), actions = create(tm)
    assert status == 200 and again['task_id'] == first['task_id'] and actions == []
    with pytest.raises(TaskError) as error:
        create(tm, points=['P2'])
    assert error.value.status == 409


def test_create_rejections(rules):
    tm, _ = make_tm(rules)
    with pytest.raises(TaskError) as error:
        create(tm, robot='pinky9')
    assert error.value.status == 404
    with pytest.raises(TaskError) as error:
        create(tm, operation='start')
    assert error.value.status == 400
    with pytest.raises(TaskError) as error:
        tm.create({'robot_id': 'pinky1', 'operation': 'home'})
    assert error.value.status == 400

    (status, task), actions = create(tm, crid='r2', points=['P36'])
    assert (status, task['state'], actions) == (400, 'REJECTED', [])
    assert task['detail'] == "unmeasured point: ['P36']"


def test_busy_and_offline_robots_are_rejected(rules):
    tm, _ = make_tm(rules)
    create(tm)
    (status, task), _ = create(tm, crid='r2', operation='home', points=[])
    assert status == 409 and '진행 중' in task['detail']

    tm, _ = make_tm(rules, robot={'online': True, 'state': 'RETURNING', 'detail': 'I1'})
    (status, task), _ = create(tm)
    assert status == 409 and 'RETURNING' in task['detail']

    tm, _ = make_tm(rules, robot={'online': False})
    (status, _), _ = create(tm)
    assert status == 503


def test_stale_fleet_status_is_503(rules):
    tm, clock = make_tm(rules)
    clock.now += 10.0
    with pytest.raises(TaskError) as error:
        create(tm)
    assert error.value.status == 503


# ---------- v1 결과 추정 ----------

def test_v1_running_then_done(rules):
    tm, _ = make_tm(rules)
    (_, task), _ = create(tm)
    tm.on_v1_status('pinky1', {'state': 'STARTING', 'detail': 'idle return'})
    assert tm.db.get(task['task_id'])['state'] == 'SENT'     # 유휴 복귀는 이 작업이 아님
    tm.on_v1_status('pinky1', {'state': 'STARTING', 'detail': 'P1'})
    tm.on_v1_status('pinky1', {'state': 'MOVING', 'detail': 'P1'})
    assert tm.db.get(task['task_id'])['detail'] == 'MOVING P1'
    tm.on_v1_status('pinky1', {'state': 'DONE', 'detail': 'arrived P1'})
    done = tm.db.get(task['task_id'])
    assert done['state'] == 'SUCCEEDED'
    assert [h['state'] for h in done['history']] == ['ACCEPTED', 'SENT', 'RUNNING', 'SUCCEEDED']
    # 끝난 뒤 새 작업을 받는다
    assert create(tm, crid='r2')[0][0] == 202


def test_v1_immediate_failure_keeps_detail(rules):
    tm, _ = make_tm(rules)
    (_, task), _ = create(tm, operation='leave', points=[])
    tm.on_v1_status('pinky1', {'state': 'FAILED', 'detail': 'no zone held'})
    got = tm.db.get(task['task_id'])
    assert (got['state'], got['detail']) == ('FAILED', 'no zone held')


def test_v1_no_reply_becomes_unknown_and_blocks(rules):
    tm, clock = make_tm(rules, ack_timeout_sec=3.0)
    (_, task), _ = create(tm)
    tm.tick()
    clock.now += 3.5
    tm.tick()
    assert tm.db.get(task['task_id'])['state'] == 'UNKNOWN'
    tm.update_fleet({'robots': {'pinky1': ONLINE_IDLE}})
    (status, rejected), actions = create(tm, crid='r2', operation='home', points=[])
    assert status == 409 and actions == [] and '결과를 모르는' in rejected['detail']

    with pytest.raises(TaskError):
        tm.resolve({'task_id': task['task_id'], 'result': 'BOGUS'})
    (status, resolved), _ = tm.resolve({'task_id': task['task_id'], 'note': '현장 확인'})
    assert (status, resolved['state']) == (200, 'FAILED')
    assert resolved['detail'] == '해제: 현장 확인'
    with pytest.raises(TaskError) as error:
        tm.resolve({'task_id': task['task_id']})
    assert error.value.status == 409
    tm.update_fleet({'robots': {'pinky1': ONLINE_IDLE}})
    assert create(tm, crid='r3')[0][0] == 202


def test_running_timeout(rules):
    tm, clock = make_tm(rules, task_timeout_sec=100.0)
    (_, task), _ = create(tm)
    tm.on_v1_status('pinky1', {'state': 'STARTING', 'detail': 'P1'})
    clock.now += 101.0
    tm.tick()
    assert tm.db.get(task['task_id'])['state'] == 'UNKNOWN'


# ---------- v2 ----------

def test_v2_auto_ack_and_finish(rules):
    tm, _ = make_tm(rules)
    tm.on_v2_state('pinky1', {'state': 'IDLE', 'task_id': '', 'task_finished': True})
    (_, task), actions = create(tm, operation='zone', points=['ZA'])
    assert actions[0]['spec'] == 'v2' and task['spec'] == 'v2'
    tid = task['task_id']
    tm.on_v1_status('pinky1', {'state': 'DONE', 'detail': 'x'})   # v2 작업에는 v1 을 붙이지 않음
    assert tm.db.get(tid)['state'] == 'SENT'
    tm.on_v2_ack('pinky1', {'task_id': tid, 'accepted': True, 'reason': ''})
    assert tm.db.get(tid)['state'] == 'RUNNING'
    tm.on_v2_state('pinky1', {'state': 'DONE', 'task_id': 'other', 'task_finished': True})
    assert tm.db.get(tid)['state'] == 'RUNNING'
    tm.on_v2_state('pinky1', {'state': 'DONE', 'detail': 'arrived ZA', 'task_id': tid,
                              'task_finished': True})
    assert tm.db.get(tid)['state'] == 'SUCCEEDED'


def test_v2_rejected_by_robot(rules):
    tm, _ = make_tm(rules, spec_mode='v2')
    (_, task), _ = create(tm, operation='leave', points=[])
    tm.on_v2_ack('pinky1', {'task_id': task['task_id'], 'accepted': False,
                            'reason': 'no zone held'})
    got = tm.db.get(task['task_id'])
    assert (got['state'], got['detail']) == ('REJECTED', 'robot: no zone held')


def test_v2_falls_back_to_v1_when_state_is_old(rules):
    tm, clock = make_tm(rules)
    tm.on_v2_state('pinky1', {'state': 'IDLE', 'task_id': ''})
    clock.now += 5.0
    tm.update_fleet({'robots': {'pinky1': ONLINE_IDLE}})
    assert create(tm)[1][0]['spec'] == 'v1'


# ---------- 정지 ----------

def test_stop_always_sends(rules):
    tm, _ = make_tm(rules, robot={'online': False})
    (status, result), actions = tm.stop({'robot_id': 'pinky1', 'emergency': True})
    assert status == 202 and result['operation'] == 'emergency_stop' and result['warning']
    assert actions[0]['command'] == 'emergency_stop'
    assert actions[0]['task_id'].startswith('s-')
    with pytest.raises(TaskError):
        tm.stop({'robot_id': 'pinky9'})


def test_stop_ends_running_task_as_stopped(rules):
    tm, _ = make_tm(rules)
    (_, task), _ = create(tm)
    tm.on_v1_status('pinky1', {'state': 'STARTING', 'detail': 'P1'})
    (_, result), actions = tm.stop({'robot_id': 'pinky1'})
    assert result['task_id'] == task['task_id'] and actions[0]['command'] == 'stop'
    tm.on_v1_status('pinky1', {'state': 'STOPPED', 'detail': 'P1'})
    assert tm.db.get(task['task_id'])['state'] == 'STOPPED'


# ---------- 수동 명령 (개발용) ----------

def test_raw_is_refused_when_off(rules):
    tm, _ = make_tm(rules)
    with pytest.raises(TaskError) as err:
        tm.raw({'robot_id': 'pinky1', 'command': 'goto:P1'})
    assert err.value.status == 403
    assert tm.snapshot()['allow_raw_cmd'] is False


def test_raw_sends_once_to_v1_without_task(rules):
    tm, _ = make_tm(rules, allow_raw_cmd=True)
    (status, result), actions = tm.raw({'robot_id': 'pinky1', 'command': '  goto:P1,P2 ',
                                        'client_request_id': 'r9'})
    assert status == 202 and result['command'] == 'goto:P1,P2' and result['warning']
    assert (result['topic'], result['msg_type']) == ('/pinky1/patrol_cmd', 'std_msgs/msg/String')
    assert actions == [{'robot': 'pinky1', 'spec': 'v1', 'operation': 'raw', 'points': [],
                        'task_id': result['raw_id'], 'command': 'goto:P1,P2'}]
    assert result['raw_id'].startswith('m-')
    # 작업 표에는 남지 않는다 (사건으로만)
    assert tm.db.recent() == [] and tm.take_changed() == []
    assert tm.snapshot()['allow_raw_cmd'] is True


@pytest.mark.parametrize('command', ['', '   ', 'goto:P1\nhome', 'x' * 201, None, 3])
def test_raw_rejects_bad_text(rules, command):
    tm, _ = make_tm(rules, allow_raw_cmd=True)
    with pytest.raises(TaskError) as err:
        tm.raw({'robot_id': 'pinky1', 'command': command})
    assert err.value.status == 400


def test_raw_blocked_by_task_and_unknown_robot(rules):
    tm, clock = make_tm(rules, allow_raw_cmd=True)
    with pytest.raises(TaskError) as err:
        tm.raw({'robot_id': 'pinky9', 'command': 'home'})
    assert err.value.status == 404
    create(tm)
    with pytest.raises(TaskError) as err:
        tm.raw({'robot_id': 'pinky1', 'command': 'home'})
    assert err.value.status == 409 and '진행 중' in err.value.detail
    # 응답이 없어 결과 모름이 되어도 막는다
    clock.now += 10.0
    tm.tick()
    with pytest.raises(TaskError) as err:
        tm.raw({'robot_id': 'pinky1', 'command': 'home'})
    assert err.value.status == 409 and '결과를 모르는' in err.value.detail
    # 다른 로봇은 보낼 수 있다
    assert tm.raw({'robot_id': 'pinky2', 'command': 'home'})[0][0] == 202


# ---------- 기록 ----------

def test_restart_marks_unfinished_unknown(rules, tmp_path):
    path = str(tmp_path / 'db' / 'tasks.db')
    clock = FakeClock()
    tm, _ = make_tm(rules, path=path, clock=clock)
    (_, task), _ = create(tm)
    tm.db.close()

    db = TaskDB(path, clock=clock)
    recovered = db.recover()
    assert [t['task_id'] for t in recovered] == [task['task_id']]
    got = db.get(task['task_id'])
    assert got['state'] == 'UNKNOWN' and '재시작' in got['detail']
    assert db.next_task_id() == 't-20261102-0002'


def test_prune_keeps_tasks(rules):
    tm, clock = make_tm(rules)
    (_, task), _ = create(tm)
    clock.now += 31 * 86400.0
    assert tm.db.prune(30) == 2
    assert tm.db.get(task['task_id'])['state'] == 'SENT'
    assert tm.db.prune(0) == 0


def test_changed_and_snapshot(rules):
    tm, _ = make_tm(rules)
    create(tm)
    changed = tm.take_changed()
    assert [t['state'] for t in changed] == ['ACCEPTED', 'SENT']
    assert tm.take_changed() == []
    snap = tm.snapshot()
    assert snap['robots'] == ['pinky1', 'pinky2'] and len(snap['tasks']) == 1
    assert snap['spec'] == {'pinky1': 'v1', 'pinky2': 'v1'}
