"""주문별로 실제 관측한 요청·작업 결과와 관제 스냅샷을 연결한다."""

import json

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


def _sent_route(route, items):
    """
    관제가 작업 요청에 실어 보낸 경로(dict)를 먼저 쓴다.

    감시 노드의 경로 표(scenario_config routes)는 사본이다. 자리 주문 경로(col1__P22 등)는
    관제가 shelf·destinations 로 만들어서 사본에 없다. 사본이 낡았을 때도 관제 값을 따른다.
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
    """회수 갈래 행을 보일지 정한다. 결제·시간 초과로 건너뛴 갈래는 대기 행으로 남기지 않는다."""
    if seen & set(CUSTOMER_RETURN_STAGES) or order.get('customer_declined'):
        return True
    if order.get('customer_received') or order.get('customer_timed_out'):
        return False
    return order.get('state') not in ('COMPLETED', 'FAILED')


def build_stage_trace(order, work_history, tasks=None, live_work=None,
                      attempts=(), route=None, unmatched=(), terminal=None):
    """요약 완료 표시와 특정 시도에 대한 수신·수용 증거를 따로 계산한다."""
    if not order:
        return []
    task_map = tasks if isinstance(tasks, dict) else {t['task_id']: t for t in tasks or []}
    items = [item for item in [*attempts, *work_history, *(live_work or [])]
             if item.get('order_id') == order['order_id'] and item.get('request_id')]
    route = _sent_route(route, items)
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
    arms = {route[key] for key in ROUTE_ARMS if route.get(key)}
    rows = []
    base_names = [spec['stage'] for spec in base]
    for spec in specs:
        stage = spec['stage']
        entries = sorted(grouped.get(stage, {}).values(), key=lambda e: (
            e.get('created_at') or e.get('first_seen') or float('inf'), e.get('attempt') or 0))
        if stage.startswith('CORRECT_'):
            successors = [stage.replace('CORRECT_', 'DOCK_')]
        else:
            successors = base_names[base_names.index(stage) + 1:][:1]
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
                elif last and not stage.startswith('CORRECT_') and not successor.startswith('CORRECT_'):
                    following = True
            row = _attempt(order, spec, item, task_map, idx, last, following, route, customer)
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


def _attempt(order, spec, item, tasks, idx, last, following, route, customer=False):
    stage = spec['stage']
    rid = item.get('request_id')
    nav = stage in NAVIGATION
    current = stage == order.get('stage') and last
    complete = stage in order.get('completed', []) and last
    manual = stage in order.get('operator_completed', []) and last
    observed = item.get('wire_results', [])
    matches = [entry['payload'] for entry in observed if (
        all(entry['payload'].get(k) == item.get(k) for k in ('order_id', 'stage', 'robot_id', 'request_id'))
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
    cp = dict(requested=bool(rid), received='UNCONFIRMED', result='NONE',
              accepted='WAITING', next_stage=False)
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
        msg = f'적재 표본 {max(0, 3-count)}개 대기 ({count}/3) · {arm}' if count < 3 else f'적재 표본 3/3 · {arm}'
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
    if nav and rid:
        task = json.loads(item.get('task') or '{}') or tasks.get(rid, {})
        obs = json.loads(item.get('observation') or '{}')
        if task.get('robot_id') != order.get('robot_id'):
            task = {}
        detail = dict(task=task, robot_report=obs)
        if obs:
            cp['received'] = 'CONFIRMED'
        if obs.get('task_finished') is True:
            cp['result'] = 'MEASURED'
        if task.get('state') in ('UNKNOWN', 'FAILED'):
            simultaneous = task.get('robot_at_observation') or {}
            zone = obs.get('held_zone') or simultaneous.get('held_zone')
            stopped = obs.get('last_state') == 'STOPPED' or simultaneous.get('state') == 'STOPPED'

            state, cp['accepted'], cp['next_stage'] = 'BLOCKED', 'REJECTED', False
            msg = ' · '.join(filter(None, [f"구역 {zone} 점유" if zone else '',
                task['state'], task.get('detail'), '정지' if stopped else '',
                '도착 미성공']))
        elif task.get('state') == 'SUCCEEDED':
            msg = '주행 원장 SUCCEEDED · ' + ('관제 단계 완료' if complete else '단계 완료 미확인')
        elif task:
            msg = f"주행 원장 {task['state']} · 완료 미확인"
    hold = order.get('detail') or order.get('hold_reason')
    if stage.startswith('DOCK_') and ('xy_m' in data or 'yaw_deg' in data):
        msg += f" · 실측 {data.get('xy_m', '미확인')} m / {data.get('yaw_deg', '미확인')}°"
    if current and order.get('state') in BLOCKED and not (complete or manual):
        state, cp['accepted'] = 'BLOCKED', 'REJECTED'
        msg += ' · ' + (hold or order['state'])
        if hold and ('시간 초과' in hold or 'timeout' in hold.lower()):
            cp['result'] = 'TIMEOUT'
    if following and rid and not current and not manual and cp['accepted'] != 'REJECTED':
        cp['next_stage'] = True
    if not last and state == 'RUNNING':
        state = 'PREVIOUS'
    if stage == 'RETURN_EXIT' and complete and order.get('state') == 'COMPLETED':
        msg = ('후미 이탈 clear 기록 · 주문 종결' if data.get('clear') is True
               else '관제 단계 완료 · 주문 종결 · clear 실측 미확인')
        cp['next_stage'] = True
    return dict(stage_code=stage, stage_name=spec['name'], target=target, action=action,
                is_correction=stage.startswith('CORRECT_'), attempt_no=idx,
                command_id=rid if nav else None, request_id=rid, status=state, checkpoints=cp,
                evidence_summary=msg, evidence_detail=detail or None, hold_reason=hold if current else None)
