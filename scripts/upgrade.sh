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
#   2.5 Refuse to cross a PostgreSQL major (chore(#704)) — abort before any
#      change with a pointer to RUNBOOK section 6.
#   3. Export GEOLENS_VERSION=<target> for compose (NOT written to .env yet).
#   4. Sync the on-disk release files to the target tag.
#   5. compose pull --ignore-buildable.
#   6. OUTAGE STARTS — stop api + worker, then PRE-UPGRADE BACKUP (pg_dump -Fc
#      to a timestamped file). Abort if it is missing/empty/unreadable.
#   7. Run the one-shot migrate (fail-closed since phase 1216) — abort on non-zero
#      BEFORE bringing the app up.
#   8. Persist GEOLENS_VERSION to .env, compose up -d, wait_for_healthy — OUTAGE
#      ENDS.
#   9. Success: print the ROLLBACK recipe for reference. Any failure: print the
#      same rollback recipe and exit non-zero — and while the app is still
#      deliberately stopped, put the PREVIOUS release back first.
#
# fix(#1467): steps 3-5 all run before the stop, so the outage is stop -> dump ->
# migrate -> start and never includes the download. Everything from step 6 on
# runs with no application writers, so a data migration may assume it sees the
# final state of the old data.
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
# fix(#1778 review round 6, P2): get_env_value now returns 1 (empty stdout)
# when a key has no `key=` line in .env at all, distinct from a key present
# with an empty value — `|| true` keeps that a no-op here, since every use
# below already treats "" as "not set" via `[ -n "$X" ] || X=default` /
# `${X:-...}`, and this script has no inherited-process-value case to
# preserve the way restore.sh/check-env.sh do (nothing here reads these
# vars before this point). Without the guard, a plain `.env` missing one of
# these optional keys would abort the whole upgrade under `set -eu`.
COMPOSE_FILE="$(get_env_value COMPOSE_FILE)" || true
[ -n "$COMPOSE_FILE" ] || COMPOSE_FILE="docker-compose.yml"
CURRENT_VERSION="$(get_env_value GEOLENS_VERSION)" || true

if [ "$COMPOSE_FILE" != "docker-compose.prod.yml" ]; then
  say "This install builds images from source (COMPOSE_FILE=$COMPOSE_FILE)."
  say ""
  say "scripts/upgrade.sh upgrades PREBUILT-IMAGE installs only. To upgrade a"
  say "source-build install, update the checkout and rebuild:"
  say ""
  say "  docker compose -f docker-compose.yml stop api worker          # outage starts"
  say "  git fetch --tags origin"
  say "  git checkout <new-tag>          # e.g. v1.2.4"
  say "  docker compose -f docker-compose.yml build"
  say "  docker compose -f docker-compose.yml up -d --no-deps migrate  # run migrations"
  say "  docker compose -f docker-compose.yml up -d                    # outage ends"
  say ""
  # fix(#1467): the stop leads, and it is part of the recipe rather than an
  # optimisation. Migrations that backfill existing rows must not run while the
  # old release is still writing, and this compose file bind-mounts
  # ./backend/app into the api container, so checking out the new tag under a
  # running app swaps its code immediately.
  say "Take the backup with api + worker already stopped (see UPGRADING.md)."
  say "No changes were made."
  exit 0
fi

export GEOLENS_VERSION="${CURRENT_VERSION:-latest}"
# What every failure path rolls back TO. An install with no GEOLENS_VERSION line
# is already running whatever `latest` resolved to, which is also what compose
# falls back to, so the two spellings are the same instance.
PREVIOUS_VERSION="${CURRENT_VERSION:-latest}"

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

# fix(#1778 review round 6, P2): see the Step 1 comment above — `|| true`
# keeps a missing key a no-op, since the next two lines already default an
# empty result.
POSTGRES_USER="$(get_env_value POSTGRES_USER)" || true
POSTGRES_DB="$(get_env_value POSTGRES_DB)" || true
[ -n "$POSTGRES_USER" ] || POSTGRES_USER="geolens"
[ -n "$POSTGRES_DB" ] || POSTGRES_DB="geolens"

TARGET_TAG="v${TARGET_VERSION}"

# --- Step 2.5: refuse to cross a PostgreSQL major (chore(#704)) --------------
# A PG N data volume cannot be opened by a PG N+1 server ("database files are
# incompatible with server"), and this script has no path that migrates one.
# Left undetected, an upgrade that crosses the boundary either leaves the
# operator silently on the OLD major (compose does not rebuild the locally-built
# db image on its own) or crash-loops `db` at the health gate the moment
# anything does rebuild it. Compare the RUNNING server's major against the
# target release's bundled db image and stop here, before anything has changed,
# with a pointer to the dump -> fresh volume -> restore procedure.
#
# Best-effort on both sides: a Docker-only host (no git) cannot read the target
# major, and an unreadable value on either side warns and continues rather than
# blocking an otherwise valid upgrade.
#
# Codex #707: skipped when DATABASE_URL_OVERRIDE points at an external database.
# A bundled install using the opt-in GEOLENS_RUNTIME_DB_ROLE also sets that
# override, so distinguish it by the Compose-only `db` hostname rather than by
# the role flag alone (fix(#1287 review)).
# fix(#1778 review round 6, P2): see the Step 1 comment above — both are
# optional flags already tested with `[ -n "$X" ]` below, so `|| true`
# keeps a missing key a no-op instead of aborting the upgrade.
DATABASE_URL_OVERRIDE_VALUE="$(get_env_value DATABASE_URL_OVERRIDE)" || true
RUNTIME_DB_ROLE_VALUE="$(get_env_value GEOLENS_RUNTIME_DB_ROLE)" || true
override_targets_bundled_db() {
  _url="$1"
  _authority="${_url#*://}"
  [ "$_authority" != "$_url" ] || return 1
  _authority="${_authority%%/*}"
  _host_port="${_authority##*@}"

  # libpq permits credentials in the authority with the host supplied only as
  # a query parameter: postgresql://user:pass@/db?host=db. Settings accepts
  # this form, so resolve it before applying the managed-database bypass.
  if [ -z "$_host_port" ]; then
    _query="${_url#*\?}"
    if [ "$_query" != "$_url" ]; then
      _host_port="$(printf '%s' "$_query" \
        | tr '&' '\n' \
        | sed -n 's/^host=\([^#]*\).*$/\1/p' \
        | head -n 1)"
    fi
  fi

  # PostgreSQL hostnames are case-insensitive. Decode the unreserved `db`
  # spelling (and an encoded port separator) that urllib.parse accepts too.
  _host_port="$(printf '%s' "$_host_port" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/%44/d/g' -e 's/%42/b/g' -e 's/%64/d/g' -e 's/%62/b/g' \
          -e 's/%3a/:/g')"
  case "$_host_port" in
    db|db:*) return 0 ;;
    *) return 1 ;;
  esac
}

bundled_runtime_override=false
if [ -n "$RUNTIME_DB_ROLE_VALUE" ] \
   && override_targets_bundled_db "$DATABASE_URL_OVERRIDE_VALUE"; then
  bundled_runtime_override=true
fi
target_pg_major=""
current_pg_major=""
if [ -n "$DATABASE_URL_OVERRIDE_VALUE" ] \
   && [ "$bundled_runtime_override" = "false" ]; then
  say "External database configured (DATABASE_URL_OVERRIDE) — skipping the bundled PostgreSQL major check."
else
  if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    git fetch --depth 1 --quiet "$REPO_URL" "refs/tags/${TARGET_TAG}:refs/tags/${TARGET_TAG}" 2>/dev/null \
      || git fetch --tags --quiet "$REPO_URL" 2>/dev/null || true
    target_pg_major="$(git show "${TARGET_TAG}:db/Dockerfile" 2>/dev/null \
      | sed -n 's|^FROM .*postgis/postgis:\([0-9][0-9]*\)-.*|\1|p' | head -n 1)"
  fi
  # server_version_num is major*10000 + minor for every version we support (>= 13).
  current_pg_num="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc 'SHOW server_version_num' 2>/dev/null | tr -cd '0-9')"
  if [ -n "$current_pg_num" ]; then
    current_pg_major="$((current_pg_num / 10000))"
  fi
fi

if [ -n "$target_pg_major" ] && [ -n "$current_pg_major" ] \
   && [ "$target_pg_major" != "$current_pg_major" ]; then
  say "GeoLens ${TARGET_VERSION} bundles PostgreSQL ${target_pg_major}; this install runs PostgreSQL ${current_pg_major}."
  say ""
  say "A PostgreSQL ${current_pg_major} data directory cannot be opened by a PostgreSQL"
  say "${target_pg_major} server, so this one-command upgrade cannot cross the boundary."
  say "The supported path is dump -> fresh volume -> restore:"
  say ""
  say "  RUNBOOK.md section 6 - Major PostgreSQL version upgrade"
  say "  https://github.com/geolens-io/geolens/blob/${TARGET_TAG}/RUNBOOK.md"
  say ""
  say "Nothing was changed. Your database is untouched and still on PostgreSQL ${current_pg_major}."
  fail "Refusing to upgrade across a PostgreSQL major version."
fi
say ""

# --- Step 3: select the target version for compose ---------------------------
# Export only — the .env pin is deliberately NOT written yet. Compose reads the
# environment ahead of .env, so this is all the sync, pull and migrate steps
# below need in order to resolve the target release's images, while .env keeps
# naming the version that is actually installed until Step 8 says otherwise
# (fix(#1467)).
export GEOLENS_VERSION="$TARGET_VERSION"

# --- Step 4: sync the on-disk release files to the target tag ----------------
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
say "Step 1/5: syncing release files to ${TARGET_TAG}, then pulling prebuilt images"
DB_CONF="db/postgresql.conf"
DB_CONF_CHANGED=0
DB_CONF_AT_TARGET=0
DB_DOCKERFILE="db/Dockerfile"
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
    # fix(#959): db/postgresql.conf is bind-mounted into the db container, so a
    # release that changes a Postgres setting (temp_file_limit, log_temp_files)
    # never reaches an existing install unless this file is synced too. Unlike
    # the files above it is one operators are told to tune (RUNBOOK section 4),
    # so overwrite it ONLY when it still matches the installed checkout; a
    # customised file is left alone with instructions to merge by hand.
    #
    # Both tests compare file CONTENT against release blobs, never against HEAD
    # or the index (codex review on #959's PR). A path-restricted checkout
    # updates the index and worktree but leaves HEAD at the tag the install was
    # created from, so a HEAD comparison would read the PREVIOUS upgrade's own
    # file as an operator edit and freeze the config forever; an index
    # comparison misses tuning the operator has staged, e.g. to version-control
    # it. Content against the installed release's blob is true in both cases:
    #   "needs changing"  = worktree differs from the TARGET tag's blob
    #   "operator edited" = worktree differs from the CURRENT release's blob
    # Unresolvable current tag => treated as edited, i.e. never clobbered.
    if [ -n "${CURRENT_VERSION:-}" ] && [ "$CURRENT_VERSION" != "latest" ]; then
      git fetch --depth 1 --quiet "$REPO_URL" \
        "refs/tags/v${CURRENT_VERSION}:refs/tags/v${CURRENT_VERSION}" 2>/dev/null || true
    fi
    if git cat-file -e "${TARGET_TAG}:${DB_CONF}" 2>/dev/null; then
      _db_conf_target="$(mktemp)"
      _db_conf_installed="$(mktemp)"
      if git show "${TARGET_TAG}:${DB_CONF}" > "$_db_conf_target" 2>/dev/null; then
        if cmp -s "$_db_conf_target" "$DB_CONF"; then
          DB_CONF_AT_TARGET=1   # already the release's file on disk
        elif git show "v${CURRENT_VERSION:-}:${DB_CONF}" > "$_db_conf_installed" 2>/dev/null \
             && cmp -s "$_db_conf_installed" "$DB_CONF"; then
          if git checkout --quiet "$TARGET_TAG" -- "$DB_CONF" 2>/dev/null; then
            DB_CONF_AT_TARGET=1
            say "  ${DB_CONF} synced to ${TARGET_TAG}"
          fi
        else
          warn "${DB_CONF} does not match the installed release — keeping your version."
          warn "  Review 'git diff ${TARGET_TAG} -- ${DB_CONF}', merge any new settings,"
          warn "  then apply them with 'docker compose up -d --force-recreate db'."
        fi
      fi
      rm -f "$_db_conf_target" "$_db_conf_installed"
    fi
    # fix(#1778): db is the ONLY locally-built image in a prebuilt install —
    # `compose pull --ignore-buildable` at Step 5 skips it by definition, and
    # `docker compose up -d` does not rebuild an existing local image on its
    # own. Left unsynced, a release that bumps the PostGIS/pgvector base
    # (db/Dockerfile) never reaches an existing install through this script,
    # and a migration that depends on the newer base fails mid-migrate with
    # no earlier signal. Same content-vs-release-blob comparison as
    # ${DB_CONF} above: sync only when the file still matches the installed
    # release's blob, so an operator's own Dockerfile edit is left alone.
    if git cat-file -e "${TARGET_TAG}:${DB_DOCKERFILE}" 2>/dev/null; then
      _db_dockerfile_target="$(mktemp)"
      _db_dockerfile_installed="$(mktemp)"
      if git show "${TARGET_TAG}:${DB_DOCKERFILE}" > "$_db_dockerfile_target" 2>/dev/null; then
        if cmp -s "$_db_dockerfile_target" "$DB_DOCKERFILE"; then
          : # already the release's file on disk — nothing to rebuild for
        elif git show "v${CURRENT_VERSION:-}:${DB_DOCKERFILE}" > "$_db_dockerfile_installed" 2>/dev/null \
             && cmp -s "$_db_dockerfile_installed" "$DB_DOCKERFILE"; then
          if git checkout --quiet "$TARGET_TAG" -- "$DB_DOCKERFILE" db/.dockerignore 2>/dev/null; then
            say "  ${DB_DOCKERFILE} synced to ${TARGET_TAG}"
          fi
        else
          warn "${DB_DOCKERFILE} does not match the installed release — keeping your version."
          warn "  Review 'git diff ${TARGET_TAG} -- ${DB_DOCKERFILE}', merge any base-image or"
          warn "  extension bump, then 'docker compose build db && docker compose up -d --force-recreate db'."
        fi
      fi
      rm -f "$_db_dockerfile_target" "$_db_dockerfile_installed"
    fi
  else
    warn "Could not fetch ${TARGET_TAG} from ${REPO_URL} — keeping the current checkout's compose/scripts."
  fi
else
  warn "git unavailable or not a git checkout — skipping release-file sync; keeping the current compose/scripts."
fi

# fix(#959): git only says what is on DISK. Whether the running database is
# serving it is a question only the container can answer, and an attempt that
# synced the config and then failed later (a pull error, say) leaves the
# release's file on disk and the OLD inode inside the container — a retry that
# trusted git alone would skip the bounce and run on stale settings forever.
# Scoped to a file that IS the release's, so an operator's own tuning is never
# applied as a side effect of upgrading. No db container (external/managed
# Postgres) or an unreadable file leaves this at 0.
if [ "$DB_CONF_AT_TARGET" = "1" ] && [ -f "$DB_CONF" ]; then
  _db_conf_running="$(mktemp)"
  if compose exec -T db cat /etc/postgresql/custom.conf > "$_db_conf_running" 2>/dev/null \
     && [ -s "$_db_conf_running" ] \
     && ! cmp -s "$_db_conf_running" "$DB_CONF"; then
    DB_CONF_CHANGED=1
  fi
  rm -f "$_db_conf_running"
fi
say ""

# --- Step 5: pull the new images, rebuild db locally if needed (the last steps before any downtime) ---------
compose pull --ignore-buildable \
  || fail "Could not pull prebuilt images for $TARGET_VERSION. Nothing was stopped, .env still pins ${PREVIOUS_VERSION}, and the database is untouched."
say ""

# fix(#1798 review round 8, P2): this whole block — computing whether the db
# image needs rebuilding, and the `compose build db` call itself — used to
# sit AFTER Step 6's `compose stop api worker`, i.e. inside the outage
# window. `compose build db` is the ONLY step compose pull's
# `--ignore-buildable` deliberately skips, so on a cache miss (db/Dockerfile
# changed, or this is the image's first build) it is a real network fetch of
# db/Dockerfile's base layer — exactly the class of "slow/unavailable
# registry" risk Step 5's pull comment above already calls out, just for a
# different image. Running it after the stop extended the outage by however
# long that fetch took, or failed the upgrade with the app already down. It
# now runs here, in the same pre-outage window as the pull, so a slow or
# failed base-image fetch is caught before anything is stopped — matching
# Step 5's own "Nothing was stopped" failure message below. Only the db
# CONTAINER RECREATE (a local operation against the image just built, not a
# network fetch) stays in the post-backup phase, where it belongs: db must
# stay up through the dump, and the recreate needs the app already stopped
# to be worth doing before the migrate step.
#
# fix(#1778 review, P1): an earlier version of this fix gated the rebuild on
# a DB_DOCKERFILE_CHANGED flag that only tracked whether THIS run's sync step
# wrote a new file — not whether the local image was ever actually rebuilt
# from it. A run that syncs db/Dockerfile and then fails before reaching the
# build (compose pull failing is enough) leaves the target Dockerfile on disk
# with the OLD image still installed. On retry, the sync comparison finds
# disk already equal to the target blob and takes the "nothing to do"
# branch, so that flag was 0 and the rebuild was skipped — migrations then
# ran against the stale PostGIS/pgvector image with no earlier signal
# anything was wrong.
#
# DB_IMAGE_BUILT_MARKER tracks image state instead of file-vs-target state: a
# byte snapshot of the db/Dockerfile the LOCAL IMAGE was actually built from,
# written only after `compose build db` succeeds. Comparing the on-disk
# Dockerfile against that marker (not against the release blob) answers "does
# the built image match what's on disk", regardless of how it got there or
# which run last touched it. A cmp-based snapshot is used instead of a hash so
# this needs no sha256sum/shasum dependency — the same reasoning the
# content-vs-release-blob sync comparisons above already rely on. A missing
# marker (fresh install of this script version, or the marker file was lost)
# is treated as "needs rebuild": a one-time rebuild that hits Docker's build
# cache when the image already matches, which establishes the marker going
# forward. The marker itself is only WRITTEN later, in the post-backup phase,
# after the recreate that makes a freshly built image live actually succeeds
# — see that block's own comment for why.
DB_IMAGE_BUILT_MARKER="$PROJECT_ROOT/.geolens-db-image-built-from"
DB_IMAGE_NEEDS_REBUILD=0
if [ -f "$DB_DOCKERFILE" ] \
   && { [ ! -f "$DB_IMAGE_BUILT_MARKER" ] || ! cmp -s "$DB_IMAGE_BUILT_MARKER" "$DB_DOCKERFILE"; }; then
  DB_IMAGE_NEEDS_REBUILD=1
fi

# fix(#1778 review round 2, P1): the marker alone cannot tell "the on-disk
# Dockerfile matches what was built" apart from "and that build is what the
# CONTAINER is actually running" — those used to be conflated by writing the
# marker right after `compose build db`, before the separate `compose up
# --force-recreate` that makes the new image live. Build succeeding while the
# recreate step fails (or never runs) left a marker claiming success while
# the running container was still on the old image; a retry then saw a
# matching marker and skipped both the rebuild and the recreate, and
# migrations ran against the stale container. The marker write stays in the
# post-backup phase, after the recreate succeeds. This block is a second,
# independent check for the same class of drift from any OTHER cause (a
# marker restored from backup, an operator's out-of-band `docker
# restart`/`down`+`up`): even when the marker matches db/Dockerfile, compare
# the RUNNING container's image id against the id compose would (re)build/run
# for `db` — a mismatch forces a rebuild and recreate regardless of what the
# marker says. `compose config --images` resolves the configured image name
# from the compose file alone (no container required), so this works even
# before `db` has ever been created; db itself is never stopped by this
# script, so reading its state here (before the api/worker stop) versus after
# is equivalent. Any lookup failing empty (no container yet, unreadable)
# fails open — like this script's other best-effort probes — since forcing a
# rebuild on every uncertain read would defeat the marker's purpose.
DB_IMAGE_STALE_CONTAINER=0
if [ "$DB_IMAGE_NEEDS_REBUILD" = "0" ]; then
  # fix(#1778 review round 7, P2): every lookup below now has an explicit
  # `|| printf ''` — without it, `compose ps -q db` / `docker inspect` /
  # `docker image inspect` returning nonzero (the db container vanished
  # between the `compose ps` above and this inspect, or Docker itself
  # hiccups) aborted the WHOLE upgrade under `set -eu`, contradicting the
  # "fails open" comment above: a probe failing is supposed to skip this
  # one drift check, not kill the script three steps into an upgrade.
  _db_image_tag="$(compose config --images db 2>/dev/null | head -n 1)"
  _db_container_id="$(compose ps -q db 2>/dev/null || printf '')"
  if [ -n "$_db_image_tag" ] && [ -n "$_db_container_id" ]; then
    _db_running_image_id="$(docker inspect --format '{{.Image}}' "$_db_container_id" 2>/dev/null || printf '')"
    _db_built_image_id="$(docker image inspect --format '{{.Id}}' "$_db_image_tag" 2>/dev/null || printf '')"
    if [ -n "$_db_running_image_id" ] && [ -z "$_db_built_image_id" ]; then
      # fix(#1778 review round 7, P2): the tagged local image `compose
      # config --images` resolved is gone (pruned) even though a `db`
      # container is currently running from SOME image — we cannot prove
      # it still matches what db/Dockerfile would build, which is exactly
      # what this check exists to prove before skipping a rebuild. Treat
      # a missing local image the same as a confirmed mismatch.
      DB_IMAGE_STALE_CONTAINER=1
      warn "The locally built db image (${_db_image_tag}) was not found locally (pruned?) — rebuilding it."
    elif [ -n "$_db_running_image_id" ] && [ -n "$_db_built_image_id" ] \
       && [ "$_db_running_image_id" != "$_db_built_image_id" ]; then
      DB_IMAGE_STALE_CONTAINER=1
      warn "The running db container's image does not match the locally built db image — rebuilding and recreating it."
    fi
  fi
fi

# fix(#1798 review round 8, P2): runs here, before Step 6's stop, so a
# db/Dockerfile base-layer fetch (the one thing --ignore-buildable above
# deliberately skips) cannot extend the outage or fail the upgrade after
# downtime has already begun. Only the container recreate that makes this
# build live stays in the post-backup phase (below) — see that block.
if [ "$DB_IMAGE_NEEDS_REBUILD" = "1" ] || [ "$DB_IMAGE_STALE_CONTAINER" = "1" ]; then
  say "Rebuilding the db image (db/Dockerfile differs from what the local image was last built from)"
  compose build db \
    || fail "Could not rebuild the db image from ${DB_DOCKERFILE}. Nothing was stopped, .env still pins ${PREVIOUS_VERSION}, and the database is untouched."
  say ""
fi

# --- Step 6: stop the app, then take the pre-upgrade backup ------------------
# fix(#1467): this line is the boundary. Everything ABOVE it — the release-file
# sync and the image pull — runs with the previous release still serving, which
# is where the download belongs: on a self-hosted link it is the longest part of
# an upgrade and it does not need the app to be down. Everything BELOW it runs
# with api + worker stopped, so a data migration may assume it sees the final
# state of the old data with no concurrent application writes behind it. A
# one-shot backfill that ran while the old code was still accepting writes would
# silently miss every row written in the window, and Alembic never re-runs the
# revision to repair them (#1467).
#
# Stopping the writers is also what makes the dump a consistent, no-lost-writes
# snapshot (Codex P1): pg_dump snapshots when it BEGINS and does NOT block
# writers, so a write acknowledged during the dump would be absent from the
# backup and lost if a failed migration later triggered the restore recipe.
#
# api and worker are the only services that write the catalog schema. db stays
# up (the dump and the migration both need it); frontend and titiler stay up and
# keep answering, though the frontend can only return errors for API calls until
# the new api is running.
BACKUP_DIR="$PROJECT_ROOT/backups/pre-upgrade"
mkdir -p "$BACKUP_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="$BACKUP_DIR/${POSTGRES_DB}_pre_${CURRENT_VERSION:-unknown}_to_${TARGET_VERSION}_${STAMP}.dump"

# Put the instance back the way we found it. `--no-deps` is load-bearing: the
# prod compose gives api a `depends_on: migrate: service_completed_successfully`
# edge, so a plain `up -d api worker` re-runs the one-shot — which on the
# migrate-failure path is the very thing that just failed, so the app would stay
# down. db is up throughout, so skipping deps costs nothing. GEOLENS_VERSION goes
# back to the previous release in the environment, which is what selects the old
# images; .env still names it (the pin does not move until Step 8).
APP_DOWN=0
restore_previous_app() {
  export GEOLENS_VERSION="$PREVIOUS_VERSION"
  compose up -d --no-deps api worker >/dev/null 2>&1
}

# `compose up -d` returns as soon as the containers are CREATED, which is not
# the same as the previous release serving again (codex P1 round 2 on #1476).
# The api image runs `alembic upgrade heads` on boot unless
# GEOLENS_API_RUN_MIGRATIONS=false, and refuses to start when it fails. So if a
# failed migration already committed a revision the OLD graph has never heard
# of, the restored api exits and the restart policy loops it. Watch it settle
# instead of reporting a restore that did not happen. An unreadable state fails
# open, like this script's other best-effort probes.
previous_app_settled() {
  _cid="$(compose ps -q api 2>/dev/null | head -n 1)"
  [ -n "$_cid" ] || return 1
  _i=0
  _state=""
  while [ "$_i" -lt 6 ]; do
    _i=$((_i + 1))
    _state="$(docker inspect --format '{{.State.Status}}' "$_cid" 2>/dev/null || printf '')"
    case "$_state" in
      restarting|exited|dead) return 1 ;;
      "") return 0 ;;
    esac
    sleep 5
  done
  [ "$_state" = "running" ]
}

report_restore() {
  if ! restore_previous_app; then
    warn "Could not start api + worker on GeoLens ${PREVIOUS_VERSION} — this instance is DOWN."
    warn "  docker compose -f $COMPOSE_FILE logs api"
    return 0
  fi
  if previous_app_settled; then
    say "Restored GeoLens ${PREVIOUS_VERSION}: api + worker are running again."
    return 0
  fi
  warn "GeoLens ${PREVIOUS_VERSION}'s api did not stay up — this instance is DOWN."
  warn "If the migration got far enough to commit a revision, the previous release"
  warn "cannot start against it: its own boot-time 'alembic upgrade heads' does not"
  warn "know that revision. Check with:"
  warn "  docker compose -f $COMPOSE_FILE logs api"
  warn "If that is what happened, going back means restoring the pre-upgrade dump"
  warn "(step 2 below), not restarting containers."
}

say "Step 2/5: stopping api + worker — the upgrade outage starts here"
# Hard precondition (Codex P1): if the stop fails, a writer may still be running,
# so the no-writers guarantee is NOT established — taking the rollback dump now
# could miss acknowledged writes, and the migration below could run underneath a
# live old app. Restart whatever we stopped and abort BEFORE the backup (the
# database is still untouched; this is before the rollback trap).
if ! compose stop api worker >/dev/null 2>&1; then
  report_restore
  fail "Could not stop api/worker to quiesce writers. The database was not touched (refusing to dump or migrate under active writers)."
fi
APP_DOWN=1

say "  pre-upgrade database backup -> $BACKUP_FILE"
# -Fc custom-format dump (the format restore.sh expects via pg_restore). Stream
# to the host file via `exec -T` so the dump lands outside the container.
if ! compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -Fc --no-owner --no-acl > "$BACKUP_FILE"; then
  rm -f "$BACKUP_FILE"
  report_restore
  fail "Pre-upgrade backup failed (pg_dump). Aborting before the database was changed."
fi
if [ ! -s "$BACKUP_FILE" ]; then
  rm -f "$BACKUP_FILE"
  report_restore
  fail "Pre-upgrade backup is empty. Aborting before the database was changed."
fi
# Read the archive back end-to-end before trusting it as the rollback artifact
# (fix(#714), same check backup.sh got in #710). A dump truncated by a disk that
# filled mid-write is non-empty and still passes `--list`, because the -Fc table
# of contents sits at the front — the damage is only visible once every data
# block is read. Do it here, while the pre-upgrade cluster is still intact and
# a re-dump is free; the next steps migrate the schema, after which this file is
# the only way back.
if ! compose exec -T db pg_restore -f /dev/null < "$BACKUP_FILE" >/dev/null 2>&1; then
  rm -f "$BACKUP_FILE"
  report_restore
  fail "Pre-upgrade backup did not read back cleanly (truncated or corrupt). Aborting before the database was changed."
fi
say "  backup OK ($(du -h "$BACKUP_FILE" 2>/dev/null | cut -f1) ) — restore with: scripts/restore.sh \"$BACKUP_FILE\""
say ""

# From here on, a failure has (potentially) changed the schema, so every failure
# path must print the rollback recipe. fix(#1467): while the app is still
# deliberately stopped, it must also put the previous release back — a failed
# upgrade never leaves the instance down. Doing it in the trap covers every way
# out, including a `set -e` abort nobody wrote a message for.
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
    if [ "$APP_DOWN" = "1" ]; then
      warn "Bringing the previous version back up so the app is not left stopped."
      report_restore
    fi
    print_rollback
  fi
}
trap rollback_trap EXIT

# fix(#959): the release's db/postgresql.conf needs the container RECREATED,
# not restarted or reloaded — `git checkout` writes a new inode and a
# single-file bind mount keeps resolving the one the container started with.
# fix(#1778): a rebuilt db image (built earlier, pre-outage — see above) needs
# the same recreate to pick it up. Do it before the migrate step, while the
# app is already stopped and the dump is already taken, and wait for the
# healthcheck.
if [ "$DB_CONF_CHANGED" = "1" ] || [ "$DB_IMAGE_NEEDS_REBUILD" = "1" ] || [ "$DB_IMAGE_STALE_CONTAINER" = "1" ]; then
  say "Recreating the db container"
  compose up -d --force-recreate --no-deps --wait db \
    || fail "Could not recreate the db container after syncing db/Dockerfile and/or ${DB_CONF}."
  say ""
  # fix(#1778 review round 2, P1): only NOW, after the recreate that makes
  # the running container match db/Dockerfile has actually succeeded, is it
  # true that the built image reflects the current file — record the marker
  # here instead of right after `compose build db`. A build that succeeds
  # followed by a recreate that fails must leave the marker exactly as it
  # was (missing or stale), so a retry rebuilds and recreates again rather
  # than seeing a false match and skipping both.
  if [ "$DB_IMAGE_NEEDS_REBUILD" = "1" ] || [ "$DB_IMAGE_STALE_CONTAINER" = "1" ]; then
    # .tmp-then-mv so a container/host killed mid-write never leaves a
    # truncated marker under the final name (the same reason every backup
    # artifact in this repo writes state that way). Failing to record it is
    # not fatal — it only costs a redundant, cache-hit rebuild on the next
    # upgrade — but is surfaced so a repeatedly-rebuilding operator knows why.
    if cp "$DB_DOCKERFILE" "${DB_IMAGE_BUILT_MARKER}.tmp" 2>/dev/null \
       && mv "${DB_IMAGE_BUILT_MARKER}.tmp" "$DB_IMAGE_BUILT_MARKER" 2>/dev/null; then
      :
    else
      rm -f "${DB_IMAGE_BUILT_MARKER}.tmp"
      warn "Could not record the db image build marker at ${DB_IMAGE_BUILT_MARKER} — the next upgrade will rebuild again even if db/Dockerfile has not changed."
    fi
  fi
fi

# --- Step 7: run migrations (fail-closed) BEFORE bringing the app up ---------
say "Step 3/5: running database migrations (fail-closed)"
# The prod compose migrate service is a one-shot. `up -d migrate` waits on db
# health and runs alembic upgrade heads; since phase 1216 it is fail-closed, so
# we trust its exit code. Use --exit-code-from to surface the migrate result.
# fix(#1467): api + worker are stopped for the whole of this step, so a data
# migration here sees the final state of the old data — no application write can
# land behind a one-shot backfill that has already passed the row.
if ! compose up -d --no-deps migrate; then
  fail "Migration step failed to start. $TARGET_VERSION was NOT started and the version pin in .env still reads ${PREVIOUS_VERSION}."
fi
# Confirm the one-shot exited 0 before proceeding to the app.
migrate_cid="$(compose ps -aq migrate 2>/dev/null | head -n 1)"
if [ -n "$migrate_cid" ]; then
  # Block until the one-shot actually exits, then read its code. `docker wait`
  # prints the exit code when the container stops — there is NO arbitrary timeout,
  # so a large/long-running migration is never falsely declared failed while it is
  # still applying (which would otherwise tell the operator to restore over a live
  # migration). (Codex P2)
  m_exit="$(docker wait "$migrate_cid" 2>/dev/null | head -n 1)"
  [ -n "$m_exit" ] || m_exit="?"
  if [ "$m_exit" != "0" ]; then
    warn "migrate one-shot exit=$m_exit. Last 30 log lines:"
    compose logs --tail 30 migrate 2>&1 | sed 's/^/  /' >&2
    fail "Migrations did NOT complete. The database may already hold part of ${TARGET_VERSION}'s migrations, and $TARGET_VERSION was NOT started. The version pin in .env still reads ${PREVIOUS_VERSION}."
  fi
else
  # fix(#1798 review round 11 audit, low-confidence item): `compose up -d
  # --no-deps migrate` just reported success starting this exact
  # container, and `ps -aq` (unlike a bare `ps -q`) includes stopped/
  # exited ones — so an EMPTY migrate_cid here means something already
  # went wrong (a Docker-level race or daemon hiccup) between that success
  # and this lookup, not a normal "not created yet" state the way it can
  # be for the db-image-staleness probes elsewhere in this file. Silently
  # falling through to "migrations applied." would tell the operator (and
  # the code below that commits the upgrade forward, unarming the
  # rollback trap) that the schema is safe to build on when there is no
  # evidence it ran at all.
  fail "Could not find the migrate one-shot container after starting it — migrations may not have run. $TARGET_VERSION was NOT started and the version pin in .env still reads ${PREVIOUS_VERSION}."
fi
say "  migrations applied."
# Committed forward. The schema is the new release's, so the trap must not put
# the previous release's containers back on top of it, and the rollback recipe
# (restore the dump, then re-pin) becomes the only correct answer.
#
# This has to be the FIRST thing after the migration succeeds, ahead of anything
# that can fail (codex P1 on #1476). Pinning .env below is fallible — an
# unwritable file, a full disk — and under `set -e` that abort reaches the EXIT
# trap. With the flag still armed, the trap would start ${PREVIOUS_VERSION}
# against a fully migrated schema, which is the state this flag exists to
# prevent. The app is then left stopped, which the printed rollback recipe
# covers; old code on a new schema is the worse of the two.
APP_DOWN=0
say ""

# --- Step 8: pin the new version, bring the app up, health gate --------------
# fix(#1467): the .env pin moves HERE, once the migrations have committed, not
# before them. While it moved first, a failed upgrade left .env naming a version
# whose migrations had not run — and re-running this script then read that pin as
# the installed version, decided there was nothing to upgrade, and exited 0 with
# the app still stopped.
say "Step 4/5: pinning GEOLENS_VERSION=$TARGET_VERSION in .env"
export GEOLENS_VERSION="$TARGET_VERSION"
update_env_value GEOLENS_VERSION "$TARGET_VERSION"
say ""

say "Step 5/5: starting GeoLens $TARGET_VERSION — the outage ends here"
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
