"""Add materialized views and A/B testing infrastructure.

Materialized views provide fast pre-computed tenant statistics.
A/B testing tables enable comparing retrieval strategies with
statistical significance.

Revision ID: 0034_materialized_views_and_ab
Revises: 0033_rag_evaluation
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0034_materialized_views_and_ab"
down_revision = "0033_rag_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Materialized view: per-tenant chunk statistics ─────────
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tenant_chunk_stats AS
        SELECT tenant_id,
               COUNT(*) AS chunk_count,
               COUNT(*) FILTER (WHERE embedding_vec IS NOT NULL) AS embedded_count,
               COUNT(*) FILTER (WHERE parent_chunk_id IS NOT NULL) AS child_count,
               COUNT(*) FILTER (WHERE context_preamble IS NOT NULL) AS contextualized_count,
               MAX(indexed_at) AS last_indexed_at
        FROM data_source_chunks
        GROUP BY tenant_id
        WITH DATA
    """)

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_tenant_chunk_stats_tenant "
        "ON mv_tenant_chunk_stats (tenant_id)"
    )

    # ── A/B testing: experiments ───────────────────────────────
    op.create_table(
        "rag_ab_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("control_config", JSONB, nullable=False),
        sa.Column("variant_config", JSONB, nullable=False),
        sa.Column("traffic_split", sa.Float, server_default="0.5"),
        sa.Column("sample_size_target", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", JSONB, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_ab_experiments_tenant_name", "rag_ab_experiments", ["tenant_id", "name"], unique=True)
    op.create_index("ix_rag_ab_experiments_status", "rag_ab_experiments", ["tenant_id", "status"])

    # ── A/B testing: per-query assignments ─────────────────────
    op.create_table(
        "rag_ab_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_log_id", UUID(as_uuid=True), nullable=True),
        sa.Column("arm", sa.String(20), nullable=False),
        sa.Column("config_used", JSONB, nullable=False),
        sa.Column("result_count", sa.Integer, nullable=True),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("user_feedback", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rag_ab_assignments_experiment",
        "rag_ab_assignments",
        ["tenant_id", "experiment_id", "arm", "created_at"],
    )

    # ── Enable RLS ─────────────────────────────────────────────
    for table in ["rag_ab_experiments", "rag_ab_assignments"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """)


def downgrade() -> None:
    for table in ["rag_ab_assignments", "rag_ab_experiments"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)

    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_tenant_chunk_stats")
