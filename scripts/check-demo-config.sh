#!/bin/sh
# Read-only guard for the public demo's catalog-first landing contract.
set -eu

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DEMO_BASE_URL="${DEMO_BASE_URL:-https://demo.getgeolens.com}"

case "$COMPOSE_FILE" in
    /*) COMPOSE_PATH=$COMPOSE_FILE ;;
    *) COMPOSE_PATH=$PROJECT_ROOT/$COMPOSE_FILE ;;
esac

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

compose() {
    docker compose -f "$COMPOSE_PATH" \
        --project-directory "$PROJECT_ROOT" "$@"
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
[ -f "$COMPOSE_PATH" ] || fail "compose file not found: $COMPOSE_PATH"

# Render Compose so this also catches a pending .env change that would take
# effect at the next recreate. Parse in memory and emit only this non-secret
# value; never print or persist the full rendered configuration.
declared_env="$(compose config --format json | python3 -c '
import json
import sys

environment = json.load(sys.stdin)["services"]["api"]["environment"]
value = environment.get("LANDING_FIRST")
if value is None:
    raise SystemExit("api.environment.LANDING_FIRST is missing")
print("{}|{}".format(value, environment.get("ENV_ONLY_CONFIG", "false")))
')" || fail "could not resolve API LANDING_FIRST from the Compose configuration"

declared_landing=${declared_env%%|*}
declared_env_only=${declared_env#*|}

case "$(printf '%s' "$declared_landing" | tr '[:upper:]' '[:lower:]')" in
    false | 0 | no | off) ;;
    *) fail "Compose API LANDING_FIRST must resolve to false; got '$declared_landing'" ;;
esac
case "$(printf '%s' "$declared_env_only" | tr '[:upper:]' '[:lower:]')" in
    false | 0 | no | off) ;;
    *) fail "Compose API ENV_ONLY_CONFIG must remain false; got '$declared_env_only'" ;;
esac

# Inspect the running container, not only .env: a changed file has no effect
# until Compose recreates the API container.
# The single-quoted variables expand inside the API container.
# shellcheck disable=SC2016
runtime="$(compose exec -T api sh -c \
    'printf "%s|%s\n" "${LANDING_FIRST-__unset__}" "${ENV_ONLY_CONFIG-false}"')" \
    || fail "could not read the API container environment"
landing_env=${runtime%%|*}
env_only_config=${runtime#*|}

case "$(printf '%s' "$landing_env" | tr '[:upper:]' '[:lower:]')" in
    false | 0 | no | off) ;;
    *) fail "API container LANDING_FIRST must resolve to false; got '$landing_env'" ;;
esac
case "$(printf '%s' "$env_only_config" | tr '[:upper:]' '[:lower:]')" in
    false | 0 | no | off) ;;
    *) fail "API container ENV_ONLY_CONFIG must remain false; got '$env_only_config'" ;;
esac

# Query only the one configuration row. psql inherits credentials inside the
# bundled DB container, so the command does not print or copy a password.
# The single-quoted variables expand inside the DB container.
# shellcheck disable=SC2016
db_override="$(compose exec -T db sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT COALESCE(
    (SELECT value::text FROM catalog.app_settings WHERE key = 'landing_first'),
    '__unset__'
);
SQL
)" || fail "could not read catalog.app_settings"

[ "$db_override" = "__unset__" ] \
    || fail "catalog.app_settings still overrides landing_first: $db_override"

auth_config="$(curl -fsSL --max-redirs 3 --max-time 15 \
    "${DEMO_BASE_URL%/}/api/auth/config/")" \
    || fail "could not fetch the public auth configuration"
effective="$(printf '%s' "$auth_config" | python3 -c '
import json
import sys

value = json.load(sys.stdin).get("landing_first")
if not isinstance(value, bool):
    raise SystemExit("landing_first is missing or is not a boolean")
print(str(value).lower())
')" || fail "public auth configuration did not contain a boolean landing_first"

[ "$effective" = "false" ] \
    || fail "public effective landing_first must be false; got '$effective'"

printf 'PASS: demo landing configuration is catalog-first\n'
printf '  Compose LANDING_FIRST: %s\n' "$declared_landing"
printf '  API LANDING_FIRST: %s\n' "$landing_env"
printf '  API ENV_ONLY_CONFIG: %s\n' "$env_only_config"
printf '  DB landing_first override: unset\n'
printf '  Public effective landing_first: %s\n' "$effective"
