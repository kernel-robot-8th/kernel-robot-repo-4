"""CCTV 이상 판정표 정본. ROS와 DB 없이 입력 dict만으로 판정한다."""

import math

NEAR_WORK_M = 0.45
NEAR_TRANSIT_M = 0.60
RUN_OVER_M = 0.20
# 감지기가 클래스별로 5초마다 다시 내므로 같은 물체는 한 사건으로 합친다.
DUPLICATE_M = 0.25
DUPLICATE_SEC = 30.0
# 닫힌 로봇 지정 사건의 범위를 같은 자리 재감지가 이어받는 시간.
INHERIT_SEC = 300.0

STEP_LOADING = 3
STEP_UNLOADING = 6
DRIVE_STEPS = (4, 5)
CARGO_ON_BOARD = ('LOADING', 'LOADED', 'UNLOADING')

NONE, PAUSE, ESTOP = 'NONE', 'PAUSE', 'ESTOP'
# 정지 범위. ROBOT은 stop_targets의 로봇만, ALL은 로봇 지정 없는 전체 정지다.
# 관제는 전체 정지에서만 작업 명령 스위치(armed)를 끈다.
ROBOT, ALL = 'ROBOT', 'ALL'


def _result(judgment, robot, robots, action=NONE, targets=(), text='', scope=ROBOT):
    order = robots[robot].get('order_id') if robot else None
    return {'judgment': judgment, 'linked_robot_id': robot, 'linked_order_id': order,
            'recommended_action': action, 'stop_scope': scope,
            'stop_targets': list(targets), 'alarm_text': text}


def _xy(item):
    x, y = item.get('map_x'), item.get('map_y')
    return None if x is None or y is None else (x, y)


def _pose(robot):
    x, y = robot.get('pose_x'), robot.get('pose_y')
    return None if x is None or y is None else (x, y)


def _near(robots, xy, radius, cargo=None):
    """반경 안 로봇을 가까운 순으로 돌려준다. cargo를 주면 그 상태인 로봇만 본다."""
    found = []
    for robot_id, robot in robots.items():
        pose = _pose(robot)
        if pose is None:
            continue
        distance = math.dist(pose, xy)
        if distance <= radius and (cargo is None or robot.get('cargo_state') in cargo):
            found.append((distance, robot_id))
    return [robot_id for _, robot_id in sorted(found)]


def _perched(xy, robots):
    hits = _near(robots, xy, NEAR_WORK_M, CARGO_ON_BOARD)
    if len(hits) > 1:
        return _result('AMBIGUOUS', None, robots, text='[판정 보류] 근처 로봇이 둘 이상입니다.')
    if not hits:
        return _result('IGNORED', None, robots)
    robot = hits[0]
    step = robots[robot].get('step_seq')
    if step in DRIVE_STEPS:
        return _result('TRANSIT_PERCHED', robot, robots, PAUSE, [robot],
                       f'[주행 위험] {robot} 이동 중 적재 상자가 테두리에 걸쳤습니다.')
    if step == STEP_UNLOADING:
        return _result('UNLOAD_FAIL', robot, robots, PAUSE, [robot],
                       f'[하역 불량] {robot} 하역 중 상자가 테두리에 걸쳤습니다.')
    return _result('LOAD_FAIL_PERCHED', robot, robots, PAUSE, [robot],
                   f'[상차 불량] {robot} 적재판 테두리에 상자가 걸쳐 있습니다.')


def _floor(xy, robots):
    hits = _near(robots, xy, NEAR_TRANSIT_M, CARGO_ON_BOARD)
    if len(hits) > 1:
        # 로봇을 특정하지 못하므로 전체를 세운다. 대상 목록은 근처 적재 로봇의 기록용이다.
        return _result('AMBIGUOUS', None, robots, PAUSE, hits,
                       '[판정 보류] 바닥 상자 근처에 적재 로봇이 둘 이상입니다.', ALL)
    if hits:
        robot = hits[0]
        step = robots[robot].get('step_seq')
        close = math.dist(_pose(robots[robot]), xy) <= NEAR_WORK_M
        if step == STEP_LOADING and close:
            return _result('LOAD_FAIL_DROP', robot, robots, PAUSE, [robot],
                           f'[상차 낙하] {robot} 상차 작업 중 상자가 바닥에 떨어졌습니다.')
        if step == STEP_UNLOADING and close:
            return _result('UNLOAD_FAIL', robot, robots, PAUSE, [robot],
                           f'[하역 낙하] {robot} 하역 작업 중 상자가 바닥에 떨어졌습니다.')
        if step in DRIVE_STEPS:
            # 통로에 떨어진 상자는 다른 로봇의 진로도 막는다. 대상 목록은 지목 로봇 기록용이다.
            return _result('TRANSIT_DROP', robot, robots, PAUSE, [robot],
                           f'[주행 중 낙하] {robot} 이동 중 상자가 바닥에 떨어졌습니다.', ALL)
    # 지목할 로봇이 없어도 전체 정지를 올린다(주문·로봇이 하나도 없어도 나오는 판정).
    return _result('LANE_OBSTACLE', None, robots, PAUSE,
                   text='[진로 장애물] 주행 구간 바닥에 상자가 놓여 있습니다.', scope=ALL)


def _run_over(xy, robots):
    # 대기 슬롯에 서 있는 로봇을 밟은 로봇으로 지목하지 않는다.
    hits = [robot for robot in _near(robots, xy, RUN_OVER_M)
            if robots[robot].get('driving') and not robots[robot].get('queue_wait')]
    if not hits:
        return _result('IGNORED', None, robots)
    robot = hits[0]
    return _result('RUN_OVER_COLLISION', robot, robots, ESTOP, [robot],
                   f'[충돌 사고] {robot}가 바닥 상자와 충돌했습니다. 즉시 정지합니다.', ALL)


def _lid(xy, robots):
    hits = _near(robots, xy, NEAR_WORK_M, CARGO_ON_BOARD)
    if not hits:
        return _result('IGNORED', None, robots)
    return _result('LID_OPEN_ANOMALY', hits[0], robots,
                   text=f'[포장 이상] {hits[0]} 작업 구역에서 상자 뚜껑 분리가 감지됐습니다.')


RULES = {'box_perched_on_rim': _perched, 'box_on_floor': _floor,
         'box_run_over': _run_over, 'lid_detached': _lid}


def judge(event, robots):
    """
    이벤트 하나를 판정한다.

    :param event: event_id, camera_id, vision_class, confidence, detected_at, zone_id,
                  map_x, map_y, bbox
    :param robots: {robot_id: order_id, stage, step_seq, cargo_state, zone, pose_x, pose_y,
                    speed_mps, driving, queue_wait, updated_at}
    :return: judgment, linked_robot_id, linked_order_id, recommended_action, stop_scope,
             stop_targets, alarm_text
    """
    xy = _xy(event)
    if xy is None:
        return _result('NO_POSITION', None, robots,
                       text='[위치 불명] 위치 없는 이상 감지입니다. 로봇을 지목하지 않습니다.')
    rule = RULES.get(event.get('vision_class'))
    return rule(xy, robots) if rule else _result('IGNORED', None, robots)


def _same_spot(event, other):
    """같은 클래스가 DUPLICATE_M 안에서 감지됐는가."""
    xy, there = _xy(event), _xy(other)
    return (xy is not None and there is not None
            and other['vision_class'] == event.get('vision_class')
            and math.dist(there, xy) <= DUPLICATE_M)


def is_duplicate(event, open_events, now):
    """열린 이벤트와 같은 물체면 그 이벤트를 돌려준다. 다시 판정하면 낙하가 장애물로 바뀐다."""
    for opened in open_events:
        # 전체 정지가 걸린 채 열린 사건은 감지가 끊겼다 와도 묶는다. 복구 도중의 재감지가
        # 전체 정지를 한 번 더 부르지 않게 한다.
        stopping = (opened.get('stop_scope') == ALL
                    and str(opened.get('control_action')).endswith(('_SENT', '_ACCEPTED')))
        if _same_spot(event, opened) and (
                stopping or now - opened['last_seen'] <= DUPLICATE_SEC):
            return opened
    return None


def closed_before(event, closed_events, now):
    """
    방금 닫힌 로봇 지정 정지 사건과 같은 물체면 그 사건을 돌려준다.

    주문이 fail로 끝나면 근처에 적재 로봇이 없어 같은 상자가 LANE_OBSTACLE(전체 정지)로
    다시 판정된다. 닫힌 사건의 범위를 이어받게 해 로봇 한 대의 사고가 전체 정지로 번지지 않게 한다.
    """
    for closed in closed_events:
        if (_same_spot(event, closed) and closed.get('stop_scope') == ROBOT
                and closed.get('recommended_action') != NONE
                and now - (closed.get('resolved_at') or 0.0) <= INHERIT_SEC):
            return closed
    return None
