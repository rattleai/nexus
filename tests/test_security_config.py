"""Tests for agent security configuration validation at startup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import _validate_security_config


def _baseline_settings(mock_settings) -> None:
    """Populate every attribute the validator reads with valid defaults.

    The validation routine has grown to cover RAG/vector knobs as well as
    the original agent security settings; tests previously only set the
    agent attributes, leaving the new ones as MagicMock instances which
    blew up on numeric comparisons (`0.0 <= MagicMock`).
    """
    # Agent security
    mock_settings.PROMPT_FIREWALL_FAIL_MODE = "block"
    mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
    mock_settings.AGENT_SANDBOX_BACKEND = "auto"
    mock_settings.AGENT_DB_STATEMENT_TIMEOUT_MS = 5000
    mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
    mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0
    mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
    mock_settings.AGENT_A2A_ENCRYPTION_ENABLED = True
    mock_settings.PROMPT_FIREWALL_ENABLED = True
    mock_settings.DEBUG = True
    # RAG / vector
    mock_settings.VECTOR_QUANTIZATION = "full"
    mock_settings.RAG_CHUNKING_STRATEGY = "fixed_size"
    mock_settings.RAG_RERANKER_PROVIDER = "none"
    mock_settings.VECTOR_INDEX_TYPE = "hnsw"
    mock_settings.RAG_QUERY_LOG_SAMPLE_RATE = 0.1
    mock_settings.RAG_QUERY_CACHE_SIMILARITY_THRESHOLD = 0.9


class TestSecurityConfigValidation:
    """Validate _validate_security_config rejects invalid configurations."""

    def test_invalid_prompt_firewall_fail_mode(self):
        """Invalid PROMPT_FIREWALL_FAIL_MODE raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)
            mock_settings.PROMPT_FIREWALL_FAIL_MODE = "invalid"

            with pytest.raises(RuntimeError, match="PROMPT_FIREWALL_FAIL_MODE"):
                _validate_security_config()

    def test_invalid_data_classification_default_level(self):
        """Invalid DATA_CLASSIFICATION_DEFAULT_LEVEL raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INVALID"

            with pytest.raises(RuntimeError, match="DATA_CLASSIFICATION_DEFAULT_LEVEL"):
                _validate_security_config()

    def test_warn_sigma_gte_suspend_sigma(self):
        """warn_sigma >= suspend_sigma raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 3.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0

            with pytest.raises(RuntimeError, match=r"WARN_SIGMA.*less than"):
                _validate_security_config()

    def test_warn_sigma_greater_than_suspend_sigma(self):
        """warn_sigma > suspend_sigma also raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 5.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0

            with pytest.raises(RuntimeError, match=r"WARN_SIGMA.*less than"):
                _validate_security_config()

    def test_invalid_sandbox_backend(self):
        """Invalid AGENT_SANDBOX_BACKEND raises RuntimeError."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)
            mock_settings.AGENT_SANDBOX_BACKEND = "docker"

            with pytest.raises(RuntimeError, match="AGENT_SANDBOX_BACKEND"):
                _validate_security_config()

    def test_valid_config_does_not_raise(self):
        """Valid configuration passes without error."""
        with patch("app.config.settings") as mock_settings:
            _baseline_settings(mock_settings)

            # Should not raise
            _validate_security_config()
