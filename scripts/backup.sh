#!/usr/bin/env bash
set -euo pipefail

# Configuration from environment (set by docker-compose)
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_USER="${POSTGRES_USER:-geolens}"
POSTGRES_DB="${POSTGRES_DB:-geolens}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAILY="${BACKUP_RETENTION_DAILY:-7}"
BACKUP_RETENTION_WEEKLY="${BACKUP_RETENTION_WEEKLY:-4}"
BACKUP_S3_ENABLED="${BACKUP_S3_ENABLED:-false}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.dump"

echo "[$(date -Iseconds)] Starting backup of database '$POSTGRES_DB'..."

# pg_dump via network connection to db service
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "$POSTGRES_HOST" \
    -U "$POSTGRES_USER" \
    -Fc "$POSTGRES_DB" > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date -Iseconds)] Backup created: $(basename "$BACKUP_FILE") ($SIZE)"

# Validate backup integrity
if ! pg_restore --list "$BACKUP_FILE" > /dev/null 2>&1; then
    echo "[$(date -Iseconds)] ERROR: Backup validation failed!" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi
echo "[$(date -Iseconds)] Backup validation passed."

# S3 upload (if enabled)
if [ "$BACKUP_S3_ENABLED" = "true" ]; then
    echo "[$(date -Iseconds)] Uploading to S3..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/backup-s3-upload.py" "$BACKUP_FILE"
    echo "[$(date -Iseconds)] S3 upload complete."

    # S3 retention cleanup
    python3 "$SCRIPT_DIR/backup-s3-retention.py"
fi

# Local retention (count-based: keep N daily + M weekly)
# Weekly = backups created on Sunday (day-of-week 0 per date +%w)
cleanup_local_backups() {
    local all_backups daily weekly
    # List all backup files sorted newest-first by filename (timestamp in name)
    mapfile -t all_backups < <(ls -1r "${BACKUP_DIR}/${POSTGRES_DB}_"*.dump 2>/dev/null)

    if [ ${#all_backups[@]} -eq 0 ]; then
        return
    fi

    daily=()
    weekly=()
    for f in "${all_backups[@]}"; do
        # Extract date from filename: geolens_20260302_020000.dump -> 20260302
        local ts
        ts=$(basename "$f" | sed "s/${POSTGRES_DB}_//" | sed 's/_.*//')
        # Get day of week (0=Sunday on Linux with GNU date)
        local dow
        dow=$(date -d "${ts:0:4}-${ts:4:2}-${ts:6:2}" +%w 2>/dev/null || echo "")
        if [ "$dow" = "0" ]; then
            weekly+=("$f")
        else
            daily+=("$f")
        fi
    done

    # Delete excess daily backups (keep newest N)
    local i
    for (( i=BACKUP_RETENTION_DAILY; i<${#daily[@]}; i++ )); do
        rm -f "${daily[$i]}"
        echo "[$(date -Iseconds)] Deleted daily backup: $(basename "${daily[$i]}")"
    done

    # Delete excess weekly backups (keep newest M)
    for (( i=BACKUP_RETENTION_WEEKLY; i<${#weekly[@]}; i++ )); do
        rm -f "${weekly[$i]}"
        echo "[$(date -Iseconds)] Deleted weekly backup: $(basename "${weekly[$i]}")"
    done
}

cleanup_local_backups

echo "[$(date -Iseconds)] Backup job finished."
