"""Tests for cursor-based pagination utilities."""

import uuid
from datetime import UTC, datetime

from app.core.pagination import decode_cursor, encode_cursor


def test_encode_decode_datetime_cursor():
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    test_id = uuid.uuid4()
    cursor = encode_cursor(now, test_id)
    assert isinstance(cursor, str)
    decoded_sort, decoded_id = decode_cursor(cursor, datetime)
    assert decoded_sort == now
    assert decoded_id == test_id


def test_encode_decode_string_cursor():
    value = "some-id-value"
    test_id = uuid.uuid4()
    cursor = encode_cursor(value, test_id)
    decoded_sort, decoded_id = decode_cursor(cursor, str)
    assert decoded_sort == value
    assert decoded_id == test_id


def test_cursor_is_url_safe():
    """Cursors should not contain characters that need URL encoding."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    test_id = uuid.uuid4()
    cursor = encode_cursor(now, test_id)
    # url-safe base64 uses only alphanumeric, -, _, =
    for char in cursor:
        assert char.isalnum() or char in "-_=", f"Unexpected character: {char}"


def test_composite_cursor_deterministic():
    """Same inputs produce the same cursor."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    test_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    cursor1 = encode_cursor(now, test_id)
    cursor2 = encode_cursor(now, test_id)
    assert cursor1 == cursor2


def test_legacy_cursor_backwards_compatible():
    """Legacy single-value cursors should still decode without errors."""
    import base64

    raw = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC).isoformat()
    legacy_cursor = base64.urlsafe_b64encode(raw.encode()).decode()
    decoded_sort, decoded_id = decode_cursor(legacy_cursor, datetime)
    assert decoded_sort == datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    # Legacy cursors get a zero UUID as fallback id
    assert decoded_id == uuid.UUID(int=0)
