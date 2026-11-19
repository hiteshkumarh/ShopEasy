"""Pluggable rate limiting architecture for ShopEasy authentication and public endpoints.

Design:
- Abstract RateLimitBackend defines interface for request tracking and reset.
- InMemoryRateLimitBackend provides local sliding-window tracking (default for local & single-instance dev/testing).
- Ready for RedisRateLimitBackend to support shared multi-instance Render deployments.
- Clean reset functionality ensures complete test isolation without inter-test interference.
- Generic 429 responses avoid exposing whether a phone number or account is registered.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, status

logger = logging.getLogger("shopeasy.rate_limit")


class RateLimitBackend(ABC):
    """Abstract interface for rate limiter storage backends."""

    @abstractmethod
    def record_and_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int]:
        """Record a request and check whether the rate limit is exceeded.

        Args:
            key: Unique identifier (e.g. "login:192.168.1.1").
            max_requests: Maximum allowed requests within window.
            window_seconds: Duration of the rate limit window in seconds.

        Returns:
            Tuple of (is_allowed: bool, retry_after_seconds: int).
        """
        pass

    @abstractmethod
    def reset(self, key_prefix: Optional[str] = None) -> None:
        """Reset all tracked keys or keys matching an optional prefix (used for test isolation)."""
        pass


class InMemoryRateLimitBackend(RateLimitBackend):
    """Thread-safe sliding-window rate limit backend using in-memory timestamps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[str, List[float]] = defaultdict(list)

    def record_and_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            timestamps = self._store[key]
            # Prune timestamps older than window_seconds
            cutoff = now - window_seconds
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(valid_timestamps) >= max_requests:
                oldest_timestamp = valid_timestamps[0]
                retry_after = int(window_seconds - (now - oldest_timestamp)) + 1
                self._store[key] = valid_timestamps
                return False, max(1, retry_after)

            valid_timestamps.append(now)
            self._store[key] = valid_timestamps
            return True, 0

    def reset(self, key_prefix: Optional[str] = None) -> None:
        with self._lock:
            if key_prefix is None:
                self._store.clear()
            else:
                keys_to_remove = [k for k in self._store if k.startswith(key_prefix)]
                for k in keys_to_remove:
                    del self._store[k]


# Singleton backend instance
_active_backend: RateLimitBackend = InMemoryRateLimitBackend()


def get_rate_limiter() -> RateLimitBackend:
    """Return the active rate limiter backend singleton."""
    return _active_backend


def set_rate_limiter(backend: RateLimitBackend) -> None:
    """Configure a custom rate limiter backend (e.g. for Redis in multi-instance production)."""
    global _active_backend
    _active_backend = backend


def clear_rate_limits(key_prefix: Optional[str] = None) -> None:
    """Reset rate limiter state. Called by test fixtures to ensure test isolation."""
    _active_backend.reset(key_prefix=key_prefix)


def rate_limit(
    action: str,
    max_requests: int = 10,
    window_seconds: int = 60,
) -> Callable[[Request], None]:
    """FastAPI dependency for rate limiting by client IP and action.

    Enforces:
      - Extracts client IP safely from X-Forwarded-For or request client.
      - Uses generic key format 'action:client_ip' so phone registration status is never leaked.
      - Returns HTTP 429 Too Many Requests with standard 'Retry-After' header.
    """

    def dependency(request: Request) -> None:
        # Determine client IP
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host
        else:
            client_ip = "127.0.0.1"

        key = f"{action}:{client_ip}"
        is_allowed, retry_after = _active_backend.record_and_check(
            key=key,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

        if not is_allowed:
            logger.warning(
                f"Rate limit exceeded for action '{action}' from IP '{client_ip}'. "
                f"Retry-After: {retry_after}s"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
