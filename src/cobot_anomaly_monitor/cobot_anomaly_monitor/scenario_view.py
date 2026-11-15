"""중앙 시나리오의 단계를 7단계 진행과 적재 상태로 바꾸는 순수 계산."""

STEP_CODES = ('MOVE_TO_LOAD_WAIT', 'DOCK_LOAD_BAY', 'ARM_LOADING', 'TRANSIT_TO_STORE',
              'DOCK_UNLOAD_BAY', 'ARM_UNLOADING', 'RETURN_HOME')
STEP_CARGO_AFTER = ('EMPTY', 'EMPTY', 'LOADED', 'LOADED', 'LOADED', 'EMPTY', 'EMPTY')
STAGE_STEP = {
    'MOVE_PICKUP': 1, 'PICKUP_EXIT': 2, 'DOCK_PICKUP': 2, 'CORRECT_PICKUP': 2, 'MARKER': 2,
    'PICK': 3, 'LOAD': 3, 'VERIFY_LOAD': 3, 'LEAVE_PICKUP': 4, 'MOVE_DROPOFF': 4,
    'PATH_EXIT': 5, 'DOCK_DROPOFF': 5, 'CORRECT_DROPOFF': 5, 'QR': 5,
    'PICK_DROPOFF': 6, 'UNLOAD': 6, 'VERIFY_UNLOAD': 6, 'CUSTOMER': 6,
    'LEAVE_DROPOFF': 7, 'RETURN_HOME': 7, 'RETURN_EXIT': 7,
}
# 구역 진입 명령 하나가 두 단계에 걸친다. 목표 지점으로 이동을 시작하면 다음 단계로 본다.
ZONE_ENTRY_STAGES = {'MOVE_PICKUP': 'pickup', 'MOVE_DROPOFF': 'dropoff'}
RESUMABLE_STAGES = ('MOVE_PICKUP', 'MOVE_DROPOFF', 'RETURN_HOME', 'CUSTOMER')
DRIVING_STATES = ('MOVING', 'RETURNING', 'LEAVING_ZONE', 'RETREATING', 'QUEUEING')
QUEUE_WAIT_SPEED_MPS = 0.03


def step_of(order, status, route):
    """주문 단계와 로봇 상태로 7단계 번호를 계산한다."""
    stage = order['stage']
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
    if stage in ('PICK_DROPOFF', 'UNLOAD', 'VERIFY_UNLOAD'):
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
