"""SQLAlchemy models for RAG evaluation tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RAGEvaluationDataset(TimestampMixin, Base):
    """Ground truth dataset for offline evaluation."""

    __tablename__ = "rag_evaluation_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="human_annotation",
    )
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_rag_eval_datasets_tenant_name", "tenant_id", "name", unique=True),
    )


class RAGEvaluationQuery(TimestampMixin, Base):
    """Individual query-answer pair within a dataset."""

    __tablename__ = "rag_evaluation_queries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevant_chunk_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    relevance_grades: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_rag_eval_queries_dataset", "tenant_id", "dataset_id"),
    )


class RAGEvaluationRun(TimestampMixin, Base):
    """A single evaluation run (batch execution against a dataset)."""

    __tablename__ = "rag_evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    aggregate_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_rag_eval_runs_tenant_dataset", "tenant_id", "dataset_id", "created_at"),
    )


class RAGEvaluationResult(Base):
    """Per-query results within an evaluation run."""

    __tablename__ = "rag_evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    retrieved_scores: Mapped[list | None] = mapped_column(ARRAY(Float), nullable=True)
    precision_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndcg_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_rag_eval_results_run", "tenant_id", "run_id"),
    )


class RAGQueryLog(Base):
    """Production query analytics (sampled or full)."""

    __tablename__ = "rag_query_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    reranked: Mapped[bool] = mapped_column(default=False)
    empty_result: Mapped[bool] = mapped_column(default=False)
    search_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_rag_query_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_rag_query_logs_empty", "tenant_id", "empty_result"),
    )
