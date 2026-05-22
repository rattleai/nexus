# NEXUS

> AI-first multi-agent platform foundation. Plug your application in.

[![CI](https://github.com/rattleai/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/rattleai/nexus/actions/workflows/ci.yml)
[![CodeQL](https://github.com/rattleai/nexus/actions/workflows/codeql.yml/badge.svg)](https://github.com/rattleai/nexus/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![Node 22+](https://img.shields.io/badge/node-22%2B-339933.svg)](frontend/package.json)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

NEXUS is a generic, multi-tenant SaaS platform you fork to build AI applications on top of. The core ships everything you'd otherwise spend a quarter on — agent runtime, multi-provider AI gateway, MCP server, A2A messaging, RAG, billing, auth, jobs, files, audit — and exposes a small, opinionated **plugin contract** so your app code stays cleanly isolated from the platform.

You write a plugin under `app/apps/<your_app>/`. The platform discovers it on startup and wires in your routers, models, MCP tools, agent tools, capabilities, Celery tasks, scopes, and frontend nav. Read [`docs/PLUGINS.md`](docs/PLUGINS.md) to ship your first one.

## Contents

- [Tech stack](#tech-stack)
- [What you get out of the box](#what-you-get-out-of-the-box)
- [Quick start](#quick-start)
- [Build your first plugin](#build-your-first-plugin)
- [Project layout](#project-layout)
- [Common commands](#common-commands)
- [Deployment](#deployment)
- [Security](#security)
- [Contributing](#contributing)
- [Community](#community)
- [License](#license)

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Celery |
| Frontend | React 19, TypeScript, Vite, TailwindCSS 4, TanStack Router |
| Database | PostgreSQL 16 (pgvector + pgvectorscale), PgBouncer, Alembic |
| Cache | Redis 7 |
| AI gateway | LiteLLM — OpenAI, Anthropic, Google, Mistral, DeepSeek, Qwen, Aleph Alpha, xAI |
| Auth | JWT (RS256/HS256), Google + GitHub OAuth, WebAuthn / FIDO2, MFA |
| Billing | Stripe — subscriptions, credit wallets, usage metering |
| Storage | S3-compatible (AWS S3, Cloudflare R2, MinIO) |
| Observability | structlog, OpenTelemetry, Prometheus, Jaeger |
| Infra | Docker, Docker Compose, Kubernetes, Terraform (AWS ECS/RDS/ElastiCache) |

## What you get out of the box

- **Multi-tenancy** with PostgreSQL Row-Level Security enforced from a non-superuser app role.
- **Agent runtime** with capabilities, governance (approval gates, spend caps), A2A messaging, sandboxed tool execution, streaming, persistence, checkpointing, and replay.
- **AI gateway** routing to multiple providers, with prompt firewall, BYOK keys, dollar wallets, cost margins, caching, and usage metering.
- **MCP server** (Nov 2025 spec) auto-derived from FastAPI routes plus plugin-contributed tools.
- **RAG pipeline** — document ingestion, chunking, hybrid search, reranker, HyDE, agentic, graph, evaluation harness.
- **Auth** — sessions, JWT with key rotation, OAuth (Google + GitHub), WebAuthn, MFA, OAuth client-credentials issuer, API keys with scopes.
- **Billing** — Stripe subscriptions and credit packs, entitlement checks, quota enforcement.
- **Background jobs**, **webhooks**, **email**, **push notifications**, **file uploads** with image transforms, **i18n** (EN/DE/ES/ZH), **PWA**.

## Quick start

```bash
git clone https://github.com/rattleai/nexus.git
cd nexus
cp .env.example .env

make dev-up            # postgres, redis, api, frontend, worker
make seed-docker       # migrations + a dev tenant + admin user

# http://localhost:3000          frontend
# http://localhost:8002/api/docs Swagger UI (DEBUG=true only)
```

Optional services:

```bash
docker compose --profile async up -d           # Celery worker + beat
docker compose --profile mcp up -d             # MCP server
docker compose --profile observability up -d   # Jaeger UI on :16686
```

Local development without Docker — see [`docs/DEPLOY.md`](docs/DEPLOY.md). For the system-level view of how the platform fits together, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Build your first plugin

A plugin is a single Python package under `app/apps/<name>/` plus an optional matching frontend tree under `frontend/src/apps/<name>/`. The reference plugin at `app/apps/example/` (≈ 150 lines + a no-op Alembic migration + a frontend mirror) demonstrates the full contract surface.

```python
# app/apps/myapp/plugin.py
from app.plugins.base import AppPluginBase

class MyAppPlugin(AppPluginBase):
    @property
    def name(self) -> str: return "myapp"
    @property
    def version(self) -> str: return "0.1.0"

    def get_routers(self):
        from app.apps.myapp.api import router
        return [router]

PLUGIN = MyAppPlugin()
```

Drop the file in place, restart the API, and your routes are mounted under `/api/v1`. The full contract (14 hooks: routers, models, MCP tools, agent tools, capabilities, Celery, scopes, error handlers, frontend manifest, lifecycle) is documented in [`docs/PLUGINS.md`](docs/PLUGINS.md).

## Project layout

```
.
├── app/
│   ├── agents/                 Agent runtime, governance, A2A, RAG, sandboxing
│   ├── ai/                     LiteLLM gateway, wallet, prompt firewall, providers
│   ├── api/v1/                 Core REST routes (auth, ai, agents, billing, jobs, files, ...)
│   ├── apps/                   Application plugins
│   │   └── example/            Reference plugin — copy this when starting
│   ├── billing/                Stripe integration, entitlements, enforcement
│   ├── core/                   Security, Redis, OAuth, encryption, logging, telemetry
│   ├── db/
│   │   ├── models/             SQLAlchemy models (infrastructure)
│   │   └── migrations/         Alembic — core history
│   ├── docprocessor/           Document parsing pipeline (PDF, DOCX, XLSX, HTML, ...)
│   ├── evaluation/             RAG evaluation harness
│   ├── mcp/                    MCP server (stdio + HTTP)
│   ├── plugins/                Plugin discovery & contract
│   ├── storage/                S3-compatible file storage
│   └── workers/                Celery tasks & scheduling
├── frontend/                   React SPA
│   └── src/apps/<name>/        Plugin frontend trees mirror app/apps/
├── infra/                      Docker, Kubernetes, Terraform, nginx
├── tests/                      pytest suite
├── docs/
│   ├── PLUGINS.md              Plugin contract + walkthrough
│   ├── DEPLOY.md               Production deployment
│   └── ...                     Architecture references
├── docker-compose.yml          Development stack
├── docker-compose.prod.yml     Production stack
├── Makefile                    Convenience targets
└── pyproject.toml              Python packaging
```

## Common commands

```bash
make help            # list every target
make dev-up          # start dev stack
make test            # backend tests
make lint            # ruff
make typecheck       # mypy
make migrate         # alembic upgrade head
make fe-dev          # frontend dev server
make fe-build        # frontend production build
make api-sync        # regenerate TypeScript client from OpenAPI
make build           # production Docker image
make mcp             # MCP server (stdio)
```

## Deployment

Three supported paths — [`docs/DEPLOY.md`](docs/DEPLOY.md) has step-by-step instructions:

- **Docker Compose** on a single VPS (4 GB RAM minimum).
- **AWS ECS Fargate** via Terraform (ECS + RDS + ElastiCache + ALB + WAF).
- **Kubernetes** via Kustomize manifests with HPA, network policies, RBAC.

## Security

- Argon2id password hashing, JWT with JTI revocation and key rotation, MFA via WebAuthn.
- AES-256-GCM (v2) for OAuth tokens and other secrets at rest.
- RLS enforced from a non-superuser app role; startup verifies the role.
- nginx with HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- CSRF (double-submit), Redis-backed rate limits, request size and gzip-bomb caps.
- Container runs non-root (UID 1001); CI signs the image with cosign.
- Pre-merge: Bandit SAST, pip-audit, Gitleaks, Trivy. Vulnerability disclosure via [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, branching model, and the local check matrix. By contributing, you agree your work is licensed under [Apache-2.0](LICENSE).

## Community

- **Discussions** — design ideas, plugin showcases, Q&A: https://github.com/rattleai/nexus/discussions
- **Issues** — bug reports and feature requests: use the templates under `.github/ISSUE_TEMPLATE/`.
- **Security** — see [SECURITY.md](SECURITY.md). Do not open public issues for vulnerabilities.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
