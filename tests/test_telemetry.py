"""Tests for OpenTelemetry integration."""

from unittest.mock import patch

import pytest


class TestSetupTelemetry:
    def test_noop_when_disabled(self):
        """setup_telemetry should be a no-op when OTEL_ENABLED=False."""
        import app.core.telemetry as tel

        tel._initialized = False

        with patch.object(tel, "settings") as mock_settings:
            mock_settings.OTEL_ENABLED = False
            tel.setup_telemetry("test-service")

        assert tel._initialized is False

    def test_get_tracer_returns_noop_when_disabled(self):
        """get_tracer should return a valid (no-op) tracer even when OTEL is disabled."""
        import app.core.telemetry as tel

        tel._tracer = None
        tracer = tel.get_tracer()
        assert tracer is not None

    def test_get_meter_returns_noop_when_disabled(self):
        """get_meter should return a valid (no-op) meter even when OTEL is disabled."""
        import app.core.telemetry as tel

        tel._meter = None
        meter = tel.get_meter()
        assert meter is not None


class TestOtelLogProcessor:
    def test_add_otel_context_no_active_span(self):
        """Should not crash when no span is active."""
        from app.core.logging import _add_otel_context

        event_dict = {"event": "test"}
        result = _add_otel_context(None, "info", event_dict)
        assert result["event"] == "test"
