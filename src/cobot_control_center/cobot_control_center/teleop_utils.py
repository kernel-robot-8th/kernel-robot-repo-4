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
상세 화면 직접 조종(cmd_vel)의 순수 로직 (ROS 없음).

흐름: 브라우저 → WS /ws/teleop/<robot> (fleet_api_app) → /control_center/teleop_cmd → teleop_node
→ /<robot>/cmd_vel. 화면은 -1~1 비율만 보내고, 실제 속도는 teleop_node 의 최대값으로 바꾼다.

- TeleopGate (teleop_node): 로봇마다 세션 하나. 입력이 timeout 동안 없으면 0 속도를 몇 번 내고 끝낸다.
  끝난 세션 번호는 기억해 두고 다시 받지 않는다 (끊긴 뒤 늦게 온 입력으로 다시 움직이지 않게).
- TeleopStore (fleet_api_node): 이 백엔드가 연 세션(로봇당 하나)과 teleop_node 상태(살아 있는지, 끝낸 이유).
- teleop_block_reason: 조종을 막는 이유. 시작 때는 API 가, 조종 중에는 teleop_node 가 같은 기준으로 본다.
"""

import json
import math
import threading
import time

# 순찰 노드가 이 상태면 관제 작업이 없어도 움직이는 중이다 (web/commands.js BUSY_ROBOT 과 같은 목록).
BUSY_ROBOT = frozenset({'STARTING', 'MOVING', 'QUEUEING', 'WAITING_ZONE', 'ARRIVED',
                        'LEAVING_ZONE', 'RETREATING', 'RETURNING', 'RETRY'})
# 진행 중이거나 결과를 모르는 관제 작업 (web/commands.js ACTIVE_TASK + UNKNOWN_TASK).
ACTIVE_TASK = frozenset({'ACCEPTED', 'SENT', 'RUNNING', 'UNKNOWN'})
# 끝난 세션 번호를 이만큼만 기억한다.
ENDED_KEEP = 50


def _ratio(value):
    """화면 입력 비율. 숫자가 아니거나 NaN·무한이면 0, 범위 밖이면 -1~1 로 자른다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return max(-1.0, min(1.0, value))


def scale_cmd(vx, wz, max_linear, max_angular):
    """화면 비율 (vx, wz) → 속도 ([m/s], [rad/s])."""
    return _ratio(vx) * float(max_linear), _ratio(wz) * float(max_angular)


def active_task(tasks, robot_id):
    """이 로봇의 진행 중·결과 모름 작업 하나 (없으면 None). tasks 는 작업 dict 목록."""
    for task in tasks or []:
        if (isinstance(task, dict) and task.get('robot_id') == robot_id
                and task.get('state') in ACTIVE_TASK):
            return task
    return None


def robot_order(orders, robot_id):
    """이 로봇에 걸린 끝나지 않은 주문 하나 (active_orders 결과에서, 없으면 None)."""
    for order in orders or []:
        if isinstance(order, dict) and order.get('robot_id') == robot_id:
            return order
    return None


def teleop_block_reason(robot, armed, task=None, order=None, route=None, held=None):
    """
    직접 조종을 막는 이유 (막지 않으면 '').

    robot 은 fleet_status 의 로봇 dict (없으면 등록 안 됨). armed 는 '작업 명령 켜기',
    held 는 fleet_control 보류 사유 (holds). 정지·대기일 때만 조종한다 (순찰 노드·Nav2 와 cmd_vel 이 겹치지 않게).
    """
    if not isinstance(robot, dict):
        return '등록되지 않은 로봇'
    if not robot.get('online'):
        return '연결 끊김'
    if not armed:
        return "작업 명령 꺼짐 (화면 위 '작업 명령 켜기' 먼저)"
    extra = robot.get('extra') if isinstance(robot.get('extra'), dict) else {}
    if extra.get('central_latched') is True or held:
        return '정지 잠금 (현장 확인 후 복구 먼저)'
    if route:
        return f'경로 진행 중 {route.get("route_id", "")}'.strip()
    if task:
        return f'작업 중 {task.get("task_id", "")}'.strip()
    if order:
        return f'주문 진행 중 {order.get("order_id", "")}'.strip()
    if robot.get('state') in BUSY_ROBOT:
        return f'로봇 작업 중 ({robot.get("state")})'
    return ''


def json_dict(text):
    """JSON 객체 문자열 → dict (아니면 None)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class TeleopGate:
    """
    teleop_node 의 세션 관리. ROS 콜백(feed·block)과 타이머(tick)가 같은 스레드에서 부른다.

    tick() 이 돌려준 (robot, 선속도, 각속도) 를 그대로 cmd_vel 로 내면 된다.
    """

    def __init__(self, robots, max_linear, max_angular, timeout_sec, stop_repeat):
        self.robots = frozenset(robots)
        self.max_linear = float(max_linear)
        self.max_angular = float(max_angular)
        self.timeout_sec = float(timeout_sec)
        self.stop_repeat = max(1, int(stop_repeat))
        self._sessions = {}   # robot → {'session', 'vx', 'wz', 'last'}
        self._stopping = {}   # robot → 남은 0 속도 횟수
        self._ended = {}      # session → 끝낸 이유 (최근 ENDED_KEEP 개)

    def feed(self, data, now):
        """
        teleop_cmd 한 건. 받아들였으면 '', 버렸으면 이유.

        data: {robot_id, session, vx, wz} 또는 {robot_id, session, stop: true}.
        """
        if not isinstance(data, dict):
            return '형식 오류'
        robot, session = data.get('robot_id'), data.get('session')
        if robot not in self.robots:
            return f'모르는 로봇: {robot}'
        if not isinstance(session, str) or not session:
            return '세션 없음'
        if session in self._ended:
            return f'끝난 세션 ({self._ended[session]})'
        current = self._sessions.get(robot)
        if current is not None and current['session'] != session:
            return '다른 세션이 조종 중'
        if data.get('stop'):
            if current is not None:
                self._end(robot, '운영자 끝냄')
            else:
                self._ended[session] = '운영자 끝냄'
            return ''
        vx, wz = scale_cmd(data.get('vx'), data.get('wz'), self.max_linear, self.max_angular)
        self._sessions[robot] = {'session': session, 'vx': vx, 'wz': wz, 'last': now}
        self._stopping.pop(robot, None)
        return ''

    def block(self, robot, reason):
        """조종 중인 로봇을 막아야 하면 (작업 시작·연결 끊김 등) 세션을 끝낸다. 끝냈으면 True."""
        if robot not in self._sessions:
            return False
        self._end(robot, reason)
        return True

    def end_all(self, reason):
        for robot in list(self._sessions):
            self._end(robot, reason)

    def _end(self, robot, reason):
        session = self._sessions.pop(robot)['session']
        self._ended[session] = reason
        while len(self._ended) > ENDED_KEEP:
            del self._ended[next(iter(self._ended))]
        self._stopping[robot] = self.stop_repeat

    def tick(self, now):
        """이번 주기에 낼 속도 목록 [(robot, 선속도 [m/s], 각속도 [rad/s])]."""
        out = []
        for robot in list(self._sessions):
            session = self._sessions[robot]
            if now - session['last'] > self.timeout_sec:
                self._end(robot, '입력 끊김')
                continue
            out.append((robot, session['vx'], session['wz']))
        for robot in list(self._stopping):
            out.append((robot, 0.0, 0.0))
            self._stopping[robot] -= 1
            if self._stopping[robot] <= 0:
                del self._stopping[robot]
        return out

    def active(self):
        """조종 중인 로봇 → 세션 번호."""
        return {robot: s['session'] for robot, s in self._sessions.items()}

    def state(self):
        """/control_center/teleop_state 에 낼 내용."""
        return {'active': self.active(), 'ended': dict(self._ended),
                'max_linear': self.max_linear, 'max_angular': self.max_angular}


class TeleopStore:
    """
    fleet_api_node 쪽. 이 백엔드가 연 조종 세션(로봇당 하나)과 teleop_node 상태.

    ROS 콜백 스레드가 put_state() 로 넣고, 웹 서버 스레드가 claim()·release()·ended() 를 부른다.
    """

    def __init__(self, stale_sec, clock=time.monotonic):
        self.stale_sec = float(stale_sec)
        self.clock = clock
        self._lock = threading.Lock()
        self._state = {}
        self._received = None
        self._sessions = {}   # robot → session (이 백엔드가 연 것)

    def put_state(self, text):
        data = json_dict(text)
        if data is None or not isinstance(data.get('active'), dict):
            return False
        with self._lock:
            self._state = data
            self._received = self.clock()
        return True

    def online(self):
        with self._lock:
            return self._received is not None and self.clock() - self._received <= self.stale_sec

    def ended(self, session):
        """teleop_node 가 이 세션을 끝냈으면 그 이유 (아니면 None)."""
        with self._lock:
            ended = self._state.get('ended')
            return ended.get(session) if isinstance(ended, dict) else None

    def claim(self, robot, session):
        """로봇당 한 화면만 조종한다. 잡았으면 True."""
        with self._lock:
            if robot in self._sessions:
                return False
            self._sessions[robot] = session
            return True

    def release(self, robot, session):
        with self._lock:
            if self._sessions.get(robot) == session:
                del self._sessions[robot]

    def session(self, robot):
        with self._lock:
            return self._sessions.get(robot)

    def sessions(self):
        with self._lock:
            return dict(self._sessions)

    def health(self):
        """/api/health 에 싣는 값. teleop: 조종 중인 로봇 목록, teleop_limits: 최대 속도."""
        online = self.online()
        with self._lock:
            state = dict(self._state)
            driving = sorted(self._sessions)
        limits = ({'max_linear': state.get('max_linear'), 'max_angular': state.get('max_angular')}
                  if online else None)
        return {'teleop_online': online, 'teleop': driving, 'teleop_limits': limits}
