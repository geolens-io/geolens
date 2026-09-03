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
#
# fix(#1778 review, P2): the awk extraction returns everything after the
# first `=` VERBATIM — but Docker Compose's own .env parser (the one
# `docker compose` itself uses to fill ${COMPOSE_FILE} etc. in the compose
# files) does not treat that text as a bare string. A `.env` an operator
# hand-edits with `COMPOSE_FILE="docker-compose.prod.yml"` or
# `POSTGRES_USER="geolens"` is valid Compose syntax and resolves to the
# unquoted value there, but used to come back from this function WITH the
# quote characters attached, silently breaking every caller that put the
# result in a path or SQL identifier. Apply the same rules Compose's
# env-file reference documents:
#   - a value wrapped in one matching pair of double or single quotes has
#     the quotes stripped;
#   - inside DOUBLE quotes, `\"` unescapes to `"` and `\\` unescapes to `\`
#     (a single left-to-right `\X -> X` pass handles both without an
#     ordering hazard between the two substitutions); single-quoted values
#     are literal — Compose applies no escape processing inside them;
#   - an UNQUOTED value's inline comment (a literal space then `#`, to end
#     of line) is stripped and the result is whitespace-trimmed, matching
#     Compose's own "inline comments for unquoted values must be preceded
#     by a space" rule. A quoted value's `#` is always literal; comment
#     stripping never applies once a value is quoted.
# A malformed quote (opens but never closes) is left completely alone rather
# than guessed at, the same policy this repo's content-vs-blob sync
# comparisons already use for unparseable input.
get_env_value() {
  key="$1"
  file="${2:-.env}"
  raw="$(awk -v k="$key" '
    {
      pat = "^" k "="
      if ($0 ~ pat) {
        print substr($0, length(k) + 2)
        exit
      }
    }
  ' "$file")"

  case "$raw" in
    \"*\")
      if [ "${#raw}" -ge 2 ]; then
        body="${raw#\"}"
        body="${body%\"}"
        printf '%s' "$body" | sed -E 's/\\(.)/\1/g'
      else
        printf '%s' "$raw"
      fi
      ;;
    \'*\')
      if [ "${#raw}" -ge 2 ]; then
        body="${raw#\'}"
        body="${body%\'}"
        printf '%s' "$body"
      else
        printf '%s' "$raw"
      fi
      ;;
    *)
      printf '%s' "$raw" | sed -E -e 's/ #.*$//' -e 's/[[:space:]]+$//' -e 's/^[[:space:]]+//'
      ;;
  esac
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

# Parse an RFC3339 UTC timestamp (docker's `.State.StartedAt`, e.g.
# 2026-07-27T01:07:52.269425417Z) to a unix epoch. GNU date first (Linux
# operator hosts), BSD date as the fallback (macOS dev; -j -u -f parses the
# fraction-stripped form as UTC). Prints nothing when the input does not look
# like a timestamp or neither date can parse it — callers must fail open.
# Always returns 0 so `set -e` callers never abort on an unparseable input.
iso_to_epoch() {
  _ts="$1"
  case "$_ts" in
    [0-9][0-9][0-9][0-9]-*) : ;;
    # Guard against non-timestamps BEFORE date sees them: GNU `date -d ""`
    # parses the empty string as today's midnight and exits 0, which would
    # turn "unreadable" into a wildly wrong age instead of failing open.
    *) return 0 ;;
  esac
  if _e=$(date -u -d "$_ts" +%s 2>/dev/null); then
    printf '%s\n' "$_e"
    return 0
  fi
  _t="${_ts%%.*}"
  _t="${_t%Z}"
  date -u -j -f '%Y-%m-%dT%H:%M:%S' "$_t" +%s 2>/dev/null || true
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
# assumed. The full tolerance Docker grants is start_period PLUS one
# in-flight probe's timeout (grace is judged by probe START time, so a probe
# launched just inside start_period may run `timeout` past the boundary)
# PLUS retries consecutive failing probes, each taking up to interval +
# timeout (a service stays `starting` through that whole streak — Codex P2
# rounds 1+3 on #867). A service
# whose container age (now - .State.StartedAt — NOT the wait budget, which
# overstates the age of a restart-policy container that restarted mid-wait
# with a freshly reset health clock; Codex P2 round 2) exceeds that entire
# window has outlived every verdict Docker could still be working on and
# fails the wait. The tolerance math only applies while the LIVE
# .State.Health.Status (read in the same inspect) still says `starting` —
# a container that flipped to (un)healthy between the compose ps snapshot
# and the inspect is judged by that verdict instead (round 4). Anything
# (unhealthy), restarting, or exited non-zero fails as before; an unreadable
# healthcheck config, StartedAt, or live status fails open (treated as
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
    # reports `starting` for that whole streak. Plus one in-flight probe's
    # timeout (Codex P2 round 3): moby grace-ignores a probe by its START
    # time, so one launched just inside start_period can run up to `timeout`
    # beyond the grace boundary before the counted retry cycles even begin.
    # So the full allowance is start_period + timeout + retries x (interval +
    # timeout); zero config values mean the daemon defaults (interval/timeout
    # 30s, retries 3).
    #
    # Codex P2 round 2 (#867): compare that allowance against the container's
    # ACTUAL age (now - .State.StartedAt), not the spent budget. A
    # restart-policy service that crashed and restarted mid-wait is seconds
    # old with a freshly reset health clock — legitimately inside its
    # start_period — and must not be classified overdue by a wait that
    # started before its life did. Unparseable StartedAt fails open, same as
    # unreadable healthcheck config.
    #
    # Codex P2 round 4 (#867): the `remaining` table is a SNAPSHOT — a probe
    # can complete between that `compose ps` and this inspect and flip the
    # container out of `starting`. Read the LIVE .State.Health.Status in the
    # same inspect and apply the tolerance math only while it still says
    # `starting`: a flip to `unhealthy` fails the service outright (Docker
    # has ruled; age math must not overrule it), a flip to `healthy` counts
    # as converged, and an unreadable status fails open like the rest.
    now_epoch=$(date -u +%s)
    overdue=""
    for svc in $(printf '%s\n' "$remaining" | cut -d'|' -f1); do
      cid=$(compose ps -q "$svc" 2>/dev/null | head -n 1)
      hc_line=""
      if [ -n "$cid" ]; then
        hc_line=$(docker inspect --format \
          '{{.State.StartedAt}} {{.Config.Healthcheck.StartPeriod.Seconds}} {{.Config.Healthcheck.Interval.Seconds}} {{.Config.Healthcheck.Timeout.Seconds}} {{.Config.Healthcheck.Retries}} {{.State.Health.Status}}' \
          "$cid" 2>/dev/null | head -n 1)
      fi
      live_status="${hc_line##* }"
      case "$live_status" in
        healthy)
          # Raced to healthy between the snapshot and this inspect: converged.
          continue ;;
        unhealthy)
          # Raced to unhealthy: Docker has ruled — fail it outright, no
          # tolerance math (age inside the window must not overrule a verdict).
          overdue="${overdue}  ${svc}: reported (health: starting) in the status snapshot but is (unhealthy) on inspection
"
          continue ;;
        starting) : ;;
        *)
          # Unreadable live status — fail open like the rest.
          continue ;;
      esac
      allowed=$(printf '%s\n' "$hc_line" | awk 'NF==6 {
        sp = int($2); iv = int($3); to = int($4); rt = int($5)
        if (iv <= 0) iv = 30
        if (to <= 0) to = 30
        if (rt <= 0) rt = 3
        # + to: a probe started just inside start_period is grace-ignored by
        # its START time and may run `timeout` past the boundary (round 3)
        print sp + to + rt * (iv + to)
      }')
      age=""
      start_epoch=$(iso_to_epoch "${hc_line%% *}")
      [ -n "$start_epoch" ] && age=$((now_epoch - start_epoch))
      if [ -n "$allowed" ] && [ -n "$age" ] && [ "$age" -ge "$allowed" ]; then
        overdue="${overdue}  ${svc}: still (health: starting) ${age}s after its last start, but its healthcheck tolerance (start_period + timeout + retries x (interval + timeout)) ended at ${allowed}s
"
      fi
    done
    if [ -z "$overdue" ]; then
      printf '\n'
      warn "these services are still starting after ${budget}s but remain within their healthcheck's tolerance (start_period + timeout + retries x (interval + timeout)):"
      printf '%s\n' "$remaining" | sed 's/^/  /' >&2
      warn "Docker will flag them (unhealthy) if they fail to converge; check later with: docker compose ps"
      return 0
    fi
    printf '\n' >&2
    warn "timed out after ${budget}s; these services are not converging (outlived their healthcheck tolerance, or already ruled unhealthy):"
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
