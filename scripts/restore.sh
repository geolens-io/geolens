#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=scripts/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# fix(#1778): read only the four values this script needs from .env with
# get_env_value's awk parser, not by shell-sourcing the file. Compose's own
# `.env` parser and `sh` disagree about the same file: install.sh writes
# values verbatim (an operator-typed admin password can legally contain a
# space), and `.` executes the rest of such a line as a command. Under
# `set -e` that is a 127 exit before this disaster-recovery entry point has
# validated anything; a value containing backticks or $(...) is executed
# with the operator's privileges. Sourcing also pulled in every OTHER secret
# in the file as a side effect, when only these four are ever read below.
if [ -f "$PROJECT_ROOT/.env" ]; then
    COMPOSE_FILE="$(get_env_value COMPOSE_FILE "$PROJECT_ROOT/.env")"
    POSTGRES_USER="$(get_env_value POSTGRES_USER "$PROJECT_ROOT/.env")"
    POSTGRES_DB="$(get_env_value POSTGRES_DB "$PROJECT_ROOT/.env")"
    GEOLENS_RUNTIME_DB_ROLE="$(get_env_value GEOLENS_RUNTIME_DB_ROLE "$PROJECT_ROOT/.env")"
fi
COMPOSE=(docker compose -f "$PROJECT_ROOT/${COMPOSE_FILE:-docker-compose.yml}")

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
# chore(#704): read stdin by OMITTING the filename — the literal "-" alias was
# never documented for pg_restore and PG 18 rejects it as a filename.
#
# `-f /dev/null`, NOT `--list`: the -Fc table of contents sits at the front of
# the archive, so `--list` reports a truncated dump as valid (measured: a
# 60%-truncated dump passes `--list`). That matters more here than anywhere
# else — the restore below runs `--clean --if-exists`, which DROPS the existing
# objects first. Passing a short dump through this gate means dropping a live
# database and then failing partway through repopulating it. `-f /dev/null`
# forces every data block to be read and decompressed. It costs one extra
# stream of the dump into the container (~0.1s per 20 MB of archive), which is
# cheap next to what it prevents.
echo "Validating backup integrity..."
if ! "${COMPOSE[@]}" exec -T db \
    pg_restore -f /dev/null < "$BACKUP_FILE" > /dev/null 2>&1; then
    echo "ERROR: Backup file is corrupt, truncated, or invalid: $BACKUP_FILE" >&2
    echo "pg_restore could not read the archive end-to-end. Aborting restore" >&2
    echo "BEFORE dropping anything — the existing database is untouched." >&2
    exit 1
fi
echo "Backup validation passed (archive read end-to-end)."
echo ""

# Configuration with defaults
POSTGRES_USER="${POSTGRES_USER:-geolens}"
POSTGRES_DB="${POSTGRES_DB:-geolens}"

# Sibling-artifact lookup. Both the object-storage archive and the globals dump
# are written by backup-entrypoint.sh next to the dump with the SAME timestamp,
# so one parse serves both (the staging block near the end of this script reuses
# these). dump name is <db>_<YYYYmmdd_HHMMSS>.dump.
_dump_dir="$(cd "$(dirname "$BACKUP_FILE")" && pwd)"
_dump_base="$(basename "$BACKUP_FILE")"
# Anchored at the END of the name. The old leftmost `grep -oE ... | head -n1`
# matched inside $POSTGRES_DB whenever the database name carried its own
# 8-digit_6-digit run, silently sending every sibling lookup down the
# unpaired-fallback path.
_ts="$(printf '%s' "$_dump_base" | sed -nE 's/^.*_([0-9]{8}_[0-9]{6})(\..*)?$/\1/p' || true)"

# fix(#995): roles are cluster objects and travel in globals-<ts>.sql, never in
# the dump. Report BEFORE the destructive --clean rather than after: replaying
# globals is a pre-restore step, and on a fresh cluster a restore that runs
# without it lands every object owned by the restoring user with no tenant
# grants. Non-fatal — a same-cluster restore (the common case) already has its
# roles, and only the roles the globals dump would actually create are checked.
_globals_dump=""
if [ -n "$_ts" ] && [ -f "${_dump_dir}/globals-${_ts}.sql" ]; then
    _globals_dump="${_dump_dir}/globals-${_ts}.sql"
fi
if [ -n "$_globals_dump" ]; then
    # Unquoted identifiers only: pg_dumpall quotes names that need it, and the
    # GeoLens roles never do. Restricting to [A-Za-z0-9_] also keeps the names
    # safe to inline in the query below.
    _globals_roles="$(grep -oE '^CREATE ROLE [A-Za-z0-9_]+' "$_globals_dump" | awk '{print $3}' | sort -u || true)"
    if [ -n "$_globals_roles" ]; then
        _role_array="$(printf '%s\n' "$_globals_roles" | sed "s/.*/'&'/" | paste -sd, -)"
        _missing_roles="$("${COMPOSE[@]}" exec -T db \
            psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
            "SELECT r FROM unnest(ARRAY[${_role_array}]::text[]) r
             WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r);" \
            2>/dev/null | tr -d '\r' | paste -sd' ' - || true)"
        if [ -n "${_missing_roles// /}" ]; then
            echo "WARNING: this cluster is missing roles that the paired globals dump defines:"
            echo "           ${_missing_roles}"
            echo "         Replay them BEFORE continuing, or restored objects will carry"
            echo "         neither their owners nor their grants (RUNBOOK.md"
            echo "         §\"Multi-tenant role reconstruction after a fresh-cluster restore\"):"
            echo ""
            echo "           docker compose exec -T db psql -U \"\$POSTGRES_USER\" -d postgres \\"
            echo "             < ${_globals_dump}"
            echo ""
        else
            echo "Paired globals dump found (${_globals_dump##*/}); every role it defines already exists."
        fi
    fi
fi

echo "Running pre-restore setup..."

# ON_ERROR_STOP: this DDL is the last gate before --clean drops the live
# database — a silently failed CREATE EXTENSION/SCHEMA here must abort the
# restore, not surface later as a half-restored DB (init-db.sh sets it too).
"${COMPOSE[@]}" exec -T db \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOSQL
-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;

-- Schemas
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS data;

EOSQL

echo "Stopping API to prevent write conflicts during restore..."
"${COMPOSE[@]}" stop api worker 2>/dev/null || true

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
# api/worker are restarted regardless of whether the script exits normally
# or via another `set -e` abort.
#
# fix(#1778): that restart is only correct once the restore AND the mandatory
# grant reconciliation below have both succeeded — RESTORE_SUCCEEDED gates it.
# BUG-022's own trap comment said the restart runs "including on failure",
# but it was never meant to cover the HARD pg_restore error path: there the
# database has already been --clean-dropped and only partly repopulated, no
# ACLs have been re-granted, and starting api/worker on top of it runs their
# boot-time `alembic upgrade heads` against the wreckage — potentially
# stamping revisions onto a half-restored schema. RUNBOOK.md says this
# reconciliation step is mandatory and "start runtime services only after
# that command succeeds"; the same reasoning applies if the reconciliation
# itself fails or its grant is not verified. RESTORE_SUCCEEDED flips to 1
# only after every one of those checks has passed.
RESTORE_SUCCEEDED=0
_cleanup() {
    echo ""
    if [ "$RESTORE_SUCCEEDED" = "1" ]; then
        echo "Restarting services..."
        "${COMPOSE[@]}" start api worker 2>/dev/null || true
    else
        echo "Leaving api/worker STOPPED: the database is in a partially-restored"
        echo "state (pg_restore failed, or the mandatory grant reconciliation below"
        echo "did not complete and verify). Starting the app now would run its"
        echo "boot-time migrations against that wreckage."
        echo "Re-run the restore, or restore a different dump."
    fi
}
trap _cleanup EXIT

echo "Restoring from: $BACKUP_FILE"

# Capture pg_restore stderr for warning vs error analysis; also capture exit code.
RESTORE_STDERR="$(mktemp)"
RESTORE_RC=0
set +e
"${COMPOSE[@]}" exec -T db \
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
        # fix(#1778): RESTORE_SUCCEEDED is still 0 — the _cleanup trap leaves
        # api/worker stopped rather than restarting them onto a half-restored
        # database with no ACLs re-applied.
        exit 1
    else
        echo "pg_restore exited with code ${RESTORE_RC} (warnings only — --clean --if-exists on fresh DB is expected)."
        echo "Warnings:"
        cat "$RESTORE_STDERR"
    fi
fi
rm -f "$RESTORE_STDERR"

# Reconcile runtime ownership/grants AFTER pg_restore, not before: --clean drops
# schema ACLs/default privileges and --no-owner makes POSTGRES_USER own restored
# relations. The privileged db-container script re-grants geolens_reader and,
# when the single-tenant runtime-role opt-in is enabled, transfers only data.*
# runtime relations to the non-superuser login. Catalog ownership stays with the
# migrator; the app receives DML/sequence/function rights there.
echo ""
echo "Re-applying database runtime grants..."
"${COMPOSE[@]}" exec -T db \
    /usr/local/bin/configure-runtime-db-role

# Assert the grant actually took — a restore that leaves the reader role
# without schema access breaks every read-only consumer until someone
# notices, so fail loudly here instead.
READER_USAGE="$("${COMPOSE[@]}" exec -T db \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT has_schema_privilege('geolens_reader', 'data', 'USAGE');" | tr -d '[:space:]')"
if [ "$READER_USAGE" != "t" ]; then
    echo "ERROR: geolens_reader has no USAGE on schema data after restore." >&2
    echo "Re-run the grant block above manually and re-check with:" >&2
    echo "  SELECT has_schema_privilege('geolens_reader', 'data', 'USAGE');" >&2
    exit 1
fi
echo "geolens_reader grants verified."

if [ -n "${GEOLENS_RUNTIME_DB_ROLE:-}" ]; then
    RUNTIME_ROLE_SAFE="$("${COMPOSE[@]}" exec -T db \
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
        "SELECT NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole
                AND NOT rolcreatedb AND NOT rolreplication
         FROM pg_roles WHERE rolname = '${GEOLENS_RUNTIME_DB_ROLE}';" \
        | tr -d '[:space:]')"
    if [ "$RUNTIME_ROLE_SAFE" != "t" ]; then
        echo "ERROR: ${GEOLENS_RUNTIME_DB_ROLE} is absent or privileged after restore." >&2
        exit 1
    fi
    echo "${GEOLENS_RUNTIME_DB_ROLE} least-privilege attributes verified."
fi

# fix(#1778): the mandatory reconciliation step (RUNBOOK.md: "start runtime
# services only after that command succeeds") has now run and every grant it
# makes has been verified — restarting api/worker on exit is safe from here.
RESTORE_SUCCEEDED=1

# Post-restore validation
echo ""
echo "Verifying restore..."
"${COMPOSE[@]}" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "SELECT 'records' AS tbl, COUNT(*) FROM catalog.records UNION ALL SELECT 'datasets', COUNT(*) FROM catalog.datasets;" \
    2>/dev/null || echo "WARNING: Post-restore validation query failed (non-fatal)"

echo ""
echo "Restore complete."

# BKP-01 (Phase 1219): object-storage (upload_staging) is backed up as a
# sibling staging-<timestamp>.tar.gz next to the dump. restore.sh keeps its
# single-arg, DB-focused contract; restoring objects into the upload_staging
# volume requires a one-off container with that volume mounted, so it is a
# documented MANUAL step (see RUNBOOK.md §"full restore (DB + object storage)").
# If we can spot
# the matching archive, point the operator at it rather than silently dropping
# the staged objects.
# _dump_dir / _ts are parsed once before the restore (see the globals block).
_staging_archive=""
_staging_match="exact"
if [ -n "$_ts" ] && [ -f "${_dump_dir}/staging-${_ts}.tar.gz" ]; then
    _staging_archive="${_dump_dir}/staging-${_ts}.tar.gz"
elif ls "${_dump_dir}"/staging-*.tar.gz >/dev/null 2>&1; then
    _staging_archive="$(ls -t "${_dump_dir}"/staging-*.tar.gz 2>/dev/null | head -n1)"
    _staging_match="fallback"
fi
if [ -n "$_staging_archive" ]; then
    echo ""
    if [ "$_staging_match" = "fallback" ]; then
        echo "WARNING: no object-storage archive matches this dump's timestamp (${_ts:-unrecognized})."
        echo "         The NEWEST archive in the directory is listed below, but it was taken"
        echo "         in a DIFFERENT backup cycle and may not pair with this dump:"
    else
        echo "NOTE: a matching object-storage archive was found:"
    fi
    echo "        ${_staging_archive}"
    echo "      The database is restored, but staged source objects are NOT"
    echo "      auto-extracted. To restore them into the upload_staging volume, run"
    echo "      the documented manual step (RUNBOOK.md §\"full restore (DB + object storage)\"):"
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
#   WARNING: a failing archive_command makes PostgreSQL retain WAL until
#   pg_wal fills the filesystem and the database stops accepting writes.
#   Monitor archiver health before enabling this. See RUNBOOK.md section 3.
#
# chore(#704): docs pinned to the bundled major — move with db/Dockerfile.
# See: https://www.postgresql.org/docs/18/continuous-archiving.html
# ==============================================================================
