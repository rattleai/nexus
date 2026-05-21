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
        self._redis_init_attempted = False
        self._redis_init_lock = threading.Lock()

    def _get_redis(self):
        """Lazy-init a sync Redis client. Returns None if unavailable.

        Uses _redis_init_attempted to avoid retrying on every call when Redis
        is down, preventing connection storms against an unavailable instance.
        """
        if self._redis is not None:
            return self._redis
        if self._redis_init_attempted:
            return None
        with self._redis_init_lock:
            if self._redis is not None:
                return self._redis
            if self._redis_init_attempted:
                return None
            try:
                import redis as sync_redis

                client = sync_redis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                client.ping()
                self._redis = client
            except Exception:
                logger.warning(
                    "circuit_breaker_redis_unavailable",
                    breaker=self.name,
                )
            self._redis_init_attempted = True
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
        was_open = self.is_open(key)
        r = self._get_redis()

        if r is not None:
            try:
                r.delete(self._redis_failures_key(key), self._redis_last_fail_key(key))
                if was_open:
                    logger.info("circuit_breaker_closed", breaker=self.name, key=key)
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error", breaker=self.name)

        with self._lock:
            self._failures.pop(key, None)
            self._last_failure_time.pop(key, None)

        if was_open:
            logger.info("circuit_breaker_closed", breaker=self.name, key=key)

    def _evict_stale_keys(self) -> None:
        """Remove stale in-memory entries to prevent unbounded growth.

        Called periodically during record_failure to keep memory bounded.
        Only runs when in-memory fallback has grown beyond a threshold.
        """
        max_keys = 10_000
        with self._lock:
            if len(self._failures) <= max_keys:
                return
            now = time.time()
            stale_keys = [k for k, t in self._last_failure_time.items() if now - t > self.recovery_timeout * 2]
            for k in stale_keys:
                self._failures.pop(k, None)
                self._last_failure_time.pop(k, None)
            if stale_keys:
                logger.info("circuit_breaker_evicted_stale", breaker=self.name, evicted=len(stale_keys))

    def record_failure(self, key: str) -> None:
        """Record a failure and potentially open the circuit."""
        was_open = self.is_open(key)
        r = self._get_redis()
        expiry = self.recovery_timeout * 2

        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.incr(self._redis_failures_key(key))
                pipe.expire(self._redis_failures_key(key), expiry)
                pipe.set(self._redis_last_fail_key(key), str(time.time()), ex=expiry)
                results = pipe.execute()
                new_count = results[0]
                if not was_open and new_count >= self.failure_threshold:
                    logger.warning(
                        "circuit_breaker_opened",
                        breaker=self.name,
                        key=key,
                        failures=new_count,
                        recovery_timeout=self.recovery_timeout,
                    )
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error", breaker=self.name)

        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1
            self._last_failure_time[key] = time.time()
            new_count = self._failures[key]

        if not was_open and new_count >= self.failure_threshold:
            logger.warning(
                "circuit_breaker_opened",
                breaker=self.name,
                key=key,
                failures=new_count,
                recovery_timeout=self.recovery_timeout,
            )

        self._evict_stale_keys()

    def get_state(self, key: str) -> dict:
        """Return the circuit state for API error responses.

        Exposes circuit_state and retry_after_seconds so clients can
        implement backoff without polling.
        """
        r = self._get_redis()
        failures = 0
        last_fail = 0.0

        if r is not None:
            try:
                failures = int(r.get(self._redis_failures_key(key)) or 0)
                last_fail = float(r.get(self._redis_last_fail_key(key)) or 0)
            except Exception:
                pass

        if failures == 0:
            with self._lock:
                failures = self._failures.get(key, 0)
                last_fail = self._last_failure_time.get(key, 0)

        if failures < self.failure_threshold:
            return {"circuit_state": "closed", "retry_after_seconds": 0}

        elapsed = time.time() - last_fail
        if elapsed > self.recovery_timeout:
            return {"circuit_state": "half_open", "retry_after_seconds": 0}

        return {
            "circuit_state": "open",
            "retry_after_seconds": max(0, int(self.recovery_timeout - elapsed)),
        }

    @staticmethod
    def host_key(url: str) -> str:
        """Extract host from URL for use as a circuit breaker key."""
        return urlparse(url).netloc


# Pre-configured breakers for common external dependencies
webhook_breaker = CircuitBreaker("webhook", failure_threshold=5, recovery_timeout=300)
storage_breaker = CircuitBreaker("storage", failure_threshold=3, recovery_timeout=120)
email_breaker = CircuitBreaker("email", failure_threshold=3, recovery_timeout=180)
oauth_breaker = CircuitBreaker("oauth", failure_threshold=5, recovery_timeout=300)
ai_breaker = CircuitBreaker("ai", failure_threshold=3, recovery_timeout=60)
