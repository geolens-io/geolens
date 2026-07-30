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
6. [Major PostgreSQL version upgrade (17 → 18)](#6-major-postgresql-version-upgrade-17--18)

---

## 1. Backup architecture

> **Recovery point objective: up to 24 hours.** The bundled backup is a nightly
> logical dump (`pg_dump`), so a failure restores to the last completed backup —
> at the default 02:00 schedule, a loss at 01:59 discards a full day of uploads,
> edits, and analysis outputs. There is no finer granularity available with this
> tooling: logical dumps cannot participate in WAL replay, so point-in-time
> recovery requires physical backup plus WAL archiving, which the bundled stack
> does **not** configure (see [§ 3](#optional-point-in-time-recovery-pitr-with-wal-archiving)).
> Shorten the exposure with a more frequent `BACKUP_SCHEDULE`, or use a managed
> database, where the provider's native PITR applies.

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

> **Warning — single-disk exposure.** By default the `backup_data` volume lives
> on the same host (and usually the same disk) as the database volume. Losing
> that disk loses the data **and every backup of it** in one event. Treat the
> local dumps as a convenience tier only: enable the S3 offsite upload below,
> or point `backup_data` at a different physical disk, before relying on this
> for disaster recovery.

Offsite upload is **opt-in**. To enable it, set in `.env`:

```
BACKUP_S3_ENABLED=true
S3_ENDPOINT=https://s3.<region>.amazonaws.com
S3_BUCKET=<your-bucket>
S3_ACCESS_KEY_ID=<key-id>
S3_REGION=us-east-1
```

Also set `S3_SECRET_ACCESS_KEY` to your access secret. See `.env.example` for all
available S3 options including `S3_ADDRESSING_STYLE`. The backup uploader follows
whatever scheme `S3_ENDPOINT` carries — use an `http://` endpoint for a
plain-HTTP MinIO (`S3_ALLOW_HTTP` only affects the app's own object-storage
client, not the backup uploader).

The built-in uploader signs requests with **AWS Signature V4** (awscli), compatible
with Cloudflare R2, modern AWS S3, and MinIO. A failed upload is logged as
`ERROR: S3 upload failed for <key>` and fails the cycle (non-zero exit) **after**
local retention pruning has run — the local dump is kept and pruned normally even
when the offsite copy fails, so the failure is visible in container logs without
sacrificing the local backup.

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

1. Validates the dump with `pg_restore -f /dev/null` — reads every data block
   and aborts if the file is corrupt or truncated. (`--list` would only read the
   table of contents, which a truncated archive still passes.)
2. Creates required extensions and schemas in the database.
3. Stops `api` and `worker` to prevent write conflicts.
4. Runs `pg_restore --clean --if-exists --no-owner` against the bundled `db` container.
5. Re-applies the `geolens_reader` grants on schema `data` and asserts they took
   (`has_schema_privilege`). `--clean` drops the schema together with its ACLs
   and default privileges, and the dump carries no ACLs (`--no-acl`), so the
   grants must be rebuilt after every restore.
6. Restarts `api` and `worker` on exit (including on failure — via a trap).
7. Runs a post-restore row-count check (`catalog.records`, `catalog.datasets`).
8. Auto-detects any sibling `staging-<timestamp>.tar.gz` next to the dump and
   prints the exact manual object-storage extract command.

**Never** use `psql < <dump>` on a custom-format (`-Fc`) dump file — it is binary,
not plain SQL, and will fail.

### Multi-tenant role reconstruction after a fresh-cluster restore

PostgreSQL roles are cluster objects and are not included in a database-only
`pg_dump`. A same-cluster restore normally retains the roles themselves — but
not the ACLs on schemas that `--clean` drops and recreates: those (including
default privileges) die with the schema and must be re-granted after the
restore, which is why `restore.sh` re-applies the `geolens_reader` grants as a
post-restore step.

Nothing about roles travels inside a GeoLens dump: `scripts/backup-entrypoint.sh`
writes it `--no-owner --no-acl` and `scripts/restore.sh` replays it `--no-owner`.
A fresh cluster therefore needs both halves rebuilt — the role *definitions*
(step 1) and the *ownership and grants* on restored tenant objects (step 2).
Run both before starting API, worker, or tile traffic.

**Step 1 — put the roles on the new cluster.**

The clean way is a globals dump captured from the source cluster while it is
still reachable, or from a replica. Take one now if your backup cycle has no
`pg_dumpall --globals-only` artifact — it is the piece a database-only
`pg_dump` can never give back.

```bash
# Load .env so $POSTGRES_USER / $POSTGRES_DB are set in this shell.
set -a; . ./.env; set +a

# On the source cluster. umask 077 because --globals-only emits role password
# verifiers: under a default 022 umask this file lands world-readable. Store it
# with the same protection as the dump itself, or add --no-role-passwords and
# reset the login passwords during recovery instead.
(umask 077; docker compose exec -T db \
  pg_dumpall --globals-only -U "$POSTGRES_USER" > globals.sql)

# On the new cluster, BEFORE pg_restore.
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres < globals.sql
```

For managed/external Postgres there is no `db` container to exec into: drop the
`docker compose exec -T db` prefix and pass the provider's `-h`, `-p`, and `-U`
to `pg_dumpall`/`psql` directly.

If no globals dump exists, create the five fixed NOLOGIN groups by hand. This
must happen **before** the step 2 commands: the downgrade passes through 0024,
whose `downgrade()` re-installs the provisioning function with
`OWNER TO geolens_tenant_provisioner`, so it fails on a cluster where that role
is missing. The block is idempotent; run it as the migrator (needs CREATEROLE),
and the attributes match what 0019 creates and validates.

```sql
DO $$
DECLARE
    group_name text;
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_roles WHERE rolname = 'geolens_tenant_provisioner'
    ) THEN
        CREATE ROLE geolens_tenant_provisioner
            NOLOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
    FOREACH group_name IN ARRAY ARRAY[
        'geolens_tenant_control', 'geolens_tenant_writer',
        'geolens_tenant_sandbox', 'geolens_tile_gateway'
    ] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = group_name) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOINHERIT NOREPLICATION NOBYPASSRLS', group_name);
        END IF;
    END LOOP;
END
$$;
```

**Step 2 — re-own the restored tenant objects via the 0019 migration.**

Replaying globals restores role definitions only; the restored tables, views,
and sequences are all owned by whoever ran `pg_restore`. Migration 0019's
upgrade is what fixes that, and it is reached by downgrading below it and
coming back up. Step 2 is required even when step 1's globals replay succeeded.

Work through 2a to 2d **in that order**. The snapshot in 2b and the restore in
2d bracket the downgrade for a reason: `alembic downgrade 0016` passes through
0022, whose `downgrade()` drops `tenant_id` from `catalog.audit_logs` and
`catalog.ingest_jobs`, and the re-upgrade rebuilds those columns by reading
each row's live parent. A row whose parent is gone has nothing to derive from
— an audit row whose actor was deleted (`user_id` is NULL after
`ON DELETE SET NULL`), or an ingest job with neither `created_by` nor
`dataset_id` — so it comes back with a NULL tenant permanently unless the
columns were snapshotted first.

**2a. Restore the dump.** Use the privileged migrator
`DATABASE_URL_OVERRIDE` for every command in this step.

```bash
pg_restore --clean --if-exists --no-owner --no-acl \
  -d "$POSTGRES_DB" geolens_<timestamp>.dump
```

**2b. Snapshot tenant attribution, BEFORE the downgrade.** Skipping this is
the one irreversible mistake in the recipe: once 2c has run, the rows you
would have saved no longer carry a `tenant_id` to save.

```sql
CREATE TABLE public.recover_audit_tenant AS
  SELECT id, tenant_id FROM catalog.audit_logs WHERE tenant_id IS NOT NULL;
CREATE TABLE public.recover_job_tenant AS
  SELECT id, tenant_id FROM catalog.ingest_jobs WHERE tenant_id IS NOT NULL;
```

**2c. Rebuild the topology.**

```bash
uv run alembic downgrade 0016
uv run alembic upgrade head
```

**2d. Put the attribution back.** Scoped to the rows the re-upgrade could not
derive, which is also what keeps the parent-consistency triggers satisfied.

```sql
UPDATE catalog.audit_logs AS a SET tenant_id = r.tenant_id
  FROM public.recover_audit_tenant AS r
 WHERE r.id = a.id AND a.tenant_id IS NULL;
UPDATE catalog.ingest_jobs AS j SET tenant_id = r.tenant_id
  FROM public.recover_job_tenant AS r
 WHERE r.id = j.id AND j.tenant_id IS NULL;
DROP TABLE public.recover_audit_tenant, public.recover_job_tenant;
```

> **Known limitation.** The downgrade in 2c passes through migrations whose
> `downgrade()` rebuilds **global** uniqueness that the current schema scopes
> per tenant (0020: `datasets.table_name`; 0021: collection names and OAuth
> subjects). A valid multi-tenant dump in which two tenants reuse such a name
> makes `alembic downgrade 0016` refuse on data the current schema permits.
> That refusal is correct — forcing it would corrupt the restored data. There
> is currently no supported way to re-run 0019's adoption without the
> downgrade (0019 installs its functions with plain `CREATE FUNCTION`, so
> `alembic stamp 0018 && alembic upgrade 0019` collides with the functions the
> dump already carries), and a globals dump does not sidestep it either,
> because globals never carried object ownership. If you hit this refusal,
> stop rather than forcing it and route through `SUPPORT.md`; the
> reconstruction logic itself is `_adopt_and_backfill_existing_tenants` in
> `backend/alembic/versions/0019_tenant_provisioning_boundary.py`.

The 0019 re-upgrade is the whole per-tenant role-reconstruction step: it
recreates the fixed provisioner/control/writer/sandbox/tile roles, walks
`catalog.tenants` to recreate each tenant reader/writer role via
`provision_tenant_data_schema`, and transfers restored tenant tables and
sequences to the matching writer. No separate script exists or is needed
(fix(#950): an earlier revision of this recipe referenced a
`prepare-tenant-rls.py` script that was never shipped). Reapply the runtime
login grants from `.env.example` afterward; those login credentials are
deliberately not stored in the database dump. Verify that the API login can
`SET ROLE` to one tenant writer/reader, the tile login can set only that tenant
reader, and neither login owns catalog RLS tables or a `data_t_*` schema — the
backend re-checks the runtime login at boot
(`assert_multi_tenant_runtime_role`) and refuses to start on an unsafe role, so
a misconfigured restore fails loudly rather than serving cross-tenant data.

### Step-by-step: full restore (DB + object storage)

With the default backup service, dumps are written to the **`backup_data` named
volume** at `/backups/daily`, **not** to a host directory. `restore.sh` takes a
**host file path**, so first copy the chosen dump (and its paired
`staging-<timestamp>.tar.gz`) out of the volume, then restore from that copy.

```bash
# 0. Copy the chosen backup out of the backup_data volume to the host.
#    Replace <project> with your Compose project name (see `docker volume ls`;
#    the volume is <project>_backup_data) and the timestamp with the one you
#    picked from "Finding the dump to restore" below.
mkdir -p ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'cp /backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump /out/ && \
                cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/ 2>/dev/null; \
                ls -lh /out'

# 1. Restore the database from the extracted dump.
./scripts/restore.sh ./restore/geolens_<YYYYmmdd_HHMMSS>.dump

# 2. Restore the matching object-storage archive into the upload_staging volume.
#    This step is MANUAL — restore.sh prints the exact command from step 1 output.
#    Replace <project> with your Compose project name.
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/restore":/restore:ro \
  alpine sh -c 'cd /staging && tar xzf /restore/staging-<YYYYmmdd_HHMMSS>.tar.gz'
```

`restore.sh` auto-detects the sibling staging archive (matched by timestamp, in the
same directory as the dump — here `./restore`) and prints the `docker run` line
above with the real paths filled in. Copy the printed command from the restore
output rather than hand-editing it.

### Finding the dump to restore

```bash
# List available daily backups in the backup_data volume (newest first).
# Replace <project> with your Compose project name (see `docker volume ls`).
docker run --rm -v <project>_backup_data:/backups:ro alpine \
  ls -lt /backups/daily

# Validate a specific dump after copying it out of the volume (step 0 above).
# Omit the filename to read stdin — the literal `-` alias was never documented
# for pg_restore and PG 18 rejects it with `could not open input file "-"`,
# which reads like a corrupt backup when the dump is fine (chore(#704)).
docker compose exec -T db \
  pg_restore --list < ./restore/geolens_<YYYYmmdd_HHMMSS>.dump | head -20
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

The GeoLens backup container archives the local `upload_staging` volume as
`staging-<YYYYmmdd_HHMMSS>.tar.gz` inside the `backup_data` named volume. Copy it
out to the host, then extract:

```bash
# Replace <project> with your Compose project name (see `docker volume ls`).
mkdir -p ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/; ls -lh /out'

docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/restore":/restore:ro \
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

PITR is a **different mechanism**, not a finer setting on the bundled backup.
`pg_dump` produces a logical dump, which does not contain the information WAL
replay needs — so no schedule change gets you recovery to an arbitrary moment.
You either run physical backup plus continuous WAL archiving, or your recovery
point is the last completed dump.

**Managed databases (recommended):** providers offer native PITR — enable it in
the provider console (see provider links above). Nothing changes in GeoLens.

**Self-hosted Docker (advanced, unsupported):** requires `wal_level = replica`,
`archive_mode = on`, a working `archive_command`, and a durable archive
destination. `scripts/restore.sh` carries a configuration outline in its
trailing comments, but this is a hand-rolled path we do not test or support.

> **Understand the failure mode before enabling it.** If `archive_command`
> starts failing — unreachable destination, full disk, bad permissions —
> PostgreSQL retains WAL segments until `pg_wal` exhausts the filesystem, at
> which point **the database stops accepting writes**. Continuous archiving
> trades a bounded data-loss risk for an availability risk that needs
> monitoring and alerting on archiver health. Do not enable it on an unattended
> single-host deployment without that in place; a nightly dump fails far more
> gracefully.

For production WAL management, use a purpose-built tool
([pgBackRest](https://pgbackrest.org/), [Barman](https://pgbarman.org/), or
[WAL-G](https://github.com/wal-g/wal-g)) rather than a hand-written
`archive_command`. See the PostgreSQL manual on
[continuous archiving and PITR](https://www.postgresql.org/docs/18/continuous-archiving.html).

---

## 4. Monitoring

GeoLens exports Prometheus metrics out of the box. Reference scrape config, alert
rules, and a Grafana dashboard ship in [`infra/monitoring/`](infra/monitoring/) —
point your monitoring stack at them, or use them as a base for an existing one.

**Uptime/liveness checks must target `/api/health`** (JSON `status`, `version`,
`build`). Behind the bundled Nginx, a bare `/health` is not an API route — the
frontend SPA catch-all answers it with HTML `200`, which an uptime monitor will
happily (and wrongly) accept.

### Metrics & alerting (Prometheus / Grafana)

Metrics are exposed on **two separate endpoints** — the API and the worker each
run their own:

| Source | On the Compose network | Host mapping | Exports |
|---|---|---|---|
| API | `http://api:8000/metrics` | `127.0.0.1:8001/metrics` | HTTP request rate / latency / errors, DB connection-pool gauges, tile-cache hit/miss |
| Worker | `http://worker:8001/metrics` | internal-only | Procrastinate job-queue depth, active, completed, failed (per queue) |

`infra/monitoring/prometheus.yml` already defines both scrape jobs
(`geolens-api`, `geolens-worker`) and loads `alerts.yml` as a rule file. Run
Prometheus on the Compose network so the `api` / `worker` hostnames resolve:

```bash
docker run --rm -d --name geolens-prometheus \
  --network geolens_default \
  -p 127.0.0.1:9090:9090 \
  -v "$PWD/infra/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/infra/monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro" \
  prom/prometheus:v3.5.0   # or a newer pinned tag
```

Then import `infra/monitoring/grafana-dashboard.json` into Grafana
(**Dashboards → Import**) and select your Prometheus data source when prompted.

Already running Prometheus/Grafana elsewhere? Copy the `scrape_configs` jobs and
the `rule_files` entry into your own config and import the dashboard JSON — the
targets just need network reach to `api:8000` and `worker:8001`.

**Alert rules** (`infra/monitoring/alerts.yml`) — thresholds are tunable defaults:

| Alert | Fires when | Severity |
|---|---|---|
| `GeoLensTargetDown` | API or worker unscrapeable for >2m | critical |
| `GeoLensApiHigh5xxRate` | 5xx share of requests >5% over 5m | critical |
| `GeoLensApiInteractiveLatencyP95` | non-tile p95 at the 1s histogram ceiling for 10m | warning |
| `GeoLensApiTileLatencyMean` | mean `/tiles/*` latency >2s for 10m | warning |
| `GeoLensJobQueueBacklog` | any queue >100 jobs for 15m | warning |
| `GeoLensJobFailures` | >5 job failures in 15m | warning |
| `GeoLensDbPoolSaturated` | connection-pool overflow in use for >10m | warning |

> Under an external pooler (`DB_USE_EXTERNAL_POOLER=true` → SQLAlchemy `NullPool`),
> the `geolens_db_pool_*` gauges are not emitted and `GeoLensDbPoolSaturated`
> never fires — pool health is the provider's responsibility there.

### Backup service healthcheck

The `backup` service exposes a Docker **freshness** healthcheck:

```bash
docker compose ps backup    # Status column: healthy / unhealthy / starting
docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q backup)
```

`healthy` means a backup cycle **fully succeeded recently** — it is not a
liveness probe. The entrypoint touches `/backups/.last-success` only after
`pg_dump`, end-to-end verification (`pg_restore -f /dev/null`), the
object-storage staging archive (when the staging volume is mounted and
non-empty), and the S3 upload (when `BACKUP_S3_ENABLED=true`) all succeed. The healthcheck fails when
that marker is missing or older than `BACKUP_MAX_AGE_MINUTES` (default `1560`
minutes = 26 hours, the default daily schedule plus slack). A container whose
backups quietly stop succeeding therefore turns `unhealthy` roughly one missed
cycle later, and `docker compose ps` shows it — no monitoring stack required.

Tuning and edge behavior:

- **Non-daily schedule?** Set `BACKUP_MAX_AGE_MINUTES` in `.env` to ~1.5× your
  `BACKUP_SCHEDULE` interval (e.g. every 12 h → `1080`), then re-create the
  service: `docker compose up -d backup`.
- **First install / new volume:** no marker exists yet, so the service reports
  `starting` until the initial on-startup backup succeeds — seconds on a fresh
  database. If no backup succeeds within the 10-minute `start_period`, it turns
  `unhealthy` after three further failed probes (~90 s more).
- **Very large database:** an initial on-startup dump that outlasts
  `start_period` shows a transient `unhealthy`; it clears on the first probe
  after the cycle completes.
- An `unhealthy` backup service does not stop or restart anything — it is a
  signal. Read `docker compose logs backup` (log markers below) to find which
  step failed.

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
| `ERROR: S3 upload failed for <key>` | Offsite upload failed; cycle returns non-zero |
| `ERROR: object-storage archive failed — this cycle will be reported as failed` | Staging tar failed; the cycle fails and the service turns `unhealthy` at the next freshness probe |
| `ERROR: pg_dump failed` | DB dump failed; no artifacts written for this cycle |
| `ERROR: <filename> failed verification (pg_restore could not read it) — discarding the corrupt dump` | The new dump did not read back end-to-end; it was deleted and the cycle failed |
| `ERROR: BACKUP_RETENTION_DAILY='...' must be >= 1` (or `..._WEEKLY`, or the `is not a plain integer` variant) | The entrypoint refused to start: retention must be an integer of at least 1, because a retention of 0 would delete each backup the moment it is written |

Every explicitly handled failure path logs an `ERROR:` marker, so one grep
catches those:

```bash
docker compose logs backup | grep 'ERROR:'
```

A few raw tool failures are not wrapped (for example the weekly `cp` copies in
the entrypoint) and surface only as the tool's own stderr, with no `ERROR:`
marker. When a backup looks wrong but the grep comes back quiet, read the
unfiltered `docker compose logs backup`.

A backup container that exits immediately at startup (`docker compose ps backup`
shows it restarting) with the `must be >= 1` line has a retention
misconfiguration: fix `BACKUP_RETENTION_DAILY` / `BACKUP_RETENTION_WEEKLY` in
`.env` and run `docker compose up -d backup`.

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
docker compose logs backup | grep 'ERROR: S3 upload failed'
```

A failed S3 upload causes the backup cycle to exit non-zero (visible as an
`ERROR: backup S3 upload failed` log line). Investigate S3 credentials and
endpoint reachability before the next scheduled run.

### PostgreSQL server logs

`docker compose logs db` shows **nothing** by design: the shipped
`db/postgresql.conf` sets `logging_collector = on`, which routes all PostgreSQL
output — slow-query lines (`log_min_duration_statement = 1000`), `auto_explain`
plans, checkpoint activity — into daily-rotated files inside the pgdata volume.
Read them with:

```bash
docker compose exec db sh -c 'ls -t "$PGDATA/log/"'
docker compose exec db sh -c 'tail -100 "$PGDATA/log/$(ls -t "$PGDATA/log/" | head -1)"'
```

An empty `docker compose logs db` does **not** mean there are no slow queries —
always check the collector files.

---

## 5. Incident response — data loss

Follow this ordered procedure to recover from data loss.

### 1. Assess scope

Determine what was lost:
- Is the database intact? (`docker compose exec db psql -U geolens -c '\l'`)
- Are uploaded source files (in `upload_staging`) missing?
- What is the latest backup timestamp? (`docker compose exec backup sh -c 'ls -lt /backups/daily/*.dump' | head -5`)

### 2. Select the newest valid dump

```bash
# List all daily dumps in the backup_data volume, newest first
docker compose exec backup sh -c 'ls -lt /backups/daily/*.dump'

# Copy the chosen dump (and its paired staging archive) out of the volume.
# Replace <project> with your Compose project name (see `docker volume ls`).
mkdir -p ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'cp /backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump /out/ && \
                cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/ 2>/dev/null; ls -lh /out'

# Validate the candidate dump before restoring. Omit the filename to read
# stdin: PG 18 rejects the literal `-` with `could not open input file "-"`,
# which reads like a corrupt backup when the dump is fine (chore(#704)).
# `-f /dev/null` reads every data block; `--list` alone would pass a dump
# truncated after its table of contents.
docker compose exec -T db \
  pg_restore -f /dev/null < ./restore/geolens_<YYYYmmdd_HHMMSS>.dump \
  && echo "candidate dump reads end-to-end"
```

If the daily dump is corrupt, fall back to a weekly backup under
`/backups/weekly/`, or to a pre-upgrade dump under `backups/pre-upgrade/`.

### 3. Restore the database

**Bundled Postgres:** (restore from the copy extracted in step 2 above)

```bash
./scripts/restore.sh ./restore/geolens_<YYYYmmdd_HHMMSS>.dump
```

**Managed / external Postgres:** restore via the provider snapshot or PITR — see
[§3](#3-restore--managed--external-postgres-mode).

### 4. Restore object storage

Extract the matching staging archive (copy the `docker run` command printed by
`restore.sh`, or construct it from the timestamp):

```bash
docker run --rm \
  -v <project>_upload_staging:/staging \
  -v "$(pwd)/restore":/restore:ro \
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

---

## 6. Major PostgreSQL version upgrade (17 → 18)

GeoLens moved its bundled database image from PostgreSQL 17 + PostGIS 3.5 to
PostgreSQL 18 + PostGIS 3.6. **A PG 17 `pgdata` volume cannot be opened by a
PG 18 server** — the `db` container will refuse to start against the old
volume ("database files are incompatible with server"). Plan a maintenance
window; downtime is roughly proportional to database size (dump + restore).

The supported path for the bundled `db` container is **dump → fresh volume →
restore**, using the same shipped tooling as disaster recovery (section 2).
`pg_upgrade` is not practical here because the bundled image ships only one
set of server binaries.

### Bundled Postgres mode (default Compose deployment)

```bash
# 0. Quiesce the app's DB writers before dumping. pg_dump snapshots the moment
#    it BEGINS and does not block writers, so a write acknowledged after it
#    starts would be missing from the rollback dump. db stays up — the dump
#    needs it.
docker compose stop api worker

# 1. Take the pre-upgrade dump straight to the HOST, then verify it reads back
#    end-to-end. Streaming via `exec -T` (same technique as scripts/upgrade.sh)
#    lands it outside the container, so there is no volume copy to make later
#    and no <project> volume name to look up.
#
#    NOT into /backups/daily: that directory is under retention. An extra file
#    there occupies a retention slot, so the next `prune_old_backups` pass —
#    which keeps BACKUP_RETENTION_DAILY (7) `*.dump` files by mtime — deletes
#    one more generation of real history than it otherwise would. ./backups/
#    is gitignored and `backups/pre-upgrade/` is where scripts/upgrade.sh
#    already puts its rollback dump.
#
#    `-f /dev/null` to verify, NOT `ls -l` and NOT `--list`: a truncated archive
#    looks fine to `ls` and still passes `--list`, because the -Fc table of
#    contents sits at the front. Read every data block now, while the old
#    cluster is still there to re-dump from.
#    The connection variables are read INSIDE the backup container (they are
#    set there); `-T` is required so Docker does not allocate a TTY and corrupt
#    the binary stream.
#
#    Dump to `.partial` and rename only after the read-back succeeds, so the
#    final filename exists if and only if a verified dump exists. Step 2 gates
#    on exactly that.
#
#    The name carries a timestamp and this attempt's file is remembered in
#    $DUMP, so a retry NEVER deletes or overwrites an earlier verified dump.
#    That matters most in the worst case: if you got past step 2 and something
#    later failed, the PG 17 volume is already gone and that earlier dump is
#    the only copy of your data left. A fixed filename would have it deleted
#    at the top of the retry — and then, because the fresh PG 18 cluster is up
#    and answering, the re-dump SUCCEEDS, verifies, and step 2 destroys the
#    volume again. You would end up with a perfectly valid dump of an empty
#    database and nothing else.
#
#    $DUMP also scopes the gate to THIS attempt, so an older verified dump
#    cannot green-light step 2 after a re-dump fails.
mkdir -p ./backups/pre-upgrade
DUMP="./backups/pre-upgrade/pre_pg18_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T backup sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$DUMP.partial" \
  && docker compose exec -T backup pg_restore -f /dev/null < "$DUMP.partial" \
  && mv "$DUMP.partial" "$DUMP" \
  && echo "pre-upgrade dump verified: $DUMP"

# 2. Stop the stack and remove ONLY the database volume.
#
#    Gated on step 1's verified dump, and chained with `&&`, because this block
#    is meant to be pasted: a failed pg_dump (disk full, version mismatch, a
#    typo'd volume name) otherwise only suppresses step 1's echo, and the shell
#    runs straight on into `docker volume rm`. Past that point there is no dump
#    and no cluster. If the guard stops you here, the PG 17 volume is still
#    intact — fix the dump and re-run step 1.
#
#    $DUMP is deliberately required, not just any file in the directory: in a
#    NEW shell it is unset and this refuses to run. That is the safe answer —
#    re-run step 1 so the dump you are about to bet the cluster on is one you
#    just verified, in this session, against the cluster still standing.
test -n "${DUMP:-}" && test -f "$DUMP" \
  && docker compose down \
  && docker volume rm <project>_pgdata

# 3. Pull/build the new images and start the WHOLE stack once — a fresh PG 18
#    cluster initializes (scripts/init-db.sh provisions extensions + base
#    roles), then the migrate service applies all migrations. This step is
#    REQUIRED before the restore: migrations create the app roles (e.g.
#    geolens_readonly) that the dump's GRANT statements reference — restoring
#    onto an unmigrated cluster spews "role ... does not exist" errors.
docker compose pull   # or: docker compose build, if you build locally.
                      # Rebuild EVERYTHING, not just db: the backup image's
                      # pg_dump major must match the new server, or every
                      # backup cycle fails with "server version mismatch".
#    `--scale backup=0` keeps the backup service DOWN for this step. It runs an
#    initial dump the moment it starts, so starting it here would capture the
#    freshly migrated but still EMPTY cluster, write it to /backups/daily as the
#    newest dump, and prune one real generation to stay inside
#    BACKUP_RETENTION_DAILY (7). Every retry of steps 2-3 would replace another
#    generation of real history with an empty-cluster dump — and section 5 tells
#    an incident responder to restore the newest dump, which would then be the
#    empty one. Nothing depends_on backup, so scaling it to 0 is safe.
docker compose up -d --wait --scale backup=0

# 4. Restore the dump (canonical entry point: validates the file, stops
#    api/worker, restores over the freshly migrated schema via
#    --clean --if-exists, and restarts api/worker when done).
#    If the shell that ran step 1 is gone, $DUMP is unset — pick the newest
#    verified dump explicitly:
#      ls -t ./backups/pre-upgrade/*.dump | head -1
./scripts/restore.sh "$DUMP"

# 5. Bring the backup service up now that the cluster holds real data, and
#    verify.
#
#    If --wait exits non-zero here, check `docker compose ps` before treating
#    the upgrade as failed: a service shown as `health: starting` is still
#    inside its declared start_period, and Docker has not judged it yet — the
#    backup service allows 10 minutes for its first dump, and dumping a large
#    freshly restored database can outlast even that, showing a transient
#    unhealthy that clears on the first probe after the cycle completes.
#    Respect the start_period before declaring failure (scripts/upgrade.sh's
#    wait_for_healthy applies the same rule); only a service that stays
#    (unhealthy), keeps restarting, or exited non-zero has actually failed.
docker compose up -d --wait
docker compose exec db psql -U geolens -c 'select version();'
curl -fsS http://localhost:8080/api/health
```

Deployments with tenant isolation enabled: after the fresh-cluster restore,
rebuild the tenant data-plane roles exactly as documented in the
role-reconstruction subsection of section 2 before starting API, worker, or
tile traffic.

### Managed / external Postgres mode

Use your provider's managed major-version upgrade (all managed providers
support in-place PG 17 → 18), then start the new GeoLens release and let the
`migrate` service run as usual. GeoLens requires the `postgis`, `pg_trgm`,
`unaccent`, and `vector` extensions to remain installed after the engine
upgrade — most providers carry extensions across, but verify with
`\dx` before starting the stack.

### Rollback

The pre-upgrade dump restores onto a PG 17 stack the same way (step 2-5 with
the previous image tags). A dump taken FROM PG 18 does NOT restore onto 17 —
keep the pre-upgrade dump until you are satisfied with the upgrade.

Pre-upgrade dumps are timestamped and accumulate in `./backups/pre-upgrade/`;
nothing prunes that directory, deliberately, so a retry can never destroy the
copy an earlier attempt verified. Delete them by hand once the upgrade has
been accepted.
