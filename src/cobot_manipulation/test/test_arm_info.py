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

"""팔 노드 info 토픽 내용 (arm_info_utils)."""

import json

from cobot_manipulation import arm_info_utils as info
from cobot_manipulation.arm_backend_utils import make_backend


def make(**overrides):
    args = {'arm_id': 'omx1', 'interface_arm_id': 'omx_1', 'boot_id': 'b1', 'backend': 'worker',
            'ready': True, 'worker': {'actions': ['pick']},
            'detect': ('READY', '보드 확인', '/dev/x'), 'power': 'ARMED', 'dead': '', 'now': 10.0}
    args.update(overrides)
    return info.make_info(**args)


def test_make_info_fields():
    got = make()
    assert got['v'] == info.INFO_VERSION and got['arm_id'] == 'omx1'
    assert got['interface_arm_id'] == 'omx_1' and got['backend'] == 'worker'
    assert got['detect'] == {'state': 'READY', 'reason': '보드 확인', 'port': '/dev/x'}
    assert got['worker'] == {'actions': ['pick'], 'ready': True}
    assert got['power'] == 'ARMED' and got['dead'] == '' and got['at'] == 10.0


def test_make_info_without_worker_and_none_dead():
    got = make(worker=None, ready=False, dead=None, detect=(None, '', None))
    assert got['worker'] == {'ready': False} and got['dead'] == ''
    assert got['detect'] == {'state': None, 'reason': '', 'port': None}


def test_info_changed_ignores_time():
    first = make(now=1.0)
    assert info.info_changed(None, first)
    assert not info.info_changed(first, make(now=99.0))
    assert info.info_changed(first, make(power='DISARMED'))
    assert info.info_changed(first, make(dead='실행기가 끝남'))


def test_worker_info_from_ready_keeps_only_valid_fields():
    got = info.worker_info_from_ready({
        'event': 'ready', 'joints': {'a.pos': 1.0}, 'actions': ['pick', 'load'],
        'models': {'pick': {'bundle': 'omx_pick_za', 'version': 'v1'}, 'bad': 3},
        'rest_pose': {'shoulder_pan': 1, 'gripper': 2.5, 'x': 'no', 'y': True},
        'safe_tol': 3})
    assert got == {'actions': ['pick', 'load'],
                   'models': {'pick': {'bundle': 'omx_pick_za', 'version': 'v1'}},
                   'rest_pose': {'shoulder_pan': 1.0, 'gripper': 2.5}, 'safe_tol': 3.0}
    assert info.worker_info_from_ready({'event': 'ready', 'actions': 'pick',
                                        'rest_pose': None, 'safe_tol': '3'}) == {}


def test_encode_keeps_korean():
    text = info.encode(make(dead='실행기 오류'))
    assert '실행기 오류' in text and json.loads(text)['dead'] == '실행기 오류'


def test_backends_start_with_empty_info_and_fake_marks_itself():
    none = make_backend('none', 1.0)
    assert none.worker_info == {}
    fake = make_backend('fake', 1.0)
    fake.attach('/dev/x', 0.0)
    assert fake.worker_info == {'fake': True}
