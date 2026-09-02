#!/bin/sh
# Regression test for scripts/restore.sh's EXIT trap (fix(#1778)).
#
# Pure shell with a stubbed `docker` on PATH that records call order to a log;
# no real stack, no DB, no network. Real restore.sh, real common.sh — only
# `docker` is faked.
#
# Asserts:
#   - a HARD pg_restore failure (stderr carries "ERROR:") leaves api/worker
#     STOPPED — before the fix, the EXIT trap restarted them unconditionally,
#     starting the app's boot-time migrations against a database that has
#     already been --clean-dropped and only partly repopulated, with no ACLs
#     re-applied
#   - a failed post-restore grant verification (geolens_reader USAGE) ALSO
#     leaves api/worker stopped, for the identical reason
#   - the ordinary warnings-only pg_restore exit (--clean --if-exists on a
#     fresh DB) still restarts api/worker once the mandatory grant
#     reconciliation has run and verified
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"       # scripts/
RESTORE_SH="$REPO_ROOT/restore.sh"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

FAKE="$WORK/repo"
mkdir -p "$FAKE/scripts/lib"
cp "$RESTORE_SH" "$FAKE/scripts/restore.sh"
cp "$REPO_ROOT/lib/common.sh" "$FAKE/scripts/lib/common.sh"
chmod +x "$FAKE/scripts/restore.sh"
printf 'services: {}\n' > "$FAKE/docker-compose.yml"

# A real .dump file the pg_restore-integrity stub reads (content is never
# parsed for real; the stub decides pass/fail from env vars).
BACKUP_FILE="$WORK/geolens_20260101_000000.dump"
printf 'PGDMP-fake-custom-format-dump-bytes\n' > "$BACKUP_FILE"

SHIM="$WORK/bin"
mkdir -p "$SHIM"

# --- docker stub -------------------------------------------------------------
# Dispatches on the compose subcommand and, for `exec`, on a distinguishing
# substring of the remaining args (restore.sh's SQL text arrives via argv for
# the -tAc calls and via stdin heredoc for the DDL setup, so only the -tAc
# calls are pattern-matchable that way).
cat > "$SHIM/docker" <<'DOCKER'
#!/bin/sh
LOG="${DOCKER_LOG:?}"
RESTORE_EXIT="${RESTORE_EXIT:-0}"
RESTORE_STDERR_TEXT="${RESTORE_STDERR_TEXT:-}"
READER_USAGE_OUT="${READER_USAGE_OUT:-t}"
RECONCILE_EXIT="${RECONCILE_EXIT:-0}"

if [ "$1" = "compose" ]; then
  shift
  if [ "$1" = "-f" ]; then shift; shift; fi
  case "$1" in
    stop)  echo "stop_app" >> "$LOG"; exit 0 ;;
    start) echo "restart_app" >> "$LOG"; exit 0 ;;
    exec)
      shift  # drop "exec"
      case "$*" in
        *--clean*)
          echo "restore" >> "$LOG"
          cat > /dev/null
          [ -n "$RESTORE_STDERR_TEXT" ] && printf '%s' "$RESTORE_STDERR_TEXT" >&2
          exit "$RESTORE_EXIT" ;;
        *configure-runtime-db-role*)
          echo "reconcile" >> "$LOG"
          exit "$RECONCILE_EXIT" ;;
        *has_schema_privilege*)
          echo "check_reader" >> "$LOG"
          printf '%s' "$READER_USAGE_OUT"
          exit 0 ;;
        *pg_restore*)
          # The pre-restore integrity check (`pg_restore -f /dev/null`,
          # stdin-fed): always succeeds so every case reaches the actual
          # restore call above.
          cat > /dev/null
          exit 0 ;;
        *)
          # DDL setup (heredoc stdin) and the final post-restore validation
          # query — neither is asserted on here.
          cat > /dev/null 2>/dev/null
          exit 0 ;;
      esac ;;
    *) exit 0 ;;
  esac
fi
exit 0
DOCKER
chmod +x "$SHIM/docker"

run_restore() {
  CALLLOG="$WORK/calls.log"
  : > "$CALLLOG"
  ( cd "$WORK" && env "PATH=$SHIM:$PATH" \
      DOCKER_LOG="$CALLLOG" \
      RESTORE_EXIT="${RESTORE_EXIT:-0}" \
      RESTORE_STDERR_TEXT="${RESTORE_STDERR_TEXT:-}" \
      READER_USAGE_OUT="${READER_USAGE_OUT:-t}" \
      RECONCILE_EXIT="${RECONCILE_EXIT:-0}" \
      bash "$FAKE/scripts/restore.sh" "$BACKUP_FILE" </dev/null > "$WORK/out.txt" 2>&1 )
  echo $? > "$WORK/code.txt"
}

pos_of() { grep -n "^$1\$" "$WORK/calls.log" 2>/dev/null | head -n1 | cut -d: -f1; }

# ============================================================================
# CASE 1 — hard pg_restore failure (stderr carries "ERROR:"): the trap must
# leave api/worker STOPPED, not restart them onto a half-restored database.
# ============================================================================
RESTORE_EXIT=1
RESTORE_STDERR_TEXT='pg_restore: error: could not execute query: ERROR:  syntax error'
run_restore
RESTORE_EXIT=0
RESTORE_STDERR_TEXT=

if [ "$(cat "$WORK/code.txt")" != "0" ]; then
  ok "hard pg_restore failure makes restore.sh exit non-zero"
else
  bad "hard pg_restore failure did not fail restore.sh"
fi
if [ -z "$(pos_of restart_app)" ]; then
  ok "hard pg_restore failure leaves api/worker STOPPED (no restart_app call)"
else
  bad "hard pg_restore failure restarted api/worker onto a half-restored DB"
fi
if [ -z "$(pos_of reconcile)" ]; then
  ok "hard pg_restore failure never reaches the grant reconciliation step"
else
  bad "grant reconciliation ran despite the hard pg_restore failure"
fi
if grep -q 'Leaving api/worker STOPPED' "$WORK/out.txt"; then
  ok "hard pg_restore failure explains why the app was left stopped"
else
  bad "hard pg_restore failure did not explain the stopped app"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# ============================================================================
# CASE 2 — grant verification fails (geolens_reader lacks USAGE) even though
# pg_restore itself succeeded: same reasoning, same left-stopped outcome.
# ============================================================================
READER_USAGE_OUT='f'
run_restore
READER_USAGE_OUT='t'

if [ "$(cat "$WORK/code.txt")" != "0" ]; then
  ok "failed grant verification makes restore.sh exit non-zero"
else
  bad "failed grant verification did not fail restore.sh"
fi
if [ -n "$(pos_of reconcile)" ]; then
  ok "failed grant verification case DID attempt reconciliation"
else
  bad "reconciliation was never attempted"
fi
if [ -z "$(pos_of restart_app)" ]; then
  ok "failed grant verification leaves api/worker STOPPED (no restart_app call)"
else
  bad "failed grant verification restarted api/worker with grants unverified"
fi

# ============================================================================
# CASE 3 — the ordinary warnings-only pg_restore exit (--clean --if-exists on
# a fresh DB, no "ERROR:" in stderr) must still restart api/worker once the
# mandatory reconciliation has run and every grant verified — the fix must
# not regress the BUG-022 behavior this trap exists for.
# ============================================================================
RESTORE_EXIT=1
RESTORE_STDERR_TEXT='pg_restore: warning: errors ignored on restore: 1'
run_restore
RESTORE_EXIT=0
RESTORE_STDERR_TEXT=

if [ "$(cat "$WORK/code.txt")" = "0" ]; then
  ok "warnings-only pg_restore exit does not fail restore.sh"
else
  bad "warnings-only pg_restore exit failed restore.sh: $(cat "$WORK/out.txt")"
fi
r="$(pos_of restart_app)"; c="$(pos_of reconcile)"
if [ -n "$r" ] && [ -n "$c" ] && [ "$c" -lt "$r" ]; then
  ok "warnings-only path reconciles grants THEN restarts api/worker ($c < $r)"
else
  bad "warnings-only path did not reconcile-then-restart (reconcile=$c restart=$r)"
  sed 's/^/    # /' "$WORK/out.txt"
fi

# ============================================================================
# CASE 4 — happy path (pg_restore exits 0 cleanly): same restart-at-the-end
# contract.
# ============================================================================
run_restore
if [ "$(cat "$WORK/code.txt")" = "0" ] && [ -n "$(pos_of restart_app)" ]; then
  ok "clean pg_restore success restarts api/worker"
else
  bad "clean pg_restore success did not restart api/worker (exit=$(cat "$WORK/code.txt"))"
  sed 's/^/    # /' "$WORK/out.txt"
fi

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
