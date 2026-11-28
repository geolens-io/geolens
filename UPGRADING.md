# Upgrading GeoLens

An upgrade pulls the new images, backs up the database, runs the migrations
(fail-closed), and brings the stack up behind a health gate. A failure before
the migrations leaves the database untouched; fix it and re-run. If you need to
roll back after the migrations ran, re-pin the old version and restore the
pre-upgrade dump. The
[upgrade guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) has the
full procedure, the manual and source-build flows, and the notes for each release.

> **Major PostgreSQL upgrades are a special case.** A release that moves the
> bundled PostgreSQL to a new major version cannot be applied with an image
> pull: the old `pgdata` volume will not open. Follow
> [RUNBOOK.md § 6](RUNBOOK.md#6-major-postgresql-version-upgrade-17--18)
> instead. `scripts/upgrade.sh` compares the running server's major with the
> target release's and stops before changing anything when they differ.

## Which install do you have?

```bash
grep -E '^(COMPOSE_FILE|GEOLENS_VERSION)=' .env
```

- **Prebuilt images:** `COMPOSE_FILE=docker-compose.prod.yml` and a pinned
  `GEOLENS_VERSION`. `scripts/upgrade.sh` automates this path.
- **Source build:** `COMPOSE_FILE=docker-compose.yml` (or unset) and no
  `GEOLENS_VERSION`. `scripts/upgrade.sh` does not modify it. Update the
  checkout and rebuild, following the guide's
  [source-build steps](https://docs.getgeolens.com/guides/quickstart/upgrade/#source-build-upgrade-alternative).

## Upgrade

From your install directory:

```bash
./scripts/upgrade.sh            # newest published release
./scripts/upgrade.sh 1.2.4      # or an explicit target version
```

In a git checkout the script first fetches the target release tag so the
compose files and mounted scripts match it. If that fetch fails, the script
stops before changing anything; retry once the network is back. To upgrade with
the compose files, scripts and `db/postgresql.conf` already on disk instead, add
`--keep-current-files` (`./scripts/upgrade.sh --keep-current-files 1.2.4`) and
review those files against the release afterwards.

The script pulls the images while the app keeps serving, stops `api` and
`worker`, takes a verified `pg_dump -Fc` to
`backups/pre-upgrade/<db>_pre_<old>_to_<new>_<timestamp>.dump`, runs the
migrations, pins the new `GEOLENS_VERSION` in `.env`, and starts the stack. Those
last steps are an outage. [RUNBOOK.md § 10](RUNBOOK.md#10-routine-version-upgrade-outage-and-rollback)
covers how long it lasts and what to do if the script dies part-way.

Datasets keep their last three previous versions by default, where earlier
releases kept one, so the database can grow to about three times a replaced
dataset's size per dataset. Set **Previous versions kept per dataset** to 1
under Settings > Storage, or send `{"settings": {"previous_versions_kept": 1}}`
to `PUT /settings/` as an admin, to keep the earlier behaviour.

GeoLens no longer sends a service credential (an ArcGIS token, a username and
password, or an API key) to a plain `http://` service address. Probing,
previewing, importing and refreshing such a service with a credential now
fails with `credential_over_http`, and that includes refreshes of datasets you
imported earlier. Move the service to `https://` where you can. For intranet
services without TLS, list their hosts in `SERVICE_CREDENTIALS_ALLOW_HTTP_HOSTS`
in `.env` (comma-separated, `host` or `host:port`) and restart `api` and
`worker`. Deployments that don't use the bundled Compose files, such as Helm
charts and the cloud templates, must pass the variable to both the api and
worker containers.

Importing, re-uploading or refreshing a service that needs a token (an
org-shared or private ArcGIS layer, for example) needs a shared cache, and
without it those requests fail with `credential_store_unavailable` (503).
`install.sh` now enables the bundled Valkey on prebuilt-image installs
(`COMPOSE_FILE=docker-compose.prod.yml`). An install made earlier doesn't have
it: add `cache` to the end of any existing `COMPOSE_PROFILES` list (don't
replace it), plus `VALKEY_PASSWORD=<openssl rand -hex 32>` and
`REDIS_URL=redis://:<that password>@valkey:6379/0`, to `.env`, then run
`docker compose up -d`. Re-running `install.sh` sets the same values when they
are missing. Source builds and installs with their own cache set `REDIS_URL` to
that cache instead, and need no bundled service.

ArcGIS service datasets with BigInteger, DateOnly or TimestampOffset fields
imported earlier hold those fields as text. Their next refresh is held for
review once, with the type changes listed. Accept it to switch to bigint,
date and timestamptz columns. TimeOnly fields stay text.

ArcGIS web maps imported or migrated with `geolens arcgis migrate` before this
release stack their layers upside down: the layer that draws at the bottom in
ArcGIS draws on top in GeoLens. The upgrade doesn't change them. Reorder their
layers in the map builder. A map imported through
`POST /maps/import/arcgis-webmap` can instead be deleted and imported again.
A rerun of `geolens arcgis migrate` translates a map it created again, in the
new order, when the web map changed in the portal since the last run or a
layer is still owed, as long as the map wasn't edited in GeoLens since then;
otherwise it leaves the layers as they are. Don't delete a migrated map to
redo it: a rerun reports it as gone and doesn't create it again. A
`style.json` exported earlier lists layers in the reverse of their draw order;
export it again.

Every existing map starts with "Readers can open the attribute table" on. While
it is on, the map's embed tokens can page its layers' rows through
`GET /datasets/{id}/rows/`, within each dataset's `tile_columns` allowlist
when it has one. To
turn it off, clear the setting under Settings > Readers in the map builder, or
send `show_attribute_table: false` in `PUT /maps/{id}`. To limit the columns,
set `tile_columns` with `PATCH /datasets/{id}`.

Migration 0101 drops the four `catalog.datasets.previous_version_*` columns,
which have been empty since 1.27. Neither 1.27 nor 1.28 reads them, so a
rolling upgrade from 1.28 keeps working. Coming from 1.26, use
`scripts/upgrade.sh`, which stops `api` and `worker` before it migrates, or
upgrade to 1.27.1 first.

During a rolling upgrade to 1.30, an instance still on 1.29 hides a scene saved
with a `transition` until it is upgraded; the stored scene is kept. A draft
saved through a 1.29 instance drops the story's reader settings (navigation,
layout, theme), so set them again once every instance is on 1.30. Chapters,
blocks and scenes without a transition are kept.

Migrations 0104 and 0105 add nullable columns and widen the API key scope
check, and 1.31 reads none of them, so a rolling upgrade from 1.31 keeps
working. A `map_author` key is refused by an instance still on 1.31.

From 1.32, an admin transfer of a map revokes that map's embed tokens, and
while public visibility is restricted to admins, embed tokens a non-admin
minted on a private or internal map stop working. Mint new ones as the new
owner or an admin where a map needs them. Reads by a caller with no sign-in or
API key (OGC API, STAC, catalog search) now stop after 30 seconds of database
time and answer 503; set `DB_ANONYMOUS_READ_TIMEOUT_SECONDS` to change it.

`SESSION_SECRET_KEY` is a new optional signing key for the OAuth sign-in
session cookie. Unset, it falls back to `JWT_SECRET_KEY`. If you set it, use at
least 32 characters that differ from the JWT secret and the tile signing key,
or the API refuses to start, and use the same value on every API replica. New installs get one generated; an
existing `.env` keeps what it has. `install.sh` and `upgrade.sh` now keep the
mode of an existing `.env` and create a new one with mode 600.

During a rolling upgrade to 1.32, an instance still on 1.31 answers 403 to a
tile URL that a 1.32 instance signed for an embedded map. Embedded maps can
miss tiles until every instance is on 1.32, and a map opened during the upgrade
recovers on reload. After a rollback to 1.31 the same happens for up to 16
minutes, until the URLs signed by 1.32 expire. Single-instance installs are not
affected.

1.33 has no migrations. Upgrade the Python SDK to 1.33 before you read job
status with it: a SQL Server import or refresh can now report a `zm_dropped`
warning, and the 1.32 SDK raises on a warning kind it doesn't know. A SQL
Server dataset imported earlier gains its Z and M values, and a point table
its `Point` type, at its next refresh, which publishes without a review. A
remote COG with a colour table imported before 1.33 keeps its stretched
rendering; delete it and import it again to draw it from the table. The new
import is a new dataset, so add it back to the maps that showed the old one:
the delete is refused while one of your own shared maps shows it, and it
removes the layer from other users' maps. An
existing DEM mosaic keeps nearest-neighbour resampling until you run
**Regenerate** on its Source tab.

1.34 runs two migrations that only add nullable columns and two partial
indexes, so instances still on 1.33 keep serving while they run. A map update
that leaves out `bookmarks`, as a 1.33 SDK or client sends it, keeps the
bookmarks the map has. Publish manifest version 2 is a preview: finish
upgrading every worker before you send a version 2 publish. During a rolling
upgrade a version 2 job waits for an upgraded worker, and a worker still on
1.33 that takes it first leaves it to fail at the stale-job sweep. To publish
again after that, upload the file again and apply with the new
`upload:<job_id>`, because the first upload is used up. Version 1 manifests
are not affected. Overlay authors: `EXTENSION_API_VERSION` is 26.

1.35 runs one migration, 0108, which replaces the worker's job-fetch function
in place with the body procrastinate 3.11 ships. Its signature and result are
unchanged, so workers still on 1.34 keep fetching jobs while it runs.
Finish upgrading every worker before you republish a raster through a publish
manifest, version 1 or 2, or send a version 2 publish that names `groups`. A
1.34 worker doesn't know the raster replacement job, so the job is left to
fail at the stale-job sweep and the dataset's publish run stays held until
then. A 1.34 worker that takes a version 2 job ignores its groups: the dataset
publishes without being shared, and a replacement whose entry drops a group
(`groups: []`) still reaches the groups the dataset has. A manifest raster
republish replaces the raster, and the old one can't be restored.

Upgrade the Python SDK and CLI to 1.35 before you read the status of a version
2 job with them: the job can now report a `manifest_groups_left_off` or
`manifest_widening_kept` warning, and the 1.34 SDK raises on a warning kind it
doesn't know.

A finished upload for a new dataset that nothing has imported yet now waits 24
hours, or `PENDING_JOB_TIMEOUT_SECONDS` plus an hour if that is longer, before
the stale sweep cancels it, when its file is staged on disk. That is every
upload unless storage is S3, which holds the file in the bucket and already
used that cutoff. A replacement of an existing dataset that is staged on disk
keeps the ordinary timeout. The staging directory can hold such files for that
long. An API instance or worker still on 1.34 cancels a finished upload after
`PENDING_JOB_TIMEOUT_SECONDS` itself, an hour by default, so finish upgrading
every instance, API and worker, before you upload a large version 2 batch.

A plain upload or URL import at the account's dataset cap is now accepted and
refused at commit, with the same 422, where it used to be refused at upload.

A dataset export's `where` filter now accepts one condition in a stated
filter language, and anything else answers 400: comparisons, `AND`, `OR`,
`NOT`, `IN`, `BETWEEN`, `LIKE`, `ILIKE` and `IS`, column names, plain string
and number literals, and parentheses. Check saved export links and scripts
before you upgrade. Text after the condition is refused, and so are function
calls, the symbolic pattern operators (`~~`, `~~*`; write `LIKE` and
`ILIKE`), a chained comparison such as `a < b = c`, and a condition nested
more than 16 levels deep. A mixed-case column needs double quotes, and so
does a column named with a reserved word such as `"order"`. There is no
deprecation window, because the old reading can't be kept safely.

A table registered on 1.35 gets `geom_4326` as a stored generated column, and
1.34 can't edit its features. A refresh on 1.35 does the same for a registered
table whose `geom_4326` column is missing. Finish upgrading every instance
before you register tables or refresh such a table, and expect feature edits
on them to fail after a rollback to 1.34.

If a reverse proxy of your own sits in front of GeoLens, such as an ingress
controller or a load balancer, let it accept a request line of 16 KiB
(`large_client_header_buffers 4 16k;` in nginx). The bundled frontend proxy
now does. A map whose layers read many columns of one dataset asks for vector
tiles with a URL longer than the usual 8 KiB default, and a proxy that refuses
it leaves those layers blank.

Overlay authors: `EXTENSION_API_VERSION` is 28. `ProcessingPort` gains
required methods, and `apply_manifest_maps` takes new arguments and can return
a minted share link under `MINTED_SHARE_KEY`; see the changelog.

## Change the published default database password

Earlier `.env.example` files set `POSTGRES_PASSWORD=geolens`. An install whose
database was created from such a file, without `install.sh` generating a value,
still uses that published password. Its API and worker log
`postgres_password_published_default` at startup, and the first release on or
after 2027-02-10 refuses to start with it. The value that matters is `POSTGRES_PASSWORD` in `.env`. This
check from your install directory finds the line as earlier templates wrote it,
bare or quoted, and not other spellings such as an `export` prefix:

```bash
grep -Eqx "POSTGRES_PASSWORD=[\"']?geolens[\"']?" .env && echo "change it"
```

To change it on a running Compose install:

```bash
# 1. Set a new password on the database role. \password prompts for it and
#    sends it hashed, so it stays out of shell history and the server log.
#    Generate one first with `openssl rand -hex 24`.
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
#    At the psql prompt run \password, enter the new value twice, then \q.

# 2. Set POSTGRES_PASSWORD in .env to the same value. Then change the password
#    inside every URL override in .env that signs in as this role, such as
#    DATABASE_URL_OVERRIDE, TILE_DATABASE_URL_OVERRIDE or
#    MIGRATION_DATABASE_URL_OVERRIDE. Leave the URL of another role alone
#    unless its password is also `geolens`: the startup warning reads
#    DATABASE_URL_OVERRIDE and TILE_DATABASE_URL_OVERRIDE as well. Give that
#    role a new password with `\password <role>` (step 1 without a name
#    changes only the role you signed in as) and put the new value in its URL.

# 3. Recreate the services that read it: db, migrate, api, worker and backup.
docker compose up -d
```

`docker compose restart` keeps each container's old environment, so use
`up -d`. With the
[least-privilege runtime role](RUNBOOK.md#single-tenant-least-privilege-database-runtime-role)
in use, `POSTGRES_PASSWORD` belongs to the bootstrap login and the API and
worker don't see it, so they don't log the warning; change it the same way.

## Replace a weak TILE_SIGNING_SECRET

A `TILE_SIGNING_SECRET` shorter than 32 characters or equal to a known-public
value logs `tile_signing_secret_weak` at startup, and the first release on or
after 2027-02-10 refuses to start with it. An unset value, or one equal to
`JWT_SECRET_KEY`, is not refused. Set a new value from `openssl rand -hex 32` in
`.env`, the same on every API replica, then run `docker compose up -d api worker`.
Signed tile URLs issued under the old key stop verifying until the page reloads
them.

## Rollback

Rollback is re-pinning the previous version and restoring the pre-upgrade dump.
Migrations move forward only, and `alembic downgrade` is **not** a supported
rollback.

```bash
# 1. Set GEOLENS_VERSION in .env back to the version you upgraded from.

# 2. Restore the dump the upgrade took. restore.sh validates it, stops
#    api/worker, runs pg_restore and restarts them.
./scripts/restore.sh backups/pre-upgrade/<db>_pre_<old>_to_<new>_<timestamp>.dump

# 3. Bring the previous version up.
docker compose up -d
```

`restore.sh` takes a custom-format (`-Fc`) dump; never feed one to `psql`.

If you downgrade the schema anyway, the downgrade of
`0087_publish_api_keys` stops while any active API key has the Publish scope,
because the older schema could only keep it as a full-access key. Revoke those
keys in Settings > API keys (or as an admin), then run the downgrade again.
Revoke them too before you start an older image against the newer schema with
`GEOLENS_API_RUN_MIGRATIONS=false`: an older image doesn't know the Publish
scope and treats those keys as full-access keys.

The downgrade of `0104_map_author_api_keys` stops the same way while any active
API key has the Map author scope, and drops the record of which key created
each map. An older image refuses Map author keys on every request.

The downgrade of `0088_dataset_kept_versions` stops while any dataset keeps more
than one previous version. The downgrade of the `restricted` map visibility
migration turns restricted maps private, and the downgrade of
`0089_sharing_groups` drops every sharing group and membership. The downgrade
of `story_group_grants` turns restricted stories private, and the downgrade of
`map_show_attribute_table` drops the `show_attribute_table` column from maps.

## Backups and disaster recovery

The `backup` service runs by default. The
[Backups & Restore guide](https://docs.getgeolens.com/guides/admin/backups/)
covers its settings, retention, offsite upload and routine restores.
[RUNBOOK.md](RUNBOOK.md) is the reference for disaster recovery, managed
Postgres, monitoring and incident response; its
[full restore](RUNBOOK.md#step-by-step-full-restore-db--object-storage)
restores the database, the object-storage archive and the cluster roles
together.
