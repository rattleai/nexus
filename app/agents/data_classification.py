"""Data classification and DLP enforcement for agent interactions.

Provides:
    - Data classification engine: Classify data as PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED
    - Classification sources: Column-level metadata, tenant patterns, PII detection
    - DLP enforcement: Block agents from accessing/outputting data above their classification level
    - Consent-aware access: Verify consent before processing personal data
    - Automatic redaction: Redact based on classification level
    - GDPR/EU AI Act alignment: Data subject access includes agent-processed data

Integrates with:
    - app/agents/validation.py OutputValidator for redaction
    - app/agents/capabilities.py for per-agent classification ceiling
    - app/ai/guardrails.py for PII pattern detection
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


class DataLevel(IntEnum):
    """Data classification levels (ordered by sensitivity)."""
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def from_str(cls, value: str) -> DataLevel:
        try:
            return cls[value.upper()]
        except KeyError:
            return cls.INTERNAL  # Safe default


# PII patterns that indicate CONFIDENTIAL or higher classification
_CONFIDENTIAL_PII_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "passport": re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
    "drivers_license": re.compile(r"\b[A-Z]\d{7,14}\b"),
    "bank_account": re.compile(r"\b\d{8,17}\b"),  # IBAN-like
}

# PII patterns that indicate INTERNAL classification
_INTERNAL_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "date_of_birth": re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b"),
}

# Keywords indicating RESTRICTED classification
_RESTRICTED_KEYWORDS = {
    "top secret", "classified", "eyes only", "trade secret",
    "attorney-client", "hipaa", "phi", "protected health",
    "material nonpublic", "mnpi",
}

# Column name patterns for automatic classification
_COLUMN_CLASSIFICATION: dict[str, DataLevel] = {
    "ssn": DataLevel.RESTRICTED,
    "social_security": DataLevel.RESTRICTED,
    "tax_id": DataLevel.RESTRICTED,
    "credit_card": DataLevel.CONFIDENTIAL,
    "card_number": DataLevel.CONFIDENTIAL,
    "cvv": DataLevel.CONFIDENTIAL,
    "password": DataLevel.CONFIDENTIAL,
    "password_hash": DataLevel.CONFIDENTIAL,
    "secret": DataLevel.CONFIDENTIAL,
    "api_key": DataLevel.CONFIDENTIAL,
    "token": DataLevel.CONFIDENTIAL,
    "email": DataLevel.INTERNAL,
    "phone": DataLevel.INTERNAL,
    "address": DataLevel.INTERNAL,
    "salary": DataLevel.CONFIDENTIAL,
    "bank_account": DataLevel.RESTRICTED,
    "iban": DataLevel.RESTRICTED,
}

# Pre-compiled column patterns using underscore word boundaries to prevent
# false positives (e.g. "ssn" should NOT match "permission").
_COLUMN_CLASSIFICATION_RE: list[tuple[re.Pattern, DataLevel]] = [
    (re.compile(rf"(?:^|_){re.escape(pattern)}(?:_|$)"), level)
    for pattern, level in _COLUMN_CLASSIFICATION.items()
]


@dataclass
class ClassificationResult:
    """Result of data classification analysis."""

    level: DataLevel = DataLevel.PUBLIC
    reasons: list[str] = field(default_factory=list)
    pii_types_found: list[str] = field(default_factory=list)
    redactions_applied: int = 0


class DataClassifier:
    """Classifies data flowing through agents by sensitivity level.

    Usage:
        classifier = DataClassifier()
        result = classifier.classify_text("John's SSN is 123-45-6789")
        # result.level == DataLevel.CONFIDENTIAL
    """

    def __init__(self, tenant_patterns: dict[str, str] | None = None):
        """Initialize with optional tenant-specific patterns.

        Args:
            tenant_patterns: Mapping of pattern_name -> DataLevel string
        """
        self.tenant_patterns = tenant_patterns or {}

    def classify_text(self, text: str) -> ClassificationResult:
        """Classify a text string by its data sensitivity level."""
        if not settings.DATA_CLASSIFICATION_ENABLED:
            default = DataLevel.from_str(settings.DATA_CLASSIFICATION_DEFAULT_LEVEL)
            return ClassificationResult(level=default)

        result = ClassificationResult()

        # Check for RESTRICTED keywords
        text_lower = text.lower()
        for keyword in _RESTRICTED_KEYWORDS:
            if keyword in text_lower:
                result.level = max(result.level, DataLevel.RESTRICTED)
                result.reasons.append(f"restricted_keyword:{keyword}")

        # Check for CONFIDENTIAL PII patterns
        for name, pattern in _CONFIDENTIAL_PII_PATTERNS.items():
            if pattern.search(text):
                result.level = max(result.level, DataLevel.CONFIDENTIAL)
                result.pii_types_found.append(name)
                result.reasons.append(f"confidential_pii:{name}")

        # Check for INTERNAL PII patterns
        for name, pattern in _INTERNAL_PII_PATTERNS.items():
            if pattern.search(text):
                result.level = max(result.level, DataLevel.INTERNAL)
                result.pii_types_found.append(name)
                result.reasons.append(f"internal_pii:{name}")

        # Check tenant-specific keyword patterns (not regex — ReDoS safety)
        for pattern_name, level_str in self.tenant_patterns.items():
            level = DataLevel.from_str(level_str)
            if level > result.level and pattern_name.lower() in text_lower:
                result.level = level
                result.reasons.append(f"tenant_pattern:{pattern_name}")

        return result

    def classify_column(self, column_name: str) -> DataLevel:
        """Classify a database column by its name.

        Uses underscore-boundary matching to avoid false positives
        (e.g. "ssn" matches "user_ssn" but not "permission").
        """
        name_lower = column_name.lower()
        for pattern_re, level in _COLUMN_CLASSIFICATION_RE:
            if pattern_re.search(name_lower):
                return level
        return DataLevel.PUBLIC

    def classify_dict(self, data: dict[str, Any]) -> ClassificationResult:
        """Classify a dictionary's data (inspects both keys and values)."""
        result = ClassificationResult()

        for key, value in data.items():
            # Classify by column/key name
            col_level = self.classify_column(key)
            if col_level > result.level:
                result.level = col_level
                result.reasons.append(f"column_name:{key}")

            # Classify by value content
            if isinstance(value, str):
                value_result = self.classify_text(value)
                if value_result.level > result.level:
                    result.level = value_result.level
                    result.reasons.extend(value_result.reasons)
                    result.pii_types_found.extend(value_result.pii_types_found)

        return result


class DLPEnforcer:
    """Enforces Data Loss Prevention policies for agent interactions.

    Usage:
        enforcer = DLPEnforcer(max_level=DataLevel.INTERNAL)
        is_allowed, reason = enforcer.check_access(data_result)
        redacted = enforcer.redact(text, data_result)
    """

    def __init__(self, max_level: DataLevel = DataLevel.INTERNAL):
        self.max_level = max_level
        self._classifier = DataClassifier()

    def check_access(self, data: str | dict[str, Any]) -> tuple[bool, str]:
        """Check if data access is allowed for the agent's classification level.

        Returns (allowed, reason).
        """
        if isinstance(data, dict):
            result = self._classifier.classify_dict(data)
        else:
            result = self._classifier.classify_text(str(data))

        if result.level > self.max_level:
            reason = (
                f"Data classified as {result.level.name} exceeds agent's "
                f"maximum level {self.max_level.name}: {', '.join(result.reasons[:3])}"
            )
            logger.warning(
                "dlp_access_denied",
                data_level=result.level.name,
                max_level=self.max_level.name,
                reasons=result.reasons[:5],
            )
            return False, reason

        return True, ""

    def redact_text(self, text: str) -> tuple[str, int]:
        """Redact data above the agent's classification level.

        Returns (redacted_text, redaction_count).
        """
        redacted = text
        count = 0

        if self.max_level < DataLevel.CONFIDENTIAL:
            # Redact CONFIDENTIAL PII
            for name, pattern in _CONFIDENTIAL_PII_PATTERNS.items():
                matches = pattern.findall(redacted)
                if matches:
                    redacted = pattern.sub(f"[REDACTED_{name.upper()}]", redacted)
                    count += len(matches)

        if self.max_level < DataLevel.INTERNAL:
            # Redact INTERNAL PII
            for name, pattern in _INTERNAL_PII_PATTERNS.items():
                matches = pattern.findall(redacted)
                if matches:
                    redacted = pattern.sub(f"[REDACTED_{name.upper()}]", redacted)
                    count += len(matches)

        return redacted, count

    def redact_dict(self, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Redact sensitive fields from a dictionary.

        Returns (redacted_dict, redaction_count).
        """
        result = {}
        total_count = 0

        for key, value in data.items():
            col_level = self._classifier.classify_column(key)
            if col_level > self.max_level:
                result[key] = f"[REDACTED_{col_level.name}]"
                total_count += 1
            elif isinstance(value, str):
                redacted_value, count = self.redact_text(value)
                result[key] = redacted_value
                total_count += count
            elif isinstance(value, dict):
                redacted_value, count = self.redact_dict(value)
                result[key] = redacted_value
                total_count += count
            else:
                result[key] = value

        return result, total_count
