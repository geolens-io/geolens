#!/usr/bin/env bash
# test_alembic_upgrade_clean_db.sh — exercise the full migration chain
# against a freshly-initialized PostGIS container.
#
# A down_revision linkage check only verifies migration ordering. This
# script is the semantic complement: does the chain actually APPLY against
# a clean DB? It builds the project's custom PostGIS+pgvector
# image (./db/Dockerfile), spins up a throwaway container with the
# extensions-init script mounted, then runs `alembic upgrade head` from
# `backend/` against that DB. Container is `docker rm -f`'d on every exit
# path via trap (success, failure, signal).
#
# Usage:
#   cd backend && ./scripts/test_alembic_upgrade_clean_db.sh
#   # or from anywhere:
#   /path/to/repo/backend/scripts/test_alembic_upgrade_clean_db.sh
#
# Env overrides:
#   ALEMBIC_TEST_DB_PORT — local port for the throwaway DB (default 54399)
#   ALEMBIC_TEST_TIMEOUT — pg_isready poll timeout in seconds (default 60)
#
# Requires: docker daemon running, uv installed, project repo checkout.

set -euo pipefail

# POSTGIS_IMAGE_TAG: base PostGIS+PostgreSQL tag. Must match the FROM line in
# `db/Dockerfile`; when that bumps PostGIS, bump it here and re-confirm pgvector
# still installs against the new postgres major. The script builds the local
# ./db image, so the test image matches the one `docker compose up` uses.
POSTGIS_IMAGE_TAG="18-3.6"

CONTAINER_NAME="geolens-alembic-test-$$"
PG_PORT="${ALEMBIC_TEST_DB_PORT:-54399}"
WAIT_SECONDS="${ALEMBIC_TEST_TIMEOUT:-60}"
TEST_IMAGE="geolens-alembic-test:latest"
PG_USER="geolens"
PG_PASSWORD="test"
PG_DB="geolens"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
DB_BUILD_CONTEXT="${REPO_ROOT}/db"
INIT_DB_SCRIPT="${REPO_ROOT}/scripts/init-db.sh"
ROLE_RECONCILER="${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh"

# Registered before the container starts so Ctrl-C drops it.
cleanup() {
  local exit_code=$?
  # Only emit the cleanup banner if the container was actually started
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    echo ""
    echo "Cleaning up throwaway container '${CONTAINER_NAME}'..."
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

echo "==> test_alembic_upgrade_clean_db.sh — clean-DB alembic upgrade smoke (KNOWN-02)"
echo "    Container: ${CONTAINER_NAME}"
echo "    Port:      ${PG_PORT}"
echo "    Image:     ${TEST_IMAGE} (built from ${DB_BUILD_CONTEXT})"
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found on PATH" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon not running (try: 'docker ps')" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found on PATH (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

if [ ! -d "${DB_BUILD_CONTEXT}" ] || [ ! -f "${DB_BUILD_CONTEXT}/Dockerfile" ]; then
  echo "ERROR: ${DB_BUILD_CONTEXT}/Dockerfile not found — expected repo root at ${REPO_ROOT}" >&2
  exit 1
fi

if [ ! -f "${INIT_DB_SCRIPT}" ]; then
  echo "ERROR: ${INIT_DB_SCRIPT} not found — extensions cannot be installed without it" >&2
  exit 1
fi

if [ ! -f "${ROLE_RECONCILER}" ] || [ ! -r "${ROLE_RECONCILER}" ]; then
  echo "ERROR: ${ROLE_RECONCILER} not found or unreadable — database roles cannot be initialized without it" >&2
  exit 1
fi

if [ ! -f "${BACKEND_DIR}/alembic.ini" ]; then
  echo "ERROR: ${BACKEND_DIR}/alembic.ini not found" >&2
  exit 1
fi

# Refuse to run if the chosen port is in use; a stale container or other
# postgres on this port would silently mask migration failures. lsof may be
# absent on Linux, so fall back to nc -z.
_port_in_use() {
  lsof -iTCP:"${PG_PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1 \
    || nc -z 127.0.0.1 "${PG_PORT}" 2>/dev/null
}
if _port_in_use; then
  echo "ERROR: port ${PG_PORT} is already in use" >&2
  echo "       override with ALEMBIC_TEST_DB_PORT=<free-port>" >&2
  exit 1
fi

# Build the test image (a cache hit is fast; the first run takes ~2-3 min for pgvector)
echo "==> Building ${TEST_IMAGE} from ${DB_BUILD_CONTEXT} (cache-friendly)..."
docker build -q -t "${TEST_IMAGE}" "${DB_BUILD_CONTEXT}" >/dev/null

echo "==> Starting container..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "127.0.0.1:${PG_PORT}:5432" \
  -e POSTGRES_USER="${PG_USER}" \
  -e POSTGRES_PASSWORD="${PG_PASSWORD}" \
  -e POSTGRES_DB="${PG_DB}" \
  -v "${INIT_DB_SCRIPT}:/docker-entrypoint-initdb.d/10-init.sh:ro" \
  -v "${ROLE_RECONCILER}:/usr/local/bin/configure-runtime-db-role:ro" \
  "${TEST_IMAGE}" >/dev/null

# Readiness needs three probes:
#   1. pg_isready alone is not enough: init-db.sh runs after initial readiness,
#      so poll for the `vector` extension to avoid racing its creation.
#   2. docker-entrypoint.sh runs init scripts against a temporary Postgres
#      listening only on the Unix socket, so pg_isready and `docker exec psql`
#      succeed during bootstrap. The temporary server then shuts down and the
#      production server starts with TCP. A TCP-only client (asyncpg from
#      alembic) connecting in between gets `ConnectionDoesNotExistError`, so
#      also probe TCP from the host, which only succeeds once the production
#      server is up on the mapped port.
#   3. The host probe uses `pg_isready` if available, otherwise `nc -z`.
_tcp_ready() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h 127.0.0.1 -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -q -t 2 2>/dev/null
  else
    nc -z 127.0.0.1 "${PG_PORT}" 2>/dev/null
  fi
}

echo -n "==> Waiting up to ${WAIT_SECONDS}s for DB readiness + extensions..."
elapsed=0
while [ "${elapsed}" -lt "${WAIT_SECONDS}" ]; do
  # In-container readiness (Unix socket), then the extension probe (confirms
  # init-db.sh and 10_postgis.sh ran), then host-side TCP readiness.
  if docker exec "${CONTAINER_NAME}" pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
    if docker exec "${CONTAINER_NAME}" \
         psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
         "SELECT 1 FROM pg_extension WHERE extname='vector'" 2>/dev/null \
         | grep -q '^1$'; then
      if _tcp_ready; then
        echo " ready."
        break
      fi
    fi
  fi
  sleep 1
  elapsed=$((elapsed + 1))
  echo -n "."
done

if [ "${elapsed}" -ge "${WAIT_SECONDS}" ]; then
  echo ""
  echo "ERROR: DB did not become ready (with extensions) within ${WAIT_SECONDS}s" >&2
  echo "       Container logs:" >&2
  docker logs "${CONTAINER_NAME}" 2>&1 | tail -60 >&2
  exit 1
fi

# Run the migrations from backend/.
echo "==> Running migration boundary/backfill smoke against the throwaway DB..."
cd "${BACKEND_DIR}"

# DATABASE_URL_OVERRIDE is the documented override that settings.database_url
# (read by alembic/env.py) honors. SSL is disabled because .env may default to
# "prefer" and the throwaway container has no TLS.
export DATABASE_URL_OVERRIDE="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
export DATABASE_SSL_MODE="disable"
# Also export POSTGRES_* in case a downstream tool reads them; settings.database_url
# builds a URL from these when no override is set.
export POSTGRES_USER="${PG_USER}"
export POSTGRES_PASSWORD="${PG_PASSWORD}"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="${PG_PORT}"
export POSTGRES_DB="${PG_DB}"

# alembic/env.py imports app.core.config.settings, which instantiates Settings()
# at import. With no repo-root .env (CI), three required fields (JWT_SECRET_KEY,
# GEOLENS_ADMIN_USERNAME/PASSWORD) are unset and the fail-fast aborts before any
# migration runs. This smoke never serves auth, so padding values are fine;
# ${VAR:-default} preserves any real value. JWT_SECRET_KEY must be >=32 chars
# and not a known-public literal.
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-alembic-clean-db-smoke-padding-key-32chars}"
export GEOLENS_ADMIN_USERNAME="${GEOLENS_ADMIN_USERNAME:-admin}"
export GEOLENS_ADMIN_PASSWORD="${GEOLENS_ADMIN_PASSWORD:-admin}"

# backend/ has no [build-system] in pyproject.toml, so the `app` package is
# imported via the cwd entry on sys.path. `uv run --no-dev` launching the
# `alembic` console script does not add cwd to sys.path the way `python -c`
# does, so env.py would fail with ModuleNotFoundError. PYTHONPATH=. restores it.
export PYTHONPATH=.

# database_connect_args in app/core/config.py returns no ssl key when
# database_ssl_mode='disable', and asyncpg then defaults to ssl='prefer' on
# TCP. The throwaway PostGIS container has no SSL configured, so the STARTTLS
# attempt drops the connection (`unexpected connection_lost() call`). asyncpg
# reads PGSSLMODE when ssl is unset, which pre-empts that default. This only
# affects this script, not the running geolens stack.
export PGSSLMODE=disable

TENANT_ID="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_SUFFIX="aaaaaaaa_aaaa_aaaa_aaaa_aaaaaaaaaaaa"
TENANT_SCHEMA="data_t_${TENANT_SUFFIX}"
TENANT_READER="geolens_reader_t_${TENANT_SUFFIX}"
TENANT_WRITER="geolens_writer_t_${TENANT_SUFFIX}"

# Stop immediately before 0019, then create the shape of a legacy tenant whose
# table and sequence are owned by the old shared database login. The 0019
# upgrade must adopt both objects into the per-tenant writer role.
alembic_rc=0
uv run --no-dev alembic upgrade 0018_tenant_insert_stamping || alembic_rc=$?
if [ "${alembic_rc}" -eq 0 ]; then
  docker exec "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 \
    -U "${PG_USER}" -d "${PG_DB}" -c \
    "INSERT INTO catalog.tenants (id, slug, name) VALUES ('${TENANT_ID}', 'legacy-owner-smoke', 'Legacy Owner Smoke'); CREATE SCHEMA ${TENANT_SCHEMA}; CREATE ROLE ${TENANT_READER} NOLOGIN; CREATE TABLE ${TENANT_SCHEMA}.legacy_features (id bigint PRIMARY KEY, name text); CREATE SEQUENCE ${TENANT_SCHEMA}.legacy_sequence; GRANT USAGE ON SCHEMA ${TENANT_SCHEMA} TO ${TENANT_READER}; GRANT SELECT ON ALL TABLES IN SCHEMA ${TENANT_SCHEMA} TO ${TENANT_READER}; ALTER DEFAULT PRIVILEGES IN SCHEMA ${TENANT_SCHEMA} GRANT SELECT ON TABLES TO ${TENANT_READER};" \
    >/dev/null
  uv run --no-dev alembic upgrade head || alembic_rc=$?
fi

if [ "${alembic_rc}" -ne 0 ]; then
  echo ""
  echo "FAIL: alembic upgrade head exited ${alembic_rc} against a clean DB" >&2
  echo ""
  echo "==> Container logs (last 100 lines):" >&2
  docker logs "${CONTAINER_NAME}" 2>&1 | tail -100 >&2
  exit "${alembic_rc}"
fi

owner_check="$(docker exec "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
  "SELECT bool_and(owner_role.rolname = '${TENANT_WRITER}') FROM pg_class AS relation JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner WHERE namespace.nspname = '${TENANT_SCHEMA}' AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S');")"
if [ "${owner_check}" != "t" ]; then
  echo "FAIL: 0019 did not transfer every legacy tenant table/sequence to ${TENANT_WRITER}" >&2
  exit 1
fi

# Model the exact deployed login grants. The runtime/tile login -> fixed
# gateway edge must be SET-capable, while the fixed gateway -> tenant role edge
# remains non-inherited and SET-only. Prove both writer and reader paths live.
docker exec "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 \
  -U "${PG_USER}" -d "${PG_DB}" -c \
  "CREATE ROLE geolens_oc_api_cycle LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; CREATE ROLE geolens_oc_tile_cycle LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; GRANT geolens_tenant_control TO geolens_oc_api_cycle WITH INHERIT TRUE, SET FALSE; GRANT geolens_tenant_writer TO geolens_oc_api_cycle WITH INHERIT FALSE, SET TRUE; GRANT geolens_tenant_sandbox TO geolens_oc_api_cycle WITH INHERIT FALSE, SET TRUE; GRANT geolens_tile_gateway TO geolens_oc_tile_cycle WITH INHERIT FALSE, SET TRUE;" \
  >/dev/null

api_writer_role="$(docker exec "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 \
  -U "${PG_USER}" -d "${PG_DB}" -qAtc \
  "SET SESSION AUTHORIZATION geolens_oc_api_cycle; BEGIN; SET LOCAL ROLE ${TENANT_WRITER}; SELECT current_user; ROLLBACK;")"
api_reader_role="$(docker exec "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 \
  -U "${PG_USER}" -d "${PG_DB}" -qAtc \
  "SET SESSION AUTHORIZATION geolens_oc_api_cycle; BEGIN; SET LOCAL ROLE ${TENANT_READER}; SELECT current_user; ROLLBACK;")"
tile_reader_role="$(docker exec "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 \
  -U "${PG_USER}" -d "${PG_DB}" -qAtc \
  "SET SESSION AUTHORIZATION geolens_oc_tile_cycle; BEGIN; SET LOCAL ROLE ${TENANT_READER}; SELECT current_user; ROLLBACK;")"
if [ "${api_writer_role}" != "${TENANT_WRITER}" ] \
   || [ "${api_reader_role}" != "${TENANT_READER}" ] \
   || [ "${tile_reader_role}" != "${TENANT_READER}" ]; then
  echo "FAIL: deployed SET-only gateway chain cannot assume the tenant role" >&2
  exit 1
fi

# 0019 intentionally retains cluster roles and operator-managed login grants.
# A real downgrade/re-upgrade must therefore validate and accept those safe
# members rather than treating them as reserved-name collisions.
echo "==> Running 0019 downgrade -> re-upgrade with deployed memberships..."
uv run --no-dev alembic downgrade 0018_tenant_insert_stamping
uv run --no-dev alembic upgrade head

# Drift gate: the upgraded schema must match the ORM models, so a column added
# to a model without a migration fails here. `alembic check` exits non-zero on
# any pending diff.
echo ""
echo "==> Running 'alembic check' (model/migration drift gate)..."
check_rc=0
uv run --no-dev alembic check || check_rc=$?
if [ "${check_rc}" -ne 0 ]; then
  echo ""
  echo "FAIL: alembic check found drift between the migrations and the ORM models (exit ${check_rc})." >&2
  echo "      Run 'alembic revision --autogenerate' and fold the diff in, or fix the model." >&2
  exit "${check_rc}"
fi

echo ""
echo "OK: alembic upgrade head + check passed against a fresh DB (${TEST_IMAGE})"
exit 0
