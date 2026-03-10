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
