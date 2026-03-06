"""Basic AI input validation and output filtering.

Provides configurable per-tenant guardrails for safety and cost control.
Tenant-level overrides are read from tenant.settings["ai_guardrails"].
"""

from __future__ import annotations

import re

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

# Default blocked input patterns (can be overridden per tenant)
_DEFAULT_BLOCKED_INPUT_PATTERNS: list[str] = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)you\s+are\s+now\s+(in\s+)?DAN\s+mode",
    r"(?i)system\s*:\s*you\s+are",
]

# PII patterns for optional output filtering
_PII_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "phone_us": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
}


class GuardrailViolation:
    """Represents a single guardrail violation."""

    def __init__(self, rule: str, detail: str):
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.rule}] {self.detail}"


def validate_input(
    messages: list[dict],
    *,
    tenant_settings: dict | None = None,
) -> list[GuardrailViolation]:
    """Validate AI input messages against guardrail rules.

    Returns a list of violations (empty means input is clean).
    """
    violations: list[GuardrailViolation] = []
    ai_config = (tenant_settings or {}).get("ai_guardrails", {})

    # 1. Max message count
    max_messages = ai_config.get("max_messages", settings.AI_MAX_MESSAGES_PER_REQUEST)
    if len(messages) > max_messages:
        violations.append(
            GuardrailViolation("max_messages", f"Too many messages: {len(messages)} > {max_messages}")
        )

    # 2. Max individual message length
    max_msg_len = ai_config.get("max_message_length", settings.AI_MAX_MESSAGE_LENGTH)
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if len(content) > max_msg_len:
            violations.append(
                GuardrailViolation("max_message_length", f"Message {i} too long: {len(content)} > {max_msg_len}")
            )

    # 3. Blocked input patterns (prompt injection detection)
    blocked_patterns = ai_config.get("blocked_input_patterns", _DEFAULT_BLOCKED_INPUT_PATTERNS)
    for msg in messages:
        content = msg.get("content", "")
        for pattern in blocked_patterns:
            try:
                if re.search(pattern, content):
                    violations.append(
                        GuardrailViolation("blocked_pattern", f"Input matches blocked pattern")
                    )
                    break  # One violation per message is enough
            except re.error:
                logger.warning("guardrail_invalid_regex", pattern=pattern)

    # 4. Total input size check
    total_chars = sum(len(m.get("content", "")) for m in messages)
    max_total = ai_config.get("max_total_input_chars", 1_000_000)
    if total_chars > max_total:
        violations.append(
            GuardrailViolation("max_total_input", f"Total input too large: {total_chars} > {max_total}")
        )

    if violations:
        logger.warning(
            "guardrail_input_violations",
            violation_count=len(violations),
            rules=[v.rule for v in violations],
        )

    return violations


def filter_output(
    content: str,
    *,
    tenant_settings: dict | None = None,
) -> str:
    """Post-process AI output to filter sensitive data.

    Only applies PII filtering if enabled in tenant settings.
    Returns the (potentially redacted) content string.
    """
    ai_config = (tenant_settings or {}).get("ai_guardrails", {})

    if not ai_config.get("filter_pii_output", False):
        return content

    # Apply PII pattern redaction
    filtered = content
    enabled_patterns = ai_config.get("pii_patterns", list(_PII_PATTERNS.keys()))

    for pattern_name in enabled_patterns:
        pattern = _PII_PATTERNS.get(pattern_name)
        if pattern:
            try:
                filtered = re.sub(pattern, f"[REDACTED_{pattern_name.upper()}]", filtered)
            except re.error:
                logger.warning("guardrail_pii_regex_error", pattern=pattern_name)

    if filtered != content:
        logger.info("guardrail_output_filtered", patterns_applied=enabled_patterns)

    return filtered
