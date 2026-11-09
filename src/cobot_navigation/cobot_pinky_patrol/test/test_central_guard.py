"""중앙 연결 감시가 오래되거나 재전송된 네트워크 메시지로 이동을 재개하지 않는지 검증한다."""

from cobot_pinky_patrol.central_guard import CentralGuard
import pytest


@pytest.fixture
def env():
    now = [0.0]
    guard = CentralGuard(clock=lambda: now[0])
    return now, guard


def packet(now, seq=1, session='server1', **changes):
    return dict(dict(session_id=session, seq=seq, issued_at=1000 + now[0], ttl_sec=3.0), **changes)


def test_first_heartbeat_command_and_replay_fencing(env):
    now, guard = env
    assert not guard.accept(packet(now))
    guard.heartbeat(packet(now))
    assert guard.accept(packet(now))
    assert not guard.accept(packet(now))
    assert not guard.accept(packet(now, 2, session='old_server'))
    assert guard.accept(packet(now, 2))


def test_expiry_stops_once_and_heartbeat_recovery_does_not_clear_latch(env):
    now, guard = env
    guard.heartbeat(packet(now))
    now[0] = 3.0
    assert guard.expired(busy=True)
    assert not guard.expired(busy=True)
    guard.heartbeat(packet(now, 2))
    assert guard.healthy and guard.latched
    assert not guard.accept(packet(now))
    assert guard.accept(packet(now), reset=True)
    assert guard.accept(packet(now, 2))


def test_session_change_latches_and_old_messages_do_not_authorize_motion(env):
    now, guard = env
    guard.heartbeat(packet(now))
    assert guard.heartbeat(packet(now, session='server2'), busy=True)
    assert guard.latched
    assert not guard.accept(packet(now, 2, session='server1'), reset=True)
    assert guard.accept(packet(now, session='server2'), reset=True)
    assert not guard.heartbeat(packet(now, 2, session='server1'))
    assert guard.session == 'server2'
    assert not guard.accept(packet(now, 2, session='server1'))


def test_clock_skew_and_missing_issued_at_do_not_block(env):
    """PC 끼리 시계를 비교하지 않는다: 보낸 시각이 어긋나거나 없어도 통한다."""
    now, guard = env
    guard.heartbeat(packet(now, issued_at=1000 - 300))
    assert guard.healthy
    assert guard.accept(packet(now, issued_at=1000 + 300))
    plain = dict(session_id='server1', seq=2)
    assert guard.accept(plain)


def test_late_old_messages_after_link_loss_do_not_resume_motion(env):
    """5초 끊겨 잠긴 뒤 뒤늦게 온 옛 하트비트·명령으로는 움직이지 않는다."""
    now, guard = env
    guard.heartbeat(packet(now))
    assert guard.accept(packet(now, 1))
    now[0] = 5.0
    assert guard.expired(busy=True) and guard.latched
    # 옛 하트비트(순번 1)는 순번이 안 늘어 워치독을 살리지 못한다
    guard.heartbeat(packet(now, 1))
    assert not guard.healthy
    # 새 하트비트로 연결은 돌아와도 잠금은 그대로, 옛·새 일반 명령 모두 거절
    guard.heartbeat(packet(now, 2))
    assert guard.healthy and guard.latched
    assert not guard.accept(packet(now, 1))
    assert not guard.accept(packet(now, 2))
    assert guard.accept(packet(now, 2), reset=True) and not guard.latched


@pytest.mark.parametrize('changes', [
    {'seq': True}, {'seq': 0}, {'seq': '1'}, {'session_id': ''},
])
def test_invalid_packet_cannot_open_command_gate(env, changes):
    now, guard = env
    guard.heartbeat(packet(now, **changes))
    assert not guard.accept(packet(now, **changes))


def test_plain_stop_does_not_latch_but_emergency_stop_does(env):
    now, guard = env
    guard.heartbeat(packet(now))
    guard.stop()
    assert not guard.latched
    assert guard.accept(packet(now))
    guard.stop(emergency=True)
    assert guard.latched
    assert not guard.accept(packet(now, 2))
    assert guard.accept(packet(now, 3), reset=True)
    assert not guard.latched


def test_controller_restart_does_not_latch_an_idle_robot(env):
    """관제가 재시작해도 놀던 로봇은 잠그지 않는다. 옛 세션 명령은 여전히 버린다."""
    now, guard = env
    guard.heartbeat(packet(now))
    assert not guard.heartbeat(packet(now, session='server2'), busy=False)
    assert not guard.latched
    assert guard.accept(packet(now, session='server2'))
    assert not guard.accept(packet(now, 2, session='server1'))
    assert not guard.heartbeat(packet(now, 2, session='server1'), busy=False)


def test_link_loss_does_not_latch_an_idle_robot(env):
    """놀던 중 끊기면 잠그지 않는다. 끊긴 동안은 명령을 거절하고, 돌아오면 바로 받는다."""
    now, guard = env
    guard.heartbeat(packet(now))
    now[0] = 5.0
    assert not guard.expired(busy=False)
    assert not guard.latched
    assert not guard.accept(packet(now, 1))
    guard.heartbeat(packet(now, 2))
    assert guard.healthy
    assert guard.accept(packet(now, 1))
