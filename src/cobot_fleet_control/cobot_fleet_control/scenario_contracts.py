"""시나리오의 영속 상태와 외부 장치 작업 계약."""

import math
import re

TERMINAL = {'COMPLETED', 'FAILED'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
# 멈춘 주문을 '이어서 가기'로 되살릴 수 있는 이동·수령 단계. 팔 작업 단계는 다시 하지 않는다.
# 관제 화면(cobot_control_center fleet_api_utils.ORDER_RESUME_STAGES)에 같은 값을 복사해 둔다.
RESUME_STAGES = {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER'}
NAVIGATION = {'MOVE_PICKUP': 'zone', 'LEAVE_PICKUP': 'leave',
              'MOVE_DROPOFF': 'zone', 'LEAVE_DROPOFF': 'leave', 'RETURN_HOME': 'home'}
WORK = {
    'PICKUP_EXIT': ('vision', 'path_exit'),
    'DOCK_PICKUP': ('vision', 'dock_check'),
    'CORRECT_PICKUP': ('navigation', 'dock_correct'),
    'MARKER': ('vision', 'marker'), 'PICK': ('pickup_arm', 'pick'),
    'LOAD': ('pickup_arm', 'load'), 'VERIFY_LOAD': ('vision', 'verify_load'),
    'PATH_EXIT': ('vision', 'path_exit'),
    'DOCK_DROPOFF': ('vision', 'dock_check'),
    'CORRECT_DROPOFF': ('navigation', 'dock_correct'),
    'QR': ('vision', 'qr'), 'PICK_DROPOFF': ('dropoff_arm', 'pick'),
    'UNLOAD': ('dropoff_arm', 'unload'),
    'VERIFY_UNLOAD': ('vision', 'verify_unload'),
    'RETURN_EXIT': ('vision', 'path_exit'),
}


def identifier(value, name):
    """영속 저장 키나 장치 대상으로 사용하기 전에 식별자 형식과 길이를 제한한다."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError(f'{name}: 영문·숫자·밑줄·하이픈 1~80자')
    return value


# 화면 확인 창 한 번으로 보내는 운영자 조치(해제·복구)의 기록 기본값 (2026-11-09).
DEFAULT_OPERATOR = 'control-center'


def operator_or_default(value):
    """운영자는 선택. 없으면 기본값, 주면 식별자 형식을 검사한다."""
    return identifier(value or DEFAULT_OPERATOR, 'operator')


def optional_text(value, name, default):
    """메모 같은 선택 글. 없거나 비면 기본 문구, 문자열이 아니면 거절한다."""
    if value is not None and not isinstance(value, str):
        raise ValueError(f'{name}는 문자열')
    return (value or '').strip() or default


def finite(value):
    """누락된 센서 값과 불리언·NaN·무한대 값을 거절한다."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))
