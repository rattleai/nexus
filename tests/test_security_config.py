"""Tests for agent security configuration validation at startup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import _validate_security_config


class TestSecurityConfigValidation:
    """Validate _validate_security_config rejects invalid configurations."""

    def test_invalid_prompt_firewall_fail_mode(self):
        """Invalid PROMPT_FIREWALL_FAIL_MODE raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "invalid"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            with pytest.raises(RuntimeError, match="PROMPT_FIREWALL_FAIL_MODE"):
                _validate_security_config()

    def test_invalid_data_classification_default_level(self):
        """Invalid DATA_CLASSIFICATION_DEFAULT_LEVEL raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INVALID"
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            with pytest.raises(RuntimeError, match="DATA_CLASSIFICATION_DEFAULT_LEVEL"):
                _validate_security_config()

    def test_warn_sigma_gte_suspend_sigma(self):
        """warn_sigma >= suspend_sigma raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 3.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            with pytest.raises(RuntimeError, match="WARN_SIGMA.*less than"):
                _validate_security_config()

    def test_warn_sigma_greater_than_suspend_sigma(self):
        """warn_sigma > suspend_sigma also raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 5.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            with pytest.raises(RuntimeError, match="WARN_SIGMA.*less than"):
                _validate_security_config()

    def test_invalid_sandbox_backend(self):
        """Invalid AGENT_SANDBOX_BACKEND raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            mock_settings.AGENT_SANDBOX_BACKEND = "docker"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            with pytest.raises(RuntimeError, match="AGENT_SANDBOX_BACKEND"):
                _validate_security_config()

    def test_valid_config_does_not_raise(self):
        """Valid configuration passes without error."""
        with patch("app.config.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
            mock_settings.DEBUG = True

            # Should not raise
            _validate_security_config()
