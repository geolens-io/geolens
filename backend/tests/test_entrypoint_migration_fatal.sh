#!/usr/bin/env bash
# test_entrypoint_migration_fatal.sh — MIG-01 regression test.
#
# Asserts that backend/scripts/api-entrypoint.sh FAILS CLOSED when the
# `alembic upgrade heads` step exits non-zero: the entrypoint must exit
# non-zero AND must never reach the uvicorn exec.
#
# How it works:
#   - A throwaway $BIN dir is prepended to PATH containing stubs for the
#     external commands the entrypoint shells out to:
#       * `uv`      — when invoked as `uv run ... alembic upgrade heads`,
#                     exits 1 (simulates a migration failure). For any other
#                     `uv run ...` (the enterprise overlay install path) it
#                     exits 0 so only the migration step trips.
#       * `setpriv` — passthrough (the test runs as non-root anyway, so the
#                     `id -u != 0` branch is taken; stub present for safety).
#       * `uvicorn` — writes a sentinel file. If the entrypoint ever execs
#                     the server, the sentinel appears → the fail-closed
#                     guard regressed.
#   - We also stub the writable-dir probe surface by pointing the staging /
#     home / cache dirs at writable temp paths so the probe passes and we
#     reach the migration step.
#   - The default `set -- sh -c "uv run ... uvicorn ..."` command runs uvicorn
#     via `uv run`, so the `uv` stub also detects a uvicorn invocation and
#     writes the sentinel — covering the exec path through `sh -c`.
#
# Run:
#   cd backend && ./tests/test_entrypoint_migration_fatal.sh
#
# Exit 0 = PASS (entrypoint failed closed). Exit 1 = FAIL.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENTRYPOINT="${BACKEND_DIR}/scripts/api-entrypoint.sh"

if [ ! -x "${ENTRYPOINT}" ] && [ ! -f "${ENTRYPOINT}" ]; then
  echo "FAIL: entrypoint not found at ${ENTRYPOINT}" >&2
  exit 1
fi

WORK="$(mktemp -d)"
BIN="${WORK}/bin"
SENTINEL="${WORK}/uvicorn-ran.sentinel"
mkdir -p "${BIN}" "${WORK}/staging" "${WORK}/home" "${WORK}/home/.cache/uv"

cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT INT TERM

# --- stub: uv -----------------------------------------------------------
# `uv run --no-dev alembic upgrade heads`  -> exit 1 (migration failure)
# `uv run ... uvicorn ...` / `uv add ...`  -> writes sentinel if uvicorn,
#                                             else exit 0.
cat > "${BIN}/uv" <<EOF
#!/usr/bin/env bash
for arg in "\$@"; do
  case "\$arg" in
    *uvicorn*) echo "STUB-UV: uvicorn would have started" >&2; touch "${SENTINEL}"; exit 0 ;;
  esac
done
# Detect the migration invocation: alembic upgrade heads
case "\$*" in
  *"alembic upgrade heads"*)
    echo "STUB-UV: simulating alembic upgrade heads FAILURE" >&2
    exit 1
    ;;
esac
# Any other uv invocation (e.g. enterprise overlay install) is a no-op success.
exit 0
EOF
chmod +x "${BIN}/uv"

# --- stub: uvicorn (direct exec path, defense in depth) -----------------
cat > "${BIN}/uvicorn" <<EOF
#!/usr/bin/env bash
echo "STUB-UVICORN: server would have started" >&2
touch "${SENTINEL}"
exit 0
EOF
chmod +x "${BIN}/uvicorn"

# --- stub: setpriv (passthrough) ----------------------------------------
cat > "${BIN}/setpriv" <<'EOF'
#!/usr/bin/env bash
# Drop the setpriv-specific flags and exec the remaining command.
while [ "$#" -gt 0 ]; do
  case "$1" in
    --reuid=*|--regid=*|--clear-groups) shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
exec "$@"
EOF
chmod +x "${BIN}/setpriv"

echo "==> Running entrypoint with stubbed failing 'alembic upgrade heads'..."
entry_rc=0
PATH="${BIN}:${PATH}" \
  APP_UID="$(id -u)" \
  APP_GID="$(id -g)" \
  UPLOAD_STAGING_DIR="${WORK}/staging" \
  APP_HOME="${WORK}/home" \
  GEOLENS_ENTERPRISE_PATH="${WORK}/no-enterprise-here" \
  bash "${ENTRYPOINT}" 2> "${WORK}/stderr.log" || entry_rc=$?

echo "----- entrypoint stderr -----"
cat "${WORK}/stderr.log"
echo "-----------------------------"
echo "entrypoint exit code: ${entry_rc}"

fail=0

# Assertion 1: entrypoint must exit non-zero.
if [ "${entry_rc}" -eq 0 ]; then
  echo "FAIL: entrypoint exited 0 despite a failed migration (expected non-zero)." >&2
  fail=1
else
  echo "OK: entrypoint exited non-zero (${entry_rc}) on migration failure."
fi

# Assertion 2: uvicorn must NEVER have run (sentinel absent).
if [ -f "${SENTINEL}" ]; then
  echo "FAIL: uvicorn sentinel present — the server started despite the migration failure." >&2
  fail=1
else
  echo "OK: uvicorn never started (sentinel absent)."
fi

# Assertion 3: a clear FATAL message must be emitted to stderr.
if grep -q "FATAL: database migrations failed" "${WORK}/stderr.log"; then
  echo "OK: FATAL fail-closed message present in stderr."
else
  echo "FAIL: expected 'FATAL: database migrations failed' message not found in stderr." >&2
  fail=1
fi

if [ "${fail}" -ne 0 ]; then
  echo ""
  echo "RESULT: FAIL (MIG-01 fail-closed guard regressed)" >&2
  exit 1
fi

echo ""
echo "RESULT: PASS (MIG-01 — entrypoint fails closed on migration error)"
exit 0
