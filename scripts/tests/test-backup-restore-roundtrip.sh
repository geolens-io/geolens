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

# The generic CI service is postgis/postgis and intentionally has no pgvector.
# Keep the backup/restore and role-isolation proof portable there, while the
# project DB image/local stack must exercise the complete embedding DDL path.
PGVECTOR_AVAILABLE="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
    -d "$ADMIN_DB" -tAc \
    "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector');" \
    | tr -d '[:space:]')"
if [ "$PGVECTOR_AVAILABLE" = "t" ]; then
    echo "pgvector available — embedding-definer DDL subproof enabled."
else
    echo "SKIP [pgvector]: extension unavailable; vector-specific embedding-definer DDL subproof disabled (function ownership and ACL checks still run)."
fi

# --- Throwaway names (unique suffix avoids colliding with anything else) ------
SUFFIX="$$_$(date +%s)"
SRC_DB="geolens_bkp_src_${SUFFIX}"
DST_DB="geolens_bkp_dst_${SUFFIX}"
SNAP_DB="geolens_bkp_snap_${SUFFIX}"   # managed-mode "provider snapshot" DB
PROVIDER_DB="geolens_bkp_provider_${SUFFIX}"
PROVIDER_FAIL_DB="geolens_bkp_provider_fail_${SUFFIX}"
RUNTIME_ROLE="geolens_bkp_app_${SUFFIX}"
RUNTIME_ROLE="${RUNTIME_ROLE//[^a-zA-Z0-9_]/_}"
RUNTIME_PASSWORD="ci-runtime-role-test-password-947-padding"
FRESH_RUNTIME_ROLE="geolens_bkp_fresh_app_${SUFFIX}"
FRESH_RUNTIME_ROLE="${FRESH_RUNTIME_ROLE//[^a-zA-Z0-9_]/_}"
ROTATED_RUNTIME_ROLE="geolens_bkp_rotated_app_${SUFFIX}"
ROTATED_RUNTIME_ROLE="${ROTATED_RUNTIME_ROLE//[^a-zA-Z0-9_]/_}"
ROTATED_RUNTIME_PASSWORD="rotated-runtime-password-947-padding"
ROTATION_ROLLBACK_PASSWORD="rotation-rollback-password-947-padding"
MIGRATION_ROLE="geolens_bkp_migrator_${SUFFIX}"
MIGRATION_ROLE="${MIGRATION_ROLE//[^a-zA-Z0-9_]/_}"
MIGRATION_PASSWORD="migration-owner-password-947-padding"
UNMANAGED_ROLE="geolens_bkp_unmanaged_${SUFFIX}"
UNMANAGED_ROLE="${UNMANAGED_ROLE//[^a-zA-Z0-9_]/_}"
UNMANAGED_PASSWORD="unmanaged-original-password-947-padding"
RESTORE_ROLE="geolens_bkp_restore_app_${SUFFIX}"
RESTORE_ROLE="${RESTORE_ROLE//[^a-zA-Z0-9_]/_}"
RESTORE_PASSWORD="restored-runtime-password-947-padding"
LEGACY_UNTRUSTED_ROLE="geolens_bkp_legacy_untrusted_${SUFFIX}"
LEGACY_UNTRUSTED_ROLE="${LEGACY_UNTRUSTED_ROLE//[^a-zA-Z0-9_]/_}"
LEGACY_UNTRUSTED_PASSWORD="legacy-untrusted-password-947-padding"
RETIRED_DB="geolens_bkp_retired_${SUFFIX}"
RECONCILER_ROLE="geolens_bkp_provider_admin_${SUFFIX}"
RECONCILER_ROLE="${RECONCILER_ROLE//[^a-zA-Z0-9_]/_}"
RECONCILER_PASSWORD="provider-admin-password-947-padding"
PROVIDER_RUNTIME_ROLE="geolens_bkp_provider_app_${SUFFIX}"
PROVIDER_RUNTIME_ROLE="${PROVIDER_RUNTIME_ROLE//[^a-zA-Z0-9_]/_}"
PROVIDER_RUNTIME_PASSWORD="provider-runtime-password-947-padding"
PROVIDER_ROTATED_ROLE="geolens_bkp_provider_rotated_app_${SUFFIX}"
PROVIDER_ROTATED_ROLE="${PROVIDER_ROTATED_ROLE//[^a-zA-Z0-9_]/_}"
PROVIDER_ROTATED_PASSWORD="provider-rotated-password-947-padding"
PROVIDER_FAIL_ROLE="geolens_bkp_provider_fail_app_${SUFFIX}"
PROVIDER_FAIL_ROLE="${PROVIDER_FAIL_ROLE//[^a-zA-Z0-9_]/_}"
PROVIDER_FAIL_PASSWORD="provider-failure-original-password-947-padding"
PROVIDER_FAIL_REPLACEMENT_ROLE="geolens_bkp_provider_fail_new_${SUFFIX}"
PROVIDER_FAIL_REPLACEMENT_ROLE="${PROVIDER_FAIL_REPLACEMENT_ROLE//[^a-zA-Z0-9_]/_}"
PROVIDER_FAIL_REPLACEMENT_PASSWORD="provider-failure-new-password-947-padding"
OLD_SESSION_PID=""
WORKDIR="$(mktemp -d)"
DUMP_FILE="${WORKDIR}/roundtrip.dump"

psql_admin() { psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" "$@"; }

cleanup() {
    set +e
    if [ -n "$OLD_SESSION_PID" ]; then
        kill "$OLD_SESSION_PID" >/dev/null 2>&1
        wait "$OLD_SESSION_PID" >/dev/null 2>&1
    fi
    # Terminate any lingering connections, then drop ALL throwaway DBs.
    for db in \
        "$SRC_DB" "$DST_DB" "$SNAP_DB" "$PROVIDER_DB" "$PROVIDER_FAIL_DB"; do
        psql_admin -tAc \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}' AND pid <> pg_backend_pid();" \
            >/dev/null 2>&1
        dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --if-exists "$db" >/dev/null 2>&1
    done
    for role in \
        "$RUNTIME_ROLE" "$FRESH_RUNTIME_ROLE" "$ROTATED_RUNTIME_ROLE" \
        "$MIGRATION_ROLE" \
        "$UNMANAGED_ROLE" "$RESTORE_ROLE" "$LEGACY_UNTRUSTED_ROLE" \
        "$PROVIDER_RUNTIME_ROLE" "$PROVIDER_ROTATED_ROLE" \
        "$PROVIDER_FAIL_ROLE" "$PROVIDER_FAIL_REPLACEMENT_ROLE" \
        "$RECONCILER_ROLE"; do
        psql_admin -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS \"${role}\"" \
            >/dev/null 2>&1
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
CREATE FUNCTION catalog.provision_tenant_data_schema(uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
    AS 'BEGIN NULL; END';
CREATE FUNCTION catalog.deprovision_tenant_data_schema(uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
    AS 'BEGIN NULL; END';
CREATE FUNCTION catalog.geolens_rebuild_embedding_column(integer)
    RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog
    AS 'SELECT true';
REVOKE ALL ON FUNCTION catalog.provision_tenant_data_schema(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog.geolens_rebuild_embedding_column(integer)
    FROM PUBLIC;
CREATE SCHEMA data;
CREATE TABLE data.ci_probe (id serial PRIMARY KEY, name text NOT NULL);
INSERT INTO catalog.records (name)
    SELECT 'record-' || g FROM generate_series(1, 137) g;
INSERT INTO catalog.datasets (slug)
    SELECT 'dataset-' || g FROM generate_series(1, 42) g;
INSERT INTO data.ci_probe (name) VALUES ('runtime-ownership-probe');
EOSQL
if [ "$PGVECTOR_AVAILABLE" = "t" ]; then
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$SRC_DB" \
        -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE catalog.record_embeddings (
    id bigint PRIMARY KEY,
    embedding public.vector(3) NOT NULL
);
INSERT INTO catalog.record_embeddings VALUES (1, '[1,2,3]');
CREATE INDEX ix_record_embeddings_hnsw
    ON catalog.record_embeddings USING hnsw
    (embedding public.vector_cosine_ops)
    WITH (m=16, ef_construction=64);
EOSQL
fi

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

# pg_dump --no-acl intentionally omits the source REVOKE, so PostgreSQL's
# default PUBLIC EXECUTE returns on restore. A rollback to legacy runtime mode
# must still repair this SECURITY DEFINER ACL before the reconciler exits.
psql_admin -v ON_ERROR_STOP=1 -c \
    "CREATE ROLE \"${LEGACY_UNTRUSTED_ROLE}\" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${LEGACY_UNTRUSTED_PASSWORD}';" \
    >/dev/null
psql_admin -d "$DST_DB" -v ON_ERROR_STOP=1 -c \
    "GRANT USAGE ON SCHEMA catalog TO \"${LEGACY_UNTRUSTED_ROLE}\";" \
    >/dev/null
# An operator-managed login with an explicit database ACL must survive the
# legacy reconciler closing PUBLIC CONNECT after a restore.
psql_admin -v ON_ERROR_STOP=1 -c \
    "GRANT CONNECT ON DATABASE \"${DST_DB}\" TO \"${LEGACY_UNTRUSTED_ROLE}\";" \
    >/dev/null
RESTORED_PUBLIC_EXECUTE="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT has_function_privilege('${LEGACY_UNTRUSTED_ROLE}', 'catalog.geolens_rebuild_embedding_column(integer)', 'EXECUTE');" \
    | tr -d '[:space:]')"
[ "$RESTORED_PUBLIC_EXECUTE" = "t" ] \
    || fail "restore fixture did not reproduce default PUBLIC function execution"

env \
    GEOLENS_RUNTIME_DB_ROLE="" GEOLENS_RUNTIME_DB_PASSWORD="" \
    GEOLENS_MIGRATION_DB_ROLE="" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null

LEGACY_PUBLIC_CONNECT="$(psql_admin -tAc \
    "SELECT EXISTS (
         SELECT 1
           FROM pg_database AS database
           CROSS JOIN LATERAL aclexplode(
               COALESCE(database.datacl, acldefault('d', database.datdba))
           ) AS database_acl
          WHERE database.datname = '${DST_DB}'
            AND database_acl.grantee = 0
            AND database_acl.privilege_type = 'CONNECT'
     );" | tr -d '[:space:]')"
[ "$LEGACY_PUBLIC_CONNECT" = "f" ] \
    || fail "legacy restored database retained PUBLIC CONNECT"
psql_admin -v ON_ERROR_STOP=1 -c \
    "GRANT geolens_reader TO \"${LEGACY_UNTRUSTED_ROLE}\";" >/dev/null
env PGPASSWORD="$LEGACY_UNTRUSTED_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$LEGACY_UNTRUSTED_ROLE" \
    -d "$DST_DB" -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    | grep -qx "runtime-ownership-probe" \
    || fail "explicitly admitted legacy app cannot use the tile reader after hardening"

LEGACY_CAN_EXECUTE="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT has_function_privilege('${LEGACY_UNTRUSTED_ROLE}', 'catalog.geolens_rebuild_embedding_column(integer)', 'EXECUTE');" \
    | tr -d '[:space:]')"
[ "$LEGACY_CAN_EXECUTE" = "f" ] \
    || fail "legacy reconciliation left PUBLIC execution on embedding rebuild"
if env PGPASSWORD="$LEGACY_UNTRUSTED_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$LEGACY_UNTRUSTED_ROLE" -d "$DST_DB" \
    -Atqc "SELECT catalog.geolens_rebuild_embedding_column(768)" \
    >/dev/null 2>&1; then
    fail "untrusted login invoked restored SECURITY DEFINER embedding rebuild"
fi
OWNER_EXECUTE="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT catalog.geolens_rebuild_embedding_column(768);" \
    | tr -d '[:space:]')"
[ "$OWNER_EXECUTE" = "t" ] \
    || fail "privileged function owner lost embedding rebuild execution"
echo "      legacy rollback ACL OK — untrusted EXECUTE denied; privileged owner retained."

# Preserve the original fresh-install proof: an absent safe target is created,
# marked, and reconciled without the adoption escape hatch.
env \
    GEOLENS_RUNTIME_DB_ROLE="$FRESH_RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RUNTIME_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$PGUSER" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$SRC_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null

# Mixed clusters must preserve the same connection boundary: a split runtime
# from database A is a member of the cluster-global reader role, but database
# B's legacy reconciliation must still prevent that login from connecting.
if env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$DST_DB" \
    -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    >/dev/null 2>&1; then
    fail "split runtime crossed into a legacy database through geolens_reader"
fi
FRESH_ROLE_MARKER="$(psql_admin -tAc \
    "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = '${FRESH_RUNTIME_ROLE}';" \
    | tr -d '[:space:]')"
[ "$FRESH_ROLE_MARKER" = "geolens-managed-runtime-role:v2:database=${SRC_DB}" ] \
    || fail "fresh runtime role lacks the durable GeoLens marker"

# PostgreSQL roles are cluster-global. A second GeoLens database must not be
# able to claim the first database's runtime role and rotate its password. The
# adoption flag is deliberately not an override while the marker's DB exists.
for adopt_collision in false true; do
    if env \
        GEOLENS_RUNTIME_DB_ROLE="$FRESH_RUNTIME_ROLE" \
        GEOLENS_RUNTIME_DB_PASSWORD="collision-runtime-password-947-padding" \
        GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING="$adopt_collision" \
        GEOLENS_MIGRATION_DB_ROLE="$PGUSER" \
        POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
        POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
        bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" \
        >/dev/null 2>&1; then
        fail "second database claimed a foreign-scoped runtime role (adopt=${adopt_collision})"
    fi
done
COLLISION_MARKER="$(psql_admin -tAc \
    "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = '${FRESH_RUNTIME_ROLE}';" \
    | tr -d '[:space:]')"
[ "$COLLISION_MARKER" = "$FRESH_ROLE_MARKER" ] \
    || fail "foreign-database collision replaced the first database's marker"
env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -Atqc "SELECT 1" | grep -qx 1 \
    || fail "foreign-database collision replaced the first database's password"
if env PGPASSWORD="collision-runtime-password-947-padding" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -Atqc "SELECT 1" >/dev/null 2>&1; then
    fail "foreign-database replacement password authenticated to the first database"
fi

# The exact database-scoped marker remains the ordinary idempotent path.
env \
    GEOLENS_RUNTIME_DB_ROLE="$FRESH_RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RUNTIME_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$PGUSER" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$SRC_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null

# Model a managed database where reconciliation runs as the provider admin but
# Alembic owns future catalog objects under a distinct migration role.
psql_admin -v ON_ERROR_STOP=1 >/dev/null <<EOSQL
CREATE ROLE "${MIGRATION_ROLE}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${MIGRATION_PASSWORD}';
CREATE ROLE "${UNMANAGED_ROLE}" LOGIN NOSUPERUSER NOCREATEDB CREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${UNMANAGED_PASSWORD}';
CREATE ROLE "${RUNTIME_ROLE}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${RUNTIME_PASSWORD}';
CREATE ROLE "${RESTORE_ROLE}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${RESTORE_PASSWORD}';
COMMENT ON ROLE "${RESTORE_ROLE}" IS
    'geolens-managed-runtime-role:v2:database=${RETIRED_DB}';
EOSQL
psql_admin -d "$DST_DB" -v ON_ERROR_STOP=1 -c \
    "GRANT USAGE, CREATE ON SCHEMA catalog TO \"${MIGRATION_ROLE}\"" >/dev/null
psql_admin -d "$DST_DB" -v ON_ERROR_STOP=1 -c \
    "ALTER TABLE data.ci_probe OWNER TO \"${RUNTIME_ROLE}\"" >/dev/null

# A globals-backed role restored under a different database name is foreign
# until the operator explicitly rebinds it, and rebind is allowed only because
# the marker's old database no longer exists in this cluster.
if env \
    GEOLENS_RUNTIME_DB_ROLE="$RESTORE_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RESTORE_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" \
    >/dev/null 2>&1; then
    fail "restored role rebound to a renamed database without explicit adoption"
fi
env \
    GEOLENS_RUNTIME_DB_ROLE="$RESTORE_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RESTORE_PASSWORD" \
    GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING=true \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null
RESTORE_MARKER="$(psql_admin -tAc \
    "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = '${RESTORE_ROLE}';" \
    | tr -d '[:space:]')"
[ "$RESTORE_MARKER" = "geolens-managed-runtime-role:v2:database=${DST_DB}" ] \
    || fail "explicit restore/rename adoption did not bind the current database"
RESTORED_EMBEDDING_FUNCTION_OWNER="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT pg_get_userbyid(function.proowner)
       FROM pg_proc AS function
      WHERE function.oid = 'catalog.geolens_rebuild_embedding_column(integer)'::regprocedure;" \
    | tr -d '[:space:]')"
[ "$RESTORED_EMBEDDING_FUNCTION_OWNER" = "$MIGRATION_ROLE" ] \
    || fail "no-owner restore embedding function was not transferred to the validated migrator"
if [ "$PGVECTOR_AVAILABLE" = "t" ]; then
    RESTORED_EMBEDDING_RELATION_OWNER="$(psql_admin -d "$DST_DB" -tAc \
        "SELECT pg_get_userbyid(relowner)
           FROM pg_class
          WHERE oid = 'catalog.record_embeddings'::regclass;" \
        | tr -d '[:space:]')"
    [ "$RESTORED_EMBEDDING_RELATION_OWNER" = "$MIGRATION_ROLE" ] \
        || fail "no-owner restore embedding relation was not transferred to the validated migrator"
    RESTORED_REBUILD_RESULT="$(env PGPASSWORD="$RESTORE_PASSWORD" \
        psql -X -h "$PGHOST" -p "$PGPORT" -U "$RESTORE_ROLE" -d "$DST_DB" \
        -v ON_ERROR_STOP=1 -Atqc \
        "SELECT catalog.geolens_rebuild_embedding_column(4);")"
    [ "$RESTORED_REBUILD_RESULT" = "t" ] \
        || fail "restored runtime could not execute the migrator-owned embedding rebuild"
fi

# An unmarked existing identity must fail before ALTER ROLE or password reset.
if env \
    GEOLENS_RUNTIME_DB_ROLE="$UNMANAGED_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="replacement-runtime-password-947-padding" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null 2>&1; then
    fail "reconciler adopted an unmarked existing administrative role"
fi
if env \
    GEOLENS_RUNTIME_DB_ROLE="$UNMANAGED_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="replacement-runtime-password-947-padding" \
    GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING=true \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null 2>&1; then
    fail "reconciler adopted an administrative role via the adoption escape hatch"
fi
UNMANAGED_CREATE_ROLE="$(psql_admin -tAc \
    "SELECT rolcreaterole FROM pg_roles WHERE rolname = '${UNMANAGED_ROLE}';" \
    | tr -d '[:space:]')"
[ "$UNMANAGED_CREATE_ROLE" = "t" ] \
    || fail "rejected unmanaged role was modified before the marker check"
env PGPASSWORD="$UNMANAGED_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$UNMANAGED_ROLE" -d "$ADMIN_DB" \
    -Atqc "SELECT 1" | grep -qx 1 \
    || fail "rejected unmanaged role password was replaced"

# A pre-created safe application login also requires explicit one-time
# adoption. This fixture already owns a data table (the prior GeoLens recipe),
# including its implicit pg_toast relation. Once marked, ordinary
# reconciliation succeeds without the flag.
if env \
    GEOLENS_RUNTIME_DB_ROLE="$RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RUNTIME_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null 2>&1; then
    fail "reconciler adopted an unmarked safe role without explicit authorization"
fi

# Exercise the SAME role/grant reconciler used by fresh bootstrap and the real
# restore script. Explicit adoption writes the durable marker.
env \
    GEOLENS_RUNTIME_DB_ROLE="$RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RUNTIME_PASSWORD" \
    GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING=true \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null

ROLE_MARKER="$(psql_admin -tAc \
    "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}';" \
    | tr -d '[:space:]')"
[ "$ROLE_MARKER" = "geolens-managed-runtime-role:v2:database=${DST_DB}" ] \
    || fail "adopted runtime role lacks the durable GeoLens marker"

# Marker proof is sufficient on subsequent reconciliation.
env \
    GEOLENS_RUNTIME_DB_ROLE="$RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$RUNTIME_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DST_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null

# Runtime and reader roles are cluster-global, so prove each database's runtime
# can use the shared reader only inside its own database. Without a database
# CONNECT boundary, the source runtime can connect to the restored database,
# SET ROLE geolens_reader, and read its catalog/data grants.
env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    | grep -qx "runtime-ownership-probe" \
    || fail "source runtime cannot read its own database through geolens_reader"
if env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$DST_DB" \
    -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    >/dev/null 2>&1; then
    fail "source runtime crossed the database boundary through geolens_reader"
fi

# Rotating the configured runtime name must atomically retire every older role
# carrying this database's exact active marker before the replacement becomes
# usable. The old credential must not retain the cluster-global reader path.
OLD_SESSION_LOG="${WORKDIR}/old-runtime-session.log"
env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -v ON_ERROR_STOP=1 \
    >"$OLD_SESSION_LOG" 2>&1 <<'EOSQL' &
SELECT pg_sleep(5);
SELECT count(*) FROM catalog.records;
EOSQL
OLD_SESSION_PID=$!
OLD_SESSION_SEEN=false
for _ in $(seq 1 50); do
    if [ "$(psql_admin -tAc \
        "SELECT count(*) FROM pg_stat_activity WHERE datname = '${SRC_DB}' AND usename = '${FRESH_RUNTIME_ROLE}' AND query LIKE '%pg_sleep%';")" -gt 0 ]; then
        OLD_SESSION_SEEN=true
        break
    fi
    sleep 0.1
done
[ "$OLD_SESSION_SEEN" = true ] \
    || { cat "$OLD_SESSION_LOG" >&2; fail "old runtime session did not reach PostgreSQL before rotation"; }
env \
    GEOLENS_RUNTIME_DB_ROLE="$ROTATED_RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$ROTATED_RUNTIME_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$PGUSER" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$SRC_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null
if wait "$OLD_SESSION_PID"; then
    fail "superseded active session retained catalog read access after rotation"
fi
OLD_SESSION_PID=""
grep -Eq "permission denied for (schema catalog|table records)" "$OLD_SESSION_LOG" \
    || { cat "$OLD_SESSION_LOG" >&2; fail "superseded active session failed for an unexpected reason"; }
if env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    >/dev/null 2>&1; then
    fail "superseded runtime credentials still connect after role rotation"
fi

OLD_ROTATION_STATE="$(psql_admin -d "$SRC_DB" -tAc \
    "SELECT retired.rolcanlogin || '|' ||
            has_database_privilege(retired.oid, current_database(), 'CONNECT') || '|' ||
            pg_has_role(retired.oid, 'geolens_reader', 'MEMBER') || '|' ||
            has_table_privilege(retired.oid, 'catalog.records', 'SELECT,INSERT,UPDATE,DELETE') || '|' ||
            has_sequence_privilege(retired.oid, 'catalog.records_id_seq', 'USAGE,SELECT')
       FROM pg_roles AS retired
      WHERE retired.rolname = '${FRESH_RUNTIME_ROLE}';" | tr -d '[:space:]')"
[ "$OLD_ROTATION_STATE" = "false|false|false|false|false" ] \
    || fail "superseded runtime retained login/ACL capability: ${OLD_ROTATION_STATE}"
OLD_ROTATION_MARKER="$(psql_admin -tAc \
    "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = '${FRESH_RUNTIME_ROLE}';" \
    | tr -d '[:space:]')"
[ "$OLD_ROTATION_MARKER" = "geolens-retired-runtime-role:v1:database=${SRC_DB}" ] \
    || fail "superseded runtime lacks the database-scoped retired marker"
ROTATED_DATA_OWNER="$(psql_admin -d "$SRC_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'data.ci_probe'::regclass;" \
    | tr -d '[:space:]')"
[ "$ROTATED_DATA_OWNER" = "$ROTATED_RUNTIME_ROLE" ] \
    || fail "rotation left data.ci_probe owned by ${ROTATED_DATA_OWNER}"

# Both future-grant directions must point only at the replacement: Alembic's
# catalog defaults and the runtime owner's data-reader defaults.
psql_admin -d "$SRC_DB" -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE SEQUENCE catalog.rotation_future_sequence;
CREATE TABLE catalog.rotation_future_table (
    id bigint PRIMARY KEY DEFAULT nextval('catalog.rotation_future_sequence')
);
EOSQL
env PGPASSWORD="$ROTATED_RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$ROTATED_RUNTIME_ROLE" -d "$SRC_DB" \
    -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
BEGIN;
INSERT INTO catalog.records (name) VALUES ('rotated-runtime-write-probe');
DELETE FROM catalog.records WHERE name = 'rotated-runtime-write-probe';
INSERT INTO catalog.rotation_future_table DEFAULT VALUES;
ALTER TABLE data.ci_probe ADD COLUMN rotated_runtime_edit integer;
SET ROLE geolens_reader;
SELECT name FROM data.ci_probe;
RESET ROLE;
ROLLBACK;
CREATE TABLE data.rotation_future_table (id bigint PRIMARY KEY);
SET ROLE geolens_reader;
SELECT count(*) FROM data.rotation_future_table;
EOSQL
OLD_FUTURE_GRANTS="$(psql_admin -d "$SRC_DB" -tAc \
    "SELECT has_table_privilege('${FRESH_RUNTIME_ROLE}', 'catalog.rotation_future_table', 'SELECT,INSERT,UPDATE,DELETE') || '|' ||
            has_sequence_privilege('${FRESH_RUNTIME_ROLE}', 'catalog.rotation_future_sequence', 'USAGE,SELECT') || '|' ||
            has_table_privilege('${FRESH_RUNTIME_ROLE}', 'data.rotation_future_table', 'SELECT');" \
    | tr -d '[:space:]')"
[ "$OLD_FUTURE_GRANTS" = "false|false|false" ] \
    || fail "superseded runtime received future grants after rotation: ${OLD_FUTURE_GRANTS}"
OLD_DEFAULT_ACL="$(psql_admin -d "$SRC_DB" -tAc \
    "SELECT EXISTS (
         SELECT 1
           FROM pg_roles AS retired
           JOIN pg_default_acl AS defaults ON true
           LEFT JOIN LATERAL aclexplode(defaults.defaclacl) AS acl ON true
          WHERE retired.rolname = '${FRESH_RUNTIME_ROLE}'
            AND (defaults.defaclrole = retired.oid OR acl.grantee = retired.oid)
     );" | tr -d '[:space:]')"
[ "$OLD_DEFAULT_ACL" = "f" ] \
    || fail "superseded runtime remains in current-database default ACLs"

# The rotation is database-scoped: the active role for the second database is
# unchanged and can still use its own reader path.
FOREIGN_RUNTIME_STATE="$(psql_admin -tAc \
    "SELECT rolcanlogin || '|' || shobj_description(oid, 'pg_authid')
       FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}';" | tr -d '[:space:]')"
[ "$FOREIGN_RUNTIME_STATE" = "true|geolens-managed-runtime-role:v2:database=${DST_DB}" ] \
    || fail "source rotation disturbed the destination database runtime: ${FOREIGN_RUNTIME_STATE}"

# A retired marker is durable rollback proof. Selecting that exact role again
# reverses the rotation without the broad existing-role adoption escape hatch.
env \
    GEOLENS_RUNTIME_DB_ROLE="$FRESH_RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$ROTATION_ROLLBACK_PASSWORD" \
    GEOLENS_MIGRATION_DB_ROLE="$PGUSER" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$SRC_DB" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null
ROLLBACK_ROLE_STATE="$(psql_admin -d "$SRC_DB" -tAc \
    "SELECT active.rolcanlogin || '|' ||
            shobj_description(active.oid, 'pg_authid') || '|' ||
            retired.rolcanlogin || '|' ||
            shobj_description(retired.oid, 'pg_authid') || '|' ||
            pg_get_userbyid(probe.relowner)
       FROM pg_roles AS active
       CROSS JOIN pg_roles AS retired
       CROSS JOIN pg_class AS probe
      WHERE active.rolname = '${FRESH_RUNTIME_ROLE}'
        AND retired.rolname = '${ROTATED_RUNTIME_ROLE}'
        AND probe.oid = 'data.ci_probe'::regclass;" | tr -d '[:space:]')"
[ "$ROLLBACK_ROLE_STATE" = "true|geolens-managed-runtime-role:v2:database=${SRC_DB}|false|geolens-retired-runtime-role:v1:database=${SRC_DB}|${FRESH_RUNTIME_ROLE}" ] \
    || fail "inverse role rotation did not restore the retired target: ${ROLLBACK_ROLE_STATE}"
env PGPASSWORD="$ROTATION_ROLLBACK_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT name FROM data.ci_probe;" \
    | grep -qx "runtime-ownership-probe" \
    || fail "reactivated runtime cannot use its same-database reader path"
if env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$FRESH_RUNTIME_ROLE" -d "$SRC_DB" \
    -Atqc "SELECT 1" >/dev/null 2>&1; then
    fail "reactivated runtime accepted its pre-retirement password"
fi

# Objects later created by the actual Alembic owner must inherit runtime
# table/sequence access even though reconciliation used a different admin.
env PGPASSWORD="$MIGRATION_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$MIGRATION_ROLE" -d "$DST_DB" \
    -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE SEQUENCE catalog.future_runtime_sequence;
CREATE TABLE catalog.future_runtime_table (
    id bigint PRIMARY KEY DEFAULT nextval('catalog.future_runtime_sequence')
);
EOSQL
FUTURE_OWNER="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'catalog.future_runtime_table'::regclass;" \
    | tr -d '[:space:]')"
[ "$FUTURE_OWNER" = "$MIGRATION_ROLE" ] \
    || fail "future catalog table owner is ${FUTURE_OWNER}, expected ${MIGRATION_ROLE}"
env PGPASSWORD="$RUNTIME_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$RUNTIME_ROLE" -d "$DST_DB" \
    -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
INSERT INTO catalog.future_runtime_table DEFAULT VALUES;
SELECT id FROM catalog.future_runtime_table;
DELETE FROM catalog.future_runtime_table;
EOSQL

ROLE_FLAGS="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT rolsuper || '|' || rolbypassrls || '|' || rolcreaterole || '|' ||
            rolcreatedb || '|' || rolreplication || '|' || rolinherit
     FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}';" | tr -d '[:space:]')"
[ "$ROLE_FLAGS" = "false|false|false|false|false|false" ] \
    || fail "runtime role retained powerful/inherited attributes: ${ROLE_FLAGS}"

DATA_OWNER="$(psql_admin -d "$DST_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class
     WHERE oid = 'data.ci_probe'::regclass;" | tr -d '[:space:]')"
[ "$DATA_OWNER" = "$RUNTIME_ROLE" ] \
    || fail "restored data.ci_probe owner is ${DATA_OWNER}, expected ${RUNTIME_ROLE}"

runtime_psql=(
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$RUNTIME_ROLE" -d "$DST_DB"
    -v ON_ERROR_STOP=1
)
PGPASSWORD="$RUNTIME_PASSWORD" "${runtime_psql[@]}" >/dev/null <<'EOSQL'
BEGIN;
INSERT INTO catalog.records (name) VALUES ('least-privilege-write-probe');
UPDATE catalog.records SET name = name WHERE name = 'least-privilege-write-probe';
DELETE FROM catalog.records WHERE name = 'least-privilege-write-probe';
ALTER TABLE data.ci_probe ADD COLUMN runtime_edit integer;
SET ROLE geolens_reader;
SELECT COUNT(*) FROM data.ci_probe;
RESET ROLE;
ROLLBACK;
EOSQL
if PGPASSWORD="$RUNTIME_PASSWORD" "${runtime_psql[@]}" \
    -c "CREATE TABLE catalog.must_be_denied (id integer)" >/dev/null 2>&1; then
    fail "runtime role can CREATE in migration-owned schema catalog"
fi
for tenant_function in \
    "catalog.provision_tenant_data_schema(uuid)" \
    "catalog.deprovision_tenant_data_schema(uuid)"; do
    CAN_EXECUTE="$(psql_admin -d "$DST_DB" -tAc \
        "SELECT has_function_privilege('${RUNTIME_ROLE}', '${tenant_function}', 'EXECUTE');" \
        | tr -d '[:space:]')"
    [ "$CAN_EXECUTE" = "f" ] \
        || fail "runtime role can execute privileged ${tenant_function}"
done
if PGPASSWORD="$RUNTIME_PASSWORD" "${runtime_psql[@]}" \
    -c "SELECT catalog.provision_tenant_data_schema('00000000-0000-0000-0000-000000000947')" \
    >/dev/null 2>&1; then
    fail "runtime role executed privileged tenant provisioning function"
fi

# A managed provider reconciliation login is commonly non-superuser with
# CREATEROLE. Prove it can transfer its existing data relations by holding SET
# authority only for the transaction, and that the membership is removed.
psql_admin -v ON_ERROR_STOP=1 >/dev/null <<EOSQL
CREATE ROLE "${RECONCILER_ROLE}" LOGIN NOSUPERUSER NOCREATEDB CREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${RECONCILER_PASSWORD}';
-- The provider admin may reconcile roles without inheriting the distinct
-- Alembic owner's catalog privileges. SET-only authority is enough to create
-- and own the bounded SECURITY DEFINER function as that validated owner.
GRANT "${MIGRATION_ROLE}" TO "${RECONCILER_ROLE}" WITH ADMIN FALSE;
GRANT "${MIGRATION_ROLE}" TO "${RECONCILER_ROLE}" WITH INHERIT FALSE;
GRANT "${MIGRATION_ROLE}" TO "${RECONCILER_ROLE}" WITH SET TRUE;
-- PostgreSQL 18 gives the CREATEROLE identity that originally creates a role
-- an ADMIN-only membership. This shared test cluster's reader was created by
-- the superuser in an earlier leg, so reproduce the managed first-bootstrap
-- authority without granting SET/INHERIT access to the provider admin.
GRANT geolens_reader TO "${RECONCILER_ROLE}" WITH ADMIN TRUE;
GRANT geolens_reader TO "${RECONCILER_ROLE}" WITH INHERIT FALSE;
GRANT geolens_reader TO "${RECONCILER_ROLE}" WITH SET FALSE;
EOSQL
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
    --owner "$RECONCILER_ROLE" "$PROVIDER_DB"
env PGPASSWORD="$RECONCILER_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$RECONCILER_ROLE" \
    -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE SCHEMA catalog;
CREATE SCHEMA data;
CREATE TABLE data.provider_probe (id bigint PRIMARY KEY);
EOSQL
if [ "$PGVECTOR_AVAILABLE" = "t" ]; then
    psql_admin -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 >/dev/null <<EOSQL
CREATE EXTENSION IF NOT EXISTS vector;
GRANT USAGE, CREATE ON SCHEMA catalog TO "${MIGRATION_ROLE}";
SET ROLE "${MIGRATION_ROLE}";
CREATE TABLE catalog.record_embeddings (
    id bigint PRIMARY KEY,
    embedding public.vector(3) NOT NULL
);
INSERT INTO catalog.record_embeddings VALUES (1, '[1,2,3]');
CREATE INDEX ix_record_embeddings_hnsw
    ON catalog.record_embeddings USING hnsw
    (embedding public.vector_cosine_ops)
    WITH (m=16, ef_construction=64);
RESET ROLE;
EOSQL
else
    psql_admin -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 -c \
        "GRANT USAGE, CREATE ON SCHEMA catalog TO \"${MIGRATION_ROLE}\";" \
        >/dev/null
fi
env \
    PGPASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_PASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$RECONCILER_ROLE" POSTGRES_DB="$PROVIDER_DB" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    GEOLENS_RUNTIME_DB_ROLE="$PROVIDER_RUNTIME_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$PROVIDER_RUNTIME_PASSWORD" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null
PROVIDER_EMBEDDING_FUNCTION_OWNER="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT pg_get_userbyid(proowner)
       FROM pg_proc
      WHERE oid = 'catalog.geolens_rebuild_embedding_column(integer)'::regprocedure;" \
    | tr -d '[:space:]')"
[ "$PROVIDER_EMBEDDING_FUNCTION_OWNER" = "$MIGRATION_ROLE" ] \
    || fail "embedding rebuild owner is ${PROVIDER_EMBEDDING_FUNCTION_OWNER}, expected ${MIGRATION_ROLE}"
PROVIDER_EMBEDDING_FUNCTION_ACL="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT has_function_privilege(
                '${PROVIDER_RUNTIME_ROLE}',
                'catalog.geolens_rebuild_embedding_column(integer)',
                'EXECUTE'
            ) || '|' ||
            has_function_privilege(
                '${RECONCILER_ROLE}',
                'catalog.geolens_rebuild_embedding_column(integer)',
                'EXECUTE'
            );" \
    | tr -d '[:space:]')"
[ "$PROVIDER_EMBEDDING_FUNCTION_ACL" = "true|false" ] \
    || fail "embedding rebuild function ACL is not runtime-only: ${PROVIDER_EMBEDDING_FUNCTION_ACL}"
PROVIDER_MIGRATOR_MEMBERSHIP_FLAGS="$(psql_admin -tAc \
    "SELECT admin_option || '|' || inherit_option || '|' || set_option
       FROM pg_auth_members
      WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = '${MIGRATION_ROLE}')
        AND member = (SELECT oid FROM pg_roles WHERE rolname = '${RECONCILER_ROLE}');" \
    | tr -d '[:space:]')"
[ "$PROVIDER_MIGRATOR_MEMBERSHIP_FLAGS" = "false|false|true" ] \
    || fail "provider admin's SET-only migrator membership changed: ${PROVIDER_MIGRATOR_MEMBERSHIP_FLAGS}"
if [ "$PGVECTOR_AVAILABLE" = "t" ]; then
    PROVIDER_REBUILD_RESULT="$(env PGPASSWORD="$PROVIDER_RUNTIME_PASSWORD" \
        psql -X -h "$PGHOST" -p "$PGPORT" -U "$PROVIDER_RUNTIME_ROLE" \
        -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 -Atqc \
        "SELECT catalog.geolens_rebuild_embedding_column(4);")"
    [ "$PROVIDER_REBUILD_RESULT" = "t" ] \
        || fail "distinct-owner embedding rebuild did not report a change"
    PROVIDER_EMBEDDING_STATE="$(psql_admin -d "$PROVIDER_DB" -tAc \
        "SELECT (SELECT count(*) FROM catalog.record_embeddings) || '|' ||
                format_type(attribute.atttypid, attribute.atttypmod) || '|' ||
                (to_regclass('catalog.ix_record_embeddings_hnsw') IS NOT NULL)::text
           FROM pg_attribute AS attribute
          WHERE attribute.attrelid = 'catalog.record_embeddings'::regclass
            AND attribute.attname = 'embedding';" \
        | tr -d '[:space:]')"
    [ "$PROVIDER_EMBEDDING_STATE" = "0|vector(4)|true" ] \
        || fail "embedding rebuild did not complete DELETE/type/index DDL: ${PROVIDER_EMBEDDING_STATE}"
    PROVIDER_RECONCILER_CATALOG_ACCESS="$(psql_admin -d "$PROVIDER_DB" -tAc \
        "SELECT pg_get_userbyid(relation.relowner) = '${RECONCILER_ROLE}' OR
                has_table_privilege('${RECONCILER_ROLE}', relation.oid,
                    'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           FROM pg_class AS relation
          WHERE relation.oid = 'catalog.record_embeddings'::regclass;" \
        | tr -d '[:space:]')"
    [ "$PROVIDER_RECONCILER_CATALOG_ACCESS" = "f" ] \
        || fail "provider reconciler retained direct catalog table authority"
    if env PGPASSWORD="$PROVIDER_RUNTIME_PASSWORD" \
        psql -X -h "$PGHOST" -p "$PGPORT" -U "$PROVIDER_RUNTIME_ROLE" \
        -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 \
        -c "ALTER TABLE catalog.record_embeddings ADD COLUMN forbidden integer" \
        >/dev/null 2>&1; then
        fail "provider runtime gained direct catalog DDL authority"
    fi
fi
PROVIDER_OWNER="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'data.provider_probe'::regclass;" \
    | tr -d '[:space:]')"
[ "$PROVIDER_OWNER" = "$PROVIDER_RUNTIME_ROLE" ] \
    || fail "non-superuser reconciler did not transfer its data table"
PROVIDER_MEMBERSHIP_FLAGS="$(psql_admin -tAc \
    "SELECT admin_option || '|' || inherit_option || '|' || set_option
       FROM pg_auth_members
      WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = '${PROVIDER_RUNTIME_ROLE}')
        AND member = (SELECT oid FROM pg_roles WHERE rolname = '${RECONCILER_ROLE}');" \
    | tr -d '[:space:]')"
[ "$PROVIDER_MEMBERSHIP_FLAGS" = "true|false|false" ] \
    || fail "successful reconciliation did not restore the provider admin's ADMIN-only membership: ${PROVIDER_MEMBERSHIP_FLAGS}"

# The same rotation path must work for a provider admin that owns the database
# and has CREATEROLE but is not superuser. It gets SET only transactionally;
# both old-ownership transfer and temporary-membership cleanup are observable.
env \
    PGPASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_PASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$RECONCILER_ROLE" POSTGRES_DB="$PROVIDER_DB" \
    GEOLENS_MIGRATION_DB_ROLE="$MIGRATION_ROLE" \
    GEOLENS_RUNTIME_DB_ROLE="$PROVIDER_ROTATED_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$PROVIDER_ROTATED_PASSWORD" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" >/dev/null
PROVIDER_ROTATED_OWNER="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'data.provider_probe'::regclass;" \
    | tr -d '[:space:]')"
[ "$PROVIDER_ROTATED_OWNER" = "$PROVIDER_ROTATED_ROLE" ] \
    || fail "provider rotation left data table owned by ${PROVIDER_ROTATED_OWNER}"
PROVIDER_OLD_STATE="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT rolcanlogin || '|' ||
            has_database_privilege(oid, current_database(), 'CONNECT') || '|' ||
            pg_has_role(oid, 'geolens_reader', 'MEMBER') || '|' ||
            COALESCE(
                has_table_privilege(
                    oid,
                    to_regclass('catalog.record_embeddings'),
                    'SELECT,INSERT,UPDATE,DELETE'
                ),
                false
            )
       FROM pg_roles WHERE rolname = '${PROVIDER_RUNTIME_ROLE}';" \
    | tr -d '[:space:]')"
[ "$PROVIDER_OLD_STATE" = "false|false|false|false" ] \
    || fail "provider rotation left old role active: ${PROVIDER_OLD_STATE}"
PROVIDER_ROTATED_MEMBERSHIP_FLAGS="$(psql_admin -tAc \
    "SELECT admin_option || '|' || inherit_option || '|' || set_option
       FROM pg_auth_members
      WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = '${PROVIDER_ROTATED_ROLE}')
        AND member = (SELECT oid FROM pg_roles WHERE rolname = '${RECONCILER_ROLE}');" \
    | tr -d '[:space:]')"
[ "$PROVIDER_ROTATED_MEMBERSHIP_FLAGS" = "true|false|false" ] \
    || fail "provider rotation did not restore replacement ADMIN-only membership: ${PROVIDER_ROTATED_MEMBERSHIP_FLAGS}"
PROVIDER_READER_ACL="$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT relacl FROM pg_class WHERE oid = 'data.provider_probe'::regclass;" \
    | tr -d '[:space:]')"
[ "$(psql_admin -d "$PROVIDER_DB" -tAc \
    "SELECT has_table_privilege('geolens_reader', 'data.provider_probe', 'SELECT');" \
    | tr -d '[:space:]')" = "t" ] \
    || fail "provider rotation did not restore reader SELECT ACL: ${PROVIDER_READER_ACL}"
env PGPASSWORD="$PROVIDER_ROTATED_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$PROVIDER_ROTATED_ROLE" \
    -d "$PROVIDER_DB" -v ON_ERROR_STOP=1 -Atqc \
    "SET ROLE geolens_reader; SELECT count(*) FROM data.provider_probe;" \
    | grep -qx 0 \
    || fail "provider replacement cannot use its same-database reader path"

# Induce an ownership error after the temporary membership is granted. The
# runtime SQL transaction must roll back its password/owner changes and remove
# membership even though psql exits through ON_ERROR_STOP.
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
    --owner "$RECONCILER_ROLE" "$PROVIDER_FAIL_DB"
env PGPASSWORD="$RECONCILER_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$RECONCILER_ROLE" \
    -d "$PROVIDER_FAIL_DB" -v ON_ERROR_STOP=1 >/dev/null <<'EOSQL'
CREATE SCHEMA catalog;
CREATE SCHEMA data;
CREATE TABLE data.reconciler_probe (id bigint PRIMARY KEY);
EOSQL
psql_admin -d "$PROVIDER_FAIL_DB" -v ON_ERROR_STOP=1 \
    -c "CREATE SEQUENCE data.foreign_probe" >/dev/null
env PGPASSWORD="$RECONCILER_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$RECONCILER_ROLE" \
    -d "$PROVIDER_FAIL_DB" -v ON_ERROR_STOP=1 >/dev/null <<EOSQL
CREATE ROLE "${PROVIDER_FAIL_ROLE}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '${PROVIDER_FAIL_PASSWORD}';
COMMENT ON ROLE "${PROVIDER_FAIL_ROLE}" IS
    'geolens-managed-runtime-role:v2:database=${PROVIDER_FAIL_DB}';
GRANT CONNECT ON DATABASE "${PROVIDER_FAIL_DB}" TO "${PROVIDER_FAIL_ROLE}";
GRANT geolens_reader TO "${PROVIDER_FAIL_ROLE}";
EOSQL
psql_admin -d "$PROVIDER_FAIL_DB" -v ON_ERROR_STOP=1 \
    -c "ALTER TABLE data.reconciler_probe OWNER TO \"${PROVIDER_FAIL_ROLE}\"" \
    >/dev/null
PROVIDER_FAIL_LOG="${WORKDIR}/provider-fail.log"
if env \
    PGPASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_PASSWORD="$RECONCILER_PASSWORD" \
    POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" \
    POSTGRES_USER="$RECONCILER_ROLE" POSTGRES_DB="$PROVIDER_FAIL_DB" \
    GEOLENS_MIGRATION_DB_ROLE="$RECONCILER_ROLE" \
    GEOLENS_RUNTIME_DB_ROLE="$PROVIDER_FAIL_REPLACEMENT_ROLE" \
    GEOLENS_RUNTIME_DB_PASSWORD="$PROVIDER_FAIL_REPLACEMENT_PASSWORD" \
    bash "${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh" \
    >"$PROVIDER_FAIL_LOG" 2>&1; then
    fail "induced provider ownership failure unexpectedly reconciled"
fi
grep -q "must be owner of sequence foreign_probe" "$PROVIDER_FAIL_LOG" \
    || { cat "$PROVIDER_FAIL_LOG" >&2; fail "provider failure did not reach ownership transfer"; }
FAILED_MEMBERSHIP_FLAGS="$(psql_admin -tAc \
    "SELECT admin_option || '|' || inherit_option || '|' || set_option
       FROM pg_auth_members
      WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = '${PROVIDER_FAIL_ROLE}')
        AND member = (SELECT oid FROM pg_roles WHERE rolname = '${RECONCILER_ROLE}');" \
    | tr -d '[:space:]')"
[ "$FAILED_MEMBERSHIP_FLAGS" = "true|false|false" ] \
    || fail "failed reconciliation did not roll back to the provider admin's ADMIN-only membership: ${FAILED_MEMBERSHIP_FLAGS}"
FAILED_OWNER="$(psql_admin -d "$PROVIDER_FAIL_DB" -tAc \
    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'data.reconciler_probe'::regclass;" \
    | tr -d '[:space:]')"
[ "$FAILED_OWNER" = "$PROVIDER_FAIL_ROLE" ] \
    || fail "failed reconciliation partially transferred data ownership"
FAILED_ROLE_STATE="$(psql_admin -d "$PROVIDER_FAIL_DB" -tAc \
    "SELECT rolcanlogin || '|' ||
            has_database_privilege(oid, current_database(), 'CONNECT') || '|' ||
            pg_has_role(oid, 'geolens_reader', 'MEMBER') || '|' ||
            shobj_description(oid, 'pg_authid')
       FROM pg_roles WHERE rolname = '${PROVIDER_FAIL_ROLE}';" \
    | tr -d '[:space:]')"
[ "$FAILED_ROLE_STATE" = "true|true|true|geolens-managed-runtime-role:v2:database=${PROVIDER_FAIL_DB}" ] \
    || fail "failed rotation did not roll back old role state: ${FAILED_ROLE_STATE}"
FAILED_REPLACEMENT_EXISTS="$(psql_admin -tAc \
    "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${PROVIDER_FAIL_REPLACEMENT_ROLE}');" \
    | tr -d '[:space:]')"
[ "$FAILED_REPLACEMENT_EXISTS" = "f" ] \
    || fail "failed rotation left the replacement role behind"
env PGPASSWORD="$PROVIDER_FAIL_PASSWORD" \
    psql -X -h "$PGHOST" -p "$PGPORT" -U "$PROVIDER_FAIL_ROLE" \
    -d "$PROVIDER_FAIL_DB" -Atqc "SELECT 1" | grep -qx 1 \
    || fail "failed reconciliation replaced the original runtime password"

echo "      runtime role OK — same-DB reader SET works; cross-DB connection, catalog DDL, and tenant-control functions denied."
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
grep -Fq "geolens-managed-runtime-role:v2:database=${SRC_DB}" "$GLOBALS_FILE" \
    || fail "globals dump omitted the managed runtime-role marker"

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

# fix(#995) review: publishing failures must fail the cycle too. backup_globals
# always runs inside a `$(...) || cycle_failed=1` command substitution, which
# suspends `set -e` for its whole body, so an unchecked `mv` (read-only volume,
# ENOSPC) would fall through and report a healthy cycle with no globals artifact
# beside a valid dump. The stub fails ONLY for globals paths, so the dump's own
# mv still succeeds and this isolates the publish step.
MV_STUB_BIN="${WORKDIR}/stub-mv"
mkdir -p "$MV_STUB_BIN"
cat > "${MV_STUB_BIN}/mv" <<'MVSTUB'
#!/bin/sh
case "$*" in *globals-*) echo "simulated mv failure" >&2; exit 1;; esac
for real in /bin/mv /usr/bin/mv; do [ -x "$real" ] && exec "$real" "$@"; done
exit 127
MVSTUB
chmod +x "${MV_STUB_BIN}/mv"

sleep 1
touch "$LAST_SUCCESS_MARKER"
MV_LOG="${WORKDIR}/cycle-mv.log"
set +e
run_cycle "${MV_STUB_BIN}:${PATH}" > "$MV_LOG" 2>&1
MV_RC=$?
set -e
[ "$MV_RC" -ne 0 ] || {
    cat "$MV_LOG" >&2
    fail "cycle returned 0 despite the globals dump never being published"
}
grep -q "could not publish" "$MV_LOG" \
    || fail "cycle failed but never logged that the globals dump could not be published"
[ ! "${CYCLE_BACKUPS}/.last-success" -nt "$LAST_SUCCESS_MARKER" ] \
    || fail ".last-success was touched by a cycle that could not publish its globals dump"
[ -z "$(find "${CYCLE_BACKUPS}/daily" -name 'globals-*.sql.tmp' 2>/dev/null)" ] \
    || fail "a failed publish left the globals .tmp behind"
echo "      publish failure OK — an unpublished globals dump fails the cycle."

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

# fix(#995) review: the Sunday branch is unreachable six days a week, so the
# weekly globals copy would otherwise ship untested. Shadow `date` so only
# `+%u` answers 7 and every other format delegates, which keeps the artifact
# timestamps real.
DATE_STUB_BIN="${WORKDIR}/stub-date"
mkdir -p "$DATE_STUB_BIN"
cat > "${DATE_STUB_BIN}/date" <<'DATESTUB'
#!/bin/sh
case "$*" in "+%u") echo 7; exit 0;; esac
for real in /bin/date /usr/bin/date; do [ -x "$real" ] && exec "$real" "$@"; done
exit 127
DATESTUB
chmod +x "${DATE_STUB_BIN}/date"

SUNDAY_BACKUPS="${WORKDIR}/sunday-backups"
mkdir -p "$SUNDAY_BACKUPS"
env BACKUP_DIR="$SUNDAY_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
    POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
    POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false PATH="${DATE_STUB_BIN}:${PATH}" \
    bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup > /dev/null 2>&1 \
    || fail "Sunday cycle exited non-zero"

WEEKLY_GLOBALS="$(find "${SUNDAY_BACKUPS}/weekly" -name 'globals-*.sql' -type f | head -1)"
[ -n "$WEEKLY_GLOBALS" ] || fail "the Sunday cycle wrote no weekly globals copy"
WEEKLY_MODE="$(ls -l "$WEEKLY_GLOBALS" | cut -c1-10)"
[ "$WEEKLY_MODE" = "-rw-------" ] \
    || fail "the weekly globals copy is ${WEEKLY_MODE}, expected -rw------- (role password verifiers)"
[ -z "$(find "${SUNDAY_BACKUPS}/weekly" -name 'globals-*.sql.tmp' 2>/dev/null)" ] \
    || fail "the weekly globals copy left its .tmp behind"
WEEKLY_TS="$(basename "$WEEKLY_GLOBALS" | sed -nE 's/^.*-([0-9]{8}_[0-9]{6})\..*$/\1/p')"
find "${SUNDAY_BACKUPS}/weekly" -maxdepth 1 -name "*_${WEEKLY_TS}.dump" -type f | grep -q . \
    || fail "the weekly globals copy does not pair with a weekly dump"
echo "      weekly copy OK — paired, mode ${WEEKLY_MODE}, no leftover .tmp."

# fix(#995) review: a Sunday cycle that crosses midnight must not produce a
# weekly dump with no paired globals. This stub answers 7 for the FIRST weekday
# question and 1 for every one after, which is exactly what a 23:59 schedule or
# a slow staging archive looks like. The cycle has to decide once and stick to
# it, so all three artifacts land in weekly/ or none do.
MIDNIGHT_STUB_BIN="${WORKDIR}/stub-midnight"
mkdir -p "$MIDNIGHT_STUB_BIN"
cat > "${MIDNIGHT_STUB_BIN}/date" <<'MIDSTUB'
#!/bin/sh
case "$*" in
  "+%u")
    n=$(cat "$WEEKDAY_CALLS" 2>/dev/null || echo 0)
    n=$((n + 1)); echo "$n" > "$WEEKDAY_CALLS"
    if [ "$n" -eq 1 ]; then echo 7; else echo 1; fi
    exit 0;;
esac
for real in /bin/date /usr/bin/date; do [ -x "$real" ] && exec "$real" "$@"; done
exit 127
MIDSTUB
chmod +x "${MIDNIGHT_STUB_BIN}/date"

MIDNIGHT_BACKUPS="${WORKDIR}/midnight-backups"
mkdir -p "$MIDNIGHT_BACKUPS"
env BACKUP_DIR="$MIDNIGHT_BACKUPS" STAGING_DIR="$CYCLE_STAGING" \
    POSTGRES_HOST="$PGHOST" PGPORT="$PGPORT" \
    POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
    POSTGRES_DB="$SRC_DB" BACKUP_S3_ENABLED=false \
    WEEKDAY_CALLS="${WORKDIR}/weekday-calls" PATH="${MIDNIGHT_STUB_BIN}:${PATH}" \
    bash "${REPO_ROOT}/scripts/backup-entrypoint.sh" --run-backup > /dev/null 2>&1 \
    || fail "midnight-crossing cycle exited non-zero"

MID_WEEKLY_DUMP="$(find "${MIDNIGHT_BACKUPS}/weekly" -name '*.dump' -type f | head -1)"
if [ -n "$MID_WEEKLY_DUMP" ]; then
    MID_TS="$(basename "$MID_WEEKLY_DUMP" .dump | sed -nE 's/^.*_([0-9]{8}_[0-9]{6})$/\1/p')"
    [ -f "${MIDNIGHT_BACKUPS}/weekly/globals-${MID_TS}.sql" ] \
        || fail "a weekly dump landed with no paired globals — the weekly decision was re-evaluated mid-cycle"
    echo "      midnight crossing OK — the weekly decision held for every artifact."
else
    fail "the midnight-crossing cycle produced no weekly dump, so the pairing was not exercised"
fi
echo ""

echo "=== PASS: backup+restore round-trip verified (bundled + managed modes) ==="
echo "    bundled DB: records=${SRC_RECORDS}==${DST_RECORDS}, datasets=${SRC_DATASETS}==${DST_DATASETS}"
echo "    managed snapshot: records=${SRC_RECORDS}==${SNAP_RECORDS}, datasets=${SRC_DATASETS}==${SNAP_DATASETS}"
echo "    globals: $(basename "$GLOBALS_FILE") mode ${GLOBALS_MODE}, failure path fails the cycle"
# trap drops all three throwaway DBs on exit.
