"""OTel instrument definitions following GenAI semantic conventions.

Creates OTel counters and histograms that bridge to the existing
Prometheus /metrics endpoint via PrometheusMetricReader.

Usage:
    from app.core.otel_metrics import record_agent_run, record_tool_call

    record_agent_run(agent_name="my-agent", status="completed", tokens=1500, cost=0.03)
    record_tool_call(tool_name="search", duration_ms=120)
"""

from __future__ import annotations

import contextlib

from app.core.telemetry import get_meter

_meter = None
_agent_runs_counter = None
_agent_step_duration = None
_agent_tool_duration = None
_client_requests_counter = None
_client_token_usage = None


def _ensure_instruments():
    """Lazily create OTel instruments on first use."""
    global _meter, _agent_runs_counter, _agent_step_duration, _agent_tool_duration
    global _client_requests_counter, _client_token_usage

    if _agent_runs_counter is not None:
        return

    _meter = get_meter()

    _client_requests_counter = _meter.create_counter(
        name="gen_ai.client.requests",
        description="Number of LLM API requests",
        unit="1",
    )

    _client_token_usage = _meter.create_counter(
        name="gen_ai.client.token.usage",
        description="Token usage for LLM requests",
        unit="token",
    )

    _agent_runs_counter = _meter.create_counter(
        name="gen_ai.agent.runs",
        description="Number of agent runs",
        unit="1",
    )

    _agent_step_duration = _meter.create_histogram(
        name="gen_ai.agent.step_duration",
        description="Duration of individual agent steps",
        unit="ms",
    )

    _agent_tool_duration = _meter.create_histogram(
        name="gen_ai.agent.tool_duration",
        description="Duration of tool call execution",
        unit="ms",
    )


def record_agent_run(
    *,
    agent_name: str,
    status: str,
    tokens: int = 0,
    cost_usd: float = 0.0,
    steps: int = 0,
) -> None:
    """Record an agent run completion."""
    with contextlib.suppress(Exception):
        _ensure_instruments()
        _agent_runs_counter.add(
            1,
            {
                "gen_ai.agent.name": agent_name,
                "gen_ai.response.finish_reason": status,
            },
        )
        if tokens > 0:
            _client_token_usage.add(
                tokens,
                {
                    "gen_ai.agent.name": agent_name,
                    "gen_ai.token.type": "total",
                },
            )


def record_step_duration(
    *,
    agent_name: str,
    step_number: int,
    duration_ms: int,
    action: str,
) -> None:
    """Record the duration of an agent step."""
    with contextlib.suppress(Exception):
        _ensure_instruments()
        _agent_step_duration.record(
            duration_ms,
            {
                "gen_ai.agent.name": agent_name,
                "gen_ai.agent.step_number": step_number,
                "agent.action": action,
            },
        )


def record_tool_call(
    *,
    tool_name: str,
    duration_ms: int,
    status: str = "success",
) -> None:
    """Record a tool call execution."""
    with contextlib.suppress(Exception):
        _ensure_instruments()
        _agent_tool_duration.record(
            duration_ms,
            {
                "gen_ai.tool.name": tool_name,
                "gen_ai.response.finish_reason": status,
            },
        )


def record_llm_request(
    *,
    model: str,
    provider: str = "unknown",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record an LLM API request."""
    with contextlib.suppress(Exception):
        _ensure_instruments()
        _client_requests_counter.add(
            1,
            {
                "gen_ai.request.model": model,
                "gen_ai.system": provider,
            },
        )
        if prompt_tokens > 0:
            _client_token_usage.add(
                prompt_tokens,
                {
                    "gen_ai.request.model": model,
                    "gen_ai.token.type": "input",
                },
            )
        if completion_tokens > 0:
            _client_token_usage.add(
                completion_tokens,
                {
                    "gen_ai.request.model": model,
                    "gen_ai.token.type": "output",
                },
            )
