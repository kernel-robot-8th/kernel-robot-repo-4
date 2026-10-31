"""런타임 코드에 작업 스레드·대기 루프·중첩 spin이 다시 생기지 않게 검사한다."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('name', [
    'pinky_patrol_node.py', 'patrol_controller.py', 'async_navigation.py',
])
def test_no_worker_or_blocking_wait(name):
    """단일 executor에서 콜백을 막는 API를 사용하지 않는다."""
    source = Path(__file__).resolve().parents[1] / 'cobot_pinky_patrol' / name
    tree = ast.parse(source.read_text())
    forbidden = {'sleep', 'wait_for_service', 'wait_for_server', 'spin_once',
                 'spin_until_future_complete', 'Thread', 'join', 'waitUntilNav2Active'}
    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (node.func.attr == 'join' and isinstance(node.func.value, ast.Constant)
                    and isinstance(node.func.value.value, str)):
                continue  # 문자열 결합은 스레드 join과 구분한다.
            assert node.func.attr not in forbidden
