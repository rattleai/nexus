"""Tests for the retry decorator."""

import pytest

from app.core.retry import retry


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


@pytest.mark.asyncio
async def test_retry_succeeds_first_try():
    call_count = 0

    @retry(max_attempts=3, base_delay=0.01, retryable=(TransientError,))
    async def succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await succeeds()
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_succeeds_after_failures():
    call_count = 0

    @retry(max_attempts=3, base_delay=0.01, retryable=(TransientError,))
    async def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TransientError("transient")
        return "recovered"

    result = await fails_twice()
    assert result == "recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted():
    call_count = 0

    @retry(max_attempts=2, base_delay=0.01, retryable=(TransientError,))
    async def always_fails():
        nonlocal call_count
        call_count += 1
        raise TransientError("always fails")

    with pytest.raises(TransientError, match="always fails"):
        await always_fails()
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_non_retryable_exception():
    call_count = 0

    @retry(max_attempts=3, base_delay=0.01, retryable=(TransientError,))
    async def fails_permanently():
        nonlocal call_count
        call_count += 1
        raise PermanentError("permanent")

    with pytest.raises(PermanentError, match="permanent"):
        await fails_permanently()
    assert call_count == 1  # No retry for non-retryable exceptions
