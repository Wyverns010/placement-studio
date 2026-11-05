"""In-memory sliding-window rate limiter: a per-client cap plus a process-wide cap."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Literal


class RateLimiter:
    """Per-client sliding window (``limit`` hits per ``window_s``) plus an optional process-wide
    cap (``global_limit`` hits per ``global_window_s``) on everything that gets through.

    Pattern: sliding-window log, one deque of timestamps per key, guarded by a lock. The clock is
    injected so tests can move time."""

    def __init__(self, limit: int = 12, window_s: float = 600.0, *,
                 global_limit: int | None = None, global_window_s: float = 3600.0,
                 clock=time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.global_limit, self.global_window_s = global_limit, global_window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, key: str, cost: int = 1) -> Literal["client", "global"] | None:
        """Record `cost` hits and return None if allowed; otherwise return which cap refused it
        ("client" first, then "global"). A refused request records nothing."""
        now = self.clock()
        with self._lock:
            for k in list(self._hits):
                d = self._hits[k]
                while d and now - d[0] >= self.window_s:
                    d.popleft()
                if not d:
                    del self._hits[k]
            while self._global and now - self._global[0] >= self.global_window_s:
                self._global.popleft()
            q = self._hits[key]
            if len(q) + cost > self.limit:
                refused = "client"
            elif self.global_limit is not None and len(self._global) + cost > self.global_limit:
                refused = "global"
            else:
                q.extend([now] * cost)
                self._global.extend([now] * cost)
                return None
            if not q:  # don't leave an empty bucket behind for a refused new client
                del self._hits[key]
            return refused
