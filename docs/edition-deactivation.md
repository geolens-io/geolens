# Edition Deactivation: Enterprise → Community

> **This runbook is for operators of an enterprise GeoLens deployment who need to downgrade to community edition** (license expiry, contract end, environment teardown, or moving SAML elsewhere). Community deployments do not have the enterprise overlay installed and do not need this procedure.

| | Value |
|---|---|
| Canonical lever | Stop loading the `geolens-enterprise` overlay |
| Defense-in-depth | Set `GEOLENS_EDITION=community` |
| Schema fate (safe path) | 4 SAML columns and SAML rows survive — ready for reactivation |
| Schema fate (destructive path) | `alembic downgrade -1` — see [Destructive path](#destructive-path-permanent-decommissioning) |
| Reactivation | See [`docs/edition-reactivation.md`](edition-reactivation.md) |

## Why overlay-removal is the canonical lever

GeoLens decides at startup whether it is running in `enterprise` or `community` edition. Two signals feed that decision:

1. The `GEOLENS_EDITION` environment variable, when set, wins.
2. Otherwise the runtime infers edition from the presence of registered extensions discovered via the `geolens.extensions` Python entry-point group.

This means `GEOLENS_EDITION=community` makes `is_enterprise()` return `False`, but it does **not** unregister extensions that were discovered at import time. The typed accessors (`get_audit_extension()`, `get_branding_extension()`, `get_auth_extension()`, `get_identity_extension()`) return whatever `register_extensions()` populated in the registry — they do not consult `is_enterprise()`. Setting only the env var leaves the audit-export and branding overlays silently active in the registry.

The complete deactivation lever is at the entry-point discovery layer. Removing the overlay package (or unmounting `docker-compose.enterprise.yml`) means `entry_points(group="geolens.extensions")` returns nothing, the registry is never populated, and `is_enterprise()` flips to `False` because there are no enterprise extensions to find. The runtime overlay install conditional in `backend/scripts/api-entrypoint.sh` makes this explicit:

```bash
if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
    uv add --editable "${ENTERPRISE_PATH}"
fi
```

No `GEOLENS_ENTERPRISE_PATH` → no install → no entry point → no extension. Deactivation is structurally the inverse of activation.

## Data-fate matrix

The data-fate matrix below maps each piece of SAML-related state to its outcome under each scenario.

| Data class | Safe path (overlay removed) | Destructive path (`alembic downgrade -1`) |
|---|---|---|
| `catalog.oauth_providers` SAML rows | preserved | DELETED |
| `catalog.oauth_providers` 4 deferred SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) | preserved (`deferred=True` keeps them off default queries) | DROPPED |
| `catalog.oauth_accounts` SAML linkage rows | preserved | DELETED |
| `catalog.users` rows with `auth_provider='oauth'` | preserved | preserved (`e002.downgrade` does not touch users) |
| Audit log entries for SAML provider mutations | preserved | preserved (audit table is not in `e002` scope) |
| `chk_oauth_providers_type` CHECK constraint | relaxed (still allows `'saml'`) | re-tightened to `('oidc', 'google', 'microsoft')` |

## Pre-flight checklist

Run these steps **before** stopping the enterprise stack. They establish the safety net you will need if anything goes wrong, and they give your SAML-authenticated users a chance to keep their access.

1. **Snapshot SAML state with `pg_dump`.** Copy this command into the deployment shell — it captures every table touched by the destructive path and gives you a restore point even if you only intend to run the safe path:

   ```bash
   pg_dump -h <host> -U <user> -d <db> \
     --table catalog.oauth_providers \
     --table catalog.oauth_accounts \
     --table catalog.users \
     --data-only --column-inserts \
     > saml-state-pre-deactivation-$(date +%Y%m%d).sql
   ```

2. **Inventory live SAML usage.** List every SAML provider currently configured:

   ```sql
   SELECT slug, display_name, enabled, created_at
   FROM catalog.oauth_providers
   WHERE provider_type = 'saml';
   ```

   Then count the SAML-authenticated users so you know how many people will be affected:

   ```sql
   SELECT COUNT(*) AS saml_users
   FROM catalog.users u
   JOIN catalog.oauth_accounts oa ON oa.user_id = u.id
   JOIN catalog.oauth_providers op ON op.id = oa.provider_id
   WHERE op.provider_type = 'saml'
     AND u.auth_provider = 'oauth';
   ```

3. **Communicate to SAML-authenticated users.** See [Handling existing SAML users](#handling-existing-saml-users) below for the conversion procedure. **Order matters:** convert each user *after* the overlay is removed (so `/auth/saml/*` returns 404 and no in-flight SAML login can race the conversion).

4. **Plan a maintenance window.** SAML logins fail immediately when the overlay is removed. Existing JWTs continue to work until they expire (per `ACCESS_TOKEN_EXPIRE_MINUTES`).

5. **Confirm the snapshot is restorable in a sandbox** before proceeding. Restore the dump to a scratch database and run the inventory queries from step 2 to verify completeness.

## Deactivation sequence (canonical path)

### Step 1: Stop the enterprise stack

```bash
docker compose down
```

Use a full container teardown — **not** `docker compose restart`. A restart-without-rebuild can leave the previous container's writable layer holding the editable install of `geolens-enterprise`, which keeps the entry-point discoverable on the next start.

### Step 2: Restart without the enterprise overlay file

```bash
# Community baseline — no -f docker-compose.enterprise.yml
docker compose up -d --build
```

For non-Docker deployments, remove the overlay package directly:

```bash
uv remove geolens-enterprise
# or, if it was pip-installed:
pip uninstall geolens-enterprise
```

### Step 3: Optional defense-in-depth — set the edition env var

```bash
# In your deployment env (e.g., .env or k8s ConfigMap)
GEOLENS_EDITION=community
```

> **`GEOLENS_EDITION=community` alone is incomplete deactivation.** Setting only the env var leaves the audit-export and branding overlays silently active in the registry. This step is defense-in-depth on top of overlay-removal — it makes `is_enterprise()` always return `False` even if a stale overlay accidentally loads. It does **not** replace step 1.

### Step 4: Verify SAML routes are gone

```bash
curl -fsS http://localhost:8000/openapi.json \
  | jq '.paths | keys[] | select(test("/auth/saml/"))' \
  || echo "no SAML routes (expected)"
# Should print nothing (empty result) or "no SAML routes (expected)".
```

### Step 5: Verify admin UI no longer shows the SAML SSO tab

Sign in to the admin UI as an admin user. The **SAML SSO** sidebar entry should be absent. If it is still visible, the overlay is still loaded — return to step 1.

### Step 6: Verify backend logs show community mode

Look for `edition=community` and an empty `features` list in the API startup logs (structured-log fields emitted by `init_edition`). If you see `edition=enterprise` or non-empty features, the overlay is still discovered — return to step 1.

The worker container also receives the overlay; `docker compose down` removes both the API and worker containers symmetrically. No additional worker step required.

## Database state after the safe path

The 4 SAML columns are physically present on `catalog.oauth_providers` (added by `e002_add_saml_columns`). The ORM marks them `deferred=True, deferred_group="saml"` — they are off default queries and only loaded via `select(...).options(undefer_group("saml"))`. Community deployments without the overlay never trigger that load, so the columns are inert. SAML provider rows, `oauth_accounts` linkage rows, and SAML-authenticated `users` rows all remain intact and will be visible again the moment the overlay is reloaded — see [`docs/edition-reactivation.md`](edition-reactivation.md).

## Handling existing SAML users

Existing SAML-authenticated users lose their login path the moment the enterprise overlay is removed (`/auth/saml/*` returns 404). Each affected user must be re-onboarded before they can sign in again. The canonical procedure for v13.2 is **conversion to local-password** via a dedicated admin endpoint that runs every step in a single database transaction — `users.id` is unchanged across the conversion, so every foreign-key reference (`audit_logs.user_id`, `user_roles.user_id`, `datasets.created_by`, `datasets.updated_by`, `api_keys.user_id`, `share_tokens.user_id`, etc.) remains valid by virtue of the user row not moving.

> **Run conversions AFTER the overlay is removed** (steps 1–6 of the canonical path above). Once `/auth/saml/*` returns 404, no in-flight SAML login can race the conversion. Running conversions before deactivation creates a window where a SAML ACS POST may hit a partially-converted user state.

### Step 1: Inventory SAML users

Reuse the inventory query from §pre-flight (extended to project per-user fields for iteration):

```sql
SELECT u.id, u.username, u.email, op.slug AS provider_slug
FROM catalog.users u
JOIN catalog.oauth_accounts oa ON oa.user_id = u.id
JOIN catalog.oauth_providers op ON op.id = oa.provider_id
WHERE op.provider_type = 'saml'
  AND u.auth_provider = 'oauth';
```

Save the result — you will iterate over `(id, username, email, provider_slug)` in step 3.

### Step 2: Decide a conversion target per user

| Target | When to use | Procedure |
|---|---|---|
| **Local-password** | Default. Universal — works regardless of OIDC config state. | Endpoint below (Step 3). |
| **OIDC re-link** | You have an OIDC `oauth_providers` row already configured and the user prefers federated SSO. | Manual procedure — see [Appendix: OIDC conversion (manual)](#appendix-oidc-conversion-manual). |

### Step 3: Run the conversion endpoint per user

First, obtain an admin JWT against the local-password admin login flow (replace `$ADMIN_USER` / `$ADMIN_PASSWORD` with your admin credentials — these are set via `GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD` env vars):

```bash
TOKEN=$(curl -fsS -X POST http://localhost:8000/auth/login/ \
  -d "username=$ADMIN_USER&password=$ADMIN_PASSWORD" \
  | jq -r .access_token)
```

Then convert each SAML user (the trailing slash on the URL is mandatory — without it FastAPI returns a 307 redirect that may drop the JSON body):

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "<temp-strong-password>"}' \
  http://localhost:8000/admin/users/<user-id>/convert-saml-to-local/
```

A successful response (HTTP 200) is the user's `UserResponse` payload with `auth_provider` reflecting the new `"local"` state. The endpoint, in a single transaction:

- Validates the user is currently SAML-authenticated (`auth_provider='oauth'` AND has an `oauth_accounts` row pointing at a `provider_type='saml'` provider). Otherwise 422.
- Sets `users.password_hash` to a bcrypt hash of the supplied password.
- Flips `users.auth_provider` from `'oauth'` to `'local'`.
- Deletes the user's `oauth_accounts` row pointing at the SAML provider. The SAML `oauth_providers` row itself is preserved — other users may still link to it post-reactivation.
- Writes one `audit_log` entry with `action='user.convert_saml_to_local'` and `details={"from": "saml", "to": "local", "provider_slug": "<slug>"}`. Password material is never logged.

All steps run in one transaction; any failure rolls back without writing the audit-log row.

> **Self-conversion is blocked.** If `<user-id>` matches the admin invoking the call, the endpoint returns 422 (`Cannot convert your own account; use a different admin account`) — this prevents an admin from fat-fingering their own new password and locking themselves out of the deployment. Use a second admin account when you need to convert your own.

### Step 4: Communicate the new credentials out-of-band

Choose a secure delivery channel for the temporary password (encrypted email, password manager share, in-person credential drop). Each user logs in to `/login` using their existing username and the new local-password credential. Encourage users to change the password immediately after first login via the standard self-service flow.

### Step 5: Verify the user can log in

Smoke-test one converted user before notifying the rest:

```bash
curl -fsS -X POST http://localhost:8000/auth/login/ \
  -d "username=$USERNAME&password=<temp-strong-password>"
```

Expected: HTTP 200 with `access_token`. If you receive 401, confirm the conversion endpoint returned 200 in step 3 and the user supplied the temporary password verbatim (no surrounding whitespace).

### Step 6: Confirm the audit trail recorded the conversion

```sql
SELECT user_id, action, resource_id, details
FROM catalog.audit_logs
WHERE action = 'user.convert_saml_to_local'
ORDER BY created_at DESC
LIMIT 10;
```

Each conversion produces exactly one row. The `user_id` field is the admin who performed the conversion; `resource_id` is the user being converted; `details` is the allow-listed dictionary with `from`, `to`, and `provider_slug`. If a row is missing for a conversion you ran, the underlying transaction rolled back — re-run the conversion after investigating the response payload from step 3.

### Appendix: OIDC conversion (manual)

If your deployment has an OIDC `oauth_providers` row configured and a user prefers federated SSO over local-password, OIDC conversion has no automated endpoint in v13.2 (deferred to a future polish phase). The manual procedure:

1. Have the user run the OIDC enrollment flow from their perspective — sign in via the OIDC provider button on `/login`. GeoLens JIT-creates a new `oauth_accounts` linkage row pointing at the OIDC provider for that user.
2. Manually delete the user's SAML `oauth_accounts` row via SQL — match on `user_id` AND the SAML `provider_id`.
3. The user's `auth_provider` stays `'oauth'`; their `users.id` is unchanged; their audit history and role memberships remain intact.

Automating this two-step procedure is on the deferred roadmap — this manual procedure exists for operators who want OIDC-federated continuity instead of local-password during the v13.2 lifecycle.

## Destructive path: permanent decommissioning

> **The `alembic downgrade -1` path is destructive and irreversible without the `pg_dump` snapshot.** Use only when you need a clean schema (permanent license revocation AND your audit team requires no SAML data residue). For temporary deactivation, the safe path above is sufficient — the schema does no harm and reactivation is a clean re-mount.

`e002_add_saml_columns.downgrade()` performs the following operations in this exact order:

1. `DELETE FROM catalog.oauth_accounts WHERE provider_id IN (SELECT id FROM catalog.oauth_providers WHERE provider_type='saml')` — every SAML user's linkage row is dropped.
2. `DELETE FROM catalog.oauth_providers WHERE provider_type='saml'` — every SAML provider row is dropped.
3. The relaxed `chk_oauth_providers_type` CHECK is dropped.
4. The strict `chk_oauth_providers_type` CHECK is recreated as `provider_type IN ('oidc', 'google', 'microsoft')`.
5. The 4 SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) are dropped from `catalog.oauth_providers`.

### Mandatory pre-step: pg_dump snapshot

This step is **mandatory and required**. Without it, the deletion is unrecoverable.

```bash
pg_dump -h <host> -U <user> -d <db> \
  --table catalog.oauth_providers \
  --table catalog.oauth_accounts \
  --table catalog.users \
  --data-only --column-inserts \
  > saml-state-pre-destructive-$(date +%Y%m%d).sql
```

Confirm the dump is restorable in a sandbox before proceeding.

### Run the alembic downgrade

```bash
uv run alembic downgrade -1
```

After the downgrade completes, the schema matches the community baseline: no SAML columns, no SAML provider rows, and the `provider_type` CHECK rejects new SAML inserts.

## Audit log limitation

Edition deactivation is not currently audit-logged at the platform level — operator-side change tickets are the audit trail. A future enhancement will emit a `lifecycle.deactivated` audit entry on `init_edition()` transitions when the cached edition changes between starts.

## References

- [`docs/edition-reactivation.md`](edition-reactivation.md) — community→enterprise re-upgrade procedure and post-reactivation verification.
- [`docs/saml.md`](saml.md) — SAML setup, IdP configuration, and SAML-side cleanup pointers (disable the SAML app at the IdP after GeoLens-side deactivation).
