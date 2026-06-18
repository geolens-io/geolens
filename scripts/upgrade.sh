#!/bin/sh
set -eu

# ==============================================================================
# GeoLens Prebuilt-Image Upgrade (UPG-01)
# ==============================================================================
# One-command upgrade for a PREBUILT-IMAGE install (COMPOSE_FILE=
# docker-compose.prod.yml). Ordered, fail-safe steps:
#
#   1. Resolve the install dir + read .env (COMPOSE_FILE + current GEOLENS_VERSION).
#      If this is a source-build install (not the prod compose), print the
#      source-build upgrade instructions and exit 0 — this tool targets prebuilt.
#   2. Determine the TARGET version (arg $1, else newest remote release tag).
#   3. PRE-UPGRADE BACKUP — pg_dump -Fc to a timestamped file. Abort if it is
#      missing/empty. (Backup BEFORE we touch images or schema.)
#   4. Bump GEOLENS_VERSION (export + persist via update_env_value).
#   5. compose pull --ignore-buildable.
#   6. Run the one-shot migrate (fail-closed since phase 1216) — abort on non-zero
#      BEFORE bringing the app up.
#   7. compose up -d, then wait_for_healthy.
#   8. Success: print the ROLLBACK recipe for reference. Any failure: stop, print
#      the same rollback recipe, exit non-zero.
#
# Shared helpers (compose / wait_for_healthy / update_env_value / tag resolution)
# live in scripts/lib/common.sh. install.sh inlines its own copies (curl|sh
# single-file + getgeolens.com byte-sync contract) and is intentionally NOT
# refactored to source this lib.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=scripts/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# Allow tests / CI to stub the heavy commands, and operate from the repo root so
# `.env`, the compose files, and scripts/ are all relative-resolvable.
cd "$PROJECT_ROOT"

need_command docker
# NOTE: no host pg_dump requirement — the pre-upgrade backup runs INSIDE the db
# container (`compose exec -T db pg_dump`, Step 3 below), which Docker-only
# self-hosters always have. Requiring it on the host would abort the upgrade on
# machines that never installed Postgres client tools.
# git is NOT required up front: it is only needed to resolve the LATEST release
# tag when no explicit target is given (Step 2 below) and for the best-effort
# release-file sync (Step 3, which warns + continues pull-only without it). A
# Docker-only host can run `scripts/upgrade.sh <version>` with no git installed.
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required."

[ -f .env ] || fail "No .env found in $PROJECT_ROOT. Run scripts/install.sh first."

REPO_URL="${GEOLENS_REPO_URL:-https://github.com/geolens-io/geolens.git}"

# --- Step 1: read current install state -------------------------------------
COMPOSE_FILE="$(get_env_value COMPOSE_FILE)"
[ -n "$COMPOSE_FILE" ] || COMPOSE_FILE="docker-compose.yml"
CURRENT_VERSION="$(get_env_value GEOLENS_VERSION)"

if [ "$COMPOSE_FILE" != "docker-compose.prod.yml" ]; then
  say "This install builds images from source (COMPOSE_FILE=$COMPOSE_FILE)."
  say ""
  say "scripts/upgrade.sh upgrades PREBUILT-IMAGE installs only. To upgrade a"
  say "source-build install, update the checkout and rebuild:"
  say ""
  say "  git fetch --tags origin"
  say "  git checkout <new-tag>          # e.g. v1.2.4"
  say "  docker compose -f docker-compose.yml build"
  say "  docker compose -f docker-compose.yml up -d migrate   # run migrations"
  say "  docker compose -f docker-compose.yml up -d"
  say ""
  say "Take a backup first (see UPGRADING.md). No changes were made."
  exit 0
fi

export GEOLENS_VERSION="${CURRENT_VERSION:-latest}"

# --- Step 2: determine target version ---------------------------------------
if [ "$#" -ge 1 ] && [ -n "${1:-}" ]; then
  TARGET_RAW="$1"
else
  need_command git  # resolving the latest tag needs `git ls-remote`
  TARGET_RAW="$(resolve_latest_remote_tag "$REPO_URL")"
  [ -n "$TARGET_RAW" ] || fail "Could not resolve a release tag from $REPO_URL. Pass an explicit version: scripts/upgrade.sh <version>"
fi
# Published image tags are bare semver (1.2.4); accept either v1.2.4 or 1.2.4.
TARGET_VERSION="${TARGET_RAW#v}"

case "$TARGET_VERSION" in
  [0-9]*.[0-9]*.[0-9]*) : ;;
  *) fail "Target '$TARGET_RAW' is not a vX.Y.Z release version." ;;
esac

if [ -n "$CURRENT_VERSION" ] && [ "$CURRENT_VERSION" != "latest" ]; then
  cmp="$(semver_compare "$TARGET_VERSION" "$CURRENT_VERSION")"
  if [ "$cmp" = "same" ]; then
    say "Already on GeoLens $CURRENT_VERSION — nothing to upgrade."
    exit 0
  fi
  if [ "$cmp" = "older" ]; then
    warn "Target $TARGET_VERSION is OLDER than the installed $CURRENT_VERSION."
    warn "Downgrades are not a supported upgrade path (schema may have moved forward)."
    warn "To roll back, restore a pre-upgrade backup — see UPGRADING.md."
    fail "Refusing to 'upgrade' to an older version."
  fi
fi

say "Upgrading GeoLens: ${CURRENT_VERSION:-unknown} -> ${TARGET_VERSION}"
say ""

# --- Step 3: pre-upgrade backup ---------------------------------------------
POSTGRES_USER="$(get_env_value POSTGRES_USER)"
POSTGRES_DB="$(get_env_value POSTGRES_DB)"
[ -n "$POSTGRES_USER" ] || POSTGRES_USER="geolens"
[ -n "$POSTGRES_DB" ] || POSTGRES_DB="geolens"

BACKUP_DIR="$PROJECT_ROOT/backups/pre-upgrade"
mkdir -p "$BACKUP_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="$BACKUP_DIR/${POSTGRES_DB}_pre_${CURRENT_VERSION:-unknown}_to_${TARGET_VERSION}_${STAMP}.dump"

say "Step 1/5: pre-upgrade database backup -> $BACKUP_FILE"
# -Fc custom-format dump (the format restore.sh expects via pg_restore). Stream
# to the host file via `exec -T` so the dump lands outside the container.
if ! compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -Fc --no-owner --no-acl > "$BACKUP_FILE"; then
  rm -f "$BACKUP_FILE"
  fail "Pre-upgrade backup failed (pg_dump). Aborting before any changes were made."
fi
if [ ! -s "$BACKUP_FILE" ]; then
  rm -f "$BACKUP_FILE"
  fail "Pre-upgrade backup is empty. Aborting before any changes were made."
fi
say "  backup OK ($(du -h "$BACKUP_FILE" 2>/dev/null | cut -f1) ) — restore with: scripts/restore.sh \"$BACKUP_FILE\""
say ""

# From here on, a failure has (potentially) changed images/schema, so every
# failure path must print the rollback recipe.
print_rollback() {
  say ""
  say "=============================== ROLLBACK ==============================="
  say "1. Re-pin the previous version in .env:"
  say "     GEOLENS_VERSION=${CURRENT_VERSION:-<previous-version>}"
  say "2. Restore the pre-upgrade database dump:"
  say "     scripts/restore.sh \"$BACKUP_FILE\""
  say "3. Bring the previous version back up:"
  say "     docker compose -f $COMPOSE_FILE up -d"
  say ""
  say "Note: 'alembic downgrade' is NOT a supported rollback — restore the dump."
  say "======================================================================="
}
rollback_trap() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    warn "Upgrade FAILED (exit $rc). Your data is safe in $BACKUP_FILE."
    print_rollback
  fi
}
trap rollback_trap EXIT

# Quiesce the app's DB writers (api + worker) AFTER the backup + trap (Codex P1):
# the schema migration below must not run concurrently with old-version request /
# job handling, and no post-dump writes (which the backup does NOT contain, so a
# rollback would lose them) should be accepted. db stays up (migrate needs it);
# the final `compose up -d` restarts api/worker on the new images, and a failed
# upgrade's rollback recipe does the same.
say "Stopping api + worker to quiesce writers before migration"
compose stop api worker >/dev/null 2>&1 || warn "Could not stop api/worker (may already be down) — continuing."
say ""

# --- Step 4: bump the version pin -------------------------------------------
say "Step 2/5: pinning GEOLENS_VERSION=$TARGET_VERSION in .env"
export GEOLENS_VERSION="$TARGET_VERSION"
update_env_value GEOLENS_VERSION "$TARGET_VERSION"
say ""

# --- Step 4.5: sync the on-disk release files to the target tag --------------
# UPG (Codex P2): `compose pull` refreshes IMAGES only. Without this, the operator
# would keep the OLD checkout's compose file + container-mounted helper scripts, so
# a release that changed compose (a new service, mount, or env wiring) would boot
# new images against stale config. Path-restricted checkout of the target tag
# refreshes the compose files, scripts/lib, and the mounted helper scripts, but
# DELIBERATELY excludes the running scripts (upgrade.sh / restore.sh / install.sh)
# so this script is never swapped under itself mid-run, and never touches .env
# (gitignored). Best-effort: a non-git install or any git failure warns and
# continues with the current files (the pre-v1043 pull-only behaviour) rather than
# aborting the upgrade. Local edits to the tracked files above are replaced.
TARGET_TAG="v${TARGET_VERSION}"
say "Step 3/5: syncing release files to ${TARGET_TAG}, then pulling prebuilt images"
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  if git fetch --depth 1 --quiet "$REPO_URL" "refs/tags/${TARGET_TAG}:refs/tags/${TARGET_TAG}" 2>/dev/null \
     || git fetch --tags --quiet "$REPO_URL" 2>/dev/null; then
    # Compose files are the critical part (image tags + services/mounts/env).
    if git checkout --quiet "$TARGET_TAG" -- \
         docker-compose.prod.yml docker-compose.yml .env.example 2>/dev/null; then
      say "  compose files synced to ${TARGET_TAG}"
    else
      warn "Could not check out ${TARGET_TAG} compose files — keeping the current ones."
      warn "If this release changed docker-compose.prod.yml, review it after the upgrade."
    fi
    # Container-mounted helper scripts (best-effort; not every release ships all).
    if git checkout --quiet "$TARGET_TAG" -- \
         scripts/lib scripts/minio-setup.sh scripts/backup-entrypoint.sh 2>/dev/null; then
      say "  mounted helper scripts synced to ${TARGET_TAG}"
    fi
  else
    warn "Could not fetch ${TARGET_TAG} from ${REPO_URL} — keeping the current checkout's compose/scripts."
  fi
else
  warn "git unavailable or not a git checkout — skipping release-file sync; keeping the current compose/scripts."
fi
say ""

# --- Step 5: pull the new images --------------------------------------------
compose pull --ignore-buildable || fail "Could not pull prebuilt images for $TARGET_VERSION."
say ""

# --- Step 6: run migrations (fail-closed) BEFORE bringing the app up ---------
say "Step 4/5: running database migrations (fail-closed)"
# The prod compose migrate service is a one-shot. `up -d migrate` waits on db
# health and runs alembic upgrade heads; since phase 1216 it is fail-closed, so
# we trust its exit code. Use --exit-code-from to surface the migrate result.
if ! compose up -d --no-deps migrate; then
  fail "Migration step failed to start. App was NOT brought up to $TARGET_VERSION."
fi
# Confirm the one-shot exited 0 before proceeding to the app.
migrate_cid="$(compose ps -aq migrate 2>/dev/null | head -n 1)"
if [ -n "$migrate_cid" ]; then
  # Give the one-shot a moment to finish, then read its exit code.
  m_attempts=24
  m_i=0
  m_state=""
  m_exit="?"
  while [ "$m_i" -lt "$m_attempts" ]; do
    m_i=$((m_i + 1))
    m_state="$(docker inspect --format '{{.State.Status}}' "$migrate_cid" 2>/dev/null || printf '')"
    if [ "$m_state" = "exited" ]; then
      m_exit="$(docker inspect --format '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || printf '?')"
      break
    fi
    sleep 5
  done
  if [ "$m_exit" != "0" ]; then
    warn "migrate one-shot exit=$m_exit. Last 30 log lines:"
    compose logs --tail 30 migrate 2>&1 | sed 's/^/  /' >&2
    fail "Migrations did NOT complete. App was NOT brought up to $TARGET_VERSION."
  fi
fi
say "  migrations applied."
say ""

# --- Step 7: bring the app up + health gate ---------------------------------
say "Step 5/5: starting GeoLens $TARGET_VERSION"
compose up -d || fail "compose up failed for $TARGET_VERSION."
if ! wait_for_healthy; then
  fail "GeoLens $TARGET_VERSION did not come up cleanly. See the failing service output above."
fi

# Success — defuse the failure trap and print the rollback recipe for reference.
trap - EXIT
say ""
say "GeoLens upgraded to $TARGET_VERSION and is healthy."
say ""
say "Pre-upgrade backup kept at: $BACKUP_FILE"
print_rollback
