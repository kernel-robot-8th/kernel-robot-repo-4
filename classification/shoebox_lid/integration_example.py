"""Wire these methods to the existing controller; never start B from an MQTT observation."""
from gate import LidGate
from infer import TopPredictor

class PackagingHandoff:
    def __init__(self, selection, request_b, device='cpu'):
        self.vision = TopPredictor(selection, device)
        self.gate = LidGate(threshold=self.vision.threshold)
        self.request_b = request_b

    def on_a_completed(self, order_id, monotonic_now):
        self.gate.arm(order_id, monotonic_now)

    def on_top_frame(self, bgr, capture_monotonic, now_fn, interlocks_fn):
        # capture_monotonic must originate at acquisition, not after inference.
        probs = self.vision.predict(bgr)
        if self.gate.observe(probs['closed_verified'], capture_monotonic, now_fn(), interlocks_fn()):
            # Existing controller owns motion and checks order ID / arm clear /
            # Pinky docked and stationary / emergency stop again, atomically.
            self.request_b(self.gate.cycle)
        return self.gate.state, probs

    def on_timer(self, monotonic_now):
        # Call even when no image arrives; TIMEOUT must never trigger B.
        return self.gate.tick(monotonic_now)
