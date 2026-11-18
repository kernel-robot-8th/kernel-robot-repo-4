"""실제 팀 시나리오의 VERIFY_LOAD 에 세 조건 판정을 붙여 off·shadow·enforce 를 재생한다."""

from cobot_anomaly_monitor.load_complete import LoadComplete
from cobot_anomaly_monitor.load_evidence import LoadEvidence
from harness import POINTS, ROBOTS, Stack
import pytest

PINKY = [100.0, 100.0, 200.0, 200.0]
FLOOR = {'name': 'box_on_floor', 'bbox': [210.0, 150.0, 250.0, 190.0]}


class Run:
    def __init__(self, path, mode):
        self.stack = stack = Stack(path)
        stack.order(route='lab_delivery')
        order = stack.until('VERIFY_LOAD')
        self.rid, self.robot, self.order_id = order['request_id'], order['robot_id'], 'order1'
        for name in ROBOTS:
            stack.status[name].update(busy=False, central_latched=False)
        stack.status[self.robot].update(held_zone='A', arrived_zone='A')
        stack.tick()
        for name in ROBOTS:
            x, y = POINTS['ZA'][:2] if name == self.robot else (-.7, 0)
            stack.core.on_pose(name, x, y, 0)
        self.judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1')
        adapter = stack.adapter
        adapter.judge, adapter.judge_mode, adapter.auto = self.judge, mode, {'vision'}
        adapter.attribute = LoadEvidence(stack.core, POINTS, '', '', '').attribution
        self.seq = 0

    def arm(self, **load):
        for stage, data in (('PICK', {'arm_safe': True}), ('LOAD', load or {'arm_safe': True})):
            self.judge.on_arm_result({
                'order_id': self.order_id, 'robot_id': self.robot, 'stage': stage,
                'source': 'omx1', 'measured': True, 'finished': True, 'success': True,
                'data': data}, self.stack.wall())
            self.stack.tick(.1)

    def frames(self, count=5, state='LOADED', boxes=()):
        """프레임을 넣을 때마다 어댑터가 다시 시도한다(노드에서는 1초 타이머가 한다)."""
        sent = []
        for _ in range(count):
            self.stack.tick(.3)
            now = self.stack.wall()
            base = {'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'e1',
                    'model_id': 'pinky-v1', 'calibration_id': 'ceil-1', 'frame_seq': self.seq,
                    'capture_time': now - .05, 'clock_error_sec': .05, 'marker_state': 'OK'}
            self.seq += 1
            self.judge.on_zones(dict(base, zones={'ZA': state}), now)
            self.judge.on_boxes(dict(base, boxes=list(boxes), truncated=0, pinky=[
                {'name': 'pinky_loaded', 'bbox': PINKY, 'zones': ['ZA']}]), now)
            sent += self.stack.adapter.retry_auto()
        return sent

    def work(self):
        return self.stack.store.work(self.rid)


@pytest.fixture
def make(tmp_path):
    runs = []

    def build(mode):
        runs.append(Run(tmp_path, mode))
        return runs[-1]
    yield build
    for run in runs:
        run.stack.close()


def test_enforce_answers_once_when_all_three_conditions_hold(make):
    run = make('enforce')
    run.arm()
    (result,) = run.frames()
    data = result['data']
    assert result['success'] is True and result['source'] == 'vision'
    assert data['load_present'] is True and data['arm_safe'] is True
    assert data['box_dropped'] is False and data['decision'] == 'vision_judged'
    assert data['manual'] is False and data['unjudged'] is False and data['operator'] == 'auto'
    run.stack.tick()
    assert 'VERIFY_LOAD' in run.stack.current()['completed']
    assert run.frames() == []


def test_enforce_holds_the_answer_without_arm_results(make):
    run = make('enforce')
    assert run.frames(8) == [] and run.work()['state'] == 'PENDING'
    (pending,) = run.stack.adapter.pending()
    assert pending['wait_reason'] == '팔 단계 결과 없음' and pending['judge']['state'] == 'ARM_UNKNOWN'
    assert pending['arm_checked'] is False
    assert pending['judge_mode'] == 'enforce'
    run.stack.tick()
    assert run.stack.current()['stage'] == 'VERIFY_LOAD'


def test_enforce_holds_the_answer_while_the_zone_is_empty(make):
    run = make('enforce')
    run.arm()
    assert run.frames(8, state='EMPTY') == []
    pending = run.stack.adapter.pending()[0]
    assert pending['wait_reason'] == '구역 상태 EMPTY' and pending['arm_checked'] is True


def test_enforce_holds_the_answer_when_the_robot_is_not_at_the_zone(make):
    run = make('enforce')
    run.arm()
    run.stack.status[run.robot].update(held_zone=None)
    assert run.frames(8) == []
    assert run.stack.adapter.pending()[0]['wait_reason'] == f'{run.robot} 상차 도착·정지 미확인'


def test_enforce_sends_a_failure_result_when_a_box_drops(make):
    run = make('enforce')
    run.arm()
    (result,) = run.frames(3, boxes=[FLOOR])
    assert result['success'] is False and result['detail'] == '상자 추락 감지'
    data = result['data']
    assert data['box_dropped'] is True and 'retry_safe' not in data
    assert data['manual'] is False and data['decision'] == 'vision_judged'
    run.stack.tick()
    assert run.stack.current()['state'] == 'UNKNOWN'  # 판단은 관제가 한다: 지금은 주문 중단


def test_shadow_keeps_the_auto_answer_and_carries_the_verdict(make):
    run = make('shadow')
    run.arm()
    (result,) = run.frames()
    data = result['data']
    assert result['success'] is True and data['decision'] == 'auto_unjudged'
    assert data['unjudged'] is True and data['load_present'] is True and data['arm_safe'] is True
    assert data['judge']['verdict'] == 'pass' and data['judge']['state'] == 'LOAD_COMPLETE'
    run.stack.tick()
    assert 'VERIFY_LOAD' in run.stack.current()['completed']


def test_shadow_answers_after_the_wait_even_when_the_verdict_never_settles(make):
    run = make('shadow')
    assert run.frames(10) == []  # 3초: 아직 기다린다
    (result,) = run.frames(10)
    judge = result['data']['judge']
    assert result['success'] is True and result['data']['decision'] == 'auto_unjudged'
    assert judge['verdict'] == 'wait' and judge['reason'] == '팔 단계 결과 없음'
    assert judge['waited_sec'] >= 5.0


def test_shadow_does_not_turn_a_drop_into_a_failure(make):
    run = make('shadow')
    run.arm()
    (result,) = run.frames(3, boxes=[FLOOR])
    assert result['success'] is True and result['data']['judge']['verdict'] == 'drop'


def test_off_answers_at_once_without_looking_at_the_judge(make):
    run = make('off')
    (result,) = run.stack.adapter.retry_auto()
    assert result['data']['decision'] == 'auto_unjudged' and 'judge' not in result['data']


def test_other_vision_stages_keep_the_plain_auto_answer(make):
    run = make('enforce')
    sent, publish = [], run.stack.adapter.publish
    run.stack.adapter.publish = lambda result: (sent.append(result), publish(result))
    run.arm()
    run.frames()
    for _ in range(20):
        run.stack.step()  # 다음 주행 단계를 끝내면 출구 확인 요청이 온다
        if len(sent) > 1:
            break
    assert [(r['stage'], r['data']['decision']) for r in sent] == [
        ('VERIFY_LOAD', 'vision_judged'), ('PATH_EXIT', 'auto_unjudged')]


def test_unknown_judge_mode_is_refused(tmp_path):
    from cobot_anomaly_monitor.manual_adapter import ManualAdapter
    with pytest.raises(ValueError):
        ManualAdapter(None, None, [], {}, None, judge=object(), judge_mode='maybe')


def test_attribution_failure_keeps_drop_evidence_without_sending_failure(make):
    run = make('enforce')
    run.arm()
    run.stack.status[run.robot].update(held_zone=None)
    assert run.frames(3, boxes=[FLOOR]) == []
    judged = run.stack.adapter.judged[run.rid]
    assert judged['verdict'] == 'wait' and judged['data'] is None
    assert judged['suppressed']['verdict'] == 'drop'
    assert judged['suppressed']['data']['evidence']['frame_seq'] == [0, 1, 2]
    rows = run.stack.store.wire_page(run.order_id, 0)
    assert any(row['kind'] == 'judge_suppressed' for row in rows['events'])


def test_long_enforce_hold_sets_operator_attention_and_records_timeout(make):
    run = make('enforce')
    run.stack.adapter.max_wait_sec = 1.0
    assert run.frames(5) == []
    pending = run.stack.adapter.pending()[0]
    assert pending['operator_attention'] is True
    rows = run.stack.store.wire_page(run.order_id, 0)
    assert sum(row['kind'] == 'judge_hold_timeout' for row in rows['events']) == 1
