.PHONY: dev dev-up dev-down test lint format migrate seed build

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

# ── Docker ───────────────────────────────────────────────────
build:  ## Build production Docker image
	docker build -t saas-platform .

# ── Help ─────────────────────────────────────────────────────
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
