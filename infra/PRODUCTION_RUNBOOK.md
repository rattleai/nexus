# Production Deployment Runbook

## Prerequisites

- AWS CLI configured with appropriate IAM permissions
- Terraform >= 1.6 installed
- Docker installed for image building
- Domain name with DNS access

## Deployment Paths

### Path A: AWS ECS Fargate (Recommended)

#### 1. Build & Push Container Image

```bash
# Authenticate to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Build production image
docker build -t ghcr.io/your-org/nxs:v1.0.0 .
docker push ghcr.io/your-org/nxs:v1.0.0
```

#### 2. Configure Terraform Variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
environment      = "prod"
aws_region       = "us-east-1"
container_image  = "ghcr.io/your-org/nxs:v1.0.0"
domain_name      = "example.com"
db_instance_class = "db.t4g.medium"
```

#### 3. Initialize & Apply Terraform

```bash
terraform init

# Review the plan
terraform plan -out=tfplan

# Apply (creates ~40 resources)
terraform apply tfplan

# Save outputs
terraform output -json > outputs.json
```

#### 4. Configure DNS

Point your domain to the ALB:
```bash
# Get ALB DNS name
terraform output alb_dns_name

# Create CNAME record:
# example.com → <alb-dns-name>
```

#### 5. Run Database Migrations

```bash
# Run as one-off ECS task
aws ecs run-task \
  --cluster nxs-prod \
  --task-definition nxs-api \
  --launch-type FARGATE \
  --overrides '{
    "containerOverrides": [{
      "name": "api",
      "command": ["alembic", "upgrade", "head"]
    }]
  }' \
  --network-configuration '{
    "awsvpcConfiguration": {
      "subnets": ["<private-subnet-id>"],
      "securityGroups": ["<ecs-sg-id>"]
    }
  }'
```

#### 6. Verify Deployment

```bash
# Check ECS services
aws ecs describe-services --cluster nxs-prod \
  --services nxs-api nxs-worker nxs-beat

# Check health endpoint
curl https://example.com/api/v1/health/live
curl https://example.com/api/v1/health/ready

# Check CloudWatch alarms
aws cloudwatch describe-alarms --alarm-name-prefix nxs
```

### Path B: Kubernetes

#### 1. Create Namespace & Secrets

```bash
kubectl create namespace nxs

# Create secrets (use external-secrets-operator in production)
kubectl -n nxs create secret generic nxs-secrets \
  --from-literal=SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  --from-literal=ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  --from-literal=DATABASE_URL=postgresql+asyncpg://app_user:PASSWORD@db-host:5432/nxs?ssl=require \
  --from-literal=REDIS_URL=rediss://:PASSWORD@redis-host:6379/0
```

#### 2. Deploy with Kustomize

```bash
cd infra/k8s
kubectl apply -k .

# Verify pods
kubectl -n nxs get pods -w

# Check logs
kubectl -n nxs logs -l app=nxs-api --tail=50
```

#### 3. Run Migrations

```bash
kubectl -n nxs exec deploy/nxs-api -- alembic upgrade head
```

### Path C: Docker Compose on VPS

#### 1. Provision Server

Minimum: 4GB RAM, 2 vCPUs, 40GB SSD (Ubuntu 22.04+).

#### 2. Deploy

```bash
# On the server
git clone <repo> /opt/nxs
cd /opt/nxs

cp .env.example .env
# Edit .env with production values

# Deploy with build and migrations
./infra/scripts/deploy.sh --build --migrate
```

## Secret Generation

Generate all required secrets before deployment:

```bash
# Generate each secret independently
python -c "import secrets; print(secrets.token_urlsafe(32))"  # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"  # ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"  # ADMIN_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"  # WEBHOOK_SIGNING_KEY

# Generate JWT RS256 keypair
openssl genrsa -out jwt_private.pem 4096
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

## Rolling Updates

### ECS
```bash
# Update container image in tfvars, then:
terraform apply

# Or force new deployment with same image:
aws ecs update-service --cluster nxs-prod \
  --service nxs-api --force-new-deployment
```

### Kubernetes
```bash
kubectl -n nxs set image deploy/nxs-api \
  api=ghcr.io/your-org/nxs:v1.1.0
kubectl -n nxs rollout status deploy/nxs-api
```

### Docker Compose
```bash
./infra/scripts/deploy.sh --build --migrate
```

## Rollback Procedures

### ECS
```bash
# Revert Terraform to previous image tag
terraform apply

# Or rollback ECS service to previous task definition
aws ecs update-service --cluster nxs-prod \
  --service nxs-api \
  --task-definition nxs-api:<previous-revision>
```

### Kubernetes
```bash
kubectl -n nxs rollout undo deploy/nxs-api
```

### Docker Compose
The deploy script auto-rolls back on health check failure. Manual:
```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

## Database Operations

### Backup (manual)
```bash
# ECS/K8s: Connect to RDS
pg_dump -h <rds-endpoint> -U nxs_master -d nxs | gzip > backup.sql.gz

# Docker Compose: Uses automated backup container (daily 2 AM UTC)
docker compose -f docker-compose.prod.yml exec db-backup /backup.sh
```

### Migration
```bash
# Always backup before migrating
alembic upgrade head

# Rollback one revision
alembic downgrade -1
```

## Monitoring & Alerts

### CloudWatch Alarms (ECS path)
Pre-configured alarms:
- ALB 5xx error rate > 5%
- ALB response time > 2s
- ECS API CPU > 80%
- ECS API memory > 80%
- RDS CPU > 80%
- RDS free storage < 5GB
- RDS connections > 80
- Redis CPU > 80%
- Redis memory > 80%
- Redis connections > 200

### Health Checks
- Liveness: `GET /api/v1/health/live` (is the process running?)
- Readiness: `GET /api/v1/health/ready` (can it serve traffic? checks DB + Redis)

## Cost Estimates

| Path | Monthly Cost | Best For |
|------|-------------|----------|
| ECS Fargate | $250-400 | Small team, managed infrastructure |
| EKS | $350-500 | Larger team, multi-service architecture |
| VPS + Docker | $20-40 | MVP, bootstrapped projects |
