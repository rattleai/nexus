# AI Agent Security & Data Protection — Implementation Plan

## Context

The nxs infrastructure is an application-agnostic, agent-first, AI-first, API-first platform built with Python/FastAPI, PostgreSQL (with RLS), Redis, and Celery. It already has strong security fundamentals: parameterized ORM queries, RLS tenant isolation, AES-256-GCM encryption, JWT+API key auth, OWASP guardrails, agent governance with spending limits, and subprocess sandboxing.

However, to achieve **production-grade, best-in-class** status for autonomous AI agents, gaps exist in: multi-layered prompt injection defense, database interaction hardening for agent-generated queries, advanced sandboxing, real-time threat detection, agent communication integrity, supply chain verification, and compliance automation. This plan addresses those gaps based on OWASP Top 10 for LLM (2025), NIST AI RMF, MITRE ATLAS, Google SAIF 2.0, and EU AI Act requirements.

---

## Phase 0 (P0) — Critical: Database & Prompt Injection Hardening

### 0.1 Database Access Gateway for Agents
**Problem:** Agents with `code_execute` or custom tools could potentially construct queries that exfiltrate data, flood the DB, or bypass tenant isolation.
**Files:** New `app/agents/db_gateway.py`, modify `app/agents/tool_registry.py`

- Create `AgentDatabaseGateway` class that mediates ALL agent database interactions
- **Query allowlisting**: Define permitted query patterns per agent (SELECT-only by default, specific tables only)
- **Row limit enforcement**: Hard cap on result rows returned to agents (default 1000, configurable per-agent)
- **Query complexity analysis**: Reject queries with excessive JOINs (>3), subqueries (>2), or no WHERE clause on large tables
- **Statement timeout per-agent**: `SET LOCAL statement_timeout = '{agent_timeout_ms}'` before each agent query (separate from global 30s)
- **Connection isolation**: Agents get read-only database sessions from the read replica by default; write access requires explicit governance approval
- **Query logging**: Every agent-executed query logged to audit with tenant_id, agent_id, query hash, row count, duration
- Integrate with existing `app/db/session.py` RLS context and `app/agents/governance.py` policy checks

### 0.2 Multi-Layered Prompt Injection Defense
**Problem:** Current regex-based detection (`app/ai/guardrails.py`) catches known patterns but is trivially bypassed via encoding, multilingual attacks, or novel phrasing.
**Files:** New `app/ai/prompt_firewall.py`, modify `app/ai/guardrails.py`, `app/agents/runtime.py`

- **Layer 1 — Structural validation** (existing, enhanced): Extend `_BLOCKED_INPUT_PATTERNS` with Unicode normalization (NFKC) before matching, base64/URL-encoding detection and decode-then-scan, and multilingual injection patterns
- **Layer 2 — Instruction hierarchy**: Implement message privilege levels in runtime. System prompts get `[SYSTEM]` markers. User inputs are wrapped with delimiter tokens that the LLM is instructed to treat as untrusted. Tool outputs wrapped with `[TOOL_OUTPUT]` delimiters
- **Layer 3 — Canary token injection**: Insert unique per-request canary strings into system prompts. If any canary appears in agent output, flag as prompt leak (OWASP LLM07). Integrate with existing `_SYSTEM_PROMPT_LEAK_PATTERNS`
- **Layer 4 — LLM-based classifier** (optional, configurable): Lightweight classifier call (haiku-class model) to score input suspicion before main agent execution. Only for high-security agents (configurable via `governance_policy.prompt_firewall_level: "strict"`)
- **Layer 5 — Output firewall**: Scan agent outputs for instruction-like content targeting downstream agents. Extend `app/agents/validation.py` `OutputValidator` with cross-agent injection detection patterns
- All layers fail-open by default (log only) with per-tenant override to fail-closed

### 0.3 Database Flooding Protection
**Problem:** An agent could issue rapid queries, large result sets, or long-running transactions that exhaust the connection pool.
**Files:** Modify `app/agents/governance.py`, `app/db/session.py`

- **Per-agent query rate limiting**: Redis-based counter (reuse existing Lua atomic pattern) — max queries per minute per agent instance
- **Connection pool partitioning**: Reserve a portion of the pool for non-agent requests (e.g., 60% general / 40% agent max). Implement via `AsyncSession` wrapper that checks agent session count before checkout
- **Result size limits**: Middleware that counts bytes streamed from DB to agent and terminates if threshold exceeded (default 5MB per query, 50MB per agent run)
- **Idle transaction detection**: Agent sessions auto-rolled-back after 10s idle (tighter than global 60s)
- Add new governance policy fields: `max_queries_per_minute`, `max_result_bytes_per_query`, `max_total_db_bytes_per_run`

---

## Phase 1 (P1) — High Priority: Agent Security Hardening

### 1.1 Capability-Based Agent Privilege System
**Problem:** Current tool allowlists are binary (allowed/denied). No support for attenuated capabilities when agents delegate to sub-agents.
**Files:** New `app/agents/capabilities.py`, modify `app/agents/executor.py`, `app/agents/orchestrator.py`

- **Capability tokens**: Signed, scoped, time-limited tokens that encode what an agent instance can do (tools, data access, spending)
- **Capability attenuation**: When agent A spawns sub-agent B via orchestrator, B's capabilities are automatically a subset of A's (monotonic reduction)
- **Dynamic privilege escalation**: Agent can request elevated capabilities via approval workflow (reuse existing `governance.py` approval system)
- **Confused deputy prevention**: Every tool invocation carries the capability token; tool_registry verifies the token before execution
- Integrate with existing `RequireScopes` pattern but at the agent-instance level

### 1.2 Container-Based Sandbox Upgrade
**Problem:** Current subprocess sandbox (`app/agents/sandbox.py`) relies on rlimits which can be bypassed on some kernels. No network policy enforcement.
**Files:** Modify `app/agents/sandbox.py`, new `app/agents/sandbox_container.py`

- **nsjail integration** (Linux namespaces): Replace subprocess with nsjail for production deployments
  - PID namespace isolation (agent can't see host processes)
  - Mount namespace (read-only root, tmpfs for scratch)
  - Network namespace (no network by default, opt-in with egress allowlist)
  - cgroup v2 resource limits (memory, CPU, I/O)
  - seccomp-bpf syscall filtering
- **Fallback chain**: nsjail (production) -> subprocess+rlimits (development) -> reject (if AGENT_SANDBOX_STRICT=true)
- **Resource accounting**: Track actual CPU/memory per execution via cgroup stats, feed into governance spending
- Keep existing `SandboxConfig`/`SandboxResult` interfaces unchanged for backward compatibility
- Add `AGENT_SANDBOX_BACKEND` config: `"nsjail"` | `"subprocess"` | `"auto"`

### 1.3 Agent-to-Agent Communication Security
**Problem:** A2A messages (`app/agents/a2a.py`) are not signed or encrypted. A compromised agent could forge messages.
**Files:** Modify `app/agents/a2a.py`, new `app/agents/a2a_security.py`

- **Message signing**: HMAC-SHA256 signature per message using a per-instance ephemeral key derived from the instance's capability token
- **Message integrity**: Include `message_hash` field; recipients verify before processing
- **Replay protection**: Monotonic sequence numbers per sender + recipient pair; reject out-of-order or duplicate messages
- **Encrypted channels** (optional): For sensitive inter-agent data, AES-256-GCM envelope encryption using recipient's public capability
- **Cross-agent injection defense**: Validate message content through prompt firewall (Layer 5 from 0.2) before injecting into recipient's context

### 1.4 Tool Supply Chain Verification
**Problem:** Tenant-registered external tools (`TenantTool`) are invoked at runtime with no integrity verification beyond SSRF checks.
**Files:** Modify `app/agents/tool_registry.py`, `app/agents/models.py`

- **Tool signature verification**: Require external tools to provide an HMAC signature of their response. Platform stores a shared secret per tool (encrypted in DB)
- **Schema drift detection**: Hash tool's input/output schema at registration time; re-verify at each invocation. Alert on unexpected changes
- **Behavioral monitoring**: Track tool response patterns (latency, size, error rates) per tenant. Flag anomalies (sudden latency spike = possible supply chain compromise)
- **Tool trust levels**: `verified` (platform-reviewed), `trusted` (tenant-approved), `untrusted` (new). Higher trust = fewer governance checks
- Add `tool_signature_secret` (encrypted) and `schema_hash` fields to `TenantTool` model

---

## Phase 2 (P2) — Medium Priority: Detection, Compliance, & Resilience

### 2.1 Real-Time Threat Detection Engine
**Files:** New `app/agents/threat_detection.py`, modify `app/agents/runtime.py`

- **Behavioral baselines**: Per-agent-definition statistical profiles (avg steps, avg tokens, avg tool calls, typical tools used). Stored in Redis, updated after each run
- **Anomaly scoring**: Real-time comparison of current run against baseline. Score factors: unusual tool usage, excessive steps, cost outliers, rapid A2A messaging
- **Alert thresholds**: Configurable per-agent. Default: warn at 2-sigma, suspend at 3-sigma
- **Automated response**: On high anomaly score: pause agent (set status=PAUSED), emit `AgentThreatDetected` event, notify via webhook/notification
- **Integration**: Hook into existing `AgentStepCompleted` event handler for real-time scoring
- **MITRE ATLAS mapping**: Map detected anomalies to ATLAS technique IDs for security team context

### 2.2 Data Classification & DLP
**Files:** New `app/agents/data_classification.py`, modify `app/agents/validation.py`, `app/ai/guardrails.py`

- **Data classification engine**: Classify data flowing through agents as PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED
- **Classification sources**: Column-level DB metadata, tenant-configured patterns, PII detection results
- **DLP enforcement**: Agents with `max_data_classification: "INTERNAL"` cannot access or output CONFIDENTIAL/RESTRICTED data
- **Consent-aware access**: Integrate with existing `Consent` model — agents must verify consent before processing personal data
- **Automatic redaction**: Extend `OutputValidator.sanitize()` to redact based on classification level, not just PII patterns
- **GDPR/EU AI Act alignment**: Data subject access requests automatically include agent-processed data in scope

### 2.3 Compliance & Policy-as-Code Framework
**Files:** New `app/agents/compliance.py`, modify `app/agents/governance.py`

- **Policy-as-code**: Define governance policies as versioned, auditable JSON/YAML documents with schema validation
- **Automated compliance checks**: Pre-execution scan of agent configuration against policy requirements
- **Compliance reporting**: Generate per-tenant compliance reports covering: OWASP LLM Top 10 coverage, NIST AI RMF alignment, EU AI Act Article 9 (risk management), Article 13 (transparency)
- **Regulatory audit trail**: Extend `AuditLog` with compliance-specific fields: `regulation`, `article`, `compliance_status`
- **Model cards**: Auto-generate model/agent cards documenting capabilities, limitations, training data, and risk assessments (EU AI Act Article 13 transparency)

### 2.4 Graceful Degradation & Anti-Abuse
**Files:** Modify `app/agents/executor.py`, `app/agents/governance.py`, `app/api/rate_limit.py`

- **Token abuse detection**: Flag agents that consistently hit spending limits, repeatedly trigger governance violations, or exhibit retry storms
- **Progressive throttling**: Instead of hard-blocking at rate limits, progressively slow agent execution (exponential backoff on tool calls)
- **Tenant-level circuit breaker**: If a tenant's agents collectively exceed cost/error thresholds, pause all tenant agent execution
- **Resource reservation**: Ensure critical platform operations (health checks, billing webhooks) are never starved by agent load
- **Dead letter handling**: Failed agent runs that exhaust retries get queued for manual review rather than silently dropped

---

## Key Files Reference

| Area | Existing Files | New Files |
|------|---------------|-----------|
| DB Gateway | `app/db/session.py`, `app/agents/tool_registry.py` | `app/agents/db_gateway.py` |
| Prompt Firewall | `app/ai/guardrails.py`, `app/agents/validation.py` | `app/ai/prompt_firewall.py` |
| Capabilities | `app/agents/executor.py`, `app/agents/governance.py` | `app/agents/capabilities.py` |
| Sandbox | `app/agents/sandbox.py` | `app/agents/sandbox_container.py` |
| A2A Security | `app/agents/a2a.py` | `app/agents/a2a_security.py` |
| Threat Detection | `app/agents/runtime.py`, `app/core/events.py` | `app/agents/threat_detection.py` |
| Data Classification | `app/agents/validation.py`, `app/ai/guardrails.py` | `app/agents/data_classification.py` |
| Compliance | `app/agents/governance.py`, `app/core/audit.py` | `app/agents/compliance.py` |

## Reusable Existing Patterns

- **Atomic Redis operations**: Lua scripts in `app/agents/governance.py` (lines 54-79) — reuse for query rate limits, anomaly counters
- **Circuit breaker**: `app/core/circuit_breaker.py` — reuse for tenant-level agent circuit breaker
- **Event system**: `app/core/events.py` + `app/agents/events.py` — extend with new security events
- **Encryption**: `app/core/encryption.py` AES-256-GCM — reuse for A2A message encryption, tool secret storage
- **Approval workflow**: `governance.py` lines 374-538 — reuse for capability escalation requests
- **SSRF validation**: `app/core/url_validation.py` — already used in tool_registry, extend for new endpoints
- **Output validation**: `app/agents/validation.py` OutputValidator — extend, don't replace
- **Audit logging**: `app/core/audit.py` — extend with compliance fields

## Configuration Additions (`app/config.py`)

```python
# Phase 0 — DB Gateway
AGENT_DB_MAX_QUERIES_PER_MINUTE: int = 60
AGENT_DB_MAX_RESULT_ROWS: int = 1000
AGENT_DB_MAX_RESULT_BYTES: int = 5_242_880  # 5 MB
AGENT_DB_MAX_JOINS: int = 3
AGENT_DB_STATEMENT_TIMEOUT_MS: int = 10_000
AGENT_DB_POOL_PARTITION_PCT: int = 40  # % of pool reserved for agents

# Phase 0 — Prompt Firewall
PROMPT_FIREWALL_ENABLED: bool = True
PROMPT_FIREWALL_CLASSIFIER_ENABLED: bool = False  # LLM classifier (costs tokens)
PROMPT_FIREWALL_CLASSIFIER_MODEL: str = "claude-haiku-4-5-20251001"
PROMPT_FIREWALL_CANARY_ENABLED: bool = True
PROMPT_FIREWALL_FAIL_MODE: str = "log"  # "log" or "block"

# Phase 1 — Sandbox
AGENT_SANDBOX_BACKEND: str = "auto"  # "nsjail", "subprocess", "auto"
AGENT_SANDBOX_STRICT: bool = False  # Reject if nsjail unavailable

# Phase 1 — A2A Security
AGENT_A2A_SIGNING_ENABLED: bool = True
AGENT_A2A_ENCRYPTION_ENABLED: bool = False

# Phase 1 — Tool Verification
AGENT_TOOL_SCHEMA_VERIFICATION: bool = True
AGENT_TOOL_BEHAVIORAL_MONITORING: bool = True

# Phase 2 — Threat Detection
AGENT_THREAT_DETECTION_ENABLED: bool = True
AGENT_THREAT_ANOMALY_WARN_SIGMA: float = 2.0
AGENT_THREAT_ANOMALY_SUSPEND_SIGMA: float = 3.0

# Phase 2 — Data Classification
DATA_CLASSIFICATION_ENABLED: bool = False
DATA_CLASSIFICATION_DEFAULT_LEVEL: str = "INTERNAL"
```

## Database Migrations

1. **Migration: agent_db_gateway** — Add `db_access_policy` JSONB to `AgentDefinition` (query patterns, allowed tables, row limits)
2. **Migration: tool_verification** — Add `schema_hash`, `tool_signature_secret_encrypted`, `trust_level` to `TenantTool`
3. **Migration: threat_baselines** — Add `behavioral_baseline` JSONB to `AgentDefinition` (auto-populated)
4. **Migration: compliance_audit** — Add `regulation`, `article`, `compliance_status` to `AuditLog`
5. **Migration: data_classification** — Add `data_classification_level` to relevant data models
6. **Migration: capability_tokens** — Add `capability_token_hash`, `capability_scope` JSONB to `AgentInstance`

## Verification Plan

### Unit Tests
- `tests/agents/test_db_gateway.py` — Query allowlisting, row limits, complexity rejection, statement timeout
- `tests/ai/test_prompt_firewall.py` — Unicode normalization bypass, base64 encoding, canary detection, instruction hierarchy
- `tests/agents/test_capabilities.py` — Capability attenuation, token verification, escalation workflow
- `tests/agents/test_a2a_security.py` — Message signing, replay rejection, encrypted channels
- `tests/agents/test_threat_detection.py` — Anomaly scoring, baseline updates, automated pause
- `tests/agents/test_sandbox_container.py` — nsjail integration, fallback chain, resource accounting

### Integration Tests
- End-to-end agent run with DB gateway enforcement (query blocked, query allowed, row limit hit)
- Prompt injection attempt blocked at each firewall layer
- Multi-agent orchestration with capability attenuation
- Tool invocation with schema verification failure
- Threat detection triggering agent suspension

### Security Tests
- SQL injection via agent tool arguments → blocked by DB gateway
- Prompt injection via tool output (indirect injection) → blocked by output firewall
- Confused deputy attack via forged A2A message → blocked by message signing
- Data exfiltration via agent output → blocked by DLP
- Resource exhaustion via rapid agent spawning → blocked by flooding protection

## Implementation Order

```
Week 1-2: Phase 0.1 (DB Gateway) + 0.3 (Flooding Protection)
Week 2-3: Phase 0.2 (Prompt Firewall — Layers 1-3, 5)
Week 3-4: Phase 1.1 (Capabilities) + 1.4 (Tool Verification)
Week 4-5: Phase 1.2 (Container Sandbox) + 1.3 (A2A Security)
Week 5-6: Phase 0.2 Layer 4 (LLM Classifier) + 2.1 (Threat Detection)
Week 6-7: Phase 2.2 (Data Classification) + 2.4 (Anti-Abuse)
Week 7-8: Phase 2.3 (Compliance Framework) + Final integration testing
```
