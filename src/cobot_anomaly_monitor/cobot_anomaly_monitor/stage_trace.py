"""주문별로 실제 관측한 요청·작업 결과와 관제 스냅샷을 연결한다."""

import json

STAGE_SPECS = [
    {"stage": "MOVE_PICKUP", "target": "pinky", "action": "zone", "name": "1 상차지로 이동"},
    {"stage": "PICKUP_EXIT", "target": "vision", "action": "path_exit", "name": "2 상차 통로 확인"},
    {"stage": "DOCK_PICKUP", "target": "vision", "action": "dock_check", "name": "3 상차 접안 확인"},
    # 3a CORRECT_PICKUP: 조건부 하위 단계
    {"stage": "MARKER", "target": "vision", "action": "marker", "name": "4 상차 마커 확인"},
    {"stage": "PICK", "target": "omx1", "action": "pick", "name": "5 피킹"},
    {"stage": "LOAD", "target": "omx1", "action": "load", "name": "6 상차"},
    {"stage": "VERIFY_LOAD", "target": "vision", "action": "verify_load", "name": "7 적재 검증"},
    {"stage": "LEAVE_PICKUP", "target": "pinky", "action": "leave", "name": "8 상차지 출발"},
    {"stage": "MOVE_DROPOFF", "target": "pinky", "action": "zone", "name": "9 하차지로 이동"},
    {"stage": "PATH_EXIT", "target": "vision", "action": "path_exit", "name": "10 하차 통로 확인"},
    {"stage": "DOCK_DROPOFF", "target": "vision", "action": "dock_check", "name": "11 하차 접안 확인"},
    # 11a CORRECT_DROPOFF: 조건부 하위 단계
    {"stage": "QR", "target": "vision", "action": "qr", "name": "12 QR 확인"},
    {"stage": "PICK_DROPOFF", "target": "omx2", "action": "pick", "name": "13 하차 피킹"},
    {"stage": "UNLOAD", "target": "omx2", "action": "unload", "name": "14 하차 안착"},
    {"stage": "VERIFY_UNLOAD", "target": "vision", "action": "verify_unload", "name": "15 하차 검증"},
    {"stage": "CUSTOMER", "target": "operator", "action": "received", "name": "16 고객 수령"},
    {"stage": "LEAVE_DROPOFF", "target": "pinky", "action": "leave", "name": "17 하차지 출발"},
    {"stage": "RETURN_HOME", "target": "pinky", "action": "home", "name": "18 홈으로 복귀"},
    {"stage": "RETURN_EXIT", "target": "vision", "action": "path_exit", "name": "19 복귀 통로 확인 / 종결"},
]


NAVIGATION = {'MOVE_PICKUP', 'LEAVE_PICKUP', 'MOVE_DROPOFF', 'LEAVE_DROPOFF', 'RETURN_HOME'}
BLOCKED = {'UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL', 'FAILED'}


def build_stage_trace(order, work_history, tasks=None, live_work=None,
                      attempts=(), route=None, unmatched=(), terminal=None):
    """요약 완료 표시와 특정 시도에 대한 수신·수용 증거를 따로 계산한다."""
    if not order:
        return []
    route = route or {}
    task_map = tasks if isinstance(tasks, dict) else {t['task_id']: t for t in tasks or []}
    grouped = {}
    for item in [*attempts, *work_history, *(live_work or [])]:
        if item.get('order_id') != order['order_id'] or not item.get('request_id'):
            continue
        bucket = grouped.setdefault(item['stage'], {})
        bucket.setdefault(item['request_id'], {}).update(item)
    current = order.get('stage')
    current_id = order.get('request_id') or order.get('command_id')
    if current and current_id:
        grouped.setdefault(current, {}).setdefault(current_id, {'request_id': current_id})
    specs = []
    for spec in STAGE_SPECS:
        specs.append(spec)
        if spec['stage'] in ('DOCK_PICKUP', 'DOCK_DROPOFF'):
            code = spec['stage'].replace('DOCK_', 'CORRECT_')
            if code in grouped or code == current or code in order.get('completed', []):
                specs.append({'stage': code, 'name': ('3a' if code.endswith('PICKUP') else '11a')
                              + ' 접안 보정', 'target': 'navigation', 'action': 'dock_correct'})
    entered = set(grouped) | set(order.get('completed', []))
    if current and order.get('state') != 'WAITING':
        entered.add(current)
    rows = []
    base_names = [base['stage'] for base in STAGE_SPECS]
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
            row = _attempt(order, spec, item, task_map, idx, last, following, route)
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
                elif row['target'] in (route.get('pickup_arm'), route.get('dropoff_arm')):
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


def _attempt(order, spec, item, tasks, idx, last, following, route):
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
    elif stage in ('PICK', 'LOAD'):
        target = route.get('pickup_arm', target)
    elif stage in ('PICK_DROPOFF', 'UNLOAD'):
        target = route.get('dropoff_arm', target)
    target = item.get('target') or target
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
        if order.get('customer_timed_out'):
            msg, cp['result'] = '수령 무응답 · 복귀', 'TIMEOUT'
        elif order.get('customer_received'):
            msg, cp['result'] = '고객 수령 입력 확인', 'MANUAL'
        elif current:
            msg = '고객 수령 입력 대기'
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
    return dict(stage_code=stage, stage_name=spec['name'], target=target, action=item.get('action') or spec['action'],
                is_correction=stage.startswith('CORRECT_'), attempt_no=idx,
                command_id=rid if nav else None, request_id=rid, status=state, checkpoints=cp,
                evidence_summary=msg, evidence_detail=detail or None, hold_reason=hold if current else None)
