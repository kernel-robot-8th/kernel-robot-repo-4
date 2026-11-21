"""2026-11-09 홈랩 1차 합격 기준 검증 테스트.

합격 기준:
1. pinky1의 B 점유 후 정지 사례:
   화면에 B 점유 -> ZB 이동 작업 UNKNOWN(운영자 stop) -> 로봇 정지가 나타나고, ZB 도착 성공으로 표시되지 않아야 한다.
2. 7번(VERIFY_LOAD) 적재 표본 2개와 팔 퇴피 확인:
   다음 단계로 넘어가지 않고 '적재 표본 1개 대기'가 보여야 하며, 수동 전환(operator_override) 뒤 늦은 영상 프레임이
   수동 결정을 덮어쓰지 않아야 한다.
"""

from pathlib import Path

from cobot_anomaly_monitor.stage_trace import (
    build_stage_trace, CUSTOMER_RETURN_STAGES, CUSTOMER_STAGES, NAVIGATION, ROUTE_ARMS, STAGE_INFO,
    STAGES)

from cobot_anomaly_monitor.console_api import ConsoleApi
import pytest

# 관제 origin/sakim 1b0cb08 이 shelf·customer_return·destinations 로 만드는 col1__P22 경로와 같은 모양.
SEAT_ROUTE = {'pickup': 'ZB', 'pickup_arm': 'omx2', 'customer': 'P22', 'dropoff': 'ZC',
              'dropoff_arm': 'omx3', 'restock': 'ZA', 'restock_arm': 'omx1', 'lane': 'main'}
# 자리 주문에 없는 경로 주문 하차 쪽 단계
DROPOFF_ONLY = {'MOVE_DROPOFF', 'PATH_EXIT', 'DOCK_DROPOFF', 'QR', 'PICK_DROPOFF', 'UNLOAD',
                'VERIFY_UNLOAD', 'LEAVE_DROPOFF'}
SEAT_BEFORE_CUSTOMER = list(CUSTOMER_STAGES[:CUSTOMER_STAGES.index('CUSTOMER')])


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
    # d1 뒤 보정 요청(c1)이 나갔으니 관제가 d1 실측을 받은 것이다(11-21 G6). 보정 성공은 만들지 않는다.
    assert dock[0]['checkpoints']['accepted'] == 'ACCEPTED'
    assert '보정 요청 관측' in dock[0]['evidence_summary']
    assert dock[0]['evidence_detail']['correction_requested'] is True
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
        # 고객 대기 시간은 dev yaml 값을 따른다(11-20 sakim 기준 120 → 300).
        stack.wait(stack.config['customer_timeout_sec'] + 1)
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


def test_stage_tables_match_control_scenario_tree():
    """감시 표는 팀 패키지를 import 하지 않는다. 팀 패키지가 있으면 관제 표(sakim 1b0cb08)와 대조한다."""
    from cobot_anomaly_monitor.stage_trace import CORRECTION, CUSTOMER_ONLY_STAGES
    tree = pytest.importorskip('cobot_fleet_control.scenario_tree')
    contracts = pytest.importorskip('cobot_fleet_control.scenario_contracts')
    assert STAGES == tuple(tree.STAGES)
    assert CUSTOMER_STAGES == tuple(tree.CUSTOMER_STAGES)
    assert set(CUSTOMER_RETURN_STAGES) == set(tree.CUSTOMER_RETURN_STAGES)
    assert set(STAGE_INFO) == set(tree.STAGES) | set(tree.CUSTOMER_STAGES)
    assert NAVIGATION == set(contracts.NAVIGATION)
    assert ROUTE_ARMS == tuple(contracts.ROUTE_ARMS)
    for stage, operation in contracts.NAVIGATION.items():
        assert STAGE_INFO[stage][1] == operation, stage
    for stage, work in contracts.WORK.items():
        expected = CORRECTION[:2] if stage.startswith('CORRECT_') else STAGE_INFO[stage][:2]
        assert tuple(work) == expected, stage
    for stage in CUSTOMER_ONLY_STAGES:
        assert STAGE_INFO[stage][2] == tree.LABELS[stage], stage


def test_route_order_targets_come_from_route_not_fixed_arms():
    """요청을 못 본 행의 대체 대상은 경로 칸이다. 경로를 모르면 칸 이름을 보인다(관제 route.get(actor, actor))."""
    order = dict(order_id='o', state='WAITING', stage='MOVE_PICKUP')
    rows = {r['stage_code']: r for r in build_stage_trace(order, [])}
    assert len(rows) == 19
    assert rows['PICK']['target'] == rows['LOAD']['target'] == 'pickup_arm'
    assert rows['PICK_DROPOFF']['target'] == rows['UNLOAD']['target'] == 'dropoff_arm'
    zb = {'pickup': 'ZB', 'dropoff': 'ZC', 'pickup_arm': 'omx2', 'dropoff_arm': 'omx3',
          'lane': 'main'}  # sakim 1b0cb08 lab_delivery_zb
    rows = {r['stage_code']: r for r in build_stage_trace(order, [], route=zb)}
    assert rows['PICK']['target'] == rows['LOAD']['target'] == 'omx2'
    assert rows['PICK_DROPOFF']['target'] == rows['UNLOAD']['target'] == 'omx3'
    assert rows['UNLOAD']['action'] == 'unload'
    returned = dict(order, kind='return')
    rows = {r['stage_code']: r for r in build_stage_trace(returned, [], route=zb)}
    assert rows['UNLOAD']['action'] == 'warehouse_store'


def test_seat_order_paid_lists_only_its_own_stages():
    """결제로 끝난 자리 주문에 하차 8행과 건너뛴 회수 갈래가 대기 행으로 남지 않는다."""
    done = [s for s in CUSTOMER_STAGES if s not in CUSTOMER_RETURN_STAGES]
    order = dict(order_id='s', robot_id='pinky1', state='COMPLETED', stage='RETURN_EXIT',
                 completed=done, customer_received=True, customer_declined=False)
    rows = build_stage_trace(order, [], route=SEAT_ROUTE)
    assert [r['stage_code'] for r in rows] == done
    assert not DROPOFF_ONLY & {r['stage_code'] for r in rows}
    assert all(r['status'] == 'COMPLETED' for r in rows)
    by = {r['stage_code']: r for r in rows}
    assert by['PICK']['target'] == by['LOAD']['target'] == 'omx2'
    assert by['MOVE_CUSTOMER']['target'] == 'pinky1' and by['MOVE_CUSTOMER']['action'] == 'goto'
    assert by['CUSTOMER']['evidence_summary'] == '고객 결제 입력 확인 · 결과 PAID'
    assert by['CUSTOMER']['evidence_detail']['outcome'] == 'PAID'
    assert by['CUSTOMER']['stage_name'] == '10 고객 결제·회수 대기'
    # 번호는 관제 CUSTOMER_STAGES 의 위치다. 회수 갈래를 건너뛰어도 바뀌지 않는다.
    assert by['RETURN_HOME']['stage_name'].startswith('17 ')


def test_seat_order_timeout_skips_return_branch():
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='RETURN_HOME',
                 request_id='home1', completed=SEAT_BEFORE_CUSTOMER + ['CUSTOMER'],
                 customer_timed_out=True, customer_declined=False)
    rows = {r['stage_code']: r for r in build_stage_trace(order, [], route=SEAT_ROUTE)}
    assert not set(CUSTOMER_RETURN_STAGES) & set(rows)
    assert rows['CUSTOMER']['checkpoints']['result'] == 'TIMEOUT'
    assert '신발 실은 채' in rows['CUSTOMER']['evidence_summary']
    assert rows['RETURN_HOME']['status'] == 'RUNNING'


def test_seat_order_waiting_for_customer_lists_both_branches():
    """결제·회수 입력 전에는 회수 갈래도 다음에 올 수 있는 단계라 대기 행으로 보인다."""
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='CUSTOMER',
                 completed=SEAT_BEFORE_CUSTOMER, customer_declined=False)
    rows = build_stage_trace(order, [], route=SEAT_ROUTE)
    assert [r['stage_code'] for r in rows] == list(CUSTOMER_STAGES)
    by = {r['stage_code']: r for r in rows}
    assert by['CUSTOMER']['evidence_summary'] == '고객 결제·회수 입력 대기'
    assert all(by[s]['status'] == 'WAITING' for s in CUSTOMER_RETURN_STAGES)


def test_seat_return_branch_uses_route_arms_from_control_request():
    """
    감시 경로 표에서 경로를 못 찾으면(옛 기록·낡은 사본) route 가 빈 값으로 온다.

    관제가 요청에 실어 보낸 route 로 자리 주문을 알아보고 팔 칸을 채운다.
    RESTOCK(restock_arm) 결과가 없으면 '결과 미관측'을 붙인다.
    """
    completed = SEAT_BEFORE_CUSTOMER + ['CUSTOMER', 'MOVE_ARRANGE', 'ARRANGE', 'LEAVE_ARRANGE',
                                        'MOVE_RESTOCK']
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='RESTOCK',
                 request_id='r-restock', completed=completed, customer_declined=True)
    history = [dict(order_id='s', robot_id='pinky1', stage='ARRANGE', request_id='r-arrange',
                    target='omx3', action='arrange_shoe', route=SEAT_ROUTE, created_at=10.0,
                    state='APPROVED', result={'success': True, 'data': {}})]
    rows = build_stage_trace(order, history, route={})
    assert [r['stage_code'] for r in rows] == list(CUSTOMER_STAGES)
    by = {r['stage_code']: r for r in rows}
    assert by['PICK']['target'] == by['LOAD']['target'] == 'omx2'
    assert by['ARRANGE']['target'] == 'omx3' and by['ARRANGE']['action'] == 'arrange_shoe'
    assert by['ARRANGE']['status'] == 'COMPLETED'
    assert by['RESTOCK']['target'] == 'omx1' and by['RESTOCK']['action'] == 'warehouse_store'
    assert by['RESTOCK']['status'] == 'RUNNING'
    assert '결과 미관측' in by['RESTOCK']['evidence_summary']
    assert '회수' in by['CUSTOMER']['evidence_summary']
    assert by['LEAVE_ARRANGE']['target'] == 'pinky1'


def test_seat_order_is_recognized_by_stage_without_any_route():
    """경로도 요청도 못 봤어도 자리 주문에만 있는 단계가 보이면 자리 단계열을 쓴다."""
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='MOVE_CUSTOMER',
                 request_id='goto1', completed=SEAT_BEFORE_CUSTOMER[:-1])
    rows = {r['stage_code']: r for r in build_stage_trace(order, [])}
    assert 'MOVE_CUSTOMER' in rows and not DROPOFF_ONLY & set(rows)
    assert rows['MOVE_CUSTOMER']['status'] == 'RUNNING'
    assert rows['PICK']['target'] == 'pickup_arm'
    assert rows['ARRANGE']['target'] == 'dropoff_arm'
    assert rows['RESTOCK']['target'] == 'restock_arm'


SEAT_POINT = {'MOVE_PICKUP': 'pickup', 'MOVE_CUSTOMER': 'customer', 'MOVE_ARRANGE': 'dropoff',
              'MOVE_RESTOCK': 'restock'}


def _team_scenario_config():
    """관제 패키지 안의 scenario.yaml(고객 자리 설정이 있는 sakim 1b0cb08 이후 판)을 읽는다."""
    fleet = pytest.importorskip('cobot_fleet_control.scenario')
    import yaml
    team = 'cobot_navigation/cobot_fleet_control/config/scenario.yaml'
    candidates = [
        Path(fleet.__file__).resolve().parents[1] / 'config/scenario.yaml',
        Path(__file__).resolve().parents[2] / team,
    ]
    for path in candidates:
        if path.is_file():
            config = yaml.safe_load(path.read_text(encoding='utf-8'))
            if config.get('destinations') and config.get('customer_return'):
                return config
    pytest.skip('고객 자리 설정이 있는 관제 scenario.yaml 없음')


def _seat_stack(path):
    """관제만 팀 scenario.yaml 로 다시 띄운다. 시험 감시 경로 표는 개발 yaml routes 만 써서 col*__P22 가 없다."""
    config = _team_scenario_config()
    from harness import Stack
    from cobot_fleet_control.control_api import ControlAPI
    from cobot_fleet_control.scenario import ScenarioService
    stack = Stack(path)
    stack.scenario = ScenarioService(stack.repo, stack.fleet, stack.gateway, **config,
                                     clock=lambda: stack.now)
    stack.api = ControlAPI(stack.scenario, stack.fleet, stack.gateway)
    stack.adapter.publish = stack.scenario.result
    stack.scenario.armed = True
    stack.scenario.store.set_stock('SHOE42', 10, 3, 1)
    return stack


def _drive_seat(stack, order):
    """자리 주문 주행 단계를 끝낸다. 구역이면 자세와 구역 토큰을 맞추고, 일반 지점이면 도착만 알린다."""
    from harness import POINTS, ZONE
    robot, stage = order['robot_id'], order['stage']
    status = stack.status[robot]
    if stage in SEAT_POINT:
        point = stack.scenario.routes[order['route']][SEAT_POINT[stage]]
        stack.move(robot, 'MOVING', point)
        if point in ZONE:
            x, y, yaw = POINTS[point]
            stack.core.on_pose(robot, x + 0.01, y, yaw + 0.02)
            status.update(state='HOLDING_ZONE', held_zone=ZONE[point], detail=point)
        else:
            status.update(state='IDLE_WAIT', held_zone=None, detail=point)
    elif stage == 'RETURN_HOME':
        stack.move(robot, 'RETURNING', 'EXIT')
        status.update(state='IDLE', held_zone=None, detail='')
    else:
        stack.move(robot, 'LEAVING_ZONE', 'EXIT')
        status.update(state='IDLE_WAIT', held_zone=None, detail='')
    stack.core.on_speed(robot, 0.0)
    stack.fleet.tick(allow_dispatch=True)
    stack.fleet.on_status(robot, {'command_id': order['request_id'], 'state': 'DONE',
                                  'task_finished': True})
    stack.fleet.tick(allow_dispatch=True)


@pytest.mark.parametrize('decision', ['declined', 'received'])
def test_seat_order_trace_and_progress_follow_control_stages(tmp_path, decision):
    """관제 실제 ScenarioService(팀 scenario.yaml)로 P22 자리 주문을 끝까지 돌리고 감시 표시를 본다."""
    stack = _seat_stack(tmp_path)
    try:
        stack.scenario.submit({'order_id': 'seat1', 'sku': 'SHOE42', 'destination': 'P22'})
        for _ in range(400):
            stack.tick()
            order = stack.current('seat1')
            if order['state'] != 'RUNNING':
                if order['state'] in ('COMPLETED', 'FAILED', 'UNKNOWN', 'ESTOP'):
                    break
                continue
            if order['stage'] == 'CUSTOMER':
                getattr(stack.scenario, decision)('seat1')
            elif order['request_id']:
                if order['stage'] in NAVIGATION:
                    _drive_seat(stack, order)
                else:
                    stack.approve(order)
        stack.core.on_tasks(stack.api.snapshot())
        final = stack.current('seat1')
        assert final['state'] == 'COMPLETED', final.get('detail')
        assert final['route'] == 'col1__P22' and 'col1__P22' not in stack.core.routes
        rows = stack.console.handle('GET', '/api/fms/orders/seat1/trace', None)[1]['trace']
        expected = [s for s in CUSTOMER_STAGES
                    if decision == 'declined' or s not in CUSTOMER_RETURN_STAGES]
        assert [r['stage_code'] for r in rows] == expected
        assert all(r['status'] == 'COMPLETED' for r in rows)
        by = {r['stage_code']: r for r in rows}
        assert by['PICK']['target'] == by['LOAD']['target'] == 'omx2'
        assert by['MOVE_CUSTOMER']['action'] == 'goto'
        if decision == 'declined':
            arrange, restock = by['ARRANGE'], by['RESTOCK']
            assert (arrange['target'], arrange['action']) == ('omx3', 'arrange_shoe')
            assert (restock['target'], restock['action']) == ('omx1', 'warehouse_store')
        # 감시 기록: 결제·회수 뒤에는 빈 트레이를 확인한 센서가 없어 EMPTY_UNVERIFIED 로 둔다(11-21 결정 D2).
        mission = stack.store.scenario('seat1')
        assert mission['cargo_state'] == 'EMPTY_UNVERIFIED' and mission['current_step_seq'] == 7
        robot = final['robot_id']
        views = [v[robot] for v in stack.history if v[robot]['order_id'] == 'seat1']
        steps = {v['stage']: v['step_seq'] for v in views}
        cargo = {v['stage']: v['cargo_state'] for v in views}
        assert steps['MOVE_CUSTOMER'] == steps['CUSTOMER'] == 4
        assert cargo['CUSTOMER'] == 'LOADED'
        assert [v['step_seq'] for v in views] == sorted(v['step_seq'] for v in views)
        tasks = {t['step_seq']: t['task_state'] for t in stack.store.tasks('seat1')}
        if decision == 'declined':
            assert steps['ARRANGE'] == steps['RESTOCK'] == 6
            assert cargo['RESTOCK'] == 'UNLOADING' and cargo['LEAVE_RESTOCK'] == 'EMPTY_UNVERIFIED'
        else:
            assert not {5, 6} & {v['step_seq'] for v in views}
            assert cargo['RETURN_HOME'] == 'EMPTY_UNVERIFIED'
            # 결제한 자리 주문은 하차 정차·팔 하역을 하지 않는다.
            assert tasks[5] == tasks[6] == 'SKIPPED'
    finally:
        stack.close()


# 11-21 추적표 표시 보강(G6·S9·S10·S11·자리 결과). 감시 scenario_config 공차는 dev yaml 값이다.
def _tolerance(stack):
    return {'dock_xy_m': stack.config['dock_xy_m'], 'dock_yaw_deg': stack.config['dock_yaw_deg']}


def _trace(stack, order_id='order1'):
    status, body = stack.console.handle('GET', f'/api/fms/orders/{order_id}/trace', None)
    assert status == 200, body
    return body


def test_failed_response_is_failed_row_with_retry_safe():
    """장치 실패 응답(success false)은 'MEASURED 결과 기록'이 아니라 FAILED 와 실패 사유로 보인다."""
    order = dict(order_id='o', robot_id='pinky1', state='RUNNING', stage='PICK', request_id='p3',
                 completed=['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER'])
    history = [
        dict(order_id='o', stage='PICK', request_id='p1', target='omx1', created_at=1.0,
             state='REJECTED', result={'success': False, 'detail': '그리퍼 미파지',
                                       'data': {'retry_safe': True, 'manual': True}}),
        dict(order_id='o', stage='PICK', request_id='p2', target='omx1', created_at=2.0,
             state='REJECTED', result={'success': False, 'detail': '', 'data': {}}),
        dict(order_id='o', stage='LOAD', request_id='l1', target='omx1', created_at=2.5,
             state='PENDING'),
        dict(order_id='o', stage='PICK', request_id='p3', target='omx1', created_at=3.0,
             state='PENDING')]
    picks = [r for r in build_stage_trace(order, history) if r['stage_code'] == 'PICK']
    assert [r['status'] for r in picks] == ['FAILED', 'FAILED', 'RUNNING']
    assert picks[0]['evidence_summary'] == '실패 응답: 그리퍼 미파지 (retry_safe=true)'
    assert picks[1]['evidence_summary'] == '실패 응답: 사유 없음 (retry_safe=없음)'
    # 실패한 시도 뒤 다음 단계 요청이 보여도 그 시도가 다음 단계로 넘겼다고 적지 않는다.
    assert not picks[1]['checkpoints']['next_stage']
    assert picks[0]['evidence_detail']['success'] is False


def test_rejected_pick_with_and_without_retry_safe_through_control(tmp_path):
    """관제 실제 흐름: retry_safe 실패는 재요청, retry_safe 없는 실패는 UNKNOWN 보류와 이후 행 '진행 안 함'."""
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        first = stack.until('PICK')
        stack.adapter.reject(first['request_id'], 'kgh', '그리퍼 미파지', retry_safe=True)
        for _ in range(20):
            stack.tick()
            retry = stack.current()
            if retry['request_id'] and retry['request_id'] != first['request_id']:
                break
        assert retry['stage'] == 'PICK' and retry['state'] == 'RUNNING'
        stack.adapter.reject(retry['request_id'], 'kgh', '팔 정지')
        for _ in range(20):
            stack.tick()
            if stack.current()['state'] == 'UNKNOWN':
                break
        assert stack.current()['state'] == 'UNKNOWN'
        stack.core.on_tasks(stack.api.snapshot())
        rows = _trace(stack)['trace']
        picks = [r for r in rows if r['stage_code'] == 'PICK']
        assert [r['request_id'] for r in picks] == [first['request_id'], retry['request_id']]
        assert picks[0]['status'] == 'FAILED'
        assert picks[0]['evidence_summary'].startswith('실패 응답: 그리퍼 미파지 (retry_safe=true)')
        assert picks[1]['status'] == 'BLOCKED'
        assert picks[1]['evidence_summary'].startswith('실패 응답: 팔 정지 (retry_safe=없음)')
        assert '재시도 안전성 미확인' in picks[1]['evidence_summary']
        later = [r for r in rows if STAGES.index(r['stage_code']) > STAGES.index('PICK')]
        assert later and all(r['status'] == 'SKIPPED' for r in later)
        assert all('주문 보류(UNKNOWN)' in r['evidence_summary'] for r in later)
    finally:
        stack.close()


def test_dock_rows_compare_with_scenario_config_tolerance(tmp_path):
    """정차 행은 감시 scenario_config 공차와 비교한다. 보정 요청이 뒤따른 시도는 관제 수용으로 본다."""
    from harness import Stack, POINTS
    stack = Stack(tmp_path)
    try:
        stack.console.dock_tolerance = _tolerance(stack)
        stack.order(route='lab_delivery')
        first = stack.until('DOCK_PICKUP')
        robot = first['robot_id']
        x, y, yaw = POINTS['ZA']
        stack.core.on_pose(robot, x + .2, y, yaw)
        stack.approve(first)
        stack.approve(stack.until('CORRECT_PICKUP'))
        retry = stack.until('DOCK_PICKUP')
        stack.core.on_pose(robot, x, y, yaw)
        stack.approve(retry)
        stack.until('MARKER')
        dock = [r for r in _trace(stack)['trace'] if r['stage_code'] == 'DOCK_PICKUP']
        assert [r['request_id'] for r in dock] == [first['request_id'], retry['request_id']]
        out, ok = dock[0], dock[1]
        assert '실측 0.200 m / 0.0° · 공차 초과 → 보정' in out['evidence_summary']
        assert out['checkpoints']['accepted'] == 'ACCEPTED'
        assert out['evidence_detail']['within_tolerance'] is False
        assert out['evidence_detail']['dock_tolerance'] == {'xy_m': 0.03, 'yaw_deg': 15.0}
        assert out['evidence_detail']['correction_requested'] is True
        assert ok['status'] == 'COMPLETED' and '공차 이내' in ok['evidence_summary']
        assert ok['evidence_detail']['within_tolerance'] is True
        # 공차 사본이 없으면 관제 행동(보정 요청)으로만 적는다.
        stack.console.dock_tolerance = None
        dock = [r for r in _trace(stack)['trace'] if r['stage_code'] == 'DOCK_PICKUP']
        assert '공차 초과 → 보정 (관제 보정 요청 기준)' in dock[0]['evidence_summary']
        assert '공차' not in dock[1]['evidence_summary']
    finally:
        stack.close()


def test_dock_failure_safe_return_skips_unreached_rows(tmp_path):
    """
    11-19 현장 FAILED '정차 공차 초과' 재현. 정차 5 cm 오차로 보정 예산을 다 쓰면 관제는 안전 복귀 뒤 FAILED 다.

    도달하지 않은 MARKER~하차 행은 대기가 아니라 SKIPPED, 안전 복귀 두 행은 '안전 복귀: <failure>' 다.
    """
    from harness import Stack, POINTS
    stack = Stack(tmp_path)
    try:
        stack.console.dock_tolerance = _tolerance(stack)
        stack.order(route='lab_delivery')
        x, y, yaw = POINTS['ZA']
        during = None
        for _ in range(600):
            stack.tick()
            order = stack.current()
            if order['state'] != 'RUNNING':
                break
            if order['stage'] == 'DOCK_PICKUP' and order['request_id']:
                stack.core.on_pose(order['robot_id'], x + .05, y, yaw)
            if order['failure'] and order['stage'] == 'RETURN_HOME' and during is None:
                stack.core.on_tasks(stack.api.snapshot())
                during = {r['stage_code']: r for r in _trace(stack)['trace']}
            stack.advance('order1')
        stack.core.on_tasks(stack.api.snapshot())
        final = stack.current()
        assert final['state'] == 'FAILED' and final['failure'] == '정차 공차 초과'
        rows = _trace(stack)['trace']
        dock = [r for r in rows if r['stage_code'] == 'DOCK_PICKUP']
        assert len(dock) == stack.config['max_retries'] + 1
        assert all('공차 초과 → 보정' in r['evidence_summary'] for r in dock)
        assert all(r['checkpoints']['accepted'] == 'ACCEPTED' for r in dock)
        assert '보정 예산 소진' in dock[-1]['evidence_summary']
        assert not any('보정 예산 소진' in r['evidence_summary'] for r in dock[:-1])
        by = {r['stage_code']: r for r in rows}
        skipped = STAGES[STAGES.index('MARKER'):STAGES.index('RETURN_HOME')]
        assert all(by[s]['status'] == 'SKIPPED' for s in skipped)
        assert all('피킹 전 실패(정차 공차 초과) 뒤 안전 복귀' in by[s]['evidence_summary']
                   for s in skipped)
        for stage in ('RETURN_HOME', 'RETURN_EXIT'):
            assert by[stage]['status'] == 'COMPLETED'
            assert '안전 복귀: 정차 공차 초과' in by[stage]['evidence_summary']
            assert by[stage]['evidence_detail']['safe_return'] == '정차 공차 초과'
        # 안전 복귀 중(RUNNING)에도 건너뛴 행은 SKIPPED, 지금 행은 안전 복귀로 보인다.
        assert during is not None
        assert during['MARKER']['status'] == 'SKIPPED'
        assert '안전 복귀: 정차 공차 초과' in during['RETURN_HOME']['evidence_summary']
        assert during['RETURN_EXIT']['status'] == 'WAITING'
        assert '안전 복귀: 정차 공차 초과' in during['RETURN_EXIT']['evidence_summary']
    finally:
        stack.close()


def test_unreached_rows_by_order_state():
    """FAILED·UNKNOWN 이면 도달하지 않은 행은 SKIPPED. 진행 중·대기 주문은 그대로 대기 행이다."""
    base = dict(order_id='o', robot_id='pinky1', stage='MOVE_PICKUP', request_id='m1')
    for state, word in (('FAILED', '주문 실패 종결'), ('UNKNOWN', '주문 보류(UNKNOWN)')):
        rows = build_stage_trace(dict(base, state=state, detail='운영자 estop'), [])
        assert rows[0]['status'] == 'BLOCKED'
        assert all(r['status'] == 'SKIPPED' and word in r['evidence_summary'] for r in rows[1:])
        assert not any(r['checkpoints']['requested'] for r in rows[1:])
    for state in ('RUNNING', 'ESTOP', 'PAUSED'):
        rows = build_stage_trace(dict(base, state=state), [])
        assert all(r['status'] == 'WAITING' for r in rows[1:]), state
    # 운영자 완료 기록만 있는 단계는 도달한 것으로 본다.
    order = dict(base, state='FAILED', stage='MARKER', operator_completed=['PICKUP_EXIT'],
                 completed=['MOVE_PICKUP'])
    by = {r['stage_code']: r for r in build_stage_trace(order, [])}
    assert by['PICKUP_EXIT']['status'] == 'COMPLETED'
    assert by['DOCK_PICKUP']['status'] == 'SKIPPED'


def test_seat_safe_return_hides_return_branch():
    """자리 주문이 피킹 전 정차 실패로 안전 복귀 중이면 회수 갈래는 올 수 없어 행을 숨긴다."""
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='RETURN_HOME',
                 request_id='home1', failure='정차 공차 초과',
                 completed=['MOVE_PICKUP', 'PICKUP_EXIT', 'DOCK_PICKUP', 'CORRECT_PICKUP'],
                 customer_declined=False)
    rows = build_stage_trace(order, [], route=SEAT_ROUTE)
    by = {r['stage_code']: r for r in rows}
    assert not set(CUSTOMER_RETURN_STAGES) & set(by)
    assert by['CUSTOMER']['status'] == 'SKIPPED'
    assert by['RETURN_HOME']['status'] == 'RUNNING'
    assert by['RETURN_EXIT']['status'] == 'WAITING'
    assert all('안전 복귀: 정차 공차 초과' in by[s]['evidence_summary']
               for s in ('RETURN_HOME', 'RETURN_EXIT'))


def test_return_kind_order_marks_customer_skipped():
    """회수 주문(kind return)은 관제가 CUSTOMER 를 건너뛴다. 대기 행으로 남기지 않는다."""
    done = [s for s in STAGES if s != 'CUSTOMER']
    order = dict(order_id='r', robot_id='pinky1', state='COMPLETED', stage='RETURN_EXIT',
                 kind='return', completed=done)
    by = {r['stage_code']: r for r in build_stage_trace(order, [])}
    assert len(by) == len(STAGES)
    assert by['CUSTOMER']['status'] == 'SKIPPED' and '생략' in by['CUSTOMER']['evidence_summary']
    assert all(by[s]['status'] == 'COMPLETED' for s in done)
    # 하차 검증 다음 단계는 CUSTOMER 가 아니라 LEAVE_DROPOFF 다.
    assert by['VERIFY_UNLOAD']['checkpoints']['next_stage'] is True
    # 진행 중에도 미리 생략으로 보인다.
    running = dict(order, state='RUNNING', stage='PICK', completed=done[:4], request_id='p1')
    by = {r['stage_code']: r for r in build_stage_trace(running, [])}
    assert by['CUSTOMER']['status'] == 'SKIPPED' and by['LEAVE_DROPOFF']['status'] == 'WAITING'


def test_return_kind_order_through_control(tmp_path):
    """allow_returns 를 켠 관제 실제 흐름(sakim 1b0cb08 kind return): 주문은 COMPLETED, CUSTOMER 행은 생략."""
    from harness import Stack
    from cobot_fleet_control.control_api import ControlAPI
    from cobot_fleet_control.scenario import ScenarioService
    stack = Stack(tmp_path)
    try:
        stack.scenario = ScenarioService(stack.repo, stack.fleet, stack.gateway,
                                         **dict(stack.config, routes=stack.routes,
                                                allow_returns=True),
                                         clock=lambda: stack.now)
        stack.api = ControlAPI(stack.scenario, stack.fleet, stack.gateway)
        stack.adapter.publish = stack.scenario.result
        stack.scenario.armed = True
        stack.scenario.store.set_stock('SHOE42', 10)
        stack.scenario.submit({'order_id': 'order1', 'sku': 'SHOE42', 'route': 'lab_delivery',
                               'kind': 'return'})
        for _ in range(400):
            stack.step()
            if stack.current()['state'] != 'RUNNING' and stack.current()['robot_id']:
                break
        stack.core.on_tasks(stack.api.snapshot())
        assert stack.current()['state'] == 'COMPLETED', stack.current()['detail']
        by = {r['stage_code']: r for r in _trace(stack)['trace']}
        assert by['CUSTOMER']['status'] == 'SKIPPED'
        assert by['UNLOAD']['action'] == 'warehouse_store'
        assert all(r['status'] == 'COMPLETED' for s, r in by.items() if s != 'CUSTOMER')
    finally:
        stack.close()


def test_seat_outcome_on_customer_row():
    """자리 주문 CUSTOMER 행에 결과(PAID·DECLINED·TIMEOUT)를 보인다. 시간 초과는 신발 실은 채 복귀."""
    stages = SEAT_BEFORE_CUSTOMER + ['CUSTOMER']
    cases = (('customer_received', 'PAID', '고객 결제 입력 확인'),
             ('customer_declined', 'DECLINED', '고객 회수 입력 확인'),
             ('customer_timed_out', 'TIMEOUT', '신발 실은 채 복귀'))
    for flag, outcome, word in cases:
        order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='RETURN_HOME',
                     request_id='home1', completed=stages, **{flag: True})
        by = {r['stage_code']: r for r in build_stage_trace(order, [], route=SEAT_ROUTE)}
        row = by['CUSTOMER']
        assert row['evidence_detail']['outcome'] == outcome
        assert word in row['evidence_summary'] and row['evidence_summary'].endswith(outcome)
        assert ('신발 실은 채 복귀' in by['RETURN_HOME']['evidence_summary']) == (
            outcome == 'TIMEOUT')
    # 경로 주문 수령은 RECEIVED 다(감시 기록 scenarios.outcome 과 같다).
    order = dict(order_id='o', state='RUNNING', stage='LEAVE_DROPOFF', completed=['CUSTOMER'],
                 customer_received=True)
    row = next(r for r in build_stage_trace(order, []) if r['stage_code'] == 'CUSTOMER')
    assert row['evidence_detail']['outcome'] == 'RECEIVED'
    # 아직 응답 전이면 결과를 적지 않는다.
    order = dict(order_id='s', robot_id='pinky1', state='RUNNING', stage='CUSTOMER',
                 completed=SEAT_BEFORE_CUSTOMER)
    row = next(r for r in build_stage_trace(order, [], route=SEAT_ROUTE)
               if r['stage_code'] == 'CUSTOMER')
    assert 'outcome' not in (row['evidence_detail'] or {})


def test_safety_requests_are_an_order_note_not_stage_rows():
    """관제 SAFETY hold 는 단계 행이 아니라 주문 메모다. 해제 요청은 운영자 복구 기록으로 알아본다."""
    from cobot_anomaly_monitor.stage_trace import order_notes
    order = dict(order_id='o', robot_id='pinky1', state='ESTOP', stage='PICK', request_id='p1')
    history = [dict(order_id='o', stage='SAFETY', action='hold', target=t, robot_id='pinky1',
                    request_id='h' + t, created_at=5.0 + i)
               for i, t in enumerate(('omx3', 'omx1'))]
    history.append(dict(order_id='o', stage='PICK', request_id='p1', target='omx1',
                        created_at=1.0, state='PENDING'))
    rows = build_stage_trace(order, history)
    assert 'SAFETY' not in {r['stage_code'] for r in rows}
    note = order_notes(order, history)['safety']
    assert [h['target'] for h in note['holds']] == ['omx3', 'omx1']
    assert note['text'] == 'SAFETY hold 2건 (omx1, omx3) · 해제 요청 미관측'
    events = [{'type': 'recovery', 'order_id': 'o', 'at': 9.0,
               'payload': {'decision': 'fail', 'operator': 'kgh'}},
              {'type': 'recovery', 'order_id': 'other', 'at': 9.0,
               'payload': {'decision': 'resume'}}]
    note = order_notes(order, history, control_events=events)['safety']
    assert note['text'].endswith('운영자 복구(fail)로 경로 팔 해제 요청됨')
    assert note['recoveries'] == [{'decision': 'fail', 'operator': 'kgh', 'at': 9.0}]
    assert order_notes(order, history[2:])['safety'] is None


def test_safety_hold_note_through_control_halt_and_recovery(tmp_path):
    """
    관제 실제 흐름. fleet_control_node.halt 처럼 경로 팔에 SAFETY hold 를 보내는 게이트웨이로 정지시킨다.

    추적 응답 notes.safety 에 hold 대상이 보이고, 운영자 fail 복구 뒤 해제 요청됨으로 바뀐다.
    """
    import json
    import uuid
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        original = stack.gateway.halt

        def halt(robot, route, order_id):
            original(robot, route, order_id)
            for target in sorted({route.get(k) for k in ROUTE_ARMS} - {None}):
                stack.gateway.work(dict(request_id=uuid.uuid4().hex, order_id=order_id,
                                        robot_id=robot, target=target, stage='SAFETY',
                                        action='hold'))
        stack.gateway.halt = halt
        stack.order(route='lab_delivery')
        order = stack.until('PICK')
        stack.scenario.interrupt('order1', 'ESTOP', '운영자 estop')
        stack.tick()
        body = _trace(stack)
        assert 'SAFETY' not in {r['stage_code'] for r in body['trace']}
        note = body['notes']['safety']
        assert sorted(h['target'] for h in note['holds']) == ['omx1', 'omx3']
        assert note['text'] == 'SAFETY hold 2건 (omx1, omx3) · 해제 요청 미관측'
        stack.status[order['robot_id']].update(busy=False, state='IDLE')
        stack.tick()
        stack.scenario.recover('order1', 'kgh', '현장 확인', 'fail',
                               dict(arms_safe=True, cargo_reconciled=True, resources_clear=True))
        for row in stack.repo.pending(limit=10000):
            event = json.loads(row['payload'])
            if event.get('type') == 'recovery':
                stack.core.on_task_event(event)
        stack.tick()
        note = _trace(stack)['notes']['safety']
        assert note['text'].endswith('운영자 복구(fail)로 경로 팔 해제 요청됨')
        assert note['recoveries'][-1]['decision'] == 'fail'
    finally:
        stack.close()


def test_arm_node_hint_on_unanswered_arm_row(tmp_path):
    """팔 대상 요청에 결과가 없고 그 팔 노드가 없으면 행 상세에 '팔 노드 없음 (<팔>_adapter 미발견)'."""
    from harness import Stack
    stack = Stack(tmp_path)
    try:
        stack.order(route='lab_delivery')
        stack.until('PICK')
        stack.core.set_arm_nodes({'omx1': False, 'omx3': True})
        pick = next(r for r in _trace(stack)['trace'] if r['stage_code'] == 'PICK')
        assert pick['evidence_detail']['arm_node_missing'] == '팔 노드 없음 (omx1_adapter 미발견)'
        assert '팔 노드 없음 (omx1_adapter 미발견)' in pick['evidence_summary']
        stack.core.set_arm_nodes({'omx1': True})
        pick = next(r for r in _trace(stack)['trace'] if r['stage_code'] == 'PICK')
        assert 'arm_node_missing' not in (pick['evidence_detail'] or {})
    finally:
        stack.close()


def test_dropoff_dock_budget_exhausted_holds_without_marking_pickup():
    """하차 정차 보정 예산 소진은 그 자리 보류다. 상차 정차 행에는 예산 소진을 붙이지 않는다."""
    done = STAGES[:STAGES.index('DOCK_DROPOFF')]
    order = dict(order_id='o', robot_id='pinky1', state='UNKNOWN', stage='DOCK_DROPOFF',
                 detail='정차 공차 초과: 관리자 확인 필요', completed=list(done) + ['DOCK_DROPOFF'])

    def dock(stage, rid, at, xy):
        return dict(order_id='o', stage=stage, request_id=rid, target='vision', created_at=at,
                    state='APPROVED', result={'success': True, 'measured': True,
                                              'data': {'xy_m': xy, 'yaw_deg': 0.0}})
    history = [dock('DOCK_PICKUP', 'p1', 1.0, 0.0), dock('DOCK_DROPOFF', 'd1', 5.0, 0.05),
               dict(order_id='o', stage='CORRECT_DROPOFF', request_id='c1', target='navigation',
                    created_at=6.0, state='APPROVED',
                    result={'success': True, 'measured': True, 'data': {'no_motion': True}}),
               dock('DOCK_DROPOFF', 'd2', 7.0, 0.05)]
    rows = build_stage_trace(order, history)
    pickup = next(r for r in rows if r['stage_code'] == 'DOCK_PICKUP')
    drops = [r for r in rows if r['stage_code'] == 'DOCK_DROPOFF']
    assert '공차' not in pickup['evidence_summary']
    assert drops[0]['evidence_summary'].endswith('공차 초과 → 보정 (관제 보정 요청 기준)')
    assert '공차 초과 → 보정 예산 소진 (관제 실패 사유 기준)' in drops[1]['evidence_summary']
    after = STAGES[STAGES.index('QR'):]
    by = {r['stage_code']: r for r in rows}
    assert all(by[s]['status'] == 'SKIPPED' for s in after)
    tolerance = {'dock_xy_m': 0.03, 'dock_yaw_deg': 15.0}
    rows = build_stage_trace(order, history, dock_tolerance=tolerance)
    pickup = next(r for r in rows if r['stage_code'] == 'DOCK_PICKUP')
    drops = [r for r in rows if r['stage_code'] == 'DOCK_DROPOFF']
    assert pickup['evidence_summary'].endswith('공차 이내')
    assert drops[0]['evidence_summary'].endswith('실측 0.050 m / 0.0° · 공차 초과 → 보정')
    assert '공차 초과 → 보정 예산 소진' in drops[1]['evidence_summary']
    # 공차 값이 숫자가 아니면 비교하지 않는다.
    rows = build_stage_trace(order, history, dock_tolerance={'dock_xy_m': None})
    pickup = next(r for r in rows if r['stage_code'] == 'DOCK_PICKUP')
    assert 'within_tolerance' not in pickup['evidence_detail']
