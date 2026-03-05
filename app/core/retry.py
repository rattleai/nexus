"""Retry decorator for transient failures in async external calls.

Provides exponential backoff with jitter for resilient external service
communication (HTTP calls, email, storage, etc.).

Usage:
    from app.core.retry import retry

    @retry(max_attempts=3, base_delay=1.0, retryable=(httpx.TransportError,))
    async def call_external_api(url: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
"""

import asyncio
import functools
import random
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

logger = structlog.stdlib.get_logger()


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Retry decorator with exponential backoff and jitter.

    Args:
        max_attempts: Maximum number of attempts (including the first try).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Base for exponential backoff calculation.
        jitter: Add random jitter to prevent thundering herd.
        retryable: Tuple of exception types that trigger a retry.
    """

    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable as exc:
                    last_exception = exc

                    if attempt == max_attempts:
                        logger.error(
                            "retry_exhausted",
                            func=func.__qualname__,
                            attempts=attempt,
                            error=str(exc),
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    if jitter:
                        delay = delay * (0.5 + random.random() * 0.5)

                    logger.warning(
                        "retry_attempt",
                        func=func.__qualname__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

            # Should not reach here, but raise if it does
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
