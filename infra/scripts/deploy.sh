#!/usr/bin/env bash
set -euo pipefail

# Production deployment script
# Usage: ./infra/scripts/deploy.sh [--build] [--migrate]

APP_NAME="saas-platform"
COMPOSE_FILE="docker-compose.prod.yml"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }

# Parse flags
BUILD=false
MIGRATE=false
for arg in "$@"; do
    case $arg in
        --build)   BUILD=true ;;
        --migrate) MIGRATE=true ;;
        *)         echo "Unknown option: $arg"; exit 1 ;;
    esac
done

log "Deploying $APP_NAME..."

if [ "$BUILD" = true ]; then
    log "Building images..."
    docker compose -f "$COMPOSE_FILE" build --no-cache
fi

log "Starting infrastructure services..."
docker compose -f "$COMPOSE_FILE" up -d db redis

log "Waiting for database to be ready..."
docker compose -f "$COMPOSE_FILE" exec -T db sh -c 'until pg_isready -U ${POSTGRES_USER:-app}; do sleep 1; done'

if [ "$MIGRATE" = true ]; then
    log "Running database migrations..."
    docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head
fi

log "Starting application services..."
docker compose -f "$COMPOSE_FILE" up -d api worker nginx

log "Waiting for API health check..."
for i in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T nginx curl -sf http://api:8000/api/v1/health/live > /dev/null 2>&1; then
        log "API is healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        log "ERROR: API failed to become healthy"
        docker compose -f "$COMPOSE_FILE" logs api --tail=50
        exit 1
    fi
    sleep 2
done

log "Deployment complete!"
docker compose -f "$COMPOSE_FILE" ps
