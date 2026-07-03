"""Process-wide provider request spacing and short rate-limit blocking.

Profile health answers whether one configured endpoint is healthy. This module
answers whether any role may call the underlying provider right now. State is
shared across Trinity roles so concurrent tasks cannot burst one free-tier API.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


DEFAULT_MIN_INTERVALS = {
    "cerebras": 2.2,
    "gemini": 4.1,
    "openrouter": 2.0,
    "groq": 2.0,
    "nvidia": 1.0,
    "sambanova": 1.0,
    "xai": 1.0,
}


@dataclass
class ProviderState:
    next_allowed_at: float = 0.0
    blocked_until: float = 0.0
    reservations: int = 0
    rate_limits: int = 0
    total_wait_seconds: float = 0.0
    last_rate_limit_at: float = 0.0


class ProviderRateLimiter:
    """Thread-safe reservation queue that works across asyncio event loops."""

    def __init__(self, intervals: Optional[Dict[str, float]] = None):
        self._intervals = dict(DEFAULT_MIN_INTERVALS if intervals is None else intervals)
        self._states: Dict[str, ProviderState] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider: str) -> str:
        return str(provider or "unknown").strip().casefold()

    def min_interval(self, provider: str) -> float:
        key = self._key(provider)
        env_key = "URUK_PROVIDER_MIN_INTERVAL_" + "".join(
            char if char.isalnum() else "_" for char in key.upper()
        )
        raw = os.environ.get(env_key)
        if raw is not None:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
        return max(0.0, float(self._intervals.get(key, 0.0)))

    async def wait_for_slot(self, provider: str) -> dict:
        """Reserve one provider slot, wait for it, then recheck shared blocking."""
        key = self._key(provider)
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, ProviderState())
            if state.blocked_until > now:
                return {
                    "allowed": False,
                    "provider": key,
                    "waited_seconds": 0.0,
                    "retry_after_seconds": round(state.blocked_until - now, 3),
                }
            scheduled = max(now, state.next_allowed_at)
            wait_seconds = max(0.0, scheduled - now)
            state.next_allowed_at = scheduled + self.min_interval(key)
            state.reservations += 1
            state.total_wait_seconds += wait_seconds

        if wait_seconds:
            await asyncio.sleep(wait_seconds)

        # An in-flight sibling may have received 429 while this call waited.
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, ProviderState())
            if state.blocked_until > now:
                return {
                    "allowed": False,
                    "provider": key,
                    "waited_seconds": round(wait_seconds, 3),
                    "retry_after_seconds": round(state.blocked_until - now, 3),
                }
        return {
            "allowed": True,
            "provider": key,
            "waited_seconds": round(wait_seconds, 3),
            "retry_after_seconds": 0.0,
        }

    def record_rate_limit(self, provider: str, retry_after_seconds: Optional[float] = None) -> None:
        key = self._key(provider)
        delay = 30.0 if retry_after_seconds is None else max(1.0, float(retry_after_seconds))
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, ProviderState())
            state.rate_limits += 1
            state.last_rate_limit_at = time.time()
            state.blocked_until = max(state.blocked_until, now + delay)
            state.next_allowed_at = max(state.next_allowed_at, state.blocked_until)

    def clear(self, provider: Optional[str] = None) -> None:
        with self._lock:
            if provider is None:
                self._states.clear()
            else:
                self._states.pop(self._key(provider), None)

    def snapshot(self) -> Dict[str, dict]:
        now = time.monotonic()
        with self._lock:
            return {
                key: {
                    "min_interval_seconds": self.min_interval(key),
                    "blocked": state.blocked_until > now,
                    "blocked_remaining_seconds": round(max(0.0, state.blocked_until - now), 1),
                    "queued_delay_seconds": round(max(0.0, state.next_allowed_at - now), 1),
                    "reservations": state.reservations,
                    "rate_limits": state.rate_limits,
                    "total_wait_seconds": round(state.total_wait_seconds, 1),
                    "last_rate_limit_at": state.last_rate_limit_at,
                }
                for key, state in self._states.items()
            }


provider_rate_limiter = ProviderRateLimiter()
