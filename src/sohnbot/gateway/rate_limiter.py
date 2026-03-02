"""Async sliding-window rate limiter for outbound Telegram messages."""

from __future__ import annotations

import asyncio
from collections import deque
import time

import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Sliding-window limiter that enforces at most N events per 60 seconds."""

    def __init__(self, max_per_minute: int = 30):
        self.max_per_minute = max(1, int(max_per_minute))
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._above_warning_threshold = False

    def _purge_old_locked(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] > 60:
            self._timestamps.popleft()

    def _update_pressure_warning_locked(self) -> None:
        used = len(self._timestamps)
        threshold = self.max_per_minute * 0.8
        above = used >= threshold
        if above and not self._above_warning_threshold:
            logger.warning(
                "telegram_rate_limiter_pressure",
                used=used,
                max_per_minute=self.max_per_minute,
                usage_ratio=(used / self.max_per_minute),
            )
        self._above_warning_threshold = above

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._purge_old_locked(now)
                self._update_pressure_warning_locked()
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    self._update_pressure_warning_locked()
                    return
                wait = max(0.0, 60 - (now - self._timestamps[0]) + 0.1)
            await asyncio.sleep(wait)

    async def try_acquire(self) -> bool:
        """Attempt to consume token without waiting; returns True on success."""
        async with self._lock:
            now = time.monotonic()
            self._purge_old_locked(now)
            self._update_pressure_warning_locked()
            if len(self._timestamps) >= self.max_per_minute:
                return False
            self._timestamps.append(now)
            self._update_pressure_warning_locked()
            return True
