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

The downgrade of `0088_dataset_kept_versions` stops while any dataset keeps more
than one previous version. The downgrade of the `restricted` map visibility
migration turns restricted maps private, and the downgrade of
`0089_sharing_groups` drops every sharing group and membership.

## Backups and disaster recovery

The `backup` service runs by default. The
[Backups & Restore guide](https://docs.getgeolens.com/guides/admin/backups/)
covers its settings, retention, offsite upload and routine restores.
[RUNBOOK.md](RUNBOOK.md) is the reference for disaster recovery, managed
Postgres, monitoring and incident response; its
[full restore](RUNBOOK.md#step-by-step-full-restore-db--object-storage)
restores the database, the object-storage archive and the cluster roles
together.
