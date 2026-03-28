"""Add capability-based agent permissions and preset system.

Adds:
- capabilities JSONB column to agent_definitions (list of capability slugs)
- capability_presets table for pre-built and tenant-custom permission profiles
- Seeds system presets for common agent roles

Revision ID: 0022_capability_model
Revises: 0021_datasource_rls_and_indexes
Create Date: 2026-03-27
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022_capability_model"
down_revision = "0021_datasource_rls_and_indexes"
branch_labels = None
depends_on = None


# ── System presets ────────────────────────────────────────────────────

SYSTEM_PRESETS = [
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:full-product-manager")),
        "name": "Full Product Manager",
        "slug": "full-product-manager",
        "description": "Full read/write/delete access to all product configurator capabilities plus AI and file tools.",
        "icon": "ShieldCheck",
        "capabilities": [
            "cpq:products:read", "cpq:products:write", "cpq:products:delete",
            "cpq:characteristics:read", "cpq:characteristics:write",
            "cpq:constraints:read", "cpq:constraints:write", "cpq:constraints:delete",
            "cpq:bom:write",
            "cpq:pricing:read", "cpq:pricing:write", "cpq:pricing:delete",
            "cpq:configurator", "cpq:data", "cpq:versioning",
            "platform:ai", "platform:files",
        ],
        "governance_overrides": {
            "require_approval_for_capabilities": ["cpq:products:delete", "cpq:pricing:delete"],
        },
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:read-only-analyst")),
        "name": "Read-Only Analyst",
        "slug": "read-only-analyst",
        "description": "View-only access to products, characteristics, constraints, and pricing simulations.",
        "icon": "Eye",
        "capabilities": [
            "cpq:products:read", "cpq:characteristics:read",
            "cpq:constraints:read", "cpq:pricing:read",
            "cpq:configurator",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:configuration-builder")),
        "name": "Configuration Builder",
        "slug": "configuration-builder",
        "description": "Create and manage product configurators: products, characteristics, constraints, and versions.",
        "icon": "Wrench",
        "capabilities": [
            "cpq:products:read", "cpq:products:write",
            "cpq:characteristics:read", "cpq:characteristics:write",
            "cpq:constraints:read", "cpq:constraints:write",
            "cpq:configurator", "cpq:data", "cpq:versioning",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:pricing-specialist")),
        "name": "Pricing Specialist",
        "slug": "pricing-specialist",
        "description": "Manage pricing rules and simulate pricing for product configurations.",
        "icon": "DollarSign",
        "capabilities": [
            "cpq:products:read", "cpq:characteristics:read",
            "cpq:pricing:read", "cpq:pricing:write",
            "cpq:configurator",
            "platform:ai",
        ],
        "governance_overrides": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "preset:code-assistant")),
        "name": "Code Assistant",
        "slug": "code-assistant",
        "description": "AI-powered code execution with file access for data processing and analysis.",
        "icon": "Code",
        "capabilities": [
            "platform:ai", "platform:files", "platform:code",
        ],
        "governance_overrides": {
            "max_cost_per_run_usd": 2.0,
        },
    },
]


def upgrade() -> None:
    # 1. Add capabilities column to agent_definitions
    op.add_column(
        "agent_definitions",
        sa.Column("capabilities", JSONB, server_default="[]", nullable=False),
    )

    # 2. Create capability_presets table
    op.create_table(
        "capability_presets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("icon", sa.String(50), server_default="Shield", nullable=False),
        sa.Column("capabilities", JSONB, nullable=False),
        sa.Column("additional_tools", JSONB, server_default="[]", nullable=False),
        sa.Column("governance_overrides", JSONB, server_default="{}", nullable=False),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_capability_preset_slug"),
    )

    # 3. Seed system presets
    presets_table = sa.table(
        "capability_presets",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("tenant_id", UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("description", sa.Text),
        sa.column("icon", sa.String),
        sa.column("capabilities", JSONB),
        sa.column("additional_tools", JSONB),
        sa.column("governance_overrides", JSONB),
        sa.column("is_system", sa.Boolean),
    )

    op.bulk_insert(presets_table, [
        {
            "id": p["id"],
            "tenant_id": None,
            "name": p["name"],
            "slug": p["slug"],
            "description": p["description"],
            "icon": p["icon"],
            "capabilities": p["capabilities"],
            "additional_tools": [],
            "governance_overrides": p["governance_overrides"],
            "is_system": True,
        }
        for p in SYSTEM_PRESETS
    ])


def downgrade() -> None:
    op.drop_table("capability_presets")
    op.drop_column("agent_definitions", "capabilities")
