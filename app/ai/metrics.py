"""Prometheus metrics for AI gateway observability."""

from prometheus_client import Counter, Gauge, Histogram

AI_REQUESTS_TOTAL = Counter(
    "saas_ai_requests_total",
    "Total AI completion requests",
    ["provider", "model", "status", "key_source"],
)

AI_TOKENS_TOTAL = Counter(
    "saas_ai_tokens_total",
    "Total tokens consumed by AI requests",
    ["provider", "model", "token_type"],  # token_type: prompt, completion
)

AI_BILLED_USD_TOTAL = Counter(
    "saas_ai_billed_usd_total",
    "Total billed USD (with margin applied)",
    ["provider", "model", "key_source"],
)

AI_LATENCY_SECONDS = Histogram(
    "saas_ai_latency_seconds",
    "AI request latency in seconds",
    ["provider", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

AI_COST_USD_TOTAL = Counter(
    "saas_ai_cost_usd_total",
    "Total raw provider cost in USD",
    ["provider", "model"],
)

AI_WALLET_BALANCE = Gauge(
    "saas_ai_wallet_balance_usd",
    "Current wallet balance in USD",
    ["tenant_id"],
)

AI_STREAM_CHUNKS_TOTAL = Counter(
    "saas_ai_stream_chunks_total",
    "Total SSE chunks sent for streaming responses",
    ["provider", "model"],
)

AI_FALLBACK_TOTAL = Counter(
    "saas_ai_fallback_total",
    "Total times a fallback model was used",
    ["primary_model", "fallback_model", "reason"],
)

# ── Embedding Gateway Metrics ────────────────────────────────

EMBEDDING_REQUESTS_TOTAL = Counter(
    "saas_embedding_requests_total",
    "Total embedding generation requests",
    ["provider", "model", "status"],
)

EMBEDDING_TOKENS_TOTAL = Counter(
    "saas_embedding_tokens_total",
    "Total tokens consumed by embedding requests",
    ["provider", "model"],
)

EMBEDDING_LATENCY_SECONDS = Histogram(
    "saas_embedding_latency_seconds",
    "Embedding generation latency in seconds",
    ["provider", "model"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

EMBEDDING_CACHE_HITS_TOTAL = Counter(
    "saas_embedding_cache_hits_total",
    "Embedding cache hits",
    ["model"],
)

EMBEDDING_CACHE_MISSES_TOTAL = Counter(
    "saas_embedding_cache_misses_total",
    "Embedding cache misses",
    ["model"],
)

# ── RAG Pipeline Metrics ─────────────────────────────────────

RAG_RETRIEVAL_TOTAL = Counter(
    "saas_rag_retrieval_total",
    "Total RAG retrieval queries",
    ["search_type"],  # vector, text, hybrid
)

RAG_RETRIEVAL_LATENCY_SECONDS = Histogram(
    "saas_rag_retrieval_latency_seconds",
    "RAG retrieval latency in seconds",
    ["search_type"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

RAG_RETRIEVAL_EMPTY_TOTAL = Counter(
    "saas_rag_retrieval_empty_total",
    "RAG retrieval queries that returned zero results",
    ["search_type"],
)

RAG_TOP_SCORE = Histogram(
    "saas_rag_top_score",
    "Similarity score of the top retrieval result",
    ["search_type"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99],
)

RAG_CHUNKS_PER_QUERY = Histogram(
    "saas_rag_chunks_per_query",
    "Number of chunks returned per RAG query",
    ["search_type"],
    buckets=[1, 2, 3, 5, 10, 20, 50],
)

RAG_RERANK_LATENCY_SECONDS = Histogram(
    "saas_rag_rerank_latency_seconds",
    "Re-ranking latency in seconds",
    ["provider"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

# ── RAG Evaluation Metrics ──────────────────────────────────

RAG_EVAL_PRECISION = Gauge(
    "saas_rag_eval_precision_at_k",
    "Precision@k from latest evaluation run",
    ["dataset"],
)

RAG_EVAL_RECALL = Gauge(
    "saas_rag_eval_recall_at_k",
    "Recall@k from latest evaluation run",
    ["dataset"],
)

RAG_EVAL_MRR = Gauge(
    "saas_rag_eval_mrr",
    "Mean Reciprocal Rank from latest evaluation run",
    ["dataset"],
)

RAG_EVAL_NDCG = Gauge(
    "saas_rag_eval_ndcg_at_k",
    "NDCG@k from latest evaluation run",
    ["dataset"],
)

RAG_EVAL_FAITHFULNESS = Gauge(
    "saas_rag_eval_faithfulness",
    "Average faithfulness score from LLM judge",
    ["dataset"],
)

RAG_EVAL_ANSWER_RELEVANCY = Gauge(
    "saas_rag_eval_answer_relevancy",
    "Average answer relevancy score from LLM judge",
    ["dataset"],
)

RAG_QUERY_EMPTY_RATE = Gauge(
    "saas_rag_query_empty_rate",
    "Rolling empty-result rate (updated by periodic task)",
)

RAG_CACHE_HIT_RATE = Gauge(
    "saas_rag_cache_hit_rate",
    "Semantic cache hit rate (rolling window)",
)

RAG_STORAGE_VECTORS_TOTAL = Gauge(
    "saas_rag_storage_vectors_total",
    "Total vector count per tenant",
    ["tenant_id"],
)
