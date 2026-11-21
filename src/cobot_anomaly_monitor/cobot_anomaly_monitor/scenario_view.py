"""중앙 시나리오의 단계를 7단계 진행과 적재 상태로 바꾸는 순수 계산."""

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
    # 단계 번호는 앞으로만 간다(monitor_core._step 의 max). 그래서 ARRANGE(6) 뒤의
    # LEAVE_ARRANGE·MOVE_RESTOCK 은 표에 4로 적어도 실제 표시는 6에 머문다.
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


def is_customer_order(order, route):
    """
    고객 자리 주문인가. 관제와 같이 경로의 customer 칸으로 판단한다.

    감시 노드 경로 표에는 자리 경로(col1__P22 등)가 없어 route 가 빈 값일 수 있다.
    그때는 자리 주문에만 있는 단계를 지났는지로 판단한다. CUSTOMER 에 오려면 MOVE_CUSTOMER 를 지나야 한다.
    """
    if 'customer' in (route or {}):
        return True
    seen = set(order.get('completed', ())) | set(order.get('operator_completed', ()))
    return bool((seen | {order.get('stage')}) & CUSTOMER_ONLY_STAGES)


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


def cargo_of(order):
    """완료 단계로 적재 상태를 계산한다. 주문에는 적재 상태 값이 없다."""
    stage, completed = order['stage'], set(order.get('completed', ()))
    if 'VERIFY_UNLOAD' in completed:
        return 'EMPTY'
    # 고객 자리 주문(관제 sakim 1b0cb08)의 결제·회수 뒤에는 빈 트레이를 확인하는 실측 단계가 없다.
    # 결제(고객이 꺼냄)·RESTOCK 완료만으로 EMPTY 로 바꾸면 핑키 옆 걸침 감지가 꺼지므로 LOADED 로 남긴다.
    # 바꿀지는 사용자 결정(11-20). RESTOCK 동작 중에는 UNLOAD 와 같이 UNLOADING 이다.
    if stage in ('PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD', 'RESTOCK'):
        return 'UNLOADING'
    if 'VERIFY_LOAD' in completed:
        return 'LOADED'
    if stage in ('LOAD', 'VERIFY_LOAD'):
        return 'LOADING'
    return 'EMPTY'


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
