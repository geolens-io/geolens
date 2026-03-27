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

if [ "$(id -u)" -eq 0 ]; then
    chown -R "${APP_UID}:${APP_GID}" "${STAGING_DIR}" "${APP_HOME}" 2>/dev/null || true
    chmod -R u+rwX,g+rwX "${STAGING_DIR}" "${APP_HOME}" 2>/dev/null || true
    probe_writable_dir "${STAGING_DIR}" "Upload staging directory"
    probe_writable_dir "${UV_CACHE_DIR}" "uv cache directory"
else
    probe_writable_dir "${STAGING_DIR}" "Upload staging directory"
    probe_writable_dir "${UV_CACHE_DIR}" "uv cache directory"
fi

export HOME="${APP_HOME}"
export XDG_CACHE_HOME="${APP_CACHE_DIR}"
export UV_CACHE_DIR

# Install enterprise extensions if mounted
# Uses `uv add --editable` so the package is visible in the uv-managed venv
# that `uv run uvicorn` uses. Plain `uv pip install` would install to system
# Python which is invisible to the project environment.
ENTERPRISE_PATH="${GEOLENS_ENTERPRISE_PATH:-/enterprise}"
if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
    echo "Installing enterprise extensions..."
    uv add --editable "${ENTERPRISE_PATH}" 2>&1 || {
        echo "WARNING: Enterprise package install failed" >&2
    }
    # Re-own cache after root install so appuser can access it later
    if [ "$(id -u)" -eq 0 ]; then
        chown -R "${APP_UID}:${APP_GID}" "${UV_CACHE_DIR}" 2>/dev/null || true
    fi
fi

# Run database migrations (idempotent — safe to run on every startup)
echo "Running database migrations..."
if [ "$(id -u)" -eq 0 ]; then
    setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups \
        uv run alembic upgrade head 2>&1 || {
        echo "WARNING: Alembic migration failed (database may not be ready yet)" >&2
    }
else
    uv run alembic upgrade head 2>&1 || {
        echo "WARNING: Alembic migration failed (database may not be ready yet)" >&2
    }
fi

if [ "$#" -eq 0 ]; then
    set -- sh -c "uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
fi

if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups "$@"
fi

exec "$@"
