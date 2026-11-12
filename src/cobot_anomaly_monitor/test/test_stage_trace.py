"""2026-11-09 홈랩 1차 합격 기준 검증 테스트.

합격 기준:
1. pinky1의 B 점유 후 정지 사례:
   화면에 B 점유 -> ZB 이동 작업 UNKNOWN(운영자 stop) -> 로봇 정지가 나타나고, ZB 도착 성공으로 표시되지 않아야 한다.
2. 7번(VERIFY_LOAD) 적재 표본 2개와 팔 퇴피 확인:
   다음 단계로 넘어가지 않고 '적재 표본 1개 대기'가 보여야 하며, 수동 전환(operator_override) 뒤 늦은 영상 프레임이
   수동 결정을 덮어쓰지 않아야 한다.
"""

from cobot_anomaly_monitor.stage_trace import build_stage_trace

from cobot_anomaly_monitor.console_api import ConsoleApi


def test_case_1_pinky1_token_b_operator_stop_records_unknown_not_success():
    """시험 1: B 토큰 점유 뒤 운영자 stop 시 ZB 도착 성공으로 표시하지 않고 정지/UNKNOWN으로 남긴다."""
    order = {
        "order_id": "order_test_1",
        "robot_id": "pinky1",
        "stage": "MOVE_PICKUP",
        "state": "RUNNING",
        "completed": [],
        "request_id": "cmd_move_zb",
    }
    work_history = []
    tasks = {
        "cmd_move_zb": {
            "task_id": "cmd_move_zb",
            "robot_id": "pinky1",
            "command": "zone:ZB",
            "state": "UNKNOWN",
            "detail": "operator stop",
            "robot_at_observation": {"held_zone": "B", "state": "STOPPED"},
        }
    }
    trace = build_stage_trace(
        order=order,
        work_history=work_history,
        tasks=tasks,
        live_work=[],
    )

    move_step = next(r for r in trace if r["stage_code"] == "MOVE_PICKUP")
    assert move_step["status"] == "BLOCKED"
    assert move_step["checkpoints"]["received"] == "UNCONFIRMED"
    assert move_step["checkpoints"]["result"] != "TIMEOUT"
    assert move_step["checkpoints"]["accepted"] == "REJECTED"
    assert move_step["checkpoints"]["next_stage"] is False

    summary = move_step["evidence_summary"]
    # 구역 B 점유, UNKNOWN, 운영자 stop, 로봇 정지 사실이 포함되어야 함
    assert "B" in summary
    assert "UNKNOWN" in summary
    assert "stop" in summary
    assert "정지" in summary
    # 절대로 도착 성공으로 표시되어서는 안 됨
    assert "도착 성공" not in summary
    assert "task_finished" not in summary


def test_case_2a_verify_load_two_samples_waits_for_one_more_sample():
    """시험 2-A: 7번 VERIFY_LOAD에서 영상 표본 2개와 팔 퇴피 확인만 들어온 경우 '적재 표본 1개 대기'를 표시하고 다음 단계로 진입하지 않는다."""
    order = {
        "order_id": "order_test_2",
        "robot_id": "pinky2",
        "stage": "VERIFY_LOAD",
        "state": "RUNNING",
        "completed": ["MOVE_PICKUP", "PICKUP_EXIT", "DOCK_PICKUP", "MARKER", "PICK", "LOAD"],
        "request_id": "req_vl_123",
    }
    live_work = [
        {
            "request_id": "req_vl_123",
            "order_id": "order_test_2",
            "robot_id": "pinky2",
            "stage": "VERIFY_LOAD",
            "target": "vision",
            "action": "verify_load",
            "load_join": True,
            "evidence_count": 2,
            "arm_checked": True,
            "wait_reason": "표본 대기",
        }
    ]

    trace = build_stage_trace(
        order=order,
        work_history=[],
        live_work=live_work,
    )

    vl_step = next(r for r in trace if r["stage_code"] == "VERIFY_LOAD")
    assert vl_step["status"] == "RUNNING"
    assert vl_step["checkpoints"]["accepted"] == "WAITING"
    assert vl_step["checkpoints"]["next_stage"] is False

    summary = vl_step["evidence_summary"]
    # 3개 중 1개 대기 사실 및 팔 퇴피 확인 표기
    assert "적재 표본 1개 대기" in summary or "2/3" in summary
    assert "팔 퇴피 확인됨" in summary

    # 다음 단계인 LEAVE_PICKUP(8번)은 아직 WAITING 상태여야 함
    leave_step = next(r for r in trace if r["stage_code"] == "LEAVE_PICKUP")
    assert leave_step["status"] == "WAITING"
    assert leave_step["checkpoints"]["requested"] is False


def test_case_2b_verify_load_manual_override_persists_even_with_late_frames():
    """시험 2-B: 운영자가 수동 확정(operator_override)한 뒤 늦은 프레임이 도착해도 결정이 덮어써지지 않고 완료 이력에 남는다."""
    order = {
        "order_id": "order_test_2",
        "robot_id": "pinky2",
        "stage": "LEAVE_PICKUP",
        "state": "RUNNING",
        "completed": ["MOVE_PICKUP", "PICKUP_EXIT", "DOCK_PICKUP", "MARKER", "PICK", "LOAD", "VERIFY_LOAD"],
        "operator_completed": ["VERIFY_LOAD"],
    }
    work_history = [
        {
            "request_id": "req_vl_123",
            "order_id": "order_test_2",
            "stage": "VERIFY_LOAD",
            "target": "vision",
            "action": "verify_load",
            "state": "APPROVED",
            "result": {
                "success": True,
                "data": {
                    "load_present": True,
                    "arm_safe": True,
                    "decision": "operator_override",
                    "manual": True,
                    "operator": "op_kgh",
                },
                "detail": "육안 확인 완료",
            },
        }
    ]

    trace = build_stage_trace(
        order=order,
        work_history=work_history,
    )

    vl_step = next(r for r in trace if r["stage_code"] == "VERIFY_LOAD")
    assert vl_step["status"] == "COMPLETED"
    assert vl_step["checkpoints"]["accepted"] == "ACCEPTED"
    assert vl_step["checkpoints"]["next_stage"] is True

    # 완료 상세 증거에 operator_override가 보존되어야 함
    assert vl_step["evidence_detail"]["decision"] == "operator_override"
    assert vl_step["evidence_detail"]["operator"] == "op_kgh"
    assert "operator_override" in vl_step["evidence_summary"] or "운영자 수동 완료" in vl_step["evidence_summary"]


def test_read_only_api_uses_real_snapshot_and_survives_restart(tmp_path):
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery_zb')
        order = stack.until('MOVE_PICKUP')
        rid = order['request_id']
        url = '/api/fms/orders/order1/trace'
        stack.console.commands = False
        status, body = stack.console.handle('GET', url, None)
        assert status == 200 and len(body['trace']) == 19
        row = body['trace'][0]
        assert row['command_id'] == rid and row['target'] == 'pinky1'
        assert row['checkpoints']['received'] == 'UNCONFIRMED'
        stack.core.on_status('pinky1', {'command_id': rid, 'held_zone': 'B', 'state': 'MOVING'})
        snapshot = stack.api.snapshot()
        task = next(t for t in snapshot['tasks'] if t['task_id'] == rid)
        task.update(state='UNKNOWN', detail='운영자 stop', updated_at=stack.wall())
        stack.core.on_status('pinky1', {'held_zone': 'B', 'state': 'STOPPED'})
        snapshot['orders'][0].update(request_id=None, state='UNKNOWN')
        stack.core.on_tasks(snapshot)
        stack.core.orders.clear()
        stack.core.tasks.clear()
        # DB만으로 조회할 때에도 live adapter와 쓰기 권한이 필요하지 않다.
        from cobot_anomaly_monitor.monitor_store import MonitorStore
        from cobot_anomaly_monitor.monitor_core import MonitorCore
        historical = MonitorStore(tmp_path / 'monitor.sqlite3')
        core = MonitorCore(historical, stack.routes, ['pinky1'], lambda _: None)
        readonly = ConsoleApi(core, None, lambda fn: fn(), None, commands=False)
        row = readonly.handle('GET', url, None)[1]['trace'][0]
        assert row['command_id'] == rid and row['status'] == 'BLOCKED'
        assert '구역 B 점유' in row['evidence_summary'] and '정지' in row['evidence_summary']
        assert row['checkpoints']['received'] == 'CONFIRMED'
        assert not row['checkpoints']['next_stage']
        assert readonly.handle('GET', '/api/fms/orders/missing/trace', None)[0] == 404
        historical.close()
    finally:
        stack.close()


def test_attempts_keep_results_separate_and_do_not_invent_correction_success():
    order = dict(order_id='o', stage='DOCK_PICKUP', request_id='d2', state='RUNNING')
    history = [dict(order_id='o', stage='DOCK_PICKUP', request_id='d1', created_at=1,
                    state='APPROVED', result={'success': True, 'data': {'manual': True, 'xy_m': .1}}),
               dict(order_id='o', stage='CORRECT_PICKUP', request_id='c1', created_at=2,
                    state='PENDING')]
    rows = build_stage_trace(order, history)
    dock = [r for r in rows if r['stage_code'] == 'DOCK_PICKUP']
    assert [r['request_id'] for r in dock] == ['d1','d2']
    assert dock[0]['checkpoints']['accepted'] == 'UNCONFIRMED'
    assert dock[0]['evidence_detail']['xy_m'] == .1
    corr = next(r for r in rows if r['is_correction'])
    assert corr['checkpoints']['result'] == 'NONE'
    assert corr['checkpoints']['accepted'] == 'WAITING'
    assert not corr['checkpoints']['next_stage']


def test_customer_timeout_and_operator_skip_do_not_invent_measurement():
    order = dict(order_id='o', state='RUNNING', stage='LEAVE_DROPOFF',
                 completed=['CUSTOMER'], customer_timed_out=True, operator_completed=['VERIFY_LOAD'])
    rows = {r['stage_code']: r for r in build_stage_trace(order, [])}
    assert '무응답' in rows['CUSTOMER']['evidence_summary']
    assert rows['VERIFY_LOAD']['checkpoints']['received'] == 'UNCONFIRMED'
    assert not rows['VERIFY_LOAD']['checkpoints']['requested']


def test_queued_order_has_no_dispatched_first_request():
    rows = build_stage_trace(dict(order_id='o', state='WAITING', stage='MOVE_PICKUP'), [])
    assert not any(r['checkpoints']['requested'] for r in rows)


def test_external_result_mismatch_is_visible_without_claiming_acceptance(tmp_path):
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        order = stack.until('PICK')
        rid = order['request_id']
        req = dict(order_id='order1', stage='PICK', request_id=rid, target='omx1', robot_id='pinky1')
        stack.store.observe_work('request', req, stack.wall())
        wrong = dict(req, source='omx2', measured=True, finished=True, success=True, data={})
        stack.store.observe_work('result', wrong, stack.wall())
        stack.store.observe_work('result', wrong, stack.wall())
        readonly = ConsoleApi(stack.core, None, lambda fn: fn(), None)
        _, body = readonly.handle('GET', '/api/fms/orders/order1/trace', None)
        row = next(r for r in body['trace'] if r['stage_code'] == 'PICK')
        assert row['request_id'] == rid and row['checkpoints']['accepted'] == 'UNCONFIRMED'
        assert row['checkpoints']['received'] == 'UNCONFIRMED'
        assert len(row['evidence_detail']['observed_results']) == 1
        assert '불일치' in row['evidence_summary']
    finally:
        stack.close()


def test_arm_silence_and_foreign_reply_remain_distinct(tmp_path):
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        order = stack.until('PICK')
        def pick():
            body = stack.console.handle('GET', '/api/fms/orders/order1/trace', None)[1]
            return next(r for r in body['trace'] if r['stage_code'] == 'PICK')
        assert '결과 미관측' in pick()['evidence_summary']
        stack.store.observe_work('result', dict(order_id='order1', request_id='other',
                                robot_id=order['robot_id'], stage='PICK', source='omx1',
                                success=True, measured=True, finished=True), stack.wall())
        row = pick()
        assert row['request_id'] == order['request_id']
        assert row['evidence_detail']['other_result_ids'] == ['other']
        assert row['checkpoints']['result'] == 'NONE' and not row['checkpoints']['next_stage']
    finally:
        stack.close()


def test_docking_replay_links_bad_measurement_correction_and_new_measurement(tmp_path):
    from harness import Stack, POINTS
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        first = stack.until('DOCK_PICKUP')
        robot = first['robot_id']
        x, y, yaw = POINTS['ZA']
        stack.core.on_pose(robot, x + .2, y, yaw)
        stack.approve(first)
        correction = stack.until('CORRECT_PICKUP')
        stack.approve(correction)
        retry = stack.until('DOCK_PICKUP')
        stack.core.on_pose(robot, x, y, yaw)
        stack.approve(retry)
        stack.until('MARKER')
        rows = stack.console.handle('GET', '/api/fms/orders/order1/trace', None)[1]['trace']
        dock = [r for r in rows if r['stage_code']=='DOCK_PICKUP']
        corr = next(r for r in rows if r['stage_code']=='CORRECT_PICKUP')
        assert [r['request_id'] for r in dock] == [first['request_id'], retry['request_id']]
        assert dock[0]['evidence_detail']['xy_m'] > .1 and dock[1]['evidence_detail']['xy_m'] == 0
        assert corr['evidence_detail']['previous_measurement'] == first['request_id']
        assert corr['evidence_detail']['next_measurement'] == retry['request_id']
    finally:
        stack.close()


def test_customer_timeout_final_clear_and_separate_resource_evidence(tmp_path):
    import json
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        stack.approve(stack.until('VERIFY_UNLOAD'))
        stack.tick()
        assert stack.current()['stage'] == 'CUSTOMER'
        stack.wait(121)
        for _ in range(150):
            stack.step()
            if stack.current()['state'] == 'COMPLETED':
                break
        stack.core.on_tasks(stack.api.snapshot())
        def trace():
            rows = stack.console.handle('GET', '/api/fms/orders/order1/trace', None)[1]['trace']
            return {r['stage_code']: r for r in rows}
        rows = trace()
        assert rows['CUSTOMER']['checkpoints']['result'] == 'TIMEOUT'
        final = rows['RETURN_EXIT']
        assert final['evidence_detail']['clear'] and final['evidence_detail']['order_state']=='COMPLETED'
        assert final['evidence_detail']['terminal_resources'] is None
        events = [json.loads(r['payload']) for r in stack.repo.pending(limit=10000)]
        terminal = next(e for e in reversed(events) if e['type']=='scenario_bt_snapshot'
                        and e['job_state']=='COMPLETED')
        stack.core.on_task_event(terminal)
        stack.core.on_task_event(dict(terminal, recorded_at=terminal['recorded_at']-1,resources=['old']))
        assert trace()['RETURN_EXIT']['evidence_detail']['terminal_resources']['resources']==[]
        stack.core.on_task_event(dict(terminal,recorded_at=terminal['recorded_at']+1,resources=['lane_test']))
        assert 'lane_test' in trace()['RETURN_EXIT']['evidence_summary']
    finally:
        stack.close()


def test_operator_load_confirmation_keeps_bypass_evidence(tmp_path):
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        pickup = stack.until('PICK')
        robot = pickup['robot_id']
        stack.status[robot].update(busy=False, central_latched=False, arrived_zone='A')
        stack.tick()
        stack.scenario.confirm_loaded('order1', 'operator', '현장 상차 확인',
                                      dict(sku='SHOE42', arm_safe=True, load_present=True,
                                           pickup_path_clear=True))
        stack.tick()
        rows = stack.console.handle('GET', '/api/fms/orders/order1/trace', None)[1]['trace']
        skipped = next(r for r in rows if r['stage_code']=='VERIFY_LOAD')
        assert skipped['checkpoints']['result'] == 'MANUAL'
        assert skipped['evidence_detail']['operator_load_confirmation']['note']=='현장 상차 확인'
        assert not skipped['request_id'] and not skipped['checkpoints']['requested']
    finally:
        stack.close()
