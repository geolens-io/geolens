#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$PROJECT_ROOT/.env"
    set +a
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
