"""기존 JSON 순찰 어댑터의 수신 감시와 세션·순번 기반 명령 차단.

PC 끼리 시계를 비교하지 않는다 (관제가 붙인 issued_at·ttl_sec 는 보지 않음, 2026-11-09).
보통 방식대로 끊김은 받는 쪽 monotonic 시계로, 옛·중복 메시지는 세션·순번으로,
끊긴 뒤에는 잠금으로 막는다. 시계 비교는 두 PC 시계가 1초만 어긋나도 정상 명령을
모두 거절해서 뺐다 (되살리려면 git 97be6c7).
"""

import time


class CentralGuard:
    """하트비트는 연결 상태만 복구하며 로컬 정지 잠금은 해제하지 않는다."""

    def __init__(self, timeout_sec=3.0, clock=time.monotonic):
        self.timeout, self.clock = timeout_sec, clock
        self.session = None
        self.heartbeat_seq = self.command_seq = 0
        self.received = None
        self.latched = False
        self.retired_sessions = set()

    @property
    def healthy(self):
        """로컬 수신 시각으로 중앙 서버의 연결 끊김을 감지한다."""
        return self.received is not None and self.clock() - self.received < self.timeout

    def heartbeat(self, payload):
        """서버 세션 변경으로 정지가 필요한지 반환한다."""
        if not isinstance(payload, dict):
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

    def stop(self, emergency=False):
        """정지는 하트비트·세션과 상관없이 늘 받는다. 잠금은 비상정지만 건다."""
        # 일반 정지는 멈추고(구역 안이면 물러나) 끝나며 다음 명령을 바로 받는다
        # (진호 님 원래 순찰 노드 기준, 2026-11-09). 제자리에 세우고 잠그려면 비상정지를 쓴다.
        if emergency:
            self.latched = True

    def accept(self, payload, reset=False):
        """연결이 살아 있을 때 현재 세션에서 순번이 늘어나는 명령만 로봇을 이동시킬 수 있다."""
        if (not self.healthy or not isinstance(payload, dict)
                or payload.get('session_id') != self.session or (self.latched and not reset)):
            return False
        seq = payload.get('seq')
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= self.command_seq:
            return False
        self.command_seq = seq
        if reset:
            self.latched = False
        return True
