"""Tests for circuit breaker pattern."""

from unittest.mock import patch

from app.core.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    def test_initially_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        with patch.object(cb, "_get_redis", return_value=None):
            assert cb.is_open("key1") is False

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        with patch.object(cb, "_get_redis", return_value=None):
            cb.record_failure("key1")
            cb.record_failure("key1")
            assert cb.is_open("key1") is False

            cb.record_failure("key1")
            assert cb.is_open("key1") is True

    def test_success_resets(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        with patch.object(cb, "_get_redis", return_value=None):
            cb.record_failure("key1")
            cb.record_failure("key1")
            assert cb.is_open("key1") is True

            cb.record_success("key1")
            assert cb.is_open("key1") is False

    def test_different_keys_independent(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        with patch.object(cb, "_get_redis", return_value=None):
            cb.record_failure("key1")
            cb.record_failure("key1")
            assert cb.is_open("key1") is True
            assert cb.is_open("key2") is False

    def test_host_key_extraction(self):
        assert CircuitBreaker.host_key("https://api.example.com/path") == "api.example.com"
        assert CircuitBreaker.host_key("http://localhost:8080/") == "localhost:8080"
