"""Tests for the multi-agent orchestrator."""

from __future__ import annotations

from app.agents.orchestrator import AgentOrchestrator


class TestInputResolution:
    def test_resolve_input_with_dot_notation(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        step_outputs = {
            "_input": {"query": "hello"},
            "step_a": {"output": {"summary": "world"}},
        }

        mapping = {
            "prompt": "$._input.query",
            "context": "$.step_a.output.summary",
        }

        result = orch._resolve_input(mapping, step_outputs, {"query": "hello"})
        assert result == {"prompt": "hello", "context": "world"}

    def test_resolve_input_missing_path(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        result = orch._resolve_input(
            {"x": "$.nonexistent.path"},
            {},
            {},
        )
        assert result == {"x": None}

    def test_resolve_input_no_mapping(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        original = {"key": "value"}
        result = orch._resolve_input({}, {}, original)
        assert result is original


class TestTransitionResolution:
    def test_always_transition(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        transitions = [
            {"from": "step_a", "to": "step_b", "condition": "always"},
        ]
        assert orch._resolve_next_step("step_a", transitions, {}) == "step_b"

    def test_on_success_transition(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        transitions = [
            {"from": "step_a", "to": "step_b", "condition": "on_success"},
        ]
        # No error → success
        assert orch._resolve_next_step("step_a", transitions, {"output": "ok"}) == "step_b"
        # With error → no match
        assert orch._resolve_next_step("step_a", transitions, {"error": "failed"}) is None

    def test_on_failure_transition(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        transitions = [
            {"from": "step_a", "to": "error_handler", "condition": "on_failure"},
        ]
        assert orch._resolve_next_step("step_a", transitions, {"error": "boom"}) == "error_handler"
        assert orch._resolve_next_step("step_a", transitions, {"output": "ok"}) is None

    def test_no_matching_transition(self):
        orch = AgentOrchestrator.__new__(AgentOrchestrator)

        transitions = [
            {"from": "step_b", "to": "step_c", "condition": "always"},
        ]
        # No transition from step_a → returns None (workflow ends)
        assert orch._resolve_next_step("step_a", transitions, {}) is None
