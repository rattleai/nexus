.PHONY: dev dev-up dev-down test lint format migrate seed build seed-docker mcp mcp-http \
       prod-up prod-down prod-logs prod-deploy prod-backup prod-certbot-init \
       api-export api-generate api-sync new-service

# ── Development ──────────────────────────────────────────────
dev-up:  ## Start all services (DB, Redis, API, frontend, worker)
	docker compose up -d

dev-down:  ## Stop all services
	docker compose down

dev:  ## Start with log output attached
	docker compose up

logs:  ## Tail logs from all services
	docker compose logs -f

# ── Backend ──────────────────────────────────────────────────
test:  ## Run backend tests
	python -m pytest tests/ -v

lint:  ## Lint backend code
	ruff check app/ tests/

format:  ## Format backend code
	ruff format app/ tests/
	ruff check --fix app/ tests/

typecheck:  ## Run mypy type checking
	mypy app/

# ── Database ─────────────────────────────────────────────────
migrate:  ## Run database migrations
	alembic upgrade head

migrate-new:  ## Create a new migration (usage: make migrate-new msg="add users table")
	alembic revision --autogenerate -m "$(msg)"

migrate-down:  ## Rollback last migration
	alembic downgrade -1

# ── Frontend ─────────────────────────────────────────────────
fe-install:  ## Install frontend dependencies
	cd frontend && npm ci

fe-dev:  ## Start frontend dev server
	cd frontend && npm run dev

fe-build:  ## Build frontend for production
	cd frontend && npm run build

fe-test:  ## Run frontend tests
	cd frontend && npm run test

fe-lint:  ## Lint frontend code
	cd frontend && npm run lint

# ── API Client Generation ────────────────────────────────────
api-export:  ## Export OpenAPI spec from the FastAPI app
	python -m scripts.export_openapi openapi.json

api-generate:  ## Generate TypeScript API client from openapi.json
	cd frontend && npx openapi-ts

api-sync:  ## Export OpenAPI spec and regenerate TypeScript client
	$(MAKE) api-export
	$(MAKE) api-generate

# ── Scaffolding ──────────────────────────────────────────────
new-service:  ## Scaffold a new microservice (usage: make new-service dest=services/my-svc)
	@test -n "$(dest)" || (echo "Usage: make new-service dest=services/my-svc" && exit 1)
	copier copy template/ $(dest)

# ── MCP Server ──────────────────────────────────────────────
mcp:  ## Start MCP server (stdio transport)
	MCP_ENABLED=true MCP_TRANSPORT=stdio nxs-mcp

mcp-http:  ## Start MCP server (HTTP transport on port 8001)
	MCP_ENABLED=true MCP_TRANSPORT=http nxs-mcp

# ── Seed ────────────────────────────────────────────────────
seed:  ## Seed dev database with test user (run locally)
	python -m scripts.seed_dev

seed-docker:  ## Seed dev database via docker compose
	docker compose exec api python -m scripts.seed_dev

# ── Docker ───────────────────────────────────────────────────
build:  ## Build production Docker image
	docker build -t nexus .

# ── Production ───────────────────────────────────────────
prod-up:  ## Start production services
	docker compose -f docker-compose.prod.yml up -d

prod-down:  ## Stop production services
	docker compose -f docker-compose.prod.yml down

prod-logs:  ## Tail production logs
	docker compose -f docker-compose.prod.yml logs -f

prod-deploy:  ## Deploy with build and migrations
	./infra/scripts/deploy.sh --build --migrate

prod-backup:  ## Run manual database backup
	./infra/scripts/backup-db.sh

prod-certbot-init:  ## Get initial TLS cert from Let's Encrypt
	docker compose -f docker-compose.prod.yml run --rm certbot certonly --webroot -w /var/www/certbot -d $${DOMAIN:?Set DOMAIN}

# ── Help ─────────────────────────────────────────────────────
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
