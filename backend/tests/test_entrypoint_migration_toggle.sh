#!/usr/bin/env bash
# Regression coverage for the API entrypoint's explicit migration toggle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENTRYPOINT="${BACKEND_DIR}/scripts/api-entrypoint.sh"

WORK="$(mktemp -d)"
BIN="${WORK}/bin"
UV_LOG="${WORK}/uv.log"
STARTED="${WORK}/started"
mkdir -p "${BIN}" "${WORK}/staging" "${WORK}/home/.cache/uv"

cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT INT TERM

# This stub records every uv invocation. The disabled and invalid cases below
# must never call it, which proves they cannot accidentally attempt DDL.
cat > "${BIN}/uv" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${UV_LOG}"
exit 0
EOF
chmod +x "${BIN}/uv"

run_entrypoint() {
    PATH="${BIN}:${PATH}" \
        APP_UID="$(id -u)" \
        APP_GID="$(id -g)" \
        UPLOAD_STAGING_DIR="${WORK}/staging" \
        APP_HOME="${WORK}/home" \
        GEOLENS_ENTERPRISE_PATH="${WORK}/no-enterprise-here" \
        bash "${ENTRYPOINT}" sh -c "touch '${STARTED}'"
}

echo "==> GEOLENS_API_RUN_MIGRATIONS=false skips DDL and starts the API command"
GEOLENS_API_RUN_MIGRATIONS=false run_entrypoint > "${WORK}/disabled.out" 2>&1
test -f "${STARTED}"
test ! -s "${UV_LOG}"
grep -q "Skipping API entrypoint migrations" "${WORK}/disabled.out"

rm -f "${STARTED}" "${UV_LOG}"

echo "==> an invalid migration-toggle value fails closed before DDL or API startup"
invalid_rc=0
GEOLENS_API_RUN_MIGRATIONS=typo run_entrypoint > "${WORK}/invalid.out" 2>&1 || invalid_rc=$?
test "${invalid_rc}" -eq 64
test ! -f "${STARTED}"
test ! -s "${UV_LOG}"
grep -q "must be exactly 'true' or 'false'" "${WORK}/invalid.out"

echo "RESULT: PASS (API entrypoint migration toggle is explicit and fail-closed)"
