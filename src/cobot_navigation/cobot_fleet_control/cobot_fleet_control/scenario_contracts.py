"""시나리오의 영속 상태와 외부 장치 작업 계약."""

import math
import re
import unicodedata

TERMINAL = {'COMPLETED', 'FAILED'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL'}
# 멈춘 주문을 '이어서 가기'로 되살릴 수 있는 이동·수령 단계. 팔 작업 단계는 다시 하지 않는다.
# 관제 화면(cobot_control_center fleet_api_utils.ORDER_RESUME_STAGES)에 같은 값을 복사해 둔다.
RESUME_STAGES = {'MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER',
                 'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'MOVE_RESTOCK'}
NAVIGATION = {'MOVE_PICKUP': 'zone', 'LEAVE_PICKUP': 'leave',
              'MOVE_DROPOFF': 'zone', 'LEAVE_DROPOFF': 'leave', 'RETURN_HOME': 'home',
              # 고객 자리 주문: 자리는 구역이 아닌 일반 지점이라 goto. 회수는 ZC 정리 → ZA 선반 반환.
              'MOVE_CUSTOMER': 'goto',
              'MOVE_ARRANGE': 'zone', 'LEAVE_ARRANGE': 'leave',
              'MOVE_RESTOCK': 'zone', 'LEAVE_RESTOCK': 'leave'}
# 이동 단계가 가는 지점 = 경로(route)의 이 칸. 고객 자리 경로의 dropoff 는 회수 정리 구역(ZC)이다.
MOVE_POINT = {'MOVE_PICKUP': 'pickup', 'MOVE_DROPOFF': 'dropoff', 'MOVE_CUSTOMER': 'customer',
              'MOVE_ARRANGE': 'dropoff', 'MOVE_RESTOCK': 'restock'}
# 구역을 나가는 단계가 반납하는 작업장 쪽 (경로 칸 이름)
LEAVE_SIDE = {'LEAVE_PICKUP': 'pickup', 'LEAVE_DROPOFF': 'dropoff',
              'LEAVE_ARRANGE': 'dropoff', 'LEAVE_RESTOCK': 'restock'}
# 정지·해제 때 hold/release_hold 를 보낼 경로의 팔 칸
ROUTE_ARMS = ('pickup_arm', 'dropoff_arm', 'restock_arm')
WORK = {
    'ARRANGE': ('dropoff_arm', 'arrange_shoe'),
    'RESTOCK': ('restock_arm', 'warehouse_store'),
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
# 팔이 움직이는 단계. 멈추면 운영자가 현장을 보고 '다시'(팔 퇴피·물건 제자리 확인) 를 고를 수 있다.
# 관제 화면(cobot_control_center fleet_api_utils.ORDER_ARM_RETRY_STAGES)에 같은 값을 복사해 둔다.
ARM_STAGES = frozenset(stage for stage, (actor, _) in WORK.items() if actor.endswith('_arm'))
# 다시 할 때 시작 단계. 싣기·내리기 실패는 물건을 처음 자리에 돌려놓고 집기부터 다시 한다.
RETRY_FROM = {'LOAD': 'PICK', 'UNLOAD': 'PICK_DROPOFF'}
# '사람이 처리함'(사람이 대신 놓음) 뒤 이어 갈 단계. 상차(PICK·LOAD)는 수동 상차 확인을 쓴다.
# 관제 화면(fleet_api_utils.ORDER_HAND_DONE_STAGES)에 같은 키를 복사해 둔다.
HAND_DONE = {'PICK_DROPOFF': 'VERIFY_UNLOAD', 'UNLOAD': 'VERIFY_UNLOAD',
             'ARRANGE': 'LEAVE_ARRANGE', 'RESTOCK': 'LEAVE_RESTOCK'}
# 단계 순서. 순서는 복구 체크포인트(resume_stage) 이전 단계를 건너뛰는 데도 쓴다.
# PICKUP_STAGES: 상차 구역 안 단계. 수동 상차 확인이 이 단계들을 사람 완료로 적는다.
PICKUP_STAGES = ('PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD')
_TO_PICKUP = ('MOVE_PICKUP',) + PICKUP_STAGES + ('LEAVE_PICKUP',)
_RETURN_HOME = ('RETURN_HOME', 'RETURN_EXIT')
# 팔이 상품에 손대기 전 단계. 여기서 직원이 취소하면 상품이 선반에 있으므로 홈으로 가고 재고를 돌려준다.
BEFORE_PICK_STAGES = frozenset(
    ('MOVE_PICKUP',) + PICKUP_STAGES[:PICKUP_STAGES.index('PICK') + 1] + ('CORRECT_PICKUP',))
# 직원 취소를 받는 단계. 그 뒤는 이미 반납·복귀 중이다.
CANCEL_STAGES = frozenset(_TO_PICKUP + ('CORRECT_PICKUP', 'MOVE_CUSTOMER', 'CUSTOMER'))
# 하차 구역 주문: 하차 팔이 내려놓는 기존 방식.
STAGES = _TO_PICKUP + (
    'MOVE_DROPOFF', 'PATH_EXIT', 'DOCK_DROPOFF', 'QR', 'PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD',
    'CUSTOMER', 'LEAVE_DROPOFF') + _RETURN_HOME
# 고객 자리(지점) 주문: ZB 상차 → 고객 자리 → 결제면 복귀, 회수면 ZC 정리 → ZA 선반 반환 → 복귀.
_CUSTOMER_RETURN = ('MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE',
                    'MOVE_RESTOCK', 'RESTOCK', 'LEAVE_RESTOCK')
CUSTOMER_STAGES = _TO_PICKUP + ('MOVE_CUSTOMER', 'CUSTOMER') + _CUSTOMER_RETURN + _RETURN_HOME
CUSTOMER_RETURN_STAGES = frozenset(_CUSTOMER_RETURN)
LABELS = {
    'MOVE_PICKUP': '상차 작업장 이동', 'PICKUP_EXIT': '상차 진입 후미 이탈 확인',
    'DOCK_PICKUP': '상차 정차 실측', 'CORRECT_PICKUP': '상차 정밀 위치 보정',
    'MARKER': '상차 마커·상품 확인', 'PICK': '상차 상품 피킹', 'LOAD': '로봇에 상차',
    'VERIFY_LOAD': '적재·로봇팔 퇴피 확인', 'LEAVE_PICKUP': '상차 구역 이탈',
    'MOVE_DROPOFF': '하차 작업장 이동', 'PATH_EXIT': '하차 진입 후미 이탈 확인',
    'DOCK_DROPOFF': '하차 정차 실측', 'CORRECT_DROPOFF': '하차 정밀 위치 보정',
    'QR': '하차 QR·상품 확인', 'PICK_DROPOFF': '하차 상품 피킹', 'UNLOAD': '목적지에 하차',
    'VERIFY_UNLOAD': '배치·빈 적재함·로봇팔 퇴피 확인', 'LEAVE_DROPOFF': '하차 구역 이탈',
    'RETURN_HOME': 'HOME 복귀', 'RETURN_EXIT': '복귀 후미 이탈 확인',
    'MOVE_CUSTOMER': '고객 자리 이동', 'MOVE_ARRANGE': '회수 정리 구역 이동',
    'ARRANGE': '회수 신발 정리', 'LEAVE_ARRANGE': '회수 정리 구역 이탈',
    'MOVE_RESTOCK': '선반 반환 구역 이동', 'RESTOCK': '신발 선반 반환',
    'LEAVE_RESTOCK': '선반 반환 구역 이탈',
}


def is_customer_route(route):
    """고객이 핑키에서 직접 꺼내는 지점 자리 경로인가."""
    return 'customer' in route


def order_stages(route):
    """경로 종류에 맞는 단계 순서."""
    return CUSTOMER_STAGES if is_customer_route(route) else STAGES


def identifier(value, name):
    """영속 저장 키나 장치 대상으로 사용하기 전에 식별자 형식과 길이를 제한한다."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError(f'{name}: 영문·숫자·밑줄·하이픈 1~80자')
    return value


# 화면 확인 창 한 번으로 보내는 운영자 조치(해제·복구)의 기록 기본값 (2026-11-09).
DEFAULT_OPERATOR = 'control-center'


OPERATOR_MAX = 40  # 화면 입력칸 최대 길이와 같게 둔다


def operator_name(value):
    """처리한 사람 이름. 키가 아니라 감사 기록용 글이므로 한글·공백을 받되 안 보이는 문자는 막는다."""
    if not isinstance(value, str):
        raise ValueError('operator: 이름은 문자열')
    # NFC: 같은 한글 이름이 입력 장치에 따라 다른 글자열로 기록되지 않게 한다.
    name = unicodedata.normalize('NFC', value.strip())
    if not 1 <= len(name) <= OPERATOR_MAX:
        raise ValueError(f'operator: 이름 1~{OPERATOR_MAX}자')
    if any(unicodedata.category(c)[0] == 'C' or unicodedata.category(c) in ('Zl', 'Zp')
           for c in name):
        raise ValueError('operator: 이름에 줄바꿈·제어 문자를 쓸 수 없음')
    return name


def operator_or_default(value):
    """운영자는 선택. 없거나 비면 기본값, 주면 이름 형식을 검사한다."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_OPERATOR
    return operator_name(value)


def optional_text(value, name, default):
    """메모 같은 선택 글. 없거나 비면 기본 문구, 문자열이 아니면 거절한다."""
    if value is not None and not isinstance(value, str):
        raise ValueError(f'{name}는 문자열')
    return (value or '').strip() or default


def finite(value):
    """누락된 센서 값과 불리언·NaN·무한대 값을 거절한다."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))
