"""Basic AI input validation and output filtering.

Provides configurable per-tenant guardrails for safety and cost control.
Tenant-level overrides are read from tenant.settings["ai_guardrails"].

Security: Tenant-supplied regex patterns are NOT accepted — only the platform's
hardcoded patterns are used for input blocking. Tenant config can only toggle
which pre-defined patterns are active (via pattern names, not raw regexes).
"""

from __future__ import annotations

import re

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

# ── Pre-compiled safe patterns ────────────────────────────
# These are platform-controlled and pre-compiled at module load time.
# Tenants cannot supply custom regex patterns (ReDoS prevention).

_BLOCKED_INPUT_PATTERNS: dict[str, re.Pattern] = {
    "ignore_instructions": re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"),
    "dan_mode": re.compile(r"(?i)you\s+are\s+now\s+(in\s+)?DAN\s+mode"),
    "system_override": re.compile(r"(?i)system\s*:\s*you\s+are"),
    "jailbreak_prompt": re.compile(r"(?i)bypass\s+(your|all|any)\s+(safety|content)\s+(filter|restriction|guideline)"),
}

_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone_us": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
}

# Default active pattern sets
_DEFAULT_ACTIVE_INPUT_PATTERNS = list(_BLOCKED_INPUT_PATTERNS.keys())
_DEFAULT_ACTIVE_PII_PATTERNS = list(_PII_PATTERNS.keys())


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
    ai_config = _safe_get_ai_config(tenant_settings)

    # 1. Max message count
    max_messages = ai_config.get("max_messages", settings.AI_MAX_MESSAGES_PER_REQUEST)
    if not isinstance(max_messages, int) or max_messages < 1:
        max_messages = settings.AI_MAX_MESSAGES_PER_REQUEST
    if len(messages) > max_messages:
        violations.append(
            GuardrailViolation("max_messages", f"Too many messages: {len(messages)} > {max_messages}")
        )

    # 2. Max individual message length
    max_msg_len = ai_config.get("max_message_length", settings.AI_MAX_MESSAGE_LENGTH)
    if not isinstance(max_msg_len, int) or max_msg_len < 1:
        max_msg_len = settings.AI_MAX_MESSAGE_LENGTH
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if len(content) > max_msg_len:
            violations.append(
                GuardrailViolation("max_message_length", f"Message {i} too long: {len(content)} > {max_msg_len}")
            )

    # 3. Blocked input patterns (prompt injection detection)
    # Tenants can only select which pre-compiled patterns are active (by name),
    # NOT supply custom regexes. This prevents ReDoS attacks.
    active_patterns = ai_config.get("active_input_patterns", _DEFAULT_ACTIVE_INPUT_PATTERNS)
    if not isinstance(active_patterns, list):
        active_patterns = _DEFAULT_ACTIVE_INPUT_PATTERNS

    for msg in messages:
        content = msg.get("content", "")
        for pattern_name in active_patterns:
            compiled = _BLOCKED_INPUT_PATTERNS.get(pattern_name)
            if compiled and compiled.search(content):
                violations.append(
                    GuardrailViolation("blocked_pattern", f"Input matches blocked pattern: {pattern_name}")
                )
                break  # One violation per message is enough

    # 4. Total input size check
    total_chars = sum(len(m.get("content", "")) for m in messages)
    max_total = ai_config.get("max_total_input_chars", 1_000_000)
    if not isinstance(max_total, int) or max_total < 1:
        max_total = 1_000_000
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
    ai_config = _safe_get_ai_config(tenant_settings)

    if not ai_config.get("filter_pii_output", False):
        return content

    # Apply PII pattern redaction (pre-compiled, safe patterns only)
    filtered = content
    enabled_patterns = ai_config.get("pii_patterns", _DEFAULT_ACTIVE_PII_PATTERNS)
    if not isinstance(enabled_patterns, list):
        enabled_patterns = _DEFAULT_ACTIVE_PII_PATTERNS

    for pattern_name in enabled_patterns:
        compiled = _PII_PATTERNS.get(pattern_name)
        if compiled:
            filtered = compiled.sub(f"[REDACTED_{pattern_name.upper()}]", filtered)

    if filtered != content:
        logger.info("guardrail_output_filtered", patterns_applied=enabled_patterns)

    return filtered


def _safe_get_ai_config(tenant_settings: dict | None) -> dict:
    """Safely extract ai_guardrails config, defaulting to empty dict on bad data."""
    if not isinstance(tenant_settings, dict):
        return {}
    ai_config = tenant_settings.get("ai_guardrails")
    if not isinstance(ai_config, dict):
        return {}
    return ai_config
