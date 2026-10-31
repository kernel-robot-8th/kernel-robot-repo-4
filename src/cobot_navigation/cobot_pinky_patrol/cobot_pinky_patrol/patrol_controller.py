"""ROS 비의존 순찰 상태 기계. 모든 메서드는 한 executor에서 짧게 실행한다."""

from collections import deque
from dataclasses import dataclass
import time

from .patrol_points_utils import exit_name, general_names, parse_command, zone_of


@dataclass(frozen=True)
class Step:
    """완료 콜백 사이에도 보존할 작업 단계."""

    kind: str
    target: str
    index: int = -1


class PatrolController:
    """대기 루프 없이 tick에서 상태를 한 단계씩 진행한다."""

    def __init__(self, points, home_name, zone_points, navigation, gate, emit,
                 prepare, ready, abort_preparation, clock=time.monotonic,
                 idle_return_sec=120.0, retries=3, ready_timeout_sec=60.0):
        self.points, self.home_name, self.zone_points = points, home_name, zone_points
        self.navigation, self.gate, self.emit = navigation, gate, emit
        self.prepare, self.ready, self.abort_preparation = prepare, ready, abort_preparation
        self.clock = clock
        self.idle_return_sec, self.retries = idle_return_sec, retries
        self.ready_timeout_sec = ready_timeout_sec
        self.phase = 'IDLE'
        self.command_id = None
        self.operation = None
        self.names = ()
        self.held_zone = None
        self.last_point = None
        self.idle_deadline = None
        self.steps = deque()
        self.step = None
        self._attempts = 0
        self._gate_zone = None
        self._slot_target = None
        self._slot_done = False
        self._stop = False
        self._emergency = False
        self._final = None
        self._last_report = None

    @property
    def busy(self):
        """이동·준비·취소 중에는 새 업무를 받지 않는다."""
        return self.phase != 'IDLE'

    def _report(self, state, detail='', index=-1, finished=False, command_id=None):
        payload = {'state': state, 'waypoint': index, 'detail': detail, 'time': time.time()}
        identity = self.command_id if command_id is None else command_id
        if identity:
            payload.update(command_id=identity, task_finished=finished)
        self.emit(payload)

    def _reject(self, command_id, detail):
        # 다른 명령의 거절이 현재 작업의 완료로 기록되지 않게 ID를 명시한다.
        payload = {'state': 'FAILED', 'waypoint': -1, 'detail': detail, 'time': time.time()}
        if command_id:
            payload.update(command_id=command_id, task_finished=True)
        self.emit(payload)

    def submit(self, raw, command_id=None):
        """입력 검증과 상태 등록만 하고 Nav2 완료를 기다리지 않는다."""
        kind, names = parse_command(raw)
        if kind in ('stop', 'emergency_stop'):
            self.stop(kind == 'emergency_stop')
            return
        if self.busy:
            if command_id and command_id != self.command_id:
                self._reject(command_id, 'robot busy')
            return
        reason = self._validate(kind, names)
        if reason:
            self._reject(command_id, reason)
            return
        self.command_id, self.operation, self.names = command_id, kind, names
        self._stop = self._emergency = False
        self._gate_zone = None
        self._final = None
        self._last_report = None
        self.idle_deadline = None
        self.steps.clear()
        self.step = None
        target_zone = zone_of(self.zone_points, names[0]) if kind == 'zone' else None
        if self.held_zone is not None and (kind != 'zone' or target_zone != self.held_zone):
            self.steps.append(Step('exit', self.held_zone))
        if kind == 'zone':
            if target_zone != self.held_zone:
                self.steps.append(Step('gate', target_zone))
            self.steps.append(Step('move', names[0], 0))
        elif kind == 'goto':
            self.steps.extend(Step('move', name, i) for i, name in enumerate(names))
        elif kind == 'home':
            self.steps.append(Step('home', self.home_name))
        self.phase = 'PREPARING'
        self._ready_deadline = self.clock() + self.ready_timeout_sec
        self._report('STARTING', ','.join(names) or kind)
        self.prepare()

    def _validate(self, kind, names):
        if kind == 'start':
            return 'start disabled'
        if kind not in ('goto', 'zone', 'leave', 'home'):
            return 'unknown command'
        if kind == 'leave' and self.held_zone is None:
            return 'no zone held'
        if kind in ('goto', 'zone'):
            if not names:
                return 'no point given'
            unknown = [n for n in names if n not in self.points]
            if unknown:
                return f'unknown point: {unknown}'
            zones = {p for members in self.zone_points.values() for p in members}
            if kind == 'zone' and (len(names) != 1 or names[0] not in zones):
                return f'zone needs one zone point: {list(names)}'
            if kind == 'goto':
                if any(n in zones for n in names):
                    return 'use zone'
                if any(n not in set(general_names(self.points)) | {self.home_name} for n in names):
                    return 'not allowed'
        return ''

    def preparation_failed(self, detail):
        """입출력 계층의 준비 실패는 주행을 시작하기 전에만 확정한다."""
        if self.phase == 'PREPARING':
            self.abort_preparation()
            self._finish('FAILED', detail)

    def stop(self, emergency=False):
        """취소만 요청한다. 최종 액션 종료가 확인되기 전에는 다음 이동을 시작하지 않는다."""
        if not self.busy and self.held_zone is None:
            self.idle_deadline = None
            return
        if not self.busy:
            self.operation, self.names, self.command_id = 'stop', (), None
        self._stop = True
        self._emergency = self._emergency or emergency
        self.idle_deadline = None
        self.abort_preparation()
        self.steps.clear()
        self.phase = 'CANCELING'
        self.navigation.cancel()

    def tick(self):
        """타이머가 호출하며 Future 결과·구역 상태만 읽는다. 내부 spin은 없다."""
        if not self.busy:
            if self.idle_deadline is not None and self.clock() >= self.idle_deadline:
                self.submit('home')
            return
        if self.navigation.fault:
            report = ('RETRY', self.navigation.fault)
            if report != self._last_report:
                self._report(*report)
                self._last_report = report
        if self.phase == 'CANCELING':
            if self.navigation.busy:
                return
            self.navigation.pop_result()
            self._stop_after_cancel()
        elif self.phase == 'PREPARING':
            if self.ready():
                self.phase = 'NEXT'
            elif self.clock() >= self._ready_deadline:
                self.abort_preparation()
                self._finish('FAILED', 'Nav2 준비 시간 초과')
        elif self.phase == 'NEXT':
            self._next()
        elif self.phase == 'QUEUEING':
            self._queue_tick()
        elif self.phase == 'NAVIGATING':
            self._move_tick()

    def _next(self):
        if not self.steps:
            state, detail = self._final or ('DONE', self._done_detail())
            self._finish(state, detail)
            return
        self.step = self.steps.popleft()
        self._attempts = 0
        if self.step.kind == 'gate':
            self._gate_zone = self.step.target
            self.gate.reset(self._gate_zone)
            self.gate.send_request()
            self._slot_target = None
            self._slot_done = False
            self.phase = 'QUEUEING'
        elif self.step.kind == 'home' and self.last_point == self.home_name:
            return
        else:
            self._begin_move()

    def _begin_move(self):
        name = exit_name(self.step.target) if self.step.kind == 'exit' else self.step.target
        state = ('RETREATING' if self._stop else 'LEAVING_ZONE') if self.step.kind == 'exit' else (
            'RETURNING' if self.step.kind == 'home' else 'MOVING')
        self._report(state, name, self.step.index)
        self.navigation.start(self.points[name])
        self._attempts += 1
        self.phase = 'NAVIGATING'

    def _move_tick(self):
        if self.navigation.busy:
            return
        result = self.navigation.pop_result()
        if result is None:
            return
        if result != 'SUCCEEDED':
            if self._attempts < self.retries:
                self._begin_move()
                return
            if self.step.kind != 'exit' and self.held_zone is not None:
                self._final = ('FAILED', self.step.target)
                self.steps.clear()
                self.steps.append(Step('exit', self.held_zone))
                self.phase = 'NEXT'
                return
            self._finish('FAILED', self.step.target)
            return
        if self.step.kind == 'exit':
            self.gate.notify_exit()
            self.held_zone = None
            self.last_point = None
        else:
            self.last_point = self.step.target
            self._report('ARRIVED', self.step.target, self.step.index)
        self.phase = 'NEXT'

    def _queue_tick(self):
        self.gate.resend_if_due()
        if self.gate.granted():
            self.navigation.cancel()
            if self.navigation.busy:
                return
            self.navigation.pop_result()
            self.held_zone = self._gate_zone
            self._gate_zone = None
            self.phase = 'NEXT'
            return
        slot = self.gate.current_slot
        if slot is not None and slot[0] == -1:
            self._final = ('FAILED', 'queue_full')
            self.phase = 'CANCELING'
            self.navigation.cancel()
            return
        target = tuple(slot[1:]) if slot is not None else None
        if target != self._slot_target:
            self.navigation.cancel()
            if self.navigation.busy:
                return
            self.navigation.pop_result()
            self._slot_target, self._slot_done, self._attempts = target, False, 0
        if target is None:
            return
        if not self.navigation.busy:
            result = self.navigation.pop_result()
            if result == 'SUCCEEDED':
                self._slot_done = True
            elif result is not None and self._attempts >= self.retries:
                self._final = ('FAILED', 'slot')
                self.phase = 'CANCELING'
                return
            if not self._slot_done:
                self.navigation.start(target)
                self._attempts += 1
                self._report('QUEUEING', f'slot{slot[0]}', 0)

    def _stop_after_cancel(self):
        if self._gate_zone is not None:
            if self.gate.granted():
                # 허가 직후 취소된 경우에도 구역 진입 이동은 아직 시작하지 않았다.
                self.gate.notify_exit()
            else:
                self.gate.cancel_entry()
            self._gate_zone = None
        if self._emergency:
            self._finish('STOPPED', 'emergency_stop: 구역 토큰 유지')
        elif self.held_zone is not None:
            self._final = self._final or ('STOPPED', 'retreated')
            self.steps.append(Step('exit', self.held_zone))
            self.phase = 'NEXT'
        else:
            self._finish(*(self._final or ('STOPPED', 'stopped')))

    def _done_detail(self):
        if self.operation == 'home':
            return 'returned home'
        if self.operation == 'leave':
            return 'left zone'
        return f'arrived {self.names[-1]}' if self.names else ''

    def _finish(self, state, detail):
        self.phase = 'IDLE'
        self.steps.clear()
        self._report(state, detail, finished=True)
        self.command_id = None
        if self.held_zone is not None:
            self._report('HOLDING_ZONE', self.held_zone)
        if state == 'DONE' and self.idle_return_sec > 0 and (
                self.held_zone is not None or self.last_point != self.home_name):
            self.idle_deadline = self.clock() + self.idle_return_sec
            self._report('IDLE_WAIT', f'{self.idle_return_sec:g}')
        else:
            self.idle_deadline = None
