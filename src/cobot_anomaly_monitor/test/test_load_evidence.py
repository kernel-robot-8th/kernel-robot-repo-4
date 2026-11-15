"""실제 팀 시나리오의 VERIFY_LOAD에서 영상·운영자 결합과 실패 경계를 재생한다."""

import json

from cobot_anomaly_monitor.load_evidence import LoadEvidence
from harness import POINTS, ROBOTS, Stack
import pytest


@pytest.fixture
def run(tmp_path):
    stack = Stack(tmp_path)
    join = LoadEvidence(stack.core, POINTS, 'ceiling', 'replay-v1', 'pinky-v1')
    stack.adapter.join = join
    stack.order(route='lab_delivery')
    order = stack.until('VERIFY_LOAD')
    robot = order['robot_id']
    for name in ROBOTS:
        stack.status[name].update(busy=False, central_latched=False)
    stack.status[robot].update(held_zone='A', arrived_zone='A')
    stack.tick()
    for name in ROBOTS:
        x, y = POINTS['ZA'][:2] if name == robot else (-.7, 0)
        stack.core.on_pose(name, x, y, 0)
    yield stack, order['request_id']
    stack.close()


def sample(stack, seq, **changes):
    stack.tick(.25)
    return dict(dict(source_kind='sim_fixture', stream_id='ceiling', stream_epoch='capture1', model_id='pinky-v1',
                     calibration_id='replay-v1', frame_seq=seq, capture_time=stack.wall()-.05,
                     clock_error_sec=.01, marker_state='OK', zones={'ZA': 'LOADED'}), **changes)


def test_frames_delivered_faster_than_clock_error_are_accepted(run):
    # 같은 호스트 전달은 수 ms 다. 오차 0.02 s 보다 빨리 왔다고 미래 프레임으로 버리면 안 된다(11-09 시뮬 vl_2·3).
    stack, rid = run
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        frame = sample(stack, seq, clock_error_sec=.02)
        frame['capture_time'] = stack.wall() - .002
        stack.adapter.on_evidence(frame)
    stack.tick()
    assert 'VERIFY_LOAD' in stack.current()['completed']


def test_frame_clearly_from_the_future_is_rejected(run):
    stack, rid = run
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        frame = sample(stack, seq, clock_error_sec=.02)
        frame['capture_time'] = stack.wall() + .1
        stack.adapter.on_evidence(frame)
    assert stack.store.work(rid)['state'] == 'PENDING'


def test_live_bt_joins_three_unique_frames_and_arm(run):
    stack, rid = run
    assert stack.adapter.confirm_arm(rid, 'operator') == {'pending': True}
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    stack.tick()
    assert 'VERIFY_LOAD' in stack.current()['completed']
    assert stack.current()['stage'] == 'LEAVE_PICKUP'
    with pytest.raises(KeyError):
        stack.adapter.confirm_arm(rid, 'late')


@pytest.mark.parametrize('changes', [
    {'zones': {'ZA': 'EMPTY'}}, {'zones': {'ZA': 'MULTI'}}, {'marker_state': 'LOST'},
    {'capture_time': 0}, {'stream_id': 'wrong'}, {'clock_error_sec': 2},
    {'model_id': 'wrong'}, {'calibration_id': 'wrong'}, {'zones': {'ZB': 'LOADED'}},
])
def test_unusable_evidence_never_completes(run, changes):
    stack, rid = run
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq, **changes))
    assert stack.store.work(rid)['state'] == 'PENDING'


def test_other_robot_missing_and_duplicate_frames(run):
    stack, rid = run
    stack.core.pose.pop('pinky2')
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    assert 'pinky2' in stack.adapter.pending()[0]['wait_reason']
    stack.core.on_pose('pinky2', -.7, 0, 0)
    frame = sample(stack, 3)
    for _ in range(3):
        stack.adapter.on_evidence(frame)
    assert stack.adapter.pending()[0]['evidence_count'] == 1


def test_manual_takeover_is_explicit_and_late_video_does_not_publish(run):
    stack, rid = run
    with pytest.raises(ValueError):
        stack.adapter.approve(rid, 'operator')
    with pytest.raises(ValueError):
        stack.adapter.manual_load(rid, 'operator', '', True, True)
    with pytest.raises(ValueError):
        stack.adapter.manual_load(rid, 'operator', '가림', False, True)
    result = stack.adapter.manual_load(rid, 'operator', '가림, 작업자 적재 확인', True, True)
    assert result['data']['decision'] == 'operator_override'
    stack.adapter.on_evidence(sample(stack, 1))
    with pytest.raises(KeyError):
        stack.adapter.manual_load(rid, 'operator', '늦은 중복', True, True)


def test_epoch_change_clears_old_frames(run):
    stack, rid = run
    for seq in range(2):
        stack.adapter.on_evidence(sample(stack, seq))
    stack.adapter.on_evidence(sample(stack, 0, stream_epoch='capture2'))
    assert stack.adapter.pending()[0]['evidence_count'] == 1
    stack.adapter.on_heartbeat({'session_id': 'new'})
    assert stack.store.work(rid)['state'] == 'EXPIRED_SESSION'


def test_uncertain_publish_cannot_be_reapproved(run):
    stack, rid = run
    def broken(result):
        raise RuntimeError('transport interrupted')
    stack.adapter.publish = broken
    with pytest.raises(RuntimeError):
        stack.adapter.manual_load(rid, 'operator', '실측 확인', True, True)
    assert stack.store.work(rid)['state'] == 'PUBLISH_UNCONFIRMED'
    with pytest.raises(KeyError):
        stack.adapter.manual_load(rid, 'operator', '재시도', True, True)


@pytest.mark.parametrize('updates', [
    {'arrived_zone': None}, {'held_zone': 'B'}, {'busy': True}, {'central_latched': True},
])
def test_target_must_be_arrived_and_stationary(run, updates):
    stack, rid = run
    stack.status['pinky1'].update(updates)
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    assert stack.store.work(rid)['state'] == 'PENDING'


def last_pose_while_driving(stack, robot='pinky1'):
    """실물·시뮬 AMCL 은 움직일 때만 위치를 낸다(update_min_d). 마지막 위치는 정지 전에 온다(11-09 시뮬 vl_1)."""
    stack.status[robot].update(busy=True)
    stack.core.on_speed(robot, 0.1)
    stack.tick()
    stack.core.on_pose(robot, *POINTS['ZA'])
    stack.status[robot].update(busy=False)
    stack.tick()


def still_for(stack, seconds, robot='pinky1', speed=0.0):
    for _ in range(int(seconds / .25)):
        stack.core.on_speed(robot, speed)
        stack.tick(.25)


def test_target_settled_by_odometry_when_amcl_is_silent(run):
    stack, rid = run
    last_pose_while_driving(stack)
    still_for(stack, 1.5)
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.core.on_speed('pinky1', 0.0)
        stack.adapter.on_evidence(sample(stack, seq))
    stack.tick()
    assert 'VERIFY_LOAD' in stack.current()['completed']


@pytest.mark.parametrize('seconds,speed', [(.5, 0.0), (1.5, 0.05)])
def test_target_not_settled_without_a_long_enough_stop(run, seconds, speed):
    stack, rid = run
    last_pose_while_driving(stack)
    still_for(stack, seconds, speed=speed)
    stack.adapter.confirm_arm(rid, 'operator')
    stack.adapter.on_evidence(sample(stack, 0))
    assert stack.store.work(rid)['state'] == 'PENDING'
    assert '정지' in stack.adapter.pending()[0]['wait_reason']


def test_target_not_settled_when_odometry_stops_arriving(run):
    stack, rid = run
    last_pose_while_driving(stack)
    still_for(stack, 1.5)
    for _ in range(3):  # 속도 표본이 끊긴다
        stack.tick(.5)
    stack.adapter.confirm_arm(rid, 'operator')
    stack.adapter.on_evidence(sample(stack, 0))
    assert stack.store.work(rid)['state'] == 'PENDING'


def drive_other(stack, xy, robot='pinky2'):
    """다른 호기가 주행 중이다. 최신 amcl_pose 를 xy 로 둔다."""
    stack.status[robot].update(busy=True)
    stack.tick()
    stack.core.on_pose(robot, xy[0], xy[1], 0)


def three_frames(stack, rid):
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    stack.tick()


def test_other_robot_driving_far_away_does_not_block(run):
    stack, rid = run
    drive_other(stack, (-.7, 0))
    three_frames(stack, rid)
    assert 'VERIFY_LOAD' in stack.current()['completed']


@pytest.mark.parametrize('offset', [.2, .45])
def test_other_robot_driving_inside_half_metre_blocks(run, offset):
    # 0.45 m 는 정지 기준(0.35)으로는 통과지만 주행 중 기준(0.50)으로는 막힌다.
    stack, rid = run
    drive_other(stack, (POINTS['ZA'][0] - offset, POINTS['ZA'][1]))
    three_frames(stack, rid)
    assert stack.store.work(rid)['state'] == 'PENDING'
    assert 'pinky2' in stack.adapter.pending()[0]['wait_reason']


def test_other_robot_driving_with_stale_pose_blocks(run):
    stack, rid = run
    drive_other(stack, (-.7, 0))
    for _ in range(4):  # 상태는 계속 오고 위치만 3초 넘게 멈춘다
        stack.tick(1.0)
    three_frames(stack, rid)
    assert stack.store.work(rid)['state'] == 'PENDING'
    assert 'pinky2' in stack.adapter.pending()[0]['wait_reason']


def test_other_robot_holding_same_zone_blocks_while_driving(run):
    stack, rid = run
    stack.status['pinky2'].update(held_zone='A')
    drive_other(stack, (-.7, 0))
    three_frames(stack, rid)
    assert stack.store.work(rid)['state'] == 'PENDING'


def silence(stack, robot):
    """호기가 기동하지 않았다: 상태도 위치도 오지 않는다."""
    feed = stack.core.on_status
    stack.core.on_status = lambda name, status: None if name == robot else feed(name, status)
    for table in (stack.core.seen, stack.core.pose, stack.core.status):
        table.pop(robot, None)


def test_robot_never_started_does_not_block(run):
    stack, rid = run
    silence(stack, 'pinky3')
    three_frames(stack, rid)
    assert 'VERIFY_LOAD' in stack.current()['completed']


def test_silent_robot_last_seen_near_zone_blocks(run):
    # 상태가 끊긴 호기의 마지막 위치가 구역 0.50 m 안이면 거기 있을 수 있다.
    stack, rid = run
    stack.core.on_pose('pinky3', POINTS['ZA'][0] - .3, POINTS['ZA'][1], 0)
    silence_keep_pose = stack.core.pose['pinky3']
    silence(stack, 'pinky3')
    stack.core.pose['pinky3'] = silence_keep_pose
    three_frames(stack, rid)
    assert stack.store.work(rid)['state'] == 'PENDING'
    assert 'pinky3' in stack.adapter.pending()[0]['wait_reason']


def test_arm_confirmation_lasts_through_the_stage(run):
    # 운영자가 먼저 누르고 영상 3프레임이 10초 뒤에 모여도 다시 누를 필요가 없다(이전: 3초 뒤 삭제).
    stack, rid = run
    stack.adapter.confirm_arm(rid, 'operator')
    confirmed = stack.wall()
    for _ in range(10):
        stack.tick(1.0)
    for robot in ROBOTS:
        stack.core.on_pose(robot, *(POINTS['ZA'] if robot == 'pinky1' else (-.7, 0, 0)))
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    stack.tick()
    assert 'VERIFY_LOAD' in stack.current()['completed']
    result = json.loads(stack.store.work(rid)['result_json'])
    assert result['data']['arm_confirmed_at'] == confirmed


def test_camera_join_is_not_marked_manual_but_takeover_is(run):
    stack, rid = run
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(3):
        stack.adapter.on_evidence(sample(stack, seq))
    data = json.loads(stack.store.work(rid)['result_json'])['data']
    assert data['decision'] == 'camera_and_operator' and data['manual'] is False


def test_operator_takeover_is_marked_manual(run):
    stack, rid = run
    data = stack.adapter.manual_load(rid, 'operator', '가림, 작업자 확인', True, True)['data']
    assert data['decision'] == 'operator_override' and data['manual'] is True


def test_second_result_owner_blocks_manual_takeover(run):
    stack, rid = run
    stack.adapter.exclusive = lambda: False
    with pytest.raises(ValueError):
        stack.adapter.manual_load(rid, 'operator', '실측', True, True)
    assert stack.store.work(rid)['state'] == 'PENDING'


def test_order_trace_reads_live_window_then_reopens_final_decision(run):
    stack, rid = run
    url = '/api/fms/orders/order1/trace'
    def row():
        code, body = stack.console.handle('GET', url, None)
        assert code == 200
        return next(r for r in body['trace'] if r['stage_code'] == 'VERIFY_LOAD')
    stack.adapter.confirm_arm(rid, 'operator')
    for seq in range(2):
        stack.adapter.on_evidence(sample(stack, seq, recorded_epoch='clip-raw', replay_frame=f'{seq}.jpg'))
    pending = row()
    assert '2/3' in pending['evidence_summary'] and '팔 퇴피 확인됨' in pending['evidence_summary']
    assert pending['checkpoints']['accepted'] == 'WAITING'
    assert not pending['checkpoints']['next_stage']
    assert len(pending['evidence_detail']['evidence']) == 2
    assert pending['evidence_detail']['evidence'][1]['recorded_epoch'] == 'clip-raw'
    assert pending['evidence_detail']['evidence'][1]['replay_frame'] == '1.jpg'
    stack.adapter.manual_load(rid, 'operator', '작업자 육안 확인', True, True)
    stack.adapter.on_evidence(sample(stack, 3))
    stack.tick()
    stack.console.adapter = None
    final = row()
    assert final['evidence_detail']['decision'] == 'operator_override'
    assert final['evidence_detail']['note'] == '작업자 육안 확인'
    assert final['checkpoints']['accepted'] == 'ACCEPTED'
    assert final['checkpoints']['next_stage']
