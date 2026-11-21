"""
자동 응답 단계 한정(11-21 S8)과 팔 노드 표 시험.

아는 11단계의 답은 11-20 이전 기준판(origin/feature/control-center 404d7ab)과 바이트까지 같아야 한다.
기대값은 그 기준판 어댑터를 같은 입력으로 돌려 얻은 값이다(scratchpad step2/adapter_diff_probe.py).
"""

import json

from cobot_anomaly_monitor.load_complete import JUDGED_DECISION
from cobot_anomaly_monitor.manual_adapter import (
    arm_missing_text, arm_node_warning, arm_presence, AUTO_STAGES, ManualAdapter,
    UNKNOWN_STAGE_REASON)
from cobot_anomaly_monitor.monitor_store import MonitorStore
import pytest

ROUTE = {'pickup': 'ZB', 'dropoff': 'ZC', 'pickup_arm': 'omx2', 'dropoff_arm': 'omx3',
         'lane': 'main'}
POINTS = {'ZB': [0.6, -0.15, -1.5], 'ZC': [-0.5, 0.3, 1.5]}
# 관제 WORK 의 vision·navigation 단계와 대상(origin/sakim scenario_contracts.py:26-41).
KNOWN = {'PICKUP_EXIT': 'vision', 'DOCK_PICKUP': 'vision', 'CORRECT_PICKUP': 'navigation',
         'MARKER': 'vision', 'VERIFY_LOAD': 'vision', 'PATH_EXIT': 'vision',
         'DOCK_DROPOFF': 'vision', 'CORRECT_DROPOFF': 'navigation', 'QR': 'vision',
         'VERIFY_UNLOAD': 'vision', 'RETURN_EXIT': 'vision'}
# 기준판 404d7ab 이 내보낸 결과 바이트(monitor_node._publish_result 의 json.dumps, 키 순서 포함).
# 자세 (0.61, -0.14, -1.48), 지점 ZB·ZC 기준. 값을 바꾸지 말 것: 관제에 가는 답이 바뀐다는 뜻이다.
BASELINE_RAW = {
    'CORRECT_DROPOFF': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "CORRE'
        'CT_DROPOFF", "source": "navigation", "measured": true, "finished": true, "su'
        'ccess": true, "detail": "자동 응답(판정 기준 미적용)", "data": {"no_motion": true, "dec'
        'ision": "auto_unjudged", "unjudged": true, "manual": false, "operator": "aut'
        'o"}}'),
    'CORRECT_PICKUP': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "CORRE'
        'CT_PICKUP", "source": "navigation", "measured": true, "finished": true, "suc'
        'cess": true, "detail": "자동 응답(판정 기준 미적용)", "data": {"no_motion": true, "deci'
        'sion": "auto_unjudged", "unjudged": true, "manual": false, "operator": "auto'
        '"}}'),
    'DOCK_DROPOFF': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "DOCK_'
        'DROPOFF", "source": "vision", "measured": true, "finished": true, "success":'
        ' true, "detail": "자동 응답(판정 기준 미적용)", "data": {"xy_m": 1.1940268003692378, "y'
        'aw_deg": -170.74142294898533, "stopped": true, "base_hold": true, "decision"'
        ': "auto_unjudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'DOCK_PICKUP': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "DOCK_'
        'PICKUP", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "자동 응답(판정 기준 미적용)", "data": {"xy_m": 0.014142135623730944, "'
        'yaw_deg": 1.1459155902616476, "stopped": true, "base_hold": true, "decision"'
        ': "auto_unjudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'MARKER': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "MARKE'
        'R", "source": "vision", "measured": true, "finished": true, "success": true,'
        ' "detail": "자동 응답(판정 기준 미적용)", "data": {"sku": "SHOE42", "decision": "auto_u'
        'njudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'PATH_EXIT': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "PATH_'
        'EXIT", "source": "vision", "measured": true, "finished": true, "success": tr'
        'ue, "detail": "자동 응답(판정 기준 미적용)", "data": {"clear": true, "decision": "auto_'
        'unjudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'PICKUP_EXIT': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "PICKU'
        'P_EXIT", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "자동 응답(판정 기준 미적용)", "data": {"clear": true, "decision": "aut'
        'o_unjudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'QR': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "QR", '
        '"source": "vision", "measured": true, "finished": true, "success": true, "de'
        'tail": "자동 응답(판정 기준 미적용)", "data": {"sku": "SHOE42", "decision": "auto_unjud'
        'ged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'RETURN_EXIT': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "RETUR'
        'N_EXIT", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "자동 응답(판정 기준 미적용)", "data": {"clear": true, "decision": "aut'
        'o_unjudged", "unjudged": true, "manual": false, "operator": "auto"}}'),
    'VERIFY_LOAD': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "VERIF'
        'Y_LOAD", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "자동 응답(판정 기준 미적용)", "data": {"load_present": true, "arm_safe'
        '": true, "decision": "auto_unjudged", "unjudged": true, "manual": false, "op'
        'erator": "auto"}}'),
    'VERIFY_UNLOAD': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "VERIF'
        'Y_UNLOAD", "source": "vision", "measured": true, "finished": true, "success"'
        ': true, "detail": "자동 응답(판정 기준 미적용)", "data": {"placed": true, "load_absent"'
        ': true, "arm_safe": true, "decision": "auto_unjudged", "unjudged": true, "ma'
        'nual": false, "operator": "auto"}}'),
}
JUDGE_RAW = {
    'shadow_wait': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "VERIF'
        'Y_LOAD", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "자동 응답(판정 기준 미적용)", "data": {"load_present": true, "arm_safe'
        '": true, "decision": "auto_unjudged", "unjudged": true, "judge": {"verdict":'
        ' "wait", "state": "WAIT", "reason": "r-wait", "conditions": {"arm": false, "'
        'tray": true}, "waited_sec": 5.0}, "manual": false, "operator": "auto"}}'),
    'enforce_pass': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "VERIF'
        'Y_LOAD", "source": "vision", "measured": true, "finished": true, "success": '
        'true, "detail": "비전 판정 통과", "data": {"load_present": true, "arm_safe": true,'
        ' "decision": "vision_judged", "manual": false, "operator": "auto"}}'),
    'enforce_drop': (
        '{"request_id": "r1", "order_id": "o1", "robot_id": "pinky1", "stage": "VERIF'
        'Y_LOAD", "source": "vision", "measured": true, "finished": true, "success": '
        'false, "detail": "r-drop", "data": {"box_dropped": true, "arm_safe": true, "'
        'decision": "vision_judged", "manual": false, "operator": "auto"}}'),
}


class Judge:
    """정해 둔 순서로 판정을 내는 가짜 판정기."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)

    def judge(self, request, created_at, now):
        verdict = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        data = ({'load_present': True, 'arm_safe': True, 'decision': JUDGED_DECISION}
                if verdict == 'pass' else
                {'box_dropped': True, 'arm_safe': True, 'decision': JUDGED_DECISION}
                if verdict == 'drop' else None)
        return {'verdict': verdict, 'state': verdict.upper(), 'reason': 'r-' + verdict,
                'conditions': {'arm': verdict == 'pass', 'tray': True}, 'data': data}


class Fixture:
    def __init__(self, path, judge=None, mode='off', warn=None):
        self.store = MonitorStore(path / 'm.sqlite3')
        self.sent, self.now, self.seq = [], 1000.0, 0
        self.state = {'pose_x': 0.61, 'pose_y': -0.14, 'pose_yaw': -1.48, 'speed_mps': 0.0}
        self.adapter = ManualAdapter(
            self.store, self.sent.append, ['vision', 'navigation', 'omx1', 'omx2', 'omx3'],
            POINTS, lambda robot: self.state, clock=lambda: self.now,
            auto_targets=['vision', 'navigation'], judge=judge, judge_mode=mode,
            shadow_wait_sec=5.0, max_wait_sec=30.0, warn=warn)
        self.adapter.on_heartbeat({'session_id': 's1'})

    def request(self, stage, target, **extra):
        self.seq += 1
        data = {'request_id': f'r{self.seq}', 'order_id': 'o1', 'robot_id': 'pinky1',
                'stage': stage, 'target': target, 'action': 'x', 'sku': 'SHOE42',
                'quantity': 1, 'attempt': 1, 'route': ROUTE, 'timeout_sec': 300.0,
                'session_id': 's1', 'seq': self.seq, 'issued_at': self.now, 'ttl_sec': 5.0}
        data.update(extra)
        return data, self.adapter.on_request(data)

    def tick(self, seconds=1.0):
        self.now += seconds
        return self.adapter.retry_auto()

    def warnings(self):
        return [dict(row, payload=json.loads(row['payload'])) for row in self.store._rows(
            "SELECT * FROM trace_work_wire WHERE kind='adapter_warning' ORDER BY rowid")]


@pytest.fixture
def fx(tmp_path):
    item = Fixture(tmp_path)
    yield item
    item.store.close()


def published(result):
    """monitor_node._publish_result 가 토픽에 싣는 문자열."""
    return json.dumps(result, ensure_ascii=False)


def test_auto_stages_are_the_control_work_vision_and_navigation_stages():
    from cobot_fleet_control.scenario_contracts import WORK
    work = {stage for stage, (target, _) in WORK.items() if target in ('vision', 'navigation')}
    assert AUTO_STAGES == work == set(KNOWN)
    assert {WORK[stage][0] for stage in KNOWN} == {'vision', 'navigation'}
    assert all(WORK[stage][0] == target for stage, target in KNOWN.items())


@pytest.mark.parametrize('stage', sorted(KNOWN))
def test_known_stage_answer_is_byte_identical_to_the_baseline(fx, stage):
    request, accepted = fx.request(stage, KNOWN[stage])
    assert accepted and len(fx.sent) == 1
    assert published(fx.sent[0]) == BASELINE_RAW[stage]
    row = fx.store.work(request['request_id'])
    assert row['state'] == 'APPROVED' and row['result_json'] == BASELINE_RAW[stage]
    assert fx.warnings() == [] and fx.adapter.pending() == []


def test_known_stage_judge_answers_are_byte_identical_to_the_baseline(tmp_path):
    """그림자 판정 5초 대기 뒤 응답, 강제 판정 통과·추락은 기준판과 같다."""
    shadow = Fixture(tmp_path / 'shadow', judge=Judge(['wait']), mode='shadow')
    shadow.request('VERIFY_LOAD', 'vision')
    for _ in range(4):
        shadow.tick()
    assert shadow.sent == [] and shadow.adapter.pending()[0]['wait_reason'] == 'r-wait'
    shadow.tick()
    assert [published(r) for r in shadow.sent] == [JUDGE_RAW['shadow_wait']]
    shadow.store.close()
    for verdict in ('pass', 'drop'):
        enforce = Fixture(tmp_path / verdict, judge=Judge([verdict]), mode='enforce')
        enforce.request('VERIFY_LOAD', 'vision')
        assert [published(r) for r in enforce.sent] == [JUDGE_RAW['enforce_' + verdict]]
        enforce.store.close()


@pytest.mark.parametrize('stage,target', [('VERIFY_ARRANGE', 'vision'),
                                          ('ALIGN_CHECK', 'navigation'), ('', 'vision')])
def test_unknown_stage_stays_pending_and_is_recorded(tmp_path, stage, target):
    warned = []
    fx = Fixture(tmp_path, warn=warned.append)
    request, accepted = fx.request(stage, target)
    assert accepted and fx.sent == []
    for _ in range(10):
        assert fx.tick() == []
    assert fx.store.work(request['request_id'])['state'] == 'PENDING' and fx.sent == []
    pending = fx.adapter.pending()
    assert len(pending) == 1 and pending[0]['wait_reason'] == UNKNOWN_STAGE_REASON
    assert pending[0]['unknown_stage'] is True
    warnings = fx.warnings()
    assert len(warnings) == 1 and warnings[0]['request_id'] == request['request_id']
    assert warnings[0]['payload']['code'] == 'UNKNOWN_STAGE'
    assert '모르는 단계' in warnings[0]['payload']['detail'] and len(warned) == 1
    fx.store.close()


def test_unknown_stage_can_still_be_answered_by_an_operator(fx):
    """사람 승인 길은 그대로다(현장 콘솔은 읽기 전용이라 실제로는 막혀 있다)."""
    request, _ = fx.request('VERIFY_ARRANGE', 'vision')
    result = fx.adapter.approve(request['request_id'], 'kgh', '현장 확인')
    assert result['success'] is True and result['data'] == {'manual': True, 'operator': 'kgh'}


def test_unknown_stage_without_order_id_is_not_written_to_the_order_wire(fx):
    request, accepted = fx.request('VERIFY_ARRANGE', 'vision', order_id=None)
    assert accepted and fx.sent == [] and fx.warnings() == []


def test_unknown_stage_for_a_manual_only_target_shows_no_auto_reason(fx):
    """자동 대상이 아닌 팔 대상은 원래 사람 승인 대기다. 모르는 단계 문구를 붙이지 않는다."""
    fx.request('PICK', 'omx2')
    assert fx.adapter.pending()[0].get('wait_reason') is None and fx.warnings() == []


@pytest.mark.parametrize('peers,expected_nodes', [
    ([], {'omx1': False, 'omx2': False, 'omx3': False}),
    (['omx3_adapter'], {'omx1': False, 'omx2': False, 'omx3': True}),
    (['omx1_adapter', 'omx2_adapter'], {'omx1': True, 'omx2': True, 'omx3': False}),
    (['arm_adapter'], {'omx1': True, 'omx2': True, 'omx3': True}),
])
def test_arm_presence_per_target(peers, expected_nodes):
    assert arm_presence(peers, ['omx1', 'omx2', 'omx3']) == expected_nodes


def test_arm_node_warning_only_for_a_known_missing_arm():
    nodes = {'omx1': False, 'omx2': False, 'omx3': True}
    assert arm_node_warning({'target': 'omx2'}, nodes) == '팔 노드 없음 (omx2_adapter 미발견)'
    assert arm_missing_text('omx2') == '팔 노드 없음 (omx2_adapter 미발견)'
    assert arm_node_warning({'target': 'omx3'}, nodes) == ''
    assert arm_node_warning({'target': 'vision'}, nodes) == ''
    assert arm_node_warning({'target': 'omx2'}, {}) == ''  # 아직 그래프를 안 읽었으면 모른다
    assert arm_node_warning({'target': None}, nodes) == '' and arm_node_warning(None, nodes) == ''
    # 정지 때 모든 팔에 가는 보류 통지는 답을 기다리는 작업이 아니다
    assert arm_node_warning({'target': 'omx2', 'stage': 'SAFETY'}, nodes) == ''
