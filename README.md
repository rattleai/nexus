# NEXUS SaaS Platform

Multi-tenant SaaS platform with a FastAPI backend, React frontend, and AI gateway. Supports JWT + OAuth authentication, Stripe billing, background job processing, real-time WebSocket communication, and progressive web app capabilities.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2 (async), Celery |
| **Frontend** | React 19, TypeScript, Vite, TailwindCSS 4, TanStack Router |
| **Database** | PostgreSQL 16 (pgvector), PgBouncer, Alembic migrations |
| **Cache** | Redis 7 |
| **AI Gateway** | LiteLLM (OpenAI, Anthropic, Google, Mistral, DeepSeek, Qwen, Aleph Alpha, xAI) |
| **Auth** | JWT (RS256/HS256), Google OAuth, GitHub OAuth, WebAuthn/FIDO2 |
| **Billing** | Stripe (subscriptions, credit packs, usage metering) |
| **Storage** | S3-compatible (AWS S3, Cloudflare R2, MinIO) |
| **Observability** | Structlog, OpenTelemetry, Prometheus, Jaeger |
| **Infra** | Docker, Docker Compose, Kubernetes, Terraform (AWS ECS/RDS/ElastiCache) |

## Features

- **Multi-tenancy** with Row-Level Security (RLS) enforcement
- **Authentication** -- API keys, JWT, Google/GitHub OAuth, WebAuthn biometrics, MFA
- **AI gateway** -- multi-provider routing, BYOK support, usage tracking, prompt templates
- **Billing** -- Stripe subscriptions, credit wallets, margin multipliers
- **Background jobs** -- Celery with Redis-backed scheduling, dead-letter queue, agent execution
- **Webhooks** -- endpoint management, delivery tracking, signing
- **Notifications** -- email (Brevo), Web Push (VAPID), Firebase Cloud Messaging
- **File storage** -- S3-compatible uploads with CDN support and image transforms
- **Real-time** -- WebSocket support, Server-Sent Events
- **PWA** -- offline-capable progressive web app with Workbox caching
- **Internationalization** -- i18next with EN, DE, ES, ZH locales
- **Plugin system** -- OpenAI GPT Actions, Microsoft Copilot, MCP server
- **Enterprise** -- SSO (SAML/OIDC), feature flags, audit logging, GDPR compliance

## Quick Start

### Prerequisites

- Docker and Docker Compose v2
- (Optional) Node 22, Python 3.12 for local development without Docker

### Development

```bash
# 1. Clone and configure
cp .env.example .env

# 2. Start all services (API, frontend, DB, Redis, PgBouncer)
make dev-up

# 3. Run database migrations
make seed-docker    # runs migrations + creates a dev user

# 4. Open the app
#    Frontend:  http://localhost:3000
#    API docs:  http://localhost:8002/api/docs
```

To start optional services:

```bash
# Celery workers (background jobs)
docker compose --profile async up -d

# MCP server
docker compose --profile mcp up -d

# Jaeger tracing UI (http://localhost:16686)
docker compose --profile observability up -d
```

### Local Development (without Docker)

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev
```

## Project Structure

```
.
├── app/                        # FastAPI backend
│   ├── agents/                 # Agent orchestration & execution
│   ├── ai/                     # LiteLLM AI gateway & provider routing
│   ├── api/v1/                 # REST API routes (27+ modules)
│   ├── billing/                # Stripe integration
│   ├── core/                   # Security, Redis, OAuth, encryption, logging
│   ├── db/
│   │   ├── models/             # SQLAlchemy ORM models
│   │   └── migrations/         # Alembic migration versions
│   ├── services/               # Business logic layer
│   ├── storage/                # S3-compatible file storage
│   ├── workers/                # Celery tasks & scheduling
│   ├── config.py               # Pydantic settings (60+ env vars)
│   └── main.py                 # App factory, middleware, lifespan
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── components/         # UI components (shadcn/ui + Radix)
│   │   ├── lib/                # API client, auth context, utilities
│   │   └── routes/             # File-based routing (TanStack Router)
│   └── public/locales/         # i18n translation files
├── infra/
│   ├── docker/                 # DB init scripts
│   ├── nginx/                  # Reverse proxy + TLS config
│   ├── k8s/                    # Kubernetes manifests (Kustomize)
│   ├── terraform/              # AWS ECS/RDS/ElastiCache/ALB/WAF
│   ├── scripts/                # deploy.sh, backup scripts
│   └── PRODUCTION_RUNBOOK.md   # Deployment guide (3 platforms)
├── tests/                      # pytest test suite
├── docker-compose.yml          # Development services
├── docker-compose.prod.yml     # Production services
├── Dockerfile                  # Multi-stage build (frontend + backend)
├── Makefile                    # Build shortcuts
└── pyproject.toml              # Python dependencies & tool config
```

## Production Deployment

Three deployment paths are supported. See [`infra/PRODUCTION_RUNBOOK.md`](infra/PRODUCTION_RUNBOOK.md) for full instructions.

### Docker Compose (VPS)

Minimum requirements: 4 GB RAM, 2 vCPU, 40 GB SSD.

```bash
# 1. Generate production secrets
export SECRET_KEY=$(openssl rand -hex 32)
export ENCRYPTION_KEY=$(openssl rand -hex 32)
export ADMIN_KEY=$(openssl rand -hex 32)
export WEBHOOK_SIGNING_KEY=$(openssl rand -hex 32)
export DB_PASSWORD=$(openssl rand -hex 24)
export REDIS_PASSWORD=$(openssl rand -hex 24)

# 2. Generate JWT RS256 keypair
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem

# 3. Configure environment
cp .env.example .env.production
# Edit .env.production:
#   - Set all secrets from step 1
#   - Set JWT_PRIVATE_KEY / JWT_PUBLIC_KEY from step 2
#   - Set DOMAIN, APP_BASE_URL
#   - Set DATABASE_URL, REDIS_URL with passwords
#   - Set CORS_ORIGINS to your domain
#   - Set DATABASE_SSL_MODE=require
#   - Configure OAuth (OAUTH_GOOGLE_*, OAUTH_GITHUB_*) if using social login
#   - Configure Stripe keys if using billing
#   - Configure AI provider keys if using AI gateway

# 4. Build and start
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# 5. Run database migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# 6. Get TLS certificate (replace with your domain)
DOMAIN=app.example.com make prod-certbot-init

# 7. Verify
curl -sf https://app.example.com/api/v1/health/ready
```

### AWS ECS Fargate

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your AWS config
terraform init && terraform apply
```

Estimated cost: $250-400/month. Creates ~40 resources (VPC, RDS, ElastiCache, ECS, ALB, WAF, S3).

### Kubernetes

```bash
cd infra/k8s
kubectl apply -k .
```

Manifests include HPA, network policies, RBAC, pod anti-affinity, and priority classes.

## Production Architecture

```
                    ┌─────────────────┐
                    │     nginx       │
                    │  TLS + headers  │
                    │  rate limiting  │
                    └────────┬────────┘
                             │ proxy network
                    ┌────────┴────────┐
                    │    api (x2)     │
                    │    FastAPI      │
                    │    uvicorn      │
                    └──┬──────────┬───┘
                       │          │ data network
              ┌────────┴───┐  ┌──┴──────────┐
              │ PostgreSQL │  │    Redis     │
              │  pgvector  │  │   7-alpine   │
              │ PgBouncer  │  └──┬──────────┘
              └────────────┘     │
                    ┌────────────┴──────────┐
                    │   celery worker (x1)  │
                    │   celery beat   (x1)  │
                    └───────────────────────┘
```

**Network isolation:** nginx can only reach the API (proxy network). API, workers, DB, and Redis share a private data network. No service exposes ports to the host except nginx (80, 443).

## Security

- **Authentication:** Argon2id password hashing, JWT with JTI-based revocation, MFA via WebAuthn
- **CSRF:** Double-submit cookie with constant-time comparison
- **Rate limiting:** Redis-backed sliding window with in-memory fallback
- **Encryption:** AES-256-GCM (v2) for OAuth tokens and sensitive data at rest
- **Database:** Row-Level Security enforced; app connects as non-superuser
- **Headers:** CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy
- **Secrets:** Startup validation rejects default/missing keys in production
- **Container:** Non-root user (UID 1001), SBOM generation, Cosign image signing in CI

## API

Interactive documentation is available in development:

- **Swagger UI:** `http://localhost:8002/api/docs`
- **ReDoc:** `http://localhost:8002/api/redoc`

Key endpoint groups:

| Prefix | Purpose |
|--------|---------|
| `/api/v1/auth/` | Login, register, password reset, OAuth, WebAuthn |
| `/api/v1/tenants/` | Tenant management |
| `/api/v1/team/` | Team invitations, membership, roles |
| `/api/v1/ai/` | AI chat, completions, usage, provider keys |
| `/api/v1/agents/` | Agent orchestration & execution |
| `/api/v1/billing/` | Plans, subscriptions, wallets, Stripe webhooks |
| `/api/v1/jobs/` | Background job management |
| `/api/v1/files/` | File upload, download, presigned URLs |
| `/api/v1/webhooks/` | Webhook endpoint management |
| `/api/v1/health/` | Liveness, readiness, detailed health checks |
| `/.well-known/jwks.json` | JWT public key discovery |
| `/.well-known/mcp` | MCP server discovery |

## Make Targets

```
make help             # Show all targets
make dev-up           # Start development services
make dev-down         # Stop all services
make test             # Run backend tests
make lint             # Lint backend (ruff)
make format           # Format backend code
make typecheck        # Run mypy
make migrate          # Run database migrations
make migrate-new msg="..." # Create new migration
make fe-dev           # Start frontend dev server
make fe-build         # Build frontend for production
make fe-test          # Run frontend tests
make api-sync         # Regenerate TypeScript API client from OpenAPI
make build            # Build production Docker image
make prod-up          # Start production services
make prod-deploy      # Deploy with build + migrations
make prod-backup      # Manual database backup
make seed-docker      # Seed dev database with test data
make mcp              # Start MCP server (stdio)
make new-service dest=... # Scaffold a new microservice
```

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`):

1. **Lint** -- ruff (backend), ESLint + TypeScript (frontend)
2. **Test** -- pytest with 80% coverage gate, vitest
3. **Security** -- Bandit SAST, pip-audit, Gitleaks, Trivy container scan
4. **Build** -- Docker image push to `ghcr.io` with Cosign signing
5. **E2E** -- Playwright browser tests
6. **Deploy** -- ECS rolling update or SSH-based deployment (manual trigger)

## Environment Variables

See [`.env.example`](.env.example) for the full list with documentation. Key groups:

| Group | Variables | Required |
|-------|----------|----------|
| **Secrets** | `SECRET_KEY`, `ENCRYPTION_KEY`, `ADMIN_KEY`, `WEBHOOK_SIGNING_KEY` | Production |
| **Database** | `DATABASE_URL`, `DB_POOL_SIZE`, `DATABASE_SSL_MODE` | Always |
| **Redis** | `REDIS_URL`, `REDIS_PASSWORD` | Always |
| **JWT** | `JWT_ALGORITHM`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` | Production (RS256) |
| **OAuth** | `OAUTH_GOOGLE_CLIENT_ID/SECRET`, `OAUTH_GITHUB_CLIENT_ID/SECRET` | If social login |
| **Stripe** | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | If billing |
| **AI** | `AI_ENABLED`, provider API keys | If AI gateway |
| **Email** | `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` | If email notifications |
| **Storage** | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | If file uploads |
| **Domain** | `DOMAIN`, `APP_BASE_URL`, `CORS_ORIGINS` | Production |
