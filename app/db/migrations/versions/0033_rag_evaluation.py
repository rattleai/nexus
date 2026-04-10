"""Add RAG evaluation tables for systematic retrieval quality measurement.

Tables:
  - rag_evaluation_datasets: ground truth datasets
  - rag_evaluation_queries: query-answer pairs within datasets
  - rag_evaluation_runs: batch evaluation executions
  - rag_evaluation_results: per-query metrics within runs
  - rag_query_logs: production query analytics (sampled)

Revision ID: 0033_rag_evaluation
Revises: 0032_contextual_retrieval
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0033_rag_evaluation"
down_revision = "0032_contextual_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Evaluation datasets ────────────────────────────────────
    op.create_table(
        "rag_evaluation_datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="human_annotation"),
        sa.Column("query_count", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_eval_datasets_tenant_name", "rag_evaluation_datasets", ["tenant_id", "name"], unique=True)

    # ── Evaluation queries ─────────────────────────────────────
    op.create_table(
        "rag_evaluation_queries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("expected_answer", sa.Text, nullable=True),
        sa.Column("relevant_chunk_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("relevance_grades", JSONB, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_eval_queries_dataset", "rag_evaluation_queries", ["tenant_id", "dataset_id"])

    # ── Evaluation runs ────────────────────────────────────────
    op.create_table(
        "rag_evaluation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("aggregate_metrics", JSONB, nullable=True),
        sa.Column("query_count", sa.Integer, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_eval_runs_tenant_dataset", "rag_evaluation_runs", ["tenant_id", "dataset_id", "created_at"])

    # ── Evaluation results ─────────────────────────────────────
    op.create_table(
        "rag_evaluation_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", UUID(as_uuid=True), nullable=False),
        sa.Column("retrieved_chunk_ids", ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("retrieved_scores", ARRAY(sa.Float), nullable=True),
        sa.Column("precision_at_k", sa.Float, nullable=True),
        sa.Column("recall_at_k", sa.Float, nullable=True),
        sa.Column("mrr", sa.Float, nullable=True),
        sa.Column("ndcg_at_k", sa.Float, nullable=True),
        sa.Column("faithfulness", sa.Float, nullable=True),
        sa.Column("answer_relevancy", sa.Float, nullable=True),
        sa.Column("generated_answer", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_eval_results_run", "rag_evaluation_results", ["tenant_id", "run_id"])

    # ── Query logs ─────────────────────────────────────────────
    op.create_table(
        "rag_query_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("search_type", sa.String(20), nullable=True),
        sa.Column("result_count", sa.Integer, nullable=True),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("mean_score", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("cache_hit", sa.Boolean, server_default="false"),
        sa.Column("reranked", sa.Boolean, server_default="false"),
        sa.Column("empty_result", sa.Boolean, server_default="false"),
        sa.Column("search_config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rag_query_logs_tenant_created", "rag_query_logs", ["tenant_id", "created_at"])
    op.create_index("ix_rag_query_logs_empty", "rag_query_logs", ["tenant_id", "empty_result"])

    # ── Enable RLS on all new tables ───────────────────────────
    for table in [
        "rag_evaluation_datasets",
        "rag_evaluation_queries",
        "rag_evaluation_runs",
        "rag_evaluation_results",
        "rag_query_logs",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """)


def downgrade() -> None:
    for table in [
        "rag_query_logs",
        "rag_evaluation_results",
        "rag_evaluation_runs",
        "rag_evaluation_queries",
        "rag_evaluation_datasets",
    ]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
