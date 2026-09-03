#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=scripts/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# fix(#1778): read only the values this check needs from .env with
# get_env_value's awk parser, not by shell-sourcing the file — see
# restore.sh for why: Compose's `.env` parser accepts values (a space, a
# backtick, `$(...)`) that `sh` does not, and shell-sourcing them under
# `set -e` either aborts on an operator-typed value or executes it.
#
# fix(#1778 review round 6, P2): same guard restore.sh uses — assign only
# when get_env_value reports the key is actually present in .env, so a
# value supplied purely through the process environment (Compose supports
# `POSTGRES_DB=production scripts/check-env.sh`) is not overwritten with an
# empty string just because .env omits that key. See restore.sh's comment
# on the same pattern for the full reasoning.
if [ -f "$PROJECT_ROOT/.env" ]; then
    if _v="$(get_env_value POSTGRES_USER "$PROJECT_ROOT/.env")"; then
        POSTGRES_USER="$_v"
    fi
    if _v="$(get_env_value POSTGRES_PASSWORD "$PROJECT_ROOT/.env")"; then
        # shellcheck disable=SC2034  # read via `${!var}` in the Section 1 loop below
        POSTGRES_PASSWORD="$_v"
    fi
    if _v="$(get_env_value POSTGRES_DB "$PROJECT_ROOT/.env")"; then
        POSTGRES_DB="$_v"
    fi
fi

ERRORS=0

pass() {
    echo "  OK: $*"
}

fail() {
    echo "  FAIL: $*" >&2
    ERRORS=$((ERRORS + 1))
}

# Section 1: Environment Variables
echo "=== Environment Variables ==="
for var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if [ -n "${!var:-}" ]; then
        pass "$var is set"
    else
        fail "$var is not set"
    fi
done

# Section 2: Database Connectivity
echo "=== Database Connectivity ==="
if docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    pg_isready -U "${POSTGRES_USER:-geolens}" -d "${POSTGRES_DB:-geolens}" > /dev/null 2>&1; then
    pass "Database is accepting connections"
else
    fail "Database is not reachable"
fi

# Section 3: GDAL Availability
echo "=== GDAL Availability ==="
if docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T api ogrinfo --version > /dev/null 2>&1; then
    pass "GDAL (ogrinfo) is available in api container"
else
    fail "GDAL (ogrinfo) is not available in api container"
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "$ERRORS check(s) failed." >&2
    exit 1
fi

echo "All checks passed."
