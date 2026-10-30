"""In-memory sliding-window rate limiter keyed by client id."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int = 12, window_s: float = 600.0, clock=time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a hit and return True if under the limit; False (not recorded) otherwise."""
        now = self.clock()
        with self._lock:
            for k in list(self._hits):
                d = self._hits[k]
                while d and now - d[0] >= self.window_s:
                    d.popleft()
                if not d:
                    del self._hits[k]
            q = self._hits[key]
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
