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
        assert set(allowed) <= set(arms.COMMANDS), state


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

    assert commander.put_status('omx_9', STATUS, 0.0) is False
    commander.put_status('omx_1', dict(STATUS, epoch_accepted=2, last_seq_accepted=5), 10.0)
    commander.make_command(request('hold'), 100.0, 10.0)
    first = commander.snapshot(10.5, 100.5)['arms'][0]
    assert first['online'] is True and first['state'] == arms.READY
    assert first['pending'] == 1 and (first['epoch'], first['seq']) == (2, 5)
    assert commander.snapshot(11.1, 101.1)['arms'][0]['state'] == arms.STALE
    json.dumps(commander.snapshot(11.1, 101.1))   # JSON 으로 낼 수 있어야 한다
