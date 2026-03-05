"""Tests for cursor-based pagination utilities."""

from datetime import UTC, datetime

from app.core.pagination import decode_cursor, encode_cursor


def test_encode_decode_datetime_cursor():
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    cursor = encode_cursor(now)
    assert isinstance(cursor, str)
    decoded = decode_cursor(cursor, datetime)
    assert decoded == now


def test_encode_decode_string_cursor():
    value = "some-id-value"
    cursor = encode_cursor(value)
    decoded = decode_cursor(cursor, str)
    assert decoded == value


def test_cursor_is_url_safe():
    """Cursors should not contain characters that need URL encoding."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    cursor = encode_cursor(now)
    # url-safe base64 uses only alphanumeric, -, _, =
    for char in cursor:
        assert char.isalnum() or char in "-_=", f"Unexpected character: {char}"
