"""Generic circuit breaker pattern for external dependencies.

Extracted from webhook-specific implementation for reuse across S3, OAuth,
email, and other external service calls.

States:
  - CLOSED: normal operation, requests pass through.
  - OPEN: too many failures, requests rejected immediately.
  - HALF_OPEN: after cooldown, allow one probe request.
"""

import threading
import time
from collections import defaultdict
from urllib.parse import urlparse

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


class CircuitBreaker:
    """Per-key circuit breaker with Redis-backed shared state and in-memory fallback."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 300,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        # In-memory fallback
        self._failures: dict[str, int] = defaultdict(int)
        self._last_failure_time: dict[str, float] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._redis_init_lock = threading.Lock()

    def _get_redis(self):
        """Lazy-init a sync Redis client. Returns None if unavailable."""
        if self._redis is None:
            with self._redis_init_lock:
                if self._redis is None:
                    try:
                        import redis as sync_redis

                        self._redis = sync_redis.from_url(
                            settings.REDIS_URL,
                            socket_connect_timeout=2,
                            socket_timeout=2,
                        )
                        self._redis.ping()
                    except Exception:
                        logger.warning(
                            "circuit_breaker_redis_unavailable",
                            breaker=self.name,
                        )
                        self._redis = None
        return self._redis

    def _redis_failures_key(self, key: str) -> str:
        return f"cb:{self.name}:{key}:failures"

    def _redis_last_fail_key(self, key: str) -> str:
        return f"cb:{self.name}:{key}:last_fail"

    def is_open(self, key: str) -> bool:
        """Return True if the circuit is open (should NOT attempt the call)."""
        r = self._get_redis()

        if r is not None:
            try:
                failures = int(r.get(self._redis_failures_key(key)) or 0)
                if failures < self.failure_threshold:
                    return False
                last_fail = float(r.get(self._redis_last_fail_key(key)) or 0)
                return time.time() - last_fail <= self.recovery_timeout
            except Exception:
                logger.warning("circuit_breaker_redis_read_error", breaker=self.name)

        # In-memory fallback
        with self._lock:
            failures = self._failures.get(key, 0)
            if failures < self.failure_threshold:
                return False
            last_fail = self._last_failure_time.get(key, 0)
            return time.time() - last_fail <= self.recovery_timeout

    def record_success(self, key: str) -> None:
        """Reset the circuit after a successful call."""
        r = self._get_redis()

        if r is not None:
            try:
                r.delete(self._redis_failures_key(key), self._redis_last_fail_key(key))
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error", breaker=self.name)

        with self._lock:
            self._failures.pop(key, None)
            self._last_failure_time.pop(key, None)

    def record_failure(self, key: str) -> None:
        """Record a failure and potentially open the circuit."""
        r = self._get_redis()
        expiry = self.recovery_timeout * 2

        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.incr(self._redis_failures_key(key))
                pipe.expire(self._redis_failures_key(key), expiry)
                pipe.set(self._redis_last_fail_key(key), str(time.time()), ex=expiry)
                pipe.execute()
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error", breaker=self.name)

        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1
            self._last_failure_time[key] = time.time()

    @staticmethod
    def host_key(url: str) -> str:
        """Extract host from URL for use as a circuit breaker key."""
        return urlparse(url).netloc


# Pre-configured breakers for common external dependencies
webhook_breaker = CircuitBreaker("webhook", failure_threshold=5, recovery_timeout=300)
storage_breaker = CircuitBreaker("storage", failure_threshold=3, recovery_timeout=120)
email_breaker = CircuitBreaker("email", failure_threshold=3, recovery_timeout=180)
oauth_breaker = CircuitBreaker("oauth", failure_threshold=5, recovery_timeout=300)
