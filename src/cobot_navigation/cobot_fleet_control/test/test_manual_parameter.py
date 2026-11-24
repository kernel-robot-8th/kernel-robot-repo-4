"""수동 확인 파라미터는 주문 ID에 묶이고 검증 성공 후에만 큐에 들어간다."""

import json
from types import SimpleNamespace
import unicodedata

import pytest

from cobot_fleet_control.control_api import manual_load_request
from cobot_fleet_control.scenario_contracts import operator_name, operator_or_default


def payload():
    """실제 현장 확인을 명시한 파라미터 입력 예시."""
    return {'order_id': 'order1', 'operator': 'operator1', 'note': '현장 확인',
            'evidence': {'sku': 'SHOE42', 'load_present': True,
                         'arm_safe': True, 'pickup_path_clear': True}}


def test_parameter_is_scoped_to_order_and_does_not_generate_sensor_result():
    """새 주문 생성이나 measured 센서 결과 없이 수동 확인 요청만 만든다."""
    request = manual_load_request(json.dumps(payload()))
    assert request['type'] == 'confirm_loaded' and request['order_id'] == 'order1'
    assert request['request_id'].startswith('loaded-')
    assert 'measured' not in request
    assert manual_load_request('') is None


def test_parameter_accepts_korean_operator_but_not_korean_order_id():
    """사람 이름만 한글을 받고 주문 ID 는 식별자 규칙을 지킨다."""
    request = manual_load_request(json.dumps({**payload(), 'operator': ' 김지혜 '}))
    assert request['operator'] == '김지혜'
    for changes in ({'order_id': '주문1'}, {'operator': ''}, {'operator': None}):
        with pytest.raises(ValueError):
            manual_load_request(json.dumps({**payload(), **changes}))


def test_operator_name_is_trimmed_and_normalized():
    """이름은 공백을 떼고 NFC 로 맞추며 40자까지 받는다."""
    assert operator_name(' kim jihye ') == 'kim jihye'
    assert operator_name(unicodedata.normalize('NFD', '김지혜')) == '김지혜'
    assert operator_name('가' * 40) == '가' * 40
    assert operator_or_default(None) == operator_or_default('  ') == 'control-center'
    assert operator_or_default('김지혜') == '김지혜'


@pytest.mark.parametrize('value', [
    '', '  ', '가' * 41, 'a\nb', 'a\x00b', 'a\u200bb', 'a\u202eb', 'a\u2028b', 'a\ud800b',
    None, 3, True, ['김지혜']])
def test_operator_name_rejects_unsafe_values(value):
    """안 보이는 문자와 글자가 아닌 값은 기록에 남기지 않는다."""
    with pytest.raises(ValueError):
        operator_name(value)


@pytest.mark.parametrize('value', ['{}', 'null', '[]', 'true', 'x', 'x' * 8193])
def test_invalid_parameter_is_rejected(value):
    """잘못된 입력을 실제 주문 처리 전에 거절한다."""
    with pytest.raises(ValueError):
        manual_load_request(value)


def test_validation_has_no_side_effect_and_only_committed_parameter_is_queued():
    """ROS 검증 콜백은 주문을 실행하지 않고 post-set 콜백만 큐에 전달한다."""
    pytest.importorskip('rclpy')
    from cobot_fleet_control.fleet_control_node import FleetControlNode

    node = SimpleNamespace(manual_load_inbox=[])
    parameter = SimpleNamespace(name='manual_load_confirmation', value=json.dumps(payload()))
    assert FleetControlNode._validate_manual_load(node, [parameter]).successful
    assert node.manual_load_inbox == []
    FleetControlNode._queue_manual_load(node, [parameter])
    assert node.manual_load_inbox[0]['order_id'] == 'order1'
    parameter.value = '{}'
    assert not FleetControlNode._validate_manual_load(node, [parameter]).successful
    assert len(node.manual_load_inbox) == 1
