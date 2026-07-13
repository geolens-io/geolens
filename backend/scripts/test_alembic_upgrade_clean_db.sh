#!/usr/bin/env bash
# test_alembic_upgrade_clean_db.sh — exercise the full migration chain
# against a freshly-initialized PostGIS container.
#
# KNOWN-02 (v1016 Phase 1071): v1015's close-gate only verified migration
# ordering via down_revision linkage (a syntactic check on the Python files).
# This script provides the semantic complement — does the chain actually
# APPLY against a clean DB? It builds the project's custom PostGIS+pgvector
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

# -----------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------
#
# POSTGIS_IMAGE_TAG: base PostGIS+PostgreSQL tag. MUST match the FROM line
# in `db/Dockerfile`. If `db/Dockerfile` bumps PostGIS, also bump it here
# (and re-confirm pgvector still installs against the new postgres major
# in the same Dockerfile). The script builds the local ./db image (which
# layers pgvector on top), so the resulting test image always matches the
# production-tier image used by `docker compose up`.
POSTGIS_IMAGE_TAG="17-3.5"

CONTAINER_NAME="geolens-alembic-test-$$"
PG_PORT="${ALEMBIC_TEST_DB_PORT:-54399}"
WAIT_SECONDS="${ALEMBIC_TEST_TIMEOUT:-60}"
TEST_IMAGE="geolens-alembic-test:latest"
PG_USER="geolens"
PG_PASSWORD="test"
PG_DB="geolens"

# -----------------------------------------------------------------------
# Locate repo root (script works from any cwd)
# -----------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
DB_BUILD_CONTEXT="${REPO_ROOT}/db"
INIT_DB_SCRIPT="${REPO_ROOT}/scripts/init-db.sh"

# -----------------------------------------------------------------------
# Cleanup (registered BEFORE the container starts so Ctrl-C drops it)
# -----------------------------------------------------------------------
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

# -----------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------
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

if [ ! -f "${BACKEND_DIR}/alembic.ini" ]; then
  echo "ERROR: ${BACKEND_DIR}/alembic.ini not found" >&2
  exit 1
fi

# Refuse to run if the chosen port is in use; a stale container or other
# postgres on this port would silently mask migration failures.
# WR-02 (Phase 1071 review): lsof is macOS/BSD-native; on Linux it may be
# absent. Fall back to nc -z (universally available on macOS and Linux) so
# the port-in-use guard works in both CI environments. The script
# auto-detects which tool is available.
_port_in_use() {
  lsof -iTCP:"${PG_PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1 \
    || nc -z 127.0.0.1 "${PG_PORT}" 2>/dev/null
}
if _port_in_use; then
  echo "ERROR: port ${PG_PORT} is already in use" >&2
  echo "       override with ALEMBIC_TEST_DB_PORT=<free-port>" >&2
  exit 1
fi

# -----------------------------------------------------------------------
# Build the test image (cache hit is fast; first run takes ~2-3 min for pgvector)
# -----------------------------------------------------------------------
echo "==> Building ${TEST_IMAGE} from ${DB_BUILD_CONTEXT} (cache-friendly)..."
docker build -q -t "${TEST_IMAGE}" "${DB_BUILD_CONTEXT}" >/dev/null

# -----------------------------------------------------------------------
# Start the throwaway container
# -----------------------------------------------------------------------
echo "==> Starting container..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "127.0.0.1:${PG_PORT}:5432" \
  -e POSTGRES_USER="${PG_USER}" \
  -e POSTGRES_PASSWORD="${PG_PASSWORD}" \
  -e POSTGRES_DB="${PG_DB}" \
  -v "${INIT_DB_SCRIPT}:/docker-entrypoint-initdb.d/10-init.sh:ro" \
  "${TEST_IMAGE}" >/dev/null

# -----------------------------------------------------------------------
# Poll readiness — three concerns:
#   1. pg_isready alone is not enough because init-db.sh runs AFTER initial
#      readiness. Poll for the `vector` extension explicitly so we don't
#      race the extension-creation step.
#   2. (Phase 1079 VG-01 fix) docker-entrypoint.sh's init-script phase
#      runs against a temporary Postgres listening ONLY on the Unix socket;
#      `pg_isready` and `docker exec ... psql` succeed via the socket during
#      this phase. After all init scripts finish, the temporary server
#      shuts down and the production server is started with TCP listening.
#      A TCP-only client (asyncpg from alembic) connecting during the
#      bootstrap-to-production transition gets `ConnectionDoesNotExistError`.
#      The fix is to ALSO probe via TCP from the host (outside the container),
#      which only succeeds once the production server is up on the mapped port.
#   3. The TCP probe uses `pg_isready` from the host if available, otherwise
#      `nc -z` on the port. Either way, the probe runs OUTSIDE `docker exec`
#      so it goes through the host port-mapping.
# -----------------------------------------------------------------------
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
  # Step 1: in-container readiness (Unix socket; passes during bootstrap)
  # Step 2: in-container extension probe (confirms init-db.sh + 10_postgis.sh ran)
  # Step 3: host-side TCP readiness (confirms production server up — bootstrap
  #         restart finished, host port-mapping is live)
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

# -----------------------------------------------------------------------
# Run alembic upgrade head from backend/
# -----------------------------------------------------------------------
echo "==> Running migration boundary/backfill smoke against the throwaway DB..."
cd "${BACKEND_DIR}"

# Export the URL in the shape backend/app/core/config.py honors (DATABASE_URL_OVERRIDE
# is the documented override surface; alembic/env.py reads settings.database_url
# which honors the override). database_ssl_mode=disable is set to skip the SSL
# negotiation that .env may default to "prefer" — the throwaway container does
# not have TLS configured.
export DATABASE_URL_OVERRIDE="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
export DATABASE_SSL_MODE="disable"
# Make sure POSTGRES_* are also exported in case any downstream tool reads them
# instead of database_url_override (defense-in-depth — settings.database_url
# falls back to building a URL from these if no override is set).
export POSTGRES_USER="${PG_USER}"
export POSTGRES_PASSWORD="${PG_PASSWORD}"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="${PG_PORT}"
export POSTGRES_DB="${PG_DB}"

# alembic/env.py does `from app.core.config import settings`, which instantiates
# Settings() at import. With no repo-root .env present in CI, three required
# fields (JWT_SECRET_KEY, GEOLENS_ADMIN_USERNAME/PASSWORD) are unset and the
# fail-fast in app/core/config.py aborts before any migration runs. This smoke
# only exercises the migration chain against a throwaway DB and never serves
# auth, so padding values are correct here. ${VAR:-default} preserves any real
# value. JWT_SECRET_KEY must be >=32 chars and not a known-public literal.
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-alembic-clean-db-smoke-padding-key-32chars}"
export GEOLENS_ADMIN_USERNAME="${GEOLENS_ADMIN_USERNAME:-admin}"
export GEOLENS_ADMIN_PASSWORD="${GEOLENS_ADMIN_PASSWORD:-admin}"

# Phase 1079 VG-01 fix: backend/ has no [build-system] in pyproject.toml, so
# the `app` package is not installed into the venv's site-packages — it is
# imported via the cwd entry on sys.path. When `uv run --no-dev` invokes the
# `alembic` console script entry point, the launcher does not implicitly add
# cwd to sys.path the way `python -c "..."` does. The alembic `env.py` then
# fails at `from app.core.config import settings` with ModuleNotFoundError.
# PYTHONPATH=. restores the cwd-on-sys.path behavior. (First live run of
# this script in Phase 1079 surfaced the bug; Phase 1071 close-gate had
# deferred the live run to Phase 1074, which also did not exercise it.)
export PYTHONPATH=.

# Phase 1079 VG-01 fix: app/core/config.py's database_connect_args returns
# `{}` (no ssl key) when database_ssl_mode='disable'. asyncpg's
# connect_utils.py:655-656 then defaults `ssl='prefer'` on TCP, which
# triggers a STARTTLS upgrade attempt against the throwaway PostGIS
# container — which has no SSL configured — and the connection drops with
# `ConnectionError: unexpected connection_lost() call`. PGSSLMODE is the
# documented asyncpg env-var hook that pre-empts the prefer default
# (connect_utils.py:653: `if ssl is None: ssl = os.getenv('PGSSLMODE')`).
# Setting PGSSLMODE=disable here is local to this script — it does NOT
# affect the running geolens stack, which connects via the app config's
# `prefer` default and a Postgres server that may legitimately offer SSL.
export PGSSLMODE=disable

TENANT_ID="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_SUFFIX="aaaaaaaa_aaaa_aaaa_aaaa_aaaaaaaaaaaa"
TENANT_SCHEMA="data_t_${TENANT_SUFFIX}"
TENANT_READER="geolens_reader_t_${TENANT_SUFFIX}"
TENANT_WRITER="geolens_writer_t_${TENANT_SUFFIX}"

# Stop immediately before 0017, then create the shape of a legacy tenant whose
# table and sequence are owned by the old shared database login. The 0017
# upgrade must adopt both objects into the per-tenant writer role.
alembic_rc=0
uv run --no-dev alembic upgrade 0016 || alembic_rc=$?
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
  echo "FAIL: 0017 did not transfer every legacy tenant table/sequence to ${TENANT_WRITER}" >&2
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

# 0017 intentionally retains cluster roles and operator-managed login grants.
# A real downgrade/re-upgrade must therefore validate and accept those safe
# members rather than treating them as reserved-name collisions.
echo "==> Running 0017 downgrade -> re-upgrade with deployed memberships..."
uv run --no-dev alembic downgrade 0016
uv run --no-dev alembic upgrade head

# -----------------------------------------------------------------------
# Drift gate: the freshly-upgraded schema must match the ORM models. This
# catches a baseline (or any migration) that has drifted from the models —
# e.g. a column added to a model without a corresponding migration. With the
# squashed single baseline this is the gate that keeps 0001_baseline and the
# models in lockstep. `alembic check` exits non-zero on any pending diff.
# -----------------------------------------------------------------------
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

# -----------------------------------------------------------------------
# Success
# -----------------------------------------------------------------------
echo ""
echo "OK: alembic upgrade head + check passed against a fresh DB (${TEST_IMAGE})"
exit 0
