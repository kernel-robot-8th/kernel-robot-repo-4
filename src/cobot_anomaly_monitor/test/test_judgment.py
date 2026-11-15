"""판정표 시험. 판정이 뒤집히면 실패해야 한다."""

from cobot_anomaly_monitor.judgment import is_duplicate, judge


def robot(xy, step=0, cargo='EMPTY', driving=False, queue_wait=False, order='o1'):
    return {'pose_x': xy[0], 'pose_y': xy[1], 'step_seq': step, 'cargo_state': cargo,
            'driving': driving, 'queue_wait': queue_wait, 'order_id': order}


def event(name, xy):
    x, y = xy if xy else (None, None)
    return {'vision_class': name, 'map_x': x, 'map_y': y}


def test_perched_while_loading_blocks_that_robot():
    result = judge(event('box_perched_on_rim', (0.62, 0.5)),
                   {'pinky1': robot((0.6, 0.5), 3, 'LOADING')})
    assert result['judgment'] == 'LOAD_FAIL_PERCHED'
    assert result['linked_robot_id'] == 'pinky1' and result['linked_order_id'] == 'o1'
    assert result['recommended_action'] == 'PAUSE' and result['stop_targets'] == ['pinky1']
    assert result['stop_scope'] == 'ROBOT'


def test_perched_while_driving_is_transit():
    robots = {'pinky1': robot((0, 0), 4, 'LOADED', True)}
    result = judge(event('box_perched_on_rim', (0.1, 0)), robots)
    assert result['judgment'] == 'TRANSIT_PERCHED' and result['stop_scope'] == 'ROBOT'


def test_perched_while_unloading_is_unload_fail():
    robots = {'pinky1': robot((0, 0), 6, 'UNLOADING')}
    result = judge(event('box_perched_on_rim', (0.1, 0)), robots)
    assert result['judgment'] == 'UNLOAD_FAIL' and result['stop_scope'] == 'ROBOT'


def test_floor_near_loaded_driver_is_transit_drop_and_stops_everyone():
    robots = {'pinky1': robot((0, 0), 4, 'LOADED', True),
              'pinky2': robot((2, 2), 1, 'EMPTY', True, order='o2'),
              'pinky3': robot((3, 3))}
    result = judge(event('box_on_floor', (0.3, 0)), robots)
    assert result['judgment'] == 'TRANSIT_DROP' and result['linked_robot_id'] == 'pinky1'
    assert result['recommended_action'] == 'PAUSE' and result['stop_scope'] == 'ALL'
    assert result['stop_targets'] == ['pinky1']


def test_floor_while_loading_stops_only_that_robot():
    robots = {'pinky1': robot((0, 0), 3, 'LOADING'), 'pinky2': robot((2, 2), 1, driving=True)}
    result = judge(event('box_on_floor', (0.3, 0)), robots)
    assert result['judgment'] == 'LOAD_FAIL_DROP' and result['stop_targets'] == ['pinky1']
    assert result['stop_scope'] == 'ROBOT'


def test_floor_while_unloading_is_unload_fail():
    robots = {'pinky1': robot((0, 0), 6, 'UNLOADING')}
    result = judge(event('box_on_floor', (0.3, 0)), robots)
    assert result['judgment'] == 'UNLOAD_FAIL' and result['stop_scope'] == 'ROBOT'


def test_floor_with_only_empty_robots_is_lane_obstacle_and_stops_everyone():
    robots = {'pinky1': robot((0, 0), 7, 'EMPTY', True)}
    result = judge(event('box_on_floor', (0.1, 0)), robots)
    assert result['judgment'] == 'LANE_OBSTACLE' and result['linked_robot_id'] is None
    assert result['recommended_action'] == 'PAUSE' and result['stop_scope'] == 'ALL'
    assert result['stop_targets'] == []


def test_lane_obstacle_needs_no_robot_at_all():
    result = judge(event('box_on_floor', (0.1, 0)), {})
    assert result['judgment'] == 'LANE_OBSTACLE' and result['linked_order_id'] is None
    assert result['recommended_action'] == 'PAUSE' and result['stop_scope'] == 'ALL'


def test_floor_far_from_loaded_robot_is_not_blamed_on_it():
    robots = {'pinky1': robot((0, 0), 4, 'LOADED', True)}
    assert judge(event('box_on_floor', (2.0, 0)), robots)['judgment'] == 'LANE_OBSTACLE'


def test_two_loaded_robots_in_range_are_not_guessed():
    robots = {'pinky1': robot((0, 0), 4, 'LOADED', True),
              'pinky2': robot((0.4, 0), 4, 'LOADED', True)}
    result = judge(event('box_on_floor', (0.2, 0)), robots)
    assert result['judgment'] == 'AMBIGUOUS' and result['linked_robot_id'] is None
    assert result['recommended_action'] == 'PAUSE' and result['stop_scope'] == 'ALL'
    assert sorted(result['stop_targets']) == ['pinky1', 'pinky2']


def test_drop_beside_a_docked_robot_names_that_robot_and_stops_everyone():
    robots = {'pinky1': robot((0, 0), 5, 'LOADED', False)}
    result = judge(event('box_on_floor', (0.2, 0)), robots)
    assert result['judgment'] == 'TRANSIT_DROP' and result['stop_targets'] == ['pinky1']
    assert result['stop_scope'] == 'ALL'


def test_ambiguous_drop_records_only_the_nearby_loaded_robots():
    robots = {'pinky1': robot((0, 0), 5, 'LOADED', False),
              'pinky2': robot((0.4, 0), 3, 'LOADING', False),
              'pinky3': robot((3, 3), 1, 'EMPTY', True)}
    result = judge(event('box_on_floor', (0.2, 0)), robots)
    assert result['judgment'] == 'AMBIGUOUS' and result['stop_scope'] == 'ALL'
    assert sorted(result['stop_targets']) == ['pinky1', 'pinky2']


def test_perched_between_two_loaded_robots_is_held_without_stop():
    robots = {'pinky1': robot((0, 0), 3, 'LOADING'), 'pinky2': robot((0.4, 0), 3, 'LOADING')}
    result = judge(event('box_perched_on_rim', (0.2, 0)), robots)
    assert result['judgment'] == 'AMBIGUOUS'
    assert result['recommended_action'] == 'NONE' and result['stop_scope'] == 'ROBOT'


def test_run_over_needs_a_moving_robot():
    still = {'pinky1': robot((0, 0), 3, 'LOADING')}
    moving = {'pinky1': robot((0, 0), 4, 'LOADED', True)}
    assert judge(event('box_run_over', (0.05, 0)), still)['judgment'] == 'IGNORED'
    result = judge(event('box_run_over', (0.05, 0)), moving)
    assert result['judgment'] == 'RUN_OVER_COLLISION'
    assert result['recommended_action'] == 'ESTOP' and result['stop_targets'] == ['pinky1']
    assert result['stop_scope'] == 'ALL'


def test_robot_waiting_in_queue_slot_is_not_blamed_for_run_over():
    waiting = {'pinky1': robot((0, 0), 1, 'EMPTY', True, queue_wait=True)}
    assert judge(event('box_run_over', (0.05, 0)), waiting)['judgment'] == 'IGNORED'


def test_robot_waiting_in_queue_slot_is_covered_by_the_full_stop():
    robots = {'pinky1': robot((0, 0), 4, 'LOADED', True),
              'pinky2': robot((2, 2), 1, 'EMPTY', True, queue_wait=True)}
    result = judge(event('box_on_floor', (0.3, 0)), robots)
    assert result['stop_scope'] == 'ALL' and result['stop_targets'] == ['pinky1']


def test_lid_detached_warns_without_stop():
    result = judge(event('lid_detached', (0.1, 0)), {'pinky1': robot((0, 0), 3, 'LOADING')})
    assert result['judgment'] == 'LID_OPEN_ANOMALY' and result['stop_targets'] == []
    assert result['recommended_action'] == 'NONE' and result['stop_scope'] == 'ROBOT'


def test_no_position_is_not_attributed():
    result = judge(event('box_on_floor', None), {'pinky1': robot((0, 0), 4, 'LOADED', True)})
    assert result['judgment'] == 'NO_POSITION' and result['linked_robot_id'] is None


def test_unknown_class_is_ignored():
    assert judge(event('box_on_tray', (0, 0)), {})['judgment'] == 'IGNORED'


def test_robot_without_pose_is_skipped():
    robots = {'pinky1': {'step_seq': 4, 'cargo_state': 'LOADED', 'driving': True}}
    assert judge(event('box_on_floor', (0, 0)), robots)['judgment'] == 'LANE_OBSTACLE'


def test_same_box_seen_again_is_merged():
    opened = [{'vision_class': 'box_on_floor', 'map_x': 1.0, 'map_y': 1.0, 'last_seen': 100.0}]
    assert is_duplicate(event('box_on_floor', (1.1, 1.0)), opened, 105.0) is opened[0]
    assert is_duplicate(event('box_on_floor', (2.0, 1.0)), opened, 105.0) is None
    assert is_duplicate(event('box_on_floor', (1.1, 1.0)), opened, 200.0) is None
    assert is_duplicate(event('lid_detached', (1.1, 1.0)), opened, 105.0) is None
    assert is_duplicate(event('box_on_floor', None), opened, 105.0) is None
