"""Agent execution layer — application-agnostic infrastructure for AI agents.

Provides:
- Agent definitions and instance lifecycle management
- Sandboxed code execution (subprocess + seccomp)
- Short-term (Redis) and long-term (PostgreSQL + pgvector) memory
- Multi-agent orchestration (supervisor, pipeline, fan-out)
- Agent-to-agent communication
- Governance, policies, and spending controls
- Dynamic tool registry
"""
