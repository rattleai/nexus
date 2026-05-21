"""Compliance and Policy-as-Code framework for agent governance.

Provides:
    - Policy-as-code: Versioned, auditable policy documents with schema validation
    - Automated compliance checks: Pre-execution scan against policy requirements
    - Compliance reporting: Per-tenant reports covering OWASP LLM, NIST AI RMF, EU AI Act
    - Regulatory audit trail: Extended audit fields for compliance context
    - Model/agent cards: Auto-generate transparency documentation

Integrates with:
    - app/agents/governance.py for policy enforcement
    - app/core/audit.py for extended audit logging
    - app/agents/events.py for ComplianceCheckCompleted events
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


# ── Policy Schema Definitions ──────────────────────────────────────

# Required policy fields by framework
_OWASP_LLM_REQUIRED_FIELDS = {
    "prompt_injection_defense": "Prompt injection defense must be configured (LLM01)",
    "output_validation": "Output validation must be enabled (LLM02)",
    "denied_tools": "Tool access restrictions must be defined (LLM06)",
    "max_spend_per_run_usd": "Spending limits must be set (LLM10)",
}

_NIST_AI_RMF_REQUIRED_FIELDS = {
    "max_spend_per_run_usd": "Resource limits for AI system governance (MAP 1.1)",
    "output_validation": "Output quality assurance (MEASURE 2.6)",
    "require_approval_for": "Human oversight mechanism (GOVERN 1.4)",
}

_EU_AI_ACT_REQUIRED_FIELDS = {
    "max_spend_per_run_usd": "Risk management (Article 9)",
    "output_validation": "Accuracy and robustness (Article 15)",
    "require_approval_for": "Human oversight (Article 14)",
}


@dataclass
class ComplianceCheck:
    """A single compliance check result."""

    framework: str  # "owasp_llm", "nist_ai_rmf", "eu_ai_act"
    check_id: str
    description: str
    status: str = "pass"  # "pass", "fail", "warning", "not_applicable"
    detail: str = ""
    article: str = ""  # Regulatory article reference
    recommendation: str = ""


@dataclass
class ComplianceReport:
    """Per-tenant compliance assessment report."""

    tenant_id: str = ""
    generated_at: float = 0.0
    frameworks: list[str] = field(default_factory=list)
    checks: list[ComplianceCheck] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    score: float = 0.0  # 0.0 - 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "generated_at": self.generated_at,
            "frameworks": self.frameworks,
            "checks": [
                {
                    "framework": c.framework,
                    "check_id": c.check_id,
                    "description": c.description,
                    "status": c.status,
                    "detail": c.detail,
                    "article": c.article,
                    "recommendation": c.recommendation,
                }
                for c in self.checks
            ],
            "summary": {
                "passed": self.passed,
                "failed": self.failed,
                "warnings": self.warnings,
                "score": self.score,
            },
        }


@dataclass
class AgentCard:
    """Transparency documentation for an agent (EU AI Act Article 13)."""

    agent_id: str = ""
    agent_name: str = ""
    description: str = ""
    model: str = ""
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    governance_summary: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "medium"  # "low", "medium", "high", "unacceptable"
    data_classification_max: str = "INTERNAL"
    sandbox_enabled: bool = False
    human_oversight: bool = False
    last_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "model": self.model,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "allowed_tools": self.allowed_tools,
            "governance": self.governance_summary,
            "risk_level": self.risk_level,
            "data_classification_max": self.data_classification_max,
            "sandbox_enabled": self.sandbox_enabled,
            "human_oversight": self.human_oversight,
            "last_updated": self.last_updated,
        }


class ComplianceEngine:
    """Automated compliance checking and reporting engine.

    Usage:
        engine = ComplianceEngine(tenant_id=...)
        report = engine.run_compliance_checks(agent_definitions, policies)
        card = engine.generate_agent_card(definition)
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def run_compliance_checks(
        self,
        agent_definitions: list[dict[str, Any]],
        policies: list[dict[str, Any]],
        *,
        frameworks: list[str] | None = None,
    ) -> ComplianceReport:
        """Run automated compliance checks across all frameworks.

        Args:
            agent_definitions: List of agent definition dicts (governance_policy, etc.)
            policies: List of governance policy dicts
            frameworks: Which frameworks to check (default: all)
        """
        frameworks = frameworks or ["owasp_llm", "nist_ai_rmf", "eu_ai_act"]
        report = ComplianceReport(
            tenant_id=self.tenant_id,
            generated_at=time.time(),
            frameworks=frameworks,
        )

        for definition in agent_definitions:
            policy = definition.get("governance_policy", {})

            if "owasp_llm" in frameworks:
                report.checks.extend(self._check_owasp_llm(definition, policy))
            if "nist_ai_rmf" in frameworks:
                report.checks.extend(self._check_nist_ai_rmf(definition, policy))
            if "eu_ai_act" in frameworks:
                report.checks.extend(self._check_eu_ai_act(definition, policy))

        # Calculate summary
        for check in report.checks:
            if check.status == "pass":
                report.passed += 1
            elif check.status == "fail":
                report.failed += 1
            elif check.status == "warning":
                report.warnings += 1

        total = report.passed + report.failed + report.warnings
        report.score = report.passed / total if total > 0 else 0.0

        return report

    def _check_owasp_llm(
        self,
        definition: dict[str, Any],
        policy: dict[str, Any],
    ) -> list[ComplianceCheck]:
        """Check OWASP LLM Top 10 2025 compliance."""
        checks: list[ComplianceCheck] = []
        agent_name = definition.get("name", "unknown")

        # LLM01: Prompt Injection
        checks.append(
            ComplianceCheck(
                framework="owasp_llm",
                check_id="LLM01",
                description=f"[{agent_name}] Prompt injection defense",
                status="pass" if settings.PROMPT_FIREWALL_ENABLED else "fail",
                article="LLM01: Prompt Injection",
                recommendation="Enable PROMPT_FIREWALL_ENABLED" if not settings.PROMPT_FIREWALL_ENABLED else "",
            )
        )

        # LLM02: Insecure Output Handling
        has_output_validation = bool(policy.get("output_validation"))
        checks.append(
            ComplianceCheck(
                framework="owasp_llm",
                check_id="LLM02",
                description=f"[{agent_name}] Output validation",
                status="pass" if has_output_validation else "warning",
                article="LLM02: Insecure Output Handling",
                recommendation="Add output_validation to governance policy" if not has_output_validation else "",
            )
        )

        # LLM06: Excessive Agency
        has_tool_restrictions = bool(
            policy.get("denied_tools") or policy.get("allowed_tools") or definition.get("allowed_tools")
        )
        checks.append(
            ComplianceCheck(
                framework="owasp_llm",
                check_id="LLM06",
                description=f"[{agent_name}] Tool access control",
                status="pass" if has_tool_restrictions else "fail",
                article="LLM06: Excessive Agency",
                recommendation="Define allowed_tools or denied_tools" if not has_tool_restrictions else "",
            )
        )

        # LLM07: System Prompt Leakage
        checks.append(
            ComplianceCheck(
                framework="owasp_llm",
                check_id="LLM07",
                description=f"[{agent_name}] System prompt leak prevention",
                status="pass" if settings.PROMPT_FIREWALL_CANARY_ENABLED else "warning",
                article="LLM07: System Prompt Leakage",
                recommendation="Enable canary tokens" if not settings.PROMPT_FIREWALL_CANARY_ENABLED else "",
            )
        )

        # LLM10: Unbounded Consumption
        has_limits = bool(policy.get("max_spend_per_run_usd") or policy.get("max_requests_per_minute"))
        checks.append(
            ComplianceCheck(
                framework="owasp_llm",
                check_id="LLM10",
                description=f"[{agent_name}] Resource consumption limits",
                status="pass" if has_limits else "fail",
                article="LLM10: Unbounded Consumption",
                recommendation="Set max_spend_per_run_usd and max_requests_per_minute" if not has_limits else "",
            )
        )

        return checks

    def _check_nist_ai_rmf(
        self,
        definition: dict[str, Any],
        policy: dict[str, Any],
    ) -> list[ComplianceCheck]:
        """Check NIST AI Risk Management Framework alignment."""
        checks: list[ComplianceCheck] = []
        agent_name = definition.get("name", "unknown")

        # GOVERN 1.4: Human oversight
        has_approval = bool(policy.get("require_approval_for"))
        checks.append(
            ComplianceCheck(
                framework="nist_ai_rmf",
                check_id="GOVERN_1_4",
                description=f"[{agent_name}] Human oversight mechanism",
                status="pass" if has_approval else "warning",
                article="GOVERN 1.4",
                recommendation="Configure require_approval_for for high-risk actions" if not has_approval else "",
            )
        )

        # MAP 1.1: Risk identification
        has_sandbox = definition.get("sandbox_enabled", False)
        checks.append(
            ComplianceCheck(
                framework="nist_ai_rmf",
                check_id="MAP_1_1",
                description=f"[{agent_name}] Code execution isolation",
                status="pass"
                if has_sandbox or "code_execute" not in (definition.get("allowed_tools") or [])
                else "warning",
                article="MAP 1.1",
            )
        )

        # MEASURE 2.6: Output quality
        has_output_check = bool(policy.get("output_validation") or definition.get("output_schema"))
        checks.append(
            ComplianceCheck(
                framework="nist_ai_rmf",
                check_id="MEASURE_2_6",
                description=f"[{agent_name}] Output quality assurance",
                status="pass" if has_output_check else "warning",
                article="MEASURE 2.6",
            )
        )

        return checks

    def _check_eu_ai_act(
        self,
        definition: dict[str, Any],
        policy: dict[str, Any],
    ) -> list[ComplianceCheck]:
        """Check EU AI Act compliance requirements."""
        checks: list[ComplianceCheck] = []
        agent_name = definition.get("name", "unknown")

        # Article 9: Risk Management
        has_limits = bool(
            policy.get("max_spend_per_run_usd")
            and definition.get("max_steps_per_run")
            and definition.get("max_duration_seconds")
        )
        checks.append(
            ComplianceCheck(
                framework="eu_ai_act",
                check_id="ART_9",
                description=f"[{agent_name}] Risk management measures",
                status="pass" if has_limits else "fail",
                article="Article 9: Risk Management System",
                recommendation="Set comprehensive execution limits" if not has_limits else "",
            )
        )

        # Article 13: Transparency
        has_description = bool(definition.get("description"))
        checks.append(
            ComplianceCheck(
                framework="eu_ai_act",
                check_id="ART_13",
                description=f"[{agent_name}] Transparency documentation",
                status="pass" if has_description else "warning",
                article="Article 13: Transparency and Provision of Information",
                recommendation="Add agent description and generate agent card" if not has_description else "",
            )
        )

        # Article 14: Human Oversight
        has_approval = bool(policy.get("require_approval_for"))
        checks.append(
            ComplianceCheck(
                framework="eu_ai_act",
                check_id="ART_14",
                description=f"[{agent_name}] Human oversight capability",
                status="pass" if has_approval else "warning",
                article="Article 14: Human Oversight",
                recommendation="Configure human-in-the-loop approval" if not has_approval else "",
            )
        )

        # Article 15: Accuracy, Robustness, Cybersecurity
        has_security = bool(settings.PROMPT_FIREWALL_ENABLED and settings.AGENT_THREAT_DETECTION_ENABLED)
        checks.append(
            ComplianceCheck(
                framework="eu_ai_act",
                check_id="ART_15",
                description=f"[{agent_name}] Accuracy, robustness, cybersecurity",
                status="pass" if has_security else "warning",
                article="Article 15: Accuracy, Robustness, Cybersecurity",
            )
        )

        return checks

    def generate_agent_card(self, definition: dict[str, Any]) -> AgentCard:
        """Auto-generate an agent/model card for transparency documentation."""
        policy = definition.get("governance_policy", {})

        card = AgentCard(
            agent_id=str(definition.get("id", "")),
            agent_name=definition.get("name", ""),
            description=definition.get("description", ""),
            model=definition.get("model", ""),
            capabilities=definition.get("allowed_tools", []),
            limitations=[
                f"Max {definition.get('max_steps_per_run', 50)} steps per run",
                f"Max {definition.get('max_duration_seconds', 300)}s execution time",
                f"Max ${policy.get('max_spend_per_run_usd', 'unlimited')} per run",
            ],
            allowed_tools=definition.get("allowed_tools", []),
            governance_summary={
                "spending_limits": {
                    "per_run": policy.get("max_spend_per_run_usd"),
                    "per_day": policy.get("max_spend_per_day_usd"),
                    "per_month": policy.get("max_spend_per_month_usd"),
                },
                "requires_approval": policy.get("require_approval_for", []),
                "rate_limit_rpm": policy.get("max_requests_per_minute"),
            },
            sandbox_enabled=definition.get("sandbox_enabled", False),
            human_oversight=bool(policy.get("require_approval_for")),
            last_updated=time.time(),
        )

        # Determine risk level based on capabilities
        if "code_execute" in (definition.get("allowed_tools") or []):
            card.risk_level = "high"
        elif len(definition.get("allowed_tools") or []) > 5:
            card.risk_level = "medium"
        else:
            card.risk_level = "low"

        return card
