#!/usr/bin/env bash
set -euo pipefail

# Production deployment script
# Usage: ./infra/scripts/deploy.sh [--build] [--migrate] [--skip-backup]

APP_NAME="saas-platform"
COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="./backups"
HEALTH_CHECK_TIMEOUT=60  # seconds
HEALTH_CHECK_INTERVAL=2  # seconds

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

# Parse flags
BUILD=false
MIGRATE=false
SKIP_BACKUP=false
for arg in "$@"; do
    case $arg in
        --build)       BUILD=true ;;
        --migrate)     MIGRATE=true ;;
        --skip-backup) SKIP_BACKUP=true ;;
        *)             echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# Track pre-migration alembic revision for rollback
PRE_MIGRATE_REVISION=""

# Rollback function — restore previous state on failure
rollback() {
    # Prevent double-rollback from trap + explicit call
    trap - ERR
    err "Deployment failed. Initiating rollback..."
    docker compose -f "$COMPOSE_FILE" logs api --tail=100
    docker compose -f "$COMPOSE_FILE" logs worker --tail=50

    # Roll back database migration if we recorded a previous revision
    if [ -n "$PRE_MIGRATE_REVISION" ]; then
        log "Rolling back database migration to revision $PRE_MIGRATE_REVISION..."
        docker compose -f "$COMPOSE_FILE" run --rm api alembic downgrade "$PRE_MIGRATE_REVISION" || \
            err "Migration rollback failed — manual intervention may be required"
    fi

    # Restart previous containers (docker compose keeps previous image)
    log "Restarting previous service versions..."
    if ! docker compose -f "$COMPOSE_FILE" up -d api worker beat nginx; then
        err "Rollback also failed! Services may be in a broken state."
        err "Manual intervention required: check 'docker compose -f $COMPOSE_FILE ps'"
    fi
    err "Rollback attempted. Please verify service state manually."
    exit 1
}

trap rollback ERR

log "Deploying $APP_NAME..."

if [ "$BUILD" = true ]; then
    log "Building images..."
    docker compose -f "$COMPOSE_FILE" build
fi

log "Starting infrastructure services..."
docker compose -f "$COMPOSE_FILE" up -d db redis

log "Waiting for database to be ready..."
docker compose -f "$COMPOSE_FILE" exec -T db sh -c 'until pg_isready -U ${POSTGRES_USER:-app}; do sleep 1; done'

# Pre-migration backup
if [ "$MIGRATE" = true ] && [ "$SKIP_BACKUP" = false ]; then
    log "Creating pre-migration database backup..."
    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/pre_deploy_$(date +'%Y%m%d_%H%M%S').sql.gz"
    if docker compose -f "$COMPOSE_FILE" exec -T db \
        pg_dump -U "${DB_USER:-app}" "${DB_NAME:-app}" --no-owner --clean \
        | gzip > "$BACKUP_FILE"; then
        log "Backup created: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
    else
        err "Backup failed! Aborting deployment. Use --skip-backup to override."
        rm -f "$BACKUP_FILE"
        exit 1
    fi
fi

if [ "$MIGRATE" = true ]; then
    log "Recording current migration revision for rollback..."
    PRE_MIGRATE_REVISION=$(docker compose -f "$COMPOSE_FILE" run --rm api alembic current 2>/dev/null | grep -oE '[a-f0-9]+' | head -1 || echo "")
    log "Pre-migration revision: ${PRE_MIGRATE_REVISION:-none}"
    log "Running database migrations..."
    docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head
fi

log "Starting application services..."
docker compose -f "$COMPOSE_FILE" up -d api worker beat nginx

log "Waiting for API health check (timeout: ${HEALTH_CHECK_TIMEOUT}s)..."
max_attempts=$((HEALTH_CHECK_TIMEOUT / HEALTH_CHECK_INTERVAL))
for i in $(seq 1 "$max_attempts"); do
    if docker compose -f "$COMPOSE_FILE" exec -T api curl -sf http://localhost:8000/api/v1/health/live > /dev/null 2>&1; then
        log "API is healthy!"
        break
    fi
    if [ "$i" -eq "$max_attempts" ]; then
        err "API failed to become healthy within ${HEALTH_CHECK_TIMEOUT}s"
        rollback
    fi
    sleep "$HEALTH_CHECK_INTERVAL"
done

trap - ERR
log "Deployment complete!"
docker compose -f "$COMPOSE_FILE" ps
