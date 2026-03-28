"""Add parallel agent instance support: max_concurrent_instances + definition-scoped memory.

Revision ID: 0012_parallel_agent_instances
Revises: 0011_gdpr_rls_policies
Create Date: 2026-03-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012_parallel_agent_instances"
down_revision = "0011_gdpr_rls_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add max_concurrent_instances to agent_definitions (0 = unlimited)
    op.execute(text(
        "ALTER TABLE agent_definitions "
        "ADD COLUMN IF NOT EXISTS max_concurrent_instances INTEGER NOT NULL DEFAULT 0"
    ))

    # Create definition-scoped shared memory table (idempotent)
    conn = op.get_bind()
    table_exists = conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_definition_memory_entries'"
    )).scalar()

    if not table_exists:
        op.create_table(
            "agent_definition_memory_entries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("agent_definitions.id"), nullable=False),
            sa.Column("namespace", sa.String(100), server_default="shared", nullable=False),
            sa.Column("key", sa.String(500), nullable=False),
            sa.Column("value", JSONB, nullable=False),
            sa.Column("embedding", JSONB, nullable=True),
            sa.Column("embedding_model", sa.String(100), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("definition_id", "namespace", "key", name="uq_agent_def_memory_def_ns_key"),
        )

    op.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_def_memory_tenant ON agent_definition_memory_entries (tenant_id)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_def_memory_definition_ns ON agent_definition_memory_entries (definition_id, namespace)"))

    # Enable RLS on new table
    op.execute(text("ALTER TABLE agent_definition_memory_entries ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE agent_definition_memory_entries FORCE ROW LEVEL SECURITY"))
    op.execute(text("""
        DO $$ BEGIN
            CREATE POLICY agent_def_memory_tenant_isolation ON agent_definition_memory_entries
                USING (tenant_id = current_setting('app.tenant_id')::uuid)
                WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """))


def downgrade() -> None:
    op.execute(text("DROP POLICY IF EXISTS agent_def_memory_tenant_isolation ON agent_definition_memory_entries"))
    op.execute(text("DROP TABLE IF EXISTS agent_definition_memory_entries"))
    op.execute(text("ALTER TABLE agent_definitions DROP COLUMN IF EXISTS max_concurrent_instances"))
