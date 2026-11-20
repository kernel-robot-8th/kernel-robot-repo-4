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
팔 노드 설정·실행기 정보 (ROS 없는 순수 로직).

ArmStatus 에는 백엔드 종류·보드 탐지·모델·쉬는 자세를 실을 칸이 없다 (msg 를 바꾸지 않는다).
그래서 /manipulation/<omx_n>/info 로 String JSON 을 따로 낸다. 관제는 이것으로 켜기가 안 되는
이유(backend=none, 보드 없음, 실행기 고장)와 작업별 모델·버전, 쉬는 자세 차이를 보여 준다.
"""

import json

INFO_VERSION = 1
# 실행기 ready 에서 받아 두는 칸 (omx_fleet_worker.py 맨 위 설명)
WORKER_KEYS = ('actions', 'models', 'rest_pose', 'safe_tol')


def worker_info_from_ready(event):
    """실행기 ready 이벤트에서 관제에 보일 칸만 골라 형식을 확인한다. 틀린 칸은 버린다."""
    info = {}
    actions = event.get('actions')
    if isinstance(actions, list):
        info['actions'] = [str(a) for a in actions]
    models = event.get('models')
    if isinstance(models, dict):
        info['models'] = {str(k): v for k, v in models.items() if isinstance(v, dict)}
    rest = event.get('rest_pose')
    if isinstance(rest, dict):
        info['rest_pose'] = {str(k): float(v) for k, v in rest.items() if _number(v)}
    if _number(event.get('safe_tol')):
        info['safe_tol'] = float(event['safe_tol'])
    return info


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def make_info(arm_id, interface_arm_id, boot_id, backend, ready, worker, detect, power, dead,
              now, torque=None):
    """
    팔 노드 정보 토픽 한 건.

    worker: 마지막 실행기 ready 정보 (끈 뒤에도 남긴다: 어떤 모델로 켜졌었는지 보이게).
    ready: 지금 실행기가 떠서 일을 받을 수 있는지.
    detect: (상태, 이유, 포트) — arm_registry_utils.detect 결과.
    torque: 실행기가 없을 때 모터에서 읽은 토크 ({'enabled', 'motors', 'errors', 'at'}), 안 쟀으면 None.
    """
    state, reason, port = detect
    return {
        'v': INFO_VERSION,
        'arm_id': arm_id,
        'interface_arm_id': interface_arm_id,
        'boot_id': boot_id,
        'backend': backend,
        'detect': {'state': state, 'reason': reason, 'port': port},
        'power': power,
        'worker': dict(worker or {}, ready=bool(ready)),
        'dead': dead or '',
        'torque': torque,
        'at': now,
    }


def info_changed(prev, cur):
    """시각(at) 을 뺀 내용이 바뀌었는지."""
    if prev is None:
        return True
    strip = {k: v for k, v in prev.items() if k != 'at'}
    return strip != {k: v for k, v in cur.items() if k != 'at'}


def encode(info):
    """한글을 그대로 담은 JSON 문자열."""
    return json.dumps(info, ensure_ascii=False, sort_keys=True)
