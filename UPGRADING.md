# Upgrading GeoLens

This guide covers upgrading a self-hosted GeoLens install between versions, with
a **backup-first** flow and a tested **rollback** path.

GeoLens upgrades are: **back up the database → pull the new images → run database
migrations (fail-closed) → bring the stack up behind a health gate.** If anything
fails, you re-pin the old version and restore the pre-upgrade dump.

> **Always take a backup before upgrading.** The one-command flow does this for
> you; the manual flows below tell you exactly when to do it.

> **⚠️ Major PostgreSQL upgrades are a special case.** When a GeoLens release
> bumps the bundled PostgreSQL **major** version (first occurrence: the release
> that moves PostgreSQL 17 → 18 / PostGIS 3.5 → 3.6), the flows on this page do
> **not** apply: a PG 17 `pgdata` volume cannot be opened by a PG 18 server, so
> after the image pull the `db` container will refuse to start ("database files
> are incompatible with server"). Follow
> [RUNBOOK.md § 6 — Major PostgreSQL version upgrade](RUNBOOK.md#6-major-postgresql-version-upgrade-17--18)
> instead (dump → fresh volume → restore, with rollback notes). The release
> notes call out every release this applies to. You do not have to catch this
> yourself: `scripts/upgrade.sh` compares the running server's major against the
> target release's bundled one and stops before changing anything, pointing here,
> when they differ.

---

## How your install was set up

`scripts/install.sh` records which path you are on in `.env`:

- **Prebuilt images** (`curl -fsSL https://getgeolens.com/install.sh | sh`):
  `.env` contains `COMPOSE_FILE=docker-compose.prod.yml` and a pinned
  `GEOLENS_VERSION=<x.y.z>`. The version-pinned `api` / `worker` / `migrate`
  images are pulled from the registry; only the small database layer builds
  locally. **This is the recommended path and the one `scripts/upgrade.sh`
  automates.**
- **Source build** (`git clone … && bash scripts/install.sh`):
  `.env` contains `COMPOSE_FILE=docker-compose.yml` (or no `COMPOSE_FILE`) and no
  `GEOLENS_VERSION` pin. Every image builds from your checkout. Upgrading means
  updating the checkout and rebuilding — see
  [Source-build upgrade](#source-build-upgrade-alternate) below.

Check which one you are on:

```bash
grep -E '^(COMPOSE_FILE|GEOLENS_VERSION)=' .env
```

---

## Prebuilt upgrade (recommended)

### One command

From your install directory:

```bash
./scripts/upgrade.sh            # upgrade to the newest published release
./scripts/upgrade.sh 1.2.4      # or pin an explicit target version
```

`scripts/upgrade.sh` performs, in order:

1. **Syncs and pulls** — checks the release files out at the target tag and
   pulls the prebuilt images (`docker compose pull --ignore-buildable`). The app
   keeps serving throughout, so the download costs no downtime. `db` is the one
   locally-built image (`--ignore-buildable` skips it by definition); when the
   release's `db/Dockerfile` changed and yours is unmodified, it is synced too
   and the image is rebuilt before the migrate step below. A `db/Dockerfile`
   you edited yourself is left alone, the same as a tuned `db/postgresql.conf`.
2. **Stops `api` and `worker`**, then takes the **pre-upgrade backup** —
   `pg_dump -Fc` to
   `backups/pre-upgrade/<db>_pre_<old>_to_<new>_<timestamp>.dump`, verified by
   reading it back end to end. The upgrade **aborts** and restarts the previous
   version if the dump is missing, empty, or unreadable.
3. **Runs migrations** — the one-shot `migrate` service (fail-closed). With the
   app stopped, a data migration sees the final state of the old data instead of
   racing writes from the release being replaced.
4. **Pins** the new `GEOLENS_VERSION` in `.env`, once the migrations have
   committed.
5. **Starts** the stack and waits for every service to report healthy.

Steps 2 through 5 are an **outage**: the instance takes no writes and answers no
API traffic until the new version is healthy.
[RUNBOOK.md § 10](RUNBOOK.md#10-routine-version-upgrade-outage-and-rollback)
covers how long that lasts, what keeps serving, and what to do if the script
dies mid-way.

On success it prints the rollback recipe for reference and keeps the
pre-upgrade dump. On **any** failure it stops, leaves your data in the dump, and
prints the same rollback recipe. If it fails while the app is stopped for the
migration, it brings the **previous** version back up first and checks that it
stayed up, so a failed upgrade does not quietly leave the instance down.

> Re-running `scripts/install.sh` in an existing install also **detects** a newer
> release: it prints a notice (non-interactive) or offers to upgrade
> (interactive). `bash scripts/install.sh --upgrade` performs the upgrade by
> delegating to `scripts/upgrade.sh`.

### Manual prebuilt equivalent

If you prefer to drive it by hand (same steps as the script):

```bash
# 1. Pull the new images first. The app keeps serving while this runs. Select
#    the target for compose without editing .env yet (replace 1.2.4).
export GEOLENS_VERSION=1.2.4
docker compose -f docker-compose.prod.yml pull --ignore-buildable

# 2. Stop the writers, THEN back up (custom-format dump — the format restore.sh
#    expects). Stopping api+worker first is what makes the dump a snapshot with
#    no lost writes, and what keeps step 3's migrations from racing writes from
#    the release you are replacing. The outage starts here.
docker compose -f docker-compose.prod.yml stop api worker
mkdir -p backups/pre-upgrade
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U geolens -d geolens -Fc --no-owner --no-acl \
  > "backups/pre-upgrade/geolens_$(date +%Y%m%d_%H%M%S).dump"

# 3. Run migrations (fail-closed one-shot) BEFORE starting the app.
docker compose -f docker-compose.prod.yml up -d --no-deps migrate
docker compose -f docker-compose.prod.yml logs migrate   # confirm it exited 0

# 4. Pin the new version in .env now that the migrations have committed.
#    Edit the GEOLENS_VERSION= line, e.g.:
#    GEOLENS_VERSION=1.2.4

# 5. Bring the stack up and verify health. The outage ends here.
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

If step 3 fails, put the previous release back rather than leaving the instance
down. `--no-deps` is required here: `api` depends on the `migrate` one-shot
completing successfully, so a plain `up -d` re-runs the migration that just
failed.

```bash
GEOLENS_VERSION=1.2.3 docker compose -f docker-compose.prod.yml \
  up -d --no-deps api worker      # replace 1.2.3 with the version you were on
```

---

## Source-build upgrade (alternate)

For installs that build from source (`COMPOSE_FILE=docker-compose.yml`),
`scripts/upgrade.sh` will detect this and print these instructions instead of
running — it does **not** modify a source install. Upgrade by updating the
checkout and rebuilding:

```bash
# 1. Stop the writers FIRST. The outage starts here. Unlike the prebuilt flow,
#    the build cannot happen while the app serves: this compose file
#    bind-mounts ./backend/app into the api container, so checking out the new
#    tag in step 3 swaps the running app's code the moment it lands.
docker compose -f docker-compose.yml stop api worker

# 2. Back up (custom-format dump — the format restore.sh expects). With the
#    writers stopped, the dump loses no acknowledged writes and step 4's
#    migrations cannot race the release you are replacing.
mkdir -p backups/pre-upgrade
docker compose -f docker-compose.yml exec -T db \
  pg_dump -U geolens -d geolens -Fc --no-owner --no-acl \
  > "backups/pre-upgrade/geolens_$(date +%Y%m%d_%H%M%S).dump"

# 3. Update the checkout to the new release tag and rebuild.
git fetch --tags origin
git checkout v1.2.4            # replace with your target tag
docker compose -f docker-compose.yml build

# 4. Run migrations (fail-closed) BEFORE starting the app.
docker compose -f docker-compose.yml up -d --no-deps migrate
docker compose -f docker-compose.yml logs migrate   # confirm it exited 0

# 5. Bring the stack up and verify health. The outage ends here.
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

---

## Rollback

Rollback is **re-pin the previous version + restore the pre-upgrade database
dump**. Schema migrations move forward only.

> **`alembic downgrade` is NOT a supported rollback.** Migrations are not
> guaranteed to be reversible. Always roll back by restoring the pre-upgrade
> `-Fc` dump that the upgrade took for you.

```bash
# 1. Re-pin the previous version in .env (edit the GEOLENS_VERSION= line):
#    GEOLENS_VERSION=1.2.3      # the version you upgraded FROM

# 2. Restore the pre-upgrade dump. scripts/restore.sh validates the dump
#    end-to-end (`pg_restore -f /dev/null`), stops api/worker, and runs
#    `pg_restore` (it always restarts api/worker afterward). Pass the dump
#    file the upgrade created:
./scripts/restore.sh backups/pre-upgrade/<db>_pre_<old>_to_<new>_<timestamp>.dump

# 3. Bring the previous version back up:
docker compose -f docker-compose.prod.yml up -d     # or docker-compose.yml for source builds
docker compose -f docker-compose.prod.yml ps
```

Notes:

- `scripts/restore.sh` takes a **custom-format (`-Fc`) dump** and restores it via
  `pg_restore` — the same format `scripts/upgrade.sh` and the manual flows
  produce. **Never** `psql < dump` a `-Fc` file; it is not plain SQL.
- `scripts/restore.sh` honours the `COMPOSE_FILE` from your `.env` (the prebuilt
  installer pins `docker-compose.prod.yml`; it falls back to `docker-compose.yml`
  for source builds), so restore targets the same Compose-project containers your
  stack is running — no `-f` editing needed for the standard prebuilt or source
  layouts.

---

## Backups

- Automated, scheduled backups **run by default** (the `backup` Compose service,
  `scripts/backup-entrypoint.sh`) with daily/weekly retention — no `--profile`
  flag needed. Configure schedule/retention via the `BACKUP_*` env vars; see the
  [Backups & Restore guide](https://docs.getgeolens.com/guides/admin/backups/).
- Off-site (S3) upload is additionally gated on `BACKUP_S3_ENABLED=true`. The
  built-in uploader (awscli) signs with **AWS Signature V4**, compatible with
  Cloudflare R2, modern AWS S3, and MinIO.
- Each backup cycle archives **both** the `pg_dump` (`<db>_<timestamp>.dump`)
  **and** the object-storage staging volume (`staging-<timestamp>.tar.gz`) so a
  restore reproduces a working instance — DB rows *and* the staged source objects
  they reference. The staging archive captures the local `upload_staging` volume
  only; deployments that offload objects to an external S3/MinIO bucket must back
  that bucket up separately.
- The backup service **fails fast on misconfiguration** (since 1.6.0): a
  `BACKUP_RETENTION_DAILY`/`BACKUP_RETENTION_WEEKLY` below 1 makes the
  container exit at boot (it would delete each backup as soon as it was
  written), and `BACKUP_S3_ENABLED=true` with `S3_BUCKET`,
  `S3_ACCESS_KEY_ID`, or `S3_SECRET_ACCESS_KEY` unset fails the backup cycle
  instead of silently skipping the offsite upload. Either misconfiguration
  surfaces as a restarting/unhealthy `backup` container after an upgrade —
  fix the `.env` values; the rest of the stack is unaffected.
- The upgrade flow takes its own **pre-upgrade** dump under
  `backups/pre-upgrade/` independently of the scheduled backup service, so you
  always have a known-good restore point for the upgrade you just ran.

---

## Disaster recovery

> **[RUNBOOK.md](RUNBOOK.md) is the canonical day-2 operations and disaster-recovery
> reference**, covering DR / restore / monitoring / incident response for both
> bundled-Postgres and managed/external-Postgres modes. The quick commands below are
> the bundled-mode summary; see RUNBOOK.md for managed-DB restore, monitoring, and
> full incident-response guidance.

To restore from a full backup (DB + object storage). Dumps are written to the
`backup_data` named volume (not a host directory), so first copy the chosen dump
and its paired staging archive out of the volume:

```bash
# 0. Copy the chosen backup out of the backup_data volume to the host. Replace
#    <project> with your Compose project name (see `docker volume ls`).
mkdir -p ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'cp /backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump /out/ && \
                cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/ 2>/dev/null; ls -lh /out'

# 1. Restore the database (custom-format dump → pg_restore). This is THE
#    canonical restore path; never `psql < dump` a -Fc file.
./scripts/restore.sh ./restore/geolens_<YYYYmmdd_HHMMSS>.dump

# 2. Restore the matching object-storage archive into the upload_staging volume.
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/restore":/restore:ro \
  alpine sh -c 'cd /staging && tar xzf /restore/staging-<YYYYmmdd_HHMMSS>.tar.gz'
```

`restore.sh` auto-detects a sibling `staging-<timestamp>.tar.gz` next to the dump
(here in `./restore`) and prints the exact `docker run` line above with the real
paths filled in, so you can copy it from the restore output rather than
hand-editing it.

---

<!--
  Maintainer note (cross-repo follow-up): the canonical user-facing upgrade docs
  also live at getgeolens.com (docs/.../upgrade.mdx, linked from README as the
  "Upgrade Guide"). Keep that page in sync with this file — same prebuilt-primary
  flow, source-build alternate, and dump-restore rollback. Do NOT let alembic
  downgrade creep back in as a rollback there. This is tracked as a cross-repo
  follow-up; it is intentionally NOT edited from the geolens repo.

  Likewise the Backups & Restore guide (getgeolens.com docs/.../backups.mdx,
  linked from README) must reflect the same corrections made here in v1043
  (BKP-02/03): scripts/restore.sh is THE restore path (never `psql <` a -Fc
  dump); backups run by default (no `--profile` gate); the built-in S3 uploader
  is SigV4 (Cloudflare R2 / modern AWS S3 / MinIO compatible); and a full restore
  copies the dump + staging-<timestamp>.tar.gz out of the backup_data volume.
  Cross-repo follow-up — intentionally NOT edited from the geolens repo.
-->
