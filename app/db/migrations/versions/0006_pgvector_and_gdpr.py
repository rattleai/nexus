"""Add pgvector extension, convert embedding column, add GDPR tables, add tool versioning.

Revision ID: 0006_pgvector_and_gdpr
Revises: 0005_add_locale_to_users
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006_pgvector_and_gdpr"
down_revision = "0005_add_locale_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension ───────────────────────────────────────
    # Install pgvector if available (requires the extension to be installed
    # on the PostgreSQL server). Falls back gracefully if not present.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Convert embedding column from JSONB to native vector type
    # Step 1: Add new vector column
    op.execute(
        "ALTER TABLE agent_memory_entries "
        "ADD COLUMN IF NOT EXISTS embedding_vec vector(1536)"
    )

    # Step 2: Migrate existing JSONB embeddings to vector column
    # Use a subquery with array_agg to safely handle malformed data
    # instead of a direct cast that would abort the entire migration.
    op.execute("""
        UPDATE agent_memory_entries
        SET embedding_vec = (
            SELECT array_agg(v::float)::vector
            FROM jsonb_array_elements_text(embedding) AS v
        )
        WHERE embedding IS NOT NULL
          AND jsonb_typeof(embedding) = 'array'
          AND jsonb_array_length(embedding) = 1536
    """)

    # Step 3: Create HNSW index CONCURRENTLY to avoid blocking the table.
    # CONCURRENTLY cannot run inside a transaction, so we end the
    # Alembic-managed transaction first.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_memory_embedding_vec "
        "ON agent_memory_entries USING hnsw (embedding_vec vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ── GDPR tables ──────────────────────────────────────────────

    op.create_table(
        "consents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("consent_type", sa.String(50), nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_consents_user_type", "consents", ["user_id", "consent_type"])
    op.create_index("ix_consents_tenant", "consents", ["tenant_id"])

    op.create_table(
        "data_subject_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="received"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("response_notes", sa.Text, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("processed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dsar_tenant_status", "data_subject_requests", ["tenant_id", "status"])
    op.create_index("ix_dsar_user", "data_subject_requests", ["user_id"])

    op.create_table(
        "data_retention_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("retention_days", sa.Integer, nullable=False),
        sa.Column("archive_before_delete", sa.Boolean, server_default="true"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_retention_tenant_resource",
        "data_retention_policies",
        ["tenant_id", "resource_type"],
        unique=True,
    )

    # ── Agent definition new columns ─────────────────────────────

    op.add_column(
        "agent_definitions",
        sa.Column("output_schema", JSONB, server_default="{}", nullable=False),
    )
    op.add_column(
        "agent_definitions",
        sa.Column("tool_versions", JSONB, server_default="{}", nullable=False),
    )

    # ── Tool versioning columns ──────────────────────────────────

    op.add_column(
        "tenant_tools",
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
    )
    op.add_column(
        "tenant_tools",
        sa.Column("version_notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_tools", "version_notes")
    op.drop_column("tenant_tools", "version")
    op.drop_column("agent_definitions", "tool_versions")
    op.drop_column("agent_definitions", "output_schema")

    op.drop_table("data_retention_policies")
    op.drop_table("data_subject_requests")
    op.drop_table("consents")

    op.drop_index("ix_agent_memory_embedding_vec", table_name="agent_memory_entries")
    op.execute("ALTER TABLE agent_memory_entries DROP COLUMN IF EXISTS embedding_vec")
    op.execute("DROP EXTENSION IF EXISTS vector")
