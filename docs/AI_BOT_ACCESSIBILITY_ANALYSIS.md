# AI Bot Accessibility: Research & Architecture Recommendation

**Date**: March 8, 2026
**Status**: Research Complete — Ready for Decision

---

## Executive Summary

This document analyzes whether the existing FastAPI REST API is sufficient for AI bot accessibility (manus.ai, OpenClaw, etc.) or whether a CLI command infrastructure is needed. After deep codebase analysis and state-of-the-art research, the recommendation is:

**Build all three layers, in this priority order:**

1. **MCP Server** (highest leverage — industry standard adopted by OpenAI, Google, Microsoft, Anthropic)
2. **Enhance the existing REST API** to be AI-agent-friendly (structured errors, rich OpenAPI descriptions)
3. **CLI with `--output json`** (lowest token cost for shell-capable agents like Claude Code, Gemini CLI)

The existing FastAPI REST API is a strong foundation (~60 endpoints, versioned, cursor-paginated) but is **not sufficient alone**. Modern AI agents overwhelmingly prefer MCP as their primary integration protocol.

---

## Table of Contents

1. [Current Platform Assessment](#1-current-platform-assessment)
2. [How AI Bots Actually Interact with Platforms](#2-how-ai-bots-actually-interact-with-platforms)
3. [MCP — The De Facto Standard](#3-mcp--the-de-facto-standard)
4. [REST API vs CLI vs MCP — The Tradeoffs](#4-rest-api-vs-cli-vs-mcp--the-tradeoffs)
5. [Best-in-Class Examples](#5-best-in-class-examples)
6. [What Makes an API AI-Agent Friendly](#6-what-makes-an-api-ai-agent-friendly)
7. [Authentication for AI Bots](#7-authentication-for-ai-bots)
8. [Emerging Standards](#8-emerging-standards)
9. [Recommended Architecture](#9-recommended-architecture)
10. [Implementation Roadmap](#10-implementation-roadmap)

---

## 1. Current Platform Assessment

### Existing API Surface

The platform already has a mature, production-grade REST API:

| Dimension | Current State | Bot-Readiness |
|-----------|---------------|---------------|
| **Endpoints** | ~60 across 14 routers | Good coverage |
| **Versioning** | `/api/v1` prefix | Ready |
| **Pagination** | Cursor-based | Excellent for bots |
| **Auth** | API Key (HMAC-SHA256), JWT (RS256), OAuth | Needs OAuth 2.1 for agents |
| **Streaming** | SSE for AI completions | Good |
| **Batch API** | Up to 10 sub-requests | Good for mobile agents |
| **Error Responses** | Consistent schema | Needs enrichment for agents |
| **OpenAPI Spec** | Auto-generated (FastAPI) | Needs richer descriptions |
| **Rate Limiting** | Token bucket per endpoint/key | Needs agent-aware tuning |
| **Webhooks** | HMAC-SHA256 signed, retry logic | Good for async workflows |

### Key API Domains Available

- **Authentication**: Login, register, OAuth, WebAuthn, token refresh
- **Teams & Users**: CRUD, invitations, roles
- **AI Gateway**: Multi-provider completions (OpenAI, Anthropic, Mistral, etc.), streaming, BYOK
- **Jobs**: Async job submission, status tracking
- **Billing**: Plans, wallets, transactions
- **Notifications**: Push subscriptions, preferences
- **Webhooks**: Event subscriptions, delivery management
- **Export**: GDPR-compliant data export
- **Admin**: Audit logs, tenant management

### Gaps for Bot Accessibility

1. **No MCP server** — bots must manually integrate REST endpoints
2. **No CLI tool** — shell-capable agents have no command-line interface
3. **OpenAPI descriptions lack semantic richness** — agents need "why" not just "what"
4. **Error responses lack agent-friendly hints** — no `error_code` enum, no `hint` field
5. **No agent-specific auth flow** — OAuth 2.1 Client Credentials not implemented
6. **No idempotency keys** on mutating endpoints — agents retry and cause duplicates
7. **No agent rate-limit tier** — agents burst differently than humans

---

## 2. How AI Bots Actually Interact with Platforms

### Manus.ai

Manus uses a three-layer architecture (planning, execution, validation) with specialized sub-agents:

- **Primary**: MCP connectors (prebuilt for Gmail, Notion, Stripe, Slack, GitHub, etc.)
- **Secondary**: Direct API calls via Python in sandboxed Linux VMs
- **Tertiary**: Shell commands and CLI tools
- **Fallback**: Browser automation (when no API/MCP exists)
- **Long tail**: Zapier integration for SaaS apps without direct connectors

**Key insight**: Manus strongly prefers structured APIs and MCP. It only falls back to browser automation when nothing else exists. **If you provide an MCP server, Manus will use it.**

### OpenClaw

OpenClaw is an open-source agent using messaging platforms (WhatsApp, Telegram, Discord) as its UI:

- **Primary**: "Skills" — modular Python/Bash/TypeScript scripts (5,700+ on ClawHub)
- **Secondary**: MCP integration via community adapters
- **Tertiary**: Direct shell access and API calls
- **Architecture**: Gateway on `127.0.0.1:18789` routing messages to agent sessions

**Key insight**: OpenClaw's skills system is essentially a CLI-like interface. A CLI with `--output json` would integrate naturally.

### Claude Code / Gemini CLI / Cursor

These developer-focused agents operate with direct shell access:

- **Primary**: CLI tools via bash (`gh`, `docker`, `npm`, `stripe`)
- **Secondary**: MCP servers (discovered dynamically)
- **Tertiary**: REST API calls via `curl` or language SDKs

**Key insight**: These agents prefer CLI for simple operations (lower token cost) and MCP for complex multi-step workflows.

---

## 3. MCP — The De Facto Standard

### What is MCP?

Model Context Protocol (MCP) is Anthropic's open standard (November 2024) for connecting AI models to external tools and data sources. It uses JSON-RPC 2.0 over stdio or HTTP.

### Adoption (as of March 2026)

| Milestone | Details |
|-----------|---------|
| **SDK Downloads** | 97M+ monthly (Python + TypeScript) |
| **MCP Servers** | 5,800+ in ecosystem |
| **MCP Clients** | 300+ |
| **Governance** | Linux Foundation Agentic AI Foundation (AAIF) |
| **Founders** | Anthropic, OpenAI, Block |
| **Members** | Google, Microsoft, AWS, Cloudflare |
| **OpenAI adoption** | March 2025 |
| **Google adoption** | April 2025 |
| **Microsoft adoption** | Build 2025 |

### MCP Architecture

```
┌─────────────────┐     JSON-RPC 2.0      ┌─────────────────┐
│   AI Agent       │ ◄──────────────────► │  MCP Server      │
│ (Manus, Claude,  │     (stdio or HTTP)   │  (Your Platform) │
│  OpenClaw, etc.) │                       │                  │
│                  │   Discovers:          │  Exposes:        │
│  - Plans tasks   │   - Tools            │  - Tools         │
│  - Selects tools │   - Resources        │  - Resources     │
│  - Chains calls  │   - Prompts          │  - Prompts       │
└─────────────────┘                       └─────────────────┘
```

**Tools**: Functions the agent can call (e.g., `create_job`, `list_teams`, `query_ai`)
**Resources**: Data the agent can read (e.g., `user://profile`, `billing://usage`)
**Prompts**: Pre-built prompt templates for common workflows

### Why MCP Wins

1. **Universal compatibility**: Works with every major AI agent framework
2. **Dynamic discovery**: Agents discover available tools at runtime
3. **Stateful sessions**: Maintains context across multiple calls
4. **Governance**: Linux Foundation stewardship ensures longevity
5. **OAuth integration**: Built-in support for OAuth 2.1 auth flows
6. **Ecosystem**: 5,800+ servers means agents already understand the protocol

---

## 4. REST API vs CLI vs MCP — The Tradeoffs

### Direct Comparison

| Dimension | REST API | CLI | MCP |
|-----------|----------|-----|-----|
| **Token cost** | Medium (JSON schemas in context) | Low (bash + stdout) | High (tool definitions permanent in context) |
| **Discoverability** | OpenAPI spec (pre-loaded) | `--help` flags (on-demand) | Dynamic tool discovery |
| **Statefulness** | Stateless (per-request) | Stateless (per-command) | Stateful sessions |
| **Auth complexity** | Bearer tokens, API keys | Stored credentials | OAuth 2.1 built-in |
| **Agent preference** | Fallback | Shell-capable agents | Primary for modern agents |
| **Setup effort** | Already exists | New development | New development |
| **Multi-agent** | Manual orchestration | N/A | Protocol-level composition |
| **Enterprise governance** | Custom | Custom | Built-in audit/scoping |
| **Streaming** | SSE/WebSocket | stdout | Built-in |

### Token Cost Analysis

One developer reported **40% token reduction** switching from MCP to CLI for simple operations. This is because:

- **MCP**: Tool definitions (JSON schemas + descriptions) are loaded into context **permanently**, consuming tokens even when not used
- **CLI**: A bash command and its stdout only consume tokens **when actually invoked**
- **REST API**: Falls between — schema definitions can be large but are typically pre-loaded once

### Practical Reality

Most agent frameworks use **all three**. The best approach is:

```
Agent Decision Tree:
├── Complex multi-step workflow? → MCP (stateful, discoverable)
├── Simple CRUD operation? → CLI (low token cost)
├── No MCP/CLI available? → REST API (universal fallback)
└── No API at all? → Browser automation (last resort)
```

**Recommendation**: Offer all three and let agent frameworks choose. This is what GitHub, Stripe, and other best-in-class platforms do.

---

## 5. Best-in-Class Examples

### GitHub (Gold Standard)

GitHub offers **all three channels** for AI bot accessibility:

| Channel | Implementation |
|---------|---------------|
| **MCP Server** | 100+ tools, Go-based, supports remote hosting or local Docker/binary. OAuth scopes, read-only modes, dynamic tool discovery |
| **CLI** | `gh` command with `--json` output. Noun-verb pattern: `gh pr create`, `gh issue list` |
| **REST/GraphQL API** | Comprehensive REST + GraphQL with rich documentation |
| **Agent HQ** | Unified platform (Universe 2025) for orchestrating any AI agent within GitHub/VS Code |

### Stripe (Best MCP Implementation)

| Channel | Implementation |
|---------|---------------|
| **Remote MCP** | `mcp.stripe.com` with OAuth authentication |
| **Local MCP** | `npx @stripe/mcp` for development |
| **Agent Toolkit** | SDKs for OpenAI Agent SDK, LangChain, CrewAI, Vercel AI SDK |
| **REST API** | Industry-leading API documentation with semantic descriptions |
| **Agentic Commerce Protocol** | Co-maintained with OpenAI for AI purchasing flows |

Stripe published benchmarks: Claude Opus 4.5 scored **92%** on full-stack Stripe API integration tasks.

### Other Notable Implementations

- **Cloudflare**: Official MCP server for Workers, D1, R2, KV
- **Supabase**: MCP server for database operations
- **Sentry**: MCP server for error tracking
- **Expo**: MCP server for React Native tooling
- **Zapier**: MCP server exposing 7,000+ SaaS app actions

---

## 6. What Makes an API AI-Agent Friendly

### Required Qualities

1. **Self-describing via OpenAPI/JSON Schema**
   - Rich `description` fields explaining **why**, not just what
   - Parameter constraints, examples, default values
   - Response schema with all possible shapes documented

2. **Structured, predictable error responses**
   ```json
   {
     "error": {
       "type": "validation_error",
       "code": "INVALID_PARAMETER",
       "message": "The 'model' parameter must be one of: gpt-4, claude-3",
       "hint": "Use GET /ai/models to list available models",
       "param": "model",
       "request_id": "req_abc123"
     }
   }
   ```

3. **Idempotency keys on mutating endpoints**
   - Agents retry aggressively. Without idempotency keys, retries create duplicates
   - Pattern: `Idempotency-Key: <client-generated-uuid>` header

4. **Consistent naming conventions**
   - camelCase for JSON properties
   - Plural nouns for collection resources
   - Standard HTTP verbs (GET=read, POST=create, PUT=replace, PATCH=update, DELETE=remove)

5. **Stable API contracts**
   - Breaking changes break all agent automation
   - Semantic versioning with deprecation notices
   - Never remove fields; only add new ones

6. **Semantic metadata**
   - JSON-LD and schema.org vocabularies help agents interpret data across systems
   - `@context` fields enable cross-platform understanding

### Agent-Specific Enhancements

| Enhancement | Why |
|-------------|-----|
| **`Retry-After` header** | Agents respect this; humans don't |
| **`X-RateLimit-Remaining` header** | Agents can throttle proactively |
| **`Link` header for pagination** | Standard pagination discovery |
| **`Prefer: return=representation`** | Agents need response after mutation |
| **Webhook event catalog** | Agents need to know what events exist |
| **Bulk/batch endpoints** | Agents process in bulk efficiently |

---

## 7. Authentication for AI Bots

### Industry Convergence: OAuth 2.1

The industry has converged on OAuth 2.1 for AI agent authentication:

| Flow | Use Case | Status in Platform |
|------|----------|-------------------|
| **Authorization Code + PKCE** | User-delegated access (agent acts on behalf of user) | Partially implemented (OAuth login exists) |
| **Client Credentials** | Machine-to-machine / service account access | Not implemented |
| **Device Authorization** | Headless agents (no browser) | Not implemented |

### Recommended Auth Architecture for Bots

```
┌─────────────┐     Client Credentials      ┌─────────────┐
│  AI Bot      │ ────────────────────────► │  OAuth 2.1    │
│  (Manus,     │     (client_id +           │  Token Server │
│   OpenClaw)  │      client_secret)        │               │
│              │ ◄────────────────────────  │  Issues:      │
│              │     access_token           │  - Scoped     │
│              │     (short-lived,          │  - Audience-  │
│              │      scoped,              │    bound      │
│              │      audience-bound)      │  - Short-lived│
└─────────────┘                            └─────────────┘
```

### Key Principles

1. **Short-lived tokens** (minutes to hours) with automated rotation
2. **Scoped access** — bots get only the permissions they need
3. **Audience-bound tokens** (`aud` claim) prevent token reuse across services
4. **Human-in-the-loop** approval for high-risk actions (delete team, billing changes)
5. **Separate bot identity** — bots should have their own identity, not impersonate users
6. **Audit trail** — all bot actions logged with bot identity, not user identity

### Current Platform Gaps

- API keys are HMAC-SHA256 hashed with scopes — **good foundation but static keys are a risk**
- No Client Credentials flow for machine-to-machine auth
- No Device Authorization flow for headless agents
- No bot-specific identity model (bots currently use user API keys)

---

## 8. Emerging Standards

Three protocols are forming the AI agent interoperability stack for 2026:

| Protocol | Purpose | Transport | Governance | Relevance |
|----------|---------|-----------|------------|-----------|
| **MCP** | Agent-to-tool (vertical) | JSON-RPC 2.0 | Linux Foundation AAIF | **Critical** — must implement |
| **A2A** | Agent-to-agent (horizontal) | HTTP, SSE, JSON-RPC | Google + 50 partners | **Watch** — implement if multi-agent workflows needed |
| **ACP** | Agent commerce / purchasing | REST | OpenAI + Stripe | **Relevant** — if billing/commerce features exposed to agents |

### Google A2A (Agent2Agent Protocol)

- Enables agents from different vendors to collaborate
- Uses "Agent Cards" for capability discovery (similar to robots.txt for agents)
- Launched with Atlassian, Salesforce, SAP, ServiceNow, PayPal, and 50+ others
- Relevant if your platform needs to participate in multi-agent workflows

### NIST AI Agent Standards Initiative

- Federal initiative (February 2026) for interoperable, secure AI agent adoption
- Focus on security, identity, and audit requirements
- Will likely influence enterprise compliance requirements

### Market Projection

Gartner projects **40% of enterprise applications** will embed AI agents by end of 2026 (up from <5% in 2025).

---

## 9. Recommended Architecture

### Three-Layer Bot Accessibility Stack

```
                        ┌──────────────────────────────────────┐
                        │          AI Bot Clients               │
                        │  (Manus, OpenClaw, Claude Code, etc.) │
                        └──────┬──────────┬──────────┬─────────┘
                               │          │          │
                    ┌──────────▼──┐  ┌────▼────┐  ┌─▼──────────┐
                    │  MCP Server  │  │   CLI   │  │  REST API  │
                    │  (Primary)   │  │  (Low   │  │  (Fallback)│
                    │              │  │  token  │  │            │
                    │  JSON-RPC    │  │  cost)  │  │  HTTP/JSON │
                    │  OAuth 2.1   │  │  JSON   │  │  API Keys  │
                    │  Tool disc.  │  │  output │  │  OpenAPI   │
                    └──────┬───────┘  └────┬────┘  └─────┬──────┘
                           │               │             │
                    ┌──────▼───────────────▼─────────────▼──────┐
                    │           Shared Service Layer             │
                    │  (Business logic, auth, validation,       │
                    │   rate limiting, audit logging)            │
                    └──────────────────┬────────────────────────┘
                                      │
                    ┌─────────────────▼────────────────────────┐
                    │           Data & Infrastructure           │
                    │  (PostgreSQL, Redis, Celery, S3)          │
                    └──────────────────────────────────────────┘
```

### Layer Details

#### Layer 1: MCP Server (Priority 1)

**What to expose:**

| MCP Tools (Actions) | MCP Resources (Data) | MCP Prompts (Templates) |
|---------------------|---------------------|------------------------|
| `create_job` | `user://profile` | `analyze_usage` |
| `list_jobs` | `billing://usage` | `generate_report` |
| `get_job_status` | `team://members` | `troubleshoot_job` |
| `query_ai` | `ai://models` | `optimize_costs` |
| `manage_team` | `jobs://recent` | |
| `configure_webhook` | `webhooks://events` | |
| `export_data` | `audit://logs` | |
| `manage_billing` | `wallet://balance` | |

**Implementation**: Use the official `mcp` Python SDK. The MCP server wraps the existing service layer — no business logic duplication.

#### Layer 2: CLI Tool (Priority 2)

**Design pattern**: Noun-verb with `--output json`

```bash
# Examples
nxs job create --type analysis --data '{"url": "..."}' --output json
nxs job list --status pending --output json
nxs ai query --model claude-3 --prompt "..." --output json
nxs team list --output json
nxs billing usage --period 2026-03 --output json
nxs webhook create --url https://... --events job.completed --output json
```

**Implementation**: Use `typer` (already a FastAPI-ecosystem tool) with `rich` for human output and `--output json` for agent output.

#### Layer 3: REST API Enhancements (Priority 3)

Enhance the existing FastAPI API:

1. **Enrich OpenAPI descriptions** — add `why` explanations, examples, hints
2. **Structured error responses** — `error_code` enum, `hint` field, `request_id`
3. **Idempotency keys** — `Idempotency-Key` header on POST/PUT/PATCH
4. **Rate limit headers** — `X-RateLimit-Remaining`, `Retry-After`
5. **OAuth 2.1 Client Credentials** — machine-to-machine auth flow
6. **Bot identity model** — separate from user identity
7. **Agent-specific rate limit tier** — higher burst, lower sustained

---

## 10. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-3)

| Task | Effort | Impact |
|------|--------|--------|
| Add OAuth 2.1 Client Credentials flow | Medium | Unblocks bot auth |
| Enrich OpenAPI descriptions on all endpoints | Low | Improves agent understanding |
| Add structured error responses with hints | Low | Reduces agent failures |
| Add `Idempotency-Key` header support | Medium | Prevents duplicate operations |
| Add rate limit response headers | Low | Enables agent throttling |

### Phase 2: MCP Server (Weeks 3-6)

| Task | Effort | Impact |
|------|--------|--------|
| Set up MCP server scaffold (`mcp` Python SDK) | Low | Foundation |
| Expose core tools: jobs, AI, teams, billing | High | Primary bot interface |
| Expose resources: profile, usage, models | Medium | Data access for agents |
| Add MCP OAuth 2.1 integration | Medium | Secure agent auth |
| Add prompt templates for common workflows | Low | Agent UX improvement |
| Write MCP server documentation | Medium | Adoption enablement |

### Phase 3: CLI Tool (Weeks 6-8)

| Task | Effort | Impact |
|------|--------|--------|
| Set up CLI scaffold with `typer` | Low | Foundation |
| Implement core commands: job, ai, team, billing | High | Shell-agent interface |
| Add `--output json` flag on all commands | Low | Agent-compatible output |
| Add `--help` with rich descriptions | Low | Agent discoverability |
| Package and distribute (PyPI, Homebrew) | Medium | Adoption |

### Phase 4: Advanced (Weeks 8-12)

| Task | Effort | Impact |
|------|--------|--------|
| Bot identity model (separate from users) | Medium | Audit & governance |
| Agent-specific rate limit tiers | Low | Better bot experience |
| A2A Agent Card for multi-agent discovery | Low | Future-proofing |
| Monitoring dashboard for bot usage | Medium | Operations visibility |
| Security hardening (scoped tokens, audit) | Medium | Enterprise readiness |

---

## Appendix A: Answer to the Original Question

> Is the REST API provided by FastAPI sufficient to allow bots to perform specific actions, or should we implement a powerful CLI command infrastructure?

**Neither alone is sufficient. The answer is: MCP + REST enhancements + CLI.**

- **REST API alone**: Insufficient. Modern AI agents (Manus, OpenClaw) prefer MCP for tool discovery and stateful sessions. Raw REST requires agents to manually parse OpenAPI specs, manage auth tokens, and handle pagination — all friction points that reduce reliability.

- **CLI alone**: Insufficient. While CLI is excellent for shell-capable agents (Claude Code, Gemini CLI) and has the lowest token cost, it doesn't support the stateful, discoverable workflow that MCP provides. It also requires distribution and installation.

- **MCP + enhanced REST + CLI**: This is what GitHub and Stripe do. It's the gold standard. Each channel serves a different agent archetype:
  - **MCP**: Manus, multi-agent orchestrators, enterprise integrations
  - **CLI**: Claude Code, Gemini CLI, developer agents with shell access
  - **REST API**: Fallback for any agent, custom integrations, direct SDK usage

The existing FastAPI REST API is an **excellent foundation**. The service layer, auth system, and business logic are already built. The MCP server and CLI are thin wrappers around this existing logic — not a rewrite.

---

## Appendix B: Sources

- [PacGenesis OpenClaw Guide](https://pacgenesis.com/what-is-openclaw-ai-everything-you-need-to-know-about-the-open-source-ai-agent-that-actually-does-things/)
- [OpenClaw Architecture (Medium)](https://bibek-poudel.medium.com/how-openclaw-works-understanding-ai-agents-through-a-real-architecture-5d59cc7a4764)
- [CrowdStrike OpenClaw Security Analysis](https://www.crowdstrike.com/en-us/blog/what-security-teams-need-to-know-about-openclaw-ai-super-agent/)
- [Stripe Agent Docs](https://docs.stripe.com/agents)
- [Stripe AI Toolkit (GitHub)](https://github.com/stripe/ai)
- [Agentic Commerce Protocol (GitHub)](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol)
- [GitHub Agent HQ (Visual Studio Magazine)](https://visualstudiomagazine.com/articles/2025/10/28/github-introduces-agent-hq-to-orchestrate-any-agent-any-way-you-work.aspx)
- [GitHub Blog on MCP](https://github.blog/developer-skills/agentic-ai-mcp-and-spec-driven-development-top-blog-posts-of-2025/)
- [Stytch Agent-to-Agent OAuth](https://stytch.com/blog/agent-to-agent-oauth-guide/)
- [Auth0 on Secure AI Agents](https://auth0.com/blog/third-party-access-tokens-secure-ai-agents/)
- [WorkOS OAuth for AI Agents](https://workos.com/blog/best-oauth-oidc-providers-for-authenticating-ai-agents-2025)
- [Curity API Security for AI Agents](https://curity.io/resources/learn/api-security-best-practice-for-ai-agents/)
- [Composio Integration Patterns](https://composio.dev/blog/apis-ai-agents-integration-patterns)
- [Google A2A Announcement](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [Top MCP Servers 2026 (Index.dev)](https://www.index.dev/blog/top-mcp-servers-for-ai-development)
