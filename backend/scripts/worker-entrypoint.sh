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

# Enterprise overlay — runtime install path (legacy / dev only).
#
# WARNING (BUG-003): This runtime `uv add --editable` CANNOT succeed when the
# container runs with read_only: true rootfs (the default hardened deployment).
# The baked /app/.venv is on the read-only layer and uv cannot write into it.
# If this block runs and the install fails, the app will boot as community
# edition; GEOLENS_EDITION=enterprise will now trigger a loud startup failure
# rather than a silent OSS fallback.
#
# The architecturally correct path for production Enterprise deployments is to
# pre-bake the overlay into the image at BUILD TIME using:
#   docker build --build-arg INSTALL_ENTERPRISE_OVERLAY=1 ...
# (see ARG INSTALL_ENTERPRISE_OVERLAY in Dockerfile)
#
# This block is retained for dev/CI scenarios where the container runs without
# read_only (e.g. `docker compose up` for local development with a mounted
# enterprise directory).  It will fail silently under read_only — the startup
# checks (BUG-003: check_enterprise_overlay_requested + WORK-02:
# assert_enterprise_ports_resolved) now run inside the WORKER bootstrap as well
# as the API lifespan, so a GEOLENS_EDITION=enterprise worker that cannot load
# the overlay will refuse to boot rather than silently running community ports.
ENTERPRISE_PATH="${GEOLENS_ENTERPRISE_PATH:-/enterprise}"
if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
    echo "Installing enterprise extensions (runtime path — only works without read_only rootfs)..."
    uv add --editable "${ENTERPRISE_PATH}" --no-dev 2>&1 || {
        echo "WARNING: Enterprise package install failed. Under read_only rootfs this is expected." >&2
        echo "Use the build-time bake path (ARG INSTALL_ENTERPRISE_OVERLAY in Dockerfile) for production." >&2
    }
    # Re-own cache after root install so appuser can access it later
    if [ "$(id -u)" -eq 0 ]; then
        chown -R "${APP_UID}:${APP_GID}" "${UV_CACHE_DIR}" 2>/dev/null || true
    fi
fi

if [ "$#" -eq 0 ]; then
    set -- sh -c "uv run --no-dev python -m app.worker"
fi

if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups "$@"
fi

exec "$@"
