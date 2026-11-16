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
팔 동작 백엔드 (ROS 없는 순수 로직).

노드는 '요청을 받아 결과를 돌려주는 일' 만 하고 실제 동작은 백엔드에 맡긴다.
실제 팔 백엔드(정책·MoveIt 등)는 로봇팔 팀이 ArmBackend 를 상속해 추가하고
make_backend() 에 이름을 등록하면 된다.

- none: 백엔드 없음. 모든 작업을 거절한다 (기본값). 실물 PC 에서 실수로 가짜 성공을 보내지 않게.
- fake: 정해진 시간 뒤 성공을 돌려준다. 격리 도메인 전용 (check_domain).
- worker: 계속 켜 두는 외부 팔 실행기(예: omx_fleet_worker.py)에 stdin/stdout JSON 으로 일을 시킨다.
  lerobot·torch 를 이 패키지에 넣지 않기 위해서다.
"""

import json
import math
import os
import queue
import shlex
import signal
import subprocess
import threading
import time

# 실물이 쓰는 도메인. cobot_mock 과 같은 규칙이다 (코드는 import 하지 않는다, CLAUDE.md 3-6).
FORBIDDEN_DOMAINS = frozenset({0, 10, 12, 20, 30, 100})


def check_domain(env):
    """가짜 결과를 내도 되는 도메인인지 본다. (ok, 메시지) 를 돌려준다."""
    raw = env.get('ROS_DOMAIN_ID', '')
    try:
        domain = int(raw)
    except ValueError:
        return False, 'ROS_DOMAIN_ID 가 비어 있음: 격리 도메인(예: 101)을 지정하세요'
    if domain in FORBIDDEN_DOMAINS:
        return False, (f'ROS_DOMAIN_ID={domain} 은 실물 도메인({sorted(FORBIDDEN_DOMAINS)}): '
                       'fake 백엔드를 쓰지 않습니다. 예: 101')
    return True, f'ROS_DOMAIN_ID={domain}'


class ArmBackend:
    """
    팔 1대의 동작 백엔드 틀. 한 번에 작업 하나만 한다.

    start() 로 시작하고, 노드가 주기적으로 poll() 을 불러 끝난 작업을 받아 간다.
    poll() 은 (요청, 성공 여부, data, detail) 목록을 돌려준다.

    전원 (관제 CMD_START·CMD_RESET, arm_power_utils): attach() 로 팔에 연결하고 ready 가 참이 되면 일을 받는다.
    release() 는 끄기를 요청하고, 결과는 take_release() 가 (끔, 이유) 로 한 번 돌려준다.
    실행기가 끄기 전에 쉬는 자세로 옮기기 시작하면 take_release_moving() 이 예상 시간[s] 을 한 번 돌려준다.
    dead 가 비어 있지 않으면 고장이다. reset() 이 상태를 비워 다시 attach() 할 수 있게 한다.
    joints·joints_at 은 마지막으로 잰 관절 값과 그 시각[s] 이다 (ArmStatus 용, 모르면 None).
    """

    name = 'base'
    available = False

    def __init__(self):
        self.job = None
        self.ready = False
        self.dead = ''
        self.joints = None
        self.joints_at = None
        self.release_result = None
        self.release_moving = None

    def busy(self):
        """작업 중인지."""
        return self.job is not None

    def start(self, request, port, now):
        """작업을 시작한다. 시작하지 못하면 이유 문자열, 시작했으면 None."""
        raise NotImplementedError

    def poll(self, now):
        """끝난 작업 목록."""
        return []

    def hold(self, now):
        """즉시 멈춘다. 하던 작업이 있으면 실패로 끝낸다 (팔 자세를 모르므로 재시도 금지)."""
        return []

    def release_hold(self, now):
        """정지 해제. 동작을 시작하지는 않는다."""

    def attach(self, port, now):
        """팔에 연결한다 (CMD_START 또는 auto_start)."""

    def running(self):
        """팔에 연결된 실행기가 떠 있는지."""
        return False

    def release(self, now):
        """끄기를 요청한다. 연결된 팔이 없으면 바로 끈다."""
        self.ready = False
        self.release_result = (True, '')

    def take_release(self):
        """끄기 결과 (끔, 이유) 를 한 번 돌려준다. 아직이면 None."""
        result, self.release_result = self.release_result, None
        return result

    def take_release_moving(self):
        """끄기 전 쉬는 자세로 옮기는 중이면 예상 시간[s] 을 한 번 돌려준다. 아니면 None."""
        seconds, self.release_moving = self.release_moving, None
        return seconds

    def request_state(self, now):
        """대기 중이면 관절 값을 새로 읽게 한다."""

    def reset(self):
        """고장·끄기 뒤 상태를 비운다. 다음 attach() 를 받을 수 있게 된다."""
        self.job, self.ready, self.dead, self.release_result = None, False, '', None
        self.release_moving = None

    def shutdown(self):
        """노드가 꺼질 때 부른다. 하던 일이 있으면 멈춘다."""


class NoBackend(ArmBackend):
    """실제 팔 백엔드가 아직 없음. 모든 작업을 거절한다."""

    name = 'none'

    def start(self, request, port, now):
        return '팔 동작 백엔드가 설정되지 않음 (backend=none)'


class FakeBackend(ArmBackend):
    """시험용: duration_sec 뒤에 성공. 결과 data 에 fake=true 를 붙여 진짜와 구분한다."""

    name = 'fake'
    available = True

    def __init__(self, duration_sec):
        super().__init__()
        self.duration_sec = duration_sec

    def attach(self, port, now):
        self.ready = True

    def running(self):
        return self.ready

    def start(self, request, port, now):
        if self.busy():
            return '팔 작업 중'
        self.job = (request, now + self.duration_sec)
        return None

    def poll(self, now):
        if self.job is None or now < self.job[1]:
            return []
        request, self.job = self.job[0], None
        return [(request, True, {'arm_safe': True, 'fake': True}, '')]

    def hold(self, now):
        if self.job is None:
            return []
        request, self.job = self.job[0], None
        return [(request, False, {'fake': True}, 'hold 로 작업 중단')]


# 실행기가 stdout 에 쓰는 기계용 줄의 머리. 나머지 줄은 사람이 읽는 로그다.
WORKER_PREFIX = '@fleet '
MAX_WORKER_LINE = 16384


def parse_worker_line(line):
    """실행기 출력 한 줄. 기계용이면 dict, 사람용 로그면 None, 깨진 기계용 줄이면 ValueError."""
    if not line.startswith(WORKER_PREFIX):
        return None
    if len(line) > MAX_WORKER_LINE:
        raise ValueError('실행기 줄이 너무 김')
    event = json.loads(line[len(WORKER_PREFIX):])
    if not isinstance(event, dict) or not isinstance(event.get('event'), str):
        raise ValueError('실행기 줄에 event 없음')
    return event


def judge_done(event):
    """
    실행기 done 이벤트를 (성공 여부, data, detail) 로 바꾼다.

    성공은 success 와 arm_safe 가 둘 다 정확히 true 일 때만이다. arm_safe 는 실행기가 단계 뒤
    안전 자세로 물러나 관절을 다시 읽어 확인한 값이다. 명령이 시작된 뒤라 retry_safe 는 붙이지 않는다.
    """
    arm_safe = event.get('arm_safe') is True
    data = {'arm_safe': arm_safe}
    for key in ('end_reason', 'success_basis', 'pose_error', 'joints'):
        if key in event:
            data[key] = event[key]
    if event.get('success') is not True:
        basis = event.get('success_basis')
        if basis == 'none':
            return False, data, '성공 판단기 없음: 성공을 확인하지 못함 (사람 확인 필요)'
        return False, data, f'성공 판단 안 나옴 (end_reason={event.get("end_reason")})'
    if not arm_safe:
        return False, data, '동작은 끝났으나 안전 자세 확인 안 됨 (arm_safe)'
    return True, data, ''


class WorkerBackend(ArmBackend):
    """
    계속 켜 두는 팔 실행기 백엔드 (예: omx_fleet_worker.py).

    팔이 READY 가 되면 attach() 가 실행기를 한 번 띄운다. 실행기는 팔에 연결해 토크를 켜고
    모델을 미리 올린 뒤 ready 를 알린다. 작업마다 stdin 으로 run 을 보내고 stdout 의 done 을 기다린다.
    작업마다 프로그램을 새로 켜지 않는 이유: lerobot 은 연결·해제 때 토크를 꺼서 팔이 떨어진다.

    hold·시간 초과면 stdin 으로 hold 를 보낸다 (실행기가 토크를 유지한 채 멈춘다). 그 작업의 결과는
    바로 실패로 돌려주고, 실행기가 멈춤을 알릴(done) 때까지 busy() 는 참이다.
    실행기가 죽으면 다시 띄우지 않는다. 팔 자세와 토크 상태를 모르므로 사람이 확인하고 노드를 다시 켠다.
    """

    name = 'worker'
    available = True

    def __init__(self, arm_id, command, timeout_sec=300.0, popen=subprocess.Popen,
                 env=None, log=None):
        super().__init__()
        self.arm_id = arm_id
        self.argv = shlex.split(command) if isinstance(command, str) else []
        self.timeout_sec = timeout_sec
        self.popen = popen
        self.env = dict(os.environ if env is None else env)
        self.log = log or (lambda text: None)
        self.process = None
        self.events = queue.Queue()
        self.stopping = None    # hold 를 보낸 작업 id: 실행기의 done 을 기다리는 중
        self.releasing = False  # release 를 보내고 답을 기다리는 중
        self.state_pending = False
        self.released = False   # 실행기가 쉬는 자세를 확인하고 정상으로 끝냄

    def busy(self):
        """작업 중이거나 멈추는 중인지."""
        return self.job is not None or self.stopping is not None

    def attach(self, port, now):
        """실행기를 띄운다. 이미 떠 있거나 고장(dead) 이면 아무것도 안 한다 (reset() 뒤 다시)."""
        if self.process is not None or self.dead:
            return
        if not self.argv:
            self.dead = '실행기 명령이 설정되지 않음 (worker_command)'
            return
        env = dict(self.env)
        env.update({'ARM_ID': self.arm_id, 'ROBOT_PORT': port, 'PYTHONUNBUFFERED': '1'})
        try:
            self.process = self.popen(self.argv, env=env, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1, start_new_session=True)
        except OSError as error:
            self.dead = f'실행기 실행 실패: {error}'
            return
        self.events = queue.Queue()  # 앞 실행기의 남은 줄과 섞이지 않게
        threading.Thread(target=self._read, args=(self.process, self.events), daemon=True).start()
        self.log(f'{self.arm_id} 실행기 시작 (pid {self.process.pid}): 팔에 연결하고 모델을 불러옴')

    def _read(self, process, events):
        for line in process.stdout:
            line = line.rstrip('\n')
            try:
                event = parse_worker_line(line)
            except ValueError as error:
                self.log(f'{self.arm_id} 실행기 줄 무시 ({error}): {line[:120]}')
                continue
            if event is None:
                self.log(f'{self.arm_id} | {line}')
            else:
                events.put(event)
        events.put({'event': 'exited'})

    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def _timeout(self, request):
        value = request.get('timeout_sec')
        if (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and value > 0):
            return min(float(value), self.timeout_sec)
        return self.timeout_sec

    def start(self, request, port, now):
        if self.dead:
            return f'팔 실행기 없음: {self.dead}'
        if not self.ready:
            return '팔 실행기 준비 중 (팔 연결·모델 불러오는 중)'
        if self.busy():
            return '팔 작업 중'
        if not self._send({'cmd': 'run', 'id': request['request_id'],
                           'action': request.get('action')}):
            return '팔 실행기에 명령을 보내지 못함'
        self.job = (request, now + self._timeout(request))
        return None

    def _finish_job(self, success, data, detail):
        request, self.job = self.job[0], None
        return [(request, success, data, detail)]

    def poll(self, now):
        finished = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            finished += self._on_event(event)
        if self.job is not None and now >= self.job[1]:
            self._send({'cmd': 'hold'})
            self.stopping = self.job[0]['request_id']
            finished += self._finish_job(False, {}, '시간 초과로 멈춤 (토크 유지): 팔 상태를 모름')
        return finished

    def running(self):
        return self.process is not None and self.process.poll() is None

    def release(self, now):
        """실행기에 release 를 보낸다. 실행기가 쉬는 자세인지 보고 끄거나 거절한다."""
        if not self.running():
            super().release(now)
            return
        if self._send({'cmd': 'release'}):
            self.releasing = True
        else:
            self.release_result = (False, '실행기에 명령을 보내지 못함')

    def request_state(self, now):
        if self.ready and not self.busy() and not self.releasing and not self.state_pending:
            self.state_pending = self._send({'cmd': 'state'})

    def reset(self):
        """끝난 실행기를 정리한다. 아직 살아 있으면 quit 을 보낸다 (토크가 꺼진다)."""
        if self.running():
            self._send({'cmd': 'quit'})
        super().reset()
        self.process, self.stopping, self.releasing, self.state_pending = None, None, False, False
        self.released = False

    def _on_joints(self, event):
        if isinstance(event.get('joints'), dict):
            self.joints, self.joints_at = event['joints'], time.time()

    def _on_event(self, event):
        kind = event['event']
        job_id = self.job[0]['request_id'] if self.job else None
        self._on_joints(event)
        if kind == 'state':
            self.state_pending = False
        elif kind == 'released':
            self.releasing, self.ready, self.released = False, False, True
            self.release_result = (True, '')
            self.log(f'{self.arm_id} 쉬는 자세 확인, 실행기가 연결을 끊음')
        elif kind == 'release_moving' and self.releasing:
            # 실행기 설정 release_move: 끄기 전에 쉬는 자세로 옮긴다. 결과(released·refused)는 그 뒤에 온다.
            try:
                seconds = max(0.0, float(event.get('seconds') or 0.0))
            except (TypeError, ValueError):
                seconds = 0.0
            self.release_moving = seconds
            self.log(f'{self.arm_id} 끄기 전 쉬는 자세로 이동 (약 {seconds:.1f}s)')
        elif kind == 'release_refused':
            self.releasing = False
            self.release_result = (False, str(event.get('detail') or '거절'))
        elif kind == 'ready':
            self.ready = True
            self.log(f'{self.arm_id} 실행기 준비 완료: {event.get("actions")}')
        elif kind == 'fatal':
            self.dead = f'실행기 오류: {event.get("detail")}'
            self.log(f'{self.arm_id} {self.dead}')
        elif kind == 'exited':
            self.ready, self.stopping, self.state_pending = False, None, False
            if self.releasing:
                self.releasing = False
                self.release_result = (False, '끄는 중 실행기가 끝남')
            if not self.released:
                self.dead = self.dead or '실행기가 끝남'  # 정상 끄기(released) 뒤의 끝남은 고장이 아니다
            if self.job:
                return self._finish_job(False, {}, f'{self.dead}: 팔 상태를 모름')
        elif kind == 'rejected' and self.job and event.get('id') == job_id:
            # 실행기가 움직이기 전에 거절했다. 관제가 다시 시도해도 안전하다.
            return self._finish_job(False, {'retry_safe': True}, str(event.get('detail') or '거절'))
        elif kind in ('done', 'rejected'):
            if event.get('id') == self.stopping:
                self.stopping = None    # hold 로 이미 실패를 보낸 작업이 멈춤을 마쳤다
            elif self.job and event.get('id') == job_id:
                return self._finish_job(*judge_done(event))
        return []

    def hold(self, now):
        if self.process is not None:
            self._send({'cmd': 'hold'})
        if self.job is None:
            return []
        self.stopping = self.job[0]['request_id']
        return self._finish_job(False, {}, 'hold 로 멈춤 (토크 유지): 팔 상태를 모름')

    def shutdown(self):
        """실행기를 끝낸다. 실행기가 연결을 끊으면 토크가 꺼져 팔이 내려앉을 수 있다."""
        if self.process is None or self.process.poll() is not None:
            return
        self._send({'cmd': 'quit'})
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGINT)


def make_backend(name, fake_duration_sec, worker_options=None):
    """이름으로 백엔드를 만든다. 모르는 이름이면 ValueError."""
    if name == 'none':
        return NoBackend()
    if name == 'fake':
        return FakeBackend(fake_duration_sec)
    if name == 'worker':
        return WorkerBackend(**(worker_options or {}))
    raise ValueError(f'모르는 backend: {name} (none, fake, worker)')
