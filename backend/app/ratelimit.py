"""Jednoduchý in-memory limiter (aplikace běží v jednom procesu)."""

from __future__ import annotations

import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 50_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._hits.setdefault(key, deque())
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        return bucket

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        return len(self._prune(key, now)) >= self.limit

    def hit(self, key: str) -> None:
        now = time.monotonic()
        if len(self._hits) > self.max_keys:
            self._gc(now)
        self._prune(key, now).append(now)

    def retry_after(self, key: str) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        return max(1, int(bucket[0] + self.window - time.monotonic()) + 1)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _gc(self, now: float) -> None:
        for key in list(self._hits):
            bucket = self._prune(key, now)
            if not bucket:
                del self._hits[key]


# Pokusy o přihlášení / ověření 2FA z jedné IP adresy.
login_ip_limiter = SlidingWindowLimiter(limit=20, window_seconds=15 * 60)
mfa_ip_limiter = SlidingWindowLimiter(limit=20, window_seconds=15 * 60)
# Ochrana NVR před zahlcením (snímky, testy připojení).
test_connection_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)
