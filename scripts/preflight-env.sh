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
# Optional vars checked only for shape, when present:
#   - SECRET_ENCRYPTION_KEY: encrypts stored SSO secrets at rest
#   - SECRET_ENCRYPTION_KEY_PREVIOUS: the key it replaced, during a rotation
# Both must be url-safe base64 of 32 random bytes, and a malformed value fails
# API boot. Leaving them unset is fine; the app derives a key from
# JWT_SECRET_KEY instead. See RUNBOOK.md section 11.
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

# A Fernet key is 32 bytes of url-safe base64: 43 characters plus one `=`.
# Accept the standard alphabet too (`+/`), because base64.urlsafe_b64decode
# does, and refusing a value the app takes would be a false failure. Surrounding
# quotes are stripped first for the same reason: the dotenv parser drops them.
for var in SECRET_ENCRYPTION_KEY SECRET_ENCRYPTION_KEY_PREVIOUS; do
    value="$(read_env_value "$var" || true)"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    if [ -n "$value" ] && ! printf '%s' "$value" | grep -Eq '^[A-Za-z0-9+/_-]{43}=$'; then
        cat >&2 <<EOF
Pre-flight: $var in .env is not a valid encryption key.

The API refuses to boot on a malformed value. It must be url-safe base64 of 32
random bytes, which is not what \`openssl rand -hex 32\` produces:

    openssl rand -base64 32 | tr '+/' '-_'

Unset it to fall back to a key derived from JWT_SECRET_KEY. RUNBOOK.md
section 11 covers what each choice means for rotation.
EOF
        exit 1
    fi
done

echo "Pre-flight: .env required vars OK (JWT_SECRET_KEY, GEOLENS_ADMIN_USERNAME, GEOLENS_ADMIN_PASSWORD)"
