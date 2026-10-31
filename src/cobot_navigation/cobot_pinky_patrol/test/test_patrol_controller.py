"""이벤트 사이에 작업 상태를 보존하는 순찰 정책과 취소 경계를 검증한다."""

from types import SimpleNamespace

from cobot_pinky_patrol.patrol_controller import PatrolController
import pytest


class Navigation:
    """완료와 취소를 테스트가 명시적으로 전달하는 비동기 포트."""

    def __init__(self):
        self.busy = False
        self.fault = ''
        self.result = None
        self.goals = []
        self.cancels = 0

    def start(self, pose):
        assert not self.busy
        self.busy = True
        self.goals.append(pose)

    def cancel(self):
        if self.busy:
            self.cancels += 1

    def finish(self, result='SUCCEEDED'):
        self.busy, self.result = False, result

    def pop_result(self):
        value, self.result = self.result, None
        return value


class Gate:
    """허가·슬롯 도착은 tick 사이의 외부 이벤트로 취급한다."""

    def __init__(self):
        self.zone = None
        self.grant = False
        self.current_slot = None
        self.exits = []
        self.cancels = []
        self.requests = 0

    def reset(self, zone):
        self.zone, self.grant, self.current_slot = zone, False, None

    def send_request(self):
        self.requests += 1

    def resend_if_due(self):
        pass

    def granted(self):
        return self.grant

    def notify_exit(self):
        self.exits.append(self.zone)
        self.grant = False

    def cancel_entry(self):
        self.cancels.append(self.zone)


def make_environment():
    points = {'I1': (0, 0, 0), 'P1': (1, 0, 0), 'P2': (2, 0, 0),
              'ZA': (3, 0, 0), 'ZA_EXIT': (3, -1, 0),
              'ZB': (4, 0, 0), 'ZB_EXIT': (4, -1, 0)}
    nav, gate, events, clock, ready = Navigation(), Gate(), [], [0], [True]
    prep = []
    controller = PatrolController(
        points, 'I1', {'A': ('ZA',), 'B': ('ZB',)}, nav, gate, events.append,
        lambda: prep.append('prepare'), lambda: ready[0], lambda: prep.append('abort'),
        clock=lambda: clock[0], idle_return_sec=10, ready_timeout_sec=5)
    return SimpleNamespace(c=controller, nav=nav, gate=gate, events=events,
                           clock=clock, ready=ready, prep=prep, points=points)


@pytest.fixture
def env():
    return make_environment()


def advance(env, phase):
    """외부 이벤트가 필요 없는 상태 전이만 제한된 횟수로 진행한다."""
    for _ in range(15):
        if env.c.phase == phase:
            return
        env.c.tick()
    pytest.fail(f'{phase}에 도달하지 못함: {env.c.phase}')


def completed(env):
    return [e for e in env.events if e.get('task_finished')]


def test_multi_waypoints_then_idle_return(env):
    env.c.submit('goto:P1,P2', 'job1')
    advance(env, 'NAVIGATING')
    assert env.nav.goals == [env.points['P1']]
    env.nav.finish()
    env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals[-1] == env.points['P2']
    env.nav.finish()
    advance(env, 'IDLE')
    assert completed(env)[-1]['command_id'] == 'job1'
    assert env.c.idle_deadline == 10
    assert env.nav.goals == [env.points['P1'], env.points['P2']]
    env.clock[0] = 11
    env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals[-1] == env.points['I1']
    env.nav.finish()
    advance(env, 'IDLE')
    assert env.c.idle_deadline is None


@pytest.mark.parametrize('command,detail', [
    ('start', 'start disabled'), ('leave', 'no zone held'), ('goto:', 'no point'),
    ('goto:P99', 'unknown point'), ('goto:ZA', 'use zone'),
    ('goto:ZA_EXIT', 'not allowed'), ('zone:P1', 'zone needs'),
    ('zone:ZA,ZB', 'zone needs'), ('dance', 'unknown command'),
])
def test_validation_never_moves(env, command, detail):
    env.c.submit(command, 'invalid')
    assert not env.c.busy and not env.nav.goals
    assert detail in completed(env)[-1]['detail']


def test_busy_rejection_and_duplicate_keep_original_id(env):
    env.c.submit('goto:P1', 'job1')
    advance(env, 'NAVIGATING')
    env.c.submit('goto:P2', 'job2')
    assert completed(env)[-1]['command_id'] == 'job2'
    assert env.c.command_id == 'job1'
    count = len(env.events)
    env.c.submit('goto:P1', 'job1')
    assert len(env.events) == count
    assert len(env.nav.goals) == 1
    env.nav.finish()
    advance(env, 'IDLE')
    assert completed(env)[-1]['command_id'] == 'job1'


def test_preparation_timeout_and_stop_do_not_move(env):
    env.ready[0] = False
    env.c.submit('home', 'job1')
    env.c.tick()
    assert env.c.phase == 'PREPARING'
    env.clock[0] = 6
    env.c.tick()
    assert completed(env)[-1]['state'] == 'FAILED' and not env.nav.goals
    env.c.submit('goto:P1', 'job2')
    env.c.stop()
    env.c.tick()
    assert completed(env)[-1]['state'] == 'STOPPED' and not env.nav.goals


def test_empty_zone_grant_before_motion_holds_token(env):
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'QUEUEING')
    assert env.gate.requests == 1 and not env.nav.goals
    env.gate.grant = True
    env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals == [env.points['ZA']]
    env.nav.finish()
    advance(env, 'IDLE')
    assert env.c.held_zone == 'A' and not env.gate.exits
    assert any(e['state'] == 'HOLDING_ZONE' for e in env.events)


def test_slot_retarget_waits_for_old_goal_termination(env):
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'QUEUEING')
    env.gate.current_slot = (1, 1, -1, 0)
    env.c.tick()
    assert env.nav.goals == [(1, -1, 0)]
    env.gate.current_slot = (0, 2, -1, 0)
    env.c.tick()
    assert len(env.nav.goals) == 1 and env.nav.cancels
    env.nav.finish('CANCELED')
    env.c.tick()
    assert env.nav.goals[-1] == (2, -1, 0)
    env.gate.grant = True
    env.c.tick()
    assert env.c.held_zone is None
    env.nav.finish('CANCELED')
    env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals[-1] == env.points['ZA']


@pytest.mark.parametrize('kind', ['stop', 'full', 'slot_failure'])
def test_queue_abort_cancels_after_motion_ends(env, kind):
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'QUEUEING')
    env.gate.current_slot = (0, 1, -1, 0)
    env.c.tick()
    if kind == 'stop':
        env.c.stop()
    elif kind == 'full':
        env.gate.current_slot = (-1, 0, 0, 0)
        env.c.tick()
    else:
        for _ in range(3):
            env.nav.finish('FAILED')
            env.c.tick()
    if env.nav.busy:
        env.c.tick()
        assert not env.gate.cancels
        env.nav.finish('CANCELED')
    advance(env, 'IDLE')
    assert env.gate.cancels == ['A'] and not env.gate.exits
    assert completed(env)[-1]['state'] == ('STOPPED' if kind == 'stop' else 'FAILED')


def test_stop_after_grant_before_enter_returns_unused_token(env):
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'QUEUEING')
    env.gate.grant = True
    env.c.stop()
    env.c.tick()
    assert env.gate.exits == ['A'] and not env.nav.goals


@pytest.mark.parametrize('command', ['goto:P1', 'home', 'leave', 'zone:ZB'])
def test_held_zone_exits_before_next_mission(env, command):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit(command, 'job1')
    advance(env, 'NAVIGATING')
    assert env.nav.goals == [env.points['ZA_EXIT']] and not env.gate.exits
    env.nav.finish()
    env.c.tick()
    assert env.gate.exits == ['A'] and env.c.held_zone is None
    if command == 'zone:ZB':
        advance(env, 'QUEUEING')
        assert env.gate.zone == 'B'
    elif command == 'leave':
        advance(env, 'IDLE')
        assert len(env.nav.goals) == 1
    else:
        advance(env, 'NAVIGATING')
        assert len(env.nav.goals) == 2


def test_stop_retreat_waits_for_cancel_result_and_exit_arrival(env):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'NAVIGATING')
    env.c.stop()
    env.c.tick()
    assert env.c.phase == 'CANCELING' and len(env.nav.goals) == 1
    assert not completed(env)
    env.nav.finish('CANCELED')
    env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals[-1] == env.points['ZA_EXIT'] and not env.gate.exits
    env.nav.finish()
    advance(env, 'IDLE')
    assert env.gate.exits == ['A'] and completed(env)[-1]['state'] == 'STOPPED'


def test_emergency_during_retreat_preserves_token(env):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'NAVIGATING')
    env.c.stop()
    env.nav.finish('CANCELED')
    env.c.tick()
    advance(env, 'NAVIGATING')
    env.c.stop(emergency=True)
    env.c.tick()
    assert env.c.busy
    env.nav.finish('CANCELED')
    advance(env, 'IDLE')
    assert env.c.held_zone == 'A' and not env.gate.exits
    assert env.c.idle_deadline is None


def test_failed_exit_retains_token_and_is_retryable(env):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit('leave', 'job1')
    advance(env, 'NAVIGATING')
    for _ in range(3):
        env.nav.finish('FAILED')
        env.c.tick()
    assert not env.c.busy and env.c.held_zone == 'A' and not env.gate.exits
    env.c.submit('leave', 'job2')
    advance(env, 'NAVIGATING')
    env.nav.finish()
    advance(env, 'IDLE')
    assert env.c.held_zone is None


def test_zone_navigation_failure_retreats_before_reporting_failure(env):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit('zone:ZA', 'job1')
    advance(env, 'NAVIGATING')
    for _ in range(3):
        env.nav.finish('FAILED')
        env.c.tick()
    advance(env, 'NAVIGATING')
    assert env.nav.goals[-1] == env.points['ZA_EXIT']
    assert not completed(env)
    env.nav.finish()
    advance(env, 'IDLE')
    assert completed(env)[-1]['state'] == 'FAILED' and env.gate.exits == ['A']


def test_unknown_action_result_never_finishes_or_releases_token(env):
    env.c.held_zone, env.gate.zone = 'A', 'A'
    env.c.submit('leave', 'job1')
    advance(env, 'NAVIGATING')
    env.nav.fault = '주행 결과 미확정'
    for _ in range(5):
        env.c.tick()
    assert env.c.busy and not completed(env) and not env.gate.exits
    assert len(env.nav.goals) == 1


@pytest.mark.parametrize('idle_sec,already_home', [(0, False), (10, True)])
def test_idle_disabled_or_already_home(env, idle_sec, already_home):
    env.c.idle_return_sec = idle_sec
    env.c.last_point = env.c.home_name if already_home else None
    env.c.submit('home' if already_home else 'goto:P1', 'job1')
    if already_home:
        advance(env, 'IDLE')
        assert not env.nav.goals
    else:
        advance(env, 'NAVIGATING')
        env.nav.finish()
        advance(env, 'IDLE')
    assert env.c.idle_deadline is None
