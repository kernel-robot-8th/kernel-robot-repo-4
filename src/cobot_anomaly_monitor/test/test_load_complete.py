"""세 조건 판정 모듈. 각 시험은 해당 조건을 뺀 구현에서 실패해야 한다."""

from cobot_anomaly_monitor.load_complete import LoadComplete
import pytest

T0 = 1000.0
REQUEST = {'request_id': 'r1', 'order_id': 'o1', 'robot_id': 'pinky1', 'stage': 'VERIFY_LOAD',
           'route': {'pickup': 'ZB', 'dropoff': 'ZA'}}
PINKY = [100.0, 100.0, 200.0, 200.0]


class Feed:
    """같은 촬영 프레임에서 나온 구역·상자 메시지를 0.33초 간격으로 넣는다."""

    def __init__(self, judge):
        self.judge, self.now, self.seq = judge, T0, 0

    def frame(self, state='LOADED', pinky=PINKY, boxes=(), marker='OK', zones=True, **changes):
        self.now += 1 / 3
        base = {'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'e1',
                'model_id': 'pinky-v1', 'calibration_id': 'ceil-1', 'frame_seq': self.seq,
                'capture_time': self.now - .05, 'clock_error_sec': .05, 'marker_state': marker}
        base.update(changes)
        self.seq += 1
        if zones:
            self.judge.on_zones(dict(base, zones={'ZB': state, 'ZA': 'NO_ROBOT'}), self.now)
        self.judge.on_boxes(dict(
            base, boxes=[{'name': n, 'bbox': b} for n, b in boxes], truncated=0,
            pinky=[{'name': 'pinky_loaded', 'bbox': pinky, 'zones': ['ZB']}] if pinky else []),
            self.now)

    def arm(self, stage, success=True, at=None, order='o1', robot='pinky1', **data):
        self.judge.on_arm_result({
            'order_id': order, 'robot_id': robot, 'stage': stage, 'source': 'omx1',
            'measured': True, 'finished': True, 'success': success, 'data': data},
            T0 - 5 if at is None else at)

    def released(self, **data):
        self.arm('PICK', at=T0 - 9, arm_safe=True)
        self.arm('LOAD', arm_safe=True, **data)

    def verdict(self, request=REQUEST):
        return self.judge.judge(request, T0, self.now)


@pytest.fixture
def feed():
    return Feed(LoadComplete('ceiling', 'pinky-v1', 'ceil-1'))


def loaded(feed, count=5, **frame):
    for _ in range(count):
        feed.frame(**frame)
    return feed.verdict()


def test_three_conditions_held_for_the_hold_time_pass(feed):
    feed.released()
    out = loaded(feed)
    assert out['verdict'] == 'pass' and out['state'] == 'LOAD_COMPLETE'
    data = out['data']
    assert data['load_present'] is True and data['arm_safe'] is True
    assert data['box_dropped'] is False and data['decision'] == 'vision_judged'
    assert data['unjudged'] is False and data['arm_source'] == 'arm_result'
    assert data['evidence']['frame_seq'] == [0, 1, 2, 3, 4] and data['evidence']['hold_sec'] >= 1.0


def test_zone_frames_without_fresh_box_frames_wait(feed):
    """상자 프레임만 끊기면 그 뒤의 추락을 모른다. 구역이 LOADED 여도 통과시키지 않는다."""
    feed.released()
    assert loaded(feed)['verdict'] == 'pass'
    for _ in range(8):
        feed.now += 1 / 3
        feed.judge.on_zones({
            'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'e1',
            'model_id': 'pinky-v1', 'calibration_id': 'ceil-1', 'frame_seq': feed.seq,
            'capture_time': feed.now - .05, 'clock_error_sec': .05, 'marker_state': 'OK',
            'zones': {'ZB': 'LOADED', 'ZA': 'NO_ROBOT'}}, feed.now)
        feed.seq += 1
    out = feed.verdict()
    assert (out['verdict'], out['reason']) == ('wait', '상자 프레임 끊김')
    assert out['conditions']['no_drop'] is None


def test_loaded_without_any_arm_input_waits(feed):
    out = loaded(feed)
    assert (out['verdict'], out['state'], out['reason']) == ('wait', 'ARM_UNKNOWN', '팔 단계 결과 없음')


@pytest.mark.parametrize('arm, state', [
    (lambda f: f.arm('LOAD', arm_safe=True), 'ARM_UNKNOWN'),  # 잡기 결과 없음
    (lambda f: (f.arm('PICK', arm_safe=True), f.arm('LOAD', at=T0 - 9, arm_safe=True)),
     'ARM_UNKNOWN'),  # 놓기가 잡기보다 먼저
    (lambda f: (f.arm('PICK', at=T0 - 9, arm_safe=True), f.arm('LOAD')), 'ARM_UNKNOWN'),
    (lambda f: (f.arm('PICK', at=T0 - 9, arm_safe=True), f.arm('LOAD', arm_safe=False)),
     'ARM_PRESENT'),
    (lambda f: (f.arm('PICK', at=T0 - 9, arm_safe=True),
                f.arm('LOAD', success=False, arm_safe=True)), 'ARM_UNKNOWN'),
    (lambda f: (f.arm('PICK', at=T0 - 9, order='o2', arm_safe=True), f.arm('LOAD', arm_safe=True)),
     'ARM_UNKNOWN'),  # 다른 주문의 잡기
    (lambda f: (f.arm('PICK', at=T0 - 9, arm_safe=True),
                f.arm('LOAD', robot='pinky2', arm_safe=True)), 'ARM_UNKNOWN'),
    (lambda f: (f.arm('PICK', at=T0 - 9, manual=True), f.arm('LOAD', arm_safe=True)),
     'ARM_UNKNOWN'),  # 사람이 승인한 팔 단계
])
def test_arm_condition_needs_both_stage_results_of_this_order(feed, arm, state):
    arm(feed)
    out = loaded(feed)
    assert out['verdict'] == 'wait' and out['state'] == state


def test_gripper_transition_is_checked_only_when_thresholds_are_set():
    feed = Feed(LoadComplete('ceiling', 'pinky-v1', 'ceil-1', gripper_closed_max=30.0,
                             gripper_open_min=60.0))
    feed.released()
    assert loaded(feed)['reason'] == '그리퍼 값 없음'
    feed.arm('PICK', at=T0 - 9, arm_safe=True, joints={'gripper.pos': 50.0})
    feed.arm('LOAD', arm_safe=True, joints={'gripper.pos': 80.0})
    assert feed.verdict()['reason'] == '잡기 뒤 그리퍼 닫힘 미확인'
    feed.arm('PICK', at=T0 - 9, arm_safe=True, joints={'gripper.pos': 10.0})
    feed.arm('LOAD', arm_safe=True, joints={'gripper.pos': 20.0})
    out = feed.verdict()
    assert (out['state'], out['reason']) == ('ARM_PRESENT', '놓기 뒤 그리퍼 열림 미확인')
    feed.arm('LOAD', arm_safe=True, joints={'gripper.pos': 80.0})
    out = feed.verdict()
    assert out['verdict'] == 'pass' and out['data']['evidence']['arm']['gripper_checked'] is True


def test_open_gripper_with_arm_not_retracted_is_not_safe():
    feed = Feed(LoadComplete('ceiling', 'pinky-v1', 'ceil-1', gripper_closed_max=30.0,
                             gripper_open_min=60.0))
    feed.arm('PICK', at=T0 - 9, arm_safe=True, joints={'gripper.pos': 10.0})
    feed.arm('LOAD', arm_safe=False, joints={'gripper.pos': 80.0})
    assert loaded(feed)['state'] == 'ARM_PRESENT'


def test_hold_time_and_sample_count_are_required(feed):
    feed.released()
    assert loaded(feed, count=3)['reason'] == '적재 표본 수집 중'
    feed.frame()
    assert feed.verdict()['verdict'] == 'pass'


@pytest.mark.parametrize('frame, reason', [
    ({'state': 'EMPTY'}, '구역 상태 EMPTY'),
    ({'state': 'NO_ROBOT'}, '구역 상태 NO_ROBOT'),
    ({'state': 'MULTI'}, '구역 상태 MULTI'),
    ({'marker': 'LOST'}, '구역 상태 모름(마커·영상)'),
])
def test_a_break_in_the_zone_state_drops_the_earlier_run(feed, frame, reason):
    feed.released()
    loaded(feed)
    feed.frame(**frame)
    out = feed.verdict()
    assert out['verdict'] == 'wait' and out['reason'] == reason
    assert loaded(feed, count=3)['verdict'] == 'wait'  # 이전 통과를 붙들지 않는다
    assert loaded(feed, count=1)['verdict'] == 'pass'


def test_stale_stream_does_not_pass(feed):
    feed.released()
    loaded(feed)
    feed.now += 2.5
    out = feed.verdict()
    assert out['verdict'] == 'wait' and out['conditions']['zone'] is None


def test_frames_before_the_request_do_not_count(feed):
    feed.released()
    feed.now = T0 - 3
    loaded(feed)
    assert feed.now < T0 and feed.judge.judge(REQUEST, T0, T0)['verdict'] == 'wait'


def test_arm_and_loaded_at_different_times_do_not_pass(feed):
    # 팔 빠짐은 처음에만 참이고(이후 다른 주문), 실림은 나중에만 보인다.
    feed.released()
    loaded(feed, state='EMPTY')
    other = dict(REQUEST, order_id='o2', request_id='r2')
    assert loaded(feed)['verdict'] == 'pass'
    assert feed.verdict(other)['state'] == 'ARM_UNKNOWN'


@pytest.mark.parametrize('changes', [
    {'stream_id': 'other'}, {'model_id': 'pinky-v0'}, {'calibration_id': 'old'},
    {'source_kind': 'guess'}, {'clock_error_sec': .5}, {'stream_epoch': ''},
])
def test_frames_from_another_source_clear_the_history(feed, changes):
    feed.released()
    loaded(feed)
    feed.frame(**changes)
    out = feed.verdict()
    assert out['verdict'] == 'wait' and out['reason'] == '시각·스트림·모델·보정 불일치'


def test_new_stream_epoch_starts_over(feed):
    feed.released()
    loaded(feed)
    feed.seq = 0
    assert loaded(feed, count=3, stream_epoch='e2')['verdict'] == 'wait'
    assert loaded(feed, count=1, stream_epoch='e2')['verdict'] == 'pass'


def test_moving_box_does_not_pass(feed):
    feed.released()
    for step in range(5):
        feed.frame(pinky=[100.0 + 6 * step, 100.0, 200.0 + 6 * step, 200.0])
    out = feed.verdict()
    assert (out['verdict'], out['reason']) == ('wait', '상자 위치가 움직임')


def test_missing_or_ambiguous_box_position_does_not_pass(feed):
    feed.released()
    assert loaded(feed, pinky=None)['reason'] == '상자 위치 표본 끊김'
    judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1')
    feed = Feed(judge)
    feed.released()
    for _ in range(5):
        feed.frame()
        judge.boxes[-1]['pinky'].append({'bbox': [300.0, 100.0, 400.0, 200.0], 'zones': ['ZB']})
    assert feed.verdict()['reason'] == '상자 위치 표본 끊김'


def test_zone_frames_without_box_frames_do_not_pass(feed):
    feed.released()
    for _ in range(5):
        feed.now += 1 / 3
        feed.judge.on_zones({
            'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'e1',
            'model_id': 'pinky-v1', 'calibration_id': 'ceil-1', 'frame_seq': feed.seq,
            'capture_time': feed.now - .05, 'clock_error_sec': .05, 'marker_state': 'OK',
            'zones': {'ZB': 'LOADED'}}, feed.now)
        feed.seq += 1
    out = feed.verdict()
    assert (out['verdict'], out['reason']) == ('wait', '상자 프레임 없음')


FLOOR = ('box_on_floor', [210.0, 150.0, 250.0, 190.0])


def test_floor_box_in_three_consecutive_frames_is_a_drop(feed):
    feed.released()
    loaded(feed)
    feed.frame(boxes=[FLOOR])
    feed.frame(boxes=[FLOOR])
    out = feed.verdict()
    assert (out['verdict'], out['reason']) == ('wait', '바닥 상자 확인 중')
    feed.frame(state='EMPTY', pinky=None, boxes=[('box_run_over', FLOOR[1])])
    out = feed.verdict()
    assert out['verdict'] == 'drop' and out['state'] == 'BOX_DROPPED'
    data = out['data']
    assert data['box_dropped'] is True and data['load_present'] is False
    assert data['arm_safe'] is True and 'retry_safe' not in data
    assert data['evidence']['names'] == ['box_on_floor', 'box_run_over']
    assert data['evidence']['frame_seq'] == [5, 6, 7]


def test_floor_box_seen_before_the_request_is_not_a_drop(feed):
    feed.released()
    feed.now = T0 - 3
    loaded(feed, count=4, boxes=[FLOOR])
    assert feed.now < T0 and feed.judge.judge(REQUEST, T0, T0)['verdict'] == 'wait'
    feed.now = T0
    assert loaded(feed, count=2, boxes=[FLOOR])['verdict'] == 'wait'


def test_single_floor_frame_is_not_a_drop(feed):
    feed.released()
    loaded(feed)
    feed.frame(boxes=[FLOOR])
    assert feed.verdict()['verdict'] == 'wait'
    assert loaded(feed, count=4)['verdict'] == 'pass'


def test_floor_box_far_from_the_zone_robot_is_ignored(feed):
    feed.released()
    out = loaded(feed, boxes=[('box_on_floor', [700.0, 700.0, 740.0, 740.0])])
    assert out['verdict'] == 'pass'


def test_drop_is_reported_even_while_the_arm_is_unknown(feed):
    out = loaded(feed, boxes=[FLOOR])
    assert out['verdict'] == 'drop' and out['data']['arm_safe'] is False


def test_box_on_the_rim_waits(feed):
    feed.released()
    out = loaded(feed, boxes=[('box_perched_on_rim', [130.0, 130.0, 170.0, 170.0])])
    assert (out['verdict'], out['reason']) == ('wait', '상자 턱 걸림(기준 미정)')


def test_unload_uses_the_same_rules_with_another_table_row(feed):
    request = dict(REQUEST, stage='VERIFY_UNLOAD', route={'pickup': 'ZA', 'dropoff': 'ZB'})
    feed.arm('PICK_DROPOFF', at=T0 - 9, arm_safe=True)
    feed.arm('UNLOAD', arm_safe=True)
    for _ in range(5):
        feed.frame(state='EMPTY')
    data = feed.verdict(request)['data']
    assert data['load_absent'] is True and data['arm_safe'] is True and 'placed' not in data


def test_unknown_stage_or_zone_waits(feed):
    feed.released()
    loaded(feed)
    assert feed.verdict(dict(REQUEST, stage='PICKUP_EXIT'))['verdict'] == 'wait'
    assert feed.verdict(dict(REQUEST, route={}))['verdict'] == 'wait'
    assert feed.verdict(dict(REQUEST, route={'pickup': 'ZC'}))['verdict'] == 'wait'


@pytest.mark.parametrize('stage', ['PICK', 'LOAD'])
def test_fake_arm_result_cannot_authorize_loaded(feed, stage):
    feed.released()
    feed.arm(stage, at=T0 - (9 if stage == 'PICK' else 5), arm_safe=True, fake=True)
    out = loaded(feed)
    assert out['verdict'] == 'wait'
    assert out['reason'] == '팔 단계가 가짜 실행 결과'


@pytest.mark.parametrize('params', [
    {'hold_sec': 0}, {'fresh_sec': float('nan')}, {'gap_sec': -1},
    {'min_frames': 0}, {'drop_frames': True}, {'drop_reach': float('inf')},
    {'allow_fixed_marker': 'yes'}, {'drop_tray_iou_max': 0.0}, {'drop_tray_iou_max': 1.5},
    {'require_tray_marker_absent': 1}, {'min_tray_box_frames': -1},
    {'min_tray_box_frames': True},
])
def test_invalid_judge_parameters_fail_closed(params):
    with pytest.raises(ValueError):
        LoadComplete('ceiling', 'pinky-v1', 'ceil-1', **params)


def test_fixed_marker_restores_zone_state_from_boxes_in_both_orders():
    for boxes_first in (False, True):
        judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1', allow_fixed_marker=True)
        feed = Feed(judge)
        feed.released()
        for seq in range(5):
            feed.now += 1 / 3
            base = {'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'e1',
                    'model_id': 'pinky-v1', 'calibration_id': 'ceil-1', 'frame_seq': seq,
                    'capture_time': feed.now - .05, 'clock_error_sec': .05,
                    'marker_state': 'FIXED'}
            zmsg = dict(base, zones={'ZB': 'NO_ROBOT', 'ZA': 'NO_ROBOT'})
            bmsg = dict(base, zones_frame_seq=seq, truncated=0, boxes=[],
                        pinky=[{'name': 'pinky_loaded', 'confidence': 0.95,
                                'bbox': PINKY, 'zones': ['ZB']}])
            if boxes_first:
                judge.on_boxes(bmsg, feed.now)
                judge.on_zones(zmsg, feed.now)
            else:
                judge.on_zones(zmsg, feed.now)
                judge.on_boxes(bmsg, feed.now)
        assert feed.verdict()['verdict'] == 'pass'


def test_d2_filters_floor_overlapping_tray_inside_anchor_and_preserves_run_over():
    judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1', drop_tray_iou_max=0.5)
    feed = Feed(judge)
    feed.released()
    tray = ('box_on_tray', [120.0, 120.0, 180.0, 180.0])
    overlap_floor = ('box_on_floor', [122.0, 122.0, 178.0, 178.0])
    out = loaded(feed, boxes=[tray, overlap_floor])
    assert out['verdict'] == 'pass'
    # box_run_over 및 앵커 밖 바닥 상자는 그대로 추락으로 잡는다.
    for _ in range(3):
        feed.frame(boxes=[tray, ('box_run_over', [122.0, 122.0, 178.0, 178.0])])
    assert feed.verdict()['verdict'] == 'drop'


def test_arm_source_mismatch_or_route_arm_mismatch_waits(feed):
    feed.arm('PICK', at=T0 - 9, arm_safe=True)
    feed.judge.on_arm_result({
        'order_id': 'o1', 'robot_id': 'pinky1', 'stage': 'LOAD', 'source': 'omx2',
        'measured': True, 'finished': True, 'success': True, 'data': {'arm_safe': True}}, T0 - 5)
    assert loaded(feed)['reason'] == '팔 결과 출처 불일치'
    feed.released()
    req = dict(REQUEST, route={'pickup': 'ZB', 'dropoff': 'ZA', 'pickup_arm': 'omx2'})
    assert feed.verdict(req)['reason'] == '팔 결과 출처 불일치'


def test_tray_marker_and_min_tray_box_guards_block_empty_tray():
    judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1', require_tray_marker_absent=True,
                         min_tray_box_frames=2)
    feed = Feed(judge)
    feed.released()
    assert loaded(feed, tray_markers=[30])['reason'] == '트레이 마커 검출(빈 차 의심)'
    assert loaded(feed, tray_markers=[])['reason'] == '트레이 위 상자 미확인'
    tray = ('box_on_tray', [120.0, 120.0, 180.0, 180.0])
    assert loaded(feed, boxes=[tray], tray_markers=[])['verdict'] == 'pass'


def test_latch_drop_preserves_confirmed_drop_after_trailing_miss():
    judge = LoadComplete('ceiling', 'pinky-v1', 'ceil-1', latch_drop=True)
    feed = Feed(judge)
    feed.released()
    for _ in range(3):
        feed.frame(boxes=[FLOOR])
    feed.frame(boxes=[])
    out = feed.verdict()
    assert out['verdict'] == 'drop' and out['data']['evidence']['frame_seq'] == [0, 1, 2]


def test_arm_session_or_attempt_mismatch_waits(feed):
    feed.judge.on_arm_result({
        'order_id': 'o1', 'robot_id': 'pinky1', 'stage': 'PICK', 'source': 'omx1',
        'session_id': 's1', 'attempt': 1, 'measured': True, 'finished': True,
        'success': True, 'data': {'arm_safe': True}}, T0 - 9)
    feed.judge.on_arm_result({
        'order_id': 'o1', 'robot_id': 'pinky1', 'stage': 'LOAD', 'source': 'omx1',
        'session_id': 's2', 'attempt': 1, 'measured': True, 'finished': True,
        'success': True, 'data': {'arm_safe': True}}, T0 - 5)
    assert loaded(feed)['reason'] == '팔 결과 세션 불일치'
    feed.judge.on_arm_result({
        'order_id': 'o1', 'robot_id': 'pinky1', 'stage': 'LOAD', 'source': 'omx1',
        'session_id': 's1', 'attempt': 2, 'measured': True, 'finished': True,
        'success': True, 'data': {'arm_safe': True}}, T0 - 4)
    req = dict(REQUEST, session_id='s1', attempt=1)
    assert feed.verdict(req)['reason'] == '팔 결과 시도 불일치'


# 팀 팔 어댑터(cobot_manipulation make_result·judge_done, b0dff64)가 실제로 내는 결과 모양.
# session_id·attempt 가 없다. data.arm_safe 는 실행기 값 그대로라 실패 결과에도 참일 수 있다.
def team_arm_result(stage, success=True, source='omx2', data=None):
    if data is None:
        data = {'arm_safe': True, 'end_reason': 'success', 'success_basis': 'yolo',
                'joints': {'gripper.pos': 12.3}, 'model': 'load@v3'}
    return {'request_id': 'rid-' + stage, 'order_id': 'o1', 'robot_id': 'pinky1', 'stage': stage,
            'source': source, 'measured': True, 'finished': True, 'success': success, 'data': data}


def team_request(arm='omx2'):
    return dict(REQUEST, session_id='sess-A', attempt=1,
                route={'pickup': 'ZB', 'dropoff': 'ZA', 'pickup_arm': arm})


def test_team_arm_results_without_session_or_attempt_still_pass(feed):
    feed.judge.on_arm_result(team_arm_result('PICK'), T0 - 9)
    feed.judge.on_arm_result(team_arm_result('LOAD'), T0 - 5)
    for _ in range(5):
        feed.frame()
    assert feed.verdict(team_request())['verdict'] == 'pass'


@pytest.mark.parametrize('data', [{}, {'retry_safe': True}, {'arm_safe': False}])
def test_team_arm_failure_results_hold(feed, data):
    feed.judge.on_arm_result(team_arm_result('PICK'), T0 - 9)
    feed.judge.on_arm_result(team_arm_result('LOAD', success=False, data=data), T0 - 5)
    for _ in range(5):
        feed.frame()
    out = feed.verdict(team_request())
    assert out['verdict'] == 'wait' and out['reason'] == '팔 단계 실패'


def test_team_arm_result_from_other_arm_than_route_holds(feed):
    feed.judge.on_arm_result(team_arm_result('PICK'), T0 - 9)
    feed.judge.on_arm_result(team_arm_result('LOAD'), T0 - 5)
    for _ in range(5):
        feed.frame()
    assert feed.verdict(team_request(arm='omx1'))['reason'] == '팔 결과 출처 불일치'
