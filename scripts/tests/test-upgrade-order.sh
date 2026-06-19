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
      # docker compose exec -T db pg_dump ...  -> the backup path; the real
      # pg_dump runs in-container, so emit a non-empty dump to stdout and log it.
      echo "backup" >> "$LOG"
      printf 'PGDMP-fake-custom-format-dump-bytes\n'
      exit 0 ;;
    up)
      # detect the migrate one-shot vs the full app up
      for a in "$@"; do
        if [ "$a" = "migrate" ]; then echo "migrate_up" >> "$LOG"; exit 0; fi
      done
      echo "app_up" >> "$LOG"; exit 0 ;;
    ps)
      # `ps -aq migrate` -> a fake container id; `ps --format ...` -> empty
      # (no unhealthy services, health gate passes immediately).
      for a in "$@"; do
        if [ "$a" = "migrate" ]; then echo "mig-cid"; exit 0; fi
      done
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
  # --format '{{.State.Status}}' -> exited ; '{{.State.ExitCode}}' -> 0|3
  case "$*" in
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

  # --- git stub: ls-remote returns a newer tag for auto-resolve. fetch/checkout
  # (the UPG release-file sync) record to $GIT_LOG so the sync can be asserted
  # WITHOUT polluting the docker call-order log. rev-parse --git-dir succeeds so
  # upgrade.sh treats the fake tree as a git checkout. Everything else is a no-op.
  cat > "$SHIM/git" <<'GIT'
#!/bin/sh
GLOG="${GIT_LOG:-/dev/null}"
case "$1" in
  ls-remote) printf 'deadbeef\trefs/tags/v1.2.4\n' ;;
  fetch)     echo "fetch" >> "$GLOG" ;;
  checkout)  echo "checkout" >> "$GLOG" ;;
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
}

run_upgrade() {  # $1=migrate mode, rest=args to upgrade.sh
  _mode="$1"; shift
  make_stubs "$_mode"
  ( env "PATH=$SHIM:$PATH" GEOLENS_REPO_URL="file:///fake" \
      DOCKER_LOG="$CALLLOG" DOCKER_MIGRATE_MODE="$_mode" GIT_LOG="$GITLOG" \
      DOCKER_STOP_MODE="${STOP_MODE:-ok}" \
      sh "$FAKE/scripts/upgrade.sh" "$@" </dev/null > "$WORK/out.txt" 2>&1 )
  echo $? > "$WORK/code.txt"
}

# Position of an event in the call log (line number; empty if absent).
pos_of() { grep -n "^$1\$" "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1; }

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

# Full expected order recorded: stop_app, backup, pull, migrate_up, app_up
order="$(tr '\n' ',' < "$WORK/calls.log")"
if [ "$order" = "stop_app,backup,pull,migrate_up,app_up," ]; then
  ok "full call order is stop api/worker -> backup -> pull -> migrate -> app_up"
else
  bad "unexpected call order: $order"
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

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
