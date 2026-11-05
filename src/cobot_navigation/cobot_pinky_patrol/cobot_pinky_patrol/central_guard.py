"""Receipt watchdog and session/sequence fencing for the existing JSON patrol adapter."""

import math
import time


def number(value):
    """Do not treat bool or NaN as a usable lease value."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class CentralGuard:
    """A heartbeat revives liveness but never clears a local stop latch."""

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
        """Use local receipt time to detect an unavailable central server."""
        return self.received is not None and self.clock() - self.received < self.timeout

    def _valid_time(self, payload):
        issued, ttl = payload.get('issued_at'), payload.get('ttl_sec')
        return (number(issued) and number(ttl) and 0 < ttl <= self.max_ttl
                and -1.0 <= self.wall() - issued < ttl)

    def heartbeat(self, payload):
        """Return whether a server session change requires a stop."""
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
        """Fire once on expiry; the robot must keep publishing its status afterwards."""
        if self.received is not None and not self.healthy and not self.latched:
            self.latched = True
            return True
        return False

    def accept(self, payload, reset=False):
        """Only a fresh, increasing command from the current session may move the base."""
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
