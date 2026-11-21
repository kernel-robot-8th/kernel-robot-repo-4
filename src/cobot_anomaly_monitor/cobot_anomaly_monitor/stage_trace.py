"""주문별로 실제 관측한 요청·작업 결과와 관제 스냅샷을 연결한다."""

import json
import math

from .scenario_view import SEAT_OUTCOMES

# 단계 순서는 관제 기준(origin/sakim 1b0cb08, 11-19) cobot_fleet_control scenario_tree 의
# STAGES(경로 주문)·CUSTOMER_STAGES(고객 자리 주문)와 같다. 감시 패키지는 팀 패키지를 import 하지 않는다.
# test_stage_trace 가 cobot_fleet_control 을 import 할 수 있을 때 두 표를 대조한다.
STAGES = (
    'MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD',
    'LEAVE_PICKUP', 'MOVE_DROPOFF', 'PATH_EXIT', 'DOCK_DROPOFF', 'QR', 'PICK_DROPOFF',
    'UNLOAD', 'VERIFY_UNLOAD', 'CUSTOMER', 'LEAVE_DROPOFF', 'RETURN_HOME', 'RETURN_EXIT',
)
# 고객 자리 주문: ZB 상차 → 고객 자리(P22) → 결제·시간 초과면 복귀, 회수면 ZC 정리 → ZA 선반 반환 → 복귀.
# 자리에는 팔이 없다. 하차 쪽 단계(MOVE_DROPOFF~VERIFY_UNLOAD, LEAVE_DROPOFF)가 없다.
CUSTOMER_STAGES = (
    'MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD', 'VERIFY_LOAD',
    'LEAVE_PICKUP', 'MOVE_CUSTOMER', 'CUSTOMER',
    'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE', 'MOVE_RESTOCK', 'RESTOCK', 'LEAVE_RESTOCK',
    'RETURN_HOME', 'RETURN_EXIT',
)
# 회수(declined) 갈래. 결제·시간 초과면 관제가 이 단계를 건너뛰고 바로 RETURN_HOME 으로 간다.
CUSTOMER_RETURN_STAGES = CUSTOMER_STAGES[CUSTOMER_STAGES.index('MOVE_ARRANGE'):
                                         CUSTOMER_STAGES.index('RETURN_HOME')]
# 자리 주문에만 있는 단계. 하나라도 관측되면 경로 설정이 없어도 자리 주문으로 본다.
CUSTOMER_ONLY_STAGES = frozenset(CUSTOMER_STAGES) - frozenset(STAGES)
# 경로의 팔 칸. 관제 scenario_contracts.ROUTE_ARMS 와 같다.
ROUTE_ARMS = ('pickup_arm', 'dropoff_arm', 'restock_arm')

# 단계 -> (대상, 작업, 이름). 대상이 팔 칸 이름(ROUTE_ARMS)이면 그 주문 경로의 팔 이름으로 바꾼다.
# 경로에 그 칸이 없으면 관제와 같이 칸 이름을 그대로 둔다(관제 scenario_runtime route.get(actor, actor)).
# 주행 단계의 작업은 관제 scenario_contracts.NAVIGATION 의 명령 종류(zone·leave·goto·home)다.
STAGE_INFO = {
    'MOVE_PICKUP': ('pinky', 'zone', '상차지로 이동'),
    'PICKUP_EXIT': ('vision', 'path_exit', '상차 통로 확인'),
    'DOCK_PICKUP': ('vision', 'dock_check', '상차 접안 확인'),
    'MARKER': ('vision', 'marker', '상차 마커 확인'),
    'PICK': ('pickup_arm', 'pick', '피킹'),
    'LOAD': ('pickup_arm', 'load', '상차'),
    'VERIFY_LOAD': ('vision', 'verify_load', '적재 검증'),
    'LEAVE_PICKUP': ('pinky', 'leave', '상차지 출발'),
    'MOVE_DROPOFF': ('pinky', 'zone', '하차지로 이동'),
    'PATH_EXIT': ('vision', 'path_exit', '하차 통로 확인'),
    'DOCK_DROPOFF': ('vision', 'dock_check', '하차 접안 확인'),
    'QR': ('vision', 'qr', 'QR 확인'),
    'PICK_DROPOFF': ('dropoff_arm', 'pick', '하차 피킹'),
    'UNLOAD': ('dropoff_arm', 'unload', '하차 안착'),
    'VERIFY_UNLOAD': ('vision', 'verify_unload', '하차 검증'),
    'CUSTOMER': ('operator', 'received', '고객 수령'),
    'LEAVE_DROPOFF': ('pinky', 'leave', '하차지 출발'),
    'RETURN_HOME': ('pinky', 'home', '홈으로 복귀'),
    'RETURN_EXIT': ('vision', 'path_exit', '복귀 통로 확인 / 종결'),
    # 고객 자리 주문 단계. 이름은 관제 scenario_tree.LABELS 와 같다.
    'MOVE_CUSTOMER': ('pinky', 'goto', '고객 자리 이동'),
    'MOVE_ARRANGE': ('pinky', 'zone', '회수 정리 구역 이동'),
    'ARRANGE': ('dropoff_arm', 'arrange_shoe', '회수 신발 정리'),
    'LEAVE_ARRANGE': ('pinky', 'leave', '회수 정리 구역 이탈'),
    'MOVE_RESTOCK': ('pinky', 'zone', '선반 반환 구역 이동'),
    'RESTOCK': ('restock_arm', 'warehouse_store', '신발 선반 반환'),
    'LEAVE_RESTOCK': ('pinky', 'leave', '선반 반환 구역 이탈'),
}
# 자리 주문의 CUSTOMER 는 고객이 핑키에서 직접 꺼내고 결제(received)하거나 회수(declined)를 누른다.
CUSTOMER_SEAT_NAME = '고객 결제·회수 대기'
# 조건부 하위 단계(정차 공차를 벗어났을 때만 생긴다). 관제 WORK 의 CORRECT_* 와 같다.
CORRECTION = ('navigation', 'dock_correct', '접안 보정')


def _specs(stages, names=None):
    """단계 순서대로 번호를 붙인다. 번호는 관제 단계 순서의 위치다."""
    names = names or {}
    return [{'stage': stage, 'target': STAGE_INFO[stage][0], 'action': STAGE_INFO[stage][1],
             'name': f'{number} {names.get(stage, STAGE_INFO[stage][2])}'}
            for number, stage in enumerate(stages, 1)]


STAGE_SPECS = _specs(STAGES)
CUSTOMER_STAGE_SPECS = _specs(CUSTOMER_STAGES, {'CUSTOMER': CUSTOMER_SEAT_NAME})

# 관제 scenario_contracts.NAVIGATION 의 단계와 같다.
NAVIGATION = {'MOVE_PICKUP', 'LEAVE_PICKUP', 'MOVE_DROPOFF', 'LEAVE_DROPOFF', 'RETURN_HOME',
              'MOVE_CUSTOMER', 'MOVE_ARRANGE', 'LEAVE_ARRANGE', 'MOVE_RESTOCK', 'LEAVE_RESTOCK'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL', 'FAILED'}
# 피킹 전 정차 실패(order.failure) 뒤 관제가 도는 안전 복귀 단계(관제 scenario_tree safe_return).
SAFE_RETURN = ('RETURN_HOME', 'RETURN_EXIT')
# 관제 SAFETY 요청(팔 hold·release_hold). 단계 행이 아니라 주문 메모로만 보인다.
SAFETY_STAGE = 'SAFETY'
# 관제가 복구할 때 경로 팔에 release_hold 를 보내는 결정(관제 scenario_safety recover).
RELEASE_DECISIONS = ('resume', 'fail')


def _sent_route(route, items):
    """
    관제가 작업 요청에 실어 보낸 경로(dict)를 먼저 쓴다.

    감시 노드 경로 표는 scenario_config 사본이다(자리 경로 col*__P22 도 관제처럼 펼친다).
    사본이 낡았거나 옛 기록이라 경로를 모를 때도 관제가 보낸 값을 따른다.
    요청을 아직 못 봤으면 넘겨받은 경로를 쓴다.
    """
    for item in items:
        sent = item.get('route')
        if isinstance(sent, dict) and sent and all(isinstance(v, str) for v in sent.values()):
            return dict(sent)
    return dict(route or {})


def _is_customer_order(route, seen):
    """관제와 같이 경로에 customer 칸이 있으면 자리 주문이다. 자리 단계가 관측돼도 자리 주문이다."""
    return 'customer' in route or bool(seen & CUSTOMER_ONLY_STAGES)


def _return_branch_listed(order, seen):
    """회수 갈래 행을 보일지 정한다. 결제·시간 초과·안전 복귀로 건너뛴 갈래는 대기 행으로 남기지 않는다."""
    if seen & set(CUSTOMER_RETURN_STAGES) or order.get('customer_declined'):
        return True
    if (order.get('customer_received') or order.get('customer_timed_out')
            or order.get('failure')):
        return False
    return order.get('state') not in ('COMPLETED', 'FAILED')


def _outcome(order, customer):
    """고객 응답 결과. 감시 기록(scenario_view.outcome_of)과 같은 값이다."""
    for flag, outcome in SEAT_OUTCOMES:
        if order.get(flag):
            return 'RECEIVED' if outcome == 'PAID' and not customer else outcome
    return ''


def _not_reached(order, stage):
    """
    도달하지 않은 행을 '건너뜀'으로 볼 이유. 없으면 None(아직 올 수 있는 대기 행).

    피킹 전 정차 실패(failure)면 관제는 안전 복귀 두 단계만 돈다. 실패 종결·UNKNOWN 보류면 더 진행하지 않는다.
    """
    failure, state = order.get('failure'), order.get('state')
    if failure and stage not in SAFE_RETURN:
        return f'건너뜀 · 피킹 전 실패({failure}) 뒤 안전 복귀'
    if state == 'FAILED':
        return '진행 안 함 · 주문 실패 종결'
    if state == 'UNKNOWN':
        return '진행 안 함 · 주문 보류(UNKNOWN), 운영자 복구 대기'
    return None


def _at(item):
    return item.get('created_at') or item.get('first_seen')


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _tolerance(dock_tolerance):
    """scenario_config 의 dock_xy_m·dock_yaw_deg. 둘 다 숫자일 때만 비교한다."""
    tol = dock_tolerance or {}
    xy, yaw = tol.get('dock_xy_m'), tol.get('dock_yaw_deg')
    return (xy, yaw) if _finite(xy) and _finite(yaw) else None


def _dock_evidence(stage, entries, idx, grouped, order, last):
    """
    정차 시도 뒤 관제가 보정을 요청했는지, 보정 예산을 다 써서 끝났는지 본다.

    보정 요청은 이 시도와 다음 정차 시도 사이에 관측한 CORRECT_* 요청이다(관제가 공차 초과로 판단한 증거).
    """
    at = _at(entries[idx - 1]) if entries else None
    following = _at(entries[idx]) if idx < len(entries) else None
    corrected = False
    if at is not None:
        for record in grouped.get(stage.replace('DOCK_', 'CORRECT_'), {}).values():
            time = _at(record)
            if time is not None and time > at and (following is None or time < following):
                corrected = True
    # 예산 소진: 상차 쪽은 failure 를 남기고 안전 복귀, 하차 쪽은 그 자리에서 보류한다(관제 retry).
    if stage == 'DOCK_PICKUP':
        reason = order.get('failure') or ''
    elif (order.get('stage') in (stage, stage.replace('DOCK_', 'CORRECT_'))
            and order.get('state') in BLOCKED):
        reason = order.get('detail') or ''
    else:
        reason = ''
    exhausted = bool(entries) and last and not corrected and '공차 초과' in str(reason)
    return {'corrected': corrected, 'exhausted': exhausted}


def build_stage_trace(order, work_history, tasks=None, live_work=None,
                      attempts=(), route=None, unmatched=(), terminal=None,
                      dock_tolerance=None):
    """
    요약 완료 표시와 특정 시도에 대한 수신·수용 증거를 따로 계산한다.

    dock_tolerance 는 감시 scenario_config 의 {'dock_xy_m', 'dock_yaw_deg'} 다. 주면 정차 행 실측을 공차와 비교한다.
    """
    if not order:
        return []
    # completed·operator_completed 가 null 이거나 목록이 아니면 빈 목록으로 본다.
    order = dict(order, **{key: [x for x in order[key] if isinstance(x, str)]
                           if isinstance(order.get(key), (list, tuple)) else []
                           for key in ('completed', 'operator_completed')})
    task_map = tasks if isinstance(tasks, dict) else {t['task_id']: t for t in tasks or []}
    items = [item for item in [*attempts, *work_history, *(live_work or [])]
             if item.get('order_id') == order['order_id'] and item.get('request_id')
             and item.get('stage') != SAFETY_STAGE]
    route = _sent_route(route, items)
    tolerance = _tolerance(dock_tolerance)
    grouped = {}
    for item in items:
        bucket = grouped.setdefault(item['stage'], {})
        bucket.setdefault(item['request_id'], {}).update(item)
    current = order.get('stage')
    current_id = order.get('request_id') or order.get('command_id')
    if current and current_id:
        grouped.setdefault(current, {}).setdefault(current_id, {'request_id': current_id})
    seen = (set(grouped) | set(order.get('completed', []))
            | set(order.get('operator_completed', [])) | {current}) - {None}
    customer = _is_customer_order(route, seen)
    base = STAGE_SPECS
    if customer:
        # 자리 주문에는 하차 쪽 8단계가 없다. 결제·시간 초과면 회수 갈래도 건너뛴다.
        listed = _return_branch_listed(order, seen)
        base = [spec for spec in CUSTOMER_STAGE_SPECS
                if listed or spec['stage'] not in CUSTOMER_RETURN_STAGES]
    specs = []
    for spec in base:
        specs.append(spec)
        if spec['stage'] in ('DOCK_PICKUP', 'DOCK_DROPOFF'):
            code = spec['stage'].replace('DOCK_', 'CORRECT_')
            if code in grouped or code == current or code in order.get('completed', []):
                number = spec['name'].split()[0]
                specs.append({'stage': code, 'name': f'{number}a {CORRECTION[2]}',
                              'target': CORRECTION[0], 'action': CORRECTION[1]})
    entered = set(grouped) | set(order.get('completed', []))
    if current and order.get('state') != 'WAITING':
        entered.add(current)
    reached = entered | set(order.get('operator_completed', []))
    arms = {route[key] for key in ROUTE_ARMS if route.get(key)}
    rows = []
    base_names = [spec['stage'] for spec in base]
    # 회수 주문(kind return)은 관제가 CUSTOMER 를 건너뛴다. 다음 단계 계산에서도 뺀다.
    flow = [name for name in base_names
            if not (order.get('kind') == 'return' and name == 'CUSTOMER')]
    for spec in specs:
        stage = spec['stage']
        entries = sorted(grouped.get(stage, {}).values(), key=lambda e: (
            e.get('created_at') or e.get('first_seen') or float('inf'), e.get('attempt') or 0))
        if stage.startswith('CORRECT_'):
            successors = [stage.replace('CORRECT_', 'DOCK_')]
        else:
            names = flow if stage in flow else base_names
            successors = names[names.index(stage) + 1:][:1]
            if stage.startswith('DOCK_'):
                successors.append(stage.replace('DOCK_', 'CORRECT_'))
        for idx, item in enumerate(entries or [{}], 1):
            last = idx >= len(entries)
            at = item.get('created_at') or item.get('first_seen')
            following = False
            for successor in successors:
                if successor not in entered:
                    continue
                records = grouped.get(successor, {}).values()
                if records and at is not None:
                    following |= any((r.get('created_at') or r.get('first_seen') or 0) > at
                                     for r in records)
                elif (last and not stage.startswith('CORRECT_')
                      and not successor.startswith('CORRECT_')):
                    following = True
            dock = None
            if stage.startswith('DOCK_'):
                dock = dict(_dock_evidence(stage, entries, idx, grouped, order, last),
                            tolerance=tolerance)
            row = _attempt(order, spec, item, task_map, idx, last, following, route, customer,
                           dock)
            if not entries and stage not in reached and row['status'] == 'WAITING':
                reason = _not_reached(order, stage)
                if reason:
                    row['status'], row['evidence_summary'] = 'SKIPPED', reason
            if order.get('failure') and stage in SAFE_RETURN:
                row['evidence_summary'] += f" · 안전 복귀: {order['failure']}"
                row['evidence_detail'] = dict(row['evidence_detail'] or {},
                                              safe_return=order['failure'])
            if stage.startswith('CORRECT_') and at is not None:
                measurements = grouped.get(successors[0], {}).values()
                times = [(r.get('created_at') or r.get('first_seen'), r['request_id'])
                         for r in measurements]
                earlier = sorted(t for t in times if t[0] is not None and t[0] < at)
                later = sorted(t for t in times if t[0] is not None and t[0] > at)
                detail = row['evidence_detail'] or {}
                detail.update(previous_measurement=earlier[-1][1] if earlier else None,
                              next_measurement=later[0][1] if later else None)
                row['evidence_detail'] = detail
            if (current == stage and current_id == item.get('request_id') and current_id
                    and not item.get('result') and not item.get('wire_results')):
                foreign = [e['payload']['request_id'] for e in unmatched
                           if e['payload'].get('stage') == stage
                           and e['payload'].get('robot_id') == order.get('robot_id')
                           and e['payload'].get('source') == row['target']
                           and e['payload'].get('request_id') != current_id
                           and at is not None and e['at'] >= at]
                if foreign:
                    row['evidence_summary'] += ' · 다른 요청 ID의 응답 관측'
                    row['evidence_detail'] = dict(row['evidence_detail'] or {},
                                                  other_result_ids=sorted(set(foreign)))
                elif row['target'] in arms:
                    row['evidence_summary'] += ' · 결과 미관측'
            if stage == 'RETURN_EXIT' and last and order.get('state') in ('COMPLETED', 'FAILED'):
                observed = terminal and terminal['job_state'] == order['state']
                detail = dict(row['evidence_detail'] or {}, order_state=order['state'],
                              terminal_resources=terminal if observed else None)
                row['evidence_detail'] = detail
                msg = ('예약 상태 미관측' if not observed else
                       '남은 예약 ' + ', '.join(terminal['resources']) if terminal['resources']
                       else '종결 시 남은 예약 없음')
                row['evidence_summary'] += ' · ' + msg
            rows.append(row)
    return rows


def order_notes(order, work_history, attempts=(), live_work=None, control_events=()):
    """
    단계 행에 넣지 않는 주문 메모. 지금은 관제 SAFETY 요청(팔 hold·release_hold)만 모은다.

    관제는 주문을 멈출 때 경로 팔에 hold(order_id 있음)를 보내고, 운영자 복구(resume·fail) 때
    release_hold(order_id 빈 값)를 보낸다. release_hold 는 주문 기록에 남지 않으므로
    같은 주문의 운영자 복구 기록(control_events 의 recovery)으로 해제 요청을 알아본다.
    """
    if not order:
        return {'safety': None}
    oid = order['order_id']
    requests = {}
    for item in [*attempts, *work_history, *(live_work or [])]:
        if (item.get('stage') == SAFETY_STAGE and item.get('order_id') == oid
                and item.get('request_id')):
            requests.setdefault(item['request_id'], {}).update(item)
    calls = sorted(({'request_id': rid, 'action': r.get('action'), 'target': r.get('target'),
                     'robot_id': r.get('robot_id'),
                     'at': r.get('wire_observed_at') or r.get('created_at') or r.get('issued_at')}
                    for rid, r in requests.items()),
                   key=lambda c: (c['at'] if _finite(c['at']) else float('inf'), c['request_id']))
    holds = [c for c in calls if c['action'] == 'hold']
    releases = [c for c in calls if c['action'] == 'release_hold']
    recoveries = sorted(
        ({'decision': (e.get('payload') or {}).get('decision'),
          'operator': (e.get('payload') or {}).get('operator'), 'at': e.get('at')}
         for e in control_events or ()
         if e.get('type') == 'recovery' and e.get('order_id') == oid),
        key=lambda r: r['at'] if _finite(r['at']) else float('inf'))
    if not holds and not releases:
        return {'safety': None}
    targets = sorted({c['target'] for c in holds if c['target']})
    text = f'SAFETY hold {len(holds)}건' + (' (' + ', '.join(targets) + ')' if targets else '')
    asked = [r for r in recoveries if r['decision'] in RELEASE_DECISIONS]
    if releases:
        text += f' · release_hold {len(releases)}건 관측'
    elif asked:
        text += f" · 운영자 복구({asked[-1]['decision']})로 경로 팔 해제 요청됨"
    else:
        text += ' · 해제 요청 미관측'
    return {'safety': {'holds': holds, 'releases': releases, 'recoveries': recoveries,
                       'text': text,
                       'release_note': 'release_hold 는 order_id 가 비어 주문 기록에 남지 않음'}}


def _number_text(value, digits):
    return f'{value:.{digits}f}' if _finite(value) else '미확인'


def _dock_text(data, dock):
    """
    정차 실측 문구와 공차 비교. 관제 MeasureDock·DockTolerance 와 같이 |xy|·|yaw| 를 공차와 비교한다.

    공차 사본이 없으면 관제 행동(보정 요청·보정 예산 소진)으로만 공차 초과를 적는다.
    """
    xy, yaw = data.get('xy_m'), data.get('yaw_deg')
    text = f' · 실측 {_number_text(xy, 3)} m / {_number_text(yaw, 1)}°'
    extra = {'correction_requested': dock['corrected']}
    tolerance, within = dock.get('tolerance'), None
    if tolerance and _finite(xy) and _finite(yaw):
        within = abs(xy) <= tolerance[0] and abs(yaw) <= tolerance[1]
        extra.update(dock_tolerance={'xy_m': tolerance[0], 'yaw_deg': tolerance[1]},
                     within_tolerance=within)
    if within is True:
        text += ' · 공차 이내'
        if dock['corrected']:
            text += ' · 관제는 보정 요청(감시 공차 사본과 다름)'
    elif within is False or dock['corrected'] or dock['exhausted']:
        text += ' · 공차 초과 → 보정' + (' 예산 소진' if dock['exhausted'] else '')
        if within is None:
            text += ' (관제 보정 요청 기준)' if dock['corrected'] else ' (관제 실패 사유 기준)'
    return text, extra


def _attempt(order, spec, item, tasks, idx, last, following, route, customer=False, dock=None):
    stage = spec['stage']
    rid = item.get('request_id')
    nav = stage in NAVIGATION
    current = stage == order.get('stage') and last
    complete = stage in order.get('completed', []) and last
    manual = stage in order.get('operator_completed', []) and last
    observed = item.get('wire_results', [])
    matches = [entry['payload'] for entry in observed if (
        all(entry['payload'].get(k) == item.get(k)
            for k in ('order_id', 'stage', 'robot_id', 'request_id'))
        and entry['payload'].get('source') == item.get('target')
        and entry['payload'].get('measured') is True and entry['payload'].get('finished') is True
        and isinstance(entry['payload'].get('success'), bool)
        and isinstance(entry['payload'].get('data', {}), dict))]
    result = item.get('result') or (matches[0] if len(matches) == 1 else {})
    data = result.get('data') or {}
    detail = dict(item.get('pending_data') or data)
    if result:
        detail.update(note=result.get('detail'), success=result.get('success'),
                      source=result.get('source'), finished=result.get('finished'),
                      measured=result.get('measured'))
    cp = {'requested': bool(rid), 'received': 'UNCONFIRMED', 'result': 'NONE',
          'accepted': 'WAITING', 'next_stage': False}
    state = 'WAITING'
    msg = '이전 단계 완료 대기'
    target = spec['target']
    if nav:
        target = order.get('robot_id') or '미배정'
    elif target in ROUTE_ARMS:
        # 관측한 요청이 없을 때의 대체값. 경로 칸이 없으면 칸 이름을 그대로 보인다.
        target = route.get(target) or target
    target = item.get('target') or target
    action = spec['action']
    if order.get('kind') == 'return' and stage == 'UNLOAD':
        action = 'warehouse_store'  # 관제 scenario_runtime: 회수 주문의 UNLOAD 는 창고 보관
    action = item.get('action') or action
    if rid:
        state, msg = 'RUNNING', '요청 관측 · 대상 수신 미확인'
    if item.get('state') == 'PENDING':
        msg = '어댑터 접수 · 대상 동작 미확인'
    if item.get('load_join') and not result:
        count = item.get('evidence_count', 0)
        arm = '팔 퇴피 확인됨' if item.get('arm_checked') else '팔 퇴피 대기'
        msg = (f'적재 표본 {max(0, 3 - count)}개 대기 ({count}/3) · {arm}' if count < 3
               else f'적재 표본 3/3 · {arm}')
        if item.get('wait_reason'):
            msg += ' · ' + item['wait_reason']
    if item.get('created_at') is not None:
        detail['request_observed_at'] = item['created_at']
    if item.get('updated_at') is not None:
        detail['adapter_updated_at'] = item['updated_at']
    if result:
        cp['result'] = ('JOINED' if data.get('decision') == 'camera_and_operator' else
                        'MANUAL' if data.get('manual') else
                        'MEASURED' if result.get('measured') is True else 'NONE')
        cp['accepted'] = 'UNCONFIRMED'
        msg = '결과 기록 · 관제 수용 미확인'
        if item.get('state') == 'PUBLISH_UNCONFIRMED':
            msg = '결과 저장 · 발행 미확인'
        if data.get('decision'):
            msg += ' · ' + str(data['decision'])
    if observed:
        detail['observed_results'] = observed
        if len(matches) != 1:
            msg = '응답 관측 · 요청과 불일치 또는 복수 결과'
            cp['accepted'] = 'UNCONFIRMED'
        elif not data.get('manual') and data.get('decision') != 'camera_and_operator':
            cp['received'] = 'CONFIRMED'
    failed = result.get('success') is False
    if (dock and dock['corrected'] and result and not failed
            and not (observed and len(matches) != 1)):
        # 관제가 이 실측을 받고 보정(CORRECT_*)을 요청했다. 수용한 것이다.
        cp['accepted'] = 'ACCEPTED'
        msg = '결과 기록 · 관제 수용(보정 요청 관측)'
        if data.get('decision'):
            msg += ' · ' + str(data['decision'])
    if current and order.get('state') == 'RUNNING' and not rid:
        state, msg = 'RUNNING', '단계 진입 · 요청 생성 미확인'
    if manual or complete:
        state = 'COMPLETED'
        cp['accepted'] = 'ACCEPTED'
        msg = '관제 단계 완료'
        if manual:
            cp['result'] = 'MANUAL'
            msg = '운영자 완료 기록'
        if data.get('decision'):
            msg += ' · ' + str(data['decision'])
        # completed는 단계 단위다. 실패·미발행 시도에 관제 수용을 귀속시키지 않는다.
        if (item.get('state') in ('REJECTED', 'PUBLISH_UNCONFIRMED')
                or result.get('success') is False or (observed and len(matches) != 1)):
            cp['accepted'], state, msg = 'UNCONFIRMED', 'RUNNING', '단계 완료 · 이 시도의 수용 미확인'
        else:
            cp['next_stage'] = bool(following)
    if manual and order.get('operator_load_confirmation'):
        detail['operator_load_confirmation'] = order['operator_load_confirmation']
    if manual and rid and not result:
        cp['accepted'], cp['next_stage'] = 'UNCONFIRMED', False
        msg = '운영자 단계 확인 · 이 요청의 장치 결과 수용 미확인'
    if failed:
        # 장치 실패 응답. 관제는 retry_safe 가 true 면 같은 단계를 다시 요청하고, 아니면 보류한다.
        retry = data.get('retry_safe')
        state, cp['next_stage'] = 'FAILED', False
        msg = (f"실패 응답: {result.get('detail') or '사유 없음'} "
               f"(retry_safe={json.dumps(retry) if isinstance(retry, bool) else '없음'})")
        if manual or complete:
            msg += ' · 단계 완료는 다른 시도·운영자 기록'
    if stage == 'CUSTOMER':
        # 관제 CustomerReceipt: 결제(received)·회수(declined)·시간 초과 중 하나로 끝난다.
        if order.get('customer_timed_out'):
            msg = '결제·회수 무응답 · 신발 실은 채 복귀' if customer else '수령 무응답 · 복귀'
            cp['result'] = 'TIMEOUT'
        elif order.get('customer_received'):
            msg = '고객 결제 입력 확인' if customer else '고객 수령 입력 확인'
            cp['result'] = 'MANUAL'
        elif order.get('customer_declined'):
            msg = '고객 회수 입력 확인 · 정리·반환 진행' if customer else '고객 구매 취소 입력 확인 · 복귀'
            cp['result'] = 'MANUAL'
        elif current:
            msg = '고객 결제·회수 입력 대기' if customer else '고객 수령 입력 대기'
        outcome = _outcome(order, customer)
        if outcome:
            detail['outcome'] = outcome
            msg += ' · 결과 ' + outcome
    if nav and rid:
        task = json.loads(item.get('task') or '{}') or tasks.get(rid, {})
        obs = json.loads(item.get('observation') or '{}')
        if task.get('robot_id') != order.get('robot_id'):
            task = {}
        detail = {'task': task, 'robot_report': obs}
        if obs:
            cp['received'] = 'CONFIRMED'
        if obs.get('task_finished') is True:
            cp['result'] = 'MEASURED'
        if task.get('state') in ('UNKNOWN', 'FAILED'):
            simultaneous = task.get('robot_at_observation') or {}
            zone = obs.get('held_zone') or simultaneous.get('held_zone')
            stopped = obs.get('last_state') == 'STOPPED' or simultaneous.get('state') == 'STOPPED'

            state, cp['accepted'], cp['next_stage'] = 'BLOCKED', 'REJECTED', False
            msg = ' · '.join(filter(None, [
                f'구역 {zone} 점유' if zone else '', task['state'], task.get('detail'),
                '정지' if stopped else '', '도착 미성공']))
        elif task.get('state') == 'SUCCEEDED':
            msg = '주행 원장 SUCCEEDED · ' + ('관제 단계 완료' if complete else '단계 완료 미확인')
        elif task:
            msg = f"주행 원장 {task['state']} · 완료 미확인"
    hold = order.get('detail') or order.get('hold_reason')
    if stage.startswith('DOCK_') and ('xy_m' in data or 'yaw_deg' in data):
        text, extra = _dock_text(data, dock or {'corrected': False, 'exhausted': False})
        msg += text
        detail.update(extra)
    if current and order.get('state') in BLOCKED and not (complete or manual):
        state, cp['accepted'] = 'BLOCKED', 'REJECTED'
        msg += ' · ' + (hold or order['state'])
        if hold and ('시간 초과' in hold or 'timeout' in hold.lower()):
            cp['result'] = 'TIMEOUT'
    if (following and rid and not current and not manual and not failed
            and cp['accepted'] != 'REJECTED'):
        cp['next_stage'] = True
    if not last and state == 'RUNNING':
        state = 'PREVIOUS'
    if stage == 'RETURN_EXIT' and complete and order.get('state') == 'COMPLETED':
        msg = ('후미 이탈 clear 기록 · 주문 종결' if data.get('clear') is True
               else '관제 단계 완료 · 주문 종결 · clear 실측 미확인')
        cp['next_stage'] = True
    if stage == 'RETURN_HOME' and customer and order.get('customer_timed_out'):
        msg += ' · 신발 실은 채 복귀'
    if stage == 'CUSTOMER' and order.get('kind') == 'return':
        # 관제 CustomerReceipt 는 회수 주문이면 수령 대기 없이 넘어간다(completed 에도 남지 않는다).
        state, msg = 'SKIPPED', '회수 주문 · 고객 수령 생략(관제가 건너뜀)'
    return {'stage_code': stage, 'stage_name': spec['name'], 'target': target, 'action': action,
            'is_correction': stage.startswith('CORRECT_'), 'attempt_no': idx,
            'command_id': rid if nav else None, 'request_id': rid, 'status': state,
            'checkpoints': cp, 'evidence_summary': msg, 'evidence_detail': detail or None,
            'hold_reason': hold if current else None}
