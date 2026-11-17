"""Pure state machine: one B request per cycle, only after A completes."""
import math
from dataclasses import dataclass

@dataclass
class LidGate:
    threshold: float = .95
    hold_seconds: float = 1.0
    min_frames: int = 5
    max_age: float = .5
    max_gap: float = .4
    timeout: float = 30.0

    def __post_init__(self):
        if not (0 < self.threshold <= 1 and self.hold_seconds > 0 and self.min_frames >= 2
                and self.max_age > 0 and self.max_gap > 0 and self.timeout > self.hold_seconds):
            raise ValueError('Invalid gate parameters')
        self.cycle = None
        self.state = 'IDLE'
        self.seen_cycles = set()
        self.start = self.last = self.since = None
        self.count = 0

    def arm(self, cycle_id, now):
        """Invoke from A-success callback, after arm has stopped/cleared the box."""
        if not cycle_id or cycle_id in self.seen_cycles or not math.isfinite(now):
            raise ValueError('A new cycle ID and finite monotonic timestamp are required')
        self.seen_cycles.add(cycle_id)
        self.cycle, self.start, self.state = cycle_id, now, 'WAIT_CLOSED'
        self.last = self.since = None
        self.count = 0

    def reset_evidence(self):
        self.since, self.count = None, 0

    def tick(self, now):
        if self.state=='WAIT_CLOSED' and now-self.start >= self.timeout:
            self.state = 'TIMEOUT'
            self.reset_evidence()
        return self.state

    def observe(self, probability, captured_at, now, interlocks_ok=False):
        if self.tick(now) != 'WAIT_CLOSED':
            return False
        if (not all(math.isfinite(v) for v in [probability,captured_at,now])
                or not 0<=probability<=1 or not 0<=now-captured_at<=self.max_age
                or captured_at < self.start or (self.last is not None and captured_at<=self.last)):
            self.reset_evidence()
            return False
        if self.last is not None and captured_at-self.last>self.max_gap:
            self.reset_evidence()
        self.last = captured_at
        if not interlocks_ok or probability<self.threshold:
            self.reset_evidence()
            return False
        if self.since is None:
            self.since = captured_at
        self.count += 1
        if self.count>=self.min_frames and captured_at-self.since>=self.hold_seconds:
            self.state = 'B_REQUESTED'
            return True
        return False
