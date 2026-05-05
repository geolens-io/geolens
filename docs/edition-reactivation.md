# Edition Reactivation: Community → Enterprise

> **This runbook is for operators re-upgrading a previously deactivated GeoLens deployment back to enterprise edition.** If you are activating enterprise for the first time, see [`docs/saml.md`](saml.md) — Installation section instead.

Re-upgrade is structurally the inverse of deactivation. If you followed the safe path in [`docs/edition-deactivation.md`](edition-deactivation.md), your `oauth_providers` SAML rows and the 4 `deferred=True` SAML columns are still in the database — re-mounting the overlay makes them queryable again. No data restore, no migration replay, no admin re-configuration.

## Re-mount the overlay

```bash
# Stop community-only stack
docker compose down

# Bring up the enterprise stack with the compose overlay from a sibling
# geolens-enterprise checkout (loads geolens-enterprise + ensures e002 is at head)
docker compose -f docker-compose.yml -f ../geolens-enterprise/docker-compose.enterprise.yml up -d --build

# Migrations run automatically on container start; if needed manually:
docker compose exec api uv run alembic upgrade heads
```

For full activation context (IdP setup, admin UI walkthrough, hardening defaults), see [`docs/saml.md`](saml.md) — Installation section.

## Post-reactivation verification checklist

1. **SAML routes mounted.**

   ```bash
   curl -fsS http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("/auth/saml/"))'
   ```

   Expected: list of SAML routes (metadata, login, acs, etc.).

2. **Enterprise overlay loaded.**

   ```bash
   docker compose logs api | grep -i 'loaded extension' | head -5
   ```

   Expected: four lines naming the `auth`, `identity`, `audit`, and `branding` extensions as loaded.

3. **Pre-deactivation SAML providers re-appear in the admin UI.** Sign in as an admin → **SAML SSO** tab → confirm the same `slug`, `display_name`, and `enabled` state as the pre-deactivation snapshot.

4. **Schema confirmation — the 4 `deferred=True` columns are physically present.**

   ```bash
   PGPASSWORD=<pw> psql -h <host> -U <user> -d <db> -c "
     SELECT column_name FROM information_schema.columns
     WHERE table_schema='catalog' AND table_name='oauth_providers'
       AND column_name IN ('idp_entity_id','idp_sso_url','idp_certificate','sp_entity_id');
   "
   ```

   Expected: 4 rows.

5. **SAML provider row count matches pre-deactivation snapshot.**

   ```bash
   PGPASSWORD=<pw> psql -h <host> -U <user> -d <db> -c "
     SELECT count(*) FROM catalog.oauth_providers WHERE provider_type='saml';
   "
   ```

   Expected: same count as pre-deactivation snapshot. Compare against the `pg_dump` snapshot taken in the deactivation runbook's pre-flight.

## End-to-end smoke test

- Open a private browser window, navigate to `/login`, click a SAML provider button, complete the IdP round-trip, and confirm you land back in GeoLens authenticated. If the IdP rejects with `Unsolicited response` for outstanding-request reasons, retry — pending-request state was cleared during deactivation; new logins re-establish it.

## Note on previously converted SAML users

If SAML users were converted to local-password during deactivation (per [`docs/edition-deactivation.md`](edition-deactivation.md) §Handling existing SAML users), those conversions persist after reactivation. Each converted user continues to log in with the local-password credential issued during deactivation — re-mounting the SAML overlay does not automatically re-link them to the SAML provider. Their `users.id`, role memberships, audit history, and dataset ownership are intact (the conversion was non-destructive across `users.id`-keyed records); only the auth path is now `local` instead of `oauth`.

If you want a previously-converted user back on SAML federated SSO, that re-linking is currently a manual procedure — automating reverse conversion (local → SAML on reactivation) is on the deferred roadmap. Operators who need it today can either (a) delete the local user and let the user re-authenticate via the IdP, which JIT-creates a fresh user row (loses any local-only metadata), or (b) manually `INSERT` an `oauth_accounts` row pointing at the SAML provider for the user and flip `users.auth_provider` back to `'oauth'` (preserves all FK history but requires manual SQL).

## Why this works

The 4 SAML columns on `catalog.oauth_providers` are added by `e002_add_saml_columns` (the enterprise alembic head). The ORM declares them `deferred=True, deferred_group="saml"` — when the overlay is absent, default queries never load them, so community deployments work unchanged. The columns and rows persist physically regardless of whether the overlay is loaded; re-mounting only restores the consumer (the SAML router and admin UI) of pre-existing data.

## References

- [`docs/edition-deactivation.md`](edition-deactivation.md) — the inverse procedure; pre-flight `pg_dump` snapshot is the safety net referenced in step 5 of the verification checklist.
- [`docs/saml.md`](saml.md) — SAML setup, IdP configuration, hardening defaults.
