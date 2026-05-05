#!/bin/sh
set -eu

REPO_URL="${GEOLENS_REPO_URL:-https://github.com/geolens-io/geolens.git}"
INSTALL_DIR="${GEOLENS_INSTALL_DIR:-geolens}"

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

check_port() {
  port="$1"
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "port $port is already in use. Set the matching *_PORT value in .env before starting GeoLens."
  fi
}

disk_available_kb() {
  df -k . 2>/dev/null | awk 'NR == 2 {print $4}'
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

prompt_value() {
  label="$1"
  default="$2"
  secret="${3:-false}"

  if [ -r /dev/tty ]; then
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

update_env_value() {
  key="$1"
  value="$2"
  tmp=".env.tmp.$$"

  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    $0 ~ "^" key "=" {
      print key "=" value
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" value
      }
    }
  ' .env > "$tmp"
  mv "$tmp" .env
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

disk_kb="$(disk_available_kb || printf '0\n')"
if [ "$disk_kb" -gt 0 ] && [ "$disk_kb" -lt 10485760 ]; then
  warn "less than 10 GB disk is available in the current filesystem."
fi

check_port 5434
check_port 8001
check_port 8080

if [ -d "$INSTALL_DIR/.git" ]; then
  say "Using existing checkout: $INSTALL_DIR"
elif [ -e "$INSTALL_DIR" ]; then
  fail "$INSTALL_DIR exists but is not a Git checkout. Move it or set GEOLENS_INSTALL_DIR."
else
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  admin_user="$(prompt_value 'Admin username' 'admin' false)"
  admin_password="$(prompt_value 'Admin password' 'admin' true)"
  update_env_value GEOLENS_ADMIN_USERNAME "$admin_user"
  update_env_value GEOLENS_ADMIN_PASSWORD "$admin_password"
else
  say ".env already exists; leaving local configuration unchanged."
fi

say "Starting GeoLens..."
docker compose up -d

say ""
say "GeoLens is starting."
say "UI:  http://localhost:8080"
say "API: http://localhost:8001"
say ""
say "Check service health with:"
say "  cd $INSTALL_DIR && docker compose ps"
