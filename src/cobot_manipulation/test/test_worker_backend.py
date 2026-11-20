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

"""worker 백엔드: 팔 대신 같은 대화 방식을 쓰는 가짜 실행기로 시험한다 (장치를 열지 않음)."""

import shlex
import sys
import time

from cobot_manipulation.arm_backend_utils import (
    judge_done, make_backend, parse_worker_line, run_message)
import pytest

NOW = 1_000_000.0
PORT = '/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_TEST-if00'

# 가짜 실행기. DONE 은 run 마다 돌려줄 done 의 나머지 필드, MODE 로 동작을 바꾼다.
FAKE_WORKER = r"""
import json, os, sys
mode = sys.argv[1]
done = json.loads(sys.argv[2])
def emit(**e):
    print('@fleet ' + json.dumps(e), flush=True)
print('사람용 로그', os.environ['ARM_ID'], os.environ['ROBOT_PORT'], flush=True)
if mode == 'fatal':
    emit(event='fatal', detail='모델 없음')
    sys.exit(2)
joints = {'shoulder_pan.pos': 1.0, 'gripper.pos': 50.0}
emit(event='ready', actions=['pick'], joints=joints,
     models={'pick': {'bundle': 'omx_pick_za', 'version': 'v1'}, 'bad': 'x'},
     rest_pose={'shoulder_pan': 1.0, 'bad': 'x'}, safe_tol=3.0)
for line in sys.stdin:
    msg = json.loads(line)
    if msg['cmd'] == 'quit':
        break
    if msg['cmd'] == 'state':
        joints['shoulder_pan.pos'] += 1
        emit(event='state', joints=joints)
        continue
    if msg['cmd'] == 'release':
        if mode in ('move_rest', 'move_blocked'):
            emit(event='release_moving', seconds=3.2, pose_error={}, joints=joints)
            if mode == 'move_blocked':
                emit(event='release_refused', detail='도착 못 함', pose_error={}, joints=joints)
                continue
            emit(event='released', pose_error={})
            break
        if mode == 'not_rest':
            emit(event='release_refused', detail='쉬는 자세가 아님', pose_error={}, joints=joints)
            continue
        emit(event='released', pose_error={})
        break
    if msg['cmd'] == 'hold':
        emit(event='done', id=held, success=False, end_reason='hold', arm_safe=False)
        continue
    if msg['action'] != 'pick':
        emit(event='rejected', id=msg['id'], detail='모델 없음')
        continue
    emit(event='started', id=msg['id'])
    if mode == 'hang':
        held = msg['id']
        continue
    if mode == 'crash':
        sys.exit(1)
    emit(event='done', id=msg['id'], box=msg.get('box'), **done)
"""


def request(**overrides):
    """fleet_control_node.work() 가 보내는 모양의 요청."""
    base = {'request_id': 'req1', 'order_id': 'ord1', 'robot_id': 'pinky1', 'stage': 'PICK',
            'target': 'omx1', 'action': 'pick', 'timeout_sec': 300.0, 'session_id': 's1',
            'seq': 1, 'issued_at': NOW, 'ttl_sec': 5.0}
    base.update(overrides)
    return base


def worker(mode='ok', done=None, **options):
    """가짜 실행기를 쓰는 백엔드. logs 에 로그를 모은다."""
    import json
    command = ' '.join(shlex.quote(part) for part in (
        sys.executable, '-c', FAKE_WORKER, mode, json.dumps(done or {})))
    logs = []
    backend = make_backend('worker', 2.0, {'arm_id': 'omx1', 'command': command,
                                           'log': logs.append, **options})
    return backend, logs


def wait(backend, now=NOW, until=None, limit_sec=10.0):
    """until(backend, 결과) 가 참이 될 때까지 poll 한다. 모은 결과를 돌려준다."""
    finished = []
    end = time.monotonic() + limit_sec
    while time.monotonic() < end:
        finished += backend.poll(now)
        if until(backend, finished):
            return finished
        time.sleep(0.02)
    raise AssertionError('기다린 상태가 오지 않음')


def ready(backend):
    backend.attach(PORT, NOW)
    wait(backend, until=lambda b, _: b.ready)


def test_runs_job_and_succeeds_only_with_success_and_arm_safe():
    backend, logs = worker(done={'success': True, 'arm_safe': True, 'end_reason': 'success',
                                 'success_basis': 'judge', 'joints': {'gripper.pos': 11.0}})
    assert backend.start(request(), PORT, NOW) == '팔 실행기 준비 중 (팔 연결·모델 불러오는 중)'
    ready(backend)
    assert any('사람용 로그 omx1 ' + PORT in line for line in logs)
    assert backend.start(request(), PORT, NOW) is None
    assert backend.start(request(request_id='b'), PORT, NOW) == '팔 작업 중'
    [(done, success, data, detail)] = wait(backend, until=lambda _, f: f)
    assert done['request_id'] == 'req1' and success is True and detail == ''
    assert data['arm_safe'] is True and data['joints'] == {'gripper.pos': 11.0}
    assert 'retry_safe' not in data and not backend.busy()
    backend.shutdown()
    assert backend.process.wait(timeout=5) == 0


def test_ready_keeps_worker_info_and_done_keeps_model():
    backend, _ = worker(done={'success': True, 'arm_safe': True, 'model': 'omx_pick_za@v1'})
    assert backend.worker_info == {}
    ready(backend)
    assert backend.worker_info == {
        'actions': ['pick'], 'models': {'pick': {'bundle': 'omx_pick_za', 'version': 'v1'}},
        'rest_pose': {'shoulder_pan': 1.0}, 'safe_tol': 3.0}
    assert backend.start(request(), PORT, NOW) is None
    [(_, success, data, _)] = wait(backend, until=lambda _, f: f)
    assert success is True and data['model'] == 'omx_pick_za@v1'
    backend.shutdown()
    assert backend.worker_info['actions'] == ['pick']  # 끈 뒤에도 마지막 값을 남긴다


def test_shelf_row_goes_to_worker_as_box():
    """주문 선반 행이 실행기 run 의 box 로 가고, 결과 data 에 남는다."""
    backend, _ = worker(done={'success': True, 'arm_safe': True})
    ready(backend)
    assert backend.start(request(shelf_row=3, shelf_col=2), PORT, NOW) is None
    [(_, success, data, _)] = wait(backend, until=lambda _, f: f)
    assert success is True and data['box'] == 3
    backend.shutdown()


@pytest.mark.parametrize('row', [None, 0, -1, True, 2.0, '2'])
def test_run_message_skips_missing_or_bad_row(row):
    """행이 없거나 1 이상 정수가 아니면 box 를 싣지 않는다 (박스 모델이면 실행기가 거절)."""
    extra = {} if row is None else {'shelf_row': row}
    assert run_message(request(**extra)) == {'cmd': 'run', 'id': 'req1', 'action': 'pick'}


@pytest.mark.parametrize('done, part', [
    ({'success': False, 'arm_safe': True, 'success_basis': 'none'}, '성공 판단기 없음'),
    ({'success': False, 'arm_safe': True, 'success_basis': 'judge'}, '성공 판단 안 나옴'),
    ({'success': True, 'arm_safe': False}, 'arm_safe'),
    ({'success': True, 'arm_safe': 'yes'}, 'arm_safe'),
    ({'success': 1, 'arm_safe': True}, '성공 판단 안 나옴'),
])
def test_judge_done_failures_never_retry_safe(done, part):
    success, data, detail = judge_done(done)
    assert success is False and part in detail and 'retry_safe' not in data


def test_worker_rejection_is_retry_safe():
    backend, _ = worker()
    ready(backend)
    backend.start(request(action='load'), PORT, NOW)
    [(_, success, data, detail)] = wait(backend, until=lambda _, f: f)
    assert success is False and data == {'retry_safe': True} and '모델 없음' in detail
    backend.shutdown()


def test_hold_fails_job_at_once_and_stays_busy_until_worker_stops():
    backend, _ = worker('hang')
    ready(backend)
    backend.start(request(), PORT, NOW)
    [(done, success, data, detail)] = backend.hold(NOW)
    assert done['request_id'] == 'req1' and success is False and 'hold' in detail
    assert 'retry_safe' not in data and backend.busy()
    assert wait(backend, until=lambda b, _: not b.busy()) == []
    backend.shutdown()


def test_timeout_sends_hold():
    backend, _ = worker('hang', timeout_sec=10.0)
    ready(backend)
    backend.start(request(timeout_sec=1.0), PORT, NOW)
    assert backend.poll(NOW + 0.5) == []
    [(_, success, _, detail)] = backend.poll(NOW + 1.0)
    assert success is False and '시간 초과' in detail
    wait(backend, now=NOW + 1.0, until=lambda b, _: not b.busy())
    backend.shutdown()


def test_crash_fails_job_and_backend_stays_dead():
    backend, _ = worker('crash')
    ready(backend)
    backend.start(request(), PORT, NOW)
    [(_, success, data, detail)] = wait(backend, until=lambda _, f: f)
    assert success is False and '끝남' in detail and 'retry_safe' not in data
    assert '실행기 없음' in backend.start(request(request_id='b'), PORT, NOW)
    backend.attach(PORT, NOW)    # 다시 띄우지 않는다
    assert backend.process.poll() is not None


def test_fatal_before_ready_rejects_work():
    backend, logs = worker('fatal')
    backend.attach(PORT, NOW)
    wait(backend, until=lambda b, _: b.dead)
    assert '모델 없음' in backend.start(request(), PORT, NOW)


def test_missing_or_bad_command():
    backend = make_backend('worker', 2.0, {'arm_id': 'omx1', 'command': ''})
    backend.attach(PORT, NOW)
    assert 'worker_command' in backend.start(request(), PORT, NOW)
    backend = make_backend('worker', 2.0, {'arm_id': 'omx1', 'command': '/nonexistent/worker'})
    backend.attach(PORT, NOW)
    assert '실행기 실행 실패' in backend.start(request(), PORT, NOW)


def test_parse_worker_line():
    assert parse_worker_line('그냥 로그') is None
    assert parse_worker_line('@fleet {"event": "ready"}') == {'event': 'ready'}
    for bad in ['@fleet not json', '@fleet []', '@fleet {"id": 1}']:
        with pytest.raises(ValueError):
            parse_worker_line(bad)


def test_state_updates_joints():
    backend, _ = worker()
    ready(backend)
    assert backend.joints == {'shoulder_pan.pos': 1.0, 'gripper.pos': 50.0}
    backend.request_state(NOW)
    backend.request_state(NOW)    # 답을 기다리는 동안 두 번 보내지 않는다
    wait(backend, until=lambda b, _: b.joints['shoulder_pan.pos'] == 2.0)
    assert backend.joints_at is not None and not backend.state_pending
    backend.shutdown()


def test_release_at_rest_ends_worker_without_fault():
    backend, _ = worker()
    ready(backend)
    backend.release(NOW)
    wait(backend, until=lambda b, _: b.release_result is not None)
    assert backend.take_release() == (True, '') and backend.take_release() is None
    wait(backend, until=lambda b, _: not b.running() and b.events.empty())
    backend.poll(NOW)
    assert backend.dead == ''    # 정상 끄기 뒤의 끝남은 고장이 아니다
    backend.reset()
    backend.attach(PORT, NOW)    # reset 뒤에는 다시 켤 수 있다
    wait(backend, until=lambda b, _: b.ready)
    backend.shutdown()


def test_release_refused_keeps_worker():
    backend, _ = worker('not_rest')
    ready(backend)
    backend.release(NOW)
    wait(backend, until=lambda b, _: b.release_result is not None)
    assert backend.take_release() == (False, '쉬는 자세가 아님')
    assert backend.running() and backend.ready and not backend.releasing
    backend.shutdown()


def test_release_moves_to_rest_then_ends():
    backend, logs = worker('move_rest')
    ready(backend)
    backend.release(NOW)
    wait(backend, until=lambda b, _: b.release_result is not None)
    assert backend.take_release_moving() == 3.2 and backend.take_release_moving() is None
    assert backend.take_release() == (True, '')
    assert any('쉬는 자세로 이동' in line for line in logs)
    wait(backend, until=lambda b, _: not b.running() and b.events.empty())
    backend.poll(NOW)
    assert backend.dead == ''
    backend.reset()
    assert backend.release_moving is None


def test_release_move_blocked_keeps_worker():
    backend, _ = worker('move_blocked')
    ready(backend)
    backend.release(NOW)
    wait(backend, until=lambda b, _: b.release_result is not None)
    assert backend.take_release_moving() == 3.2
    assert backend.take_release() == (False, '도착 못 함')
    assert backend.running() and backend.ready and not backend.releasing
    backend.shutdown()


def test_release_moving_ignored_when_not_releasing():
    backend, _ = worker()
    backend._on_event({'event': 'release_moving', 'seconds': 5})
    assert backend.take_release_moving() is None


def test_reset_after_crash_allows_new_worker():
    backend, _ = worker('crash')
    ready(backend)
    backend.start(request(), PORT, NOW)
    wait(backend, until=lambda _, f: f)
    assert backend.dead
    backend.reset()
    assert backend.dead == '' and backend.process is None
    backend.attach(PORT, NOW)
    wait(backend, until=lambda b, _: b.ready)


def test_release_without_running_worker_is_immediate():
    backend, _ = worker()
    backend.release(NOW)
    assert backend.take_release() == (True, '')
