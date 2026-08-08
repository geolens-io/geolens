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
8. [Audit log retention](#8-audit-log-retention)
9. [Uploaded source-file retention](#9-uploaded-source-file-retention)

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

### Abandoned multipart uploads (bucket hygiene)

A client that starts a presigned multipart upload and walks away — never
completing, never aborting — leaves uploaded parts consuming bucket storage
indefinitely. Until `CompleteMultipartUpload` runs, no object exists at the
target key, so the application's staging sweeps cannot see the parts (they
enumerate objects), and the app itself only aborts an upload on an explicit
failed or empty completion. Cleaning these up is a bucket-level job.

Recommended policy: **abort incomplete multipart uploads after 1 day.**
That is sized for the default upload-job lifetime: `PENDING_JOB_TIMEOUT_SECONDS`
(default 3600 = 1h) bounds both how long a pending job stays alive and how
long its presigned part URLs remain valid, so with defaults nothing
legitimate is still uploading a day after initiation.

> **Coupling.** The abort deadline must stay at or above the configured
> upload lifetime plus headroom — that means both the AWS rule's
> `DaysAfterInitiation` and the MinIO expiry below. If you raise
> `PENDING_JOB_TIMEOUT_SECONDS` past ~23h (it accepts up to 7 days), raise
> them to match, or the bucket aborts parts of uploads that are still
> legitimately in flight.

**AWS S3** — apply an `AbortIncompleteMultipartUpload` lifecycle rule:

```bash
# WARNING: put-bucket-lifecycle-configuration REPLACES the bucket's entire
# lifecycle configuration. If the bucket already has rules, fetch them first
# and add this rule to the existing "Rules" list:
#   aws s3api get-bucket-lifecycle-configuration --bucket <your-bucket>
aws s3api put-bucket-lifecycle-configuration --bucket <your-bucket> \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "abort-abandoned-multipart-uploads",
        "Status": "Enabled",
        "Filter": {},
        "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
      }
    ]
  }'
```

**MinIO** — do NOT reach for `mc ilm` here. The `mc ilm rule add` command has
no abort-incomplete-multipart flag (verified against the `mc` release pinned
in `docker-compose.yml`, `RELEASE.2025-08-13T08-35-41Z`), and MinIO strips
`AbortIncompleteMultipartUpload` from lifecycle JSON supplied via
`mc ilm rule import` — the import reports success and the rule silently
disappears ([minio/minio#19115](https://github.com/minio/minio/issues/19115),
closed "working as intended"). MinIO's equivalent is the server-side
stale-uploads sweep in the `api` config subsystem: uploads idle past
`stale_uploads_expiry` (default `24h`) are aborted by a sweep that runs every
`stale_uploads_cleanup_interval` (default `6h`).

The bundled Compose files set both on the `minio` service with defaults of
`MINIO_API_STALE_UPLOADS_EXPIRY=24h` and
`MINIO_API_STALE_UPLOADS_CLEANUP_INTERVAL=6h`, so a cloud-dev or
self-hosted MinIO from this repo already aborts abandoned uploads after a
day. Both are overridable from `.env` (see `.env.example`); the expiry is
the knob to raise when `PENDING_JOB_TIMEOUT_SECONDS` exceeds ~23h, per the
coupling note above. For a MinIO you manage yourself:

```bash
mc admin config set <alias> api stale_uploads_expiry=24h stale_uploads_cleanup_interval=6h
# Verify (environment variables take precedence over config set):
mc admin config get <alias> api
```

---

## 2. Restore — bundled Postgres mode

Use this path when Postgres runs in the bundled `db` container (the default
self-hosted Docker Compose deployment).

### Single-tenant least-privilege database runtime role

The default remains backward-compatible: API and worker use `POSTGRES_USER`
unless the operator explicitly sets `GEOLENS_RUNTIME_DB_ROLE`. New and existing
single-tenant installs can opt into a dedicated non-superuser login without
changing the multi-tenant role topology.

The credential order is load-bearing:

1. `POSTGRES_USER` / `POSTGRES_PASSWORD` remain the bundled database bootstrap,
   migration, backup, and restore identity. Do not put this credential in the
   steady-state app URL after adoption.
2. `MIGRATION_DATABASE_URL_OVERRIDE` carries that privileged identity only to
   the ordered one-shot `migrate` service.
3. `DATABASE_URL_OVERRIDE` carries the dedicated runtime login to API and worker.
4. `GEOLENS_API_RUN_MIGRATIONS=false` prevents the API image's migration safety
   net from attempting extension/schema DDL with the runtime login.
5. API and worker bootstrap verify the exact live login named by
   `GEOLENS_RUNTIME_DB_ROLE` and refuse to start if it is superuser, can bypass
   RLS, create roles/databases, replicate, assume a powerful role, or create in
   `catalog`/`public`.

On a fresh bundled volume, `init-db.sh` creates extensions and schemas first,
then runs `scripts/lib/configure-runtime-db-role.sh`. The latter creates the login,
grants catalog DML/sequence/function access, grants CREATE plus relation
ownership only in `data`, and grants SET access to `geolens_reader`. The
privileged migrate service then applies Alembic before API/worker connect.
The admin embedding-dimension resize is the sole catalog-DDL exception: the
reconciler installs a bounded `SECURITY DEFINER` function, revokes its default
`PUBLIC` execute grant, and grants it only to the configured runtime role. The
runtime login never receives catalog ownership or general DDL privileges.

#### Adopt the single-tenant runtime role on an existing install

`init-db.sh` never reruns on a non-empty PostgreSQL volume. Adoption is therefore
an explicit maintenance operation, not an Alembic migration or silent startup
privilege rewrite. Take a verified backup first, then:

```bash
# 1. Generate a credential distinct from POSTGRES_PASSWORD.
openssl rand -hex 32

# 2. Put the generated value and the four companion settings in .env.
#    Use the actual existing POSTGRES_USER password in the migration URL.
GEOLENS_RUNTIME_DB_ROLE=geolens_app
GEOLENS_RUNTIME_DB_PASSWORD=paste_generated_hex_here
DATABASE_URL_OVERRIDE=postgresql://geolens_app:paste_generated_hex_here@db:5432/geolens
MIGRATION_DATABASE_URL_OVERRIDE=postgresql://geolens:paste_existing_postgres_password_here@db:5432/geolens
GEOLENS_API_RUN_MIGRATIONS=false

# 3. Stop writers. Recreate only db so it receives the new env and read-only
#    reconciler mount; the named pgdata volume is preserved.
docker compose stop api worker
docker compose up -d --no-deps --force-recreate --wait db

# 4. Run the canonical idempotent grant/ownership reconciliation as
#    POSTGRES_USER inside db. It does not run any Alembic migration.
docker compose exec -T db /usr/local/bin/configure-runtime-db-role

# 5. Prove migrations still run with the separate privileged URL, then start.
docker compose run --rm --no-deps migrate
docker compose up -d
```

Load `.env` into the verification shell and query through the runtime login:

```bash
set -a; . ./.env; set +a
docker compose exec -T db env PGPASSWORD="$GEOLENS_RUNTIME_DB_PASSWORD" \
  psql -h 127.0.0.1 -U "$GEOLENS_RUNTIME_DB_ROLE" -d "$POSTGRES_DB" -c \
  "SELECT current_user, rolsuper, rolbypassrls, rolcreaterole,
          rolcreatedb, rolreplication
     FROM pg_roles WHERE rolname = current_user;"
```

All five capability booleans must be `f`. Also confirm API and worker are
healthy. To roll back the connection change, clear `GEOLENS_RUNTIME_DB_ROLE`,
`GEOLENS_RUNTIME_DB_PASSWORD`, and `MIGRATION_DATABASE_URL_OVERRIDE`, restore
the previous `DATABASE_URL_OVERRIDE`/migration-toggle values, then recreate API
and worker. Leave the role in place during rollback: dropping it before
re-owning `data.*` relations is destructive and unnecessary.

For managed/external PostgreSQL, run privileged migrations first, then run
`scripts/lib/configure-runtime-db-role.sh` from the host with `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_DB`, `PGPASSWORD`, and the two
`GEOLENS_RUNTIME_DB_*` variables exported. The provider credential must be able
to create roles, change relation ownership, and alter default privileges. Start
runtime services only after that command succeeds. Provider snapshot/PITR
restore normally preserves the role; after any logical restore, rerun the same
script before restarting writers.

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
6. Runs the same privileged role/grant reconciler as bootstrap. It re-applies
   `geolens_reader`; when `GEOLENS_RUNTIME_DB_ROLE` is set it also restores
   catalog runtime grants and re-owns only `data.*` runtime relations. `--clean`
   drops schema ACLs/default privileges and `--no-owner` makes the restore login
   own every restored relation, so this post-restore step is mandatory.
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
run their own. The api service (only) runs multiple uvicorn workers in
production and is scraped correctly under that fan-out because
`docker-compose.yml`/`docker-compose.prod.yml` set `PROMETHEUS_MULTIPROC_DIR`
for it by default (fix #1240 / #651); a bespoke deployment that runs the api
image outside these compose files with `UVICORN_WORKERS>1` needs to set that
same env var to a writable, container-local directory or every scrape reverts
to seeing one arbitrary worker.

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

### API worker memory & recycling

Each API worker samples its own RSS from `/proc/self/status` every 60 seconds
and exports it as the Prometheus gauge `geolens_worker_rss_bytes` (labelled by
`pid`) on the API `/metrics` endpoint. The api service runs in
`prometheus_client` multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, fix #1240 /
#651): every live worker's gauge is present in a single scrape, and HTTP
request counters/histograms sum across workers instead of alternating between
per-process values. Before this fix, a scrape only ever saw one worker, so
successive scrapes could sawtooth between unrelated running totals and
Prometheus read the downward steps as counter resets. The structured log
lines the RSS sampler writes remain useful as a secondary signal independent
of scraping — a growth curve exists in `docker compose logs api` even if
`/metrics` is never scraped:

| Log message | Level | Meaning |
|---|---|---|
| `API worker memory` | INFO | Startup baseline, then an hourly heartbeat (`rss_mb`, `pid`) |
| `API worker memory above watermark` | WARNING | Worker RSS crossed 60% of the container memory limit (1200 MB fallback when no cgroup limit is readable); repeats at most every 5 minutes |

A steadily climbing `rss_mb` — or the watermark WARNING — means one worker is
heading for the container memory cap (`API_MEM_LIMIT`, default 2 GB). When it
gets there, the cgroup OOM killer terminates that worker and drops its in-flight
requests; the only trace outside these logs is host `dmesg` (#643).

The backstop is bounded worker recycling via `UVICORN_MAX_REQUESTS`: when it is
set, the api command appends uvicorn's `--limit-max-requests` (wired in the
image CMD in `Dockerfile`; `docker-compose.prod.yml` does the same and defaults
the value to 10000). This applies to production deployments only — the
development `docker-compose.yml` overrides that command with a `--reload`
invocation that does not pass `--limit-max-requests`, so setting the variable
there has no effect. A worker exits gracefully after that many requests. With
more than one worker (the production Compose default is `UVICORN_WORKERS=2`)
the uvicorn supervisor respawns it in place, so slow growth cannot ride one
worker into the OOM killer. With a single worker there is no supervisor: the
process exits at the threshold and the container's restart policy
(`restart: unless-stopped` in `docker-compose.prod.yml`) restarts it, which is
a brief API outage per recycle — direct image deployments that keep the baked
`UVICORN_WORKERS=1` default must run under such a policy for recycling to be
safe. If the watermark WARNING still fires between recycles, lower the
value; the `UVICORN_MAX_REQUESTS` entry in `.env.example` documents the value
rules. Note that under production Compose an unset or empty value falls back
to the compose default of 10000 — disabling recycling there means editing the
`docker-compose.prod.yml` value, not blanking the variable (blanking works
only for direct image runs). Recycling caps the blast radius — it does not
explain what grows. That
investigation is tracked in #643.

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

---

## 8. Audit log retention

`catalog.audit_logs` has no built-in expiry: every login, dataset mutation,
share change, and export is a permanent row (see `AGENTS.md`'s Security
pre-commit checklist and `backend/app/modules/audit/router.py`'s module
docstring, which already flags that the table can reach millions of rows on a
busy instance). Community ships bounded CSV/JSON export
(`GET /admin/audit-logs/export/{format}`, capped at 100,000 rows per request)
but no automatic pruning — an operator who wants a retention window applies it
out of band, with `scripts/audit_retention.sh`. That is deliberately an
operator-run script rather than an in-app feature: an in-app pruning endpoint
means a new destructive-write surface (Rule 1 of the Security pre-commit
checklist, plus RBAC and rate-limit review for a delete-many endpoint), and a
script an operator invokes deliberately is the smaller, auditable surface for a
table whose entire purpose is being an audit trail.

### Deciding on a window

There is no default; pick a retention period your compliance posture
requires (30/90/365 days are common). Whatever you pick, keep two things in
mind:
- `dataset.download_cog`, `feature.*`, and `dataset.view` rows are usually the
  bulk of the table on an active instance — high-frequency, low-value-per-row
  events. A shorter window for those and a longer one for account/security
  events (`user.login.*`, `user.logout`, `user.change_password`,
  `oauth_provider.*`) is a reasonable split if your regulatory requirement
  distinguishes between them. The script below has no per-action filter — it
  applies one window to every action — so a split like that still has to be
  done by hand.
- The export endpoint is the archive step. Deleting rows you have not
  exported is not "retention", it's data loss — always export the window you
  are about to delete first.

### Archive-then-delete by age

`scripts/audit_retention.sh` performs the whole procedure: it exports the
window through the API, verifies the archive, and only then deletes exactly
the rows it archived. Run it from the repository root.

```bash
export ADMIN_TOKEN=<an admin bearer token>

# Single-tenant deployment (see the confirmation note below):
./scripts/audit_retention.sh \
  --api-url https://<your-host>/api \
  --days 90 \
  --archive-dir /var/backups/geolens/audit-archives \
  --confirm-single-tenant "yes, this deployment has no per-tenant host routing"

# Per-tenant host routing: one run per tenant, against that tenant's host.
./scripts/audit_retention.sh \
  --api-url https://<tenant-host>/api \
  --days 90 \
  --archive-dir /var/backups/geolens/audit-archives \
  --tenant-slug <your-tenant-slug>
```

**Give `--archive-dir` a path outside the checkout**, alongside wherever §1
puts your database backups. The archives belong with your backups rather than
your source tree, and keeping them out of the working copy means no later
`git add .` can stage an export of usernames, IP addresses and activity. The
default is `./audit-archives`, which lands in the repository root when you run
the script from there; `.gitignore` covers that directory as a second line of
defence, but the directory you actually want is the one next to your backups.

`--help` lists every flag. The ones worth knowing before the first run:

| Flag | Effect |
| --- | --- |
| `--days N` / `--cutoff TS` | The retention boundary. Exactly one is required; there is no default window. |
| `--tenant-slug SLUG` / `--confirm-single-tenant PHRASE` | The scope. Exactly one is required. |
| `--dry-run` | Export and verify, then stop without deleting. Use it for the first run on any deployment. |
| `--archive-dir DIR` | Where archives land (default `./audit-archives`). Point it outside the checkout. |
| `--db-url URL` | External/managed Postgres (below). |
| `--batch-size N` | Rows per delete statement, default 5000. |
| `--max-rows N` | Rows per export call, default 100000. |
| `--vacuum` | `VACUUM (ANALYZE) catalog.audit_logs` after the delete. |

#### What it verifies before deleting anything

The script exits non-zero and deletes nothing if any of these fails:

- **The export request itself.** curl runs with `--fail`, so an expired token,
  a wrong host, or any 4xx/5xx aborts the run instead of saving the error body
  (e.g. `{"detail":"Not authenticated"}`) as if it were the archive.
- **The archive is a complete JSON array.** A 200 carrying a proxy error page,
  or a truncated stream, fails here rather than reporting a plausible row
  count. JSON is used rather than CSV because a CSV line count is not a row
  count: `resource_name` comes from user-supplied titles, which may contain
  literal newlines that the CSV writer preserves inside a quoted field.
- **The archive holds exactly as many rows as the database counts** for the
  identical window and scope, and no row whose timestamp falls outside that
  window.
- **The archive holds exactly the rows the delete would remove**, compared by
  audit-log id. Size and time range are not enough on their own: the export is
  scoped by the host it is called against, so pairing `--tenant-slug` with the
  wrong tenant's `--api-url` returns that tenant's rows, and if both tenants
  have the same number of rows in the window every other check passes while the
  archive describes the wrong history. If your server predates this check it
  will not send the id at all, and the script stops rather than guessing;
  upgrade the deployment.
- **After the delete**, no row at or before the cutoff remains in scope.

Two structural properties sit behind those checks:

- The cutoff is evaluated **once**, in the database, and every later step reuses
  that exact string. Nothing re-evaluates `now() - interval '90 days'`, so the
  count, the export and the delete cannot drift apart over the minutes a large
  run takes.
- Both window bounds are inclusive everywhere (`created_at >= date_from AND
  created_at <= date_to`), matching the export endpoint's own filters. There is
  no way to ask that endpoint for an exclusive bound, and a delete using `<`
  against an export using `<=` can discard a row that was never archived.

Archive filenames carry the scope, a UTC timestamp and the pid, and the script
refuses to write over a file that already exists — two tenants archived on the
same day, or the same tenant archived twice, cannot truncate each other's only
copy.

An archive is a verbatim dump of usernames, IP addresses and activity for the
whole window, so the script runs under `umask 077`: archives are created 0600
and an archive directory it creates is 0700. Under the usual 022 they would be
world-readable by every local account on the host. A directory that already
exists keeps whatever permissions you gave it, so check that one yourself.

Windows holding more than `--max-rows` rows are split automatically. Narrowing
`date_to` by hand does not work: the endpoint always returns the *newest* rows
in a range, so repeating the same call returns the same slice forever.
Consecutive sub-windows share their boundary instant, so a row on a boundary is
archived twice — harmless, and much safer than offsetting a bound by an epsilon,
which would drop that row from every export instead.

Timestamps are not unique, so a split can land in the middle of a group of rows
sharing one instant. When that happens the script backs off to the last distinct
timestamp before the group and exports what precedes it, rather than treating
the window as unsplittable. The only case it genuinely cannot split is a *single
instant* holding more rows than `--max-rows`, because no choice of bounds makes
that window exportable; the run stops and names the timestamp. Raise
`--max-rows` (up to 100000) or archive that instant by hand.

If you want a CSV copy for human review, export it separately *after* a run has
completed; never use CSV as the verification input.

#### Choosing a scope

**The script does not detect your deployment's tenancy mode, and neither
should you infer it.** An empty tenant slug is not evidence of a single-tenant
deployment; a mistyped slug or a failed lookup is exactly what turns into an
unscoped, cross-tenant delete. So the two scopes are separate flags with no
fallback between them, and `--tenant-slug` aborts if the slug resolves to
nothing.

`--confirm-single-tenant` takes the phrase verbatim:

```
yes, this deployment has no per-tenant host routing
```

An earlier revision of this procedure read `GEOLENS_TENANCY_MODE` from `.env`
instead. That value can be absent, injected by an orchestrator rather than
persisted to a file, or simply not read from wherever the running deployment
gets its configuration — any config-derived signal here can be missing, stale,
or wrong in a way a shell script cannot detect. The phrase has to be typed by
an operator who has personally confirmed it.

Running the unscoped mode on a deployment that *does* have per-tenant host
routing is the worst outcome available here, and the reason is the export, not
the delete: the export is always scoped to whichever tenant's host you call it
against, so an unscoped delete removes every other tenant's audit history that
the export never captured — permanent loss with no archive.

#### Connecting to the database

By default the script talks to the bundled `db` container through
`docker compose exec`, reading `POSTGRES_USER` / `POSTGRES_DB` from `.env` like
the other scripts here. On a managed or external Postgres (§3) there is no `db`
container, so use either:

```bash
# The whole URL in the environment, password included:
export GEOLENS_RETENTION_DB_URL="postgresql://user:pw@host:5432/geolens"
./scripts/audit_retention.sh ...

# ...or a password-free URL on the command line, with the password in the
# environment beside it:
export PGPASSWORD=...
./scripts/audit_retention.sh --db-url "postgresql://user@host:5432/geolens" ...

# ...or the standard libpq environment variables (setting PGHOST or PGSERVICE
# is what selects this mode):
export PGHOST=... PGPORT=5432 PGUSER=... PGDATABASE=geolens PGPASSWORD=...
./scripts/audit_retention.sh ...
```

**`--db-url` will not accept a password, and refuses rather than warning.**
Command lines are world-readable on most systems (`ps`,
`/proc/<pid>/cmdline`), so anything typed there is visible to every local
account for as long as the process runs — and this script runs for the whole
retention pass, longer than any command it spawns. Nothing can retract it
afterwards, so the password has to arrive by another route. The two above both
work; the error message names them if you forget.

That covers both places a libpq URL can carry one: `user:password@` and a
`?password=` query parameter. Supplying it in both is refused as well, because
libpq silently resolves that in favour of the query parameter and ignores the
other — so changing the wrong half would connect with the credential you
thought you had replaced.

Secrets in the command lines the script *does* control are handled for you: a
password from `GEOLENS_RETENTION_DB_URL` is moved into the environment before
`psql` is invoked, and the admin bearer token reaches `curl` through a `0600`
header file instead of `-H`.

A password inside either URL must be percent-encoded, as libpq requires
(`p@ss/word` becomes `p%40ss%2Fword`). The script decodes it before handing it
over; if the encoding is malformed it stops and tells you to use `PGPASSWORD`
instead, rather than guessing and connecting with a mangled password.

A SQLAlchemy driver suffix is stripped for you: `postgresql+asyncpg://` and
`postgresql+psycopg://` both become `postgresql://`, which is what libpq's URI
parser accepts.

Whichever credential you use must be able to see and modify rows across every
tenant — **not** the app's least-privilege runtime login. `catalog.audit_logs`
carries the `tenant_isolation` row-level security policy (migration 0022), and a
session without `BYPASSRLS` reads zero rows through it, so that credential would
count nothing, delete nothing, and report success. Use the same
privileged/migrator-class credential §2 calls out for schema changes, not the
steady-state `DATABASE_URL_OVERRIDE` your deployment authenticates with day to
day. Boot already refuses to start `GEOLENS_TENANCY_MODE=multi_tenant` with a
runtime role that *can* bypass RLS (`backend/app/core/db/rls.py`), by design, so
the two credentials really are different accounts.

The script enforces this per query rather than trusting you to get it right:
every statement it runs is preceded by `SET row_security = off`, which is a
no-op for a session that can bypass RLS and an error — "query would be affected
by row-level security policy" — for one that cannot. The run stops there. A
connectivity check could not have caught it, because `SELECT ... LIMIT 0`
succeeds for a login RLS reduces to nothing, which is exactly why the wrong
credential used to look like an empty retention window.

The export goes through the API, not a direct database connection, so this
choice does not affect it.

#### Scheduling and running cost

Run it from a low-traffic maintenance window. The table's only DELETE-supporting
index is `ix_catalog_audit_logs_created_action_resource`
(`created_at DESC, action, resource_type`), so an unbounded delete on a
multi-million-row table can hold locks and bloat the table; the script batches
at `--batch-size` rows per statement for that reason. Pass `--vacuum` if the run
removed a large fraction of the table — routine autovacuum handles smaller,
regular prunes on its own.

Requires `curl` and `jq` on the machine you run it from. Beyond that it depends
on how you connect: the bundled path needs `docker` and nothing else, because it
runs `psql` *inside* the db container, while the `--db-url`,
`GEOLENS_RETENTION_DB_URL` and `PG*` paths need a `psql` client on the host. A
Docker-only self-host does not need one installed.

**What is actually lost:** the deleted rows, permanently, including the
ability to answer "who did X on day Y" for anything older than the window.
That is the intended tradeoff of retention; keep the exported archive (offsite,
per §1's guidance on the primary backup) if you need to answer that question
later without re-enabling unbounded storage in the live table.

---

## 9. Uploaded source-file retention

When someone uploads a file, GeoLens keeps the uploaded bytes only as long as it
needs them to build the dataset. This section says what survives the ingest, so
you are not surprised later by what a restore does and does not contain.

### What is deleted, and when

| Upload | Where the data ends up | The uploaded file |
| --- | --- | --- |
| Vector (Shapefile, GPKG, GeoJSON, CSV, …) | PostGIS table | **Archived to `originals/`**, and the staging copy deleted |
| Raster (GeoTIFF) | A Cloud-Optimized GeoTIFF in object storage | Deleted after a **lossless** conversion; archived to `originals/` otherwise |
| Raster replace (re-upload onto an existing raster dataset) | The dataset's COG is swapped for the new one | Deleted after a **lossless** conversion; archived to `originals/` otherwise |

Vector uploads are archived rather than discarded: after a successful ingest
the file is copied to `originals/<dataset-id>/<filename>` and only the staging
copy is removed. That archive is best-effort — if the copy fails the ingest
still succeeds, because the data is already in PostGIS, and the job records an
`archive_failed` flag you can see on the admin Jobs page. So treat a vector
original as present-but-not-guaranteed, and check the flag if you are relying
on one.

A raster dataset **is** its COG. When the conversion is lossless the converted
asset carries everything the upload did, and every re-processing case an
operator actually has — different overview levels, different compression,
different internal tiling — starts from the COG just as well as from the
original. Keeping a second copy of every raster ever uploaded bought nothing and
cost object storage forever, so in that case it is no longer kept (ADR-002
Decision 7).

### When the conversion is lossy, the upload is kept

Two things about a conversion can make the COG an unfaithful copy, and either
one causes the upload to be kept.

**Compression.** The import form lets the uploader choose. Four options are
lossless — **DEFLATE** (the default), **LZW**, **ZSTD**, **LERC** — and two
discard image detail to save space: **JPEG** and **WEBP**.

LERC is lossless here because GeoLens never sets an error bound on it. LERC can
be tuned to throw away precision, but that is the GDAL creation option
`MAX_Z_ERROR`, its default is zero, and the conversion pipeline does not pass
it. So a LERC upload keeps its exact sample values and is treated like any other
lossless conversion.

**Reprojection.** Supplying a CRS override reprojects the raster, which
resamples every pixel onto a new grid. The output is a faithful *rendering* but
not the original measurements, so this counts as lossy even under DEFLATE.

In either case the uploaded file is the only copy of the original samples that
will ever exist, so GeoLens keeps it.

### Where the kept original lives, and for how long

It is copied to `originals/<dataset-id>/<hash>` — the same place vector ingests
archive their sources. On an object-storage install that is a prefix in your
bucket; on a local install it is `originals/` inside the `upload_staging`
volume. One location, both shapes.

The `<hash>` is the first 32 characters of the uploaded file's SHA-256, and it
is the whole name: **no filename, no extension**. The object is identified by
its content and nothing else, so the same bytes are the same object however they
were named — upload `survey.tif` and `survey-final.tif` with identical content
and you get one stored copy, not two. That also means two uploads sharing a
filename cannot overwrite each other, which matters because a replacement is
archived before its swap commits: if the swap then fails, the dataset keeps
serving the previous raster, whose original must still be sitting there
untouched.

**To find out what a stored original was called**, read the dataset's asset
table rather than the object name — each kept original has a row whose
description is the filename it was uploaded under. Listing the `originals/`
prefix shows hashes by design; the names live where they cannot affect which
object is which.

That location is deliberate. The copy is **not** left under `staging/`, because
staging is for transient files and the retention purge is entitled to clean it:
the purge keeps only each dataset's most recent completed job, so a kept
original would have been deleted the next time that dataset was ingested or
replaced. Under `originals/` no purge touches it.

Its lifetime is therefore tied to the dataset, not to a job:

| Event | What happens to the kept original |
| --- | --- |
| The dataset is replaced again with a lossy conversion | The new original is kept alongside it. Every upload with distinct content persists, whatever it is called; re-uploading a byte-identical file rewrites the same object rather than adding a second copy. |
| The dataset is replaced with a **lossless** conversion | Nothing new is kept. Earlier originals stay — they are still the only copy of what those uploads contained. |
| The dataset is **deleted** | Removed with it. Deleting a raster dataset clears the whole `originals/<dataset-id>/` prefix. |
| The `ingest_jobs` retention window passes | Nothing. This copy is not a job artifact. |

**It counts against the owner's storage quota.** Every kept original gets its
own row in the dataset's asset table, so `MAX_STORAGE_BYTES_PER_USER` sees
those bytes and a lossy replacement is admitted only if the COG *and* the
original fit. That includes superseded originals: the cap exists to bound your
storage by policy, so nothing that persists is left uncounted. Re-uploading a
byte-identical file does not double-count — it is the same object and the same
row.

Those rows are internal. They are not published as downloadable assets in
search or STAC responses, because the original is the higher-fidelity copy the
conversion deliberately replaced.

**If the archive cannot be written, the ingest fails.** A durable copy of the
original is a precondition of a lossy conversion, not a nice-to-have: the
conversion's success is what licenses deleting the uploaded file, so if the
detail the COG cannot carry is not yet safely stored, GeoLens refuses to
publish. The dataset keeps whatever it was serving, the uploaded file is
retained with the failed job, and the job's error says so. Retry once object
storage is healthy. That retention is the FAILED-job window —
`INGEST_JOBS_RETENTION_DAYS`, default 30 — not the permanent one, so do not
leave a failed lossy ingest sitting for a month before retrying it.

> **If you delete an original object by hand, its row stays.** There is no
> reconciliation between storage and the asset table, so the owner's usage will
> overstate by the size of whatever you removed until the dataset itself is
> deleted (which clears both). If you need the quota back immediately, delete
> the dataset rather than the object — or accept the overstatement until then.

The practical consequences:

- Expect storage for lossily-converted rasters to hold roughly the COG plus the
  original, not the COG alone. If storage growth surprises you, list the
  `originals/` prefix — that is usually where it is.
- Those originals are safe to delete yourself if you accept losing the only
  faithful copy. Nothing in GeoLens reads them; they exist so the choice stays
  yours.
- If you want the smaller footprint and do not need the original, ingest with a
  lossless compression and no CRS override, and accept the larger COG.

Provenance is still recorded: the dataset's `source_filename` and the
`file_hash` in `origin_ref` identify exactly which bytes were ingested. What is
gone is the ability to hand those bytes back.

> **If your workflow depends on re-downloading the file a user uploaded,
> archive it before it reaches GeoLens.** GeoLens is a catalog, not an archive
> of submissions, and the download endpoints serve the COG, not the original.

### The other case where the original is kept

If COG conversion **fails**, the uploaded file is retained. At that point it is
the only copy in the system and it is what you need to diagnose the failure —
open it with `gdalinfo`, check the driver, check the CRS.

That retention is bounded, not permanent. The failed `ingest_jobs` row and its
staged file are removed by the periodic purge once the row is older than
`INGEST_JOBS_RETENTION_DAYS` (default 30; `0` disables the purge and keeps
everything). So the practical rule is: **you have the retention window to
retrieve a failed upload's source file, and after that it is gone.**

Failed uploads are visible on the admin Jobs page with their error message.
The files themselves live under `staging/<job-id>/` — in the `upload_staging`
volume on local storage, or under that prefix in your bucket on S3/MinIO.

### Interaction with backups

§1's `staging-<timestamp>.tar.gz` archives the `upload_staging` volume. What
that does and does not recover depends on which case put the file there.

| Case | In the staging tar? |
| --- | --- |
| Failed upload, still inside the retention window | Yes |
| **Vector original, local storage** | **Yes** — archived under `originals/` in that volume |
| Vector original, object-storage install | No — in your bucket under `originals/` |
| **Retained original from a lossy or reprojected ingest, local storage** | **Yes** — it lives under `originals/` inside that same volume |
| Retained original, object-storage install | No — it is in your bucket under `originals/`, covered by whatever backs up the bucket, not by this tar |
| Successfully ingested original from a **lossless** conversion | No — deleted before the backup ran |

The last row is the only one that is genuinely unrecoverable, and it is the
case where the COG carries the same samples anyway. Retained originals are
recoverable on a local install, so if you are restoring one and need the
pre-conversion files back, extract the staging archive as §2 describes and the
`originals/` tree comes with it.
