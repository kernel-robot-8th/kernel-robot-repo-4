"""중앙 시나리오의 단계를 7단계 진행과 적재 상태로 바꾸는 순수 계산."""

from .judgment import (
    CARGO_UNVERIFIED, PHASE_ARRANGE, PHASE_HANDOVER, PHASE_LOADING, PHASE_PICK, PHASE_RESIDUAL,
    PHASE_TRANSIT, PHASE_UNLOADING)

STEP_CODES = ('MOVE_TO_LOAD_WAIT', 'DOCK_LOAD_BAY', 'ARM_LOADING', 'TRANSIT_TO_STORE',
              'DOCK_UNLOAD_BAY', 'ARM_UNLOADING', 'RETURN_HOME')
STEP_CARGO_AFTER = ('EMPTY', 'EMPTY', 'LOADED', 'LOADED', 'LOADED', 'EMPTY', 'EMPTY')
# CUSTOMER 는 주문 종류마다 자리가 다르다. step_of 가 주문을 보고 고른다.
# - 고객 자리 주문: P22 같은 일반 지점에서 고객이 핑키에서 직접 꺼내고 결제한다. 팔도, 하차 정차 실측도 없다.
#   그래서 ARM_UNLOADING(6)이나 DOCK_UNLOAD_BAY(5)가 아니라 운송 단계(4, TRANSIT_TO_STORE)에 둔다.
#   배송은 고객이 받을 때 끝나므로 가장 가까운 단계로 본다. 판정(judgment.DRIVE_STEPS)은 4와 5를
#   같게 다루므로 5를 골라도 사고 분류는 같다. 4로 두면 회수 갈래 MOVE_ARRANGE 가 4에서 시작해
#   구역 진입 때 5가 된다.
# - 경로 주문: 하차 팔이 내려놓은 뒤라 하역 단계(6)다. 옛 값 그대로다.
# STAGE_STEP 에는 자리 값을 적는다. monitor_core._advance 가 건너뛴 단계의 성공 여부를 이 표로 보므로,
# 6으로 적으면 결제한 자리 주문(4 → 7)의 ARM_UNLOADING 을 SUCCEEDED 로 잘못 남긴다.
CUSTOMER_SEAT_STEP = 4
CUSTOMER_ROUTE_STEP = 6
STAGE_STEP = {
    'MOVE_PICKUP': 1, 'PICKUP_EXIT': 2, 'DOCK_PICKUP': 2, 'CORRECT_PICKUP': 2, 'MARKER': 2,
    'PICK': 3, 'LOAD': 3, 'VERIFY_LOAD': 3, 'LEAVE_PICKUP': 4, 'MOVE_DROPOFF': 4,
    'PATH_EXIT': 5, 'DOCK_DROPOFF': 5, 'CORRECT_DROPOFF': 5, 'QR': 5,
    'PICK_DROPOFF': 6, 'UNLOAD': 6, 'VERIFY_UNLOAD': 6, 'CUSTOMER': CUSTOMER_SEAT_STEP,
    'LEAVE_DROPOFF': 7, 'RETURN_HOME': 7, 'RETURN_EXIT': 7,
    # 고객 자리 주문 단계(관제 origin/sakim 1b0cb08 scenario_tree.CUSTOMER_STAGES).
    # 주행은 운송(4), 구역 진입은 ZONE_ENTRY_STAGES 로 5, 팔 작업은 하역 쪽(6)으로 둔다.
    # 이탈은 다음에 갈 곳을 따른다: 정리 구역 이탈은 반환 구역으로 가는 운송(4),
    # 반환 구역 이탈은 LEAVE_DROPOFF 처럼 복귀(7).
    # 표시용 단계 번호는 앞으로만 간다(monitor_core._step 의 max). 그래서 ARRANGE(6) 뒤의
    # LEAVE_ARRANGE·MOVE_RESTOCK 은 표에 4로 적어도 실제 표시는 6에 머문다.
    # 사고 판정은 이 max 를 쓰지 않는다. phase_of 가 지금 단계와 적재로 국면을 다시 계산한다.
    'MOVE_CUSTOMER': 4, 'MOVE_ARRANGE': 4, 'ARRANGE': 6, 'LEAVE_ARRANGE': 4,
    'MOVE_RESTOCK': 4, 'RESTOCK': 6, 'LEAVE_RESTOCK': 7,
}
CUSTOMER_ONLY_STAGES = frozenset(('MOVE_CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE',
                                  'MOVE_RESTOCK', 'RESTOCK', 'LEAVE_RESTOCK'))
# 구역 진입 명령 하나가 두 단계에 걸친다. 목표 지점으로 이동을 시작하면 다음 단계로 본다.
# 값은 경로 칸 이름이다. 관제 scenario_contracts.MOVE_POINT 와 같다(MOVE_ARRANGE 는 dropoff = 정리 구역).
# MOVE_CUSTOMER 는 구역이 아닌 일반 지점(goto)이라 대기 슬롯이 없어 넣지 않는다.
ZONE_ENTRY_STAGES = {'MOVE_PICKUP': 'pickup', 'MOVE_DROPOFF': 'dropoff',
                     'MOVE_ARRANGE': 'dropoff', 'MOVE_RESTOCK': 'restock'}
# 관제 scenario_contracts.RESUME_STAGES 와 같은 값(관제 화면 ORDER_RESUME_STAGES 도 같다).
RESUMABLE_STAGES = ('MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER',
                    'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'MOVE_RESTOCK')
DRIVING_STATES = ('MOVING', 'RETURNING', 'LEAVING_ZONE', 'RETREATING', 'QUEUEING')
QUEUE_WAIT_SPEED_MPS = 0.03
LOADING_STAGES = ('PICK', 'LOAD', 'VERIFY_LOAD')
# RESTOCK(omx1 warehouse_store)은 핑키 위 상자를 선반에 내려놓는 하역이다. ARRANGE 는 다시 올리는 정리라 뺀다.
UNLOADING_STAGES = ('PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD', 'RESTOCK')
TRANSIT_STEPS = (4, 5)
# 주행 명령 단계(관제 scenario_contracts.NAVIGATION 과 같다). 정지 요청으로 잠깐 서도 국면은 그대로 둔다.
NAVIGATION_STAGES = frozenset(('MOVE_PICKUP', 'LEAVE_PICKUP', 'MOVE_DROPOFF', 'LEAVE_DROPOFF',
                               'RETURN_HOME', 'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'LEAVE_ARRANGE',
                               'MOVE_RESTOCK', 'LEAVE_RESTOCK'))
# 관제 stale_sec 와 같다. 순찰 상태는 0.5초마다 오므로 이보다 오래되면 통신이 끊긴 것으로 본다.
STATUS_STALE_SEC = 3.0
# 관제 보류 사유 -> 로봇 동작 상태. 모르는 사유는 옛 표시처럼 PAUSED 로 둔다.
# STOP 은 로봇 지정 없는 전체 stop 의 보류다. 주문이 있으면 관제가 ESTOP 상태로 끊는다(control_api._stop).
HOLD_OP_STATE = {'ESTOP': 'ESTOP', 'STOP': 'ESTOP', 'PAUSE': 'PAUSED', 'PAUSED': 'PAUSED',
                 'MANUAL': 'MANUAL', 'UNKNOWN': 'UNKNOWN', 'LINK_LOST': 'LINK_LOST',
                 'DISPATCH_FAILED': 'DISPATCH_FAILED', 'RESET_PENDING': 'RESET_PENDING',
                 'RESET_UNCONFIRMED': 'RESET_UNCONFIRMED'}
# 자리 주문 고객 응답(관제 customer_received·customer_declined·customer_timed_out) -> 기록 값.
SEAT_OUTCOMES = (('customer_received', 'PAID'), ('customer_declined', 'DECLINED'),
                 ('customer_timed_out', 'TIMEOUT'))


def is_customer_order(order, route):
    """
    고객 자리 주문인가. 관제와 같이 경로의 customer 칸으로 판단한다.

    감시 노드는 관제처럼 자리 경로(col1__P22 등)를 만든다(monitor_node.layout_routes). 그래도 설정에 자리
    설정이 없거나 옛 기록을 다시 볼 때는 route 가 빈 값일 수 있다. 그때는 자리 주문에만 있는 단계를
    지났는지로 판단한다. CUSTOMER 에 오려면 MOVE_CUSTOMER 를 지나야 한다.
    """
    if 'customer' in (route or {}):
        return True
    stage = order.get('stage')
    seen = done_stages(order) | ({stage} if isinstance(stage, str) else set())
    return bool(seen & CUSTOMER_ONLY_STAGES)


def step_of(order, status, route):
    """주문 단계와 로봇 상태로 7단계 번호를 계산한다."""
    stage = order['stage']
    if stage == 'CUSTOMER':
        return CUSTOMER_SEAT_STEP if is_customer_order(order, route) else CUSTOMER_ROUTE_STEP
    step = STAGE_STEP.get(stage, 0)
    side = ZONE_ENTRY_STAGES.get(stage)
    if side and route and (status or {}).get('detail') == route.get(side):
        return step + 1
    return step


def done_stages(order):
    """
    관제가 끝낸 단계. 운영자 수동 상차 확인(confirm_loaded)은 operator_completed 에만 넣는다.

    목록이 null 이거나 목록이 아니면 빈 것으로 본다(스냅샷 콜백에서 예외를 내지 않게).
    """
    done = set()
    for key in ('completed', 'operator_completed'):
        value = order.get(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            done.update(item for item in value if isinstance(item, str))
    return done


def cargo_of(order):
    """
    완료 단계로 적재 상태를 계산한다. 주문에는 적재 상태 값이 없다.

    - PICK 도 상차 중이다. 현장 omx2 E 모델은 pick 이 상자를 꺼내 핑키에 올리기까지 한다.
    - 운영자 수동 상차 확인(operator_completed 의 VERIFY_LOAD)과 재기동 복원(manual_load_pending)은 실린 것이다.
    - 고객 자리 주문의 결제(customer_received)·RESTOCK 완료 뒤에는 빈 트레이를 확인하는 센서 단계가 없다.
      비었다고 단정하지 않고 EMPTY_UNVERIFIED 로 둔다(11-21 사용자 결정 D2).
    - 시간 초과(customer_timed_out)는 신발을 실은 채 복귀하므로 LOADED 그대로다.
    """
    stage, done = order['stage'], done_stages(order)
    if 'VERIFY_UNLOAD' in done:
        return 'EMPTY'
    if stage in UNLOADING_STAGES:
        return 'UNLOADING'
    if order.get('customer_received') or 'RESTOCK' in done:
        return CARGO_UNVERIFIED
    if ('VERIFY_LOAD' in done or order.get('manual_load_pending')
            or order.get('operator_load_confirmation')):
        return 'LOADED'
    if stage in LOADING_STAGES:
        return 'LOADING'
    return 'EMPTY'


def phase_of(order, status, route, cargo, driving, residual=False):
    """
    사고 판정용 국면(judgment.PHASE_*). 표시용 단계와 달리 앞으로만 가지 않는다.

    :param order: 진행 중 주문 또는 None(주문 없는 로봇)
    :param cargo: 로봇의 적재 상태(잔류 화물을 반영한 값)
    :param driving: 로봇이 주행 중인가(마지막 순찰 상태 기준. 통신이 끊겨도 그대로 둔다)
    :param residual: 주문 자체로는 빈 로봇이 잔류 화물 때문에만 LOADED 인가
    """
    step, stage = 0, None
    if order:
        stage = order['stage']
        if stage == 'PICK':
            return PHASE_PICK
        if stage in LOADING_STAGES:
            return PHASE_LOADING
        if stage in UNLOADING_STAGES:
            return PHASE_UNLOADING
        if stage == 'ARRANGE':
            return PHASE_ARRANGE
        if stage == 'CUSTOMER':
            # 경로 주문 CUSTOMER 는 하차 팔이 내려놓은 뒤라 옛 값(하역 단계 6)을 그대로 쓴다.
            # 단 주문으로는 빈 로봇이 잔류 화물 때문에만 LOADED 면 잔류 국면으로 본다. 하역으로 보면
            # 바닥 낙하가 로봇 단독 정지(UNLOAD_FAIL)가 되어 11-20 전(LANE_OBSTACLE, 전체)보다 좁아진다.
            if is_customer_order(order, route):
                return PHASE_HANDOVER
            return PHASE_RESIDUAL if residual else PHASE_UNLOADING
        step = step_of(order, status, route)
    # 화물을 싣고 움직이거나 주행·운송·복귀 단계에 있으면 운송이다. 회수 갈래(LEAVE_ARRANGE·MOVE_RESTOCK)와
    # 시간 초과 복귀(RETURN_HOME, 7), 잔류 화물을 실은 채 받은 다음 주문의 MOVE_PICKUP 이 여기에 든다.
    if cargo == 'LOADED' and (driving or stage in NAVIGATION_STAGES
                              or step in TRANSIT_STEPS + (7,)):
        return PHASE_TRANSIT
    if step in TRANSIT_STEPS:
        return PHASE_TRANSIT
    if cargo in ('LOADED', CARGO_UNVERIFIED):
        return PHASE_RESIDUAL
    return None


def outcome_of(order, route):
    """고객 응답 결과. 자리 주문은 PAID·DECLINED·TIMEOUT, 경로 주문 수령은 RECEIVED 로 적는다."""
    for flag, outcome in SEAT_OUTCOMES:
        if order.get(flag):
            if outcome == 'PAID' and not is_customer_order(order, route):
                return 'RECEIVED'
            return outcome
    return ''


def leaves_residual(order, route):
    """신발을 실은 채 끝나는 자리 주문(결제·회수 무응답 시간 초과)인가."""
    return bool(order.get('customer_timed_out')) and is_customer_order(order, route)


def driving_of(status):
    """정지 대상 판단용. 대기 슬롯의 로봇도 armed와 무관하게 움직일 수 있어 포함한다."""
    return (status or {}).get('state') in DRIVING_STATES


def queue_wait_of(status, speed_mps):
    """순찰 노드는 슬롯 도착을 따로 알리지 않으므로 속도로 구분한다."""
    return ((status or {}).get('state') == 'QUEUEING'
            and speed_mps is not None and speed_mps <= QUEUE_WAIT_SPEED_MPS)


def zone_of(status, active):
    """구역 토큰이 있으면 그 구역, 주문이 없으면 홈, 그 외는 통로로 본다."""
    held = (status or {}).get('held_zone')
    if held:
        return 'ZONE_' + str(held)
    return 'LANE' if active or driving_of(status) else 'HOME'


def op_state_of(status, active):
    """순찰 상태를 관제 표시용 동작 상태로 줄인다."""
    status = status or {}
    state = status.get('state')
    if status.get('central_latched') is True:
        return 'HOLD_ANOMALY'
    if state == 'QUEUEING':
        return 'WAITING_QUEUE'
    if driving_of(status):
        return 'MOVING'
    if not status:
        return 'OFFLINE'
    return 'WAIT_ARM' if active and status.get('held_zone') else 'IDLE'


def hold_op_state(reason):
    """관제 보류 사유나 주문 중단 상태를 동작 상태로 바꾼다. 문자열이 아니면 옛 표시처럼 PAUSED."""
    return HOLD_OP_STATE.get(reason, 'PAUSED') if isinstance(reason, str) else 'PAUSED'
