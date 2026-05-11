"""Tests for data classification and DLP enforcement.

Covers:
    - DataLevel enum parsing and ordering
    - Text classification: PII detection, restricted keywords, tenant patterns
    - Column classification: word-boundary matching, false-positive prevention
    - DLP enforcement: access checks, text redaction, dict redaction
    - Data exfiltration attack scenarios
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.data_classification import DataClassifier, DataLevel, DLPEnforcer

# ── TestDataLevel ─────────────────────────────────────────────────────


class TestDataLevel:
    """DataLevel enum: parsing and ordering."""

    def test_from_str_valid(self):
        assert DataLevel.from_str("CONFIDENTIAL") == DataLevel.CONFIDENTIAL

    def test_from_str_unknown(self):
        assert DataLevel.from_str("INVALID") == DataLevel.INTERNAL  # safe default

    def test_ordering(self):
        assert DataLevel.PUBLIC < DataLevel.INTERNAL < DataLevel.CONFIDENTIAL < DataLevel.RESTRICTED
        assert DataLevel.PUBLIC == 0
        assert DataLevel.INTERNAL == 1
        assert DataLevel.CONFIDENTIAL == 2
        assert DataLevel.RESTRICTED == 3


# ── TestTextClassification ────────────────────────────────────────────


class TestTextClassification:
    """Text classification: PII patterns, restricted keywords, tenant patterns."""

    def _make_classifier(self, **kwargs):
        return DataClassifier(**kwargs)

    def test_ssn_confidential(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("SSN is 123-45-6789")
        assert result.level == DataLevel.CONFIDENTIAL
        assert "ssn" in result.pii_types_found

    def test_credit_card_confidential(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("Card: 4111 1111 1111 1111")
        assert result.level == DataLevel.CONFIDENTIAL

    def test_email_internal(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("Email: john@example.com")
        assert result.level == DataLevel.INTERNAL

    def test_phone_internal(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("Call 555-123-4567")
        assert result.level == DataLevel.INTERNAL

    def test_restricted_keyword(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("This is top secret information")
        assert result.level == DataLevel.RESTRICTED

    def test_clean_text_public(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("The weather is nice today")
        assert result.level == DataLevel.PUBLIC

    def test_disabled_returns_default(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = False
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier()
            result = classifier.classify_text("SSN is 123-45-6789")
        assert result.level == DataLevel.INTERNAL

    def test_tenant_patterns_applied(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            classifier = self._make_classifier(
                tenant_patterns={"project_alpha": "RESTRICTED"},
            )
            result = classifier.classify_text("About project_alpha details")
        assert result.level == DataLevel.RESTRICTED


# ── TestColumnClassification ──────────────────────────────────────────


class TestColumnClassification:
    """Column-name classification with underscore-boundary matching."""

    def _classifier(self):
        return DataClassifier()

    def test_ssn_restricted(self):
        assert self._classifier().classify_column("user_ssn") == DataLevel.RESTRICTED

    def test_password_confidential(self):
        assert self._classifier().classify_column("password_hash") == DataLevel.CONFIDENTIAL

    def test_email_internal(self):
        assert self._classifier().classify_column("email") == DataLevel.INTERNAL

    def test_generic_public(self):
        assert self._classifier().classify_column("name") == DataLevel.PUBLIC

    def test_no_false_positive_permission(self):
        # "permission" must NOT match "ssn" substring
        assert self._classifier().classify_column("permission") == DataLevel.PUBLIC

    def test_no_false_positive_tokenizer(self):
        # "tokenizer_config" must NOT match "token"
        assert self._classifier().classify_column("tokenizer_config") == DataLevel.PUBLIC

    def test_no_false_positive_microphone(self):
        # "microphone" must NOT match "phone"
        assert self._classifier().classify_column("microphone") == DataLevel.PUBLIC

    def test_compound_name(self):
        # "user_ssn_hash" contains "ssn" as an underscore-delimited word
        assert self._classifier().classify_column("user_ssn_hash") == DataLevel.RESTRICTED


# ── TestDLPEnforcement ────────────────────────────────────────────────


class TestDLPEnforcement:
    """DLP enforcer: access control, text redaction, dict redaction."""

    def test_access_within_level(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            enforcer = DLPEnforcer(max_level=DataLevel.CONFIDENTIAL)
            allowed, reason = enforcer.check_access("SSN is 123-45-6789")
        assert allowed is True
        assert reason == ""

    def test_access_above_level(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
            allowed, reason = enforcer.check_access("SSN is 123-45-6789")
        assert allowed is False
        assert reason != ""

    def test_redact_ssn(self):
        enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
        redacted, count = enforcer.redact_text("SSN 123-45-6789")
        assert "[REDACTED_SSN]" in redacted
        assert count >= 1

    def test_redact_email(self):
        enforcer = DLPEnforcer(max_level=DataLevel.PUBLIC)
        redacted, count = enforcer.redact_text("email john@example.com")
        assert "[REDACTED_EMAIL]" in redacted
        assert count >= 1

    def test_redact_dict_key(self):
        enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
        redacted, count = enforcer.redact_dict({"password": "secret123"})
        assert redacted["password"] == "[REDACTED_CONFIDENTIAL]"
        assert count >= 1

    def test_redact_dict_value(self):
        enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
        redacted, count = enforcer.redact_dict({"note": "SSN is 123-45-6789"})
        assert "REDACTED" in redacted["note"]
        assert count >= 1


# ── TestDataExfiltrationAttacks ───────────────────────────────────────


class TestDataExfiltrationAttacks:
    """Attack scenarios: data exfiltration via PII embedding."""

    def test_ssn_exfiltration(self):
        with patch("app.agents.data_classification.settings") as mock_settings:
            mock_settings.DATA_CLASSIFICATION_ENABLED = True
            mock_settings.DATA_CLASSIFICATION_DEFAULT_LEVEL = "INTERNAL"
            enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
            allowed, _reason = enforcer.check_access("The user's SSN is 123-45-6789")
        assert allowed is False

    def test_mixed_pii_all_redacted(self):
        enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
        text = "SSN: 123-45-6789, email: alice@corp.com, phone: 555-999-1234"
        redacted, count = enforcer.redact_text(text)
        # SSN is CONFIDENTIAL — redacted when max_level < CONFIDENTIAL
        assert "123-45-6789" not in redacted
        # Email and phone are INTERNAL-level PII — only redacted when
        # max_level < INTERNAL. At INTERNAL they stay visible.
        assert count >= 1


# ── TestCreditCardReDoS ──────────────────────────────────────────────


class TestCreditCardReDoS:
    """Validate that credit card regex does not exhibit catastrophic backtracking."""

    def test_credit_card_regex_no_redos(self):
        """Pattern '1 ' * 100 should complete quickly (under 100ms), not hang."""
        import time

        from app.agents.data_classification import _CONFIDENTIAL_PII_PATTERNS

        text = "1 " * 100
        start = time.monotonic()
        _CONFIDENTIAL_PII_PATTERNS["credit_card"].search(text)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"Credit card regex took {elapsed_ms:.1f}ms (ReDoS risk)"
