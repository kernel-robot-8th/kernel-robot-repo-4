"""시나리오의 영속 상태와 외부 장치 작업 계약."""

import math
import re

TERMINAL = {'COMPLETED', 'FAILED'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
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


def finite(value):
    """누락된 센서 값과 불리언·NaN·무한대 값을 거절한다."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))
