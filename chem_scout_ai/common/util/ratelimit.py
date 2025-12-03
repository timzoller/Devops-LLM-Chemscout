"""Very small, lightweight rate limiter used by the backend module."""

import time
import threading


class RateLimiter:
    """
    Simple rate limiter that enforces *minimum* delay between calls.

    If rate is None → limiter is disabled.
    """

    def __init__(self, rate: float | None) -> None:
        # rate = allowed calls per second → convert to minimum interval
        self.enabled = rate is not None
        self.min_interval = 1.0 / rate if rate else 0.0
        self._last_call = 0.0
        self._lock = threading.Lock()

    def __enter__(self):
        if not self.enabled:
            return

        with self._lock:
            now = time.time()
            elapsed = now - self._last_call

            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)

            self._last_call = time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
