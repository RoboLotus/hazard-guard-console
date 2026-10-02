"""Experiment-only input gate. Drops display work, never queues old frames."""
import math


class EncodeGate:
    def __init__(self):
        self.next_at = None

    def reset(self):
        self.next_at = None

    def allow(self, now, fps):
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be finite and positive")
        period = 1 / fps
        if self.next_at is None:
            self.next_at = now + period
            return True
        if now + 1e-9 < self.next_at:
            return False
        self.next_at += (math.floor(max(0, now - self.next_at) / period) + 1) * period
        return True
