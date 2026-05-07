# Edition Deactivation Runbook

Deactivating the GeoLens **Enterprise** overlay (returning a deployment to the open-core community edition) is an operator-facing flow shipped with the private `geolens-enterprise` source. The open-core build of GeoLens runs as the community edition by default; no deactivation step is required for fresh community deployments.

## Pre-step: take a `pg_dump` backup

The deactivation flow may include `alembic downgrade -1` (and in some scenarios additional revisions) to remove enterprise-only schema (SAML overlay columns, audit-log export tables, etc.). **Before running any downgrade, take a verifiable database backup.** From the API container or any host with `pg_dump` and access to the database:

```bash
# Compressed schema + data dump, named with timestamp + revision before downgrade
pg_dump \
  --host="$POSTGRES_HOST" \
  --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --format=custom \
  --file="geolens-pre-deactivation-$(date +%Y%m%d-%H%M%S).dump"
```

Verify the dump is restorable on a throwaway database before continuing — `pg_restore --list <dump>` to inspect contents and `pg_restore --dbname=<scratch>` to confirm it loads cleanly. The downgrade is irreversible without this backup; SAML-mapped users and enterprise-only audit-log rows would be lost.

## Detailed deactivation procedure

For step-by-step deactivation procedures (including SAML-user conversion to local accounts, audit-log preservation, and edition gating verification), see the operator guide on the documentation site:

- **Edition deactivation runbook:** [docs.getgeolens.com/guides/operations/edition-deactivation/](https://docs.getgeolens.com/guides/operations/edition-deactivation/)

For information on obtaining or licensing the GeoLens Enterprise overlay, see the README **Enterprise and Security** section or contact `enterprise@getgeolens.com`.
