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
    """

    name = 'base'
    available = False

    def __init__(self):
        self.job = None

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
        """팔이 READY 가 되면 노드가 부른다."""

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
        self.ready = False
        self.dead = ''          # 실행기가 끝난 이유. 비어 있지 않으면 일을 받지 않는다
        self.stopping = None    # hold 를 보낸 작업 id: 실행기의 done 을 기다리는 중

    def busy(self):
        """작업 중이거나 멈추는 중인지."""
        return self.job is not None or self.stopping is not None

    def attach(self, port, now):
        """팔이 READY 가 되면 실행기를 띄운다. 이미 떠 있거나 죽은 뒤면 아무것도 안 한다."""
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
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()
        self.log(f'{self.arm_id} 실행기 시작 (pid {self.process.pid}): 팔에 연결하고 모델을 불러옴')

    def _read(self, process):
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
                self.events.put(event)
        self.events.put({'event': 'exited'})

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

    def _on_event(self, event):
        kind = event['event']
        job_id = self.job[0]['request_id'] if self.job else None
        if kind == 'ready':
            self.ready = True
            self.log(f'{self.arm_id} 실행기 준비 완료: {event.get("actions")}')
        elif kind == 'fatal':
            self.dead = f'실행기 오류: {event.get("detail")}'
            self.log(f'{self.arm_id} {self.dead}')
        elif kind == 'exited':
            self.dead = self.dead or '실행기가 끝남'
            self.ready = False
            self.stopping = None
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
