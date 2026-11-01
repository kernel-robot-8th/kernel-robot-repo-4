# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
생성 타입 시험: colcon build 로 생긴 Python 타입을 import 해서 필드·상수를 본다.

v2 는 v1(주행 순찰 노드의 String 규격)과 값이 같아야 한다. 그래서 state 14종과
명령 6종을 v1 목록과 대조한다. import 가 안 되면 실패다 (건너뛰지 않는다).
"""

from cobot_patrol_interfaces.msg import PatrolCommand, PatrolCommandAck, PatrolState

# v1: cobot_pinky_patrol/pinky_patrol_node_pinky1.py 가 발행하는 state
V1_STATES = {'IDLE', 'STARTING', 'MOVING', 'QUEUEING', 'ARRIVED', 'HOLDING_ZONE',
             'LEAVING_ZONE', 'RETREATING', 'RETURNING', 'IDLE_WAIT', 'DONE', 'STOPPED',
             'FAILED', 'RETRY'}
# v1: patrol_cmd 명령 (start 는 비활성이라 v2 에 넣지 않았다)
V1_OPERATIONS = {'goto', 'zone', 'leave', 'home', 'stop', 'emergency_stop'}


def constants(msg_type, prefix):
    return {getattr(msg_type, n) for n in dir(msg_type) if n.startswith(prefix)}


def test_state_constants_match_v1():
    assert constants(PatrolState, 'STATE_') == V1_STATES


def test_operation_constants_match_v1():
    assert constants(PatrolCommand, 'OP_') == V1_OPERATIONS


def test_patrol_command_fields():
    msg = PatrolCommand(task_id='t1', operation=PatrolCommand.OP_GOTO, points=['P1', 'P2'])
    assert (msg.task_id, msg.operation, list(msg.points)) == ('t1', 'goto', ['P1', 'P2'])


def test_patrol_command_ack_fields():
    msg = PatrolCommandAck(robot_id='pinky1', task_id='t1', accepted=False,
                           reason=PatrolCommandAck.REASON_BUSY)
    assert msg.reason == 'busy'
    assert hasattr(msg, 'header')


def test_patrol_state_fields():
    msg = PatrolState(robot_id='pinky1', state=PatrolState.STATE_MOVING, waypoint=1,
                      detail='P2', task_id='t1', task_finished=False, held_zone='')
    assert set(PatrolState.get_fields_and_field_types()) == {
        'header', 'robot_id', 'state', 'waypoint', 'detail', 'task_id', 'task_finished',
        'held_zone'}
    assert msg.waypoint == 1
