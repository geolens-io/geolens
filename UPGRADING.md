# Upgrading GeoLens

This guide covers upgrading a self-hosted GeoLens install between versions, with
a **backup-first** flow and a tested **rollback** path.

GeoLens upgrades are: **back up the database → pull the new images → run database
migrations (fail-closed) → bring the stack up behind a health gate.** If anything
fails, you re-pin the old version and restore the pre-upgrade dump.

> **Always take a backup before upgrading.** The one-command flow does this for
> you; the manual flows below tell you exactly when to do it.

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

1. **Pre-upgrade backup** — `pg_dump -Fc` to
   `backups/pre-upgrade/<db>_pre_<old>_to_<new>_<timestamp>.dump`. The upgrade
   **aborts** if the dump is missing or empty (nothing else is touched).
2. **Pins** the new `GEOLENS_VERSION` in `.env`.
3. **Pulls** the prebuilt images (`docker compose pull --ignore-buildable`).
4. **Runs migrations** — the one-shot `migrate` service (fail-closed). A failed
   migration **aborts before the app is started**.
5. **Starts** the stack and waits for every service to report healthy.

On success it prints the rollback recipe for reference and keeps the
pre-upgrade dump. On **any** failure it stops, leaves your data in the dump, and
prints the same rollback recipe.

> Re-running `scripts/install.sh` in an existing install also **detects** a newer
> release: it prints a notice (non-interactive) or offers to upgrade
> (interactive). `bash scripts/install.sh --upgrade` performs the upgrade by
> delegating to `scripts/upgrade.sh`.

### Manual prebuilt equivalent

If you prefer to drive it by hand (same steps as the script):

```bash
# 1. Back up first (custom-format dump — the format restore.sh expects).
mkdir -p backups/pre-upgrade
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U geolens -d geolens -Fc --no-owner --no-acl \
  > "backups/pre-upgrade/geolens_$(date +%Y%m%d_%H%M%S).dump"

# 2. Pin the new version in .env (replace 1.2.4 with your target).
#    Edit the GEOLENS_VERSION= line, e.g.:
#    GEOLENS_VERSION=1.2.4

# 3. Pull the new prebuilt images.
docker compose -f docker-compose.prod.yml pull --ignore-buildable

# 4. Run migrations (fail-closed one-shot) BEFORE starting the app.
docker compose -f docker-compose.prod.yml up -d --no-deps migrate
docker compose -f docker-compose.prod.yml logs migrate   # confirm it exited 0

# 5. Bring the stack up and verify health.
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

---

## Source-build upgrade (alternate)

For installs that build from source (`COMPOSE_FILE=docker-compose.yml`),
`scripts/upgrade.sh` will detect this and print these instructions instead of
running — it does **not** modify a source install. Upgrade by updating the
checkout and rebuilding:

```bash
# 1. Back up first.
mkdir -p backups/pre-upgrade
docker compose -f docker-compose.yml exec -T db \
  pg_dump -U geolens -d geolens -Fc --no-owner --no-acl \
  > "backups/pre-upgrade/geolens_$(date +%Y%m%d_%H%M%S).dump"

# 2. Update the checkout to the new release tag.
git fetch --tags origin
git checkout v1.2.4            # replace with your target tag

# 3. Rebuild the images from the new source.
docker compose -f docker-compose.yml build

# 4. Run migrations (fail-closed) BEFORE starting the app.
docker compose -f docker-compose.yml up -d migrate
docker compose -f docker-compose.yml logs migrate   # confirm it exited 0

# 5. Bring the stack up and verify health.
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

# 2. Restore the pre-upgrade dump. scripts/restore.sh validates the dump with
#    `pg_restore --list`, stops api/worker, and runs `pg_restore` (it always
#    restarts api/worker afterward). Pass the dump file the upgrade created:
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
