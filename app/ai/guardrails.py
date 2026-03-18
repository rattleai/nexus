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


# ── OWASP LLM Top 10 2025 Guardrails ─────────────────────

_SYSTEM_PROMPT_LEAK_PATTERNS: dict[str, re.Pattern] = {
    "reveal_instructions": re.compile(r"(?i)(reveal|show|repeat|output|print)\s+(your|the|system)\s+(instructions|prompt|rules)"),
    "what_is_prompt": re.compile(r"(?i)what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions|rules)"),
    "beginning_text": re.compile(r"(?i)(start|begin)\s+(with|from|of)\s+(your|the)\s+(first|initial|original)\s+(message|instruction|text)"),
}

_RAG_POISONING_PATTERNS: dict[str, re.Pattern] = {
    "inject_context": re.compile(r"(?i)when\s+someone\s+asks\s+about.*(?:respond|say|tell|answer)\s+(?:with|that)"),
    "override_knowledge": re.compile(r"(?i)(?:override|replace|ignore)\s+(?:all|any|the)\s+(?:context|knowledge|documents|information)"),
    "fake_document": re.compile(r"(?i)(?:according\s+to|per|as\s+stated\s+in)\s+(?:the\s+)?document.*(?:the\s+answer\s+is|you\s+should|always)"),
}

_EXCESSIVE_AGENCY_PATTERNS: dict[str, re.Pattern] = {
    "run_arbitrary": re.compile(r"(?i)(?:execute|run|invoke)\s+(?:any|all|every)\s+(?:tool|function|command|action)"),
    "autonomous_mode": re.compile(r"(?i)(?:enter|switch\s+to|enable)\s+(?:autonomous|unrestricted|unlimited)\s+mode"),
    "bypass_approval": re.compile(r"(?i)(?:skip|bypass|ignore)\s+(?:approval|confirmation|verification|review)"),
}


def validate_owasp_llm_top10(
    messages: list[dict],
    *,
    tenant_settings: dict | None = None,
) -> list[GuardrailViolation]:
    """Check input against OWASP LLM Top 10 2025 categories.

    Covers:
    - LLM01: Prompt Injection (handled by validate_input)
    - LLM06: Excessive Agency
    - LLM07: System Prompt Leakage
    - LLM08: Vector/Embedding Weaknesses (RAG poisoning)
    - LLM10: Unbounded Consumption (handled by rate limits + governance)
    """
    violations: list[GuardrailViolation] = []

    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue

        # LLM07: System Prompt Leakage attempts
        for name, pattern in _SYSTEM_PROMPT_LEAK_PATTERNS.items():
            if pattern.search(content):
                violations.append(
                    GuardrailViolation("owasp_llm07_system_prompt_leak", f"System prompt extraction attempt: {name}")
                )
                break

        # LLM08: RAG Poisoning / Vector injection
        for name, pattern in _RAG_POISONING_PATTERNS.items():
            if pattern.search(content):
                violations.append(
                    GuardrailViolation("owasp_llm08_rag_poisoning", f"RAG poisoning attempt: {name}")
                )
                break

        # LLM06: Excessive Agency attempts
        for name, pattern in _EXCESSIVE_AGENCY_PATTERNS.items():
            if pattern.search(content):
                violations.append(
                    GuardrailViolation("owasp_llm06_excessive_agency", f"Excessive agency attempt: {name}")
                )
                break

    if violations:
        logger.warning(
            "owasp_llm_top10_violations",
            violation_count=len(violations),
            rules=[v.rule for v in violations],
        )

    return violations


def _safe_get_ai_config(tenant_settings: dict | None) -> dict:
    """Safely extract ai_guardrails config, defaulting to empty dict on bad data."""
    if not isinstance(tenant_settings, dict):
        return {}
    ai_config = tenant_settings.get("ai_guardrails")
    if not isinstance(ai_config, dict):
        return {}
    return ai_config
