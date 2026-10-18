#!/usr/bin/env bash
set -euo pipefail

APP_UID="${APP_UID:-1001}"
APP_GID="${APP_GID:-1001}"
STAGING_DIR="${UPLOAD_STAGING_DIR:-/app/staging}"
APP_HOME="${APP_HOME:-/home/appuser}"
APP_CACHE_DIR="${APP_CACHE_DIR:-${APP_HOME}/.cache}"
UV_CACHE_DIR="${UV_CACHE_DIR:-${APP_CACHE_DIR}/uv}"

probe_writable_dir() {
    local path="$1"
    local label="$2"
    local probe_file="${path}/.geolens-write-probe-$$"

    if ! touch "${probe_file}" 2>/dev/null; then
        echo "ERROR: ${label} is not writable: ${path}" >&2
        echo "Remediation: ensure mounted volume permissions allow uid:gid ${APP_UID}:${APP_GID} write access." >&2
        echo "Alternatively set UPLOAD_STAGING_DIR to a writable path for the API runtime user." >&2
        exit 1
    fi

    rm -f "${probe_file}"
}

mkdir -p "${STAGING_DIR}" "${APP_HOME}" "${UV_CACHE_DIR}"

# prometheus_client multiprocess mode, api service only (the worker's own
# /metrics endpoint stays single-process). Created here, alongside the other
# runtime-writable dirs, so the chown/chmod block below covers it: this
# container starts as root and drops to appuser via setpriv before exec, and
# the mmap-backed metric files are written by that dropped-privilege process.
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    mkdir -p "${PROMETHEUS_MULTIPROC_DIR}"
fi

if [ "$(id -u)" -eq 0 ]; then
    chown -R "${APP_UID}:${APP_GID}" "${STAGING_DIR}" "${APP_HOME}" 2>/dev/null || true
    chmod -R u+rwX,g+rwX "${STAGING_DIR}" "${APP_HOME}" 2>/dev/null || true
    probe_writable_dir "${STAGING_DIR}" "Upload staging directory"
    probe_writable_dir "${UV_CACHE_DIR}" "uv cache directory"
    if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
        chown -R "${APP_UID}:${APP_GID}" "${PROMETHEUS_MULTIPROC_DIR}" 2>/dev/null || true
        chmod -R u+rwX,g+rwX "${PROMETHEUS_MULTIPROC_DIR}" 2>/dev/null || true
    fi
else
    probe_writable_dir "${STAGING_DIR}" "Upload staging directory"
    probe_writable_dir "${UV_CACHE_DIR}" "uv cache directory"
fi

export HOME="${APP_HOME}"
export XDG_CACHE_HOME="${APP_CACHE_DIR}"
export UV_CACHE_DIR
export PYTHONPATH="/app${PYTHONPATH:+:${PYTHONPATH}}"

# Enterprise overlay: runtime install path (legacy / dev only).
#
# This runtime `uv add --editable` cannot succeed under a read_only rootfs (the
# default hardened deployment): the baked /app/.venv is on the read-only layer.
# If the install fails, the app boots as community edition and
# GEOLENS_EDITION=enterprise triggers a loud startup failure (RuntimeError)
# instead of a silent OSS fallback.
#
# Production paid deployments use the overlay repository's immutable image,
# which installs its locked wheel at build time. The public Dockerfile does not
# copy private packages. This block remains for dev/CI runs without read_only
# (for example `docker compose up` with a mounted enterprise directory).
ENTERPRISE_PATH="${GEOLENS_ENTERPRISE_PATH:-/enterprise}"
if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
    echo "Installing enterprise extensions (runtime path — only works without read_only rootfs)..."
    uv add --editable "${ENTERPRISE_PATH}" --no-dev 2>&1 || {
        echo "WARNING: Enterprise package install failed. Under read_only rootfs this is expected." >&2
        echo "Use the overlay repository's immutable image build for production." >&2
    }
    # Re-own cache after root install so appuser can access it later
    if [ "$(id -u)" -eq 0 ]; then
        chown -R "${APP_UID}:${APP_GID}" "${UV_CACHE_DIR}" 2>/dev/null || true
    fi
fi

# Run database migrations (idempotent, safe on every startup).
# The dedicated migrate service normally runs first; this default-on step is a
# fail-closed safety net for deployments that start the API directly. A
# deployment with a dedicated, ordered migrate service may set
# GEOLENS_API_RUN_MIGRATIONS=false so the least-privilege API login never tries
# to execute DDL. Any value other than the exact strings "true" and "false" is
# rejected: a typo must never silently disable the safety net.
#
# `alembic upgrade heads` against an already-migrated DB is a no-op that exits
# 0, so a non-zero exit is a real error (migration failure, DB unreachable,
# broken chain). Booting on a failed or partial migration would serve a broken
# schema, so print FATAL to stderr and exit with the migration's return code.
if [ -n "${GEOLENS_RUNTIME_DB_ROLE:-}" ] \
    && [ "${GEOLENS_API_RUN_MIGRATIONS:-true}" != "false" ]; then
    echo "FATAL: GEOLENS_RUNTIME_DB_ROLE requires GEOLENS_API_RUN_MIGRATIONS=false." >&2
    echo "       Run the ordered migrate service with MIGRATION_DATABASE_URL_OVERRIDE;" >&2
    echo "       the runtime login must never attempt schema or extension DDL." >&2
    exit 64
fi

case "${GEOLENS_API_RUN_MIGRATIONS:-true}" in
    true)
        echo "Running database migrations..."
        migration_rc=0
        if [ "$(id -u)" -eq 0 ]; then
            setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups \
                uv run --no-dev alembic upgrade heads 2>&1 || migration_rc=$?
        else
            uv run --no-dev alembic upgrade heads 2>&1 || migration_rc=$?
        fi
        if [ "${migration_rc}" -ne 0 ]; then
            echo "FATAL: database migrations failed (rc=${migration_rc}); refusing to start." >&2
            echo "       'alembic upgrade heads' is idempotent, so a non-zero exit is a real" >&2
            echo "       error (failed/partial migration, unreachable DB, or broken chain) —" >&2
            echo "       not an already-applied no-op. Check the migrate service logs and the" >&2
            echo "       DB connectivity before retrying." >&2
            exit "${migration_rc}"
        fi
        ;;
    false)
        echo "Skipping API entrypoint migrations (GEOLENS_API_RUN_MIGRATIONS=false)."
        ;;
    *)
        echo "FATAL: GEOLENS_API_RUN_MIGRATIONS must be exactly 'true' or 'false'; refusing to start." >&2
        exit 64
        ;;
esac

# Clear stale prometheus_client multiprocess mmap files before any worker
# starts. MultiProcessCollector aggregates every *.db file under the directory
# regardless of which container generation wrote it, so a leftover file (e.g.
# from a different UVICORN_WORKERS topology) would pollute the Counter and
# Histogram sums. The directory normally lives on the api tmpfs /tmp mount,
# which a restart discards; this guards an operator-set non-ephemeral path.
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    rm -f "${PROMETHEUS_MULTIPROC_DIR}"/*.db 2>/dev/null || true
fi

if [ "$#" -eq 0 ]; then
    set -- sh -c "uv run --no-dev uvicorn app.api.main:app --host 0.0.0.0 --port 8000"
fi

if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups "$@"
fi

exec "$@"
