"""Tests for authentication utilities."""

from app.api.auth import hash_api_key


def test_hash_api_key_deterministic():
    """Same key should produce the same hash."""
    key = "sk_test_abc123"
    h1 = hash_api_key(key)
    h2 = hash_api_key(key)
    assert h1 == h2


def test_hash_api_key_different_keys():
    """Different keys should produce different hashes."""
    h1 = hash_api_key("sk_key_one")
    h2 = hash_api_key("sk_key_two")
    assert h1 != h2


def test_hash_api_key_length():
    """SHA-256 should produce a 64-character hex string."""
    h = hash_api_key("any-key")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
