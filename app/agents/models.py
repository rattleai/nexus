"""SQLAlchemy models for the agent execution layer.

All models are tenant-scoped via RLS (tenant_id column + set_tenant_context).
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, VersionMixin

# ── Enums ──────────────────────────────────────────────────────────────


class AgentStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class InstanceStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions for agent instances.
# Enforced by AgentInstance.validate_status_transition().
VALID_INSTANCE_TRANSITIONS: dict[InstanceStatus, set[InstanceStatus]] = {
    InstanceStatus.PENDING: {InstanceStatus.RUNNING, InstanceStatus.CANCELLED, InstanceStatus.FAILED},
    InstanceStatus.RUNNING: {
        InstanceStatus.COMPLETED,
        InstanceStatus.FAILED,
        InstanceStatus.CANCELLED,
        InstanceStatus.PAUSED,
    },
    InstanceStatus.PAUSED: {InstanceStatus.RUNNING, InstanceStatus.CANCELLED, InstanceStatus.FAILED},
    InstanceStatus.COMPLETED: set(),
    InstanceStatus.FAILED: set(),
    InstanceStatus.CANCELLED: set(),
}


class SessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class WorkflowStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class WorkflowRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolSource(enum.StrEnum):
    BUILTIN = "builtin"
    TENANT = "tenant"
    MARKETPLACE = "marketplace"


# ── Agent Definition ───────────────────────────────────────────────────


class AgentDefinition(Base, TimestampMixin, SoftDeleteMixin, AuditMixin, VersionMixin):
    """Tenant-scoped blueprint for an AI agent.

    Defines the agent's personality, capabilities, constraints, and runtime
    configuration. Multiple instances can be spawned from one definition.
    """

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_agent_def_tenant_slug"),
        Index("ix_agent_def_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status", values_callable=lambda e: [m.value for m in e]),
        default=AgentStatus.DRAFT,
        nullable=False,
    )

    # AI configuration
    system_prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    model: Mapped[str] = mapped_column(String(100), default="gpt-4o", server_default="gpt-4o")
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Tool access — JSON array of tool names this agent may invoke (legacy)
    allowed_tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Capability-based tool access — list of capability slugs (e.g. "myapp:items:write").
    # When non-empty, resolved to tool names at runtime and unioned with allowed_tools.
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Tool version pinning — JSON object {"tool_name": version_int}
    # When set, the agent uses the pinned schema version instead of latest
    tool_versions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Execution constraints
    max_steps_per_run: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    max_tokens_per_run: Mapped[int] = mapped_column(Integer, default=100_000, server_default="100000")
    sandbox_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Parallel tool execution — when True, multiple tool calls are run concurrently
    parallel_tool_execution: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Maximum concurrent running instances (0 = unlimited)
    max_concurrent_instances: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Memory configuration
    memory_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Output validation — JSON schema enforced on agent responses
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Governance policy (inline or reference to AgentPolicy)
    governance_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Database access policy — controls which tables/patterns the agent can query
    db_access_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Behavioral baseline for threat detection (auto-populated after runs)
    behavioral_baseline: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Arbitrary metadata
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")

    # Relationships
    instances: Mapped[list[AgentInstance]] = relationship(back_populates="definition", lazy="raise")


# ── Agent Instance ─────────────────────────────────────────────────────


class AgentInstance(Base, TimestampMixin):
    """A running (or stopped) instance of an AgentDefinition.

    Tracks resource consumption, status, and links to sessions.
    """

    __tablename__ = "agent_instances"
    __table_args__ = (
        Index("ix_agent_inst_tenant_status", "tenant_id", "status"),
        Index("ix_agent_inst_definition", "definition_id"),
        Index("ix_agent_inst_status_heartbeat", "status", "last_heartbeat_at"),
        Index("ix_agent_inst_session", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_definitions.id"),
        nullable=False,
    )

    status: Mapped[InstanceStatus] = mapped_column(
        Enum(InstanceStatus, name="instance_status", values_callable=lambda e: [m.value for m in e]),
        default=InstanceStatus.PENDING,
        nullable=False,
    )

    # Execution tracking
    steps_executed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Heartbeat: updated every step to signal liveness (Temporal pattern)
    last_heartbeat_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Step checkpoint: last completed step's data for crash recovery & observability
    last_checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Input/output
    input_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Idempotency key for deduplication
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Capability token hash and scope for capability-based privilege system
    capability_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability_scope: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Parent conversation session (for multi-turn interactive runs)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id"),
        nullable=True,
    )

    # Parent workflow run (if spawned by orchestrator)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id"),
        nullable=True,
    )

    # Relationships
    definition: Mapped[AgentDefinition] = relationship(back_populates="instances")
    sessions: Mapped[list[AgentSession]] = relationship(
        back_populates="instance",
        foreign_keys="AgentSession.instance_id",
        lazy="raise",
    )

    @validates("status")
    def validate_status_transition(self, key: str, new_status: InstanceStatus) -> InstanceStatus:
        """Enforce valid state machine transitions for agent instances."""
        # Skip validation on initial creation (no previous state)
        state = self.__dict__.get("status")
        if state is None:
            return new_status
        old_status = InstanceStatus(state) if isinstance(state, str) else state
        valid_next = VALID_INSTANCE_TRANSITIONS.get(old_status)
        if valid_next is not None and new_status not in valid_next:
            raise ValueError(f"Invalid agent instance status transition: {old_status.value} -> {new_status.value}")
        return new_status


# ── Agent Session ──────────────────────────────────────────────────────


class AgentSession(Base, TimestampMixin):
    """A conversation or execution session within an agent instance.

    Sessions provide context continuity — each session has its own
    short-term memory (conversation history) while sharing long-term
    memory at the instance level.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index("ix_agent_session_instance", "instance_id"),
        Index("ix_agent_session_definition", "tenant_id", "definition_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_instances.id"),
        nullable=False,
    )

    # Direct link to the agent definition (for listing conversations per agent)
    definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_definitions.id"),
        nullable=True,
    )

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.ACTIVE,
        nullable=False,
    )
    messages: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Interactive conversation fields
    is_interactive: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0.0, server_default="0")
    last_activity_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600, server_default="3600")

    # Relationships
    instance: Mapped[AgentInstance] = relationship(back_populates="sessions", foreign_keys=[instance_id])


# ── Agent Memory Entry ─────────────────────────────────────────────────


class AgentMemoryEntry(Base, TimestampMixin):
    """Persistent key-value memory entries for an agent instance.

    Supports optional vector embeddings for semantic search (pgvector).
    """

    __tablename__ = "agent_memory_entries"
    __table_args__ = (
        UniqueConstraint("instance_id", "namespace", "key", name="uq_agent_memory_instance_ns_key"),
        Index("ix_agent_memory_tenant", "tenant_id"),
        Index("ix_agent_memory_instance_ns", "instance_id", "namespace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_instances.id"),
        nullable=False,
    )

    namespace: Mapped[str] = mapped_column(String(100), default="default", server_default="default")
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Optional vector embedding for semantic search (pgvector)
    # Stored as JSONB array; use pgvector extension for actual vector ops
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # TTL support
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Agent Definition Memory Entry ─────────────────────────────────────


class AgentDefinitionMemoryEntry(Base, TimestampMixin):
    """Persistent memory entries shared across all instances of an agent definition.

    Allows parallel instances of the same agent (e.g., periodic email checker
    and on-demand call handler) to share knowledge without being tied to a
    specific instance lifecycle.
    """

    __tablename__ = "agent_definition_memory_entries"
    __table_args__ = (
        UniqueConstraint("definition_id", "namespace", "key", name="uq_agent_def_memory_def_ns_key"),
        Index("ix_agent_def_memory_tenant", "tenant_id"),
        Index("ix_agent_def_memory_definition_ns", "definition_id", "namespace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    namespace: Mapped[str] = mapped_column(String(100), default="shared", server_default="shared")
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Optional vector embedding for semantic search
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # TTL support
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Workflow Definition ────────────────────────────────────────────────


class WorkflowDefinition(Base, TimestampMixin, SoftDeleteMixin, AuditMixin, VersionMixin):
    """Multi-agent workflow blueprint.

    Defines a DAG of agent steps with transitions and conditions.
    """

    __tablename__ = "workflow_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_workflow_def_tenant_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status", values_callable=lambda e: [m.value for m in e]),
        default=WorkflowStatus.DRAFT,
        nullable=False,
    )

    # DAG definition: list of steps with agent references and transitions
    # Format: {"steps": [...], "transitions": [...], "entry_step": "..."}
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Governance: max parallel agents, max total cost, require approval steps
    governance: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")


# ── Workflow Run ───────────────────────────────────────────────────────


class WorkflowRun(Base, TimestampMixin):
    """An execution of a WorkflowDefinition.

    Tracks the state machine as agents execute their steps.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_run_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_definitions.id"),
        nullable=False,
    )

    status: Mapped[WorkflowRunStatus] = mapped_column(
        Enum(WorkflowRunStatus, name="workflow_run_status", values_callable=lambda e: [m.value for m in e]),
        default=WorkflowRunStatus.PENDING,
        nullable=False,
    )

    # Current state: which steps are active, completed, pending
    state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    input_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Aggregated metrics
    total_steps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Tenant Tool ────────────────────────────────────────────────────────


class TenantTool(Base, TimestampMixin, SoftDeleteMixin):
    """Custom tool registered by a tenant for use by their agents.

    Each tool is an MCP-compatible endpoint that agents can invoke.
    """

    __tablename__ = "tenant_tools"
    __table_args__ = (UniqueConstraint("tenant_id", "tool_name", name="uq_tenant_tool_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    source: Mapped[ToolSource] = mapped_column(
        Enum(ToolSource, name="tool_source", values_callable=lambda e: [m.value for m in e]),
        default=ToolSource.TENANT,
        nullable=False,
    )

    # MCP tool schema
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Versioning — allows agents to pin to a specific tool version
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    version_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # External endpoint (for tenant-hosted tools)
    endpoint_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Supply chain verification
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_signature_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_level: Mapped[str] = mapped_column(
        String(20),
        default="untrusted",
        server_default="untrusted",
    )  # "verified", "trusted", "untrusted"

    # Health/status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    health_check_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")


# ── Agent Policy ───────────────────────────────────────────────────────


class AgentPolicy(Base, TimestampMixin, VersionMixin):
    """Reusable governance policy for agents.

    Defines spending limits, tool access controls, approval requirements,
    and rate limits. Can be referenced by multiple agent definitions.
    """

    __tablename__ = "agent_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_agent_policy_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Spending limits
    max_spend_per_run_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_spend_per_day_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_spend_per_month_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Tool access control
    allowed_tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    denied_tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Actions requiring human approval
    require_approval_for: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    approval_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    approval_default_action: Mapped[str] = mapped_column(String(10), default="deny", server_default="deny")

    # Rate limits (per-agent, separate from tenant-level)
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_steps_per_run: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Full policy document (for complex rules)
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class CapabilityPreset(Base, TimestampMixin, SoftDeleteMixin):
    """Pre-built capability profile for quick agent setup.

    System presets (``tenant_id=NULL``) are seeded via migrations and
    cannot be modified by tenants.  Tenant presets are fully CRUD-able.
    """

    __tablename__ = "capability_presets"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_capability_preset_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    icon: Mapped[str] = mapped_column(String(50), default="Shield", server_default="Shield")

    # Capability slugs this preset grants
    capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Optional extra raw tool names (for tenant-specific custom tools)
    additional_tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Bundled governance policy overrides applied when this preset is used
    governance_overrides: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # System presets are seeded at startup and cannot be edited by tenants
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
