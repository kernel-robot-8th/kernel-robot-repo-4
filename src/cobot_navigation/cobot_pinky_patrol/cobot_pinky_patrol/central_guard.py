"""기존 JSON 순찰 어댑터의 수신 감시와 세션·순번 기반 명령 차단."""

import math
import time


def number(value):
    """불리언이나 NaN을 유효한 만료 시간으로 취급하지 않는다."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class CentralGuard:
    """하트비트는 연결 상태만 복구하며 로컬 정지 잠금은 해제하지 않는다."""

    def __init__(self, timeout_sec=3.0, max_ttl_sec=5.0,
                 clock=time.monotonic, wall=time.time):
        self.timeout, self.max_ttl, self.clock, self.wall = timeout_sec, max_ttl_sec, clock, wall
        self.session = None
        self.heartbeat_seq = self.command_seq = 0
        self.received = None
        self.latched = False
        self.retired_sessions = set()

    @property
    def healthy(self):
        """로컬 수신 시각으로 중앙 서버의 연결 끊김을 감지한다."""
        return self.received is not None and self.clock() - self.received < self.timeout

    def _valid_time(self, payload):
        issued, ttl = payload.get('issued_at'), payload.get('ttl_sec')
        return (number(issued) and number(ttl) and 0 < ttl <= self.max_ttl
                and -1.0 <= self.wall() - issued < ttl)

    def heartbeat(self, payload):
        """서버 세션 변경으로 정지가 필요한지 반환한다."""
        if not isinstance(payload, dict) or not self._valid_time(payload):
            return False
        session, seq = payload.get('session_id'), payload.get('seq')
        if (not isinstance(session, str) or not session or isinstance(seq, bool)
                or not isinstance(seq, int) or seq <= 0 or session in self.retired_sessions):
            return False
        changed = self.session is not None and session != self.session
        if session == self.session and seq <= self.heartbeat_seq:
            return False
        if session != self.session:
            if self.session:
                self.retired_sessions.add(self.session)
            self.session, self.heartbeat_seq, self.command_seq = session, 0, 0
        if changed:
            self.latched = True
        self.heartbeat_seq, self.received = seq, self.clock()
        return changed

    def expired(self):
        """만료 시 한 번만 정지를 알린다. 이후에도 로봇 상태는 계속 발행해야 한다."""
        if self.received is not None and not self.healthy and not self.latched:
            self.latched = True
            return True
        return False

    def accept(self, payload, reset=False):
        """현재 세션에서 유효 시간 안에 수신한 순번이 증가하는 명령만 로봇을 이동시킬 수 있다."""
        if (not self.healthy or not self._valid_time(payload)
                or payload.get('session_id') != self.session or (self.latched and not reset)):
            return False
        seq = payload.get('seq')
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= self.command_seq:
            return False
        self.command_seq = seq
        if reset:
            self.latched = False
        return True
