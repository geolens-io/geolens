#!/bin/sh
set -eu

REPO_URL="${GEOLENS_REPO_URL:-https://github.com/geolens-io/geolens.git}"
INSTALL_DIR="${GEOLENS_INSTALL_DIR:-geolens}"

# Compose file selection. docker-compose.yml builds every service from source;
# docker-compose.prod.yml pulls the prebuilt, version-pinned release images
# (api/worker/frontend) and only builds the small db layer. We switch to the
# prod file below when installing a release tag whose checkout ships it, and
# fall back to the source build if the pull fails. `compose` wraps every call
# so the selected file is used consistently (up, pull, ps, logs).
COMPOSE_FILE="docker-compose.yml"
RELEASE_VERSION=""

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

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

# Generate a strong password from the same entropy source as the JWT secret.
# The "Aa" prefix + "_1" suffix guarantee 4 character classes (upper, lower,
# digit, symbol) so the value satisfies a multi-class complexity policy, and
# uses only .env / connection-string-safe characters (no = $ " ' @ : / space).
generate_password() {
  printf 'Aa%s_1\n' "$(generate_jwt_secret)"
}

check_port() {
  port="$1"
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "port $port is already in use. Set the matching *_PORT value in .env before starting GeoLens."
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

    migrate_cid=$(compose ps -aq migrate 2>/dev/null | head -n 1)
    if [ -n "$migrate_cid" ]; then
      migrate_state=$(docker inspect --format '{{.State.Status}}' "$migrate_cid" 2>/dev/null || printf '')
      if [ "$migrate_state" = "exited" ]; then
        migrate_exit=$(docker inspect --format '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || printf '?')
        if [ "$migrate_exit" != "0" ]; then
          printf '\n' >&2
          warn "migrate one-shot exited with code $migrate_exit. Last 30 log lines:"
          compose logs --tail 30 migrate 2>&1 | sed 's/^/  /' >&2
          return 1
        fi
      fi
    fi

    # Treat as unhealthy any service that is neither reporting (healthy) nor a
    # successfully-exited one-shot. The migrate one-shot exits 0 (its failure is
    # caught above); some Compose versions list exited containers in `ps` without
    # `-a`, so exclude `Exited (0)` explicitly rather than relying on that.
    unhealthy=$(compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '|Exited (0)' | grep -v '^$' || true)
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
  compose ps 2>&1 | sed 's/^/  /' >&2
  warn "Inspect with: docker compose ps  /  docker compose logs <service>"
  return 1
}

# GAP-025: the entire imperative install sequence lives in main() and is
# invoked by a single `main "$@"` on the LAST line. `sh` parses the whole
# function body before executing it, so a truncated `curl ... | sh` download
# (a connection drop mid-stream) yields a syntax error at EOF instead of
# running a partial prefix that could write a half-configured .env or leave a
# partially-fetched checkout. All function and constant definitions above are
# parse-only (no side effects), so they are safe to stream.
main() {
  say "GeoLens installer"
  say "Repository: $REPO_URL"
  say "Install directory: $INSTALL_DIR"

  need_command git
  need_command docker

  # Verify the Compose v2 plugin via the `version` SUBCOMMAND, not a `--version`/
  # `--help` flag. `docker --version` and `docker --help` are answered by the
  # docker root command and exit 0 even when no `compose` plugin is installed, so
  # flag-based checks false-pass — then the install dies cryptically at the first
  # real `docker compose` call ("unknown flag" / "unknown shorthand flag" with
  # docker's root usage). `docker compose version` only exits 0 when the plugin is
  # actually present.
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required. Install Docker Desktop or the docker compose plugin."

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
    # Install the latest published release tag for a reproducible build. Resolve it
    # from the remote so no full clone is needed first; semver tags are sorted
    # numerically (not lexically, so v1.10.0 > v1.9.0). Fall back to the default
    # branch when no release tag resolves (offline, or a fork with no releases).
    # Override with GEOLENS_REF=<tag|branch> to pin a specific ref or track main.
    ref="${GEOLENS_REF:-}"
    ref_is_tag=false
    if [ -z "$ref" ]; then
      # Auto-resolve the highest semver release tag. Match the FULL refs/tags/<name>
      # ref (via `awk '{print $2}'`), not just the basename, so a nested decoy tag
      # like refs/tags/evil/v9.9.9 cannot masquerade as a top-level v9.9.9 release.
      ref="$(git ls-remote --tags --refs "$REPO_URL" 2>/dev/null \
        | awk '{print $2}' \
        | grep -E '^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
        | sed 's#^refs/tags/##' \
        | sort -t. -k1.2,1n -k2,2n -k3,3n \
        | tail -n 1)"
      if [ -n "$ref" ]; then
        ref_is_tag=true
      fi
    else
      # Explicit GEOLENS_REF: classify it against the remote's tag list. Capture the
      # query result separately from the membership test so a remote-query FAILURE
      # fails closed — never silently downgrade a ref that might be a release tag to
      # the shadowable `clone --branch` path below. Match the full refs/tags/ ref.
      remote_tags="$(git ls-remote --tags --refs "$REPO_URL" 2>/dev/null)" \
        || fail "Could not query $REPO_URL to classify GEOLENS_REF=$ref"
      if printf '%s\n' "$remote_tags" | awk '{print $2}' | grep -qxF "refs/tags/$ref"; then
        ref_is_tag=true
      fi
    fi
    if [ "$ref_is_tag" = "true" ]; then
      say "Installing release $ref"
      # Strip the leading v: published image tags are bare semver (1.2.3), matching
      # publish.yml's type=semver,pattern={{version}}.
      RELEASE_VERSION="${ref#v}"
      # Check out the tag via an explicit refs/tags/ fetch into a detached HEAD,
      # NOT `git clone --branch "$ref"`. Git resolves `--branch <name>` as a branch
      # first and only falls back to a tag, so a malicious refs/heads/<tag> pushed
      # to the remote would shadow the real refs/tags/<tag> and get built in place
      # of the release. A fully-qualified refs/tags/ fetch cannot be shadowed.
      #
      # Build into a temp dir and move into place only after checkout succeeds, so a
      # failed or interrupted fetch never leaves a half-initialized INSTALL_DIR that
      # the next run would mistake for a valid checkout (git clone is atomic this
      # way). The earlier `[ -e "$INSTALL_DIR" ]` guard guarantees INSTALL_DIR does
      # not exist yet, so building a sibling temp dir and moving it in is safe.
      tmp="${INSTALL_DIR}.tmp.$$"
      rm -rf "$tmp"
      if ! { git init -q "$tmp" \
          && git -C "$tmp" remote add origin "$REPO_URL" \
          && git -C "$tmp" fetch -q --depth 1 origin "refs/tags/$ref:refs/tags/$ref" \
          && git -C "$tmp" checkout -q --detach "refs/tags/$ref"; }; then
        rm -rf "$tmp"
        fail "Could not fetch release $ref from $REPO_URL"
      fi
      mv "$tmp" "$INSTALL_DIR"
    elif [ -n "$ref" ]; then
      # A GEOLENS_REF that is not a release tag (e.g. a branch like main) — track it.
      say "Installing ref $ref"
      git clone --depth 1 --branch "$ref" "$REPO_URL" "$INSTALL_DIR"
    else
      warn "Could not resolve a release tag; cloning the default branch."
      git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
    PROJECT_HINT="$INSTALL_DIR"
  fi

  ENV_CREATED=false
  if [ ! -f .env ]; then
    cp .env.example .env
    ENV_CREATED=true
  fi

  # JWT_SECRET_KEY: generate iff missing or empty. Existing real values are kept.
  existing_jwt="$(get_env_value JWT_SECRET_KEY)"
  if [ -z "$existing_jwt" ]; then
    jwt="$(generate_jwt_secret)"
    update_env_value JWT_SECRET_KEY "$jwt"
    say "Generated JWT_SECRET_KEY."
  fi

  # POSTGRES_PASSWORD (SEC-010): .env.example ships the publicly-known default
  # `geolens`. On a FRESH install replace it with a strong value so the database
  # is initialized with a real password. On a re-run we must NOT rotate it — the
  # pgdata volume is already initialized with the existing value and changing it
  # would lock the app out.
  existing_pg_pw="$(get_env_value POSTGRES_PASSWORD)"
  if [ "$ENV_CREATED" = "true" ] && { [ -z "$existing_pg_pw" ] || [ "$existing_pg_pw" = "geolens" ]; }; then
    update_env_value POSTGRES_PASSWORD "$(generate_password)"
    say "Generated POSTGRES_PASSWORD."
  elif [ "$existing_pg_pw" = "geolens" ]; then
    warn "POSTGRES_PASSWORD is still the public default 'geolens'. If the database has not been initialized yet, set a strong value in .env before first start."
  fi

  # Admin credentials: set only if either is empty. Honors GEOLENS_ADMIN_USERNAME /
  # GEOLENS_ADMIN_PASSWORD env vars for non-interactive installs.
  existing_admin_user="$(get_env_value GEOLENS_ADMIN_USERNAME)"
  existing_admin_pass="$(get_env_value GEOLENS_ADMIN_PASSWORD)"
  generated_admin_pw=false
  if [ -z "$existing_admin_user" ] || [ -z "$existing_admin_pass" ]; then
    admin_user="$(prompt_value 'Admin username' 'admin' false GEOLENS_ADMIN_USERNAME)"
    # Password (SEC-011): honor an explicitly-provided GEOLENS_ADMIN_PASSWORD;
    # interactively let the operator type one (blank = generate). Otherwise
    # GENERATE a strong password — never silently default to 'admin', which a
    # headless `curl | sh` install would otherwise do for an internet-facing app.
    admin_password="${GEOLENS_ADMIN_PASSWORD:-}"
    if [ -z "$admin_password" ] && [ "$HAS_TTY" = "true" ]; then
      admin_password="$(prompt_value 'Admin password (blank = generate a strong one)' '' true)"
    fi
    if [ -z "$admin_password" ]; then
      admin_password="$(generate_password)"
      generated_admin_pw=true
    fi
    update_env_value GEOLENS_ADMIN_USERNAME "$admin_user"
    update_env_value GEOLENS_ADMIN_PASSWORD "$admin_password"
    if [ "$generated_admin_pw" = "true" ]; then
      # Do not echo the secret to stdout/logs; it is stored in .env.
      say "Generated a strong admin password — retrieve it with: grep '^GEOLENS_ADMIN_PASSWORD=' .env"
    fi
  else
    say ".env already has admin credentials; leaving unchanged."
  fi

  # Docker Compose interpolates required MinIO variables even when the cloud-dev
  # profile is inactive, so populate generated values unless the operator already
  # supplied them for local S3 testing.
  existing_minio_user="$(get_env_value MINIO_ROOT_USER)"
  existing_minio_pass="$(get_env_value MINIO_ROOT_PASSWORD)"
  if [ -z "$existing_minio_user" ]; then
    update_env_value MINIO_ROOT_USER "$(generate_jwt_secret)"
  fi
  if [ -z "$existing_minio_pass" ]; then
    update_env_value MINIO_ROOT_PASSWORD "$(generate_jwt_secret)"
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

  # If we're sitting on an exact release tag (an in-place install, or a re-run in
  # an existing vX.Y.Z checkout) but RELEASE_VERSION wasn't set by the
  # fresh-clone-by-tag path above, detect it now — otherwise an in-place or repeat
  # install silently rebuilds from source instead of reusing the prebuilt images.
  if [ -z "$RELEASE_VERSION" ]; then
    detected_tag="$(git describe --exact-match --tags HEAD 2>/dev/null || true)"
    case "$detected_tag" in
      v[0-9]*.[0-9]*.[0-9]*) RELEASE_VERSION="${detected_tag#v}" ;;
    esac
  fi

  # Prefer prebuilt release images: when installing a release tag whose checkout
  # ships docker-compose.prod.yml, pull the version-pinned images instead of
  # building from source. Falls back to the source build for dev checkouts, branch
  # installs, older releases without the prod compose, or when the pull fails
  # (private/unavailable registry, offline, or a Compose too old for
  # --ignore-buildable). The db layer always builds locally (no published image).
  if [ -n "$RELEASE_VERSION" ] && [ -f docker-compose.prod.yml ]; then
    COMPOSE_FILE="docker-compose.prod.yml"
    export GEOLENS_VERSION="$RELEASE_VERSION"
    say "Pulling prebuilt images for GeoLens ${RELEASE_VERSION} (skips the source build)..."
    if compose pull --ignore-buildable; then
      # Persist BOTH the pin and the compose file so the operator's later bare
      # `docker compose ...` in this dir targets the prod (prebuilt-image) file at
      # the same version. Without COMPOSE_FILE in .env, bare compose auto-discovers
      # docker-compose.yml (the dev source-build file) and silently rebuilds.
      update_env_value GEOLENS_VERSION "$RELEASE_VERSION"
      update_env_value COMPOSE_FILE "docker-compose.prod.yml"
    else
      warn "Could not pull prebuilt images; building from source instead."
      COMPOSE_FILE="docker-compose.yml"
      unset GEOLENS_VERSION 2>/dev/null || true
      # Overwrite any stale prod pin from a previous run so bare `docker compose`
      # matches the source build we actually ran.
      update_env_value COMPOSE_FILE "docker-compose.yml"
    fi
  fi

  say "Starting GeoLens..."
  # Use the short `-d` flag, not `--detach`: `-d` is accepted by every Docker
  # Compose version, while some older Compose builds reject the `--detach` long
  # form with "unknown flag: --detach". `compose` adds -f "$COMPOSE_FILE".
  compose up -d

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
}

main "$@"
