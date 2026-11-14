"""OMX 추론 worker 순수 로직 시험."""

import time

from cobot_manipulation.omx_infer_utils import (build_command, build_result, parse_request,
                                                run_inference, should_handle,
                                                slot_from_request, validate_command)
import pytest


REQUEST = {'request_id': 'r1', 'order_id': 'order1', 'robot_id': 'pinky1', 'stage': 'PICK',
           'target': 'omx1', 'action': 'pick', 'sku': 'shoe', 'quantity': 1, 'attempt': 0,
           'timeout_sec': 300.0, 'slot': 2}


def test_parse_request_requires_object():
    assert parse_request('{"a": 1}') == {'a': 1}
    with pytest.raises(ValueError):
        parse_request('[1, 2]')


def test_should_handle_only_own_arm_and_action():
    assert should_handle(REQUEST, 'omx1', {'pick'})
    assert not should_handle(dict(REQUEST, action='load'), 'omx1', {'pick'})
    assert not should_handle(dict(REQUEST, target='omx2'), 'omx1', {'pick'})
    assert not should_handle(dict(REQUEST, target='vision'), 'omx1', {'pick'})


@pytest.mark.parametrize('slot', [1, 2, 3, 4])
def test_slot_accepts_allowed(slot):
    assert slot_from_request(dict(REQUEST, slot=slot)) == slot


@pytest.mark.parametrize('value', [0, 5, True, '1', 1.0, None])
def test_slot_rejects_invalid(value):
    with pytest.raises(ValueError):
        slot_from_request(dict(REQUEST, slot=value))


def test_slot_missing():
    request = dict(REQUEST)
    del request['slot']
    with pytest.raises(ValueError, match='값 없음'):
        slot_from_request(request)


def test_validate_command():
    assert validate_command(['bash', '/x/infer.sh', '{slot}']) == ['bash', '/x/infer.sh', '{slot}']
    with pytest.raises(ValueError):
        validate_command(['bash', '', '{slot}'])
    with pytest.raises(ValueError):
        validate_command(['bash', '/x/infer.sh'])


def test_build_command_replaces_only_slot():
    assert build_command(['bash', '/x/infer.sh', '{slot}'], 3) == ['bash', '/x/infer.sh', '3']


def test_build_result_matches_fleet_contract():
    result = build_result(REQUEST, 'omx1', True, 'ok', {'slot': 2, 'retry_safe': False})
    assert result == {'request_id': 'r1', 'order_id': 'order1', 'robot_id': 'pinky1',
                      'stage': 'PICK', 'source': 'omx1', 'measured': True, 'finished': True,
                      'success': True, 'detail': 'ok', 'data': {'slot': 2, 'retry_safe': False}}


def test_run_inference_success_and_failure():
    assert run_inference(['sh', '-c', 'exit 0'], 5.0)[0] == 0
    returncode, detail = run_inference(['sh', '-c', 'exit 3'], 5.0)
    assert returncode == 3 and '3' in detail


def test_run_inference_timeout_kills_group():
    started = time.monotonic()
    # 자식 프로세스까지 남지 않아야 wait가 바로 끝난다.
    returncode, detail = run_inference(['sh', '-c', 'sleep 30 & wait'], 0.5)
    assert returncode is None and '시간 초과' in detail
    assert time.monotonic() - started < 10.0
