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

"""관제 작업 요청 판정과 결과 형식, 백엔드 동작."""

import json

from cobot_manipulation.arm_backend_utils import check_domain, make_backend
from cobot_manipulation.work_contract_utils import (decode, encode, EXECUTE, IGNORE,
                                                    make_result, REJECT, reject_result,
                                                    RequestFilter)
import pytest

NOW = 1_000_000.0


def request(**overrides):
    """fleet_control_node.work() 가 보내는 모양 그대로의 요청."""
    base = {'request_id': 'req1', 'order_id': 'ord1', 'robot_id': 'pinky1', 'stage': 'PICK',
            'target': 'omx1', 'action': 'pick', 'sku': 'sku1', 'quantity': 1, 'attempt': 0,
            'route': {'pickup_arm': 'omx1', 'dropoff_arm': 'omx2'}, 'timeout_sec': 300.0,
            'session_id': 's1', 'seq': 1, 'issued_at': NOW, 'ttl_sec': 5.0}
    base.update(overrides)
    return base


def test_accepts_own_request():
    assert RequestFilter('omx1').check(request(), NOW)[0] == EXECUTE


def test_ignores_other_target():
    assert RequestFilter('omx1').check(request(target='omx2'), NOW)[0] == IGNORE


@pytest.mark.parametrize('broken', [
    {'request_id': ''}, {'stage': None}, {'session_id': 3}, {'seq': '1'}, {'seq': True},
    {'issued_at': float('nan')}, {'ttl_sec': None},
])
def test_malformed_request_is_ignored(broken):
    assert RequestFilter('omx1').check(request(**broken), NOW)[0] == IGNORE


def test_duplicate_request_runs_once():
    guard = RequestFilter('omx1')
    assert guard.check(request(), NOW)[0] == EXECUTE
    assert guard.check(request(seq=2), NOW)[0] == IGNORE


def test_seq_going_back_is_ignored_but_new_session_resets():
    guard = RequestFilter('omx1')
    guard.check(request(request_id='a', seq=5), NOW)
    assert guard.check(request(request_id='b', seq=5), NOW)[0] == IGNORE
    assert guard.check(request(request_id='c', seq=1, session_id='s2'), NOW)[0] == EXECUTE


def test_expired_request_is_rejected_as_retry_safe():
    verdict, _, retry_safe = RequestFilter('omx1').check(request(), NOW + 5.1)
    assert (verdict, retry_safe) == (REJECT, True)


def test_future_request_means_clock_skew():
    verdict, reason, retry_safe = RequestFilter('omx1').check(request(issued_at=NOW + 60), NOW)
    assert (verdict, retry_safe) == (REJECT, True)
    assert '시계' in reason


def test_hold_runs_even_when_expired_or_stale():
    guard = RequestFilter('omx1')
    guard.check(request(request_id='a', seq=9), NOW)
    hold = request(request_id='h', seq=3, stage='SAFETY', action='hold')
    assert guard.check(hold, NOW + 100)[0] == EXECUTE


def test_release_hold_is_not_exempt_from_ttl():
    release = request(stage='SAFETY', action='release_hold')
    assert RequestFilter('omx1').check(release, NOW + 100)[0] == REJECT


def test_unknown_action_is_rejected_without_retry():
    verdict, _, retry_safe = RequestFilter('omx1').check(request(action='dance'), NOW)
    assert (verdict, retry_safe) == (REJECT, False)


@pytest.mark.parametrize('action', ['pick', 'load', 'unload', 'warehouse_store', 'hold',
                                    'release_hold'])
def test_known_actions(action):
    assert RequestFilter('omx1').check(request(action=action), NOW)[0] == EXECUTE


def receive_accepts(result, sent):
    """scenario_runtime.receive() 의 결과 검사 조건을 옮긴 것."""
    return (result.get('request_id') == sent['request_id']
            and result.get('robot_id') == sent['robot_id']
            and result.get('stage') == sent['stage']
            and result.get('source') == sent['route']['pickup_arm']
            and result.get('measured') is True and result.get('finished') is True
            and isinstance(result.get('data', {}), dict)
            and isinstance(result.get('success'), bool))


def test_result_passes_fleet_receive_checks():
    sent = request()
    result = json.loads(encode(make_result(sent, 'omx1', True, {'arm_safe': True})))
    assert receive_accepts(result, sent)
    assert result['order_id'] == 'ord1'


def test_reject_result_marks_retry_safe_only_when_asked():
    sent = request()
    safe = reject_result(sent, 'omx1', '탐지 안 됨', True)
    unsafe = reject_result(sent, 'omx1', '모르는 action', False)
    assert receive_accepts(safe, sent) and safe['success'] is False
    assert safe['data'] == {'retry_safe': True} and safe['detail'] == '탐지 안 됨'
    assert 'retry_safe' not in unsafe['data']


@pytest.mark.parametrize('text', ['[]', 'not json', '{"a": "' + 'x' * 17000 + '"}'])
def test_decode_rejects_bad_messages(text):
    with pytest.raises(ValueError):
        decode(text)


def test_fake_backend_finishes_after_duration_and_one_job_at_a_time():
    backend = make_backend('fake', 2.0)
    assert backend.start(request(), '/dev/x', NOW) is None
    assert backend.start(request(request_id='b'), '/dev/x', NOW) == '팔 작업 중'
    assert backend.poll(NOW + 1.0) == []
    [(done, success, data, _)] = backend.poll(NOW + 2.0)
    assert done['request_id'] == 'req1' and success is True
    assert data == {'arm_safe': True, 'fake': True}
    assert not backend.busy()


def test_fake_backend_hold_ends_job_as_failure():
    backend = make_backend('fake', 2.0)
    backend.start(request(), '/dev/x', NOW)
    [(_, success, data, detail)] = backend.hold(NOW)
    assert success is False and 'retry_safe' not in data and detail
    assert backend.hold(NOW) == []


def test_no_backend_rejects_everything():
    assert make_backend('none', 2.0).start(request(), '/dev/x', NOW)
    with pytest.raises(ValueError):
        make_backend('moveit', 2.0)


@pytest.mark.parametrize('domain, ok', [
    ('', False), ('abc', False), ('0', False), ('10', False), ('12', False), ('100', False),
    ('101', True), ('77', True),
])
def test_fake_only_in_isolated_domain(domain, ok):
    assert check_domain({'ROS_DOMAIN_ID': domain})[0] is ok
