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
if lsof -iTCP:"${PG_PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
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
# Poll readiness — pg_isready alone is not enough because init-db.sh runs
# AFTER initial readiness. Poll for the `vector` extension explicitly so
# we don't race the extension-creation step.
# -----------------------------------------------------------------------
echo -n "==> Waiting up to ${WAIT_SECONDS}s for DB readiness + extensions..."
elapsed=0
while [ "${elapsed}" -lt "${WAIT_SECONDS}" ]; do
  if docker exec "${CONTAINER_NAME}" pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
    # pg_isready true → DB accepting connections. Now confirm init-db.sh ran
    # by checking for the `vector` extension (the last one init-db.sh creates
    # before COMMIT). If init-db.sh failed, the migration will fail at the
    # baseline extension-check and we want to surface that as a real failure,
    # not a readiness timeout.
    if docker exec "${CONTAINER_NAME}" \
         psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
         "SELECT 1 FROM pg_extension WHERE extname='vector'" 2>/dev/null \
         | grep -q '^1$'; then
      echo " ready."
      break
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
echo "==> Running 'alembic upgrade head' against the throwaway DB..."
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

alembic_rc=0
uv run --no-dev alembic upgrade head || alembic_rc=$?

if [ "${alembic_rc}" -ne 0 ]; then
  echo ""
  echo "FAIL: alembic upgrade head exited ${alembic_rc} against a clean DB" >&2
  echo ""
  echo "==> Container logs (last 100 lines):" >&2
  docker logs "${CONTAINER_NAME}" 2>&1 | tail -100 >&2
  exit "${alembic_rc}"
fi

# -----------------------------------------------------------------------
# Success
# -----------------------------------------------------------------------
echo ""
echo "OK: alembic upgrade head applied cleanly against a fresh DB (${TEST_IMAGE})"
exit 0
