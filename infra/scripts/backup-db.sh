#!/usr/bin/env bash
set -euo pipefail

# Database backup script
# Usage: ./infra/scripts/backup-db.sh [output-dir]

COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating database backup: $BACKUP_FILE"
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "${DB_USER:-app}" "${DB_NAME:-app}" --no-owner --clean \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: $BACKUP_FILE ($SIZE)"

# Prune backups older than 30 days
find "$BACKUP_DIR" -name "db_backup_*.sql.gz" -mtime +30 -delete 2>/dev/null || true
echo "Old backups pruned (30 day retention)"
