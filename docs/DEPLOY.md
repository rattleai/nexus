# Deployment

NEXUS supports three deployment paths. Pick the one that matches your operational maturity:

| Path | When to use | Resources |
|------|-------------|-----------|
| **Docker Compose** | Single-tenant, single-region, you own the box. | 4 GB RAM minimum, 2 vCPU, 40 GB SSD. |
| **AWS ECS Fargate** | Production multi-tenant on AWS without running Kubernetes. | Provisioned by Terraform; ~$250-400/month. |
| **Kubernetes** | You already run Kubernetes. | Kustomize manifests with HPA, network policies, RBAC, pod anti-affinity. |

Each path is described below. For a runbook covering on-call procedures, backups, certificate rotation, and incident response, see [`infra/PRODUCTION_RUNBOOK.md`](../infra/PRODUCTION_RUNBOOK.md).

## Local development without Docker

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm ci && npm run dev
```

You will need Postgres 16 with the `vector` (and optionally `vectorscale`) extensions, plus Redis 7, accessible at the URLs in `.env`.

## Docker Compose (VPS)

```bash
# 1. Generate production secrets (one-time)
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
#   - Paste secrets from steps 1 + 2
#   - Set DOMAIN, APP_BASE_URL to your domain
#   - Set DATABASE_URL, REDIS_URL with the passwords
#   - Set CORS_ORIGINS to your domain
#   - Set DATABASE_SSL_MODE=require
#   - Configure OAuth (OAUTH_GOOGLE_*, OAUTH_GITHUB_*) if using social login
#   - Configure Stripe keys if using billing
#   - Configure AI provider keys if using the AI gateway

# 4. Build and start
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# 5. Run migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# 6. Get a TLS certificate (replace with your domain)
DOMAIN=your-domain.com make prod-certbot-init

# 7. Verify
curl -sf https://your-domain.com/api/v1/health/ready
```

The compose file isolates services on private networks: nginx is the only container exposing ports to the host (80, 443). API, workers, Postgres, and Redis are reachable only through the proxy or from each other.

## AWS ECS Fargate

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars (domain, region, sizing, AI provider keys)
terraform init
terraform apply
```

The Terraform module provisions ~40 resources — VPC, subnets, RDS Postgres, ElastiCache Redis, ECS cluster + service, ALB, WAF, S3 buckets for artifacts, IAM roles, CloudWatch log groups, parameter store entries.

After apply:

```bash
# Run the bootstrap migration. ECS exec is enabled in the task definition.
aws ecs execute-command \
  --cluster nxs-prod \
  --task <task-id> \
  --container api \
  --interactive --command "alembic upgrade head"
```

The CI deploy job in `.github/workflows/ci.yml` performs `aws ecs update-service --force-new-deployment` to roll out a new image tag once it has been published to GHCR. Cluster and service names are taken from `vars.ECS_CLUSTER` and `vars.ECS_SERVICE` — set them as repository variables.

## Kubernetes

```bash
cd infra/k8s
kubectl create namespace nexus
# Replace placeholder secrets in secret.yaml first
kubectl apply -k . -n nexus
```

Manifests cover:

- Deployments for API, frontend, Celery worker, Celery beat.
- HorizontalPodAutoscalers based on CPU + custom metrics.
- NetworkPolicies that restrict pod-to-pod traffic to known paths.
- PodDisruptionBudgets and pod anti-affinity to spread replicas across nodes.
- ServiceAccount + RBAC role for the operator pod.
- Ingress with TLS termination and the same security headers as the nginx config.

## Production architecture

```
                    ┌─────────────────┐
                    │     nginx       │
                    │  TLS + headers  │
                    │  rate limiting  │
                    └────────┬────────┘
                             │ proxy network
                    ┌────────┴────────┐
                    │    api (x N)    │
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
                    │   celery worker (x M) │
                    │   celery beat   (x 1) │
                    └───────────────────────┘
```

## Key environment variables

The full list is in [`.env.example`](../.env.example). Highlights:

| Group | Variables | Required |
|-------|-----------|----------|
| Secrets | `SECRET_KEY`, `ENCRYPTION_KEY`, `ADMIN_KEY`, `WEBHOOK_SIGNING_KEY` | Production |
| Database | `DATABASE_URL`, `DATABASE_MIGRATION_URL`, `DATABASE_SSL_MODE` | Always |
| Redis | `REDIS_URL`, `REDIS_PASSWORD` | Always |
| JWT | `JWT_ALGORITHM`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE` | Production (RS256) |
| OAuth | `OAUTH_GOOGLE_CLIENT_ID/SECRET`, `OAUTH_GITHUB_CLIENT_ID/SECRET` | If social login |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | If billing |
| AI | `AI_ENABLED`, `AI_<PROVIDER>_API_KEY` | If AI gateway |
| Email | `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` | If email notifications |
| Storage | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | If file uploads |
| Domain | `DOMAIN`, `APP_BASE_URL`, `CORS_ORIGINS` | Production |
| Plugins | `APP_<NAME>_ENABLED` (one per plugin under `app/apps/`) | As needed |

## Releasing

The release workflow at [`.github/workflows/release.yml`](../.github/workflows/release.yml) is triggered by pushing a `v*` tag. It builds the GHCR image, signs it with cosign, generates an SPDX SBOM, and publishes a GitHub Release whose body is pulled from the matching `CHANGELOG.md` section.

```bash
# Cut a release
git tag -s v0.1.1 -m "v0.1.1"
git push origin v0.1.1
```

The deploy step in CI then needs to be triggered manually with `workflow_dispatch` once the image is in GHCR and you're ready to roll it out.
