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
#   3. Real backup cycle (#995) — RUN backup-entrypoint.sh --run-backup against a
#      temp BACKUP_DIR and assert the globals artifact: paired timestamp, mode
#      0600 (it holds role password verifiers), and that a failing pg_dumpall
#      fails the cycle without touching .last-success.
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

for bin in pg_dump pg_dumpall pg_restore psql createdb dropdb; do
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
SNAP_DB="geolens_bkp_snap_${SUFFIX}"   # managed-mode "provider snapshot" DB
WORKDIR="$(mktemp -d)"
DUMP_FILE="${WORKDIR}/roundtrip.dump"

psql_admin() { psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" "$@"; }

cleanup() {
    set +e
    # Terminate any lingering connections, then drop ALL throwaway DBs.
    for db in "$SRC_DB" "$DST_DB" "$SNAP_DB"; do
        psql_admin -tAc \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}' AND pid <> pg_backend_pid();" \
            >/dev/null 2>&1
        dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --if-exists "$db" >/dev/null 2>&1
    done
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== BKP-04 backup+restore round-trip (local — bundled + managed modes) ==="
echo "Test Postgres: ${PGHOST}:${PGPORT} (admin db: ${ADMIN_DB})"
echo "Throwaway DBs: src=${SRC_DB} dst=${DST_DB} snap=${SNAP_DB}"
echo ""

# ------------------------------------------------------------------------------
# 1. BUNDLED MODE — DB round-trip via pg_dump/pg_restore (restore.sh flags)
# ------------------------------------------------------------------------------
echo "[1/5] Creating source DB and seeding known rows (bundled mode)..."
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

echo "[2/5] pg_dump -Fc, then pg_restore into a fresh DB (restore.sh flags)..."
pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" \
    -Fc --no-owner --no-acl -f "$DUMP_FILE"
[ -s "$DUMP_FILE" ] || fail "dump file is empty"

# Integrity check — same as restore.sh's and backup-entrypoint.sh's pre-flight.
pg_restore -f /dev/null < "$DUMP_FILE" >/dev/null 2>&1 \
    || fail "pg_restore verification of a good dump failed"

# Pin WHY that check is `-f /dev/null` and not the cheaper `--list`. In a -Fc
# archive the table of contents is at the front, so `--list` happily accepts a
# dump truncated after it — exactly the shape a disk-full mid-dump produces.
# Both callers depend on truncation being caught: backup-entrypoint.sh discards
# the dump, and restore.sh aborts BEFORE its --clean --if-exists drops the live
# database. If someone swaps these back to `--list` to save a pass, this fails.
TRUNC_FILE="${WORKDIR}/truncated.dump"
DUMP_BYTES="$(wc -c < "$DUMP_FILE")"
head -c "$(( DUMP_BYTES * 60 / 100 ))" "$DUMP_FILE" > "$TRUNC_FILE"
if pg_restore -f /dev/null < "$TRUNC_FILE" >/dev/null 2>&1; then
    fail "a 60%-truncated dump passed verification — the integrity gate is not catching truncation"
fi
# Whether --list ALSO catches it depends on dump size: this fixture is small
# enough that 60% cuts into the TOC itself, while on a realistic dump 60% lands
# well past it and --list passes (measured on a 21 MB dump). So the assertion
# above is deliberately only on -f /dev/null; this is reporting, not a gate.
if pg_restore --list "$TRUNC_FILE" >/dev/null 2>&1; then
    echo "      truncation gate OK — rejected by -f /dev/null; --list missed it (the reason for the stricter check)."
else
    echo "      truncation gate OK — rejected by -f /dev/null; --list also caught it (fixture too small to clear the TOC)."
fi
rm -f "$TRUNC_FILE"

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
echo "[3/5] Object-storage (staging) tar round-trip..."
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

# ------------------------------------------------------------------------------
# 3. MANAGED MODE — provider-snapshot DB + object-storage recovery
# ------------------------------------------------------------------------------
# In managed mode, the database is provider-owned (e.g. AWS RDS / Cloud SQL).
# GeoLens's backup covers OBJECT STORAGE ONLY; the DB is recovered by the
# provider from a native snapshot. This section models that pairing:
#   (a) "Provider snapshot" — restore the dump into a fresh DB via direct
#       pg_restore flags (NOT via restore.sh's docker-compose-exec path, which
#       does not apply to an external DB). Simulates a provider-native restore.
#   (b) Object-storage recovery — extract the staging archive produced in
#       step [3/5] into a fresh location.
#   (c) Functional-pairing assert — DB rows match source; objects are present.

echo "[4/5] MANAGED MODE — provider-snapshot DB + object-storage recovery..."
STAGING_MANAGED="${WORKDIR}/staging-managed"
mkdir -p "$STAGING_MANAGED"

# (a) Create the "provider snapshot" DB by restoring from the pg_dump produced
#     in the bundled-mode leg. Use direct pg_restore flags only — NOT the
#     restore.sh docker-compose-exec path, which is inapplicable to an external
#     managed DB.
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$SNAP_DB"
SNAP_RESTORE_ERR="${WORKDIR}/snap_restore.err"
set +e
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SNAP_DB" \
    --clean --if-exists --no-owner "$DUMP_FILE" 2>"$SNAP_RESTORE_ERR"
SNAP_RC=$?
set -e
if [ "$SNAP_RC" -ne 0 ]; then
    if grep -qi "error:" "$SNAP_RESTORE_ERR"; then
        echo "--- snapshot pg_restore stderr ---" >&2; cat "$SNAP_RESTORE_ERR" >&2
        fail "managed-mode: pg_restore into snapshot DB reported errors (exit ${SNAP_RC})"
    fi
    echo "      snapshot pg_restore exit ${SNAP_RC} (warnings only — expected on fresh DB)"
fi

SNAP_RECORDS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SNAP_DB" -tAc "SELECT COUNT(*) FROM catalog.records;")"
SNAP_DATASETS="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SNAP_DB" -tAc "SELECT COUNT(*) FROM catalog.datasets;")"
echo "      snapshot DB counts: records=${SNAP_RECORDS} datasets=${SNAP_DATASETS}"

[ "$SRC_RECORDS" = "$SNAP_RECORDS" ]   || fail "managed-mode: snapshot records count mismatch: ${SRC_RECORDS} != ${SNAP_RECORDS}"
[ "$SRC_DATASETS" = "$SNAP_DATASETS" ] || fail "managed-mode: snapshot datasets count mismatch: ${SRC_DATASETS} != ${SNAP_DATASETS}"
echo "      managed-mode DB recovery OK (provider-snapshot rows match source)."

# (b) Restore the object-storage archive into a fresh staging location.
#     Reuses the archive produced in step [3/5] — same archive the backup
#     entrypoint uploads to S3 for an operator to retrieve during DR.
tar xzf "$ARCHIVE" -C "$STAGING_MANAGED"
diff -r "$STAGING_SRC" "$STAGING_MANAGED" >/dev/null \
    || fail "managed-mode: staging tree differs after recovery"
echo "      managed-mode object-storage recovery OK — staging files present and intact."

# (c) Functional-pairing: the snapshot DB rows + the restored objects together
#     represent a working instance (row counts match source; staging files present).
echo "PASS [MANAGED MODE]: provider-snapshot DB (records=${SNAP_RECORDS} datasets=${SNAP_DATASETS}) + object-storage archive verified."
echo ""

# ------------------------------------------------------------------------------
# 4. fix(#995): REAL backup cycle — globals artifact, its mode, and its pairing
# ------------------------------------------------------------------------------
# The legs above mirror what backup-entrypoint.sh does. This one RUNS it
# (`--run-backup`, BACKUP_DIR pointed at a temp dir), because the property being
# guarded is a property of that script and not of pg_dumpall: the globals dump
# carries role password verifiers, so a lost `umask 077` publishes them
# world-readable into the backup volume and, with offsite upload on, into the
# bucket. A mirrored copy here would assert the umask of the copy.
echo "[5/5] Real backup cycle — globals artifact (pairing, mode, failure path)..."
CYCLE_BACKUPS="${WORKDIR}/cycle-backups"
CYCLE_STAGING="${WORKDIR}/cycle-staging"
mkdir -p "$CYCLE_BACKUPS" "$CYCLE_STAGING/nested"
echo "cog-bytes" > "$CYCLE_STAGING/a.tif"

# Deliberately permissive so a dropped `umask 077` in the script would show up
# as a 0644 artifact rather than being masked by a strict ambient umask.
umask 022

run_cycle() {
    env BACKUP_DIR="$CYCLE_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
        POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
        POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
        POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false \
        PATH="$1" \
        bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup
}

CYCLE_LOG="${WORKDIR}/cycle.log"
if ! run_cycle "$PATH" > "$CYCLE_LOG" 2>&1; then
    cat "$CYCLE_LOG" >&2
    fail "backup cycle exited non-zero"
fi

CYCLE_DUMP="$(find "${CYCLE_BACKUPS}/daily" -name '*.dump' -type f | head -1)"
[ -n "$CYCLE_DUMP" ] || fail "cycle produced no dump"
# Anchored at the END of the name, the way restore.sh parses it: the database
# name is the prefix and may itself contain digit runs (this test's throwaway
# names do), so a leftmost match can land inside the db name instead.
CYCLE_TS="$(basename "$CYCLE_DUMP" .dump | sed -nE 's/^.*_([0-9]{8}_[0-9]{6})$/\1/p')"
[ -n "$CYCLE_TS" ] || fail "could not parse a timestamp out of $(basename "$CYCLE_DUMP")"

# Pairing: the globals artifact must carry the DUMP's timestamp, not its own
# `date` call — restore.sh matches them by exact filename.
GLOBALS_FILE="${CYCLE_BACKUPS}/daily/globals-${CYCLE_TS}.sql"
[ -f "$GLOBALS_FILE" ] \
    || fail "no globals dump paired with the dump's timestamp (expected $(basename "$GLOBALS_FILE"))"
[ -s "$GLOBALS_FILE" ] || fail "globals dump is empty"
grep -q "^CREATE ROLE" "$GLOBALS_FILE" \
    || fail "globals dump contains no CREATE ROLE — it is not a real --globals-only dump"

# Mode: `ls -l` rather than stat, whose flags differ between BSD and GNU.
GLOBALS_MODE="$(ls -l "$GLOBALS_FILE" | cut -c1-10)"
[ "$GLOBALS_MODE" = "-rw-------" ] \
    || fail "globals dump is ${GLOBALS_MODE}, expected -rw------- (umask 077 lost — role password verifiers are world-readable)"
echo "      globals artifact OK — $(basename "$GLOBALS_FILE"), mode ${GLOBALS_MODE}, paired timestamp."

[ -f "${CYCLE_BACKUPS}/.last-success" ] || fail "successful cycle did not write .last-success"

# Failure path: a pg_dumpall that fails must fail the CYCLE (an unrestorable-
# roles backup is not a good backup), leaving .last-success at its old value so
# the freshness healthcheck goes unhealthy. Shadow pg_dumpall on PATH — the stub
# name does not shadow pg_dump, so the dump itself still succeeds and this
# isolates the globals step.
STUB_BIN="${WORKDIR}/stub-bin"
mkdir -p "$STUB_BIN"
printf '#!/bin/sh\necho "simulated pg_dumpall failure" >&2\nexit 1\n' > "${STUB_BIN}/pg_dumpall"
chmod +x "${STUB_BIN}/pg_dumpall"

# Artifact names carry a whole-second timestamp, so back-to-back cycles reuse
# one name and silently overwrite each other — which would leave the pairing
# check below with a single set and nothing to prove. Sleep past the boundary.
sleep 1
# A marker file rather than a stringified `ls -l`: ls prints minute-granularity
# times, so a re-touch inside the same minute would compare equal.
LAST_SUCCESS_MARKER="${WORKDIR}/last-success-marker"
touch "$LAST_SUCCESS_MARKER"

FAIL_LOG="${WORKDIR}/cycle-fail.log"
set +e
run_cycle "${STUB_BIN}:${PATH}" > "$FAIL_LOG" 2>&1
FAIL_RC=$?
set -e
[ "$FAIL_RC" -ne 0 ] || {
    cat "$FAIL_LOG" >&2
    fail "cycle returned 0 despite pg_dumpall failing — an unrestorable-roles backup was reported as good"
}
grep -q "pg_dumpall --globals-only failed" "$FAIL_LOG" \
    || fail "cycle failed but never logged why the globals dump could not be captured"
[ ! "${CYCLE_BACKUPS}/.last-success" -nt "$LAST_SUCCESS_MARKER" ] \
    || fail ".last-success was touched by a cycle whose globals dump failed"
# The partial file must not be left behind: a truncated globals dump replays as
# a partial set of roles, which is worse than having none.
[ -z "$(find "${CYCLE_BACKUPS}/daily" -name 'globals-*.sql' -size 0 2>/dev/null)" ] \
    || fail "a failed globals dump left an empty artifact behind"
[ -z "$(find "${CYCLE_BACKUPS}/daily" -name 'globals-*.sql.tmp' 2>/dev/null)" ] \
    || fail "a failed globals dump left its .tmp behind"
echo "      failure path OK — cycle non-zero, .last-success untouched, no partial artifact."

# fix(#995) review: companions prune by PAIRING, not by their own count. The
# failure path above is exactly how the counts diverge — a good dump with no
# globals — so with count-based pruning a retention window of 1 keeps the
# newest dump while the older globals, being the only one of its kind, survives
# as an orphan. Drive that with BACKUP_RETENTION_DAILY=1: the first cycle's
# dump ages out, so its globals must go with it.
sleep 1  # distinct timestamp again, for the same reason as above
ORPHAN_LOG="${WORKDIR}/cycle-orphan.log"
if ! env BACKUP_RETENTION_DAILY=1 BACKUP_RETENTION_WEEKLY=1 \
    BACKUP_DIR="$CYCLE_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
    POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
    POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false \
    bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup > "$ORPHAN_LOG" 2>&1; then
    cat "$ORPHAN_LOG" >&2
    fail "retention-1 cycle exited non-zero"
fi
# keep=1 plus the held-back complete set = 2 dumps.
REMAINING_DUMPS="$(find "${CYCLE_BACKUPS}/daily" -name '*.dump' -type f | wc -l | tr -d ' ')"
[ "$REMAINING_DUMPS" = "2" ] \
    || fail "expected retention to leave 2 dumps (1 kept + 1 protected complete set), found ${REMAINING_DUMPS}"
for g in "${CYCLE_BACKUPS}"/daily/globals-*.sql; do
    [ -f "$g" ] || continue
    g_ts="$(basename "$g" | sed -nE 's/^.*-([0-9]{8}_[0-9]{6})\..*$/\1/p')"
    find "${CYCLE_BACKUPS}/daily" -maxdepth 1 -name "*_${g_ts}.dump" -type f | grep -q . \
        || fail "globals-${g_ts}.sql outlived its dump — companions are not pruning by pairing"
done
echo "      pairing OK — every surviving globals dump still has the dump it pairs with."

# fix(#995) review: a run of pg_dumpall failures must not walk the last
# complete set out of retention. Each failed cycle still writes a valid dump,
# so at retention 1 those dumps would otherwise evict the only dump that has a
# globals file, and the orphan sweep would then take the globals with it —
# leaving an operator with backups that cannot restore onto a fresh cluster.
COMPLETE_TS="$(basename "$(find "${CYCLE_BACKUPS}/daily" -name 'globals-*.sql' | head -1)" | sed -nE 's/^.*-([0-9]{8}_[0-9]{6})\..*$/\1/p')"
[ -n "$COMPLETE_TS" ] || fail "no complete set to protect before the failure run"
for _ in 1 2 3; do
    sleep 1
    env BACKUP_RETENTION_DAILY=1 BACKUP_RETENTION_WEEKLY=1 \
        BACKUP_DIR="$CYCLE_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
        POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
        POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
        POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false PATH="${STUB_BIN}:${PATH}" \
        bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup > /dev/null 2>&1 || true
done
[ -f "${CYCLE_BACKUPS}/daily/globals-${COMPLETE_TS}.sql" ] \
    || fail "three failed cycles at retention 1 evicted the last complete set's globals"
find "${CYCLE_BACKUPS}/daily" -maxdepth 1 -name "*_${COMPLETE_TS}.dump" -type f | grep -q . \
    || fail "three failed cycles at retention 1 evicted the last complete set's dump"
echo "      protection OK — the newest complete set survived a run of globals failures."

# fix(#995) review: retention orders by the timestamp EXTRACTED from the name,
# not by the whole path. The database name is the prefix, so a path sort ranks
# it ahead of the timestamp: after a POSTGRES_DB rename to a lexically earlier
# name, every fresh dump sorts as the oldest and is pruned while the obsolete
# ones are kept. These two fixtures only differ in which order they land under
# each rule — `aaa_` is NEWER but sorts first by path.
SORT_BACKUPS="${WORKDIR}/sort-backups"
mkdir -p "${SORT_BACKUPS}/daily"
: > "${SORT_BACKUPS}/daily/zzz_20260101_000000.dump"
: > "${SORT_BACKUPS}/daily/aaa_20260102_000000.dump"
env BACKUP_RETENTION_DAILY=1 BACKUP_RETENTION_WEEKLY=1 \
    BACKUP_DIR="$SORT_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
    POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
    POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false \
    bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup > /dev/null 2>&1 \
    || fail "sort-order cycle exited non-zero"
[ -f "${SORT_BACKUPS}/daily/aaa_20260102_000000.dump" ] \
    || fail "retention pruned the NEWER dump because its database-name prefix sorts first"
[ ! -f "${SORT_BACKUPS}/daily/zzz_20260101_000000.dump" ] \
    || fail "retention kept the older dump — pruning is not ordered by the embedded timestamp"
echo "      ordering OK — retention follows the embedded timestamp, not the database-name prefix."
echo ""

echo "=== PASS: backup+restore round-trip verified (bundled + managed modes) ==="
echo "    bundled DB: records=${SRC_RECORDS}==${DST_RECORDS}, datasets=${SRC_DATASETS}==${DST_DATASETS}"
echo "    managed snapshot: records=${SRC_RECORDS}==${SNAP_RECORDS}, datasets=${SRC_DATASETS}==${SNAP_DATASETS}"
echo "    globals: $(basename "$GLOBALS_FILE") mode ${GLOBALS_MODE}, failure path fails the cycle"
# trap drops all three throwaway DBs on exit.
