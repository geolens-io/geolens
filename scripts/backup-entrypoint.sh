#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GeoLens Automated Backup Entrypoint
# ==============================================================================
# Runs pg_dump on a cron schedule with daily/weekly retention and optional
# S3 upload. Designed for the default-on Docker Compose backup service.
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
#   S3_ADDRESSING_STYLE    S3 addressing style: auto, path, virtual (default: auto)
# ==============================================================================

BACKUP_DIR="/backups"
DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

# BKP-01 (Phase 1219): the upload_staging volume is mounted read-only at
# /staging. Each backup cycle tars it alongside the pg_dump so a restore can
# reproduce a WORKING instance (DB rows + the staged source objects). Override
# the mount point if the compose file changes it.
STAGING_DIR="${STAGING_DIR:-/staging}"

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

    # BKP-01: archive the object-storage staging volume alongside the dump.
    # Named with the SAME timestamp as the dump so restore can pair them.
    local staging_archive=""
    staging_archive="$(backup_staging "$timestamp")"

    # S3 upload — record any failure but DON'T return yet. The local dump (and
    # the staging archive, if any) already landed on disk; retention pruning
    # below must still run so a transient S3 outage can't let them accumulate.
    local cycle_failed=0
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        local upload_failed=0
        upload_to_s3 "$filepath" "daily/${filename}" || upload_failed=1
        if [ -n "$staging_archive" ]; then
            upload_to_s3 "$staging_archive" "daily/$(basename "$staging_archive")" || upload_failed=1
        fi
        if [ "$(date '+%u')" = "7" ]; then
            upload_to_s3 "$filepath" "weekly/${filename}" || upload_failed=1
            if [ -n "$staging_archive" ]; then
                upload_to_s3 "$staging_archive" "weekly/$(basename "$staging_archive")" || upload_failed=1
            fi
        fi
        if [ "$upload_failed" -eq 1 ]; then
            log "ERROR: backup S3 upload failed — check S3 credentials and endpoint reachability"
            cycle_failed=1
        fi
    fi

    # Retention runs regardless of S3 outcome (dumps and their paired staging
    # archives share retention counts) — local backups must be pruned even when
    # the offsite upload failed, or backup_data fills up during an S3 outage.
    prune_old_backups "$DAILY_DIR" "$BACKUP_RETENTION_DAILY"
    prune_old_backups "$WEEKLY_DIR" "$BACKUP_RETENTION_WEEKLY"
    prune_old_staging "$DAILY_DIR" "$BACKUP_RETENTION_DAILY"
    prune_old_staging "$WEEKLY_DIR" "$BACKUP_RETENTION_WEEKLY"

    # Surface the S3 failure now that retention has run, so the cycle is still
    # reported as failed (non-zero) to the cron / sleep-loop caller.
    if [ "$cycle_failed" -eq 1 ]; then
        return 1
    fi

    log "Backup cycle complete"
}

# ---------------------------------------------------------------------------
# BKP-01: object-storage (upload_staging) archive
# ---------------------------------------------------------------------------
# Tars the read-only /staging mount into staging-<timestamp>.tar.gz next to the
# dump. Prints the archive path on stdout (consumed by run_backup); all human
# logging goes to stderr so it never contaminates that path. Skips cleanly when
# the staging mount is absent or empty so a fresh install (no uploads yet) still
# produces a valid DB-only backup cycle.
backup_staging() {
    local timestamp="$1"
    local archive="${DAILY_DIR}/staging-${timestamp}.tar.gz"

    if [ ! -d "$STAGING_DIR" ]; then
        log "Staging dir ${STAGING_DIR} not mounted — skipping object-storage archive" >&2
        return 0
    fi
    if [ -z "$(find "$STAGING_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]; then
        log "Staging dir ${STAGING_DIR} is empty — skipping object-storage archive" >&2
        return 0
    fi

    log "Archiving object storage: $(basename "$archive")" >&2
    if tar czf "$archive" -C "$STAGING_DIR" . 2>/dev/null; then
        local size
        size="$(du -h "$archive" | cut -f1)"
        log "Object-storage archive complete: $(basename "$archive") (${size})" >&2
        if [ "$(date '+%u')" = "7" ]; then
            cp "$archive" "${WEEKLY_DIR}/$(basename "$archive")"
            log "Weekly object-storage copy saved: $(basename "$archive")" >&2
        fi
        printf '%s\n' "$archive"
    else
        log "WARNING: object-storage archive failed — staging backup skipped" >&2
        rm -f "$archive"
    fi
}

# ---------------------------------------------------------------------------
# S3 upload via awscli with AWS Signature V4
#
# Uses SigV4 — the only signature version accepted by Cloudflare R2 and
# required by modern AWS S3 (and MinIO). Credentials are passed through the
# environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) — never on argv,
# which would expose secrets in the process list. The endpoint, region, and
# addressing style are read from S3_ENDPOINT, S3_REGION, and
# S3_ADDRESSING_STYLE respectively. A failed upload returns non-zero and logs
# an ERROR so silent offsite backup loss is detectable in container logs.
# ---------------------------------------------------------------------------
upload_to_s3() {
    local filepath="$1"
    local s3_key="$2"

    if [ -z "${S3_BUCKET:-}" ] || [ -z "${S3_ACCESS_KEY_ID:-}" ] || [ -z "${S3_SECRET_ACCESS_KEY:-}" ]; then
        log "WARNING: S3 upload enabled but credentials missing — skipping"
        return 0
    fi

    # Pass credentials via environment — not on argv (prevents secret leakage
    # in the process list and shell history).
    export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
    export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"
    export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"

    # Force SigV4 and configure addressing style (use 'path' for MinIO/R2 when needed).
    aws configure set default.s3.signature_version s3v4
    aws configure set default.s3.addressing_style "${S3_ADDRESSING_STYLE:-auto}"

    # Build argument list; --endpoint-url is only added when S3_ENDPOINT is set.
    local aws_args=()
    if [ -n "${S3_ENDPOINT:-}" ]; then
        aws_args+=(--endpoint-url "$S3_ENDPOINT")
    fi
    aws_args+=(--region "${S3_REGION:-us-east-1}" --no-progress)

    log "Uploading to S3: ${s3_key}"
    if aws s3 cp "$filepath" "s3://${S3_BUCKET}/backups/${s3_key}" "${aws_args[@]}"; then
        log "S3 upload complete: ${s3_key}"
    else
        log "ERROR: S3 upload failed for ${s3_key}"
        return 1
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

# BKP-01: prune object-storage archives with the same retention policy as dumps.
prune_old_staging() {
    local dir="$1"
    local keep="$2"

    local count
    count="$(find "$dir" -name "staging-*.tar.gz" -type f | wc -l)"
    if [ "$count" -gt "$keep" ]; then
        local to_remove=$((count - keep))
        log "Pruning ${to_remove} old object-storage archive(s) from ${dir}"
        find "$dir" -name "staging-*.tar.gz" -type f -printf '%T+ %p\n' | \
            sort | head -n "$to_remove" | awk '{print $2}' | \
            xargs rm -f
    fi
}

# ---------------------------------------------------------------------------
# GAP-005 (Phase 1184): BACKUP_SCHEDULE validation
# ---------------------------------------------------------------------------
# The sleep-loop fallback scheduler (used when no cron daemon is available)
# only supports expressions of the form "M H * * *" (a literal minute + hour,
# with all three remaining fields set to *). Any other form silently never
# fires — the comparison `[ "$current_min" = "*/15" ]` never matches.
#
# Validation approach: FAIL FAST at startup if BACKUP_SCHEDULE uses a form the
# simple scheduler cannot honour. If crond/cron is available the expression is
# passed through to the system cron, which handles the full 5-field syntax —
# but we still validate so that a misconfigured schedule surfacing on a crond
# host does not silently break when run on an image without crond.
#
# Supported: M H * * *   where M is 0-59 and H is 0-23 (literal integers)
# Unsupported: */N steps, ranges, lists, or non-* dom/month/dow fields.
validate_cron_expr() {
    local expr="$1"

    # Split into exactly 5 fields
    field_count="$(echo "$expr" | awk '{print NF}')"
    if [ "$field_count" -ne 5 ]; then
        log "ERROR: BACKUP_SCHEDULE must have exactly 5 fields (got ${field_count}): '${expr}'" >&2
        log "Supported format: 'M H * * *'  (e.g. '0 2 * * *' for 02:00 daily)" >&2
        exit 1
    fi

    f_min="$(echo "$expr" | awk '{print $1}')"
    f_hour="$(echo "$expr" | awk '{print $2}')"
    f_dom="$(echo "$expr" | awk '{print $3}')"
    f_month="$(echo "$expr" | awk '{print $4}')"
    f_dow="$(echo "$expr" | awk '{print $5}')"

    # Validate: minute must be a plain integer 0-59
    case "$f_min" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' is not a plain integer." >&2
            log "The built-in sleep-loop scheduler only supports literal 'M H * * *'." >&2
            log "Examples: '0 2 * * *' (02:00), '30 6 * * *' (06:30)" >&2
            log "To use step/range expressions, ensure crond is available in the container." >&2
            exit 1
            ;;
    esac
    if [ "$f_min" -lt 0 ] || [ "$f_min" -gt 59 ]; then
        log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' out of range 0-59." >&2
        exit 1
    fi

    # Validate: hour must be a plain integer 0-23
    case "$f_hour" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' is not a plain integer." >&2
            log "The built-in sleep-loop scheduler only supports literal 'M H * * *'." >&2
            exit 1
            ;;
    esac
    if [ "$f_hour" -lt 0 ] || [ "$f_hour" -gt 23 ]; then
        log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' out of range 0-23." >&2
        exit 1
    fi

    # Validate: dom, month, dow must all be '*'
    if [ "$f_dom" != "*" ] || [ "$f_month" != "*" ] || [ "$f_dow" != "*" ]; then
        log "ERROR: BACKUP_SCHEDULE fields 3-5 must all be '*' for the built-in scheduler." >&2
        log "Got: dom='${f_dom}' month='${f_month}' dow='${f_dow}'" >&2
        log "The sleep-loop scheduler only fires once per day at a fixed hour:minute." >&2
        log "To use day-of-week or monthly schedules, ensure crond is available." >&2
        exit 1
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

# GAP-005: validate the schedule expression before doing anything else so
# an unsupported expression fails loudly instead of silently never firing.
validate_cron_expr "$CRON_EXPR"

# First-run entry point
log "GeoLens backup service starting"
log "Schedule: ${CRON_EXPR}"
log "Retention: ${BACKUP_RETENTION_DAILY} daily, ${BACKUP_RETENTION_WEEKLY} weekly"
log "S3 upload: ${BACKUP_S3_ENABLED}"

# Run an initial backup on startup
run_backup || log "ERROR: Initial backup failed"

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
        run_backup || log "ERROR: Scheduled backup failed"
        sleep 60  # Avoid double-trigger within the same minute
    fi
done
