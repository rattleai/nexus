"""Domain events for the agent execution layer.

All agent events extend DomainEvent and are emitted via emit(event, durable=True)
so they're persisted to the Redis Streams event bus for cross-process delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.events import DomainEvent


@dataclass
class AgentDefinitionCreated(DomainEvent):
    tenant_id: str = ""
    agent_id: str = ""
    name: str = ""
    slug: str = ""


@dataclass
class AgentDefinitionUpdated(DomainEvent):
    tenant_id: str = ""
    agent_id: str = ""
    changes: dict = field(default_factory=dict)


@dataclass
class AgentInstanceStarted(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    input_summary: str = ""


@dataclass
class AgentStepCompleted(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    step_number: int = 0
    action: str = ""
    tool_name: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass
class AgentInstanceCompleted(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    steps_executed: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class AgentInstanceFailed(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    error: str = ""
    step_number: int = 0


@dataclass
class AgentInstanceStopped(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    reason: str = ""


@dataclass
class AgentMemoryUpdated(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    namespace: str = ""
    key: str = ""
    action: str = ""  # "set", "delete", "clear"


@dataclass
class AgentGovernanceViolation(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    violation_type: str = ""  # "spending_limit", "denied_tool", "rate_limit"
    details: str = ""


@dataclass
class AgentApprovalRequested(DomainEvent):
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    action: str = ""
    approval_id: str = ""
    timeout_seconds: int = 300


@dataclass
class AgentApprovalResolved(DomainEvent):
    tenant_id: str = ""
    approval_id: str = ""
    decision: str = ""  # "approved", "denied", "timeout"
    resolved_by: str = ""


@dataclass
class WorkflowRunStarted(DomainEvent):
    tenant_id: str = ""
    workflow_id: str = ""
    run_id: str = ""


@dataclass
class WorkflowStepCompleted(DomainEvent):
    tenant_id: str = ""
    run_id: str = ""
    step_name: str = ""
    agent_id: str = ""
    status: str = ""


@dataclass
class WorkflowRunCompleted(DomainEvent):
    tenant_id: str = ""
    workflow_id: str = ""
    run_id: str = ""
    total_steps: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class WorkflowRunFailed(DomainEvent):
    tenant_id: str = ""
    workflow_id: str = ""
    run_id: str = ""
    error: str = ""
    failed_step: str = ""


# ── Security Events (Phase 0-2) ──────────────────────────────────────


@dataclass
class AgentDBQueryBlocked(DomainEvent):
    """Emitted when the DB gateway blocks an agent query."""
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    reason: str = ""  # "disallowed_pattern", "row_limit", "complexity", "rate_limit"
    query_hash: str = ""


@dataclass
class PromptInjectionDetected(DomainEvent):
    """Emitted when the prompt firewall detects a potential injection."""
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    layer: str = ""  # "structural", "canary_leak", "cross_agent", "classifier"
    detail: str = ""
    blocked: bool = False


@dataclass
class AgentThreatDetected(DomainEvent):
    """Emitted when the threat detection engine flags anomalous behavior."""
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    anomaly_score: float = 0.0
    factors: dict = field(default_factory=dict)
    action_taken: str = ""  # "warn", "pause", "suspend"
    atlas_technique: str = ""


@dataclass
class AgentCapabilityEscalation(DomainEvent):
    """Emitted when an agent requests elevated capabilities."""
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    requested_capabilities: list = field(default_factory=list)
    granted: bool = False


@dataclass
class ToolSchemaViolation(DomainEvent):
    """Emitted when a tool's schema drifts from its registered hash."""
    tenant_id: str = ""
    tool_name: str = ""
    expected_hash: str = ""
    actual_hash: str = ""


@dataclass
class A2AMessageSecurityEvent(DomainEvent):
    """Emitted when A2A message security detects an issue."""
    tenant_id: str = ""
    from_instance: str = ""
    to_instance: str = ""
    issue: str = ""  # "signature_invalid", "replay_detected", "injection_detected"


@dataclass
class DataClassificationViolation(DomainEvent):
    """Emitted when an agent accesses data above its classification level."""
    tenant_id: str = ""
    instance_id: str = ""
    agent_id: str = ""
    data_level: str = ""
    agent_max_level: str = ""


@dataclass
class ComplianceCheckCompleted(DomainEvent):
    """Emitted when a compliance check run finishes."""
    tenant_id: str = ""
    framework: str = ""  # "owasp_llm", "nist_ai_rmf", "eu_ai_act"
    passed: int = 0
    failed: int = 0
    warnings: int = 0
