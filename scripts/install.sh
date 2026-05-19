#!/bin/sh
set -eu

REPO_URL="${GEOLENS_REPO_URL:-https://github.com/geolens-io/geolens.git}"
INSTALL_DIR="${GEOLENS_INSTALL_DIR:-geolens}"

# Restore terminal echo if interrupted between stty -echo / stty echo.
trap 'stty echo </dev/tty 2>/dev/null; exit 130' INT TERM

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'Warning: %s\n' "$*" >&2
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required but was not found"
}

# Detect a usable controlling terminal once. `[ -r /dev/tty ]` is not enough —
# the device file can be readable per perms while open(2) fails with ENXIO when
# there is no controlling terminal (e.g., `curl ... | sh` in some contexts).
HAS_TTY=false
if (printf '' >/dev/tty) 2>/dev/null; then
  HAS_TTY=true
fi

generate_jwt_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi
  if [ -r /dev/urandom ]; then
    LC_ALL=C tr -dc 'a-f0-9' </dev/urandom 2>/dev/null | dd bs=1 count=64 2>/dev/null
    printf '\n'
    return
  fi
  fail "cannot generate JWT_SECRET_KEY: install openssl, or run on a host with /dev/urandom."
}

check_port() {
  port="$1"
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "port $port is already in use. Set the matching *_PORT value in .env before starting GeoLens."
  fi
}

disk_available_kb() {
  df -k . 2>/dev/null | awk 'NR == 2 {print $4} END {if (NR < 2) print 0}'
}

memory_total_kb() {
  if command -v sysctl >/dev/null 2>&1 && sysctl -n hw.memsize >/dev/null 2>&1; then
    sysctl -n hw.memsize | awk '{print int($1 / 1024)}'
  elif [ -r /proc/meminfo ]; then
    awk '/MemTotal/ {print $2}' /proc/meminfo
  else
    printf '0\n'
  fi
}

# Read a value from .env. Handles values containing `=` correctly (returns the
# full remainder after the first `=`). Returns empty if the key is missing or
# the value is empty.
get_env_value() {
  key="$1"
  awk -v k="$key" '
    {
      pat = "^" k "="
      if ($0 ~ pat) {
        print substr($0, length(k) + 2)
        exit
      }
    }
  ' .env
}

# Replace `KEY=...` in .env (or append if missing). Pass the value via ENVIRON
# rather than `awk -v` so backslashes in passwords are preserved verbatim —
# `awk -v val=foo\bar` would interpret `\b` as a backspace.
update_env_value() {
  key="$1"
  value="$2"
  tmp=".env.tmp.$$"

  __VAL="$value" awk -v key="$key" '
    BEGIN { val = ENVIRON["__VAL"]; updated = 0 }
    $0 ~ "^" key "=" {
      print key "=" val
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" val
      }
    }
  ' .env > "$tmp"
  mv "$tmp" .env
}

# Ask for a value: env-var override > tty prompt > default.
# Args: label default secret(true|false) envvar
prompt_value() {
  label="$1"
  default="$2"
  secret="${3:-false}"
  envvar="${4:-}"

  if [ -n "$envvar" ]; then
    eval "envval=\${$envvar:-}"
    if [ -n "$envval" ]; then
      printf '%s\n' "$envval"
      return
    fi
  fi

  if [ "$HAS_TTY" = "true" ]; then
    if [ "$secret" = "true" ]; then
      printf '%s [%s]: ' "$label" "$default" >/dev/tty
      stty -echo </dev/tty 2>/dev/null || true
      IFS= read -r value </dev/tty || value=""
      stty echo </dev/tty 2>/dev/null || true
      printf '\n' >/dev/tty
    else
      printf '%s [%s]: ' "$label" "$default" >/dev/tty
      IFS= read -r value </dev/tty || value=""
    fi
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return
    fi
  fi

  printf '%s\n' "$default"
}

say "GeoLens installer"
say "Repository: $REPO_URL"
say "Install directory: $INSTALL_DIR"

need_command git
need_command docker

docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required. Install Docker Desktop or the docker compose plugin."

mem_kb="$(memory_total_kb)"
if [ "$mem_kb" -gt 0 ] && [ "$mem_kb" -lt 4194304 ]; then
  warn "this host reports less than 4 GB RAM. GeoLens may start slowly or fail under raster workloads."
fi

disk_kb="$(disk_available_kb)"
[ -n "$disk_kb" ] || disk_kb=0
if [ "$disk_kb" -gt 0 ] && [ "$disk_kb" -lt 10485760 ]; then
  warn "less than 10 GB disk is available in the current filesystem."
fi

# If the user already cd'd into a checkout, use it. Otherwise honor INSTALL_DIR.
PROJECT_HINT=""
if [ -f docker-compose.yml ] && [ -f .env.example ]; then
  say "Using current directory: $(pwd)"
elif [ -d "$INSTALL_DIR/.git" ]; then
  say "Using existing checkout: $INSTALL_DIR"
  cd "$INSTALL_DIR"
  PROJECT_HINT="$INSTALL_DIR"
elif [ -e "$INSTALL_DIR" ]; then
  fail "$INSTALL_DIR exists but is not a Git checkout. Move it or set GEOLENS_INSTALL_DIR."
else
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  PROJECT_HINT="$INSTALL_DIR"
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

# JWT_SECRET_KEY: generate iff missing or empty. Existing real values are kept.
existing_jwt="$(get_env_value JWT_SECRET_KEY)"
if [ -z "$existing_jwt" ]; then
  jwt="$(generate_jwt_secret)"
  update_env_value JWT_SECRET_KEY "$jwt"
  say "Generated JWT_SECRET_KEY."
fi

# Admin credentials: prompt only if either is empty. Honors GEOLENS_ADMIN_USERNAME /
# GEOLENS_ADMIN_PASSWORD env vars for non-interactive installs.
existing_admin_user="$(get_env_value GEOLENS_ADMIN_USERNAME)"
existing_admin_pass="$(get_env_value GEOLENS_ADMIN_PASSWORD)"
if [ -z "$existing_admin_user" ] || [ -z "$existing_admin_pass" ]; then
  admin_user="$(prompt_value 'Admin username' 'admin' false GEOLENS_ADMIN_USERNAME)"
  admin_password="$(prompt_value 'Admin password' 'admin' true GEOLENS_ADMIN_PASSWORD)"
  update_env_value GEOLENS_ADMIN_USERNAME "$admin_user"
  update_env_value GEOLENS_ADMIN_PASSWORD "$admin_password"
else
  say ".env already has admin credentials; leaving unchanged."
fi

# Read the configured ports from .env so the in-use check matches what compose
# will actually bind, even if the user changed DB_PORT/API_PORT/FRONTEND_PORT.
db_port="$(get_env_value DB_PORT)"
api_port="$(get_env_value API_PORT)"
fe_port="$(get_env_value FRONTEND_PORT)"
[ -n "$db_port" ] || db_port=5434
[ -n "$api_port" ] || api_port=8001
[ -n "$fe_port" ] || fe_port=8080

check_port "$db_port"
check_port "$api_port"
check_port "$fe_port"

say "Starting GeoLens..."
docker compose up -d

# Wait up to 90s for the stack to become healthy. The migrate one-shot must
# exit 0; every healthcheck-having service must report (healthy). If migrate
# fails or the wait times out, surface the failing service with its log tail
# and exit non-zero — silent "Starting..." on a dead stack is the worst kind
# of false success signal.
wait_for_healthy() {
  attempts=18
  sleep_s=5
  i=0
  while [ "$i" -lt "$attempts" ]; do
    i=$((i + 1))

    migrate_cid=$(docker compose ps -aq migrate 2>/dev/null | head -n 1)
    if [ -n "$migrate_cid" ]; then
      migrate_state=$(docker inspect --format '{{.State.Status}}' "$migrate_cid" 2>/dev/null || printf '')
      if [ "$migrate_state" = "exited" ]; then
        migrate_exit=$(docker inspect --format '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || printf '?')
        if [ "$migrate_exit" != "0" ]; then
          printf '\n' >&2
          warn "migrate one-shot exited with code $migrate_exit. Last 30 log lines:"
          docker compose logs --tail 30 migrate 2>&1 | sed 's/^/  /' >&2
          return 1
        fi
      fi
    fi

    unhealthy=$(docker compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '^$' || true)
    if [ -z "$unhealthy" ]; then
      printf '\n'
      return 0
    fi

    if [ "$i" -eq 1 ]; then
      printf 'Waiting for services to become healthy'
    else
      printf '.'
    fi
    sleep "$sleep_s"
  done

  printf '\n' >&2
  warn "timed out after $((attempts * sleep_s))s waiting for services. Current status:"
  docker compose ps 2>&1 | sed 's/^/  /' >&2
  warn "Inspect with: docker compose ps  /  docker compose logs <service>"
  return 1
}

if ! wait_for_healthy; then
  fail "GeoLens did not come up cleanly. See the failing service output above."
fi

say ""
say "GeoLens is ready."
say "UI:  http://localhost:${fe_port}"
say "API: http://localhost:${api_port}"
say ""
say "Check service health with:"
if [ -n "$PROJECT_HINT" ]; then
  say "  cd $PROJECT_HINT && docker compose ps"
else
  say "  docker compose ps"
fi
