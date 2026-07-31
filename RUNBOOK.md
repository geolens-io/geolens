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
7. [Schema rollback](#7-schema-rollback)

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

Each cycle produces three paired artifacts with matching timestamps:

| Artifact | Format | What it contains |
|---|---|---|
| `<db>_<YYYYmmdd_HHMMSS>.dump` | `pg_dump -Fc` custom-format | Full database (schema + data), restorable via `pg_restore` |
| `staging-<YYYYmmdd_HHMMSS>.tar.gz` | tar.gz | Contents of the `upload_staging` volume (source files, rasters, COGs) |
| `globals-<YYYYmmdd_HHMMSS>.sql` | `pg_dumpall --globals-only` plain SQL | Cluster roles, their passwords, and cluster-wide grants |

The staging archive is omitted silently when the `upload_staging` volume is absent
or empty (fresh install with no uploaded datasets).

The globals dump is the piece a database-only `pg_dump` can never give back, and
it is what makes the fresh-cluster role reconstruction in [§ 2](#2-restore--bundled-postgres-mode)
work. It contains **role password verifiers**, so it is written mode `0600` and
must keep the same protection as the dump itself wherever it is copied. A
`pg_dumpall` failure fails the whole cycle: a backup set that cannot restore its
roles should not be reported as a good one.

### Retention

Artifacts land at:
- Daily: `backup_data` volume → `/backups/daily/`
- Weekly (every Sunday): `backup_data` volume → `/backups/weekly/`

Default retention: 7 daily, 4 weekly (set `BACKUP_RETENTION_DAILY` /
`BACKUP_RETENTION_WEEKLY` in `.env` to override). The count applies to the
`.dump` files, ordered by the timestamp in the filename; the paired
`staging-*.tar.gz` and `globals-*.sql` artifacts are pruned when the dump they
belong with ages out. Retention therefore evicts whole backup sets, and a
companion artifact never outlives its dump — which matters because a cycle can
produce a dump without a companion (an empty staging volume, or a failed
`pg_dumpall`), and counting each kind separately would prune complete sets while
leaving orphans behind.

One exception: the **newest complete set** — a dump that still has its globals
dump — is held back on top of the window, so a directory can hold `keep` + 1
dumps. A run of `pg_dumpall` failures still produces valid database dumps each
cycle, and without the exemption those would walk the last restorable-onto-a-
fresh-cluster set out of retention while the healthcheck was already reporting
the problem. The cost is one extra dump plus a few KB of SQL.

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
2. Reports any sibling `globals-<timestamp>.sql`, naming the roles it defines
   that the target cluster is missing. This happens **before** anything
   destructive, because replaying globals is a pre-restore step. It is a
   warning, not a gate: a same-cluster restore already has its roles.
3. Creates required extensions and schemas in the database.
4. Stops `api` and `worker` to prevent write conflicts.
5. Runs `pg_restore --clean --if-exists --no-owner` against the bundled `db` container.
6. Re-applies the `geolens_reader` grants on schema `data` and asserts they took
   (`has_schema_privilege`). `--clean` drops the schema together with its ACLs
   and default privileges, and the dump carries no ACLs (`--no-acl`), so the
   grants must be rebuilt after every restore.
7. Restarts `api` and `worker` on exit (including on failure — via a trap).
8. Runs a post-restore row-count check (`catalog.records`, `catalog.datasets`).
9. Auto-detects any sibling `staging-<timestamp>.tar.gz` next to the dump and
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

Use the `globals-<timestamp>.sql` artifact that the backup cycle wrote next to
the dump you are restoring. It is captured automatically, from the source
cluster, at the moment of the dump — matching timestamps mean the roles and the
data belong to the same point in time.

Like the dump, it lives inside the `backup_data` volume, so copy it to the host
first (step 0 of [full restore](#step-by-step-full-restore-db--object-storage)
extracts all three artifacts together), then replay it **before** `pg_restore`:

```bash
# Load .env so $POSTGRES_USER / $POSTGRES_DB are set in this shell.
set -a; . ./.env; set +a

# On the new cluster, BEFORE pg_restore. Substitute the timestamp of the dump
# you are restoring; ./restore is where step 0 put the extracted artifacts.
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres \
  < ./restore/globals-<YYYYmmdd_HHMMSS>.sql
```

If the source cluster is still reachable and you would rather capture roles as
of now than as of the dump, take a fresh globals dump instead:

```bash
# umask 077 because --globals-only emits role password verifiers: under a
# default 022 umask this file lands world-readable. Store it with the same
# protection as the dump itself, or add --no-role-passwords and reset the login
# passwords during recovery instead.
(umask 077; docker compose exec -T db \
  pg_dumpall --globals-only -U "$POSTGRES_USER" > globals.sql)
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

**Step 2 — re-own the restored tenant objects. Last resort; read this first.**

Replaying globals restores role definitions only; the restored tables, views,
and sequences are all owned by whoever ran `pg_restore`. Migration 0019's
upgrade is what fixes that, and the only way to reach it is to downgrade below
0019 and come back up.

> **That downgrade is not a supported recovery path.** It walks back through
> every migration between head and 0019, and several of them either refuse on
> data the current schema fully supports or discard state the re-upgrade
> cannot rebuild. As of 0030 the known list is:
>
> | Migration | What its `downgrade()` does |
> |---|---|
> | 0030 | **Refuses** while any `catalog.records` row holds a MULTIPOLYGON `spatial_extent` — i.e. any antimeridian-crossing footprint, which the current schema exists to store |
> | 0029 | **Refuses** while any API key carries an expiry or any user's `key_epoch` has been bumped. Dropping `api_keys.expires_at` and both `key_epoch` columns would turn time-limited keys into permanent ones and un-revoke keys a `key_epoch` bump had invalidated; the error message lists the affected keys and the SQL that revokes them |
> | 0027 | **Refuses** while any dataset uses a `parquet`, `json`, `xlsx`, or `xls` source format — all currently supported |
> | 0022 | **Discards** `tenant_id` on `catalog.audit_logs` and `catalog.ingest_jobs`. The re-upgrade re-derives it from each row's live parent, so rows whose parent is gone lose tenant attribution permanently |
> | 0021, 0020 | **Refuse** when two tenants share a collection name, OAuth subject, or `datasets.table_name` — all legal under the current per-tenant scoping |
>
> The refusals are correct: forcing them would corrupt the restored data.
> Taken together they mean this path is unusable or lossy for most real
> multi-tenant databases, and there is currently no supported way to re-run
> 0019's adoption without it (0019 installs its functions with plain
> `CREATE FUNCTION`, so `alembic stamp 0018 && alembic upgrade 0019` collides
> with the functions the restored dump already carries).
>
> **So: do not treat this as routine.** Open a support issue (`SUPPORT.md`)
> before running it on data you care about.
>
> Be clear about what the alternatives do and do not buy you. A globals dump
> and a same-cluster restore both remove the *role* half of the problem —
> globals replays the role definitions onto a new cluster, and on the same
> cluster they never left. Neither touches the *ownership* half. The archive
> carries no owner or ACL metadata, `--clean` drops each schema together with
> its ACLs and default privileges, and `scripts/restore.sh` restores
> `--no-owner` and re-grants only the single-tenant `geolens_reader`
> privileges on schema `data`. Once per-tenant roles are in play, every
> restore therefore lands tenant relations owned by `$POSTGRES_USER` with no
> per-tenant grants, and step 2 is the only shipped way to fix that. Removing
> that dependency is
> the product gap this section is really describing — keep a globals dump
> regardless, because it is the half you *can* solve today.

If you have read the above and are proceeding anyway, work through 2a to 2d
**in that order**. The snapshot in 2b and the restore in 2d bracket the
downgrade because of 0022, and cover only that one row of the table — the
other losses above have no equivalent remediation here.

Everything below runs through the Compose containers, because the bundled
database listens on `127.0.0.1:${DB_PORT}` rather than a host socket and the
Alembic config lives in `backend/`, not the repo root. Do **not** use
`scripts/restore.sh` here — it restarts `api` and `worker` on exit, and the
whole point of this section is that nothing may serve traffic until step 2d.
Managed/external Postgres: drop the `docker compose exec -T db` prefix and
pass the provider's `-h`, `-p`, and `-U` instead.

Keep `.env` loaded in this shell (`set -a; . ./.env; set +a`, as in step 1) —
`$POSTGRES_USER` and `$POSTGRES_DB` expand on the host, not in the container.
The dump path is a host path; copy the dump out of the `backup_data` volume
first, exactly as in "Step-by-step: full restore" below.

**2a. Restore the dump.**

```bash
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-acl < ./restore/geolens_<timestamp>.dump
```

**2b. Snapshot tenant attribution, BEFORE the downgrade.** Skipping this is
the one irreversible mistake in the recipe: once 2c has run, the rows you
would have saved no longer carry a `tenant_id` to save.

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE TABLE public.recover_audit_tenant AS
  SELECT id, tenant_id FROM catalog.audit_logs WHERE tenant_id IS NOT NULL;
CREATE TABLE public.recover_job_tenant AS
  SELECT id, tenant_id FROM catalog.ingest_jobs WHERE tenant_id IS NOT NULL;
SQL
```

**2c. Rebuild the topology.** Run these against the **`migrate`** service with
`--no-deps`, not against `api`. Both parts matter: `api`'s entrypoint runs
`alembic upgrade heads` of its own accord before it would execute your command
(`backend/scripts/api-entrypoint.sh`), and `api` declares
`depends_on: migrate`, so without `--no-deps` Compose starts the `migrate`
one-shot — with `.env`'s runtime credential rather than your override — and
upgrades the schema before the downgrade ever runs. The `migrate` service has
`entrypoint: []` and depends only on a healthy `db`, so it does exactly what
you ask and nothing else.

```bash
docker compose run --rm --no-deps -e DATABASE_URL_OVERRIDE="<migrator-url>" \
  migrate sh -c "uv run --no-dev alembic downgrade 0016"
docker compose run --rm --no-deps -e DATABASE_URL_OVERRIDE="<migrator-url>" \
  migrate sh -c "uv run --no-dev alembic upgrade heads"
```

The migrator credential is required: the least-privilege runtime login in
`.env` is deliberately not allowed to do any of this.

**2d. Put the attribution back.** Scoped to the rows the re-upgrade could not
derive, which is also what keeps the parent-consistency triggers satisfied.

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
UPDATE catalog.audit_logs AS a SET tenant_id = r.tenant_id
  FROM public.recover_audit_tenant AS r
 WHERE r.id = a.id AND a.tenant_id IS NULL;
UPDATE catalog.ingest_jobs AS j SET tenant_id = r.tenant_id
  FROM public.recover_job_tenant AS r
 WHERE r.id = j.id AND j.tenant_id IS NULL;
DROP TABLE public.recover_audit_tenant, public.recover_job_tenant;
SQL
```

**If 2c refuses, the database it refused in is not salvageable — start over
from the dump.** A failed downgrade does not roll back the ones that already
succeeded. Several of these migrations do index work inside Alembic's
`autocommit_block()` (0020, 0021, 0022 among them), which commits the DDL
preceding it, so a refusal at 0021 leaves you past 0022's discards with no
transaction to undo them. Drop and recreate the target database, then
re-run 2a and 2b against the untouched dump before attempting anything else.

0029 is the one place where the order works in your favour: walking back from
head it is reached second, before any of the discarding migrations, so its
refusal stops the run while the database is still whole. Deal with its
remediation there rather than discovering the loss after a refusal further
down (fix(#1016) — it used to drop those columns silently).
The dump file itself is never modified, so nothing is lost by restarting — but
continuing in a half-downgraded database is how a recovery turns into a second
incident.

Do not force a refusal past its guard. Those migrations are protecting data
the current schema legitimately holds, and the remediations their error
messages offer — widening seam extents to `-180..180`, remapping source
formats — are themselves lossy. The reconstruction logic 2c is trying to reach
is `_adopt_and_backfill_existing_tenants` in
`backend/alembic/versions/0019_tenant_provisioning_boundary.py`; making it
runnable without the downgrade is a product gap, not something to work around
by hand here.

When 2c does complete, its 0019 re-upgrade is the whole per-tenant
role-reconstruction step: it recreates the fixed
provisioner/control/writer/sandbox/tile roles, walks
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
**host file path**, so first copy the chosen dump and its two paired artifacts
(`staging-<timestamp>.tar.gz`, `globals-<timestamp>.sql`) out of the volume,
then restore from that copy. Copying all three keeps them siblings on the host,
which is how `restore.sh` finds them.

```bash
# 0. Copy the chosen backup out of the backup_data volume to the host.
#    Replace <project> with your Compose project name (see `docker volume ls`;
#    the volume is <project>_backup_data) and the timestamp with the one you
#    picked from "Finding the dump to restore" below.
#    umask 077: the globals file holds role password verifiers, so the copy
#    must not be readable by other users on the host either.
mkdir -p ./restore && chmod 700 ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'umask 077; \
                cp /backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump /out/ && \
                cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/ 2>/dev/null; \
                cp /backups/daily/globals-<YYYYmmdd_HHMMSS>.sql /out/ 2>/dev/null; \
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

`restore.sh` auto-detects both siblings (matched by timestamp, in the same
directory as the dump — here `./restore`). For the staging archive it prints the
`docker run` line above with the real paths filled in; copy the printed command
from the restore output rather than hand-editing it. For the globals dump it
reports, **before** anything destructive runs, which roles the target cluster is
missing — replay it first if that list is non-empty, following the role
reconstruction procedure earlier in this section.

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

### Database temp-file ceiling (`temp_file_limit`)

The bundled Postgres config sets `temp_file_limit = 4GB` (`db/postgresql.conf`).
Temporary spill files (`pgsql_tmp`) live on the same volume as the database
itself, so an unbounded spill from a single runaway query — typically a large
analysis dissolve or buffer — could fill the data volume and stop the whole
cluster. The ceiling is a deliberate guard that converts that outage into one
failed query.

If you see this in the database logs or as a query error:

```
ERROR:  temporary file size exceeds "temp_file_limit" (4194304kB)
```

(SQLSTATE `53400`) — the guard worked as designed. The cluster keeps serving;
only the offending session failed. Two responses:

- **Filter the dataset**: the query genuinely needed more than 4GB of temp
  spill, which usually means the analysis input should be narrowed (smaller
  area of interest, fewer features) before rerunning.
- **Raise the ceiling**: if the disk has the headroom and the workload is
  legitimate, increase `temp_file_limit` in `db/postgresql.conf`, then
  **recreate** the db container:

  ```bash
  docker compose up -d --force-recreate --wait db
  ```

  Recreate, not `restart` and not `pg_reload_conf()`. `db/postgresql.conf` is
  bind-mounted as a single file, and most editors save by writing a new file
  and renaming it over the old one; the running container keeps resolving the
  inode it started with, so a reload re-reads the *old* contents and the
  change appears to do nothing. Recreating re-resolves the mount. (If you
  edited in place — `sed -i` does not qualify, it renames too — a reload is
  enough, from inside the container where Compose has already set the
  credentials; single quotes on purpose, so the variables expand in the
  container shell rather than on the host, where `.env` values are not
  exported.)

  ```bash
  docker compose exec db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_reload_conf();"'
  ```

  Verify either way with `SHOW temp_file_limit;`.

  `scripts/upgrade.sh` syncs `db/postgresql.conf` from the target release and
  recreates the db container when it changed, but only while the file still
  matches the release you are upgrading *from*. The comparison is on file
  contents, not on `git status`, so tuning you committed or staged counts as
  tuning: a customised config is never overwritten. The upgrade warns and
  leaves your version in place, so re-check it against the release after any
  upgrade that mentions a Postgres setting.

  Two cases where the upgrade will not do it for you, both needing the
  recreate command above by hand. The upgrader excludes itself from the
  release-file sync so it is never swapped under itself mid-run, so an install
  still running an upgrader from before this behaviour shipped skips the
  config sync entirely; it picks it up on the following upgrade. And a
  customised file is left alone by design. Either way, `SHOW
  temp_file_limit;` after an upgrade tells you whether the running cluster has
  the release's value.

  The limit is enforced **per process**, not per query: every session
  spilling at once gets the full ceiling, and a parallel query spills from
  each worker process separately (`max_parallel_workers_per_gather = 1` in
  the bundled config, so budget up to 2 processes per query). Size the
  ceiling against available disk headroom divided by the peak number of
  spilling processes — concurrent spill-heavy sessions times (1 + parallel
  workers per gather) — not against one query in isolation. In practice the
  per-user materialize cap keeps analysis at one CTAS per user at a time, so
  the session count to budget for is the number of simultaneously active
  analysis users plus any ad-hoc sessions.

`log_temp_files = 64MB` logs every spill above 64MB, so temp-file pressure is
visible in the database logs before it reaches the ceiling — a rising number of
`temporary file:` log lines is the early-warning signal.

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

# Copy the chosen dump and BOTH its paired artifacts out of the volume — the
# globals dump included, or a fresh-cluster restore has no roles to replay and
# restore.sh cannot report which ones are missing.
# Replace <project> with your Compose project name (see `docker volume ls`).
# umask 077: globals-*.sql holds role password verifiers.
mkdir -p ./restore && chmod 700 ./restore
docker run --rm \
  -v <project>_backup_data:/backups:ro \
  -v "$(pwd)/restore":/out \
  alpine sh -c 'umask 077; \
                cp /backups/daily/geolens_<YYYYmmdd_HHMMSS>.dump /out/ && \
                cp /backups/daily/staging-<YYYYmmdd_HHMMSS>.tar.gz /out/ 2>/dev/null; \
                cp /backups/daily/globals-<YYYYmmdd_HHMMSS>.sql /out/ 2>/dev/null; \
                ls -lh /out'

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

---

## 7. Schema rollback

Rolling the schema back (`alembic downgrade`) is rare — the supported
recovery paths are restore-from-backup (§2/§3) and the upgrade rollback
quick-reference in UPGRADING.md. When you do downgrade, several migrations
refuse by design rather than discard state the re-upgrade cannot rebuild. The
two you are most likely to meet are documented in full below.

### Downgrading past `0030_records_spatial_extent_type` fails when antimeridian-crossing extents exist

Migration 0030 widened `catalog.records.spatial_extent` so a dataset footprint
that crosses the antimeridian (e.g. Fiji) is stored as a two-ring
MULTIPOLYGON instead of a globe-spanning `-180..180` box (the accompanying
CHECK constraint is `chk_records_spatial_extent_type`, allowing POLYGON or
MULTIPOLYGON). Its `downgrade()` **refuses rather than coerces**: if any
record holds a MULTIPOLYGON extent, the downgrade raises and leaves the
column alone. That refusal is data protection, not a broken migration — the
only POLYGON that contains a two-ring seam extent is `-180..180`, which would
silently re-register exactly the globe-spanning extent the migration exists
to eliminate.

Mid-rollback this surfaces as a `RuntimeError` from a failed
`alembic downgrade`, quoting the two statements below. Inspect the affected
records:

```sql
SELECT id, title, ST_AsText(spatial_extent) FROM catalog.records WHERE GeometryType(spatial_extent) = 'MULTIPOLYGON';
```

If proceeding is worth the loss, run the remediation and re-run the
downgrade:

```sql
UPDATE catalog.records SET spatial_extent = ST_Envelope(spatial_extent) WHERE GeometryType(spatial_extent) = 'MULTIPOLYGON';
```

**What is actually lost:** the remediation collapses **every** MULTIPOLYGON
extent, not only seam-crossing ones. Each affected record's extent widens to
its single-ring envelope: for a seam-crossing shape that envelope is the full
`-180..180` longitude span, so Pacific datasets go back to reporting a global
footprint in the catalog, OGC/STAC bboxes, and search-by-extent; a
non-crossing multipart extent loses its part structure and reports the
bounding box around all parts. Both persist until the schema is upgraded
again and the extents recomputed.

### Downgrading past `0029_api_key_hardening` fails when API keys carry expiry or revocation state

Migration 0029 added `api_keys.expires_at` (optional key expiry) and the
`key_epoch` pair that makes an epoch bump revoke previously minted keys. Its
`downgrade()` **refuses** rather than dropping them, because dropping them
fails in the unsafe direction: with no expiry column an already-expired key
resolves as a permanent one, and with no `key_epoch` pair a key revoked by an
epoch bump resolves again. Nothing errors when that happens — the schema is
valid and the deployment is quietly less secure than it looks.

It refuses when any `catalog.api_keys` row has a non-null `expires_at`, or any
`catalog.users` row has `key_epoch > 1`. The error message carries the counts
and the query below. List the keys that would come back live:

```sql
SELECT ak.id, ak.user_id, ak.expires_at, ak.key_epoch, u.key_epoch AS owner_epoch
FROM catalog.api_keys ak
JOIN catalog.users u ON u.id = ak.user_id
WHERE ak.expires_at IS NOT NULL OR ak.key_epoch <> u.key_epoch;
```

Revoking them is almost always what you want, rather than accepting their
resurrection. That, plus clearing the epoch state, lets the downgrade proceed:

```sql
DELETE FROM catalog.api_keys ak USING catalog.users u
WHERE ak.user_id = u.id
  AND (ak.expires_at IS NOT NULL OR ak.key_epoch <> u.key_epoch);
UPDATE catalog.users SET key_epoch = 1;
```

**What is actually lost:** the deleted keys, permanently. Their owners must
mint new ones, which is the correct outcome — an expired or revoked key should
not survive a schema rollback. What you avoid is the alternative, where those
same keys keep working and nobody is told.

Two further migrations refuse on downgrade for the same reason (blocking data
exists that the older schema cannot represent safely): `0010` while GitHub
OAuth providers exist, and `0005` while tenant-scoped data exists. Both print
their own remediation in the error message; neither is auto-coerced.
