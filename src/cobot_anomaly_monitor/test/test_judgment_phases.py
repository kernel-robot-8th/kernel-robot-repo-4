"""판정 국면(phase)별 분류와 재감지 재판정 규칙 시험(11-21)."""

import json

from cobot_anomaly_monitor.judgment import escalated, judge, rejudge
import pytest


def robot(phase, cargo, xy=(0.0, 0.0), driving=False, order='o1'):
    return {'pose_x': xy[0], 'pose_y': xy[1], 'phase': phase, 'cargo_state': cargo,
            'step_seq': 0, 'driving': driving, 'queue_wait': False, 'order_id': order}


def event(name, distance):
    return {'vision_class': name, 'map_x': distance, 'map_y': 0.0}


# (국면, 적재, 감지, 거리) -> (판정, 조치, 범위, 지목)
TABLE = [
    ('PICK', 'LOADING', 'box_perched_on_rim', 0.05, 'LOAD_FAIL_PERCHED', 'PAUSE', 'ROBOT', True),
    # 11-20 전 PICK 바닥 상자는 진로 장애물(전체 정지)이었다. 범위를 좁히지 않는다.
    ('PICK', 'LOADING', 'box_on_floor', 0.30, 'LOAD_FAIL_DROP', 'PAUSE', 'ALL', True),
    ('PICK', 'LOADING', 'box_on_floor', 0.52, 'LANE_OBSTACLE', 'PAUSE', 'ALL', False),
    ('LOADING', 'LOADING', 'box_on_floor', 0.30, 'LOAD_FAIL_DROP', 'PAUSE', 'ROBOT', True),
    ('ARRANGE', 'LOADED', 'box_perched_on_rim', 0.05, 'ARRANGE_FAIL', 'PAUSE', 'ROBOT', True),
    ('ARRANGE', 'LOADED', 'box_on_floor', 0.30, 'ARRANGE_FAIL', 'PAUSE', 'ROBOT', True),
    ('ARRANGE', 'LOADED', 'box_on_floor', 0.52, 'LANE_OBSTACLE', 'PAUSE', 'ALL', False),
    ('HANDOVER', 'LOADED', 'box_perched_on_rim', 0.05, 'CUSTOMER_HANDOVER_PERCHED', 'PAUSE',
     'ROBOT', True),
    ('HANDOVER', 'LOADED', 'box_on_floor', 0.30, 'CUSTOMER_HANDOVER_DROP', 'PAUSE', 'ROBOT', True),
    ('HANDOVER', 'LOADED', 'box_on_floor', 0.52, 'LANE_OBSTACLE', 'PAUSE', 'ALL', False),
    ('HANDOVER', 'LOADED', 'lid_detached', 0.05, 'CUSTOMER_HANDOVER_LID', 'NONE', 'ROBOT', True),
    ('HANDOVER', 'EMPTY_UNVERIFIED', 'box_on_floor', 0.30, 'CUSTOMER_HANDOVER_DROP', 'PAUSE',
     'ROBOT', True),
    ('TRANSIT', 'LOADED', 'box_on_floor', 0.52, 'TRANSIT_DROP', 'PAUSE', 'ALL', True),
    ('RESIDUAL', 'LOADED', 'box_perched_on_rim', 0.05, 'RESIDUAL_PERCHED', 'PAUSE', 'ROBOT', True),
    ('RESIDUAL', 'LOADED', 'box_on_floor', 0.52, 'RESIDUAL_DROP', 'PAUSE', 'ALL', True),
    ('RESIDUAL', 'EMPTY_UNVERIFIED', 'box_perched_on_rim', 0.05, 'RESIDUAL_PERCHED', 'PAUSE',
     'ROBOT', True),
    ('RESIDUAL', 'EMPTY_UNVERIFIED', 'box_on_floor', 0.30, 'RESIDUAL_DROP', 'PAUSE', 'ALL', True),
    ('RESIDUAL', 'EMPTY_UNVERIFIED', 'lid_detached', 0.05, 'LID_OPEN_ANOMALY', 'NONE', 'ROBOT',
     True),
    (None, 'EMPTY', 'box_on_floor', 0.30, 'LANE_OBSTACLE', 'PAUSE', 'ALL', False),
    (None, 'EMPTY', 'box_perched_on_rim', 0.05, 'IGNORED', 'NONE', 'ROBOT', False),
]


@pytest.mark.parametrize('phase,cargo,name,distance,judgment,action,scope,linked', TABLE)
def test_phase_table(phase, cargo, name, distance, judgment, action, scope, linked):
    result = judge(event(name, distance), {'pinky1': robot(phase, cargo)})
    assert (result['judgment'], result['recommended_action'], result['stop_scope']) == (
        judgment, action, scope)
    assert (result['linked_robot_id'] == 'pinky1') is linked


def test_arrange_and_residual_texts_use_the_right_words():
    arrange = judge(event('box_on_floor', 0.3), {'pinky1': robot('ARRANGE', 'LOADED')})
    assert '정리' in arrange['alarm_text'] and '하역' not in arrange['alarm_text']
    suspect = judge(event('box_perched_on_rim', 0.05),
                    {'pinky1': robot('RESIDUAL', 'EMPTY_UNVERIFIED')})
    assert suspect['alarm_text'].startswith('[잔류 의심]') and '상차' not in suspect['alarm_text']
    known = judge(event('box_perched_on_rim', 0.05), {'pinky1': robot('RESIDUAL', 'LOADED')})
    assert known['alarm_text'].startswith('[잔류 화물]')


def test_robot_without_phase_key_keeps_the_old_step_table():
    old = {'pinky1': {'pose_x': 0.0, 'pose_y': 0.0, 'step_seq': 6, 'cargo_state': 'LOADED',
                      'driving': True, 'queue_wait': False, 'order_id': 'o1'}}
    assert judge(event('box_on_floor', 0.3), old)['judgment'] == 'UNLOAD_FAIL'


def test_unverified_robot_counts_for_ambiguity():
    robots = {'pinky1': robot('RESIDUAL', 'EMPTY_UNVERIFIED'),
              'pinky2': robot('TRANSIT', 'LOADED', (0.5, 0.0), True, 'o2')}
    result = judge(event('box_on_floor', 0.25), robots)
    assert (result['judgment'], result['stop_scope']) == ('AMBIGUOUS', 'ALL')


def opened(judgment, action, scope, linked=None, targets=(), phase=''):
    return {'judgment': judgment, 'recommended_action': action, 'stop_scope': scope,
            'linked_robot_id': linked, 'stop_targets_json': json.dumps(list(targets)),
            'robot_phase_at_event': phase}


def fresh(judgment, action, scope, linked, targets):
    return {'judgment': judgment, 'recommended_action': action, 'stop_scope': scope,
            'linked_robot_id': linked, 'linked_order_id': 'o1', 'stop_targets': list(targets),
            'alarm_text': ''}


def test_rejudge_links_an_unlinked_event_and_keeps_the_wider_scope():
    old = opened('LANE_OBSTACLE', 'PAUSE', 'ALL')
    merged = rejudge(old, fresh('LOAD_FAIL_DROP', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1']),
                     'LOAD|LOADING|LOADING')
    assert (merged['judgment'], merged['stop_scope'], merged['linked_robot_id']) == (
        'LOAD_FAIL_DROP', 'ALL', 'pinky1')
    # 전체 정지는 이미 요청했다. 지목 로봇이 생겨도 새 요청은 없다.
    assert merged['stop_targets'] == ['pinky1'] and not escalated(old, merged)


def test_escalation_counts_new_targets_only_for_robot_stops():
    old = opened('LOAD_FAIL_PERCHED', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1'], 'A')
    merged = dict(fresh('LOAD_FAIL_PERCHED', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1', 'pinky2']))
    assert escalated(old, merged)
    assert not escalated(old, dict(merged, stop_targets=['pinky1']))


def test_rejudge_upgrades_ignored_and_reports_escalation():
    old = opened('IGNORED', 'NONE', 'ROBOT')
    merged = rejudge(old, fresh('LOAD_FAIL_PERCHED', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1']),
                     'PICK|PICK|LOADING')
    assert merged['judgment'] == 'LOAD_FAIL_PERCHED' and escalated(old, merged)


def test_rejudge_same_robot_only_when_its_phase_changed():
    old = opened('ARRANGE_FAIL', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1'], 'ARRANGE|ARRANGE|LOADED')
    again = fresh('TRANSIT_DROP', 'PAUSE', 'ALL', 'pinky1', ['pinky1'])
    assert rejudge(old, again, 'ARRANGE|ARRANGE|LOADED') is None
    merged = rejudge(old, again, 'LEAVE_ARRANGE|TRANSIT|LOADED')
    assert (merged['judgment'], merged['stop_scope']) == ('TRANSIT_DROP', 'ALL')
    assert escalated(old, merged)


def test_rejudge_never_narrows_and_never_moves_to_another_robot():
    old = opened('TRANSIT_DROP', 'PAUSE', 'ALL', 'pinky1', ['pinky1'], 'X')
    narrower = rejudge(old, fresh('UNLOAD_FAIL', 'PAUSE', 'ROBOT', 'pinky1', ['pinky1']), 'Y')
    assert narrower['stop_scope'] == 'ALL' and not escalated(old, narrower)
    assert rejudge(old, fresh('TRANSIT_DROP', 'PAUSE', 'ALL', 'pinky2', ['pinky2']), 'Y') is None
    gone = fresh('LANE_OBSTACLE', 'PAUSE', 'ALL', None, [])
    assert rejudge(old, gone, '') is None
    estop = opened('RUN_OVER_COLLISION', 'ESTOP', 'ALL', 'pinky1', ['pinky1'], 'X')
    merged = rejudge(estop, fresh('TRANSIT_DROP', 'PAUSE', 'ALL', 'pinky1', ['pinky1']), 'Y')
    assert merged['recommended_action'] == 'ESTOP'
