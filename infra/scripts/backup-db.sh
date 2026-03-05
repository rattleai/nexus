#!/usr/bin/env bash
set -euo pipefail

# Database backup script with integrity verification and optional encryption.
# Usage: ./infra/scripts/backup-db.sh [output-dir]
#
# Environment variables:
#   BACKUP_ENCRYPTION_KEY  — If set, backup is encrypted with AES-256-CBC (openssl).
#   DB_USER                — PostgreSQL user (default: app)
#   DB_NAME                — PostgreSQL database (default: app)

COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sql.gz"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

mkdir -p "$BACKUP_DIR"

log "Creating database backup: $BACKUP_FILE"
if ! docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "${DB_USER:-app}" "${DB_NAME:-app}" --no-owner --clean \
    | gzip > "$BACKUP_FILE"; then
    err "Database backup failed"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Verify the backup is non-empty
if [ ! -s "$BACKUP_FILE" ]; then
    err "Backup file is empty"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Generate SHA-256 checksum for integrity verification
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"
log "Checksum written: $CHECKSUM_FILE"

# Optional encryption
if [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    ENCRYPTED_FILE="${BACKUP_FILE}.enc"
    if openssl enc -aes-256-cbc -salt -pbkdf2 -in "$BACKUP_FILE" \
        -out "$ENCRYPTED_FILE" -pass "env:BACKUP_ENCRYPTION_KEY"; then
        # Replace plaintext backup with encrypted version
        rm -f "$BACKUP_FILE"
        BACKUP_FILE="$ENCRYPTED_FILE"
        # Update checksum for encrypted file
        sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"
        log "Backup encrypted: $BACKUP_FILE"
    else
        err "Encryption failed — keeping unencrypted backup"
    fi
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "Backup complete: $BACKUP_FILE ($SIZE)"

# Prune backups older than 30 days
PRUNED=$(find "$BACKUP_DIR" -name "db_backup_*" -mtime +30 -print -delete 2>/dev/null | wc -l)
if [ "$PRUNED" -gt 0 ]; then
    log "Pruned $PRUNED old backup file(s) (30 day retention)"
fi
