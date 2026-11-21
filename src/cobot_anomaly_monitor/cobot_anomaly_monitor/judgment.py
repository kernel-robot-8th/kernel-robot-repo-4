"""CCTV 이상 판정표 정본. ROS와 DB 없이 입력 dict만으로 판정한다."""

import json
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
# 결제·RESTOCK 뒤처럼 비었다고 보지만 빈 트레이를 확인한 센서가 없는 상태(11-21 사용자 결정 D2).
# 걸침·바닥 상자는 이 로봇을 지목하되 '잔류 의심'으로 적는다.
CARGO_UNVERIFIED = 'EMPTY_UNVERIFIED'
CARGO_LINKABLE = CARGO_ON_BOARD + (CARGO_UNVERIFIED,)

# 판정용 국면. 표시용 7단계(step_seq)는 앞으로만 가므로 판정은 이 값을 쓴다(scenario_view.phase_of).
# 로봇 dict에 phase 키가 없으면 옛 방식대로 step_seq로 고른다.
PHASE_PICK = 'PICK'            # 팔이 상자를 꺼내 핑키에 올리는 중(omx2 E 모델은 pick이 올리기까지 한다)
PHASE_LOADING = 'LOADING'      # LOAD·VERIFY_LOAD
PHASE_TRANSIT = 'TRANSIT'      # 화물을 싣고 작업장 사이를 가는 중(정차한 QR 포함)
PHASE_UNLOADING = 'UNLOADING'  # 하차 팔 작업·RESTOCK 선반 반환
PHASE_ARRANGE = 'ARRANGE'      # ZC 정리. 상자를 핑키 위에 다시 올린다. 하역이 아니다
PHASE_HANDOVER = 'HANDOVER'    # 자리 주문 CUSTOMER. 로봇은 서 있고 고객이 꺼낸다(D1)
PHASE_RESIDUAL = 'RESIDUAL'    # 작업·운송 국면 밖에서 화물이 실렸거나 비었는지 모르는 로봇

NONE, PAUSE, ESTOP = 'NONE', 'PAUSE', 'ESTOP'
# 정지 범위. ROBOT은 stop_targets의 로봇만, ALL은 로봇 지정 없는 전체 정지다.
# 관제는 전체 정지에서만 작업 명령 스위치(armed)를 끈다.
ROBOT, ALL = 'ROBOT', 'ALL'
ACTION_RANK = {NONE: 0, PAUSE: 1, ESTOP: 2}
SCOPE_RANK = {ROBOT: 0, ALL: 1}


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


def _phase(robot):
    """판정 국면. phase 키가 있으면 그 값(None 포함), 없으면 옛 step_seq 대응을 쓴다."""
    if 'phase' in robot:
        return robot['phase']
    step = robot.get('step_seq')
    if step == STEP_LOADING:
        return PHASE_LOADING
    if step == STEP_UNLOADING:
        return PHASE_UNLOADING
    return PHASE_TRANSIT if step in DRIVE_STEPS else None


def _residual_text(robot, robots, what):
    if robots[robot].get('cargo_state') == CARGO_UNVERIFIED:
        return f'[잔류 의심] {robot} 빈 트레이로 본 로봇{what}(남은 상자 또는 오검출).'
    return f'[잔류 화물] {robot} 실린 화물{what}.'


def _perched(xy, robots):
    hits = _near(robots, xy, NEAR_WORK_M, CARGO_LINKABLE)
    if len(hits) > 1:
        # 어느 로봇의 상자인지 모르므로 근처 로봇을 모두 세운다(로봇 지정). 11-20 전에는 조치가 없었다.
        # 화물로 잇는 로봇(PICK·잔류 화물·EMPTY_UNVERIFIED)이 늘어 한 대를 세우던 자리가
        # 보류로 바뀌면 범위가 좁아진다. 그래서 둘 이상이면 모두 세운다(D3).
        return _result('AMBIGUOUS', None, robots, PAUSE, hits,
                       '[판정 보류] 근처 로봇이 둘 이상입니다. 근처 로봇을 모두 세웁니다.')
    if not hits:
        return _result('IGNORED', None, robots)
    robot = hits[0]
    phase = _phase(robots[robot])
    if phase == PHASE_TRANSIT:
        return _result('TRANSIT_PERCHED', robot, robots, PAUSE, [robot],
                       f'[주행 위험] {robot} 이동 중 적재 상자가 테두리에 걸쳤습니다.')
    if phase == PHASE_UNLOADING:
        return _result('UNLOAD_FAIL', robot, robots, PAUSE, [robot],
                       f'[하역 불량] {robot} 하역 중 상자가 테두리에 걸쳤습니다.')
    if phase == PHASE_ARRANGE:
        return _result('ARRANGE_FAIL', robot, robots, PAUSE, [robot],
                       f'[정리 불량] {robot} 정리 중 상자가 테두리에 걸쳤습니다.')
    if phase == PHASE_HANDOVER:
        # 범위는 11-20 전과 같은 로봇 한 대다(그때는 UNLOAD_FAIL).
        return _result('CUSTOMER_HANDOVER_PERCHED', robot, robots, PAUSE, [robot],
                       f'[고객 인계] {robot} 고객 인계 중 상자가 테두리에 걸쳤습니다.')
    if phase == PHASE_RESIDUAL or robots[robot].get('cargo_state') == CARGO_UNVERIFIED:
        return _result('RESIDUAL_PERCHED', robot, robots, PAUSE, [robot],
                       _residual_text(robot, robots, ' 테두리에 상자가 걸쳐 있습니다'))
    return _result('LOAD_FAIL_PERCHED', robot, robots, PAUSE, [robot],
                   f'[상차 불량] {robot} 적재판 테두리에 상자가 걸쳐 있습니다.')


def _floor(xy, robots):
    hits = _near(robots, xy, NEAR_TRANSIT_M, CARGO_LINKABLE)
    if len(hits) > 1:
        # 로봇을 특정하지 못하므로 전체를 세운다. 대상 목록은 근처 적재 로봇의 기록용이다.
        return _result('AMBIGUOUS', None, robots, PAUSE, hits,
                       '[판정 보류] 바닥 상자 근처에 적재 로봇이 둘 이상입니다.', ALL)
    if hits:
        robot = hits[0]
        phase = _phase(robots[robot])
        close = math.dist(_pose(robots[robot]), xy) <= NEAR_WORK_M
        if phase == PHASE_PICK and close:
            # 11-20 전에는 PICK 을 빈 로봇으로 봐 진로 장애물(전체 정지)이었다. 범위는 좁히지 않는다(D3).
            return _result('LOAD_FAIL_DROP', robot, robots, PAUSE, [robot],
                           f'[상차 낙하] {robot} 상차 작업 중 상자가 바닥에 떨어졌습니다.', ALL)
        if phase == PHASE_LOADING and close:
            return _result('LOAD_FAIL_DROP', robot, robots, PAUSE, [robot],
                           f'[상차 낙하] {robot} 상차 작업 중 상자가 바닥에 떨어졌습니다.')
        if phase == PHASE_UNLOADING and close:
            return _result('UNLOAD_FAIL', robot, robots, PAUSE, [robot],
                           f'[하역 낙하] {robot} 하역 작업 중 상자가 바닥에 떨어졌습니다.')
        if phase == PHASE_ARRANGE and close:
            return _result('ARRANGE_FAIL', robot, robots, PAUSE, [robot],
                           f'[정리 낙하] {robot} 정리 작업 중 상자가 바닥에 떨어졌습니다.')
        if phase == PHASE_HANDOVER and close:
            return _result('CUSTOMER_HANDOVER_DROP', robot, robots, PAUSE, [robot],
                           f'[고객 인계 낙하] {robot} 고객 인계 중 상자가 바닥에 떨어졌습니다.')
        if phase == PHASE_TRANSIT:
            # 통로에 떨어진 상자는 다른 로봇의 진로도 막는다. 대상 목록은 지목 로봇 기록용이다.
            return _result('TRANSIT_DROP', robot, robots, PAUSE, [robot],
                           f'[주행 중 낙하] {robot} 이동 중 상자가 바닥에 떨어졌습니다.', ALL)
        if phase == PHASE_RESIDUAL or robots[robot].get('cargo_state') == CARGO_UNVERIFIED:
            # 로봇만 지목한다. 범위는 옛 진로 장애물과 같은 전체 정지다(D2).
            return _result('RESIDUAL_DROP', robot, robots, PAUSE, [robot],
                           _residual_text(robot, robots, ' 근처 바닥에 상자가 있습니다'), ALL)
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
    hits = _near(robots, xy, NEAR_WORK_M, CARGO_LINKABLE)
    if not hits:
        return _result('IGNORED', None, robots)
    if _phase(robots[hits[0]]) == PHASE_HANDOVER:
        # 고객이 받은 상자를 여는 것은 정상 행동이다. 이상으로 치지 않고 기록만 남긴다(D1).
        return _result('CUSTOMER_HANDOVER_LID', hits[0], robots,
                       text=f'[기록] {hits[0]} 고객 인계 중 상자 뚜껑이 열렸습니다(고객 개봉으로 봄).')
    return _result('LID_OPEN_ANOMALY', hits[0], robots,
                   text=f'[포장 이상] {hits[0]} 작업 구역에서 상자 뚜껑 분리가 감지됐습니다.')


RULES = {'box_perched_on_rim': _perched, 'box_on_floor': _floor,
         'box_run_over': _run_over, 'lid_detached': _lid}


def judge(event, robots):
    """
    이벤트 하나를 판정한다.

    :param event: event_id, camera_id, vision_class, confidence, detected_at, zone_id,
                  map_x, map_y, bbox
    :param robots: {robot_id: order_id, stage, step_seq, phase, cargo_state, zone, pose_x,
                    pose_y, speed_mps, driving, queue_wait, updated_at}
                   phase가 없으면 step_seq로 국면을 고른다(옛 입력과 같은 판정).
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
    """
    열린 이벤트와 같은 물체면 그 이벤트를 돌려준다.

    합친 재감지는 rejudge로만 다시 판정한다. 그냥 다시 판정하면 로봇이 떠난 뒤 낙하가 장애물로 바뀐다.
    """
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


def _wider(table, old, new):
    return old if table.get(old, -1) >= table.get(new, -1) else new


def rejudge(opened, fresh, phase, adopt=True):
    """
    합친 재감지의 새 판정과 열린 사건을 합친다. 바꿀 것이 없으면 None을 돌려준다.

    로봇이 정차한 채 단계만 바뀌면(PICK -> LOAD, ARRANGE -> LEAVE_ARRANGE 등) 처음 분류가 굳지 않게 한다.
    - 새 판정이 로봇을 지목하지 못하면(로봇이 떠난 뒤) 처음 판정을 둔다. 낙하가 장애물로 바뀌지 않는다.
    - 처음 판정이 다른 로봇을 지목했으면 그대로 둔다.
    - 처음 판정이 로봇을 지목하지 못했으면 adopt 가 참일 때만 새 로봇을 잇는다. 부르는 쪽이
      첫 감지 때부터 그 자리에 있던 로봇인지 본다(monitor_core._adoptable). 지나가던 로봇에 옛 사건을 붙이지 않는다.
    - 같은 로봇이면 그 로봇의 국면(단계·판정 국면·적재)이 바뀐 때만 다시 판정한다.
    - 조치와 정지 범위는 둘 중 넓은 쪽, 정지 대상은 합친다. 그래서 판정 이름은 새 판정을 따르지만
      범위는 그 이름의 본래 범위보다 넓을 수 있다(예: TRANSIT_DROP 뒤 UNLOAD_FAIL 이 ALL,
      PICK 의 LOAD_FAIL_DROP(ALL) 뒤 LOAD 의 LOAD_FAIL_DROP 도 ALL). 이미 건 정지를 좁히지 않기 위해서다.

    :param opened: 열린 사건 행(cctv_anomaly_events)
    :param fresh: judge() 결과
    :param phase: 새 판정 때 지목 로봇의 국면 문자열(robot_phase_at_event와 같은 형식)
    :param adopt: 지목 로봇이 없던 사건에 새 지목 로봇을 이어도 되는가
    """
    robot = fresh['linked_robot_id']
    before = opened.get('linked_robot_id')
    if robot is None or before not in (None, robot) or (before is None and not adopt):
        return None
    if before == robot and (opened.get('robot_phase_at_event') or '') == phase:
        return None
    targets = list(dict.fromkeys(json.loads(opened.get('stop_targets_json') or '[]')
                                 + list(fresh['stop_targets'])))
    merged = dict(fresh, stop_targets=targets,
                  recommended_action=_wider(ACTION_RANK, opened['recommended_action'],
                                            fresh['recommended_action']),
                  stop_scope=_wider(SCOPE_RANK, opened['stop_scope'], fresh['stop_scope']))
    if (merged['judgment'], merged['recommended_action'], merged['stop_scope'], targets,
            robot) == (opened['judgment'], opened['recommended_action'], opened['stop_scope'],
                       json.loads(opened.get('stop_targets_json') or '[]'), before):
        return None
    return merged


def escalated(opened, merged):
    """
    다시 판정한 결과가 조치나 범위를 넓혔는가(새로 정지를 요청해야 하는가).

    전체 정지의 대상 목록은 기록용이라 대상이 늘어도 새 요청이 아니다. 로봇 지정 정지만 대상을 본다.
    """
    old_targets = set(json.loads(opened.get('stop_targets_json') or '[]'))
    action = (ACTION_RANK.get(merged['recommended_action'], 0)
              > ACTION_RANK.get(opened['recommended_action'], 0))
    scope = SCOPE_RANK.get(merged['stop_scope'], 0) > SCOPE_RANK.get(opened['stop_scope'], 0)
    added = merged['stop_scope'] == ROBOT and set(merged['stop_targets']) - old_targets
    return bool(action or scope or added)
