# shellcheck shell=sh
# GeoLens shared shell helpers — sourced by scripts/upgrade.sh (and any future
# operator script). NOT sourced by scripts/install.sh: install.sh is a
# self-contained single file streamed over `curl ... | sh` and byte-synced to the
# getgeolens.com mirror, so it deliberately inlines its own copies of these
# helpers. Keep the COMPOSE wrapper / update_env_value logic here in lockstep
# with install.sh's inlined versions. wait_for_healthy deliberately diverges:
# install.sh's copy budgets 300s and returns a non-fatal rc=2 on timeout (first
# boot under QEMU emulation), while this copy keeps a 90s budget for the
# upgrade path where images and volumes already exist locally.
#
# This file has NO side effects on source: it only defines functions and the few
# constants below. The caller sets COMPOSE_FILE before invoking compose().

# COMPOSE_FILE is selected by the caller (upgrade.sh reads it from .env). Default
# to the source-build file so a bare source still works.
: "${COMPOSE_FILE:=docker-compose.yml}"

# Wrap every compose call so the selected -f file is used consistently.
compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

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

# Read a value from .env. Handles values containing `=` correctly (returns the
# full remainder after the first `=`). Returns empty if the key is missing or
# the value is empty. Reads from "$1" if given, else ./.env.
get_env_value() {
  key="$1"
  file="${2:-.env}"
  awk -v k="$key" '
    {
      pat = "^" k "="
      if ($0 ~ pat) {
        print substr($0, length(k) + 2)
        exit
      }
    }
  ' "$file"
}

# Replace `KEY=...` in .env (or append if missing). Pass the value via ENVIRON
# rather than `awk -v` so backslashes in values are preserved verbatim.
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

# Resolve the highest semver release tag (vX.Y.Z) from a remote, matching the
# FULL refs/tags/<name> ref so a nested decoy tag (refs/tags/evil/v9.9.9) cannot
# masquerade as a top-level release. Numeric semver sort (v1.10.0 > v1.9.0).
# Prints the tag (with leading v) or empty. Mirrors install.sh :250.
resolve_latest_remote_tag() {
  _url="$1"
  git ls-remote --tags --refs "$_url" 2>/dev/null \
    | awk '{print $2}' \
    | grep -E '^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sed 's#^refs/tags/##' \
    | sort -t. -k1.2,1n -k2,2n -k3,3n \
    | tail -n 1
}

# Compare two bare semver strings (no leading v). Prints "newer" if $1 > $2,
# "same" if equal, "older" if $1 < $2. Pure numeric field comparison.
semver_compare() {
  _a="$1"
  _b="$2"
  __A="$_a" __B="$_b" awk '
    BEGIN {
      n = split(ENVIRON["__A"], a, ".")
      m = split(ENVIRON["__B"], b, ".")
      max = (n > m) ? n : m
      for (i = 1; i <= max; i++) {
        ai = (i <= n) ? a[i] + 0 : 0
        bi = (i <= m) ? b[i] + 0 : 0
        if (ai > bi) { print "newer"; exit }
        if (ai < bi) { print "older"; exit }
      }
      print "same"
    }
  '
}

# Wait up to 90s for the stack to become healthy. The migrate one-shot must exit
# 0; every healthcheck-having service must report (healthy). Surfaces the failing
# service with a log tail on timeout/failure. Diverges from install.sh's inlined
# copy (300s budget, non-fatal rc=2 timeout) — see the header note above.
#
# Services still in `(health: starting)` when the budget runs out are treated
# as converging ONLY while they sit inside their own declared start_period
# (e.g. the backup service allows 10m for its first pg_dump of a large DB,
# far beyond this 90s budget) — there Docker has not judged them yet, and
# neither should we. test(#826): that claim is now VERIFIED per service, not
# assumed. The full tolerance Docker grants is start_period PLUS retries
# consecutive failing probes, each taking up to interval + timeout (a service
# stays `starting` through that whole streak — Codex P2 on #867). A service
# still `starting` after we already waited past that entire window has
# outlived every verdict Docker could still be working on and fails the
# wait. Anything (unhealthy), restarting, or exited non-zero fails as
# before; an unreadable healthcheck config fails open (treated as
# converging), matching this script's other best-effort probes.
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

  # Budget spent — classify what is left. `(health: starting)` means the
  # service is within its declared start_period and Docker has not ruled on it;
  # failing the upgrade here would tell the operator to roll back a stack that
  # is converging fine (a pre-existing install whose first backup pg_dump
  # outlasts 90s hit exactly that). Warn and succeed when ONLY such services
  # remain; anything (unhealthy)/restarting/exited-nonzero is a real failure.
  remaining=$(compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '|Exited (0)' | grep -v '^$' || true)
  if [ -z "$remaining" ]; then
    printf '\n'
    return 0
  fi
  broken=$(printf '%s\n' "$remaining" | grep -v '(health: starting)' || true)
  if [ -z "$broken" ]; then
    budget=$((attempts * sleep_s))
    # test(#826): verify each straggler really is inside its healthcheck's
    # DECLARED tolerance before letting it pass. `(health: starting)` only
    # means Docker has not ruled yet — a service with a broken healthcheck can
    # sit there long after its grace ran out. Codex P2 (#867): start_period
    # alone is NOT the boundary — after it ends, Docker still tolerates
    # `retries` consecutive failing probes (each taking up to interval +
    # timeout) before flipping to (unhealthy), and the service honestly
    # reports `starting` for that whole streak. So the full allowance is
    # start_period + retries x (interval + timeout); zero config values mean
    # the daemon defaults (interval/timeout 30s, retries 3). The container
    # was started at (or before) the `compose up -d` this wait follows, so
    # the budget we already spent is a lower bound on its age: allowance <=
    # budget means Docker has had every chance to rule and still has not.
    overdue=""
    for svc in $(printf '%s\n' "$remaining" | cut -d'|' -f1); do
      cid=$(compose ps -q "$svc" 2>/dev/null | head -n 1)
      allowed=""
      if [ -n "$cid" ]; then
        allowed=$(docker inspect --format \
          '{{.Config.Healthcheck.StartPeriod.Seconds}} {{.Config.Healthcheck.Interval.Seconds}} {{.Config.Healthcheck.Timeout.Seconds}} {{.Config.Healthcheck.Retries}}' \
          "$cid" 2>/dev/null | head -n 1 | awk 'NF==4 {
            sp = int($1); iv = int($2); to = int($3); rt = int($4)
            if (iv <= 0) iv = 30
            if (to <= 0) to = 30
            if (rt <= 0) rt = 3
            print sp + rt * (iv + to)
          }')
      fi
      if [ -n "$allowed" ] && [ "$allowed" -le "$budget" ]; then
        overdue="${overdue}  ${svc}: still (health: starting) after ${budget}s, but its healthcheck tolerance (start_period + retries x (interval + timeout)) ended at ${allowed}s
"
      fi
    done
    if [ -z "$overdue" ]; then
      printf '\n'
      warn "these services are still starting after ${budget}s but remain within their healthcheck's tolerance (start_period + retries x (interval + timeout)):"
      printf '%s\n' "$remaining" | sed 's/^/  /' >&2
      warn "Docker will flag them (unhealthy) if they fail to converge; check later with: docker compose ps"
      return 0
    fi
    printf '\n' >&2
    warn "timed out after ${budget}s; these services outlived their healthcheck's start_period + retry tolerance without a passing probe:"
    printf '%s' "$overdue" >&2
    warn "Inspect with: docker compose ps  /  docker compose logs <service>"
    return 1
  fi
  printf '\n' >&2
  warn "timed out after $((attempts * sleep_s))s waiting for services. Current status:"
  compose ps 2>&1 | sed 's/^/  /' >&2
  warn "Inspect with: docker compose ps  /  docker compose logs <service>"
  return 1
}
