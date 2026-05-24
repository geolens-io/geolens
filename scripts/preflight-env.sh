#!/usr/bin/env bash
# Pre-flight: verify boot-required env vars are non-empty in .env BEFORE running
# `docker compose up` (which takes 5-10 minutes on a cold cache only to crash
# at startup if these are empty).
#
# Required vars (per backend/app/core/config.py + .env.example top section):
#   - JWT_SECRET_KEY           — secret used to sign JWT access/refresh tokens
#   - GEOLENS_ADMIN_USERNAME   — admin account created on first boot
#   - GEOLENS_ADMIN_PASSWORD   — admin account password
#
# Run automatically by `make dev` unless SKIP_PREFLIGHT=1.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    cat >&2 <<EOF
Pre-flight: .env not found at $ENV_FILE

Run the installer to bootstrap one:
    bash scripts/install.sh

It copies .env.example, generates JWT_SECRET_KEY, and prompts for admin
credentials. Re-running is idempotent.
EOF
    exit 1
fi

# Read values without sourcing the file (avoids accidentally running anything
# in .env, and avoids polluting the calling shell). awk handles values that
# contain `=` correctly by returning everything after the first `=`.
read_env_value() {
    local key="$1"
    awk -F= -v k="$key" '
        $0 ~ "^"k"=" {
            sub("^"k"=", "")
            print
            exit
        }
    ' "$ENV_FILE"
}

REQUIRED=(JWT_SECRET_KEY GEOLENS_ADMIN_USERNAME GEOLENS_ADMIN_PASSWORD)
MISSING=()

for var in "${REQUIRED[@]}"; do
    value="$(read_env_value "$var" || true)"
    if [ -z "$value" ]; then
        MISSING+=("$var")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    cat >&2 <<EOF
Pre-flight: the following required vars are empty in .env:

$(printf '  - %s\n' "${MISSING[@]}")

The API container will fail to boot. To fix:
    bash scripts/install.sh        # generates secrets and prompts for admin creds

To bypass this check (e.g., for unusual deployment paths):
    make dev SKIP_PREFLIGHT=1
EOF
    exit 1
fi

echo "Pre-flight: .env required vars OK (JWT_SECRET_KEY, GEOLENS_ADMIN_USERNAME, GEOLENS_ADMIN_PASSWORD)"
