#!/usr/bin/env bash
# ==============================================================================
# BKP-04 (Phase 1219): backup + restore round-trip test (LOCAL proof)
# ==============================================================================
# Proves the canonical backup/restore path actually reproduces the data:
#
#   1. DB round-trip — create a throwaway source DB with known rows, pg_dump -Fc
#      it, restore into a SECOND throwaway DB using the SAME pg_restore flags
#      scripts/restore.sh uses (--clean --if-exists --no-owner), then assert the
#      restored row counts match the source EXACTLY.
#   2. Object-storage round-trip — tar a staging dir (as backup-entrypoint.sh
#      does), extract it elsewhere, assert the file tree + contents survive.
#
# Both THROWAWAY databases are ALWAYS dropped on exit (trap), success or fail.
# This connects to the already-running test Postgres (localhost:5434 via
# .env.test) and never touches the real app databases. It does NOT spin up a
# stack and is safe to run standalone:
#
#   bash scripts/tests/test-backup-restore-roundtrip.sh
#
# The full S3/MinIO offset path (pg_dump → S3 → download → restore) runs in CI
# (see the backup-roundtrip job in .github/workflows/ci.yml); it is CI-on-push.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- Load test DB connection (.env.test → localhost:5434) ---------------------
# Pre-set POSTGRES_* env vars take precedence (CI points these at its own
# Postgres service); .env.test only fills gaps for a plain local run. We capture
# any pre-set values, source .env.test, then restore the pre-set ones.
_pre_host="${POSTGRES_HOST:-}"; _pre_port="${POSTGRES_PORT:-}"
_pre_user="${POSTGRES_USER:-}"; _pre_pass="${POSTGRES_PASSWORD:-}"; _pre_db="${POSTGRES_DB:-}"
ENV_TEST="${REPO_ROOT}/.env.test"
if [ -f "$ENV_TEST" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$ENV_TEST"
    set +a
fi
[ -n "$_pre_host" ] && POSTGRES_HOST="$_pre_host"
[ -n "$_pre_port" ] && POSTGRES_PORT="$_pre_port"
[ -n "$_pre_user" ] && POSTGRES_USER="$_pre_user"
[ -n "$_pre_pass" ] && POSTGRES_PASSWORD="$_pre_pass"
[ -n "$_pre_db" ]   && POSTGRES_DB="$_pre_db"

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5434}"
PGUSER="${POSTGRES_USER:-geolens}"
export PGPASSWORD="${POSTGRES_PASSWORD:-geolens}"
ADMIN_DB="${POSTGRES_DB:-geolens}"

for bin in pg_dump pg_restore psql createdb dropdb; do
    command -v "$bin" >/dev/null 2>&1 || { echo "SKIP: $bin not found on PATH"; exit 0; }
done

# Verify the test Postgres is reachable before creating throwaway DBs.
if ! psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" -tAc "SELECT 1" >/dev/null 2>&1; then
    echo "SKIP: test Postgres not reachable at ${PGHOST}:${PGPORT} (is the test DB up?)"
    exit 0
fi

# --- Throwaway names (unique suffix avoids colliding with anything else) ------
SUFFIX="$$_$(date +%s)"
SRC_DB="geolens_bkp_src_${SUFFIX}"
DST_DB="geolens_bkp_dst_${SUFFIX}"
WORKDIR="$(mktemp -d)"
DUMP_FILE="${WORKDIR}/roundtrip.dump"

psql_admin() { psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" "$@"; }

cleanup() {
    set +e
    # Terminate any lingering connections, then drop BOTH throwaway DBs.
    for db in "$SRC_DB" "$DST_DB"; do
        psql_admin -tAc \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}' AND pid <> pg_backend_pid();" \
            >/dev/null 2>&1
        dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --if-exists "$db" >/dev/null 2>&1
    done
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== BKP-04 backup+restore round-trip (local) ==="
echo "Test Postgres: ${PGHOST}:${PGPORT} (admin db: ${ADMIN_DB})"
echo "Throwaway DBs: ${SRC_DB} -> ${DST_DB}"
echo ""

# ------------------------------------------------------------------------------
# 1. DB round-trip
# ------------------------------------------------------------------------------
echo "[1/3] Creating source DB and seeding known rows..."
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$SRC_DB"

# Mirror the app's catalog schema shape just enough to be representative.
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE TABLE catalog.records  (id serial PRIMARY KEY, name text NOT NULL);
CREATE TABLE catalog.datasets (id serial PRIMARY KEY, slug text NOT NULL);
INSERT INTO catalog.records (name)
    SELECT 'record-' || g FROM generate_series(1, 137) g;
INSERT INTO catalog.datasets (slug)
    SELECT 'dataset-' || g FROM generate_series(1, 42) g;
EOSQL

SRC_RECORDS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" -tAc "SELECT COUNT(*) FROM catalog.records;")"
SRC_DATASETS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" -tAc "SELECT COUNT(*) FROM catalog.datasets;")"
echo "      source counts: records=${SRC_RECORDS} datasets=${SRC_DATASETS}"

echo "[2/3] pg_dump -Fc, then pg_restore into a fresh DB (restore.sh flags)..."
pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" \
    -Fc --no-owner --no-acl -f "$DUMP_FILE"
[ -s "$DUMP_FILE" ] || fail "dump file is empty"

# Integrity check — same as restore.sh's pre-flight.
pg_restore --list "$DUMP_FILE" >/dev/null || fail "pg_restore --list validation failed"

createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$DST_DB"
# Same flags restore.sh uses. --clean --if-exists emits expected warnings on a
# fresh DB; tolerate a nonzero exit that carries no real ERROR lines.
RESTORE_ERR="${WORKDIR}/restore.err"
set +e
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DST_DB" \
    --clean --if-exists --no-owner "$DUMP_FILE" 2>"$RESTORE_ERR"
RC=$?
set -e
if [ "$RC" -ne 0 ]; then
    if grep -qi "error:" "$RESTORE_ERR"; then
        echo "--- pg_restore stderr ---" >&2; cat "$RESTORE_ERR" >&2
        fail "pg_restore reported real errors (exit ${RC})"
    fi
    echo "      pg_restore exit ${RC} (warnings only — expected on fresh DB)"
fi

DST_RECORDS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DST_DB" -tAc "SELECT COUNT(*) FROM catalog.records;")"
DST_DATASETS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DST_DB" -tAc "SELECT COUNT(*) FROM catalog.datasets;")"
echo "      restored counts: records=${DST_RECORDS} datasets=${DST_DATASETS}"

[ "$SRC_RECORDS" = "$DST_RECORDS" ]   || fail "records count mismatch: ${SRC_RECORDS} != ${DST_RECORDS}"
[ "$SRC_DATASETS" = "$DST_DATASETS" ] || fail "datasets count mismatch: ${SRC_DATASETS} != ${DST_DATASETS}"
echo "      DB round-trip OK — row counts match exactly."
echo ""

# ------------------------------------------------------------------------------
# 2. Object-storage (staging) round-trip — mirrors backup-entrypoint.sh tar step
# ------------------------------------------------------------------------------
echo "[3/3] Object-storage (staging) tar round-trip..."
STAGING_SRC="${WORKDIR}/staging-src"
STAGING_DST="${WORKDIR}/staging-dst"
mkdir -p "$STAGING_SRC/nested" "$STAGING_DST"
echo "raster-cog-bytes" > "$STAGING_SRC/object-a.tif"
echo "vector-fgb-bytes" > "$STAGING_SRC/nested/object-b.fgb"
ARCHIVE="${WORKDIR}/staging-roundtrip.tar.gz"

tar czf "$ARCHIVE" -C "$STAGING_SRC" .
[ -s "$ARCHIVE" ] || fail "staging archive is empty"
tar xzf "$ARCHIVE" -C "$STAGING_DST"

diff -r "$STAGING_SRC" "$STAGING_DST" >/dev/null || fail "staging tree differs after round-trip"
echo "      staging round-trip OK — object tree + contents match."
echo ""

echo "=== PASS: backup+restore round-trip verified (DB rows + objects) ==="
echo "    records: ${SRC_RECORDS}==${DST_RECORDS}, datasets: ${SRC_DATASETS}==${DST_DATASETS}"
# trap drops both throwaway DBs on exit.
