#!/usr/bin/env bash
set -euo pipefail

# GeoLens automated backup entrypoint.
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
#   BACKUP_RETENTION_DAILY Days of daily backups to keep, one per day (default: 7)
#   BACKUP_RETENTION_WEEKLY Weeks of weekly backups to keep, one per ISO week (default: 4)
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

# Overridable only so scripts/tests/test-backup-restore-roundtrip.sh can drive a
# real cycle into a temp directory instead of re-implementing one. Nothing in
# either compose file sets it, so every deployment gets /backups. Same shape as
# STAGING_DIR below.
BACKUP_DIR="${BACKUP_DIR:-/backups}"
DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

# The upload_staging volume is mounted read-only at /staging. Each backup
# cycle tars it alongside the pg_dump so a restore reproduces a working
# instance (DB rows plus the staged source objects). Override the mount point
# if the compose file changes it.
STAGING_DIR="${STAGING_DIR:-/staging}"

# "<timestamp> <record id>..." for the dump retention always keeps, with a
# sample of its catalog record ids, so cycles over a database restarted on an
# empty volume cannot rotate it out.
LAST_GOOD_FILE="${BACKUP_DIR}/.last-good-dump"

POSTGRES_DB="${POSTGRES_DB:-geolens}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
BACKUP_RETENTION_DAILY="${BACKUP_RETENTION_DAILY:-7}"
BACKUP_RETENTION_WEEKLY="${BACKUP_RETENTION_WEEKLY:-4}"
BACKUP_S3_ENABLED="${BACKUP_S3_ENABLED:-false}"
S3_REGION="${S3_REGION:-us-east-1}"

# Dumps carry every row and the globals carry role password verifiers, so
# nothing this script writes is readable by other users.
umask 077

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Retention must be a positive integer: prune keeps only the newest N days or
# weeks, so a retention of 0 would delete the dump this very cycle just produced and
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

run_backup() {
    local timestamp
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    # Decide "is this a weekly cycle?" once, with the timestamp that names
    # the cycle, and reuse it for every artifact. Asking the weekday again
    # as each one is written would let a Sunday cycle that crosses
    # midnight (a 23:59 schedule, or a large staging archive) copy the
    # dump into weekly/ and then answer Monday for its companions, leaving
    # a weekly dump with no paired globals.
    CYCLE_IS_WEEKLY=0
    [ "$(date '+%u')" = "7" ] && CYCLE_IS_WEEKLY=1
    local filename="${POSTGRES_DB}_${timestamp}.dump"
    local filepath="${DAILY_DIR}/${filename}"
    # Declared before the first early-exit candidate after the dump is
    # published (the pg_restore verification below), so every failure
    # between "dump published" and "retention" records itself and falls
    # through to retention. A `return` there would skip
    # prune_old_backups/prune_s3_prefix: for a Sunday cycle whose weekly
    # copy failed (typically a nearly full volume), neither daily nor
    # weekly would ever expire, and the next cycle would run out of space
    # before it could prune. dump_ok tracks whether $filepath is still
    # there to copy or upload after a verification failure removes it.
    local cycle_failed=0
    local dump_ok=1
    local good_ts="" good_ids="" good_sample=""
    read -r good_ts good_ids 2>/dev/null < "$LAST_GOOD_FILE" || true
    [[ "$good_ts" =~ ^[0-9]{8}_[0-9]{6}$ ]] || good_ts=""
    [[ -n "$good_ts" && "$good_ids" =~ ^[0-9A-Za-z-]+(\ [0-9A-Za-z-]+)*$ ]] || good_ids=""

    # Orphaned .tmp dumps (pg_dump killed mid-write) match no prune glob and
    # would accumulate forever; a new cycle starting means no dump is in
    # flight, so any leftover .tmp is garbage. The globals dump writes through
    # the same .tmp-then-rename path, in both directories, and needs the same
    # sweep, as do the weekly dump copy and both staging archive locations.
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

    # Verify the dump now, while the previous cycle's good copy is still
    # inside retention: a corrupt dump is indistinguishable from a good
    # one until something parses it, and finding out during a restore is
    # too late.
    #
    # Use `-f /dev/null`, not `--list`. In a -Fc archive the table of
    # contents sits at the front, so `--list` succeeds on a dump truncated
    # anywhere after it (a 60%-truncated dump passes `--list` and fails
    # `-f /dev/null`). Truncation from a full disk is the corruption this
    # must catch. `-f /dev/null` decompresses every data block and writes
    # the SQL nowhere; it costs ~0.1s per 20 MB and touches no database.
    if ! pg_restore -f /dev/null < "$filepath" > /dev/null 2>&1; then
        log "ERROR: ${filename} failed verification (pg_restore could not read it) — discarding the corrupt dump"
        rm -f "$filepath"
        # Mark failed and fall through to retention rather than
        # returning: this dump is gone, but old dumps (local and
        # offsite) still need pruning, and staging/globals for this
        # cycle are independent of $filepath.
        cycle_failed=1
        dump_ok=0
    else
        log "Backup verified: ${filename} fully readable"
        # A check that can't run fails the cycle: the healthcheck must show
        # that this dump may not be protected.
        good_sample="$(good_dump_sample "$good_ts" "$good_ids")" || cycle_failed=1
    fi

    # Weekly copy on Sundays. Skipped when verification above already
    # discarded the dump (dump_ok=0) — there is nothing left to copy.
    if [ "$dump_ok" -eq 1 ] && [ "$CYCLE_IS_WEEKLY" -eq 1 ]; then
        if ! publish_weekly_copy "$filepath"; then
            log "ERROR: could not write the weekly dump copy to ${WEEKLY_DIR}"
            # Mark failed and fall through: a nearly full volume
            # is the typical cause, and the fix is retention
            # pruning, which a `return` would skip for both daily
            # and weekly.
            cycle_failed=1
        else
            log "Weekly copy saved: ${filename}"
        fi
    fi

    # Archive the object-storage staging volume alongside the dump, named
    # with the same timestamp so restore can pair them.
    #
    # A fatal tar failure marks the cycle failed (like the S3 path below)
    # rather than returning early: retention pruning below must always
    # run, and `|| cycle_failed=1` keeps `set -e` from aborting on the
    # non-zero command substitution. The cycle then exits non-zero and
    # `.last-success` is never touched, so the healthcheck sees the missed
    # staging archive. cycle_failed is declared near the top of this
    # function and must not be re-declared `local` here, which would reset
    # any failure the verification or weekly-copy steps already recorded.
    local staging_archive=""
    staging_archive="$(backup_staging "$timestamp")" || cycle_failed=1

    # Cluster globals (roles, their passwords, cluster-wide grants)
    # alongside the dump. A database-only pg_dump cannot restore them, so
    # without this artifact the fresh-cluster path in RUNBOOK § 2 has no
    # input. Unlike the staging archive there is no partial-success case,
    # so any failure marks the cycle failed the way the S3 path does.
    local globals_dump=""
    globals_dump="$(backup_globals "$timestamp")" || cycle_failed=1

    # S3 upload: record any failure but do not return yet. The local dump
    # (and the staging archive, if any) already landed on disk; retention
    # pruning below must still run so a transient S3 outage cannot let
    # them accumulate.
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        local upload_failed=0
        # $filepath no longer exists when verification discarded it
        # above (dump_ok=0); there is nothing to upload, and that is
        # not a new failure (already counted via cycle_failed).
        if [ "$dump_ok" -eq 1 ]; then
            upload_to_s3 "$filepath" "daily/${filename}" || upload_failed=1
        fi
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
            if [ "$dump_ok" -eq 1 ]; then
                upload_to_s3 "$filepath" "weekly/${filename}" || upload_failed=1
            fi
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

    # Only a cycle whose artifacts all landed may take over: retention would
    # otherwise keep a set with a missing companion and prune a complete one.
    if [ -n "$good_sample" ] && [ "$cycle_failed" -eq 1 ]; then
        log "WARNING: this cycle failed, so retention keeps ${good_ts:-no older dump} rather than ${filename}"
    elif [ -n "$good_sample" ]; then
        # Through a .tmp name: a torn marker would read back as no marker.
        if printf '%s %s\n' "$timestamp" "$good_sample" > "${LAST_GOOD_FILE}.tmp" \
            && mv "${LAST_GOOD_FILE}.tmp" "$LAST_GOOD_FILE"; then
            good_ts="$timestamp"
        else
            rm -f "${LAST_GOOD_FILE}.tmp"
            log "ERROR: could not record ${filename} as the dump retention keeps — this cycle will be reported as failed"
            cycle_failed=1
        fi
    fi

    # Retention runs regardless of S3 outcome (dumps set the window; their
    # companions follow) — local backups must be pruned even when the offsite
    # upload failed, or backup_data fills up during an S3 outage.
    prune_old_backups "$DAILY_DIR" "$BACKUP_RETENTION_DAILY" day "$good_ts"
    prune_old_backups "$WEEKLY_DIR" "$BACKUP_RETENTION_WEEKLY" week "$good_ts"
    # Must run after prune_old_backups — it prunes by what that just left.
    prune_orphaned_companions "$DAILY_DIR"
    prune_orphaned_companions "$WEEKLY_DIR"

    # The offsite copies get the same retention as their local
    # counterparts. Runs regardless of this cycle's upload outcome, for the
    # same reason local pruning does — a transient S3 hiccup on THIS cycle's
    # upload must not stop last cycle's objects from being pruned.
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        prune_s3_prefix "daily" "$BACKUP_RETENTION_DAILY" day "$good_ts" || cycle_failed=1
        prune_s3_prefix "weekly" "$BACKUP_RETENTION_WEEKLY" week "$good_ts" || cycle_failed=1
    fi

    # Surface the S3 failure now that retention has run, so the cycle is still
    # reported as failed (non-zero) to the cron / sleep-loop caller.
    if [ "$cycle_failed" -eq 1 ]; then
        return 1
    fi

    # Freshness marker for the compose healthcheck. Every failure
    # path above returns before this line, so the marker's mtime records the
    # last FULLY successful cycle (dump + verify + S3 when enabled). The
    # healthcheck in docker-compose(.prod).yml goes unhealthy when it is
    # missing or older than BACKUP_MAX_AGE_MINUTES.
    touch "${BACKUP_DIR}/.last-success"
    # Stays on the volume when offsite upload is later switched off, so the
    # healthcheck can tell a dropped offsite copy from one never configured.
    if [ "$BACKUP_S3_ENABLED" = "true" ]; then
        touch "${BACKUP_DIR}/.last-offsite-success"
    fi

    log "Backup cycle complete"
}

# Prints a fresh sample of catalog record ids when this cycle's dump may take
# over from the kept one: the database has records and at least half of the ids
# sampled from the kept dump (any records, for a marker without ids). Prints
# nothing otherwise, and fails when the check itself can't run. Ids rather than counts, so a re-created database's first
# upload can't take over even when the lost catalog held a single record. The
# check runs after pg_dump, outside its snapshot; a database restored in that
# window could mark a dump that lacks the restored rows, too narrow to engineer
# for. Stdout carries the result, so logs go to stderr.
good_dump_sample() {
    local good_ts="$1" good_ids="$2" row count present sample
    local -a marked=()
    read -r -a marked <<< "$good_ids"
    row="$(psql -X -At -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" -v ids="{$(IFS=,; printf '%s' "${marked[*]:-}")}" <<'SQL'
SELECT to_regclass('catalog.records') IS NOT NULL AS has_records_table \gset
\if :has_records_table
SELECT count(*), count(*) FILTER (WHERE id::text = ANY (:'ids'::text[])),
    (SELECT string_agg(id::text, ' ')
     FROM (SELECT id FROM catalog.records ORDER BY random() LIMIT 100) sampled)
FROM catalog.records;
\else
SELECT 0, 0, '';
\endif
SQL
    )" || row=""
    IFS='|' read -r count present sample <<< "$row"
    if ! [[ "$count" =~ ^[0-9]+$ && "$present" =~ ^[0-9]+$ ]]; then
        log "ERROR: could not check catalog records in ${POSTGRES_DB}${good_ts:+; retention keeps ${good_ts}} — this cycle will be reported as failed" >&2
        return 1
    elif [ "$count" -eq 0 ] || [ $((present * 2)) -lt "${#marked[@]}" ]; then
        if [ -n "$good_ts" ]; then
            log "WARNING: ${POSTGRES_DB} has ${count} catalog records, ${present} of the ${#marked[@]} sampled from ${good_ts}; retention keeps ${good_ts}. If the records were deleted on purpose, delete ${LAST_GOOD_FILE} to release that dump." >&2
        fi
    else
        printf '%s' "$sample"
    fi
}

# Weekly entries are hard links to the daily files: a weekly set costs no extra
# space and appears under its final name only once complete. A filesystem that
# refuses links gets a full copy through a .tmp name instead.
publish_weekly_copy() {
    local src="$1"
    local dst
    dst="${WEEKLY_DIR}/$(basename "$src")"
    if ln "$src" "$dst" 2>/dev/null; then
        return 0
    fi
    log "WARNING: could not hard-link $(basename "$src") into ${WEEKLY_DIR}; writing a full copy instead" >&2
    if cp "$src" "${dst}.tmp" && mv "${dst}.tmp" "$dst"; then
        return 0
    fi
    rm -f "${dst}.tmp"
    return 1
}

# Object-storage (upload_staging) archive: tars the read-only /staging mount
# into staging-<timestamp>.tar.gz next to the dump. Prints the archive path on
# stdout (consumed by run_backup); all human logging goes to stderr so it
# never contaminates that path. Skips cleanly when the staging mount is absent
# or empty so a fresh install (no uploads yet) still produces a valid DB-only
# backup cycle.
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
    # Write to .tmp and rename on success, same as the dump — a
    # container killed mid-tar (OOM, `compose stop`, disk full) would
    # otherwise leave a truncated archive under the final name, unverified
    # and indistinguishable from a good one until restore.sh tries to
    # extract it.
    tar czf "${archive}.tmp" -C "$STAGING_DIR" . || tar_rc=$?
    # GNU tar exit 1 means "some files differ": api/worker wrote to
    # staging mid-archive. The archive is written and every quiescent file
    # in it is sound; files caught mid-write are re-archived next cycle.
    # Failing the cycle on exit 1 would leave the freshness healthcheck
    # unhealthy indefinitely on a busy install, so only exit >= 2 (fatal
    # tar error) fails it.
    if [ "$tar_rc" -ge 2 ]; then
        log "ERROR: object-storage archive failed — this cycle will be reported as failed" >&2
        rm -f "${archive}.tmp"
        return 1
    fi
    if [ "$tar_rc" -eq 1 ]; then
        log "WARNING: staging changed during archiving (tar exit 1) — archive kept; changed files re-archive next cycle" >&2
    fi
    # Verify the archive is a well-formed, fully readable tar stream
    # before publishing it under its final name, the tar-side analogue of
    # the dump's `pg_restore -f /dev/null` check. Neither tar exit code
    # above (0 or 1) catches a truncated gzip member from a disk that
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
    # A weekly-copy failure must not `return` before the final printf:
    # $archive is already published under DAILY_DIR, and run_backup's
    # caller does `staging_archive="$(backup_staging "$timestamp")" ||
    # cycle_failed=1`. Returning early would leave $staging_archive empty,
    # so the valid daily artifact would never reach upload_to_s3, and a
    # nearly full WEEKLY_DIR volume would orphan it from the offsite copy.
    # weekly_failed keeps the cycle marked failed (as with run_backup's
    # own weekly dump-copy failure) while still printing the path.
    local weekly_failed=0
    if [ "${CYCLE_IS_WEEKLY:-0}" -eq 1 ]; then
        if ! publish_weekly_copy "$archive"; then
            log "ERROR: could not write the weekly object-storage copy to ${WEEKLY_DIR}" >&2
            weekly_failed=1
        else
            log "Weekly object-storage copy saved: $(basename "$archive")" >&2
        fi
    fi
    printf '%s\n' "$archive"
    if [ "$weekly_failed" -eq 1 ]; then
        return 1
    fi
}

# Cluster globals (roles + cluster-wide grants). Writes
# globals-<timestamp>.sql next to the dump, with the same timestamp so a
# restore can pair them. Prints the path on stdout (consumed by run_backup);
# all human logging goes to stderr so it never contaminates that path.
#
# umask 077 is required: `pg_dumpall --globals-only` emits role password
# verifiers, and under the default 022 umask the file lands world-readable in
# the backup volume and, with BACKUP_S3_ENABLED=true, in the bucket. The
# subshell scopes the umask to the redirect that creates the file; RUNBOOK §
# "Role reconstruction after a fresh-cluster restore" documents this form.
#
# Unlike backup_staging there is no salvageable partial: a truncated globals
# file replays as a partial set of roles, which is worse than none, so any
# non-zero exit discards it and fails the cycle.
backup_globals() {
    local timestamp="$1"
    local globals_file="${DAILY_DIR}/globals-${timestamp}.sql"
    local weekly_failed=0

    log "Dumping cluster globals: $(basename "$globals_file")" >&2
    # Write to .tmp and rename on success, as the dump does. A container
    # killed mid-write (OOM, `compose stop`) never reaches the cleanup
    # below, so writing to the final name would leave a truncated globals
    # file beside a complete dump, looking like the valid pair. The .tmp
    # is swept at the top of the next cycle.
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
        # A weekly-copy failure must not `return` before the final printf:
        # $globals_file is already published under DAILY_DIR, and the caller
        # needs its path to upload it offsite.
        if ! publish_weekly_copy "$globals_file"; then
            log "ERROR: could not write the weekly globals copy to ${WEEKLY_DIR}" >&2
            weekly_failed=1
        else
            log "Weekly globals copy saved: $(basename "$globals_file")" >&2
        fi
    fi
    printf '%s\n' "$globals_file"
    if [ "$weekly_failed" -eq 1 ]; then
        return 1
    fi
}

# S3 upload via awscli with AWS Signature V4, the only signature version
# accepted by Cloudflare R2 and required by modern AWS S3 (and MinIO).
# Credentials go through the environment (AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY), never argv, which would expose them in the process
# list. Endpoint, region and addressing style come from S3_ENDPOINT, S3_REGION
# and S3_ADDRESSING_STYLE. A failed upload returns non-zero and logs an ERROR
# so silent offsite backup loss is detectable in container logs.
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

# Shared S3 prefix listing.
#
# `aws s3 ls s3://bucket/prefix/` on a prefix with no objects exits 1 with
# empty stdout and stderr (documented AWS CLI behavior). That is the ordinary
# case for backups/weekly/ before the first Sunday cycle, so exit != 0 cannot
# be unconditionally fatal. A real failure (bad creds, unreachable endpoint,
# missing s3:ListBucket) writes to stderr or exits with something other than 0
# or 1 and still propagates, since a listing that silently returns nothing
# every cycle would mean retention never runs. Both prune_s3_prefix calls
# (daily, weekly) and its orphaned-companion pass share this listing.
#
# The listing uses `aws s3api list-objects-v2 --output json`, not the
# whitespace-column `aws s3 ls` text: a key containing whitespace cannot be
# recovered reliably from that format (`awk '{print $NF}'` truncates a key
# with a space, and `read` strips leading whitespace from the last field).
#
# Keys are written as NUL-terminated records, not newline-terminated lines.
# common.sh decodes Compose's `\n`/`\r`/`\t` escapes in a double-quoted .env
# value, so POSTGRES_DB (and every dump/companion filename built from it) can
# contain an embedded newline. A newline-terminated listing would turn one
# such key into what looks like two keys to every downstream `while read`
# loop, which would then `aws s3 rm` a key that was never in the bucket,
# leaving the real dump in place and the cycle unhealthy forever. NUL is the
# one byte an S3 key cannot contain, so it is the only safe delimiter.
# `sys.stdout.buffer.write(...)` (not `print`) writes the raw bytes with an
# explicit trailing `\0`, matching `while IFS= read -r -d '' rec`.
#
# Bash strings cannot hold a NUL byte, so the function writes the listing to
# the file path passed as $2 instead of returning it on stdout. Callers read
# that file with `read -r -d ''` into a bash array (see prune_s3_prefix), and
# array elements are never re-split, so a key keeps every embedded newline,
# tab and space all the way to the `aws s3 rm` argv.
#
# This file is bash-only ([[ ]], arrays, `read -d ''`): the shebang is bash
# and the compose files and Dockerfile invoke it directly, never via sh. The
# selection and deletion decision stays in bash rather than moving to python
# with an `xargs -0` delete list, which would lose the per-key error handling
# (a failed `aws s3 rm` must not drop its dump from the kept set).
#
# Prints one object key per NUL-terminated record to the file at $2 on success
# (an empty prefix leaves it empty) and returns 0; returns 1 only for a
# genuine failure, with the reason logged.
s3_list_prefix() {
    local prefix="$1"
    local out_file="$2"
    shift 2

    local out err rc=0
    out="$(mktemp)" || return 1
    err="$(mktemp)" || { rm -f "$out"; return 1; }
    aws s3api list-objects-v2 --bucket "$S3_BUCKET" \
        --prefix "backups/${prefix}/" --output json "$@" \
        > "$out" 2> "$err" || rc=$?

    # The empty-prefix carve-out matches `aws s3 ls` (exit 1, both streams
    # empty). `list-objects-v2` returns an ordinary 200 with no `Contents`
    # key for an empty prefix, but the exit-1-with-no-output shape is kept
    # as a defensive carve-out across awscli versions. Any other non-zero
    # exit, or any output, is a failure.
    if [ "$rc" -eq 0 ] || { [ "$rc" -eq 1 ] && [ ! -s "$out" ] && [ ! -s "$err" ]; }; then
        # The image has no jq, but the `awscli` apt package pulls in
        # python3 (`aws` is itself a python3 script). Write each
        # `.Contents[].Key`, with the "backups/<prefix>/" portion
        # stripped to the bare filename callers expect and every other
        # byte untouched, NUL-terminated to $out_file. An empty or
        # Contents-less response writes nothing.
        if python3 -c '
import json, sys

raw = sys.stdin.read()
data = json.loads(raw) if raw.strip() else {}
strip = "backups/" + sys.argv[1] + "/"
out = sys.stdout.buffer
for obj in data.get("Contents", []):
    key = obj["Key"]
    if key.startswith(strip):
        key = key[len(strip):]
    out.write(key.encode("utf-8", "surrogateescape"))
    out.write(b"\0")
' "$prefix" < "$out" > "$out_file"; then
            rm -f "$out" "$err"
            return 0
        fi
        log "ERROR: could not parse the S3 listing for s3://${S3_BUCKET}/backups/${prefix}/ (aws exited ${rc}, python3 JSON parse failed) — offsite objects were not pruned this cycle" >&2
        rm -f "$out" "$err"
        return 1
    fi

    # log() is a plain echo, so this error goes to stderr to reach the
    # container log. Functions whose stdout the caller consumes
    # (backup_staging, backup_globals) keep log output off stdout for the
    # same reason.
    log "ERROR: could not list s3://${S3_BUCKET}/backups/${prefix}/ for retention pruning (exit ${rc}): $(cat "$err" 2>/dev/null) — offsite objects were not pruned this cycle" >&2
    rm -f "$out" "$err"
    return 1
}

# S3 retention pruning. Applies the local retention to backups/<prefix>/: keep
# the newest *.dump object of each of the `keep` most recent days or weeks, by
# the embedded timestamp (mark_retained, as prune_old_backups does), then drop
# any *.sql/*.tar.gz companion whose paired dump is no longer kept (the S3
# analogue of prune_orphaned_companions). It runs only with
# BACKUP_S3_ENABLED=true and reads the same BACKUP_RETENTION_* values.
#
# s3_newest_complete_ts is the S3 analogue of newest_complete_ts: the
# timestamp of the newest set that is complete (a *.dump object with the
# globals-*.sql that pairs with it), read from the listing prune_s3_prefix
# already fetched. Without it, a partial upload cycle (the dump uploads, the
# globals upload fails) can destroy the only complete offsite set: the partial
# dump counts toward `keep`, evicts the previous complete dump under
# BACKUP_RETENTION_DAILY=1, and that dump's globals is pruned as an orphan in
# the same cycle, leaving a dump with no globals to rebuild roles on a fresh
# cluster.
#
# The listing arrives as positional parameters ("$@"), one key per parameter,
# because the caller expands a bash array and array elements are never
# re-split: a key containing a newline or tab stays one parameter. The
# `_${ts}.dump` membership check is a plain `[[ glob ]]` test per parameter,
# which cannot match across a parameter boundary.
#
# Timestamps are extracted with bash `=~` against the whole name, never a
# value piped into sed/grep/awk. A key built from POSTGRES_DB can carry an
# embedded newline, which a line-oriented tool reads as multiple records,
# turning one capture into a multi-line $ts that never equals a genuine
# timestamp. `[[ str =~ regex ]]` matches the entire string, so an embedded
# newline can only make the anchored ^...$ pattern fail, never produce a
# second match.
s3_newest_complete_ts() {
    local name ts best="" n2 matched
    for name in "${@:-}"; do
        [ -n "$name" ] || continue
        if [[ "$name" == globals-*.sql ]]; then
            if [[ "$name" =~ ^globals-([0-9]{8}_[0-9]{6})\.sql$ ]]; then
                ts="${BASH_REMATCH[1]}"
            else
                continue
            fi
            matched=0
            for n2 in "${@:-}"; do
                if [[ "$n2" == *"_${ts}.dump" ]]; then
                    matched=1
                    break
                fi
            done
            if [ "$matched" -eq 1 ] && { [ -z "$best" ] || [ "$ts" \> "$best" ]; }; then
                best="$ts"
            fi
        fi
    done
    printf '%s' "$best"
}

prune_s3_prefix() {
    local prefix="$1"
    local keep="$2"
    local period="$3"
    local good="${4:-}"

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

    # A genuine listing failure (bad creds, unreachable endpoint, missing
    # s3:ListBucket) must not be swallowed: a listing that silently
    # returns nothing every cycle would mean retention never runs. An
    # empty prefix (e.g. weekly/ before the first Sunday cycle) is not a
    # failure; s3_list_prefix distinguishes the two.
    #
    # The listing is a NUL-terminated file read once into a bash array.
    # Every pass below (protection, retention counting, orphan detection)
    # iterates or expands that array, never a newline-joined string, so an
    # embedded newline or tab in a key cannot be mistaken for a record or
    # field boundary.
    local listing_file
    listing_file="$(mktemp)" || return 1
    if ! s3_list_prefix "$prefix" "$listing_file" "${aws_args[@]:-}"; then
        rm -f "$listing_file"
        return 1
    fi

    local -a all_names=()
    local name
    while IFS= read -r -d '' name; do
        all_names+=("$name")
    done < "$listing_file"
    rm -f "$listing_file"

    # A `| while` loop runs in a subshell, so a failure flag set inside it
    # never reaches this function's scope: a failing `aws s3 rm` would log
    # an ERROR yet the function would exit 0, `cycle_failed` in run_backup
    # would stay unset, `.last-success` would be touched, and the bucket
    # would keep growing with the healthcheck green. Neither deletion loop
    # below uses `| while` (both are plain `for` over bash arrays), so
    # `rm_failed=1` persists.
    local rm_failed=0

    # Protect the newest complete set (a dump with the globals that pairs
    # with it) as prune_old_backups does locally. It is held back in
    # addition to the retention window, not inside it, so a retention of 1
    # keeps the complete set and prunes the newest incomplete dump
    # instead. See s3_newest_complete_ts: a partial upload cycle can
    # otherwise remove the only set restorable onto a fresh cluster.
    local protect=""
    if [ "${#all_names[@]}" -gt 0 ]; then
        protect="$(s3_newest_complete_ts "${all_names[@]:-}")"
    fi

    # Dump timestamp and name are two parallel arrays indexed together,
    # not a "ts\tname" string. A tab-joined record is safe against a tab
    # inside one record but is still a newline-delimited blob under
    # `sort`, `grep`, `cut`, `head` and `tail`, unsafe against a newline
    # splitting one record into two. Separate arrays leave no text-joining
    # step for a key's own bytes to collide with.
    local -a dump_ts=() dump_name=()
    local -a protect_ts=() protect_name=()
    local ts
    for name in "${all_names[@]:-}"; do
        [ -n "$name" ] || continue
        if [[ "$name" == *.dump ]]; then
            # Extract with a bash match, not `printf '%s' "$name"
            # | sed -nE '...p'`. `name` is a bucket key derived
            # from POSTGRES_DB (backup_globals writes
            # `${POSTGRES_DB}_${timestamp}.dump`), so an embedded
            # newline in POSTGRES_DB puts one inside `name`. sed
            # would read one key as two lines, both matching, and
            # print both, so `ts` would become a two-line string
            # that never equals `$protect`. The protected dump
            # would then fall into the ordinary count-based
            # `dump_ts`/`dump_name` bucket instead of
            # `protect_ts`/`protect_name`: at
            # BACKUP_RETENTION_DAILY=1 a newer partial-upload
            # cycle could evict it, and the orphan pass would
            # delete its globals file.
            #
            # `[[ str =~ regex ]]` matches the whole $name in one
            # shot, so an embedded newline can only make the
            # anchored pattern fail (name skipped, like any
            # malformed key), never yield a second match. The
            # `else continue` arm exits 0 on no match, never a
            # hard error on an empty-listing cycle.
            if [[ "$name" =~ ^.*[_-]([0-9]{8}_[0-9]{6})\.dump$ ]]; then
                ts="${BASH_REMATCH[1]}"
            else
                continue
            fi
            if [ -n "$protect" ] && [ "$ts" = "$protect" ]; then
                protect_ts+=("$ts")
                protect_name+=("$name")
            else
                dump_ts+=("$ts")
                dump_name+=("$name")
            fi
        fi
    done

    # Sort dump_ts/dump_name together, oldest first, via a NUL-safe index
    # permutation: `sort` runs over "<timestamp> <index>" lines (both
    # plain whitespace-free ASCII), never over a dump name, so a name's
    # newlines or tabs never reach a text tool that would treat them as
    # separators. The sorted index order then permutes the (ts, name)
    # arrays.
    if [ "${#dump_ts[@]}" -gt 0 ]; then
        local _i sort_input=""
        for ((_i = 0; _i < ${#dump_ts[@]}; _i++)); do
            sort_input="${sort_input}${dump_ts[$_i]} ${_i}"$'\n'
        done
        local -a order=()
        local _sts _sidx
        while IFS=' ' read -r _sts _sidx; do
            [ -n "$_sidx" ] || continue
            order+=("$_sidx")
        done < <(printf '%s' "$sort_input" | sort)
        local -a sorted_ts=() sorted_name=()
        for _i in "${order[@]:-}"; do
            [ -n "$_i" ] || continue
            sorted_ts+=("${dump_ts[$_i]}")
            sorted_name+=("${dump_name[$_i]}")
        done
        dump_ts=("${sorted_ts[@]:-}")
        dump_name=("${sorted_name[@]:-}")
    fi

    local count="${#dump_ts[@]}"
    local to_remove=0
    if [ "$count" -gt 0 ]; then
        RK_TS=("${dump_ts[@]}")
        mark_retained "$period" "$keep" "$protect" "$good"
        local _i
        for ((_i = 0; _i < count; _i++)); do
            if [ "${RK_KEEP[$_i]}" -eq 0 ]; then
                to_remove=$((to_remove + 1))
            fi
        done
    fi
    if [ "$to_remove" -gt 0 ]; then
        log "Pruning ${to_remove} old offsite backup(s) from s3://${S3_BUCKET}/backups/${prefix}/"
        # A dump whose `aws s3 rm` failed is still in the bucket, so it stays
        # in the kept set and the orphan pass below leaves its companions.
        local -a surviving_ts=() surviving_name=()
        for ((_i = 0; _i < count; _i++)); do
            if [ "${RK_KEEP[$_i]}" -eq 0 ]; then
                if aws s3 rm "s3://${S3_BUCKET}/backups/${prefix}/${dump_name[$_i]}" "${aws_args[@]:-}" > /dev/null; then
                    continue
                fi
                log "ERROR: could not delete s3://${S3_BUCKET}/backups/${prefix}/${dump_name[$_i]}"
                rm_failed=1
            fi
            surviving_ts+=("${dump_ts[$_i]}")
            surviving_name+=("${dump_name[$_i]}")
        done
        dump_ts=("${surviving_ts[@]:-}")
        dump_name=("${surviving_name[@]:-}")
    fi

    # Recombine the surviving candidates with the protected entry (if any) —
    # its companion must not be pruned as an orphan below just because the
    # protected dump sat outside the count-based candidate set.
    if [ "${#protect_ts[@]}" -gt 0 ]; then
        dump_ts+=("${protect_ts[@]}")
        dump_name+=("${protect_name[@]}")
    fi
    local -a kept_ts=("${dump_ts[@]:-}")

    for name in "${all_names[@]:-}"; do
        [ -n "$name" ] || continue
        if [[ "$name" == *.sql || "$name" == *.tar.gz ]]; then
            # Same hazard as the dump loop above: this key can be
            # a globals-*.sql or staging-*.tar.gz companion, and
            # this loop runs over the same $all_names listing that
            # holds the POSTGRES_DB-derived dump keys. Matched
            # with `[[ =~ ]]` against the whole string rather than
            # piped through sed, for the same reason.
            if [[ "$name" =~ ^.*[_-]([0-9]{8}_[0-9]{6})\.(sql|tar\.gz)$ ]]; then
                ts="${BASH_REMATCH[1]}"
            else
                continue
            fi
            local _found=0 _kt
            for _kt in "${kept_ts[@]:-}"; do
                [ -n "$_kt" ] || continue
                if [ "$_kt" = "$ts" ]; then
                    _found=1
                    break
                fi
            done
            if [ "$_found" -eq 0 ]; then
                log "Pruning orphaned s3://${S3_BUCKET}/backups/${prefix}/${name} (its dump aged out)"
                if ! aws s3 rm "s3://${S3_BUCKET}/backups/${prefix}/${name}" "${aws_args[@]:-}" > /dev/null; then
                    log "ERROR: could not delete s3://${S3_BUCKET}/backups/${prefix}/${name}"
                    rm_failed=1
                fi
            fi
        fi
    done

    # Surface a partial-prune cycle to run_backup so it marks the cycle
    # failed (cycle_failed=1), as a listing failure above does: retention
    # that mostly ran and quietly leaves objects behind is a failure.
    if [ "$rm_failed" -eq 1 ]; then
        return 1
    fi
}

# Retention pruning. Ordered by the timestamp in the filename, not by mtime:
# the embedded timestamp is the cycle's identity, while mtime is when the file
# was last written (weekly copies carry their `cp` time), and `find -printf`
# is a GNU extension that would make this unrunnable outside the container,
# including in scripts/tests/test-backup-restore-roundtrip.sh, a standalone
# local tool.
#
# Sorted on the extracted timestamp, not the whole path: the database name is
# the prefix, so after a POSTGRES_DB rename to a lexically earlier name every
# fresh dump would sort as the oldest and be pruned first. Files whose name
# carries no timestamp are not ours; they are neither counted nor deleted.
#
# The result is returned in the parallel DL_TS/DL_PATH globals (the same
# out-parameter pattern as common.sh's `_ern_*`/`_eir_*`), oldest first,
# rather than as a newline-joined "<ts>\t<path>" blob. A dump filename is
# `${POSTGRES_DB}_${timestamp}.dump`, and a filesystem name can contain an
# embedded newline as freely as an S3 key; `find`'s one-pathname-per-line
# output would read such a file back as two `dump` values before any
# downstream tool ran. Every step (`find -print0`, the array append, the
# index-permutation sort that prune_s3_prefix also uses) treats one dump as
# one array element.
dump_listing_arrays() {
    local dir="$1"
    DL_TS=()
    DL_PATH=()
    local dump base ts
    while IFS= read -r -d '' dump; do
        base="${dump##*/}"
        if [[ "$base" =~ ^.*_([0-9]{8}_[0-9]{6})\.dump$ ]]; then
            ts="${BASH_REMATCH[1]}"
        else
            continue
        fi
        DL_TS+=("$ts")
        DL_PATH+=("$dump")
    done < <(find "$dir" -maxdepth 1 -name "*.dump" -type f -print0)

    # Same NUL-safe index-permutation sort as prune_s3_prefix: `sort` only
    # sees "<timestamp> <index>" lines, never a path, and the sorted index
    # order permutes DL_TS/DL_PATH in place.
    if [ "${#DL_TS[@]}" -gt 0 ]; then
        local _i sort_input=""
        for ((_i = 0; _i < ${#DL_TS[@]}; _i++)); do
            sort_input="${sort_input}${DL_TS[$_i]} ${_i}"$'\n'
        done
        local -a order=()
        local _sts _sidx
        while IFS=' ' read -r _sts _sidx; do
            [ -n "$_sidx" ] || continue
            order+=("$_sidx")
        done < <(printf '%s' "$sort_input" | sort)
        local -a sorted_ts=() sorted_path=()
        for _i in "${order[@]:-}"; do
            [ -n "$_i" ] || continue
            sorted_ts+=("${DL_TS[$_i]}")
            sorted_path+=("${DL_PATH[$_i]}")
        done
        DL_TS=("${sorted_ts[@]:-}")
        DL_PATH=("${sorted_path[@]:-}")
    fi
}

# The timestamp of the newest set that is complete: a dump with the globals
# dump that pairs with it. prune_old_backups keeps that one out of the
# retention window.
#
# Without the exemption a run of pg_dumpall failures walks every complete set
# out of retention: each failed cycle still produces a valid dump (discarding
# it would be worse; data without roles beats nothing), so it counts toward
# the window and evicts an older complete set, whose globals goes with it as
# an orphan. After a full window of failures the operator has been warned
# every cycle (`.last-success` stale, healthcheck unhealthy) and still has
# dumps, but nothing that restores onto a fresh cluster. Holding one complete
# set back costs at most one extra dump plus a few KB of SQL.
newest_complete_ts() {
    local dir="$1"
    local globals ts best=""
    for globals in "$dir"/globals-*.sql; do
        [ -f "$globals" ] || continue
        # Bash `=~` on the whole string, not a value piped into sed;
        # see dump_listing_arrays. globals-*.sql is script-generated
        # and never carries POSTGRES_DB, but every extraction site in
        # this file uses the same form so none depends on a filename
        # not embedding operator input.
        if [[ "${globals##*/}" =~ ^globals-([0-9]{8}_[0-9]{6})\.sql$ ]]; then
            ts="${BASH_REMATCH[1]}"
        else
            continue
        fi
        find "$dir" -maxdepth 1 -name "*_${ts}.dump" -type f | grep -q . || continue
        if [ -z "$best" ] || [ "$ts" \> "$best" ]; then
            best="$ts"
        fi
    done
    printf '%s' "$best"
}

# Retention bucket of a YYYYmmdd_HHMMSS timestamp, in PERIOD_KEY: the calendar
# day, or the ISO week named by its Monday as a day count since 1970-01-01.
# Plain arithmetic, so GNU, BSD and busybox hosts all agree.
backup_period_key() {
    local period="$1" ts="$2"
    if [ "$period" = "day" ]; then
        PERIOD_KEY="${ts:0:8}"
        return 0
    fi
    local y=$((10#${ts:0:4})) m=$((10#${ts:4:2})) d=$((10#${ts:6:2}))
    if [ "$m" -le 2 ]; then
        y=$((y - 1))
    fi
    local era=$((y / 400))
    local yoe=$((y - era * 400))
    local doy=$(((153 * ((m + 9) % 12) + 2) / 5 + d - 1))
    local days=$((era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468))
    PERIOD_KEY=$((days - (days + 3) % 7))
}

# Sets RK_KEEP[i] to 1 for the newest entry of each of the `keep` most recent
# periods in RK_TS (sorted oldest first) and to 0 for the rest. Only periods
# that hold a backup count, so neither a stopped service nor a wrong clock
# ages out history that nothing newer has replaced. `protect` is the newest
# complete set, kept by the caller outside RK_TS: it stands for its own
# period, so only a newer entry in that period is kept beside it. `good` names
# the last dump known to hold the catalog; the newest entry at or before it is
# always kept, unless `protect` already stands for it. "At or before" covers a
# tier without that exact dump: weekly/, or offsite after upload was off.
mark_retained() {
    local period="$1" keep="$2" protect="${3:-}" good="${4:-}"
    local protect_key=""
    if [ -n "$protect" ]; then
        backup_period_key "$period" "$protect"
        protect_key="$PERIOD_KEY"
    fi
    RK_KEEP=()
    local _i last="" seen=0 good_found=0
    for ((_i = ${#RK_TS[@]} - 1; _i >= 0; _i--)); do
        RK_KEEP[_i]=0
        if [ -n "$good" ] && [ "$good_found" -eq 0 ] && ! [ "${RK_TS[$_i]}" \> "$good" ]; then
            good_found=1
            if [ -z "$protect" ] || [ "$protect" \> "$good" ] || [ "${RK_TS[$_i]}" \> "$protect" ]; then
                RK_KEEP[_i]=1
            fi
        fi
        backup_period_key "$period" "${RK_TS[$_i]}"
        if [ "$PERIOD_KEY" = "$protect_key" ] && [ "${RK_TS[$_i]}" \< "$protect" ]; then
            continue
        fi
        if [ "$PERIOD_KEY" != "$last" ]; then
            last="$PERIOD_KEY"
            seen=$((seen + 1))
            if [ "$seen" -le "$keep" ]; then
                RK_KEEP[_i]=1
            fi
        fi
    done
}

prune_old_backups() {
    local dir="$1"
    local keep="$2"
    local period="$3"
    local good="${4:-}"

    dump_listing_arrays "$dir"
    [ "${#DL_TS[@]}" -gt 0 ] || return 0

    # The protected set is held back IN ADDITION to the retention window, not
    # inside it: letting it occupy a slot would mean a retention of 1 keeps the
    # complete set and throws away the newest dump, which is the wrong trade.
    # So a directory holds at most `keep` + 1 dumps.
    local protect
    protect="$(newest_complete_ts "$dir")"

    # Filter DL_TS/DL_PATH by array index, never by grepping a
    # "<ts>\t<path>" text line: $protect is compared against a validated,
    # digits-only $ts (newline-free by dump_listing_arrays's regex
    # capture), so an embedded newline has no text stream to hide in.
    local -a cand_ts=() cand_path=()
    local _i
    for ((_i = 0; _i < ${#DL_TS[@]}; _i++)); do
        if [ -n "$protect" ] && [ "${DL_TS[$_i]}" = "$protect" ]; then
            continue
        fi
        cand_ts+=("${DL_TS[$_i]}")
        cand_path+=("${DL_PATH[$_i]}")
    done
    [ "${#cand_ts[@]}" -gt 0 ] || return 0

    RK_TS=("${cand_ts[@]}")
    mark_retained "$period" "$keep" "$protect" "$good"
    local to_remove=0
    for ((_i = 0; _i < ${#cand_ts[@]}; _i++)); do
        if [ "${RK_KEEP[$_i]}" -eq 0 ]; then
            to_remove=$((to_remove + 1))
        fi
    done
    [ "$to_remove" -gt 0 ] || return 0

    log "Pruning ${to_remove} old backup(s) from ${dir}"
    for ((_i = 0; _i < ${#cand_ts[@]}; _i++)); do
        if [ "${RK_KEEP[$_i]}" -eq 0 ]; then
            rm -f "${cand_path[$_i]}"
        fi
    done
}

# Companion artifacts (the object-storage archive and the globals dump) are
# pruned by pairing, not by their own count.
#
# Independent counts look equivalent but are not, because a companion can be
# absent for a cycle that still produces a dump: backup_staging skips a
# missing or empty staging mount, and a failed pg_dumpall leaves a good dump
# with no globals. Once the counts diverge, `keep the newest N of each` prunes
# a dump whose companion is younger than N and so survives, and after enough
# such cycles every complete set is gone while the orphans remain.
#
# The dumps are the primary artifact and prune_old_backups is the authority on
# retention. This runs after it and drops any companion whose dump is no
# longer there, so every companion present has the dump it pairs with.
prune_orphaned_companions() {
    local dir="$1"

    local companion base ts
    for companion in "$dir"/staging-*.tar.gz "$dir"/globals-*.sql; do
        # Unmatched globs expand to themselves; -f skips those.
        [ -f "$companion" ] || continue
        base="$(basename "$companion")"
        # Anchored at the end, like restore.sh's parse. Bash `=~` on
        # the whole string, not piped into sed; see
        # dump_listing_arrays.
        if [[ "$base" =~ ^.*-([0-9]{8}_[0-9]{6})\..*$ ]]; then
            ts="${BASH_REMATCH[1]}"
        else
            # A name we cannot pair is left alone rather than guessed at.
            continue
        fi
        if ! find "$dir" -maxdepth 1 -name "*_${ts}.dump" -type f | grep -q .; then
            log "Pruning orphaned ${base} from ${dir} (its dump has aged out)"
            rm -f "$companion"
        fi
    done
}

# BACKUP_SCHEDULE validation.
# The sleep-loop fallback scheduler (used when no cron daemon is available)
# only supports "M H * * *": a literal minute and hour with the other three
# fields set to *. Any other form never fires, since the comparison
# `[ "$current_min" = "*/15" ]` never matches.
#
# Fail fast at startup if BACKUP_SCHEDULE uses a form the simple scheduler
# cannot honour. If crond/cron is available the expression goes to the system
# cron, which handles the full 5-field syntax, but it is still validated so a
# schedule that works on a crond host does not silently break on an image
# without crond.
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

# Validate the schedule before doing anything else so an unsupported
# expression fails loudly instead of silently never firing.
validate_cron_expr "$CRON_EXPR"

# First-run entry point
log "GeoLens backup service starting"
log "Schedule: ${CRON_EXPR}"
log "Retention: ${BACKUP_RETENTION_DAILY} daily, ${BACKUP_RETENTION_WEEKLY} weekly"
log "S3 upload: ${BACKUP_S3_ENABLED}"

# BACKUP_S3_ENABLED defaults to false, and "S3 upload: false" reads
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
    if [ -e "${BACKUP_DIR}/.last-offsite-success" ]; then
        log "WARNING: offsite upload succeeded earlier on this volume and is now off."
        log "WARNING:   The healthcheck turns unhealthy once that last offsite copy is"
        log "WARNING:   older than BACKUP_MAX_AGE_MINUTES. Set BACKUP_S3_ENABLED=true again,"
        log "WARNING:   or, if turning offsite upload off was intended, clear the marker with:"
        log "WARNING:     docker compose exec backup rm ${BACKUP_DIR}/.last-offsite-success"
    fi
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
