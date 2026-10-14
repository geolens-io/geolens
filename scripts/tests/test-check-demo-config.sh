#!/bin/sh
set -eu

REPO_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
FAKE_BIN="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN"' EXIT HUP INT TERM

cat >"$FAKE_BIN/docker" <<'EOF'
#!/bin/sh
case " $* " in
    *" config --format json "*) printf '{"services":{"api":{"environment":{"LANDING_FIRST":"%s","ENV_ONLY_CONFIG":"%s"}}}}\n' "${TEST_DECLARED_ENV:-false}" "${TEST_DECLARED_ENV_ONLY:-false}" ;;
    *" ps -q "*) printf 'container-a\n' ;;
    *" inspect "*) printf '%s\n' "${TEST_CONFIG_FILES:-$TEST_PROD_PATH}" ;;
    *" exec -T api "*) printf '%s|%s\n' "${TEST_LANDING_ENV:-false}" "${TEST_ENV_ONLY_CONFIG:-false}" ;;
    *" exec -T db "*) printf '%s\n' "${TEST_DB_OVERRIDE:-__unset__}" ;;
    *) exit 2 ;;
esac
EOF

cat >"$FAKE_BIN/curl" <<'EOF'
#!/bin/sh
printf '{"landing_first":%s}\n' "${TEST_EFFECTIVE:-false}"
EOF

chmod +x "$FAKE_BIN/docker" "$FAKE_BIN/curl"

TEST_PROD_PATH="$REPO_ROOT/docker-compose.prod.yml"
export TEST_PROD_PATH

PATH="$FAKE_BIN:$PATH" "$REPO_ROOT/scripts/check-demo-config.sh" >/dev/null

if TEST_DECLARED_ENV=true PATH="$FAKE_BIN:$PATH" \
    "$REPO_ROOT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: a pending Compose true value was accepted\n' >&2
    exit 1
fi

if TEST_DECLARED_ENV_ONLY=true PATH="$FAKE_BIN:$PATH" \
    "$REPO_ROOT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: an ENV_ONLY_CONFIG shortcut was accepted\n' >&2
    exit 1
fi

if TEST_DB_OVERRIDE='{"v": true}' PATH="$FAKE_BIN:$PATH" \
    "$REPO_ROOT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: a DB override was accepted\n' >&2
    exit 1
fi

if TEST_EFFECTIVE=true PATH="$FAKE_BIN:$PATH" \
    "$REPO_ROOT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: an effective true value was accepted\n' >&2
    exit 1
fi

# A COMPOSE_FILE list is honored, and containers created from fewer files
# than the list are reported.
PROJECT="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$PROJECT"' EXIT HUP INT TERM
mkdir -p "$PROJECT/scripts"
cp -R "$REPO_ROOT/scripts/lib" "$REPO_ROOT/scripts/env-value.sh" \
    "$REPO_ROOT/scripts/check-demo-config.sh" "$PROJECT/scripts/"
: >"$PROJECT/docker-compose.prod.yml"
: >"$PROJECT/override.yml"
printf 'COMPOSE_FILE=docker-compose.prod.yml:override.yml\n' >"$PROJECT/.env"
LISTED="$PROJECT/docker-compose.prod.yml,$PROJECT/override.yml"

if ! TEST_CONFIG_FILES=$LISTED PATH="$FAKE_BIN:$PATH" \
    "$PROJECT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: containers matching the .env COMPOSE_FILE list were rejected\n' >&2
    exit 1
fi

printf 'COMPOSE_FILE=./docker-compose.prod.yml:override.yml\n' >"$PROJECT/.env"
if ! TEST_CONFIG_FILES=$LISTED PATH="$FAKE_BIN:$PATH" \
    "$PROJECT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: an equivalent ./ spelling reported false drift\n' >&2
    exit 1
fi
printf 'COMPOSE_FILE=docker-compose.prod.yml:override.yml\n' >"$PROJECT/.env"

mkdir -p "$PROJECT/overrides"
printf 'COMPOSE_FILE=overrides/../docker-compose.prod.yml:override.yml\n' >"$PROJECT/.env"
if ! TEST_CONFIG_FILES=$LISTED PATH="$FAKE_BIN:$PATH" \
    "$PROJECT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: a ../ spelling reported false drift\n' >&2
    exit 1
fi
printf 'COMPOSE_FILE=docker-compose.prod.yml:override.yml\n' >"$PROJECT/.env"

if TEST_CONFIG_FILES=$PROJECT/docker-compose.prod.yml PATH="$FAKE_BIN:$PATH" \
    "$PROJECT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: a container missing the override file was accepted\n' >&2
    exit 1
fi

if TEST_CONFIG_FILES=$LISTED COMPOSE_FILE=missing.yml PATH="$FAKE_BIN:$PATH" \
    "$PROJECT/scripts/check-demo-config.sh" >/dev/null 2>&1; then
    printf 'FAIL: a missing compose file was accepted\n' >&2
    exit 1
fi

printf 'PASS: demo config checker accepts the intended state and rejects drift\n'
