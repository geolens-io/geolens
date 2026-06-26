# GeoLens Operator Runbook — Day-2 Operations & Disaster Recovery

This is the canonical in-repo reference for day-2 operations: backup architecture,
restore procedures, monitoring, and incident response. An operator can recover a
GeoLens installation from a backup using this document alone, with no external
documentation.

> **Implements BKP-04.** See [UPGRADING.md](UPGRADING.md) for the upgrade and
> rollback quick-reference; this document is the authoritative source for DR /
> restore / monitoring / incident response for both database modes.

---

## Table of Contents

1. [Backup architecture](#1-backup-architecture)
2. [Restore — bundled Postgres mode](#2-restore--bundled-postgres-mode)
3. [Restore — managed / external Postgres mode](#3-restore--managed--external-postgres-mode)
4. [Monitoring](#4-monitoring)
5. [Incident response — data loss](#5-incident-response--data-loss)

---

## 1. Backup architecture

### Automated backups are on by default

Backup runs automatically on every `docker compose up` — no `--profile backup`
flag is needed. The `backup` service starts alongside `api`, `worker`, and `db`.

The default schedule is **02:00 daily** (`BACKUP_SCHEDULE=0 2 * * *`). An initial
backup runs at container start. Subsequent backups fire on the configured schedule
(via cron, or a built-in sleep-loop when cron is unavailable in the image).

To change the schedule, set `BACKUP_SCHEDULE` in `.env`:

```
BACKUP_SCHEDULE=0 3 * * *    # 03:00 daily — must be in "M H * * *" form
```

### What each backup cycle captures

Each cycle produces two paired artifacts with matching timestamps:

| Artifact | Format | What it contains |
|---|---|---|
| `<db>_<YYYYmmdd_HHMMSS>.dump` | `pg_dump -Fc` custom-format | Full database (schema + data), restorable via `pg_restore` |
| `staging-<YYYYmmdd_HHMMSS>.tar.gz` | tar.gz | Contents of the `upload_staging` volume (source files, rasters, COGs) |

The staging archive is omitted silently when the `upload_staging` volume is absent
or empty (fresh install with no uploaded datasets).

### Retention

Artifacts land at:
- Daily: `backup_data` volume → `/backups/daily/`
- Weekly (every Sunday): `backup_data` volume → `/backups/weekly/`

Default retention: 7 daily, 4 weekly (set `BACKUP_RETENTION_DAILY` /
`BACKUP_RETENTION_WEEKLY` in `.env` to override). Retention prunes both
`.dump` files and their paired `staging-*.tar.gz` archives.

### Offsite (S3) upload

Offsite upload is **opt-in**. To enable it, set in `.env`:

```
BACKUP_S3_ENABLED=true
S3_ENDPOINT=https://s3.<region>.amazonaws.com
S3_BUCKET=<your-bucket>
S3_ACCESS_KEY_ID=<key-id>
S3_REGION=us-east-1
```

Also set `S3_SECRET_ACCESS_KEY` to your access secret. See `.env.example` for all
available S3 options including `S3_ALLOW_HTTP`.

The built-in uploader signs with **AWS Signature V2** (compatible with classic AWS
buckets and MinIO). For buckets requiring Sig-V4 (most modern AWS buckets), replace
the upload step with a sidecar using `aws-cli`. S3 upload failures are non-fatal and
logged as `WARNING: S3 upload failed for <key> (non-fatal)` — a failed upload does
not abort the local backup cycle.

### Scope caveat

The staging archive captures the **local `upload_staging` Docker volume only**.
If your deployment offloads objects to an external S3/R2/GCS bucket, that bucket's
lifecycle policy is responsible for its own backup; GeoLens does not back up
external object stores.

---

## 2. Restore — bundled Postgres mode

Use this path when Postgres runs in the bundled `db` container (the default
self-hosted Docker Compose deployment).

### Canonical restore entry point

```bash
./scripts/restore.sh <dump-file>
```

`scripts/restore.sh` is the **canonical operator-facing restore entry point**. It:

1. Validates the dump with `pg_restore --list` — aborts if the file is corrupt.
2. Creates required extensions and schemas in the database.
3. Stops `api` and `worker` to prevent write conflicts.
4. Runs `pg_restore --clean --if-exists --no-owner` against the bundled `db` container.
5. Restarts `api` and `worker` on exit (including on failure — via a trap).
6. Runs a post-restore row-count check (`catalog.records`, `catalog.datasets`).
7. Auto-detects any sibling `staging-<timestamp>.tar.gz` next to the dump and
   prints the exact manual object-storage extract command.

**Never** use `psql < <dump>` on a custom-format (`-Fc`) dump file — it is binary,
not plain SQL, and will fail.

### Step-by-step: full restore (DB + object storage)

```bash
# 1. Restore the database.
#    Replace the dump path with the backup you want to restore from.
./scripts/restore.sh backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump

# 2. Restore the matching object-storage archive into the upload_staging volume.
#    This step is MANUAL — restore.sh prints the exact command from step 1 output.
#    Replace <project> with your Compose project name.
#    Run `docker volume ls` to confirm the volume name (<project>_upload_staging).
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/backups/daily":/restore:ro \
  alpine sh -c 'cd /staging && tar xzf /restore/staging-<YYYYmmdd_HHMMSS>.tar.gz'
```

`restore.sh` auto-detects the sibling staging archive (matched by timestamp) and
prints the `docker run` line above with the real paths filled in. Copy the printed
command from the restore output rather than hand-editing it.

### Finding the dump to restore

```bash
# List available daily backups (newest first)
ls -lt backups/daily/*.dump

# Validate a specific dump before restoring
docker compose exec -T db \
  pg_restore --list - < backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump | head -20
```

---

## 3. Restore — managed / external Postgres mode

Use this path when Postgres is provided by a cloud managed database service
(AWS RDS, Google Cloud SQL, Azure Database for PostgreSQL, or any other
external Postgres provider).

### How responsibility is divided

| Component | Recovery owner |
|---|---|
| Database | **Provider** — via native snapshot / PITR (not restore.sh) |
| Object storage (`upload_staging` volume) | **GeoLens backup container** — via `staging-<timestamp>.tar.gz` archive |

`restore.sh` issues its `docker compose exec db` commands against the bundled `db`
container. **Do not run `restore.sh` when the database is external** — there is no
bundled `db` container to exec into. Restore the database using the provider's
native tooling.

### Step-by-step: full restore (managed DB mode)

**Step 1: Restore the database from a provider snapshot or PITR.**

| Provider | Documentation entry point |
|---|---|
| AWS RDS | Modify instance → Automated backups → Restore to point in time |
| Google Cloud SQL | Edit instance → Backups → Restore |
| Azure Database for PostgreSQL | Server → Backup → Restore |

Follow the provider console or CLI to restore the DB to the desired point in time.
After restoration, verify that the DB is reachable and extensions are present
(`postgis`, `vector`, `pg_trgm`, `unaccent`).

**Step 2: Restore the object-storage archive into the `upload_staging` volume.**

The GeoLens backup container will have archived the local `upload_staging` volume
as `staging-<YYYYmmdd_HHMMSS>.tar.gz`. Copy the archive to the host, then extract:

```bash
# Replace <project> with your Compose project name.
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/backups/daily":/restore:ro \
  alpine sh -c 'cd /staging && tar xzf /restore/staging-<YYYYmmdd_HHMMSS>.tar.gz'
```

**Step 3: Boot the application against the recovered database.**

Update `.env` to point `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_DB` at the restored managed database endpoint, then bring the stack up:

```bash
docker compose up -d api worker frontend
docker compose ps    # confirm api and worker are healthy
```

### Optional: point-in-time recovery (PITR) with WAL archiving

For finer-grained recovery between backup snapshots, managed databases provide
native PITR — enable it via the provider console (see provider links above). For
self-hosted Docker deployments, WAL archiving requires `wal_level = replica` and
`archive_command` in `postgresql.conf`; see the comments at the end of
`scripts/restore.sh` for the configuration outline.

---

## 4. Monitoring

### Backup service healthcheck

The `backup` service exposes a Docker healthcheck:

```bash
docker compose ps backup    # Status column: healthy / unhealthy / starting
docker compose inspect backup --format '{{.State.Health.Status}}'
```

The check (`pgrep -f backup-entrypoint || pgrep -f sleep`) confirms the entrypoint
process is running. `start_period` is 30 s; the check runs every 60 s.

### Log markers

Follow backup logs:

```bash
docker compose logs -f backup
```

| Log message | Meaning |
|---|---|
| `Backup complete: <filename> (<size>)` | `pg_dump` succeeded; dump is in `/backups/daily/` |
| `Object-storage archive complete: staging-<ts>.tar.gz (<size>)` | `upload_staging` archived alongside the dump |
| `Backup cycle complete` | Full cycle (dump + staging + S3 if enabled) finished |
| `WARNING: S3 upload failed for <key> (non-fatal)` | Offsite upload failed; local backup is intact |
| `WARNING: object-storage archive failed (non-fatal)` | Staging tar failed; DB dump is still good |
| `ERROR: pg_dump failed` | DB dump failed; no artifacts written for this cycle |

A healthy cycle produces at least `Backup complete` and `Backup cycle complete`.
Missing these messages at the expected schedule time indicates a missed backup.

### Where artifacts land

The `backup_data` named volume is mounted at `/backups` inside the container.
To inspect artifacts from the host:

```bash
# List current daily backups
docker compose exec backup ls -lh /backups/daily/

# Or access via a temporary container
docker run --rm -v <project>_backup_data:/backups alpine ls -lh /backups/daily/
```

### Detecting a failed offsite upload

When `BACKUP_S3_ENABLED=true`, search the logs for the failure marker:

```bash
docker compose logs backup | grep 'WARNING: S3 upload failed'
```

A failed S3 upload does not affect the local backup cycle but means the offsite
copy is absent for that cycle. Investigate S3 credentials and endpoint reachability.

---

## 5. Incident response — data loss

Follow this ordered procedure to recover from data loss.

### 1. Assess scope

Determine what was lost:
- Is the database intact? (`docker compose exec db psql -U geolens -c '\l'`)
- Are uploaded source files (in `upload_staging`) missing?
- What is the latest backup timestamp? (`docker compose exec backup ls -lt /backups/daily/*.dump | head -5`)

### 2. Select the newest valid dump

```bash
# List all daily dumps, newest first
docker compose exec backup ls -lt /backups/daily/*.dump

# Validate the candidate dump before restoring
docker compose -f docker-compose.yml exec -T db \
  pg_restore --list - < backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump | head -20
```

If the daily dump is corrupt, fall back to a weekly backup under
`/backups/weekly/`, or to a pre-upgrade dump under `backups/pre-upgrade/`.

### 3. Restore the database

**Bundled Postgres:**

```bash
./scripts/restore.sh backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump
```

**Managed / external Postgres:** restore via the provider snapshot or PITR — see
[§3](#3-restore--managed--external-postgres-mode).

### 4. Restore object storage

Extract the matching staging archive (copy the `docker run` command printed by
`restore.sh`, or construct it from the timestamp):

```bash
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/backups/daily":/restore:ro \
  alpine sh -c 'cd /staging && tar xzf /restore/staging-<YYYYmmdd_HHMMSS>.tar.gz'
```

### 5. Verify row counts and application boot

```bash
# Quick row-count sanity check (restore.sh also runs this automatically)
docker compose exec db psql -U geolens -d geolens -c \
  "SELECT 'records' AS tbl, COUNT(*) FROM catalog.records
   UNION ALL SELECT 'datasets', COUNT(*) FROM catalog.datasets;"

# Confirm the stack is healthy
docker compose ps
```

For a full round-trip confidence check, the automated recovery test is at
`scripts/tests/test-backup-restore-roundtrip.sh`. Run it against a non-production
stack to confirm the restore procedure from end to end before trusting the data.

### 6. Post-incident notes

- Record the incident timestamp, affected data range, and dump used.
- Confirm whether the S3 offsite copy covered the recovery window
  (`docker compose logs backup | grep 'S3 upload complete'`).
- If the backup cycle missed the recovery window, review `BACKUP_SCHEDULE` and
  whether any `ERROR: pg_dump failed` entries appear in the logs for that period.
- Re-enable the backup service if it was stopped during recovery:
  `docker compose start backup`.
