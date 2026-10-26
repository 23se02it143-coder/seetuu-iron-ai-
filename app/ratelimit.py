"""A small in-memory sliding-window rate limiter.

Good for a single-process deployment. If you run several workers or instances,
swap `limiter` for a Redis-backed implementation with the same `hit()` signature.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import ApiError


def client_ip(request: Request) -> str:
    # uvicorn's --proxy-headers already rewrites request.client for trusted proxies.
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, max(1, math.ceil(bucket[0] + window - now))
            bucket.append(now)
            if now - self._last_sweep > 300:
                self._sweep(now, window)
            return True, 0

    def _sweep(self, now: float, window: float) -> None:
        self._last_sweep = now
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - max(window, 3600)]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limit(bucket: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: `dependencies=[Depends(rate_limit("waitlist", 5, 600))]`."""

    def dependency(request: Request, settings: Settings = Depends(get_settings)) -> None:
        if not settings.rate_limit_enabled:
            return
        allowed, retry_after = limiter.hit(f"{bucket}:{client_ip(request)}", limit, window_seconds)
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                f"Too many requests. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
