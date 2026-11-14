"""OMX 추론 worker의 순수 로직. ROS 없이 단독 시험할 수 있게 분리한다."""

import json
import os
import signal
import subprocess

SLOT_PLACEHOLDER = '{slot}'
# fleet receive()가 결과를 요청과 대조할 때 쓰는 필드 (scenario_runtime.py receive 참고)
ECHO_FIELDS = ('request_id', 'order_id', 'robot_id', 'stage')


def parse_request(text):
    """작업 요청 JSON 문자열을 객체로 읽는다."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('작업 요청은 JSON 객체여야 합니다')
    return data


def should_handle(request, arm_id, actions):
    """이 팔이 맡은 동작만 처리한다. load 등 다른 판정은 별도 통신(YOLO)이 맡는다."""
    return request.get('target') == arm_id and request.get('action') in actions


def slot_from_request(request, key='slot', allowed=(1, 2, 3, 4)):
    """요청에 실린 위치 번호만 검증해 돌려준다. 값은 주문 DB 쪽에서 채운다."""
    if key not in request:
        raise ValueError(f'{key} 값 없음')
    value = request[key]
    # bool은 int의 하위 타입이라 True가 1로 통과하지 않게 먼저 막는다.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{key}는 정수여야 합니다: {value!r}')
    if value not in allowed:
        raise ValueError(f'{key} 범위 밖: {value} (허용 {list(allowed)})')
    return value


def validate_command(template):
    """실행 명령 설정을 시작 시점에 확인해 현장에서 경로 누락을 바로 알 수 있게 한다."""
    if not template or any(not isinstance(part, str) or not part for part in template):
        raise ValueError('command에 빈 항목이 있습니다: infer.sh 경로를 설정하세요')
    if not any(SLOT_PLACEHOLDER in part for part in template):
        raise ValueError(f'command에 {SLOT_PLACEHOLDER} 자리가 없습니다')
    return list(template)


def build_command(template, slot):
    """셸 문자열을 조합하지 않고 인자 목록의 {slot} 자리만 바꾼다."""
    return [part.replace(SLOT_PLACEHOLDER, str(slot)) for part in template]


def run_inference(command, timeout_sec, cwd=None):
    """추론 스크립트를 실행하고 (종료 코드, 설명)을 돌려준다. 시간 초과면 종료 코드는 None."""
    # 새 세션으로 띄워 시간 초과 시 bash 아래 lerobot 자식 프로세스까지 함께 종료한다.
    # 키보드 입력을 기다리는 스크립트가 멈추지 않도록 stdin은 닫아 둔다.
    process = subprocess.Popen(command, cwd=cwd or None, stdin=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        returncode = process.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        return None, f'추론 시간 초과 ({timeout_sec:.1f}s)'
    if returncode == 0:
        return 0, '추론 종료'
    return returncode, f'추론 실패 (종료 코드 {returncode})'


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def build_result(request, arm_id, success, detail, data=None):
    """fleet이 받아들이는 장치 최종 결과 형식으로 만든다."""
    result = {field: request.get(field) for field in ECHO_FIELDS}
    result.update(source=arm_id, measured=True, finished=True, success=bool(success),
                  detail=detail, data=dict(data or {}))
    return result
