"""수동 확인 파라미터는 주문 ID에 묶이고 검증 성공 후에만 큐에 들어간다."""

import json
from types import SimpleNamespace

import pytest

from cobot_fleet_control.control_api import manual_load_request


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
