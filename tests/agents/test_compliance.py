"""Tests for the compliance and policy-as-code engine.

Covers:
    - OWASP LLM Top 10 compliance checks
    - EU AI Act regulatory alignment
    - Compliance report generation and scoring
    - Agent card (transparency documentation) generation
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.compliance import ComplianceEngine, ComplianceReport

# ── TestOWASPLLMChecks ────────────────────────────────────────────────


class TestOWASPLLMChecks:
    """OWASP LLM Top 10 2025 compliance checks."""

    def _run(self, definition, *, frameworks=None):
        engine = ComplianceEngine(tenant_id="test-tenant")
        return engine.run_compliance_checks(
            [definition],
            [],
            frameworks=frameworks,
        )

    def test_prompt_injection_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-a",
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm01 = [c for c in report.checks if c.check_id == "LLM01"]
        assert len(llm01) == 1
        assert llm01[0].status == "pass"

    def test_prompt_injection_fail(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = False
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = False
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = False
            definition = {
                "name": "agent-a",
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm01 = [c for c in report.checks if c.check_id == "LLM01"]
        assert len(llm01) == 1
        assert llm01[0].status == "fail"

    def test_tool_access_control_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-b",
                "allowed_tools": ["ai_complete"],
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm06 = [c for c in report.checks if c.check_id == "LLM06"]
        assert len(llm06) == 1
        assert llm06[0].status == "pass"

    def test_tool_access_control_fail(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-c",
                "allowed_tools": [],
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm06 = [c for c in report.checks if c.check_id == "LLM06"]
        assert len(llm06) == 1
        assert llm06[0].status == "fail"

    def test_resource_limits_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-d",
                "governance_policy": {"max_spend_per_run_usd": 1.0},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm10 = [c for c in report.checks if c.check_id == "LLM10"]
        assert len(llm10) == 1
        assert llm10[0].status == "pass"

    def test_resource_limits_fail(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-e",
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["owasp_llm"])
        llm10 = [c for c in report.checks if c.check_id == "LLM10"]
        assert len(llm10) == 1
        assert llm10[0].status == "fail"


# ── TestEUAIActChecks ─────────────────────────────────────────────────


class TestEUAIActChecks:
    """EU AI Act regulatory compliance checks."""

    def _run(self, definition, *, frameworks=None):
        engine = ComplianceEngine(tenant_id="test-tenant")
        return engine.run_compliance_checks(
            [definition],
            [],
            frameworks=frameworks,
        )

    def test_risk_management_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-rm",
                "max_steps_per_run": 50,
                "max_duration_seconds": 300,
                "governance_policy": {"max_spend_per_run_usd": 1.0},
            }
            report = self._run(definition, frameworks=["eu_ai_act"])
        art9 = [c for c in report.checks if c.check_id == "ART_9"]
        assert len(art9) == 1
        assert art9[0].status == "pass"

    def test_risk_management_fail(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-rm-bad",
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["eu_ai_act"])
        art9 = [c for c in report.checks if c.check_id == "ART_9"]
        assert len(art9) == 1
        assert art9[0].status == "fail"

    def test_human_oversight_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-ho",
                "governance_policy": {
                    "require_approval_for": ["code_execute"],
                },
            }
            report = self._run(definition, frameworks=["eu_ai_act"])
        art14 = [c for c in report.checks if c.check_id == "ART_14"]
        assert len(art14) == 1
        assert art14[0].status == "pass"

    def test_transparency_pass(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            definition = {
                "name": "agent-tr",
                "description": "A transparent agent for testing.",
                "governance_policy": {},
            }
            report = self._run(definition, frameworks=["eu_ai_act"])
        art13 = [c for c in report.checks if c.check_id == "ART_13"]
        assert len(art13) == 1
        assert art13[0].status == "pass"


# ── TestComplianceReport ──────────────────────────────────────────────


class TestComplianceReport:
    """Compliance report scoring and serialization."""

    def _make_report(self, statuses):
        from app.agents.compliance import ComplianceCheck

        report = ComplianceReport(
            tenant_id="t1",
            frameworks=["owasp_llm"],
        )
        for i, status in enumerate(statuses):
            report.checks.append(
                ComplianceCheck(
                    framework="owasp_llm",
                    check_id=f"CHECK_{i}",
                    description=f"Check {i}",
                    status=status,
                ),
            )
        # Recalculate summary
        for c in report.checks:
            if c.status == "pass":
                report.passed += 1
            elif c.status == "fail":
                report.failed += 1
            elif c.status == "warning":
                report.warnings += 1
        total = report.passed + report.failed + report.warnings
        report.score = report.passed / total if total > 0 else 0.0
        return report

    def test_report_summary(self):
        report = self._make_report(["pass", "pass", "pass", "fail", "warning"])
        assert report.passed == 3
        assert report.failed == 1
        assert report.warnings == 1
        assert report.score == pytest.approx(0.6)

    def test_report_to_dict(self):
        report = self._make_report(["pass", "fail"])
        d = report.to_dict()
        assert "summary" in d
        assert d["summary"]["passed"] == 1
        assert d["summary"]["failed"] == 1
        assert "checks" in d
        assert len(d["checks"]) == 2
        assert d["tenant_id"] == "t1"
        assert d["frameworks"] == ["owasp_llm"]

    def test_framework_filter(self):
        with patch("app.agents.compliance.settings") as mock_settings:
            mock_settings.PROMPT_FIREWALL_ENABLED = True
            mock_settings.PROMPT_FIREWALL_CANARY_ENABLED = True
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = True
            engine = ComplianceEngine(tenant_id="t2")
            definition = {
                "name": "agent-filter",
                "governance_policy": {"max_spend_per_run_usd": 1.0},
            }
            report = engine.run_compliance_checks(
                [definition],
                [],
                frameworks=["owasp_llm"],
            )
        # Only OWASP checks should be present; no NIST or EU checks
        frameworks_found = {c.framework for c in report.checks}
        assert "owasp_llm" in frameworks_found
        assert "nist_ai_rmf" not in frameworks_found
        assert "eu_ai_act" not in frameworks_found


# ── TestAgentCard ─────────────────────────────────────────────────────


class TestAgentCard:
    """Agent card (transparency documentation) generation."""

    def _engine(self):
        return ComplianceEngine(tenant_id="t1")

    def test_card_generation(self):
        definition = {
            "id": "abc-123",
            "name": "my-agent",
            "description": "A test agent.",
            "model": "gpt-4o",
            "allowed_tools": ["ai_complete"],
            "governance_policy": {},
        }
        card = self._engine().generate_agent_card(definition)
        assert card.agent_name == "my-agent"
        assert card.model == "gpt-4o"
        assert "ai_complete" in card.allowed_tools

    def test_risk_level_high(self):
        definition = {
            "name": "risky-agent",
            "allowed_tools": ["code_execute", "ai_complete"],
            "governance_policy": {},
        }
        card = self._engine().generate_agent_card(definition)
        assert card.risk_level == "high"

    def test_risk_level_low(self):
        definition = {
            "name": "safe-agent",
            "allowed_tools": ["ai_complete"],
            "governance_policy": {},
        }
        card = self._engine().generate_agent_card(definition)
        assert card.risk_level == "low"

    def test_card_to_dict(self):
        definition = {
            "id": "xyz-789",
            "name": "card-agent",
            "description": "Docs agent.",
            "model": "gpt-4o-mini",
            "allowed_tools": ["ai_complete"],
            "governance_policy": {"require_approval_for": ["code_execute"]},
        }
        card = self._engine().generate_agent_card(definition)
        d = card.to_dict()
        expected_keys = {
            "agent_id",
            "agent_name",
            "description",
            "model",
            "capabilities",
            "limitations",
            "allowed_tools",
            "governance",
            "risk_level",
            "data_classification_max",
            "sandbox_enabled",
            "human_oversight",
            "last_updated",
        }
        assert expected_keys == set(d.keys())
        assert d["human_oversight"] is True
