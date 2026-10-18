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
        echo "Alternatively set UPLOAD_STAGING_DIR to a writable path for the worker runtime user." >&2
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
export PYTHONPATH="/app${PYTHONPATH:+:${PYTHONPATH}}"

# Enterprise overlay: runtime install path (legacy / dev only).
#
# This runtime `uv add --editable` cannot succeed under a read_only rootfs (the
# default hardened deployment): the baked /app/.venv is on the read-only layer.
# If the install fails, the app boots as community edition and
# GEOLENS_EDITION=enterprise triggers a loud startup failure instead of a
# silent OSS fallback. check_enterprise_overlay_requested and
# assert_enterprise_ports_resolved run in the worker bootstrap as well as the
# API lifespan, so an enterprise worker that cannot load the overlay refuses to
# boot rather than running community ports.
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

# The worker does not run database migrations. It relies on
# `depends_on: migrate (service_completed_successfully)` in docker-compose so
# the dedicated migrate service has already upgraded the schema. The fail-closed
# migration guard lives in api-entrypoint.sh; the worker's own fail-loud startup
# guards (overlay check, port-resolution assertion, schema-skew guard) run in
# the Python bootstrap, app/platform/jobs/worker.py:main().
if [ "$#" -eq 0 ]; then
    set -- sh -c "uv run --no-dev python -m app.worker"
fi

if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups "$@"
fi

exec "$@"
