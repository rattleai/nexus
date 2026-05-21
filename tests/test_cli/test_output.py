"""Tests for CLI output formatting."""

import json

from app.cli.output import format_error_json, format_json, format_table


def test_format_json_wraps_in_envelope():
    result = format_json({"key": "value"})
    parsed = json.loads(result)
    assert parsed["status"] == "ok"
    assert parsed["data"]["key"] == "value"


def test_format_json_list():
    result = format_json([1, 2, 3])
    parsed = json.loads(result)
    assert parsed["data"] == [1, 2, 3]


def test_format_error_json():
    result = format_error_json("bad request", code="BAD_REQUEST", hint="fix it")
    parsed = json.loads(result)
    assert parsed["status"] == "error"
    assert parsed["code"] == "BAD_REQUEST"
    assert parsed["detail"] == "bad request"
    assert parsed["hint"] == "fix it"


def test_format_error_json_no_hint():
    result = format_error_json("fail")
    parsed = json.loads(result)
    assert "hint" not in parsed


def test_format_table_dict():
    result = format_table({"name": "test", "status": "ok"})
    assert "name" in result
    assert "test" in result


def test_format_table_list():
    data = [
        {"id": "1", "name": "alpha"},
        {"id": "2", "name": "beta"},
    ]
    result = format_table(data)
    assert "alpha" in result
    assert "beta" in result
    assert "id" in result


def test_format_table_empty_list():
    result = format_table([])
    assert "No results" in result


def test_format_table_with_title():
    result = format_table({"a": "b"}, title="Test")
    assert "Test" in result
