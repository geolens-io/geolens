#!/usr/bin/env bash
# Pre-flight: verify boot-required env vars are non-empty BEFORE running
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
# Each value is read the way Compose resolves it: from the exported
# environment when that sets the name (even to an empty string), else .env.
#
# The whole file is checked first: a line Compose cannot load stops
# `docker compose up` whatever key it holds, so it is refused here by line.
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

# fix(#1882 codex r2): read through the shared parser, never a local one.
# A value may be quoted and may carry a trailing `# comment`, both valid
# Compose forms; a second parser here read the comment as part of the value
# and failed a well-formed key. get_env_value still never sources .env.
# shellcheck source=scripts/lib/common.sh
. "$PROJECT_ROOT/scripts/lib/common.sh"

# fix(#1886): an exported name overrides its .env line for Compose, so every
# check below runs on the value the API container will actually receive.
value_source() {
    if env_is_exported "$1"; then
        echo "your shell environment (which overrides .env)"
    else
        echo ".env"
    fi
}

# fix(#1899): Compose loads every line of .env before anything else, so the
# whole file is checked first and the first line it would refuse is named.
check_env_file() {
    local hit line key reason why
    hit="$(env_file_first_refused_line "$ENV_FILE")" || return 0
    # "LINE KEY REASON", split by expansion: a key may hold `[`, which globs.
    line="${hit%% *}"
    reason="${hit##* }"
    key="${hit#* }"
    key="${key% *}"
    case "$reason" in
        whitespace-in-key) why="its key contains a space" ;;
        unexpected-character) why="its key contains a character docker compose does not allow" ;;
        unterminated-quote) why="its quoted value never closes" ;;
        *) why="a \${NAME:?message} reference names a NAME that is not set, or a \${ never closes" ;;
    esac
    cat >&2 <<EOF
Pre-flight: .env line $line ($key) cannot be loaded by docker compose: $why.

Compose reads every line of .env before it applies your shell environment, so
\`docker compose up\` stops on this line even if the key is not one GeoLens
reads. Fix or remove the line in .env.
EOF
    exit 1
}

# Sets \`value\` to what Compose will pass for $1. rc 2 (a line Compose
# refuses) cannot occur once check_env_file has passed; it re-runs the check.
read_effective() {
    value=""
    rc=0
    effective_env_value_into value "$1" "$ENV_FILE" || rc=$?
    if [ "$rc" -eq 2 ]; then
        check_env_file
    fi
}

check_env_file

REQUIRED=(JWT_SECRET_KEY GEOLENS_ADMIN_USERNAME GEOLENS_ADMIN_PASSWORD)
MISSING=()

for var in "${REQUIRED[@]}"; do
    read_effective "$var"
    if [ -z "$value" ]; then
        MISSING+=("$var, read from $(value_source "$var")")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    cat >&2 <<EOF
Pre-flight: the following required vars are empty:

$(printf '  - %s\n' "${MISSING[@]}")

The API container will fail to boot. To fix:
    bash scripts/install.sh        # generates secrets and prompts for admin creds

A name exported in your shell overrides its .env line; unset it to use .env.

To bypass this check (e.g., for unusual deployment paths):
    make dev SKIP_PREFLIGHT=1
EOF
    exit 1
fi

# A Fernet key is 32 bytes of url-safe base64: 43 characters plus one `=`.
# Accept the standard alphabet too (`+/`), because base64.urlsafe_b64decode
# does, and refusing a value the app takes would be a false failure.
for var in SECRET_ENCRYPTION_KEY SECRET_ENCRYPTION_KEY_PREVIOUS; do
    read_effective "$var"
    if [ -n "$value" ] && ! printf '%s' "$value" | grep -Eq '^[A-Za-z0-9+/_-]{43}=$'; then
        cat >&2 <<EOF
Pre-flight: $var in $(value_source "$var") is not a valid encryption key.

The API refuses to boot on a malformed value. It must be url-safe base64 of 32
random bytes, which is not what \`openssl rand -hex 32\` produces:

    openssl rand -base64 32 | tr '+/' '-_'

Unset it to fall back to a key derived from JWT_SECRET_KEY. RUNBOOK.md
section 11 covers what each choice means for rotation.
EOF
        exit 1
    fi
done

echo "Pre-flight: required vars OK (JWT_SECRET_KEY, GEOLENS_ADMIN_USERNAME, GEOLENS_ADMIN_PASSWORD)"
