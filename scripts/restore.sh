#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Argument validation
if [ $# -ne 1 ]; then
    echo "Usage: $0 <backup-file>" >&2
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

# Validate backup integrity before restore
echo "Validating backup integrity..."
if ! docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    pg_restore --list - < "$BACKUP_FILE" > /dev/null 2>&1; then
    echo "ERROR: Backup file is corrupt or invalid: $BACKUP_FILE" >&2
    echo "pg_restore --list validation failed. Aborting restore." >&2
    exit 1
fi
echo "Backup validation passed."
echo ""

# Source .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration with defaults
POSTGRES_USER="${POSTGRES_USER:-geolens}"
POSTGRES_DB="${POSTGRES_DB:-geolens}"
echo "Running pre-restore setup..."

docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOSQL
-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;

-- Schemas
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS data;

-- Read-only role for data schema access
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN
        CREATE ROLE geolens_reader NOLOGIN;
    END IF;
END
\$\$;
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;

EOSQL

echo "Stopping API to prevent write conflicts during restore..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" stop api worker 2>/dev/null || true

# BUG-022 (Phase 1184): ensure api/worker are always restarted, even on failure.
# pg_restore --clean --if-exists exits nonzero on EXPECTED warnings (e.g. "object
# does not exist" when dropping objects absent from a fresh DB). Under `set -e`
# that nonzero exit aborted the script, leaving api/worker stopped and skipping
# post-restore validation.
#
# Fix strategy:
#   1. A trap on EXIT restarts api/worker on every exit path (normal + error).
#   2. pg_restore is run with `|| RESTORE_RC=$?` (disabling -e for that call)
#      so we can inspect its exit code manually.
#   3. pg_restore exit code handling:
#      - 0            → success
#      - nonzero with ONLY warning lines (no "ERROR:" lines in stderr) → treat as
#        success (expected warnings from --clean --if-exists on a fresh DB)
#      - nonzero with real ERROR lines in stderr → hard failure, abort
#
# The trap fires before the EXIT signal is delivered to the shell, so
# api/worker are restarted regardless of whether the script exits normally,
# via `exit 1` (hard pg_restore error), or via another `set -e` abort.
_cleanup() {
    echo ""
    echo "Restarting services..."
    docker compose -f "$PROJECT_ROOT/docker-compose.yml" start api worker 2>/dev/null || true
}
trap _cleanup EXIT

echo "Restoring from: $BACKUP_FILE"

# Capture pg_restore stderr for warning vs error analysis; also capture exit code.
RESTORE_STDERR="$(mktemp)"
RESTORE_RC=0
set +e
docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner \
    < "$BACKUP_FILE" 2>"$RESTORE_STDERR"
RESTORE_RC=$?
set -e

if [ "$RESTORE_RC" -ne 0 ]; then
    # Distinguish expected warnings (nonzero due to --clean on a fresh DB) from
    # hard errors. pg_restore prefixes hard errors with "pg_restore: error:" or
    # "ERROR:" (the latter from psql-layer output forwarded through pg_restore).
    if grep -qi "error:" "$RESTORE_STDERR" 2>/dev/null; then
        echo "" >&2
        echo "ERROR: pg_restore failed (exit code ${RESTORE_RC}). Stderr:" >&2
        cat "$RESTORE_STDERR" >&2
        rm -f "$RESTORE_STDERR"
        # _cleanup trap will restart api/worker before exit
        exit 1
    else
        echo "pg_restore exited with code ${RESTORE_RC} (warnings only — --clean --if-exists on fresh DB is expected)."
        echo "Warnings:"
        cat "$RESTORE_STDERR"
    fi
fi
rm -f "$RESTORE_STDERR"

# Post-restore validation
echo ""
echo "Verifying restore..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "SELECT 'records' AS tbl, COUNT(*) FROM catalog.records UNION ALL SELECT 'datasets', COUNT(*) FROM catalog.datasets;" \
    2>/dev/null || echo "WARNING: Post-restore validation query failed (non-fatal)"

echo ""
echo "Restore complete."

# BKP-01 (Phase 1219): object-storage (upload_staging) is backed up as a
# sibling staging-<timestamp>.tar.gz next to the dump. restore.sh keeps its
# single-arg, DB-focused contract; restoring objects into the upload_staging
# volume requires a one-off container with that volume mounted, so it is a
# documented MANUAL step (see UPGRADING.md §"Disaster recovery"). If we can spot
# the matching archive, point the operator at it rather than silently dropping
# the staged objects.
_dump_dir="$(cd "$(dirname "$BACKUP_FILE")" && pwd)"
_dump_base="$(basename "$BACKUP_FILE")"
# dump name is <db>_<YYYYmmdd_HHMMSS>.dump → extract the timestamp if present.
_ts="$(printf '%s' "$_dump_base" | grep -oE '[0-9]{8}_[0-9]{6}' | head -n1 || true)"
_staging_archive=""
if [ -n "$_ts" ] && [ -f "${_dump_dir}/staging-${_ts}.tar.gz" ]; then
    _staging_archive="${_dump_dir}/staging-${_ts}.tar.gz"
elif ls "${_dump_dir}"/staging-*.tar.gz >/dev/null 2>&1; then
    _staging_archive="$(ls -t "${_dump_dir}"/staging-*.tar.gz 2>/dev/null | head -n1)"
fi
if [ -n "$_staging_archive" ]; then
    echo ""
    echo "NOTE: a matching object-storage archive was found:"
    echo "        ${_staging_archive}"
    echo "      The database is restored, but staged source objects are NOT"
    echo "      auto-extracted. To restore them into the upload_staging volume, run"
    echo "      the documented manual step (UPGRADING.md §\"Disaster recovery\"):"
    echo ""
    echo "        docker run --rm \\"
    echo "          -v <project>_upload_staging:/staging \\"
    echo "          -v \"${_dump_dir}\":/restore:ro \\"
    echo "          alpine sh -c 'cd /staging && tar xzf /restore/$(basename "$_staging_archive")'"
    echo ""
fi
# _cleanup trap restarts api/worker on exit (runs here too — normal exit).

# ==============================================================================
# WAL Archiving (Optional PITR Upgrade)
# ==============================================================================
#
# For point-in-time recovery (PITR), WAL archiving enables restoring the
# database to any moment between backups. This is NOT configured by default.
#
# MANAGED DATABASES (recommended):
#   AWS RDS, Google Cloud SQL, and Azure Database for PostgreSQL provide
#   native automated backups with PITR. Enable via the provider's console:
#   - AWS RDS: Modify instance -> Backup -> Enable automated backups
#   - Cloud SQL: Edit instance -> Backups -> Enable PITR
#   - Azure: Server -> Backup -> Configure retention
#   No application changes required.
#
# SELF-HOSTED DOCKER (advanced):
#   Requires postgresql.conf modifications in the db container:
#     wal_level = replica
#     archive_mode = on
#     archive_command = 'test ! -f /wal_archive/%f && cp %p /wal_archive/%f'
#   Plus a volume mount for /wal_archive and a separate WAL shipping process.
#   Consider pgBackRest for production WAL management.
#
# See: https://www.postgresql.org/docs/17/continuous-archiving.html
# ==============================================================================
