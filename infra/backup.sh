#!/bin/bash
# PostgreSQL backup script for DENT
# Usage: ./infra/backup.sh [compose-file]
# Cron: 0 3 * * * cd /opt/dent && ./infra/backup.sh docker-compose.server.yml >> /var/log/dent-backup.log 2>&1

set -euo pipefail

COMPOSE_FILE="${1:-docker-compose.server.yml}"
BACKUP_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/dent_db_${TIMESTAMP}.sql.gz"
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting PostgreSQL backup..."

docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U dent --no-owner --no-privileges dent \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"

# Cleanup old backups
DELETED=$(find "$BACKUP_DIR" -name "dent_db_*.sql.gz" -mtime +${KEEP_DAYS} -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] Cleaned up $DELETED old backups (>${KEEP_DAYS} days)"
fi
