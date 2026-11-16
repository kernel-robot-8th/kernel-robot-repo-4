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

"""로봇팔 명령 로직(arm_command_utils.py)을 ROS 없이 검사한다."""

import json
import math

from cobot_control_center import arm_command_utils as arms
from cobot_control_center import site_arms_utils as site_arms
import pytest

STATUS = {'torque_enabled': True, 'hold_active': False, 'hold_reason': '', 'work_step': 'IDLE',
          'epoch_accepted': 0, 'last_seq_accepted': 0}


def make(ack_timeout=8.0):
    return arms.ArmCommander(['omx1', 'omx_2'], 5000, ack_timeout, 1.0)


def request(command, arm_id='omx_1', request_id='r1'):
    return {'request_id': request_id, 'arm_id': arm_id, 'command': command,
            'client_request_id': 'c1', 'source': '10.0.0.5'}


def ack(header, result=0, stop_executed=False, reason=''):
    return {'command_id': header['command_id'], 'robot_id': header['robot_id'],
            'epoch': header['epoch'], 'seq': header['seq'], 'result': result,
            'stop_executed': stop_executed, 'reason': reason, 'rx_to_ack_ms': 3}


@pytest.mark.parametrize('name, expected', [
    ('omx1', 'omx_1'), ('omx_3', 'omx_3'), ('pinky', 'pinky'), ('', '')])
def test_interface_arm_id(name, expected):
    assert arms.interface_arm_id(name) == expected


def test_scenario_arm_id():
    assert arms.scenario_arm_id('omx_2') == 'omx2'


@pytest.mark.parametrize('status, online, expected', [
    (None, True, arms.STALE),
    (STATUS, False, arms.STALE),
    (STATUS, True, arms.READY),
    (dict(STATUS, work_step=''), True, arms.BUSY),
    (dict(STATUS, torque_enabled=False), True, arms.OFF),
    (dict(STATUS, hold_active=True, hold_reason='HOLD'), True, arms.HOLD),
    (dict(STATUS, hold_active=True, hold_reason='SOFT_LATCH'), True, arms.SOFT_LATCH),
    # 정지는 토크가 꺼져 있어도 보여야 한다
    (dict(STATUS, torque_enabled=False, hold_active=True), True, arms.HOLD),
])
def test_derive_state(status, online, expected):
    assert arms.derive_state(status, online) == expected


def test_every_state_allows_a_stop():
    for state, allowed in arms.ALLOWED.items():
        assert set(allowed) & arms.STOP_COMMANDS, state
        assert set(allowed) <= set(arms.COMMANDS) | {arms.WORK}, state
    # 작업 시험은 대기(READY)에서만
    assert [s for s, allowed in arms.ALLOWED.items() if arms.WORK in allowed] == [arms.READY]


def test_clean_float():
    assert arms.clean_float(1.5) == 1.5
    assert arms.clean_float(math.nan) is None
    assert arms.clean_float(math.inf) is None


def test_parse_request():
    assert arms.parse_request(json.dumps({'request_id': 'a'}))['request_id'] == 'a'
    for bad in ['', 'nope', '[1]', '{}', None]:
        with pytest.raises(ValueError):
            arms.parse_request(bad)


def test_make_command_rejects_unknown_arm_and_command():
    commander = make()
    with pytest.raises(arms.CommandError) as error:
        commander.make_command(request('start', arm_id='omx_9'), 100.0, 0.0)
    assert error.value.status == 404
    with pytest.raises(arms.CommandError) as error:
        commander.make_command(request('dance'), 100.0, 0.0)
    assert error.value.status == 400


def test_header_fields():
    commander = make()
    header, command = commander.make_command(request('START', arm_id='omx1'), 100.0, 0.0)
    assert command == 3
    assert header['robot_id'] == 'omx_1' and header['issued_by'] == 'control_center'
    assert header['ttl_ms'] == 5000 and header['issued_at'] == 100.0
    assert header['tx_id'] == 'c1' and len(header['command_id']) == 36


def test_start_uses_new_epoch_and_others_use_accepted_epoch():
    commander = make()
    first, _ = commander.make_command(request('start'), 100.0, 0.0)
    assert (first['epoch'], first['seq']) == (1, 1)
    # 응답 전에는 팔이 아직 epoch 0 이다. 정지는 팔이 받아들인 epoch 로 간다.
    hold, _ = commander.make_command(request('hold', request_id='r2'), 100.0, 0.0)
    assert (hold['epoch'], hold['seq']) == (0, 2)
    commander.put_ack(ack(first), 100.1)
    reset, _ = commander.make_command(request('reset', request_id='r3'), 100.0, 0.0)
    assert (reset['epoch'], reset['seq']) == (1, 3)
    second, _ = commander.make_command(request('start', request_id='r4'), 100.0, 0.0)
    assert second['epoch'] == 2


def test_status_raises_epoch_and_seq_after_other_controller():
    commander = make()
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=7, last_seq_accepted=40), 0.0)
    header, _ = commander.make_command(request('reset'), 100.0, 0.0)
    assert (header['epoch'], header['seq']) == (7, 41)
    start, _ = commander.make_command(request('start', request_id='r2'), 100.0, 0.0)
    assert (start['epoch'], start['seq']) == (8, 42)


def test_arm_node_restart_still_accepts_new_start():
    # 팔 노드를 다시 켜면 epoch 0·seq 0 으로 돌아온다. 새 START 는 그래도 더 크다.
    commander = make()
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=3, last_seq_accepted=9), 0.0)
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=0, last_seq_accepted=0), 1.0)
    header, _ = commander.make_command(request('start'), 100.0, 1.0)
    assert header['epoch'] == 1 and header['seq'] == 1
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=0, last_seq_accepted=0), 1.0)
    hold, _ = commander.make_command(request('hold', request_id='r2'), 100.0, 1.0)
    assert hold['epoch'] == 0 and hold['seq'] == 2


def test_ack_replies_accepted_rejected_and_stop():
    commander = make()
    header, _ = commander.make_command(request('start'), 100.0, 0.0)
    out = commander.put_ack(ack(header), 100.2)
    assert out['type'] == 'reply' and out['request_id'] == 'r1' and out['status'] == 200
    assert out['body']['result'] == 'ACCEPTED' and out['body']['command'] == 'start'
    assert out['body']['arm_id'] == 'omx_1' and out['body']['client_request_id'] == 'c1'

    header, _ = commander.make_command(request('reset', request_id='r2'), 100.0, 0.0)
    out = commander.put_ack(ack(header, result=5, reason='쉬는 자세가 아님'), 100.3)
    assert out['status'] == 409 and out['body']['result'] == 'REJECTED_STATE'
    assert out['body']['reason'] == '쉬는 자세가 아님'

    # 정지는 판정이 거부여도 멈췄으면 성공
    header, _ = commander.make_command(request('hold', request_id='r3'), 100.0, 0.0)
    out = commander.put_ack(ack(header, result=3, stop_executed=True), 100.4)
    assert out['status'] == 200 and out['body']['result'] == 'REJECTED_TTL'


def test_foreign_ack_is_recorded_but_not_replied():
    commander = make()
    other = {'command_id': 'x', 'robot_id': 'omx_1', 'epoch': 1, 'seq': 1}
    assert commander.put_ack(ack(other, result=6, reason='남의 것'), 100.0) is None
    snap = commander.snapshot(0.0, 100.0)
    assert snap['arms'][0]['last_ack']['reason'] == '남의 것'
    # 같은 응답이 두 번 와도 두 번째는 답하지 않고, 첫 기록(명령 이름)을 지우지 않는다
    header, _ = commander.make_command(request('start'), 100.0, 0.0)
    assert commander.put_ack(ack(header), 100.0) is not None
    assert commander.put_ack(ack(header), 100.5) is None
    last = commander.snapshot(0.0, 101.0)['arms'][0]['last_ack']
    assert last['command'] == 'start' and last['received_at'] == 100.0


def test_expire_replies_504_once():
    commander = make(ack_timeout=8.0)
    commander.make_command(request('start'), 100.0, 0.0)
    assert commander.expire(7.9) == []
    late = commander.expire(8.1)
    assert len(late) == 1 and late[0]['status'] == 504 and late[0]['request_id'] == 'r1'
    assert 'omx_1' in late[0]['body']['detail']
    assert commander.expire(9.0) == []


def test_snapshot_stale_and_pending():
    commander = make()
    snap = commander.snapshot(0.0, 100.0)
    assert snap['ttl_ms'] == 5000
    assert [a['arm_id'] for a in snap['arms']] == ['omx_1', 'omx_2']
    first = snap['arms'][0]
    assert first['state'] == arms.STALE and first['online'] is False and first['age'] is None
    assert first['alias'] == 'omx1' and first['allowed'] == ['hold', 'soft_latch']
    assert first['work'] is None and snap['work_actions'] == list(arms.WORK_ACTIONS)

    assert commander.put_status('omx_9', STATUS, 0.0) is False
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=2, last_seq_accepted=5), 10.0)
    commander.make_command(request('hold'), 100.0, 10.0)
    first = commander.snapshot(10.5, 100.5)['arms'][0]
    assert first['online'] is True and first['state'] == arms.READY
    assert first['pending'] == 1 and (first['epoch'], first['seq']) == (2, 5)
    assert commander.snapshot(11.1, 101.1)['arms'][0]['state'] == arms.STALE
    json.dumps(commander.snapshot(11.1, 101.1))   # JSON 으로 낼 수 있어야 한다


# ---------- 작업 시험 (make_work, /fleet/work_request) ----------

def work_request(action='pick', arm_id='omx_1', request_id='w1'):
    return {'request_id': request_id, 'arm_id': arm_id, 'action': action,
            'client_request_id': 'c9', 'source': '10.0.0.5'}


def ready_commander(**kwargs):
    commander = arms.ArmCommander(['omx_1', 'omx_2'], 5000, 8.0, 1.0, session_id='s1', **kwargs)
    commander.put_status('omx_1', STATUS, 10.0)
    return commander


def result_for(payload, success=True, detail='', data=None):
    """팔 노드 work_contract_utils.make_result 와 같은 모양."""
    return {'request_id': payload['request_id'], 'order_id': payload['order_id'],
            'robot_id': payload['robot_id'], 'stage': payload['stage'],
            'source': payload['target'],
            'measured': True, 'finished': True, 'success': success, 'detail': detail,
            'data': data or {}}


def test_work_payload_matches_arm_node_contract():
    commander = ready_commander(work_timeout_sec=90.0)
    payload = commander.make_work(work_request('PICK', arm_id='omx1'), 100.0, 10.5)
    # 팔 노드 RequestFilter: target 은 시나리오 이름, 글자 필드는 비지 않음, seq 는 int
    assert payload['target'] == 'omx1' and payload['action'] == 'pick'
    for key in ('request_id', 'stage', 'action', 'session_id'):
        assert isinstance(payload[key], str) and payload[key], key
    assert payload['stage'] == 'MANUAL_TEST' and payload['session_id'] == 's1'
    assert payload['seq'] == 1 and type(payload['seq']) is int
    assert payload['issued_at'] == 100.0 and payload['ttl_sec'] == 5.0
    assert payload['timeout_sec'] == 90.0
    assert payload['order_id'] == '' and payload['robot_id'] == ''
    json.dumps(payload, allow_nan=False)


def test_work_rejects_unknown_arm_action_and_not_ready():
    commander = ready_commander()
    for request, status in [(work_request(arm_id='omx_9'), 404),
                            (work_request('dance'), 400), (work_request('hold'), 400),
                            (work_request(arm_id='omx_2'), 409)]:   # omx_2 상태 없음 → STALE
        with pytest.raises(arms.CommandError) as error:
            commander.make_work(request, 100.0, 10.5)
        assert error.value.status == status, request
    for status in [dict(STATUS, torque_enabled=False), dict(STATUS, work_step=''),
                   dict(STATUS, hold_active=True, hold_reason='HOLD')]:
        commander.put_status('omx_1', status, 10.0)
        with pytest.raises(arms.CommandError) as error:
            commander.make_work(work_request(), 100.0, 10.5)
        assert error.value.status == 409
    # 상태가 끊겨도(STALE) 안 된다
    commander.put_status('omx_1', STATUS, 10.0)
    with pytest.raises(arms.CommandError):
        commander.make_work(work_request(), 100.0, 11.5)


def test_work_one_at_a_time_and_seq_grows():
    commander = ready_commander()
    first = commander.make_work(work_request(), 100.0, 10.5)
    snap = commander.snapshot(10.5, 100.0)['arms'][0]
    assert snap['work']['state'] == arms.WORK_RUNNING and arms.WORK not in snap['allowed']
    with pytest.raises(arms.CommandError) as error:
        commander.make_work(work_request('load', request_id='w2'), 100.0, 10.6)
    assert error.value.status == 409 and '진행 중' in error.value.detail
    record = commander.put_work_result(result_for(first), 130.0)
    assert record['state'] == arms.WORK_SUCCEEDED and record['duration'] == 30.0
    assert record['arm_id'] == 'omx_1' and record['client_request_id'] == 'c9'
    second = commander.make_work(work_request('load', request_id='w2'), 131.0, 10.7)
    assert second['seq'] == 2 and second['request_id'] != first['request_id']


def test_work_failure_keeps_retry_safe_and_detail():
    commander = ready_commander()
    payload = commander.make_work(work_request(), 100.0, 10.5)
    record = commander.put_work_result(
        result_for(payload, False, '정지 유지 중 (release_hold 필요)', {'retry_safe': True}), 100.2)
    assert record['state'] == arms.WORK_FAILED and record['retry_safe'] is True
    assert record['detail'] == '정지 유지 중 (release_hold 필요)'
    payload = commander.make_work(work_request(request_id='w2'), 101.0, 10.6)
    record = commander.put_work_result(result_for(payload, False, '작업 중 정지'), 140.0)
    assert record['retry_safe'] is False
    # NaN 이 든 data 는 스냅샷 JSON 을 깨지 않게 버린다
    payload = commander.make_work(work_request(request_id='w3'), 141.0, 10.7)
    record = commander.put_work_result(result_for(payload, data={'x': math.nan}), 142.0)
    assert record['data'] == {}
    json.dumps(commander.snapshot(10.8, 142.0), allow_nan=False)


def test_work_ignores_foreign_and_duplicate_results():
    commander = ready_commander()
    payload = commander.make_work(work_request(), 100.0, 10.5)
    assert commander.put_work_result({'request_id': 'order-work', 'success': True}, 101.0) is None
    assert commander.put_work_result('nope', 101.0) is None
    assert commander.snapshot(10.6, 101.0)['arms'][0]['work']['state'] == arms.WORK_RUNNING
    assert commander.put_work_result(result_for(payload), 102.0) is not None
    assert commander.put_work_result(result_for(payload, False), 102.5) is None
    assert commander.snapshot(10.6, 103.0)['arms'][0]['work']['state'] == arms.WORK_SUCCEEDED


def test_work_without_result_expires_once():
    commander = ready_commander(work_timeout_sec=60.0, work_margin_sec=10.0)
    payload = commander.make_work(work_request(), 100.0, 10.0)
    assert commander.expire_works(79.9, 170.0) == []
    late = commander.expire_works(80.1, 170.1)
    assert len(late) == 1 and late[0]['state'] == arms.WORK_NO_RESULT
    assert late[0]['arm_id'] == 'omx_1'
    assert commander.expire_works(90.0, 180.0) == []
    # 늦게 온 결과는 기록을 바꾸지 않는다
    assert commander.put_work_result(result_for(payload), 200.0) is None


# ---------- 알람: 기록(take_events)·활성 알람(snapshot arms[].alarms) ----------

def kinds(commander):
    return [(e['arm'], e['kind'], e['level'], e['text']) for e in commander.take_events()]


def alarms(commander, now_mono, now_wall=200.0, index=0):
    return [a['code'] for a in commander.snapshot(now_mono, now_wall)['arms'][index]['alarms']]


def test_link_state_and_boot_events():
    commander = make()
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b1'), 0.0, 100.0)
    assert kinds(commander) == [('omx_1', 'link', 'info', '연결됨 (대기)')]
    # 대기 ↔ 작업 중은 기록하지 않는다 (작업 결과로 대신)
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b1', work_step=''), 0.1, 100.1)
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b1'), 0.2, 100.2)
    assert kinds(commander) == []
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b1', hold_active=True,
                                       hold_reason='HOLD'), 0.3, 100.3)
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b1', hold_active=True,
                                       hold_reason='SOFT_LATCH'), 0.4, 100.4)
    assert kinds(commander) == [('omx_1', 'state', 'warn', '대기 → 정지'),
                                ('omx_1', 'state', 'bad', '정지 → 소프트 정지')]
    commander.put_status('omx_1', dict(STATUS, robot_boot_id='b2', torque_enabled=False),
                         0.5, 100.5)
    out = kinds(commander)
    assert out[0][1:3] == ('boot', 'warn') and out[1] == ('omx_1', 'state', 'info',
                                                          '소프트 정지 → 꺼짐')


def test_link_lost_once_and_offline_alarm():
    commander = make()
    commander.check_links(5.0, 105.0)
    assert kinds(commander) == [] and alarms(commander, 5.0) == []   # 받은 적 없으면 알람 없음
    commander.put_status('omx_1', STATUS, 0.0, 100.0)
    commander.take_events()
    commander.check_links(0.9, 100.9)
    assert kinds(commander) == []
    commander.check_links(1.5, 101.5)
    commander.check_links(2.5, 102.5)
    assert [k[1:3] for k in kinds(commander)] == [('link', 'bad')]
    snap = commander.snapshot(2.5, 102.5)['arms'][0]
    assert snap['alarms'][0]['code'] == 'offline' and snap['alarms'][0]['since'] == 101.5
    # 다시 들어오면 연결됨 기록, 알람 풀림
    commander.put_status('omx_1', STATUS, 3.0, 103.0)
    assert kinds(commander) == [('omx_1', 'link', 'info', '연결됨 (대기)')]
    assert alarms(commander, 3.0) == []


def test_hold_and_soft_latch_alarms():
    commander = make()
    commander.put_status('omx_1', dict(STATUS, hold_active=True, hold_reason='HOLD'), 0.0, 100.0)
    snap = commander.snapshot(0.1, 100.1)['arms'][0]
    assert [a['code'] for a in snap['alarms']] == ['hold'] and snap['alarms'][0]['since'] == 100.0
    commander.put_status('omx_1', dict(STATUS, hold_active=True, hold_reason='SOFT_LATCH'),
                         0.2, 100.2)
    assert alarms(commander, 0.3) == ['soft_latch']
    commander.put_status('omx_1', STATUS, 0.4, 100.4)
    assert alarms(commander, 0.5) == []


def test_ack_and_timeout_events():
    commander = make()
    header, _ = commander.make_command(request('start'), 100.0, 0.0)
    commander.put_ack(ack(header), 100.1)
    header, _ = commander.make_command(request('reset', request_id='r2'), 100.0, 0.0)
    commander.put_ack(ack(header, result=5, reason='쉬는 자세 아님'), 100.2)
    header, _ = commander.make_command(request('hold', request_id='r3'), 100.0, 0.0)
    commander.put_ack(ack(header, result=3, stop_executed=True), 100.3)
    commander.put_ack(ack(header, result=3, stop_executed=True), 100.35)   # 두 번째: 기록 없음
    commander.put_ack(ack({'command_id': 'x', 'robot_id': 'omx_1', 'epoch': 1, 'seq': 9},
                          result=1), 100.4)
    assert kinds(commander) == [
        ('omx_1', 'ack', 'info', '켜기 → 수락'),
        ('omx_1', 'ack', 'warn', '끄기 → REJECTED_STATE: 쉬는 자세 아님'),
        ('omx_1', 'ack', 'info', '정지 → REJECTED_TTL (정지는 실행됨)'),
        ('omx_1', 'ack', 'warn', '다른 곳이 낸 명령 → REJECTED_EPOCH')]
    commander.make_command(request('start', request_id='r4'), 100.0, 0.0)
    commander.expire(9.0, 109.0)
    assert kinds(commander) == [('omx_1', 'timeout', 'bad', '켜기 → 응답 없음 (8s)')]


def test_posture_alarm_from_work_and_cleared():
    commander = ready_commander()
    commander.take_events()
    payload = commander.make_work(work_request('unload'), 100.0, 10.5)
    commander.put_work_result(result_for(payload, False, 'hold 로 작업 중단'), 102.0)
    out = kinds(commander)
    assert out == [('omx_1', 'work', 'bad', '작업 시험 unload → 실패 (2.0 s): hold 로 작업 중단')]
    assert alarms(commander, 10.6) == ['posture_unknown']
    # 끄기 수락으로 풀림 (쉬는 자세를 확인하고 꺼짐)
    header, _ = commander.make_command(request('reset'), 103.0, 10.6)
    commander.put_ack(ack(header), 103.1)
    assert alarms(commander, 10.7) == []
    # 팔을 안 움직인 거절(retry_safe)은 알람 없이 warn 기록
    commander.put_status('omx_1', STATUS, 10.7, 104.0)
    payload = commander.make_work(work_request(request_id='w2'), 104.0, 10.7)
    commander.put_work_result(result_for(payload, False, '만료', {'retry_safe': True}), 104.1)
    assert kinds(commander)[-1][2] == 'warn' and alarms(commander, 10.8) == []
    # 결과 없음 → 알람, 다음 성공으로 풀림
    commander.make_work(work_request(request_id='w3'), 105.0, 10.8)
    commander.expire_works(500.0, 600.0)
    assert kinds(commander)[-1][1:3] == ('work', 'bad')
    assert alarms(commander, 10.9) == ['posture_unknown']
    commander.put_status('omx_1', STATUS, 501.0, 601.0)
    payload = commander.make_work(work_request(request_id='w4'), 602.0, 501.0)
    commander.put_work_result(result_for(payload), 610.0)
    assert alarms(commander, 501.1) == []


def test_order_work_results_are_logged_once():
    commander = ready_commander()
    commander.take_events()
    order = {'request_id': 'o-1', 'order_id': 'order-001', 'robot_id': 'pinky1',
             'stage': 'PICK', 'source': 'omx1', 'measured': True, 'finished': True,
             'success': False, 'detail': '보드 연결 끊김', 'data': {}}
    assert commander.put_work_result(order, 100.0) is None   # 내 작업이 아니라 답은 없음
    assert commander.put_work_result(order, 100.5) is None   # 두 번 와도 기록은 한 번
    assert kinds(commander) == [('omx_1', 'work', 'bad',
                                 '주문 작업 PICK → 실패 (order-001, pinky1): 보드 연결 끊김')]
    assert alarms(commander, 10.5) == ['posture_unknown']
    # 모르는 팔의 결과는 버린다
    commander.put_work_result(dict(order, request_id='o-2', source='omx9'), 101.0)
    assert kinds(commander) == []


# ---------- 현장 팔 배치 (config/site_arms.yaml) ----------

def test_parse_site_arms_keeps_order_and_blanks():
    site = site_arms.parse_site_arms({'arms': {
        'omx1': {'station': 'ZA', 'role': 'pickup', 'host': '8-OMEN', 'serial': '77aa01'},
        'omx_2': {'station': 'ZB', 'role': '', 'host': None},
        'omx3': None}})
    assert list(site) == ['omx_1', 'omx_2', 'omx_3']
    assert site['omx_1'] == {'station': 'ZA', 'role': 'pickup', 'host': '8-OMEN',
                             'serial': '77AA01', 'actions': None}
    assert site['omx_2'] == {'station': 'ZB', 'role': '', 'host': '', 'serial': '',
                             'actions': None}
    assert site['omx_3']['station'] == ''


@pytest.mark.parametrize('data', [
    None, {}, {'arms': {}}, {'arms': []},
    {'arms': {'omx1': {'role': 'flying'}}},
    {'arms': {'omx1': {'serial': 'not-a-serial!'}}},
    {'arms': {'omx1': {'station': ['ZA']}}},
    {'arms': {'omx1': 'ZA'}},
    {'arms': {'omx1': {}, 'omx_1': {}}},    # 같은 팔 두 번
    {'arms': {'??': {}}},
])
def test_parse_site_arms_rejects_bad_files(data):
    with pytest.raises(ValueError):
        site_arms.parse_site_arms(data)


def test_installed_site_arms_file_parses():
    import pathlib
    import yaml
    path = pathlib.Path(__file__).resolve().parent.parent / 'config' / 'site_arms.yaml'
    site = site_arms.parse_site_arms(yaml.safe_load(path.read_text(encoding='utf-8')))
    assert list(site) == ['omx_1', 'omx_2', 'omx_3']
    assert [info['station'] for info in site.values()] == ['ZA', 'ZB', 'ZC']


def test_snapshot_carries_site():
    site = {'omx_1': {'station': 'ZA', 'role': 'pickup', 'host': '8-OMEN', 'serial': 'A1'}}
    commander = arms.ArmCommander(['omx_1', 'omx_2'], 5000, 8.0, 1.0, site=site)
    snap = commander.snapshot(0.0, 100.0)['arms']
    assert snap[0]['site']['station'] == 'ZA' and snap[1]['site'] is None
    json.dumps(snap)


# ---------- 자리별 작업 (site_arms.yaml actions) ----------

def test_parse_site_actions():
    site = site_arms.parse_site_arms({'arms': {
        'omx1': {'actions': ['pick', 'LOAD', 'pick']}, 'omx2': {'actions': []}, 'omx3': {}}})
    assert site['omx_1']['actions'] == ['pick', 'load']
    assert site['omx_2']['actions'] == [] and site['omx_3']['actions'] is None
    for bad in [['dance'], 'pick', [1], ['hold']]:
        with pytest.raises(ValueError):
            site_arms.parse_site_arms({'arms': {'omx1': {'actions': bad}}})


def test_work_only_for_site_actions():
    site = site_arms.parse_site_arms({'arms': {
        'omx1': {'station': 'ZA', 'actions': ['pick', 'load']},
        'omx2': {'station': 'ZC', 'actions': []}}})
    commander = arms.ArmCommander(list(site), 5000, 8.0, 1.0, site=site)
    commander.put_status('omx_1', STATUS, 10.0)
    commander.put_status('omx_2', STATUS, 10.0)
    with pytest.raises(arms.CommandError) as error:
        commander.make_work(work_request('unload'), 100.0, 10.5)
    assert error.value.status == 409 and '(ZA)' in error.value.detail
    with pytest.raises(arms.CommandError) as error:
        commander.make_work(work_request('pick', arm_id='omx_2'), 100.0, 10.5)
    assert error.value.status == 409 and '없음' in error.value.detail
    assert commander.make_work(work_request('load'), 100.0, 10.5)['action'] == 'load'
    snap = commander.snapshot(10.6, 100.6)['arms']
    assert snap[0]['work_actions'] == ['pick', 'load']
    assert snap[1]['work_actions'] == [] and arms.WORK not in snap[1]['allowed']
    # 배치 칸이 없는 팔은 제한 없음
    assert arms.ArmCommander(['omx_1'], 5000, 8.0, 1.0).snapshot(0.0, 0.0)['arms'][0][
        'work_actions'] == list(arms.WORK_ACTIONS)


def test_installed_site_actions():
    import pathlib
    import yaml
    path = pathlib.Path(__file__).resolve().parent.parent / 'config' / 'site_arms.yaml'
    site = site_arms.parse_site_arms(yaml.safe_load(path.read_text(encoding='utf-8')))
    assert [info['actions'] for info in site.values()] == [['pick', 'load'], ['pick', 'load'], []]


# ---------- 꺼짐 / 고장(FAULT) 구분 ----------

FAULT_ACK = {'accepted': False, 'result': 'REJECTED_STATE',
             'reason': '꺼짐(DISARMED)에서만 켤 수 있음 (지금 FAULT)', 'received_at': 100.0}


def test_off_allows_start_but_not_reset():
    assert 'start' in arms.ALLOWED[arms.OFF] and 'reset' not in arms.ALLOWED[arms.OFF]
    assert 'reset' in arms.ALLOWED[arms.FAULT] and 'start' not in arms.ALLOWED[arms.FAULT]


def test_fault_from_start_rejection():
    off = dict(STATUS, torque_enabled=False)
    assert arms.derive_state(off, True, FAULT_ACK) == arms.FAULT
    # 다른 거절이나 수락은 그냥 꺼짐
    assert arms.derive_state(off, True, dict(FAULT_ACK, reason='seq 역행')) == arms.OFF
    assert arms.derive_state(off, True, dict(FAULT_ACK, accepted=True)) == arms.OFF
    # 토크가 켜져 있으면(다시 켜짐) 고장이 아님
    assert arms.derive_state(STATUS, True, FAULT_ACK) == arms.READY


def test_fault_snapshot_alarm_and_clear_by_reset():
    commander = make()
    commander.put_status('omx_1', dict(STATUS, torque_enabled=False), 10.0)
    header, _ = commander.make_command(request('start'), 100.0, 10.0)
    commander.put_ack(ack(header, result=5, reason=FAULT_ACK['reason']), 100.1)
    arm = commander.snapshot(10.1, 100.2)['arms'][0]
    assert arm['state'] == arms.FAULT and arm['allowed'] == ['reset', 'hold', 'soft_latch']
    assert [a['code'] for a in arm['alarms']] == ['fault']
    header, _ = commander.make_command(request('reset', request_id='r2'), 100.3, 10.2)
    commander.put_ack(ack(header), 100.4)
    arm = commander.snapshot(10.3, 100.5)['arms'][0]
    assert arm['state'] == arms.OFF and arm['alarms'] == []
