"""중앙 연결 감시가 오래되거나 재전송된 네트워크 메시지로 이동을 재개하지 않는지 검증한다."""

from cobot_pinky_patrol.central_guard import CentralGuard
import pytest


@pytest.fixture
def env():
    now = [0.0]
    guard = CentralGuard(clock=lambda: now[0], wall=lambda: 1000 + now[0])
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
    assert guard.expired()
    assert not guard.expired()
    guard.heartbeat(packet(now, 2))
    assert guard.healthy and guard.latched
    assert not guard.accept(packet(now))
    assert guard.accept(packet(now), reset=True)
    assert guard.accept(packet(now, 2))


def test_session_change_latches_and_old_messages_do_not_authorize_motion(env):
    now, guard = env
    guard.heartbeat(packet(now))
    assert guard.heartbeat(packet(now, session='server2'))
    assert guard.latched
    assert not guard.accept(packet(now, 2, session='server1'), reset=True)
    assert guard.accept(packet(now, session='server2'), reset=True)
    assert not guard.heartbeat(packet(now, 2, session='server1'))
    assert guard.session == 'server2'
    assert not guard.accept(packet(now, 2, session='server1'))


def test_delayed_heartbeat_does_not_refresh_watchdog(env):
    now, guard = env
    old = packet(now)
    guard.heartbeat(old)
    now[0] = 4
    guard.heartbeat(old)
    assert not guard.healthy
    assert guard.expired()


@pytest.mark.parametrize('changes', [
    {'seq': True}, {'seq': 0}, {'seq': '1'}, {'ttl_sec': 1000}, {'ttl_sec': float('nan')},
    {'issued_at': float('inf')}, {'issued_at': 1100}, {'session_id': ''},
])
def test_invalid_packet_cannot_open_command_gate(env, changes):
    now, guard = env
    guard.heartbeat(packet(now, **changes))
    assert not guard.accept(packet(now, **changes))
