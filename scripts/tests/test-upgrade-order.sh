#!/bin/sh
# Regression test for scripts/upgrade.sh (UPG-01) — the prebuilt-image upgrade
# flow. Pure shell with stubbed docker/pg_dump/git on PATH that RECORD CALL
# ORDER to a log; no real stack, no DB, no network.
#
# Asserts:
#   - backup (pg_dump) runs BEFORE the image pull
#   - migrate runs BEFORE the app `up -d` and BEFORE the health gate
#   - a NON-ZERO migrate aborts BEFORE `up -d` and prints the rollback recipe
#   - a source-build install (COMPOSE_FILE=docker-compose.yml) exits 0 with the
#     source-build instructions and makes NO compose/pg_dump calls
#   - test(#826) wait_for_healthy edge cases: a still-starting service passes
#     ONLY while its container AGE (now - StartedAt — not the wait budget,
#     which lies about a service that restarted mid-wait; Codex P2 round 2)
#     is inside its healthcheck's full tolerance — start_period + timeout +
#     retries x (interval + timeout), per Docker's verdict semantics: grace
#     is judged by probe START time, so one in-flight probe's timeout rides
#     past the boundary (Codex P2 rounds 1+3 on #867) — one that outlived it
#     fails the wait; the LIVE Health.Status read in the same inspect wins
#     over the snapshot AND the tolerance math in both directions (round 4);
#     an (unhealthy) service at budget end fails the wait; unreadable
#     config, StartedAt, or live status fails open
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"      # scripts/
PROJECT_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
UPGRADE_SH="$REPO_ROOT/upgrade.sh"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

# upgrade.sh cd's to its own PROJECT_ROOT (the real repo) and reads ./.env there.
# To run hermetically we copy the two scripts + lib into a throwaway tree and
# drop a fake .env so the real repo's .env (if any) is never touched.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

FAKE="$WORK/repo"
mkdir -p "$FAKE/scripts/lib"
cp "$UPGRADE_SH" "$FAKE/scripts/upgrade.sh"
cp "$REPO_ROOT/lib/common.sh" "$FAKE/scripts/lib/common.sh"
# restore.sh is only *referenced* in printed text; a placeholder keeps paths real.
printf '#!/bin/sh\nexit 0\n' > "$FAKE/scripts/restore.sh"
chmod +x "$FAKE/scripts/upgrade.sh" "$FAKE/scripts/restore.sh"

# Shared stub bin. docker/pg_dump/git append their invocation to $CALLLOG.
SHIM="$WORK/bin"
mkdir -p "$SHIM"

make_stubs() {
  # $1 = migrate exit behavior: "ok" (exit 0) or "fail" (exit 3)
  _migrate_mode="$1"
  CALLLOG="$WORK/calls.log"
  : > "$CALLLOG"
  GITLOG="$WORK/git.log"
  : > "$GITLOG"

  # --- docker stub ---------------------------------------------------------
  # Handles: `docker compose version`, `docker compose -f <f> <cmd...>`,
  # and `docker inspect --format <fmt> <cid>`. Logs a normalized event for the
  # compose subcommands we care about, and answers `ps -aq migrate` / `inspect`
  # so the migrate-exit check works. Single-quoted heredoc (no shell expansion
  # in the stub body); $CALLLOG / $_migrate_mode are passed in via the stub's
  # environment as DOCKER_LOG / DOCKER_MIGRATE_MODE.
  cat > "$SHIM/docker" <<'DOCKER'
#!/bin/sh
LOG="${DOCKER_LOG:?}"
MIGRATE_MODE="${DOCKER_MIGRATE_MODE:-ok}"
STOP_MODE="${DOCKER_STOP_MODE:-ok}"
if [ "$1" = "compose" ]; then
  shift
  # strip "-f <file>"
  if [ "$1" = "-f" ]; then shift; shift; fi
  case "$1" in
    version) exit 0 ;;
    stop)    echo "stop_app" >> "$LOG"; [ "$STOP_MODE" = "fail" ] && exit 1; exit 0 ;;
    pull)    echo "pull" >> "$LOG"; exit 0 ;;
    exec)
      # Four distinct in-container calls share `compose exec -T db`:
      #   psql       -> the PG-major probe (Step 2.5); answer server_version_num.
      #   pg_dump    -> the backup path; emit non-empty dump bytes to stdout.
      #   pg_restore -> the end-to-end read-back of that dump (fix(#714)).
      #   cat        -> the LIVE postgresql.conf the container is serving
      #                 (fix(#959)); DOCKER_DB_RUNNING_CONF models a container
      #                 still holding the pre-upgrade inode. Empty output
      #                 models an external/managed DB with no `db` service.
      for a in "$@"; do
        if [ "$a" = "cat" ]; then
          [ -n "${DOCKER_DB_RUNNING_CONF:-}" ] \
            && printf '%s\n' "$DOCKER_DB_RUNNING_CONF"
          exit 0
        fi
        if [ "$a" = "psql" ]; then
          echo "probe_pg" >> "$LOG"
          # "none" models a probe that answers nothing (external/managed
          # Postgres: there is no `db` service to exec into).
          [ "${DOCKER_PG_NUM:-170005}" = "none" ] || echo "${DOCKER_PG_NUM:-170005}"
          exit 0
        fi
        if [ "$a" = "pg_restore" ]; then
          echo "verify_backup" >> "$LOG"
          cat > /dev/null
          [ "${DOCKER_VERIFY_MODE:-ok}" = "fail" ] && exit 1
          exit 0
        fi
      done
      echo "backup" >> "$LOG"
      printf 'PGDMP-fake-custom-format-dump-bytes\n'
      exit 0 ;;
    up)
      # detect the migrate one-shot vs the db-only config recreate vs the app up
      for a in "$@"; do
        if [ "$a" = "migrate" ]; then echo "migrate_up" >> "$LOG"; exit 0; fi
      done
      # fix(#959): `up -d --force-recreate --no-deps --wait db` applies a synced
      # db/postgresql.conf. It is NOT an app up — logging it as one would make
      # the ordering assertions read a config bounce as bringing the app back.
      case "$*" in
        *--no-deps*\ db|*--no-deps*\ db\ *) echo "db_recreate" >> "$LOG"; exit 0 ;;
      esac
      echo "app_up" >> "$LOG"; exit 0 ;;
    ps)
      # `ps -aq migrate` -> a fake container id. `ps --format ...` (the
      # health-gate poll) -> the DOCKER_PS_STATUS table, empty by default so
      # the gate passes immediately. `ps -q <service>` -> a per-service cid
      # for wait_for_healthy's start_period lookup (test(#826)).
      for a in "$@"; do
        if [ "$a" = "migrate" ]; then echo "mig-cid"; exit 0; fi
      done
      case "$*" in
        *--format*)
          [ -n "${DOCKER_PS_STATUS:-}" ] && printf '%s\n' "$DOCKER_PS_STATUS"
          exit 0 ;;
        *" -q "*)
          for a in "$@"; do svc="$a"; done
          echo "cid-$svc"
          exit 0 ;;
      esac
      exit 0 ;;
    logs) exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "$1" = "wait" ]; then
  # docker wait <cid> -> block-then-print the migrate one-shot's exit code (0|3).
  [ "$MIGRATE_MODE" = "fail" ] && echo 3 || echo 0
  exit 0
fi
if [ "$1" = "inspect" ]; then
  # --format '{{.State.Status}}' -> exited ; '{{.State.ExitCode}}' -> 0|3.
  # test(#826): the healthcheck format (StartedAt + StartPeriod/Interval/
  # Timeout/Retries + live Health.Status fields) -> "<started_at>
  # <start_period> <interval> <timeout> <retries> <live_status>" for the
  # cid-<svc> container, from DOCKER_STARTED_<svc> + DOCKER_HC_<svc> (the HC
  # tuple carries the live status as its last field). Empty/unset HC models an
  # unreadable healthcheck (fail-open branch): the real docker's template
  # errors on a nil Healthcheck and prints nothing to stdout. A non-timestamp
  # DOCKER_STARTED_<svc> models an unparseable StartedAt (also fail-open).
  case "$*" in
    *StartPeriod*)
      for a in "$@"; do cid="$a"; done
      svc="${cid#cid-}"
      eval "hc=\${DOCKER_HC_${svc}:-}"
      eval "st=\${DOCKER_STARTED_${svc}:-}"
      [ -n "$hc" ] && echo "${st:-unset-started} $hc"
      exit 0 ;;
    *State.Status*)   echo "exited" ; exit 0 ;;
    *State.ExitCode*) [ "$MIGRATE_MODE" = "fail" ] && echo 3 || echo 0 ; exit 0 ;;
  esac
  exit 0
fi
exit 0
DOCKER
  chmod +x "$SHIM/docker"

  # --- pg_dump stub (need_command pg_dump must succeed) --------------------
  printf '#!/bin/sh\nexit 0\n' > "$SHIM/pg_dump"
  chmod +x "$SHIM/pg_dump"

  # --- sleep stub: wait_for_healthy polls 18 x 5s, so the health-gate cases
  # (test(#826)) would otherwise take 90 real seconds each. upgrade.sh has no
  # other sleep, so a no-op is safe.
  printf '#!/bin/sh\nexit 0\n' > "$SHIM/sleep"
  chmod +x "$SHIM/sleep"

  # --- git stub: ls-remote returns a newer tag for auto-resolve. fetch/checkout
  # (the UPG release-file sync) record to $GIT_LOG so the sync can be asserted
  # WITHOUT polluting the docker call-order log. rev-parse --git-dir succeeds so
  # upgrade.sh treats the fake tree as a git checkout. Everything else is a no-op.
  #
  # fix(#959): `show <tag>:db/postgresql.conf` answers per tag, so the config
  # sync can be exercised for real — v1.2.3 is what the install is running,
  # v1.2.4 is what the release ships. `checkout ... db/postgresql.conf` writes
  # the target content, matching what real git does to the worktree.
  cat > "$SHIM/git" <<'GIT'
#!/bin/sh
GLOG="${GIT_LOG:-/dev/null}"
DB_CONF_INSTALLED='temp_file_limit = 0
'
DB_CONF_TARGET='temp_file_limit = 4GB
'
case "$1" in
  ls-remote) printf 'deadbeef\trefs/tags/v1.2.4\n' ;;
  fetch)     echo "fetch" >> "$GLOG" ;;
  checkout)
    echo "checkout" >> "$GLOG"
    for a in "$@"; do
      if [ "$a" = "db/postgresql.conf" ]; then
        printf '%s' "$DB_CONF_TARGET" > db/postgresql.conf
      fi
    done ;;
  # `git show <tag>:db/Dockerfile` -> the target release's bundled db base
  # image, which the Step 2.5 PG-major guard parses.
  show)
    case "$2" in
      *:db/postgresql.conf)
        case "$2" in
          v1.2.4:*) printf '%s' "$DB_CONF_TARGET" ;;
          *)        printf '%s' "$DB_CONF_INSTALLED" ;;
        esac ;;
      *) printf 'FROM --platform=linux/amd64 postgis/postgis:%s-3.6\n' "${GIT_TARGET_PG:-17}" ;;
    esac ;;
  *)         exit 0 ;;
esac
GIT
  chmod +x "$SHIM/git"
}

# Seed a PREBUILT (.prod) .env pinned to an OLDER version so v1.2.4 is an upgrade.
seed_prod_env() {
  cat > "$FAKE/.env" <<'ENV'
COMPOSE_FILE=docker-compose.prod.yml
GEOLENS_VERSION=1.2.3
POSTGRES_USER=geolens
POSTGRES_DB=geolens
ENV
  # compose files referenced by name only (stub never reads them) but keep real.
  printf 'services: {}\n' > "$FAKE/docker-compose.prod.yml"
  printf 'services: {}\n' > "$FAKE/docker-compose.yml"
  # fix(#959): the bind-mounted Postgres config, seeded to the INSTALLED
  # release's content ($DB_CONF_INSTALLED in the git stub) so the default case
  # is an untouched file the upgrade may sync. Pass $1 to seed something else
  # and model an operator who tuned it.
  mkdir -p "$FAKE/db"
  printf '%s\n' "${1:-temp_file_limit = 0}" > "$FAKE/db/postgresql.conf"
}

run_upgrade() {  # $1=migrate mode, rest=args to upgrade.sh
  _mode="$1"; shift
  make_stubs "$_mode"
  ( env "PATH=$SHIM:$PATH" GEOLENS_REPO_URL="file:///fake" \
      DOCKER_LOG="$CALLLOG" DOCKER_MIGRATE_MODE="$_mode" GIT_LOG="$GITLOG" \
      DOCKER_STOP_MODE="${STOP_MODE:-ok}" \
      DOCKER_VERIFY_MODE="${VERIFY_MODE:-ok}" \
      DOCKER_PS_STATUS="${PS_STATUS:-}" \
      DOCKER_HC_backup="${HC_BACKUP:-}" DOCKER_HC_api="${HC_API:-}" \
      DOCKER_HC_frontend="${HC_FRONTEND:-}" \
      DOCKER_STARTED_backup="${STARTED_BACKUP:-}" \
      DOCKER_STARTED_api="${STARTED_API:-}" \
      DOCKER_STARTED_frontend="${STARTED_FRONTEND:-}" \
      DOCKER_PG_NUM="${PG_NUM:-170005}" GIT_TARGET_PG="${TARGET_PG:-17}" \
      DOCKER_DB_RUNNING_CONF="${DB_RUNNING_CONF-temp_file_limit = 0}" \
      sh "$FAKE/scripts/upgrade.sh" "$@" </dev/null > "$WORK/out.txt" 2>&1 )
  echo $? > "$WORK/code.txt"
}

# Position of an event in the call log (line number; empty if absent).
pos_of() { grep -n "^$1\$" "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1; }

# RFC3339 UTC timestamp $1 seconds in the past — the shape docker prints for
# `.State.StartedAt`. GNU date first, BSD date fallback (same dual-branch
# strategy as common.sh's iso_to_epoch).
iso_ago() {
  _e=$(( $(date -u +%s) - $1 ))
  date -u -d "@${_e}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
    || date -u -r "${_e}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null
}

# ============================================================================
# CASE 1 — happy path, explicit target. Assert ordering.
# ============================================================================
seed_prod_env
run_upgrade ok 1.2.4

if [ "$(cat "$WORK/code.txt")" = "0" ]; then
  ok "happy-path upgrade exits 0"
else
  bad "happy-path upgrade exit=$(cat "$WORK/code.txt")"
  sed 's/^/    # /' "$WORK/out.txt"
fi

b="$(pos_of backup)"; p="$(pos_of pull)"; m="$(pos_of migrate_up)"; a="$(pos_of app_up)"
if [ -n "$b" ] && [ -n "$p" ] && [ "$b" -lt "$p" ]; then
  ok "backup (pg_dump) runs BEFORE the image pull ($b < $p)"
else
  bad "backup did not precede pull (backup=$b pull=$p)"
fi
if [ -n "$m" ] && [ -n "$a" ] && [ "$m" -lt "$a" ]; then
  ok "migrate runs BEFORE the app up -d ($m < $a)"
else
  bad "migrate did not precede app up (migrate=$m app=$a)"
fi
if [ -n "$p" ] && [ -n "$m" ] && [ "$p" -lt "$m" ]; then
  ok "pull runs before migrate ($p < $m)"
else
  bad "pull did not precede migrate (pull=$p migrate=$m)"
fi
if grep -q 'ROLLBACK' "$WORK/out.txt"; then
  ok "success path prints the rollback recipe for reference"
else
  bad "success path did not print rollback recipe"
fi

# Full expected order: probe_pg, stop_app, backup, verify_backup, pull,
# db_recreate, migrate_up, app_up. The PG-major probe runs first — it must
# decide before anything is changed. db_recreate appears because the git stub
# reports a db/postgresql.conf that differs from the target tag (fix(#959));
# it lands after the pull and before migrate, so migrations already run under
# the release's Postgres settings.
order="$(tr '\n' ',' < "$WORK/calls.log")"
expected="probe_pg,stop_app,backup,verify_backup,pull,db_recreate,migrate_up,app_up,"
if [ "$order" = "$expected" ]; then
  ok "full call order is probe pg major -> stop api/worker -> backup -> verify -> pull -> db conf recreate -> migrate -> app_up"
else
  bad "unexpected call order: $order"
fi

# fix(#959): the config bounce must not straddle the migrate step or the app up.
d="$(pos_of db_recreate)"
if [ -n "$d" ] && [ -n "$p" ] && [ -n "$m" ] && [ "$p" -lt "$d" ] && [ "$d" -lt "$m" ]; then
  ok "synced db/postgresql.conf is applied between the pull and migrate ($p < $d < $m)"
else
  bad "db config recreate out of place (pull=$p db_recreate=$d migrate=$m)"
fi

# fix(#714): the rollback dump is read back end-to-end BEFORE the first
# irreversible step. A dump truncated by a full disk is non-empty and passes
# `--list`, so `-s` alone would let the upgrade migrate the schema behind an
# unrestorable rollback artifact.
v="$(pos_of verify_backup)"
if [ -n "$v" ] && [ -n "$b" ] && [ -n "$p" ] && [ "$b" -lt "$v" ] && [ "$v" -lt "$p" ]; then
  ok "rollback dump verified between the dump and the first irreversible step ($b < $v < $p)"
else
  bad "backup not verified before the pull (backup=$b verify=$v pull=$p)"
fi

# Writers quiesced BEFORE the dump (so the snapshot loses no acknowledged writes on
# rollback) and before migrate (Codex P1).
s="$(pos_of stop_app)"
if [ -n "$s" ] && [ -n "$b" ] && [ -n "$m" ] && [ "$s" -lt "$b" ] && [ "$b" -lt "$m" ]; then
  ok "api/worker stopped before the backup dump and before migrate ($s < $b < $m)"
else
  bad "writers not quiesced before the dump (stop=$s backup=$b migrate=$m)"
fi

# UPG release-file sync (Codex P2): the prebuilt flow fetches the target tag and
# checks out the compose/scripts BEFORE pulling images, so new images get the new
# release's config. (git fetch/checkout are recorded to git.log; both happen in the
# Step-3 sync, which runs before the docker `pull` logged above.)
if grep -q '^fetch$' "$WORK/git.log" 2>/dev/null && grep -q '^checkout$' "$WORK/git.log" 2>/dev/null; then
  ok "release files are fetched + checked out from the target tag before the pull"
else
  bad "release-file sync did not run (git.log: $(tr '\n' ',' < "$WORK/git.log" 2>/dev/null))"
fi

# ============================================================================
# CASE 2 — migrate fails: must abort BEFORE app up_d and print rollback.
# ============================================================================
seed_prod_env
run_upgrade fail 1.2.4

if [ "$(cat "$WORK/code.txt")" != "0" ]; then
  ok "failed migrate makes upgrade exit non-zero"
else
  bad "failed migrate did NOT fail the upgrade"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if [ -z "$(pos_of app_up)" ]; then
  ok "failed migrate aborts BEFORE the app up -d (no app_up call)"
else
  bad "app was brought up despite a failed migrate"
fi
if [ -n "$(pos_of migrate_up)" ]; then
  ok "migrate WAS attempted before the abort"
else
  bad "migrate was never attempted"
fi
if grep -q 'ROLLBACK' "$WORK/out.txt" && grep -q 'restore.sh' "$WORK/out.txt"; then
  ok "failed migrate prints the rollback recipe (restore.sh)"
else
  bad "failed migrate did not print the rollback recipe"
  sed 's/^/    # /' "$WORK/out.txt"
fi
# Backup must still have happened before the abort (data is safe).
if [ -n "$(pos_of backup)" ] && [ -z "$(pos_of app_up)" ]; then
  ok "backup was taken before the failed migrate (data safe)"
else
  bad "backup ordering wrong on the failure path"
fi

# ============================================================================
# CASE 2b — fix(#959): a tuned db/postgresql.conf survives the upgrade.
# The customization test is CONTENT-based (worktree vs the installed release's
# blob), not `git diff`-based, so it holds whether or not the operator staged
# or committed their tuning — an operator who version-controls production
# tuning would otherwise look clean to git and get silently overwritten
# (codex review on #959's PR).
# ============================================================================
seed_prod_env 'temp_file_limit = 64GB   # tuned by the operator'
run_upgrade ok 1.2.4

if grep -q '64GB' "$FAKE/db/postgresql.conf"; then
  ok "customized db/postgresql.conf is NOT overwritten by the upgrade"
else
  bad "upgrade clobbered a customized db/postgresql.conf: $(cat "$FAKE/db/postgresql.conf")"
fi
if [ -z "$(pos_of db_recreate)" ]; then
  ok "no db container bounce when the config was left alone"
else
  bad "db was recreated even though the config was not synced"
fi
if grep -q 'keeping your version' "$WORK/out.txt"; then
  ok "upgrade warns that it kept the operator's config"
else
  bad "upgrade did not warn about the retained config"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# An unmodified config IS synced, and the sync is what triggers the bounce.
seed_prod_env
run_upgrade ok 1.2.4
if grep -q '4GB' "$FAKE/db/postgresql.conf" && [ -n "$(pos_of db_recreate)" ]; then
  ok "unmodified db/postgresql.conf is synced to the target release and applied"
else
  bad "unmodified config was not synced/applied (conf=$(cat "$FAKE/db/postgresql.conf"), calls=$(tr '\n' ',' < "$WORK/calls.log"))"
fi

# ============================================================================
# CASE 2c — fix(#959): a retry after an interrupted upgrade still bounces the
# db. The earlier attempt already wrote the release's config to disk, so git
# sees nothing to do; only the RUNNING container knows it is still serving the
# pre-upgrade inode (codex review on #959's PR).
# ============================================================================
seed_prod_env 'temp_file_limit = 4GB'          # synced by the failed attempt
DB_RUNNING_CONF='temp_file_limit = 0'          # container still on the old file
run_upgrade ok 1.2.4
if [ -n "$(pos_of db_recreate)" ]; then
  ok "retry after an interrupted upgrade still recreates db (config on disk, not live)"
else
  bad "retry skipped the db recreate: calls=$(tr '\n' ',' < "$WORK/calls.log")"
fi

# ...and once it IS live, the upgrade does not bounce the database for nothing.
seed_prod_env 'temp_file_limit = 4GB'
DB_RUNNING_CONF='temp_file_limit = 4GB'
run_upgrade ok 1.2.4
if [ -z "$(pos_of db_recreate)" ]; then
  ok "no db bounce when the running container already serves the release config"
else
  bad "db was recreated despite already serving the release config"
fi
unset DB_RUNNING_CONF

# ============================================================================
# CASE 3 — source-build install: instructions + exit 0, NO compose/backup calls.
# ============================================================================
cat > "$FAKE/.env" <<'ENV'
COMPOSE_FILE=docker-compose.yml
GEOLENS_VERSION=1.2.3
ENV
make_stubs ok
( env "PATH=$SHIM:$PATH" GEOLENS_REPO_URL="file:///fake" \
    DOCKER_LOG="$CALLLOG" DOCKER_MIGRATE_MODE=ok \
    sh "$FAKE/scripts/upgrade.sh" </dev/null > "$WORK/out.txt" 2>&1 )
echo $? > "$WORK/code.txt"

if [ "$(cat "$WORK/code.txt")" = "0" ]; then
  ok "source-build install exits 0 (no-op with instructions)"
else
  bad "source-build install exit=$(cat "$WORK/code.txt")"
fi
if grep -q 'source-build install' "$WORK/out.txt" && grep -q 'docker compose -f docker-compose.yml build' "$WORK/out.txt"; then
  ok "source-build install prints rebuild-from-source instructions"
else
  bad "source-build install did not print source instructions"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if [ ! -s "$WORK/calls.log" ]; then
  ok "source-build install makes NO compose/backup calls (safe no-op)"
else
  bad "source-build install touched the stack: $(tr '\n' ',' < "$WORK/calls.log")"
fi

# ============================================================================
# CASE 4 — same-version target is a no-op (exit 0, no backup/pull).
# ============================================================================
seed_prod_env
run_upgrade ok 1.2.3
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -z "$(pos_of backup)" ] && [ -z "$(pos_of pull)" ]; then
  ok "same-version target is a clean no-op (no backup/pull)"
else
  bad "same-version target was not a clean no-op (exit=$(cat "$WORK/code.txt"), calls=$(tr '\n' ',' < "$WORK/calls.log"))"
fi

# ============================================================================
# CASE 5 — older target is refused (no downgrade).
# ============================================================================
seed_prod_env
run_upgrade ok 1.2.0
if [ "$(cat "$WORK/code.txt")" != "0" ] && [ -z "$(pos_of pull)" ]; then
  ok "older target is refused before any pull (no downgrade)"
else
  bad "older target was not refused (exit=$(cat "$WORK/code.txt"))"
fi

# ============================================================================
# CASE 6 — writer quiesce fails: abort BEFORE the backup, restart writers (P1).
# ============================================================================
seed_prod_env
STOP_MODE=fail
run_upgrade ok 1.2.4
STOP_MODE=ok
if [ "$(cat "$WORK/code.txt")" != "0" ] && [ -z "$(pos_of backup)" ]; then
  ok "failed writer quiesce aborts BEFORE the backup (no dump under active writers)"
else
  bad "failed quiesce did not abort before backup (exit=$(cat "$WORK/code.txt"), calls=$(tr '\n' ',' < "$WORK/calls.log"))"
fi
if [ -n "$(pos_of app_up)" ]; then
  ok "failed quiesce restarts api/worker (restart_writers ran)"
else
  bad "failed quiesce did not restart api/worker"
fi

# ============================================================================
# CASE 6b — fix(#714): the dump is written but reads back corrupt. Abort before
# the first irreversible step, discard the unusable artifact, restart writers.
# ============================================================================
seed_prod_env
# Clear dumps left by earlier passing cases: the filename carries a
# whole-second timestamp, so the "was it discarded?" check below would
# otherwise pass or fail depending on whether CASE 1 happened to land in the
# same second as this one.
rm -rf "$FAKE/backups/pre-upgrade"
VERIFY_MODE=fail
run_upgrade ok 1.2.4
VERIFY_MODE=ok
if [ "$(cat "$WORK/code.txt")" != "0" ] && [ -z "$(pos_of pull)" ]; then
  ok "unreadable rollback dump aborts BEFORE the pull (nothing irreversible ran)"
else
  bad "corrupt dump did not abort before pull (exit=$(cat "$WORK/code.txt"), calls=$(tr '\n' ',' < "$WORK/calls.log"))"
fi
if [ -z "$(find "$FAKE/backups/pre-upgrade" -name '*.dump' 2>/dev/null)" ]; then
  ok "unreadable rollback dump is discarded, not left to look like a backup"
else
  bad "corrupt dump was left on disk: $(find "$FAKE/backups/pre-upgrade" -name '*.dump')"
fi
if [ -n "$(pos_of app_up)" ]; then
  ok "failed verification restarts api/worker (app is not left down)"
else
  bad "failed verification did not restart api/worker"
fi

# ============================================================================
# CASE 7 — chore(#704): a target release bundling a DIFFERENT PostgreSQL major
# is refused before ANY change (no stop, no dump, no pull), with a RUNBOOK
# pointer. A PG N volume cannot be opened by a PG N+1 server.
# ============================================================================
seed_prod_env
PG_NUM=170005 TARGET_PG=18 run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" != "0" ]; then
  ok "PG major mismatch refuses the upgrade (non-zero exit)"
else
  bad "PG major mismatch did NOT refuse the upgrade"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if [ -z "$(pos_of stop_app)" ] && [ -z "$(pos_of backup)" ] && [ -z "$(pos_of pull)" ]; then
  ok "PG major mismatch aborts before any change (no stop/backup/pull)"
else
  bad "PG major mismatch touched the stack: $(tr '\n' ',' < "$WORK/calls.log")"
fi
if grep -q 'RUNBOOK' "$WORK/out.txt" && grep -q 'PostgreSQL 18' "$WORK/out.txt"; then
  ok "PG major mismatch points at the RUNBOOK major-upgrade procedure"
else
  bad "PG major mismatch did not print the RUNBOOK pointer"
  sed 's/^/    # /' "$WORK/out.txt"
fi
# The .env pin must NOT have moved — the operator is still on their old version.
if grep -q '^GEOLENS_VERSION=1.2.3$' "$FAKE/.env"; then
  ok "PG major mismatch leaves GEOLENS_VERSION unchanged"
else
  bad "PG major mismatch moved the version pin: $(grep GEOLENS_VERSION "$FAKE/.env")"
fi

# Matching majors must NOT be blocked (guard is a boundary check, not a gate).
seed_prod_env
PG_NUM=180004 TARGET_PG=18 run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "matching PG major upgrades normally"
else
  bad "matching PG major was blocked (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Codex #707: with DATABASE_URL_OVERRIDE set the app uses an external database,
# but the prod compose still starts the bundled `db`. Probing that stale local
# container would refuse an upgrade for an operator whose provider is already on
# the new major, so the check is skipped entirely in that mode.
seed_prod_env
printf 'DATABASE_URL_OVERRIDE=postgresql://u:p@managed.example.com:5432/geolens\n' >> "$FAKE/.env"
PG_NUM=170005 TARGET_PG=18 run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "external database (DATABASE_URL_OVERRIDE) skips the bundled PG major check"
else
  bad "external database was blocked by the bundled check (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if [ -z "$(pos_of probe_pg)" ]; then
  ok "external database mode does not probe the bundled db container"
else
  bad "external database mode still probed the bundled db"
fi

# Fail-open: an unreadable server version (a bundled db that cannot be reached)
# must NOT block an otherwise valid upgrade. Guards the `set -eu` edge where an
# empty probe could abort the script outright.
seed_prod_env
PG_NUM=none TARGET_PG=18 run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "unreadable server version fails open (upgrade proceeds)"
else
  bad "unreadable server version blocked the upgrade (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# ============================================================================
# CASE 8 — test(#826) wait_for_healthy: a service still `(health: starting)`
# at budget end passes ONLY while inside its healthcheck's full tolerance:
# start_period + timeout + retries x (interval + timeout). The prod backup service
# declares start_period 10m for its first pg_dump — far beyond the 90s
# budget — so it must warn and succeed, not fail the upgrade.
# (sleep is stubbed, so the 18 x 5s poll loop runs instantly.)
# HC tuple format: "<start_period> <interval> <timeout> <retries> <live_status>".
# ============================================================================
seed_prod_env
PS_STATUS='backup|Up 30 seconds (health: starting)'
HC_BACKUP='600 30 5 3 starting'   # tolerance 600 + 5 + 3x35 = 710s > container age
STARTED_BACKUP="$(iso_ago 95)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "still-starting service INSIDE its healthcheck tolerance converges (upgrade succeeds)"
else
  bad "in-tolerance service failed the wait (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if grep -q "within their healthcheck's tolerance" "$WORK/out.txt"; then
  ok "converging services are surfaced with the tolerance warning"
else
  bad "no tolerance warning was printed for the converging service"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Codex P2 (#867): start_period alone is NOT the boundary. After it ends,
# failing probes only accumulate toward `retries` consecutive failures, and
# the service honestly stays `starting` until the streak is exhausted. The
# prod frontend (start_period 15s, interval 30s, timeout 10s, retries 3) can
# legitimately report `starting` at the 90s budget with only two post-grace
# failures — tolerance 15 + 10 + 3x40 = 145s > its 95s age — and must PASS
# the wait, even though its bare start_period (15s) is far below both.
seed_prod_env
PS_STATUS='frontend|Up About a minute (health: starting)'
HC_FRONTEND='15 30 10 3 starting'
STARTED_FRONTEND="$(iso_ago 95)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "service past start_period but inside its retry tolerance PASSES (Codex P2)"
else
  bad "mid-retry-streak service was failed prematurely (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Codex P2 round 2 (#867): a restart-policy service that crashed and
# restarted mid-wait is seconds old with a freshly reset health clock. Its
# tolerance (40s) is far below the 90s budget, but its AGE (5s) is inside
# start_period — comparing tolerance against the spent budget would fail an
# upgrade that is actually recovering. Age must win: this PASSES.
seed_prod_env
PS_STATUS='backup|Up 5 seconds (health: starting)'
HC_BACKUP='10 5 5 3 starting'
STARTED_BACKUP="$(iso_ago 5)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "service restarted mid-wait (young age, small tolerance) PASSES (Codex P2 round 2)"
else
  bad "freshly restarted service was classified overdue (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Codex P2 round 3 (#867): grace is judged by probe START time, so a probe
# launched just inside start_period can run `timeout` past the boundary
# before the counted retry cycles begin — the worst-case verdict lands at
# start_period + timeout + retries x (interval + timeout), one `timeout`
# later than round 1's bound. A container aged inside that final `timeout`
# margin (140s: past round 1's 135s bound for 15/30/10/3, inside the true
# 145s bound) was previously misclassified overdue and must PASS.
seed_prod_env
PS_STATUS='frontend|Up 2 minutes (health: starting)'
HC_FRONTEND='15 30 10 3 starting'
STARTED_FRONTEND="$(iso_ago 140)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "service inside the in-flight-probe timeout margin PASSES (Codex P2 round 3)"
else
  bad "service in the final timeout margin was classified overdue (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# ============================================================================
# CASE 9 — test(#826): a service whose container AGE is past its FULL
# tolerance (start_period + timeout + retries x (interval + timeout)) and still
# `(health: starting)` has outlived every verdict Docker could still be
# working on. It must FAIL the wait, not ride the converging branch — this
# was the untested hole where a broken healthcheck passed the upgrade.
# ============================================================================
seed_prod_env
PS_STATUS='backup|Up 2 minutes (health: starting)'
HC_BACKUP='10 5 5 3 starting'   # tolerance 10 + 5 + 3x10 = 45s, well under the 120s age
STARTED_BACKUP="$(iso_ago 120)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" != "0" ]; then
  ok "service stuck past its healthcheck tolerance FAILS the wait (upgrade exits non-zero)"
else
  bad "stuck service passed the wait (exit=0)"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if grep -q 'these services are not converging' "$WORK/out.txt" \
   && grep -q 'ended at 45s' "$WORK/out.txt"; then
  ok "failure names the overdue service with its computed tolerance"
else
  bad "overdue-service diagnostic missing from the output"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if grep -q 'ROLLBACK' "$WORK/out.txt"; then
  ok "stuck service failure prints the rollback recipe"
else
  bad "stuck service failure did not print the rollback recipe"
fi

# Mixed: one straggler within its tolerance, one past it — the overdue one
# must still fail the wait (no blanket pass because A converging service
# exists).
seed_prod_env
PS_STATUS='backup|Up 2 minutes (health: starting)
api|Up 2 minutes (health: starting)'
HC_BACKUP='600 30 5 3 starting'
STARTED_BACKUP="$(iso_ago 120)"
HC_API='10 5 5 3 starting'
STARTED_API="$(iso_ago 120)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" != "0" ] && grep -q 'api: still (health: starting)' "$WORK/out.txt"; then
  ok "mixed stragglers: the overdue service fails the wait even beside a converging one"
else
  bad "mixed stragglers did not fail on the overdue service (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi
HC_API=""
STARTED_API=""

# Unreadable healthcheck config fails OPEN (converging), matching the
# script's other best-effort probes — a docker inspect hiccup must not tell
# the operator to roll back a stack that is coming up fine.
seed_prod_env
PS_STATUS='backup|Up 30 seconds (health: starting)'
HC_BACKUP=""
STARTED_BACKUP="$(iso_ago 120)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && grep -q "within their healthcheck's tolerance" "$WORK/out.txt"; then
  ok "unreadable healthcheck config fails open (still-starting service treated as converging)"
else
  bad "unreadable healthcheck config blocked the upgrade (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Unparseable StartedAt also fails OPEN (Codex P2 round 2): without a
# trustworthy age, classifying the service overdue could fail a recovering
# stack — same best-effort posture as unreadable healthcheck config.
seed_prod_env
PS_STATUS='backup|Up 2 minutes (health: starting)'
HC_BACKUP='10 5 5 3 starting'
STARTED_BACKUP='garbage-not-a-timestamp'
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && grep -q "within their healthcheck's tolerance" "$WORK/out.txt"; then
  ok "unparseable StartedAt fails open (no age, service treated as converging)"
else
  bad "unparseable StartedAt blocked the upgrade (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Codex P2 round 4 (#867): the `remaining` table is a snapshot — a probe can
# complete between that `compose ps` and the per-service inspect and flip
# the container out of `starting`. The tolerance math must yield to the LIVE
# status read in the same inspect.
#
# Flip to (unhealthy): Docker has ruled; the service must FAIL even though
# its age (5s) is comfortably inside its tolerance — age math must not
# overrule a verdict.
seed_prod_env
PS_STATUS='backup|Up 5 seconds (health: starting)'
HC_BACKUP='10 5 5 3 unhealthy'
STARTED_BACKUP="$(iso_ago 5)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" != "0" ] \
   && grep -q 'is (unhealthy) on inspection' "$WORK/out.txt"; then
  ok "service that flipped to (unhealthy) after the snapshot FAILS the wait (Codex P2 round 4)"
else
  bad "raced-to-unhealthy service was not failed (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# Flip to (healthy): converged; the service must PASS even though its age
# (120s) is far past its 45s tolerance — the verdict wins in both directions.
seed_prod_env
PS_STATUS='backup|Up 2 minutes (health: starting)'
HC_BACKUP='10 5 5 3 healthy'
STARTED_BACKUP="$(iso_ago 120)"
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of app_up)" ]; then
  ok "service that flipped to (healthy) after the snapshot PASSES the wait (Codex P2 round 4)"
else
  bad "raced-to-healthy service was failed by stale tolerance math (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# ============================================================================
# CASE 10 — test(#826): an (unhealthy) service at budget end takes the broken
# branch and fails the wait (previously untested — the stub always answered
# an empty, instantly-healthy stack).
# ============================================================================
seed_prod_env
PS_STATUS='api|Up 3 minutes (unhealthy)'
run_upgrade ok 1.2.4
if [ "$(cat "$WORK/code.txt")" != "0" ] && grep -q 'timed out after 90s waiting for services' "$WORK/out.txt"; then
  ok "(unhealthy) service at budget end fails the wait with the timeout diagnostic"
else
  bad "(unhealthy) service did not fail the wait (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi
PS_STATUS=""
HC_BACKUP=""
HC_FRONTEND=""
STARTED_BACKUP=""
STARTED_FRONTEND=""

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
