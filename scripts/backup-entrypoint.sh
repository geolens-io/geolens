#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GeoLens Automated Backup Entrypoint
# ==============================================================================
# Runs pg_dump on a cron schedule with daily/weekly retention and optional
# S3 upload. Each cycle also captures the cluster globals (roles + cluster-wide
# grants), which a database-only pg_dump cannot carry. Designed for the
# default-on Docker Compose backup service.
#
# Environment variables (set in docker-compose.yml):
#   POSTGRES_USER          Database username
#   POSTGRES_PASSWORD      Database password
#   POSTGRES_DB            Database name (default: geolens)
#   POSTGRES_HOST          Database hostname (default: db)
#   BACKUP_SCHEDULE        Cron expression (default: "0 2 * * *")
#   BACKUP_RETENTION_DAILY Number of daily backups to keep (default: 7)
#   BACKUP_RETENTION_WEEKLY Number of weekly backups to keep (default: 4)
#   BACKUP_S3_ENABLED      Upload to S3 (default: false)
#   S3_ENDPOINT            S3/MinIO endpoint URL
#   S3_BUCKET              S3 bucket name
#   S3_ACCESS_KEY_ID       S3 access key
#   S3_SECRET_ACCESS_KEY   S3 secret key
#   S3_REGION              S3 region (default: us-east-1)
#   S3_ADDRESSING_STYLE    S3 addressing style: auto, path, virtual (default: auto)
#
# The uploader (awscli) follows whatever scheme S3_ENDPOINT carries — use an
# http:// endpoint for plain-HTTP MinIO. There is no separate allow-http knob
# here; S3_ALLOW_HTTP only affects the app's own object-storage client.
# ==============================================================================

# Overridable only so scripts/tests/test-backup-restore-roundtrip.sh can drive a
# real cycle into a temp directory instead of re-implementing one. Nothing in
# either compose file sets it, so every deployment gets /backups. Same shape as
# STAGING_DIR below.
BACKUP_DIR="${BACKUP_DIR:-/backups}"
DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

# BKP-01 (Phase 1219): the upload_staging volume is mounted read-only at
# /staging. Each backup cycle tars it alongside the pg_dump so a restore can
# reproduce a WORKING instance (DB rows + the staged source objects). Override
# the mount point if the compose file changes it.
STAGING_DIR="${STAGING_DIR:-/staging}"

POSTGRES_DB="${POSTGRES_DB:-geolens}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
BACKUP_RETENTION_DAILY="${BACKUP_RETENTION_DAILY:-7}"
BACKUP_RETENTION_WEEKLY="${BACKUP_RETENTION_WEEKLY:-4}"
BACKUP_S3_ENABLED="${BACKUP_S3_ENABLED:-false}"
S3_REGION="${S3_REGION:-us-east-1}"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Retention must be a positive integer: prune keeps only the newest N files,
# so a retention of 0 would delete the dump this very cycle just produced and
# then mark the cycle successful — a backup service that retains nothing.
# Checked on every invocation (startup and cron --run-backup re-entry).
for _ret_var in BACKUP_RETENTION_DAILY BACKUP_RETENTION_WEEKLY; do
    eval "_ret_val=\$$_ret_var"
    case "$_ret_val" in
        ''|*[!0-9]*)
            log "ERROR: ${_ret_var}='${_ret_val}' is not a plain integer"
            exit 1
            ;;
    esac
    if [ "$_ret_val" -lt 1 ]; then
        log "ERROR: ${_ret_var}='${_ret_val}' must be >= 1 — a retention of 0 would delete each backup as soon as it is written"
        exit 1
    fi
done
unset _ret_var _ret_val

# ---------------------------------------------------------------------------
# pg_dump
# ---------------------------------------------------------------------------
run_backup() {
    local timestamp
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    # fix(#995 review): decide "is this a weekly cycle?" ONCE, with the
    # timestamp that names the cycle, and reuse it for every artifact. Each one
    # used to re-ask the weekday at the moment it was written, so a Sunday
    # cycle that crossed midnight — a 23:59 schedule, or a large staging
    # archive — could copy the dump into weekly/ and then answer Monday for its
    # companions, leaving a weekly dump with no paired globals.
    CYCLE_IS_WEEKLY=0
    [ "$(date '+%u')" = "7" ] && CYCLE_IS_WEEKLY=1
    local filename="${POSTGRES_DB}_${timestamp}.dump"
    local filepath="${DAILY_DIR}/${filename}"

    # fix(#819): orphaned .tmp dumps (pg_dump killed mid-write) match no prune glob and
    # would accumulate forever; a new cycle starting means no dump is in
    # flight, so any leftover .tmp is garbage. fix(#995): the globals dump
    # writes through the same .tmp-then-rename path, in both directories, and
    # needs the same sweep. fix(#1778): the weekly dump copy and both staging
    # archive locations now write through the same path too.
    rm -f "${DAILY_DIR}"/*.dump.tmp "${DAILY_DIR}"/globals-*.sql.tmp \
        "${WEEKLY_DIR}"/globals-*.sql.tmp "${WEEKLY_DIR}"/*.dump.tmp \
        "${DAILY_DIR}"/staging-*.tar.gz.tmp "${WEEKLY_DIR}"/staging-*.tar.gz.tmp

    log "Starting backup: ${filename}"

    export PGPASSWORD="${POSTGRES_PASSWORD}"
    # Dump to a .tmp name and rename only on success: if pg_dump is killed
    # mid-write (prod mem_limit OOM, container stop, disk full) a truncated
    # file under the final name would sit in the retention window looking like
    # a complete backup. The rename makes a *.dump file appear only atomically.
    if pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -Fc --no-owner --no-acl -f "${filepath}.tmp"; then
        mv "${filepath}.tmp" "$filepath"
        local size
        size="$(du -h "$filepath" | cut -f1)"
        log "Backup complete: ${filename} (${size})"
    else
        log "ERROR: pg_dump failed"
        rm -f "${filepath}.tmp"
        return 1
    fi

    # Verify the dump NOW, while the previous cycle's good copy is still inside
    # retention — a corrupt dump is byte-for-byte indistinguishable from a good
    # one until something parses it, and discovering that during a restore is
    # too late.
    #
    # MUST be `-f /dev/null`, NOT `--list`. In a -Fc archive the table of
    # contents sits at the front, so `--list` succeeds on a dump truncated
    # anywhere after it — measured: a 60%-truncated dump passes `--list` and
    # fails `-f /dev/null`. Truncation (disk filled mid-dump, half-written
    # file) is precisely the corruption this is meant to catch, so the cheaper
    # check would be theatre. `-f /dev/null` decompresses every data block and
    # writes the SQL nowhere; it costs ~0.1s per 20 MB and touches no database.
    if ! pg_restore -f /dev/null < "$filepath" > /dev/null 2>&1; then
        log "ERROR: ${filename} failed verification (pg_restore could not read it) — discarding the corrupt dump"
        rm -f "$filepath"
        return 1
    fi
    log "Backup verified: ${filename} fully readable"

    # Weekly copy on Sundays
    if [ "$CYCLE_IS_WEEKLY" -eq 1 ]; then
        # fix(#1778): same .tmp-then-rename as the daily dump and the weekly
        # globals copy — a container killed mid-cp (OOM, `compose stop`,
        # ENOSPC) would otherwise leave a truncated file under the final
        # weekly dump name, indistinguishable from a good one until a
        # restore months later tries to read it.
        if ! cp "$filepath" "${WEEKLY_DIR}/${filename}.tmp" \
            || ! mv "${WEEKLY_DIR}/${filename}.tmp" "${WEEKLY_DIR}/${filename}"; then
            log "ERROR: could not write the weekly dump copy to ${WEEKLY_DIR}"
            rm -f "${WEEKLY_DIR}/${filename}.tmp"
            return 1
        fi
        log "Weekly copy saved: ${filename}"
    fi

    # BKP-01: archive the object-storage staging volume alongside the dump.
    # Named with the SAME timestamp as the dump so restore can pair them.
    # A fatal tar failure marks the cycle failed (like the S3 path below) rather than
    # returning early: retention pruning further down must always run, and the
    # `|| cycle_failed=1` also keeps `set -e` from aborting on the non-zero
    # command substitution. The cycle then exits non-zero and `.last-success`
    # is never touched, so the healthcheck sees the missed staging archive.
    local cycle_failed=0
    local staging_archive=""
    staging_archive="$(backup_staging "$timestamp")" || cycle_failed=1

    # fix(#995): cluster globals (roles, their passwords, and cluster-wide
    # grants) alongside the dump. A database-only pg_dump can never restore
    # them, so without this artifact the fresh-cluster path in RUNBOOK § 2 has
    # no input. Unlike the staging archive there is no partial-success case, so
    # any failure marks the cycle failed the way the S3 path does.
    local globals_dump=""
    globals_dump="$(backup_globals "$timestamp")" || cycle_failed=1

    # S3 upload — record any failure but DON'T return yet. The local dump (and
    # the staging archive, if any) already landed on disk; retention pruning
    # below must still run so a transient S3 outage can't let them accumulate.
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        local upload_failed=0
        upload_to_s3 "$filepath" "daily/${filename}" || upload_failed=1
        if [ -n "$staging_archive" ]; then
            upload_to_s3 "$staging_archive" "daily/$(basename "$staging_archive")" || upload_failed=1
        fi
        # The globals dump goes offsite with the dump it pairs with: an operator
        # rebuilding on a fresh cluster is doing so precisely because the local
        # disk is gone, so a globals artifact that only exists there is no use.
        if [ -n "$globals_dump" ]; then
            upload_to_s3 "$globals_dump" "daily/$(basename "$globals_dump")" || upload_failed=1
        fi
        if [ "$CYCLE_IS_WEEKLY" -eq 1 ]; then
            upload_to_s3 "$filepath" "weekly/${filename}" || upload_failed=1
            if [ -n "$staging_archive" ]; then
                upload_to_s3 "$staging_archive" "weekly/$(basename "$staging_archive")" || upload_failed=1
            fi
            if [ -n "$globals_dump" ]; then
                upload_to_s3 "$globals_dump" "weekly/$(basename "$globals_dump")" || upload_failed=1
            fi
        fi
        if [ "$upload_failed" -eq 1 ]; then
            log "ERROR: backup S3 upload failed — check S3 credentials and endpoint reachability"
            cycle_failed=1
        fi
    fi

    # Retention runs regardless of S3 outcome (dumps set the window; their
    # companions follow) — local backups must be pruned even when the offsite
    # upload failed, or backup_data fills up during an S3 outage.
    prune_old_backups "$DAILY_DIR" "$BACKUP_RETENTION_DAILY"
    prune_old_backups "$WEEKLY_DIR" "$BACKUP_RETENTION_WEEKLY"
    # Must run after prune_old_backups — it prunes by what that just left.
    prune_orphaned_companions "$DAILY_DIR"
    prune_orphaned_companions "$WEEKLY_DIR"

    # fix(#1778): the offsite copies get the same retention as their local
    # counterparts. Runs regardless of this cycle's upload outcome, for the
    # same reason local pruning does — a transient S3 hiccup on THIS cycle's
    # upload must not stop last cycle's objects from being pruned.
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        prune_s3_prefix "daily" "$BACKUP_RETENTION_DAILY" || cycle_failed=1
        prune_s3_prefix "weekly" "$BACKUP_RETENTION_WEEKLY" || cycle_failed=1
    fi

    # Surface the S3 failure now that retention has run, so the cycle is still
    # reported as failed (non-zero) to the cron / sleep-loop caller.
    if [ "$cycle_failed" -eq 1 ]; then
        return 1
    fi

    # fix(#712): freshness marker for the compose healthcheck. Every failure
    # path above returns before this line, so the marker's mtime records the
    # last FULLY successful cycle (dump + verify + S3 when enabled). The
    # healthcheck in docker-compose(.prod).yml goes unhealthy when it is
    # missing or older than BACKUP_MAX_AGE_MINUTES.
    touch "${BACKUP_DIR}/.last-success"

    log "Backup cycle complete"
}

# ---------------------------------------------------------------------------
# BKP-01: object-storage (upload_staging) archive
# ---------------------------------------------------------------------------
# Tars the read-only /staging mount into staging-<timestamp>.tar.gz next to the
# dump. Prints the archive path on stdout (consumed by run_backup); all human
# logging goes to stderr so it never contaminates that path. Skips cleanly when
# the staging mount is absent or empty so a fresh install (no uploads yet) still
# produces a valid DB-only backup cycle.
backup_staging() {
    local timestamp="$1"
    local archive="${DAILY_DIR}/staging-${timestamp}.tar.gz"

    if [ ! -d "$STAGING_DIR" ]; then
        log "Staging dir ${STAGING_DIR} not mounted — skipping object-storage archive" >&2
        return 0
    fi
    if [ -z "$(find "$STAGING_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]; then
        log "Staging dir ${STAGING_DIR} is empty — skipping object-storage archive" >&2
        return 0
    fi

    # tar's own stderr is left attached so its diagnostic (e.g. "file changed
    # as we read it" when api/worker write temp files mid-archive) reaches the
    # container log instead of vanishing.
    log "Archiving object storage: $(basename "$archive")" >&2
    local tar_rc=0
    # fix(#1778): write to .tmp and rename on success, same as the dump — a
    # container killed mid-tar (OOM, `compose stop`, disk full) would
    # otherwise leave a truncated archive under the final name, unverified
    # and indistinguishable from a good one until restore.sh tries to
    # extract it.
    tar czf "${archive}.tmp" -C "$STAGING_DIR" . || tar_rc=$?
    # fix(#843): GNU tar exit 1 means "some files differ" — api/worker wrote
    # to staging mid-archive. The archive IS written and every quiescent file
    # in it is sound; only files caught mid-write are fuzzy and re-archive
    # next cycle. Failing the whole cycle on exit 1 traded a usable DB dump +
    # near-complete staging archive for nothing, and on a busy install the
    # freshness healthcheck sat unhealthy indefinitely. Only exit >= 2
    # (fatal tar error) fails the cycle.
    if [ "$tar_rc" -ge 2 ]; then
        log "ERROR: object-storage archive failed — this cycle will be reported as failed" >&2
        rm -f "${archive}.tmp"
        return 1
    fi
    if [ "$tar_rc" -eq 1 ]; then
        log "WARNING: staging changed during archiving (tar exit 1) — archive kept; changed files re-archive next cycle" >&2
    fi
    # fix(#1778): verify the archive is a well-formed, fully readable tar
    # stream before publishing it under its final name — the tar-side
    # analogue of the dump's `pg_restore -f /dev/null` check. Neither tar exit
    # code above (0 or 1) catches a truncated gzip member from a disk that
    # filled mid-write.
    if ! tar tzf "${archive}.tmp" > /dev/null 2>&1; then
        log "ERROR: ${archive}.tmp failed verification (tar could not read it) — discarding the corrupt archive" >&2
        rm -f "${archive}.tmp"
        return 1
    fi
    if ! mv "${archive}.tmp" "$archive"; then
        log "ERROR: could not publish $(basename "$archive") — is the backup volume writable and not full?" >&2
        rm -f "${archive}.tmp"
        return 1
    fi
    local size
    size="$(du -h "$archive" | cut -f1)"
    log "Object-storage archive complete: $(basename "$archive") (${size})" >&2
    if [ "${CYCLE_IS_WEEKLY:-0}" -eq 1 ]; then
        # Same .tmp-then-rename as the weekly dump/globals copies, and for the
        # same reason: a container killed mid-cp must never leave a truncated
        # file under the final weekly archive name.
        if ! cp "$archive" "${WEEKLY_DIR}/$(basename "$archive").tmp" \
            || ! mv "${WEEKLY_DIR}/$(basename "$archive").tmp" "${WEEKLY_DIR}/$(basename "$archive")"; then
            log "ERROR: could not write the weekly object-storage copy to ${WEEKLY_DIR}" >&2
            rm -f "${WEEKLY_DIR}/$(basename "$archive").tmp"
            return 1
        fi
        log "Weekly object-storage copy saved: $(basename "$archive")" >&2
    fi
    printf '%s\n' "$archive"
}

# ---------------------------------------------------------------------------
# fix(#995): cluster globals (roles + cluster-wide grants)
# ---------------------------------------------------------------------------
# Writes globals-<timestamp>.sql next to the dump, same timestamp so a restore
# can pair them. Prints the path on stdout (consumed by run_backup); all human
# logging goes to stderr so it never contaminates that path.
#
# umask 077 is not optional. `pg_dumpall --globals-only` emits role password
# verifiers; under the default 022 umask the file lands world-readable in the
# backup volume and, with BACKUP_S3_ENABLED=true, in the bucket. The subshell
# scopes the umask to the redirect that creates the file and nothing else —
# this is the form RUNBOOK § "Multi-tenant role reconstruction" documents.
#
# Unlike backup_staging there is no salvageable partial: a truncated globals
# file replays as a partial set of roles, which is worse than none, so any
# non-zero exit discards it and fails the cycle.
backup_globals() {
    local timestamp="$1"
    local globals_file="${DAILY_DIR}/globals-${timestamp}.sql"

    log "Dumping cluster globals: $(basename "$globals_file")" >&2
    # fix(#995): write to .tmp and rename on success, for the same reason the
    # dump does. A container killed mid-write (OOM, `compose stop`) never
    # reaches the cleanup below, so writing straight to the final name would
    # leave a truncated globals file sitting next to a complete dump, looking
    # like the valid paired artifact. The rename makes globals-*.sql appear
    # only atomically; the .tmp is swept at the top of the next cycle.
    local rc=0
    (umask 077; pg_dumpall -h "$POSTGRES_HOST" -U "$POSTGRES_USER" \
        --globals-only > "${globals_file}.tmp") || rc=$?
    if [ "$rc" -ne 0 ]; then
        log "ERROR: pg_dumpall --globals-only failed (exit ${rc}) — roles could not be captured, so this cycle will be reported as failed" >&2
        rm -f "${globals_file}.tmp"
        return 1
    fi
    # Every publish step is checked explicitly. This function always runs inside
    # a `$(...) || cycle_failed=1` command substitution, which suspends `set -e`
    # for its whole body — so an unchecked `mv` or `cp` failing (read-only
    # volume, ENOSPC) would fall through to the final printf, return success,
    # and let the cycle touch .last-success with no globals artifact beside a
    # valid dump.
    if ! mv "${globals_file}.tmp" "$globals_file"; then
        log "ERROR: could not publish $(basename "$globals_file") — is the backup volume writable and not full?" >&2
        rm -f "${globals_file}.tmp"
        return 1
    fi

    local size
    size="$(du -h "$globals_file" | cut -f1)"
    log "Cluster globals complete: $(basename "$globals_file") (${size})" >&2
    if [ "$CYCLE_IS_WEEKLY" -eq 1 ]; then
        # Same .tmp-then-rename as the daily artifact, and for the same reason:
        # a container killed mid-`cp` never reaches the failure branch, so
        # copying straight to the final name would leave a truncated file under
        # the weekly globals filename beside an already-published weekly dump,
        # where a recovery would take it for the valid paired artifact.
        #
        # cp carries the source's 0600 across (measured on both busybox and GNU
        # cp), but the weekly copy is the one an operator reaches for months
        # later, so pin the mode rather than inheriting it, and do it before the
        # rename so the file is never visible under its final name at a wider
        # mode.
        local weekly_copy="${WEEKLY_DIR}/$(basename "$globals_file")"
        if ! cp "$globals_file" "${weekly_copy}.tmp" \
            || ! chmod 600 "${weekly_copy}.tmp" \
            || ! mv "${weekly_copy}.tmp" "$weekly_copy"; then
            log "ERROR: could not write the weekly globals copy to ${WEEKLY_DIR}" >&2
            rm -f "${weekly_copy}.tmp"
            return 1
        fi
        log "Weekly globals copy saved: $(basename "$globals_file")" >&2
    fi
    printf '%s\n' "$globals_file"
}

# ---------------------------------------------------------------------------
# S3 upload via awscli with AWS Signature V4
#
# Uses SigV4 — the only signature version accepted by Cloudflare R2 and
# required by modern AWS S3 (and MinIO). Credentials are passed through the
# environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) — never on argv,
# which would expose secrets in the process list. The endpoint, region, and
# addressing style are read from S3_ENDPOINT, S3_REGION, and
# S3_ADDRESSING_STYLE respectively. A failed upload returns non-zero and logs
# an ERROR so silent offsite backup loss is detectable in container logs.
# ---------------------------------------------------------------------------
upload_to_s3() {
    local filepath="$1"
    local s3_key="$2"

    # BACKUP_S3_ENABLED=true is a promise of an offsite copy; missing bucket
    # or credentials mean that promise cannot be kept, so fail the cycle
    # (keeping .last-success stale and the healthcheck honest) instead of
    # skipping quietly and reporting success.
    if [ -z "${S3_BUCKET:-}" ] || [ -z "${S3_ACCESS_KEY_ID:-}" ] || [ -z "${S3_SECRET_ACCESS_KEY:-}" ]; then
        log "ERROR: BACKUP_S3_ENABLED=true but S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY are not all set — offsite upload impossible"
        return 1
    fi

    # Pass credentials via environment — not on argv (prevents secret leakage
    # in the process list and shell history).
    export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
    export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"
    export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"

    # Force SigV4 and configure addressing style (use 'path' for MinIO/R2 when needed).
    aws configure set default.s3.signature_version s3v4
    aws configure set default.s3.addressing_style "${S3_ADDRESSING_STYLE:-auto}"

    # Build argument list; --endpoint-url is only added when S3_ENDPOINT is set.
    local aws_args=()
    if [ -n "${S3_ENDPOINT:-}" ]; then
        aws_args+=(--endpoint-url "$S3_ENDPOINT")
    fi
    aws_args+=(--region "${S3_REGION:-us-east-1}" --no-progress)

    log "Uploading to S3: ${s3_key}"
    if aws s3 cp "$filepath" "s3://${S3_BUCKET}/backups/${s3_key}" "${aws_args[@]}"; then
        log "S3 upload complete: ${s3_key}"
    else
        log "ERROR: S3 upload failed for ${s3_key}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# fix(#1778): S3 retention pruning
# ---------------------------------------------------------------------------
# upload_to_s3 only ever adds objects under backups/<prefix>/ — nothing ever
# removed one, so with BACKUP_S3_ENABLED=true the offsite copies grow without
# bound while RUNBOOK documents a fixed "N daily / N weekly" retention. This
# mirrors that local policy against the S3 prefix: keep the newest `keep`
# *.dump objects by their embedded timestamp (same sort key dump_listing
# uses), then drop any *.sql/*.tar.gz companion whose paired dump is no
# longer among the kept set (the S3 analogue of prune_orphaned_companions).
#
# No new env var: this is gated by the same BACKUP_S3_ENABLED an operator
# already opted into for the upload itself, and uses the same
# BACKUP_RETENTION_DAILY / BACKUP_RETENTION_WEEKLY counts as the local path.
#
# fix(#1778 review round 2, P1): the S3 analogue of newest_complete_ts()
# below — the timestamp of the newest set that is COMPLETE (a *.dump object
# with the globals-*.sql that pairs with it), read from the SAME `aws s3 ls`
# listing prune_s3_prefix already fetched (no second S3 round trip). Without
# this, a partial upload cycle (the dump uploads, the globals upload fails)
# can destroy the only complete offsite set: the partial cycle's own dump
# still counts toward `keep`, evicts the previous COMPLETE dump under
# BACKUP_RETENTION_DAILY=1, and that complete dump's globals companion is
# pruned right behind it as an orphan in the very same cycle — a
# disaster-recovery restore then has a dump but no globals to rebuild roles
# on a fresh cluster.
s3_newest_complete_ts() {
    local listing="$1"
    local names name ts best=""
    names="$(printf '%s\n' "$listing" | awk '{print $NF}')"
    while IFS= read -r name; do
        if [[ "$name" == globals-*.sql ]]; then
            ts="$(printf '%s' "$name" | sed -nE 's/^globals-([0-9]{8}_[0-9]{6})\.sql$/\1/p')"
            [ -n "$ts" ] || continue
            if printf '%s\n' "$names" | grep -qE "_${ts}\.dump\$"; then
                if [ -z "$best" ] || [ "$ts" \> "$best" ]; then
                    best="$ts"
                fi
            fi
        fi
    done <<< "$names"
    printf '%s' "$best"
}

prune_s3_prefix() {
    local prefix="$1"
    local keep="$2"

    if [ -z "${S3_BUCKET:-}" ] || [ -z "${S3_ACCESS_KEY_ID:-}" ] || [ -z "${S3_SECRET_ACCESS_KEY:-}" ]; then
        log "ERROR: BACKUP_S3_ENABLED=true but S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY are not all set — cannot prune offsite retention"
        return 1
    fi

    export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
    export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"
    export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
    aws configure set default.s3.signature_version s3v4
    aws configure set default.s3.addressing_style "${S3_ADDRESSING_STYLE:-auto}"

    local aws_args=()
    if [ -n "${S3_ENDPOINT:-}" ]; then
        aws_args+=(--endpoint-url "$S3_ENDPOINT")
    fi
    aws_args+=(--region "${S3_REGION:-us-east-1}")

    # A listing failure (bad creds, unreachable endpoint, missing
    # s3:ListBucket) must not be swallowed: unlike a single upload retrying
    # next cycle, a listing that silently returns nothing every cycle would
    # mean retention never runs at all — precisely the bug this fixes.
    local ls_output ls_rc=0
    ls_output="$(aws s3 ls "s3://${S3_BUCKET}/backups/${prefix}/" "${aws_args[@]}" 2>&1)" || ls_rc=$?
    if [ "$ls_rc" -ne 0 ]; then
        log "ERROR: could not list s3://${S3_BUCKET}/backups/${prefix}/ for retention pruning (exit ${ls_rc}) — offsite objects were not pruned this cycle"
        return 1
    fi

    # "<timestamp>\t<name>" for every *.dump object, oldest first. A `[[ ]]`
    # glob test (not `case`, and not `grep`) filters the suffix, and
    # `sed -nE ...p` (not `grep -oE`) extracts the timestamp — two separate
    # bash pitfalls, both real:
    #   - this file runs under `set -euo pipefail`, and a `grep` that matches
    #     nothing exits 1 — on the ordinary "nothing to prune yet" cycle that
    #     would abort the whole backup, not just skip pruning. `[[ ]]` and
    #     `sed -n` both exit 0 regardless of whether anything matched, the
    #     same reason dump_listing() below uses `find` (never errors on zero
    #     matches) and `sed -nE`.
    #   - a `case`/`esac` block that both sits inside a `$( )` command
    #     substitution AND contains its own nested `$( )` confuses bash's
    #     parser (measured on bash 5.2: "syntax error near unexpected token
    #     `newline'") — `[[ ]]` sidesteps it entirely.
    local dumps name ts
    dumps="$(
        printf '%s\n' "$ls_output" | awk '{print $NF}' \
            | while IFS= read -r name; do
                if [[ "$name" == *.dump ]]; then
                    ts="$(printf '%s' "$name" | sed -nE 's/^.*[_-]([0-9]{8}_[0-9]{6})\.dump$/\1/p')"
                    [ -n "$ts" ] || continue
                    printf '%s\t%s\n' "$ts" "$name"
                fi
            done | sort
    )"

    # fix(#1778 review, P2): a `| while` loop runs in a SUBSHELL — a `local`
    # variable set inside it (a failure flag) never reaches this function's
    # own scope. Before this fix, `aws s3 rm` failing just logged an ERROR
    # from *inside* that subshell and the loop (and therefore the pipeline,
    # and therefore this function) still exited 0: `cycle_failed` in
    # run_backup never got set, `.last-success` was touched, and the offsite
    # bucket kept growing with the healthcheck reporting green. Both deletion
    # loops below use `< <(...)` process substitution instead of `| while` —
    # the loop body then runs in THIS shell, so `rm_failed=1` actually
    # persists past the loop.
    local rm_failed=0

    # fix(#1778 review round 2, P1): protect the newest COMPLETE set (a dump
    # with the globals that pairs with it) the same way prune_old_backups
    # does locally — held back IN ADDITION to the retention window, not
    # inside it, so a retention of 1 keeps the complete set and prunes the
    # newest incomplete dump instead of the other way around. See
    # s3_newest_complete_ts's comment above for why this matters more here
    # than it might look: a partial upload cycle can otherwise take out the
    # only restorable-onto-a-fresh-cluster set in a single pass.
    local protect protect_line=""
    protect="$(s3_newest_complete_ts "$ls_output")"
    if [ -n "$protect" ]; then
        protect_line="$(printf '%s\n' "$dumps" | grep "^${protect}	" || true)"
    fi

    local candidates
    if [ -n "$protect" ]; then
        candidates="$(printf '%s\n' "$dumps" | grep -v "^${protect}	" || true)"
    else
        candidates="$dumps"
    fi

    if [ -n "$candidates" ]; then
        local count
        count="$(printf '%s\n' "$candidates" | wc -l | tr -d ' ')"
        if [ "$count" -gt "$keep" ]; then
            local to_remove=$((count - keep))
            log "Pruning ${to_remove} old offsite backup(s) from s3://${S3_BUCKET}/backups/${prefix}/"
            while IFS= read -r name; do
                if ! aws s3 rm "s3://${S3_BUCKET}/backups/${prefix}/${name}" "${aws_args[@]}" > /dev/null; then
                    log "ERROR: could not delete s3://${S3_BUCKET}/backups/${prefix}/${name}"
                    rm_failed=1
                fi
            done < <(printf '%s\n' "$candidates" | head -n "$to_remove" | cut -f2)
            candidates="$(printf '%s\n' "$candidates" | tail -n "+$((to_remove + 1))")"
        fi
    fi

    # Recombine the surviving candidates with the protected entry (if any) —
    # its companion must not be pruned as an orphan below just because the
    # protected dump sat outside the count-based candidate set.
    if [ -n "$protect_line" ]; then
        dumps="$(printf '%s\n%s\n' "$candidates" "$protect_line" | sed '/^$/d' | sort)"
    else
        dumps="$candidates"
    fi
    local kept_ts
    kept_ts="$(printf '%s\n' "$dumps" | cut -f1)"

    while IFS= read -r name; do
        if [[ "$name" == *.sql || "$name" == *.tar.gz ]]; then
            ts="$(printf '%s' "$name" | sed -nE 's/^.*[_-]([0-9]{8}_[0-9]{6})\.(sql|tar\.gz)$/\1/p')"
            [ -n "$ts" ] || continue
            if ! printf '%s\n' "$kept_ts" | grep -qx "$ts"; then
                log "Pruning orphaned s3://${S3_BUCKET}/backups/${prefix}/${name} (its dump aged out)"
                if ! aws s3 rm "s3://${S3_BUCKET}/backups/${prefix}/${name}" "${aws_args[@]}" > /dev/null; then
                    log "ERROR: could not delete s3://${S3_BUCKET}/backups/${prefix}/${name}"
                    rm_failed=1
                fi
            fi
        fi
    done < <(printf '%s\n' "$ls_output" | awk '{print $NF}')

    # fix(#1778 review, P2): surface a partial-prune cycle to the caller so
    # run_backup marks it failed (cycle_failed=1) — the same treatment a
    # listing failure above already gets, and the same reason: retention
    # that "mostly" ran and quietly leaves objects behind is the exact bug
    # this function exists to fix.
    if [ "$rm_failed" -eq 1 ]; then
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Retention pruning
# ---------------------------------------------------------------------------
# Ordered by the timestamp in the filename, not by mtime. Two reasons: the
# embedded timestamp is the cycle's identity, while mtime is whenever the file
# was last written (the weekly copies all carry their `cp` time, so mtime order
# there is the copy order, not the backup order); and `find -printf` is a GNU
# extension, so mtime ordering made this function silently unrunnable outside
# the container — including in scripts/tests/test-backup-restore-roundtrip.sh,
# which is documented as a standalone local tool.
#
# Sorted on the EXTRACTED timestamp, not the whole path: the database name is
# the prefix, so sorting the path puts it ahead of the timestamp, and after a
# POSTGRES_DB rename to a lexically earlier name every fresh dump would sort as
# the oldest and be pruned first. Files whose name carries no timestamp are not
# ours; they are neither counted nor deleted.
#
# Emits "<timestamp>\t<path>" lines, oldest first.
dump_listing() {
    local dir="$1"
    local dump ts
    find "$dir" -maxdepth 1 -name "*.dump" -type f | while IFS= read -r dump; do
        ts="$(printf '%s' "${dump##*/}" | sed -nE 's/^.*_([0-9]{8}_[0-9]{6})\.dump$/\1/p')"
        [ -n "$ts" ] || continue
        printf '%s\t%s\n' "$ts" "$dump"
    done | sort
}

# fix(#995): the timestamp of the newest set that is COMPLETE — a dump with the
# globals dump that pairs with it. prune_old_backups keeps that one out of the
# retention window.
#
# Without the exemption a run of pg_dumpall failures walks every complete set
# out of retention: each failed cycle still produces a valid dump (discarding it
# would make the failure strictly worse — data without roles beats nothing), so
# it counts toward the window and evicts an older complete set, whose globals
# then goes with it as an orphan. After a full window of failures the operator
# has been told loudly every cycle (`.last-success` stale, healthcheck
# unhealthy) and still has dumps, but nothing that restores onto a fresh
# cluster. Holding one complete set back costs at most one extra dump plus a
# few KB of SQL and is the difference between a degraded DR path and none.
newest_complete_ts() {
    local dir="$1"
    local globals ts best=""
    for globals in "$dir"/globals-*.sql; do
        [ -f "$globals" ] || continue
        ts="$(printf '%s' "${globals##*/}" | sed -nE 's/^globals-([0-9]{8}_[0-9]{6})\.sql$/\1/p')"
        [ -n "$ts" ] || continue
        find "$dir" -maxdepth 1 -name "*_${ts}.dump" -type f | grep -q . || continue
        if [ -z "$best" ] || [ "$ts" \> "$best" ]; then
            best="$ts"
        fi
    done
    printf '%s' "$best"
}

prune_old_backups() {
    local dir="$1"
    local keep="$2"

    local listing
    listing="$(dump_listing "$dir")"
    [ -n "$listing" ] || return 0

    # The protected set is held back IN ADDITION to the retention window, not
    # inside it: letting it occupy a slot would mean a retention of 1 keeps the
    # complete set and throws away the newest dump, which is the wrong trade.
    # So a directory holds at most `keep` + 1 dumps.
    local protect
    protect="$(newest_complete_ts "$dir")"

    local candidates
    if [ -n "$protect" ]; then
        candidates="$(printf '%s\n' "$listing" | grep -v "^${protect}	" || true)"
    else
        candidates="$listing"
    fi
    [ -n "$candidates" ] || return 0

    local count
    count="$(printf '%s\n' "$candidates" | wc -l | tr -d ' ')"
    [ "$count" -gt "$keep" ] || return 0

    local to_remove=$((count - keep))
    log "Pruning ${to_remove} old backup(s) from ${dir}"
    printf '%s\n' "$candidates" | head -n "$to_remove" | cut -f2- | \
        while IFS= read -r stale; do
            rm -f "$stale"
        done
}

# BKP-01 / fix(#995): companion artifacts (the object-storage archive and the
# globals dump) are pruned by PAIRING, not by their own count.
#
# Counting them independently looked equivalent and is not, because a companion
# can be absent for a cycle that still produces a dump: backup_staging skips a
# missing or empty staging mount, and a failed pg_dumpall leaves a good dump
# with no globals. Once the counts diverge, `keep the newest N of each` prunes
# a dump whose companion is younger than N and therefore survives — so after
# enough such cycles every complete set is gone while the orphans remain.
#
# The dumps are the primary artifact and prune_old_backups is the authority on
# retention. This runs AFTER it and drops any companion whose dump is no longer
# there, which keeps the invariant that matters for a restore: every companion
# present has the dump it pairs with.
prune_orphaned_companions() {
    local dir="$1"

    local companion base ts
    for companion in "$dir"/staging-*.tar.gz "$dir"/globals-*.sql; do
        # Unmatched globs expand to themselves; -f skips those.
        [ -f "$companion" ] || continue
        base="$(basename "$companion")"
        # Anchored at the end, like restore.sh's parse.
        ts="$(printf '%s' "$base" | sed -nE 's/^.*-([0-9]{8}_[0-9]{6})\..*$/\1/p')"
        # A name we cannot pair is left alone rather than guessed at.
        [ -n "$ts" ] || continue
        if ! find "$dir" -maxdepth 1 -name "*_${ts}.dump" -type f | grep -q .; then
            log "Pruning orphaned ${base} from ${dir} (its dump has aged out)"
            rm -f "$companion"
        fi
    done
}

# ---------------------------------------------------------------------------
# GAP-005 (Phase 1184): BACKUP_SCHEDULE validation
# ---------------------------------------------------------------------------
# The sleep-loop fallback scheduler (used when no cron daemon is available)
# only supports expressions of the form "M H * * *" (a literal minute + hour,
# with all three remaining fields set to *). Any other form silently never
# fires — the comparison `[ "$current_min" = "*/15" ]` never matches.
#
# Validation approach: FAIL FAST at startup if BACKUP_SCHEDULE uses a form the
# simple scheduler cannot honour. If crond/cron is available the expression is
# passed through to the system cron, which handles the full 5-field syntax —
# but we still validate so that a misconfigured schedule surfacing on a crond
# host does not silently break when run on an image without crond.
#
# Supported: M H * * *   where M is 0-59 and H is 0-23 (literal integers)
# Unsupported: */N steps, ranges, lists, or non-* dom/month/dow fields.
validate_cron_expr() {
    local expr="$1"

    # Split into exactly 5 fields
    field_count="$(echo "$expr" | awk '{print NF}')"
    if [ "$field_count" -ne 5 ]; then
        log "ERROR: BACKUP_SCHEDULE must have exactly 5 fields (got ${field_count}): '${expr}'" >&2
        log "Supported format: 'M H * * *'  (e.g. '0 2 * * *' for 02:00 daily)" >&2
        exit 1
    fi

    f_min="$(echo "$expr" | awk '{print $1}')"
    f_hour="$(echo "$expr" | awk '{print $2}')"
    f_dom="$(echo "$expr" | awk '{print $3}')"
    f_month="$(echo "$expr" | awk '{print $4}')"
    f_dow="$(echo "$expr" | awk '{print $5}')"

    # Validate: minute must be a plain integer 0-59
    case "$f_min" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' is not a plain integer." >&2
            log "The built-in sleep-loop scheduler only supports literal 'M H * * *'." >&2
            log "Examples: '0 2 * * *' (02:00), '30 6 * * *' (06:30)" >&2
            log "To use step/range expressions, ensure crond is available in the container." >&2
            exit 1
            ;;
    esac
    if [ "$f_min" -lt 0 ] || [ "$f_min" -gt 59 ]; then
        log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' out of range 0-59." >&2
        exit 1
    fi

    # Validate: hour must be a plain integer 0-23
    case "$f_hour" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' is not a plain integer." >&2
            log "The built-in sleep-loop scheduler only supports literal 'M H * * *'." >&2
            exit 1
            ;;
    esac
    if [ "$f_hour" -lt 0 ] || [ "$f_hour" -gt 23 ]; then
        log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' out of range 0-23." >&2
        exit 1
    fi

    # Validate: dom, month, dow must all be '*'
    if [ "$f_dom" != "*" ] || [ "$f_month" != "*" ] || [ "$f_dow" != "*" ]; then
        log "ERROR: BACKUP_SCHEDULE fields 3-5 must all be '*' for the built-in scheduler." >&2
        log "Got: dom='${f_dom}' month='${f_month}' dow='${f_dow}'" >&2
        log "The sleep-loop scheduler only fires once per day at a fixed hour:minute." >&2
        log "To use day-of-week or monthly schedules, ensure crond is available." >&2
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
CRON_EXPR="${BACKUP_SCHEDULE:-0 2 * * *}"

# Cron re-entry: called with --run-backup by cron job — execute and exit
if [ "${1:-}" = "--run-backup" ]; then
    run_backup
    exit $?
fi

# GAP-005: validate the schedule expression before doing anything else so
# an unsupported expression fails loudly instead of silently never firing.
validate_cron_expr "$CRON_EXPR"

# First-run entry point
log "GeoLens backup service starting"
log "Schedule: ${CRON_EXPR}"
log "Retention: ${BACKUP_RETENTION_DAILY} daily, ${BACKUP_RETENTION_WEEKLY} weekly"
log "S3 upload: ${BACKUP_S3_ENABLED}"

# fix(#798): BACKUP_S3_ENABLED defaults to false, and "S3 upload: false" reads
# as configuration output rather than as the exposure it describes. The
# deployment that most needs the warning is exactly the one that never
# configured anything, so say plainly what the default means.
#
# Startup only, not per cycle: a nightly warning in the logs of a deliberately
# local-only install is noise that trains operators to ignore the log. It costs
# nothing when offsite upload is on, because it does not print then.
if [ "$BACKUP_S3_ENABLED" != "true" ]; then
    log "WARNING: offsite backup upload is DISABLED (BACKUP_S3_ENABLED is not 'true')."
    log "WARNING:   Backups are written to the same host, and usually the same physical"
    log "WARNING:   disk, as the database. Losing that disk loses the data AND every"
    log "WARNING:   backup of it in one event."
    log "WARNING:   Enable the offsite copy (RUNBOOK.md, section 1, \"Offsite (S3) upload\")"
    log "WARNING:   or point the backup volume at different storage before relying on"
    log "WARNING:   this for disaster recovery."
fi

# Run an initial backup on startup
run_backup || log "ERROR: Initial backup failed"

# Try cron daemon first, fall back to sleep loop
if command -v crontab >/dev/null 2>&1; then
    CRON_LINE="${CRON_EXPR} /scripts/backup-entrypoint.sh --run-backup >> /var/log/backup.log 2>&1"
    echo "$CRON_LINE" | crontab -
    log "Cron installed, entering foreground"
    exec crond -f -l 2 2>/dev/null || exec cron -f
fi

# Fallback: sleep loop with schedule check (no cron available)
log "No cron daemon — using sleep-loop scheduler"
sched_min="$(echo "$CRON_EXPR" | awk '{print $1}')"
sched_hour="$(echo "$CRON_EXPR" | awk '{print $2}')"

while true; do
    # Sleep to just past the next minute boundary rather than a fixed 60s: a
    # fixed sleep drifts by the loop's own per-iteration cost and can
    # eventually skip the scheduled minute entirely.
    sleep $((61 - 10#$(date '+%S')))
    current_hour="$(date '+%-H')"
    current_min="$(date '+%-M')"
    # Compare numerically in base 10 on both sides: a schedule written with a
    # zero-padded minute (e.g. "05 2 * * *") passes validation but would never
    # string-match date's unpadded "5".
    if [ "$((10#$current_hour))" -eq "$((10#$sched_hour))" ] && [ "$((10#$current_min))" -eq "$((10#$sched_min))" ]; then
        run_backup || log "ERROR: Scheduled backup failed"
        sleep 60  # Avoid double-trigger within the same minute
    fi
done
