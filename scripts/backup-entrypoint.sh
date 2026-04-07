#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GeoLens Automated Backup Entrypoint
# ==============================================================================
# Runs pg_dump on a cron schedule with daily/weekly retention and optional
# S3 upload. Designed for the Docker Compose backup profile service.
#
# Environment variables (set in docker-compose.yml):
#   POSTGRES_USER          Database username
#   POSTGRES_PASSWORD      Database password
#   POSTGRES_DB            Database name (default: geolens)
#   POSTGRES_HOST          Database hostname (default: db)
#   BACKUP_SCHEDULE        Cron expression (default: "0 2 * * *")
#   BACKUP_RETENTION_DAILY Number of daily backups to keep (default: 7)
#   BACKUP_RETENTION_WEEKLY Number of weekly backups to keep (default: 4)
#   BACKUP_S3_ENABLED      Upload to S3 (default: false)
#   S3_ENDPOINT            S3/MinIO endpoint URL
#   S3_BUCKET              S3 bucket name
#   S3_ACCESS_KEY_ID       S3 access key
#   S3_SECRET_ACCESS_KEY   S3 secret key
#   S3_REGION              S3 region (default: us-east-1)
#   S3_ALLOW_HTTP          Allow HTTP for S3 (default: false)
# ==============================================================================

BACKUP_DIR="/backups"
DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

POSTGRES_DB="${POSTGRES_DB:-geolens}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
BACKUP_RETENTION_DAILY="${BACKUP_RETENTION_DAILY:-7}"
BACKUP_RETENTION_WEEKLY="${BACKUP_RETENTION_WEEKLY:-4}"
BACKUP_S3_ENABLED="${BACKUP_S3_ENABLED:-false}"
S3_REGION="${S3_REGION:-us-east-1}"
S3_ALLOW_HTTP="${S3_ALLOW_HTTP:-false}"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ---------------------------------------------------------------------------
# pg_dump
# ---------------------------------------------------------------------------
run_backup() {
    local timestamp
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    local filename="${POSTGRES_DB}_${timestamp}.dump"
    local filepath="${DAILY_DIR}/${filename}"

    log "Starting backup: ${filename}"

    export PGPASSWORD="${POSTGRES_PASSWORD}"
    if pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -Fc --no-owner --no-acl -f "$filepath"; then
        local size
        size="$(du -h "$filepath" | cut -f1)"
        log "Backup complete: ${filename} (${size})"
    else
        log "ERROR: pg_dump failed"
        rm -f "$filepath"
        return 1
    fi

    # Weekly copy on Sundays
    if [ "$(date '+%u')" = "7" ]; then
        cp "$filepath" "${WEEKLY_DIR}/${filename}"
        log "Weekly copy saved: ${filename}"
    fi

    # S3 upload
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        upload_to_s3 "$filepath" "daily/${filename}"
        if [ "$(date '+%u')" = "7" ]; then
            upload_to_s3 "$filepath" "weekly/${filename}"
        fi
    fi

    # Retention
    prune_old_backups "$DAILY_DIR" "$BACKUP_RETENTION_DAILY"
    prune_old_backups "$WEEKLY_DIR" "$BACKUP_RETENTION_WEEKLY"

    log "Backup cycle complete"
}

# ---------------------------------------------------------------------------
# S3 upload (uses pg_dump image's curl — no aws cli dependency)
# ---------------------------------------------------------------------------
upload_to_s3() {
    local filepath="$1"
    local s3_key="$2"

    if [ -z "${S3_BUCKET:-}" ] || [ -z "${S3_ACCESS_KEY_ID:-}" ] || [ -z "${S3_SECRET_ACCESS_KEY:-}" ]; then
        log "WARNING: S3 upload enabled but credentials missing — skipping"
        return 0
    fi

    local protocol="https"
    if [ "$S3_ALLOW_HTTP" = "true" ]; then
        protocol="http"
    fi

    local endpoint="${S3_ENDPOINT:-https://s3.${S3_REGION}.amazonaws.com}"
    local date_value
    date_value="$(date -R)"
    local content_type="application/octet-stream"
    local resource="/${S3_BUCKET}/backups/${s3_key}"
    local string_to_sign="PUT\n\n${content_type}\n${date_value}\n${resource}"
    local signature
    signature="$(printf '%s' "$string_to_sign" | openssl dgst -sha1 -hmac "$S3_SECRET_ACCESS_KEY" -binary | base64)"

    local url="${endpoint}/${S3_BUCKET}/backups/${s3_key}"

    log "Uploading to S3: ${s3_key}"
    if curl -sf -X PUT -T "$filepath" \
        -H "Date: ${date_value}" \
        -H "Content-Type: ${content_type}" \
        -H "Authorization: AWS ${S3_ACCESS_KEY_ID}:${signature}" \
        "$url"; then
        log "S3 upload complete: ${s3_key}"
    else
        log "WARNING: S3 upload failed for ${s3_key} (non-fatal)"
    fi
}

# ---------------------------------------------------------------------------
# Retention pruning
# ---------------------------------------------------------------------------
prune_old_backups() {
    local dir="$1"
    local keep="$2"

    local count
    count="$(find "$dir" -name "*.dump" -type f | wc -l)"
    if [ "$count" -gt "$keep" ]; then
        local to_remove=$((count - keep))
        log "Pruning ${to_remove} old backup(s) from ${dir}"
        find "$dir" -name "*.dump" -type f -printf '%T+ %p\n' | \
            sort | head -n "$to_remove" | awk '{print $2}' | \
            xargs rm -f
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
CRON_EXPR="${BACKUP_SCHEDULE:-0 2 * * *}"

# Cron re-entry: called with --run-backup by cron job — execute and exit
if [ "${1:-}" = "--run-backup" ]; then
    run_backup
    exit $?
fi

# First-run entry point
log "GeoLens backup service starting"
log "Schedule: ${CRON_EXPR}"
log "Retention: ${BACKUP_RETENTION_DAILY} daily, ${BACKUP_RETENTION_WEEKLY} weekly"
log "S3 upload: ${BACKUP_S3_ENABLED}"

# Run an initial backup on startup
run_backup || log "WARNING: Initial backup failed"

# Try cron daemon first, fall back to sleep loop
if command -v crontab >/dev/null 2>&1; then
    CRON_LINE="${CRON_EXPR} /scripts/backup-entrypoint.sh --run-backup >> /var/log/backup.log 2>&1"
    echo "$CRON_LINE" | crontab -
    log "Cron installed, entering foreground"
    exec crond -f -l 2 2>/dev/null || exec cron -f
fi

# Fallback: sleep loop with schedule check (no cron available)
log "No cron daemon — using sleep-loop scheduler"
sched_min="$(echo "$CRON_EXPR" | awk '{print $1}')"
sched_hour="$(echo "$CRON_EXPR" | awk '{print $2}')"

while true; do
    sleep 60
    current_hour="$(date '+%-H')"
    current_min="$(date '+%-M')"
    if [ "$current_hour" = "$sched_hour" ] && [ "$current_min" = "$sched_min" ]; then
        run_backup || log "WARNING: Scheduled backup failed"
        sleep 60  # Avoid double-trigger within the same minute
    fi
done
