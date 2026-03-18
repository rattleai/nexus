"""Agent output validation framework.

Validates agent outputs against:
    1. JSON schema (if output_schema is defined on the AgentDefinition)
    2. Content policies (PII patterns, prohibited content)
    3. Size constraints (max output length)

Called by the runtime after each agent response to enforce quality gates.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.stdlib.get_logger()

# PII patterns for detection (not exhaustive — extend per jurisdiction)
_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

# Maximum output length (characters) before forced truncation
_MAX_OUTPUT_LENGTH = 100_000


class ValidationError:
    """A single validation failure."""

    def __init__(self, code: str, message: str, *, severity: str = "error"):
        self.code = code
        self.message = message
        self.severity = severity  # "error", "warning"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


class OutputValidator:
    """Validates agent output against configured rules."""

    def __init__(self, policy: dict[str, Any] | None = None):
        self.policy = policy or {}

    def validate(self, output: str, *, output_schema: dict | None = None) -> list[ValidationError]:
        """Run all validation checks on agent output.

        Returns list of ValidationError (empty = valid).
        """
        errors: list[ValidationError] = []

        # 1. Size check
        max_len = self.policy.get("max_output_length", _MAX_OUTPUT_LENGTH)
        if len(output) > max_len:
            errors.append(ValidationError(
                "output_too_long",
                f"Output exceeds maximum length ({len(output)} > {max_len})",
            ))

        # 2. JSON schema validation
        if output_schema:
            schema_errors = self._validate_json_schema(output, output_schema)
            errors.extend(schema_errors)

        # 3. PII detection
        if self.policy.get("block_pii", False):
            pii_errors = self._detect_pii(output)
            errors.extend(pii_errors)

        # 4. Prohibited patterns
        prohibited = self.policy.get("prohibited_patterns", [])
        for pattern_str in prohibited:
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                if pattern.search(output):
                    errors.append(ValidationError(
                        "prohibited_content",
                        f"Output contains prohibited pattern: {pattern_str[:50]}",
                    ))
            except re.error:
                logger.warning("invalid_prohibited_pattern", pattern=pattern_str[:50])

        # 5. Required keywords (must contain certain phrases)
        required = self.policy.get("required_keywords", [])
        for keyword in required:
            if keyword.lower() not in output.lower():
                errors.append(ValidationError(
                    "missing_required_keyword",
                    f"Output is missing required keyword: {keyword}",
                    severity="warning",
                ))

        return errors

    def _validate_json_schema(self, output: str, schema: dict) -> list[ValidationError]:
        """Validate output against a JSON schema if the output is valid JSON."""
        import json

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            # Output is not JSON — check if schema requires JSON
            if schema.get("type") in ("object", "array"):
                return [ValidationError(
                    "invalid_json",
                    "Output must be valid JSON according to the output schema",
                )]
            return []

        try:
            import jsonschema
            jsonschema.validate(data, schema)
            return []
        except ImportError:
            # jsonschema not installed — skip schema validation
            logger.debug("jsonschema_not_installed_skipping_validation")
            return []
        except jsonschema.ValidationError as exc:
            return [ValidationError(
                "schema_violation",
                f"Output does not match schema: {exc.message[:200]}",
            )]
        except jsonschema.SchemaError as exc:
            logger.warning("invalid_output_schema", error=str(exc)[:200])
            return []

    def _detect_pii(self, output: str) -> list[ValidationError]:
        """Scan for common PII patterns."""
        errors: list[ValidationError] = []
        for pii_type, pattern in _PII_PATTERNS.items():
            matches = pattern.findall(output)
            if matches:
                errors.append(ValidationError(
                    "pii_detected",
                    f"Potential {pii_type} detected in output ({len(matches)} occurrence(s))",
                ))
        return errors

    def sanitize(self, output: str) -> str:
        """Sanitize output by redacting detected PII patterns."""
        sanitized = output
        for pii_type, pattern in _PII_PATTERNS.items():
            sanitized = pattern.sub(f"[REDACTED_{pii_type.upper()}]", sanitized)

        # Enforce max length
        max_len = self.policy.get("max_output_length", _MAX_OUTPUT_LENGTH)
        if len(sanitized) > max_len:
            sanitized = sanitized[:max_len] + "... [truncated]"

        return sanitized


def validate_agent_output(
    output: str,
    *,
    governance_policy: dict | None = None,
    output_schema: dict | None = None,
) -> tuple[bool, list[dict], str]:
    """Convenience function to validate and optionally sanitize agent output.

    Returns (is_valid, errors_list, sanitized_output).
    """
    policy = (governance_policy or {}).get("output_validation", {})
    validator = OutputValidator(policy)

    errors = validator.validate(output, output_schema=output_schema)

    # Filter by severity
    blocking_errors = [e for e in errors if e.severity == "error"]

    if policy.get("sanitize_pii", False):
        output = validator.sanitize(output)

    return (
        len(blocking_errors) == 0,
        [e.to_dict() for e in errors],
        output,
    )
