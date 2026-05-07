# Changelog

All notable changes to GeoLens are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

GitHub release notes are generated from this file, so `CHANGELOG.md` is the release-note source of truth.

> **Note on version history.** GeoLens 1.0.0 marks the first public release. Prior to 1.0.0, the project was internally versioned as 2.0 → 14.0 during pre-public development. The legacy entries below 1.0.0 are preserved for historical context only — they do not represent prior public releases. There is no migration path from any pre-1.0.0 version; 1.0.0 is the first version anyone outside the project has run.

## [Unreleased]

> Pre-public-release security & audit hardening sweep. 17 audit dimensions
> reviewed; all Critical and High findings remediated inline. Recommend a
> 1.1.0 minor bump on the next public release to signal the breaking changes
> below.

### Changed (BREAKING)

- `PUT /maps/{id}/thumbnail/` request body changed from `text/plain` raw
  `data:image/...` string to `application/json` `{"data_uri": "..."}`.
  Required to enable Python SDK generation (the `text/plain` body shape was
  silently dropped by `openapi-python-client`). Custom callers must send
  `Content-Type: application/json` with `{"data_uri": "data:image/png;base64,..."}`.
  Internal SDKs (`pip install geolens`, `@geolens/sdk`) at 1.0.2+ already use
  the new shape.
- Lowered max `limit` query parameter from 1000 to 200 on OGC Features
  `/items`, STAC `/collections/{id}/items`, STAC `/search` (GET+POST), and
  `/datasets/{id}/features`. Use the new `after_gid` keyset cursor for paging
  through large result sets — see `### Added` below. Offset-based paging
  remains supported as a legacy path.

### Added — Map Builder API surface

The Map Builder feature shipped 10 new public routes between v1.0.0 and the
upcoming v1.1.0 tag. All routes are documented in `/api/docs` and exposed
through the auto-generated `geolens` (Python) and `@geolens/sdk`
(TypeScript) SDKs.

- `POST /maps/import` — Import a MapLibre style JSON document into a new
  GeoLens map. Accepts a typed `MapStyleImportRequest` body (Pydantic v2,
  `extra="allow"` for forward-compat MapLibre fields). Per-layer dataset
  access is enforced via the existing RBAC layer; inaccessible datasets
  return 403 with the offending dataset IDs in the detail.
- `GET /maps/{map_id}/style.json` — Export a saved GeoLens map as a
  complete MapLibre style JSON document, ready to round-trip through
  `POST /maps/import` or feed into any MapLibre client.
- `PATCH /maps/{map_id}/layers` — Apply incremental layer changes (added,
  updated, removed, reorder) without a full PUT replacement. Body is a
  `MapLayerDiffRequest` with `added`/`updated`/`removed`/`order` arrays
  plus a `fallback_full_replace` client hint. Avoids the lost-write
  problem of full PUT for concurrent builder edits.
- `GET /maps/{map_id}/history` — Return recent builder edit history for a
  map (paginated, owner/admin only). Each event records actor, target,
  action, summary, and a structured details bag for the History panel.
- `GET /maps/icons` — List reusable map icons (bundled defaults plus
  user-uploaded). Powers the symbol-layer icon picker.
- `POST /maps/icons` — Upload a reusable SVG or PNG icon for symbol
  layers. SVG uploads are validated through `defusedxml` and re-serialized
  to defeat attribute-encoding bypasses (SEC-09 / Phase 273).
- `GET /maps/icons/{icon_id}/asset` — Serve an uploaded or bundled icon
  asset by stable icon ID. SVG responses carry
  `Content-Security-Policy: default-src 'none'; sandbox` (SEC-01 /
  Phase 273) so an uploaded SVG cannot fetch other origins, run scripts,
  or read auth cookies even if validation is bypassed in the future.
- `GET /maps/sprites/geolens.json` — Serve the stable GeoLens sprite
  JSON index. Used by MapLibre to map sprite IDs to atlas coordinates.
- `GET /maps/sprites/geolens.png` — Serve the generated GeoLens sprite
  sheet. Cache-Control: `public, max-age=3600`.

(Continuation) `POST /ingest/manifest/apply` was first announced in
[1.0.1]; the route is now part of the auto-generated SDKs and accepts a
typed `ManifestApplyRequest` body. See [1.0.1] § "Manifest-driven catalog
automation" for the full feature description.

### Added

- New CLI auth flags: `scripts/seed-natural-earth.py` accepts
  `--username`/`--password` and mints a temporary API key for the run
  (cleaned up on exit). Replaces the pre-existing `--api-key` flow that
  required operators to mint a key out-of-band.
- `after_gid` keyset cursor on `/datasets/{id}/features` and OGC Features
  `/items` endpoints. The `rel=next` link emits a keyset URL when a page is
  full, providing constant-time pagination over large catalogs.
- Per-dataset `tile_columns` attribute allowlist (new
  `catalog.datasets.tile_columns` array column, Alembic revision `0012`).
  Defaults to no attribute columns at z<10 to bound MVT tile size for wide
  schemas.
- Public operator runbook stubs at `docs/saml.md`,
  `docs/edition-deactivation.md`, `docs/edition-reactivation.md` (full
  enterprise runbooks live in the private overlay; stubs link out).
- New Alembic revisions: `0008_refresh_tokens_expires_idx`,
  `0009_audit_logs_indexes`, `0010_trgm_search_indexes`,
  `0011_record_embeddings_hnsw_idx`, `0012_dataset_tile_columns`.
- Extended `@pytest.mark.perf` coverage to OGC Records, OGC Features, STAC
  landing/collections, and ingest-upload latency budgets (perf-marker count
  5 → 14).

### Changed

- Composite indexes on `audit_logs(created_at DESC, action, resource_type)`
  and `audit_logs(resource_id)` to keep admin filter+sort hot paths fast.
- pg_trgm GIN trigram indexes on `lower(unaccent(records.title))`,
  `records.summary`, `records.keywords`, and `maps.name` so ILIKE+unaccent
  search no longer seq-scans.
- HNSW vector index for `record_embeddings.embedding` is now created in
  Alembic migration `0011`. Previously it was lazy-created at first
  embedding-backfill run, which left fresh installs with no index.
- Index added on `refresh_tokens.expires_at` for cleanup DELETE.
- Tile pool now drops to the `geolens_reader` role on every connection
  checkout via a `SET ROLE` setup callback. Previously it ran as the
  privileged app user.
- TTL LRU cache (300s) for query embeddings keyed on
  `(query_text.lower(), model_name)` reduces redundant embedding API calls.
- Helm chart `secret.yaml` env name renamed `SECRET_KEY` → `JWT_SECRET_KEY`
  to match Pydantic Settings (previously broke deploys silently).
- Per-service memory caps in `docker-compose.yml` matching the documented
  2GB VPS budget.
- README adds §"Add Your First Dataset" with the manifest-driven
  `geolens init/validate/apply` flow + cross-link from Demo Mode to the
  `examples/manifests/first-catalog/` example. README §Demo lists Manhattan
  Skyline (was missing).
- CONTRIBUTING.md project tree synced to current `modules/` / `platform/` /
  `processing/` / `standards/` layout. Test commands updated to flat
  backend test directory (replaced stale `tests/unit` / `tests/api` paths).
- `StyleJsonDialog` and `ImportSummary` user-facing strings wrapped via
  `useTranslation('builder')`; new `builder.styleJson.*` block with i18next
  plural keys ships in en/es/fr/de.
- `alembic check` filter for known SAML overlay drift; new H-06/H-07/H-09
  indexes declared in SQLAlchemy models so drift-as-CI-gate is usable.
- CI `e2e-test` job rationale documented inline in
  `.github/workflows/ci.yml` and `.github/CONTRIBUTING.md` (cron-revival
  path noted). New `npm run e2e:smoke:audit` script wires up 5 previously
  unreferenced E2E specs.
- Co-located smoke tests added for `AdminUsersPage`, `AdminAuditPage`, and
  `AdminSettingsPage`.

### Removed

- Duplicate `backend/Dockerfile` deleted. The canonical multi-stage root
  `Dockerfile` is the single source.

### Fixed

- README quickstart's `seed-natural-earth.py --api-key admin` example
  could not work as written — `admin` is a username, not an API key, and
  no API key was created at bootstrap. The seed script now supports
  `--username`/`--password` (mints + cleans up a temp API key) so the
  documented one-line invocation succeeds against a fresh `docker compose
  up` deployment.
- Tile MVT SQL gained `LIMIT 50000` per-tile feature cap and per-zoom
  geometry simplification extended through z<10. The existing perf marker
  only exercised z=0 single-row paths, masking regressions on real-world
  wide datasets.
- `/maps/{id}/layers/` (with trailing slash) and `/maps/icons/` (with
  trailing slash) previously returned a misleading 405/422 because they
  shadowed `/maps/{map_id}` parameter routes. The trailing-slash variants
  are removed; use `/maps/{id}/layers` and `/maps/icons` (no slash).
- Replaced unowned `geolens.io` domain references with `getgeolens.com` in
  `sdks/python/pyproject.toml` author email, `cli/pyproject.toml` author
  email, and `.env.demo` demo-sandbox host comments. PyPI metadata for
  already-shipped 1.0.x wheels is immutable; the next published version
  will carry the corrected author email.
- Corrected widget developer guide path: `frontend/docs/widgets.md`
  referenced `src/components/widgets/` but the directory is named
  `src/components/map-widgets/`.
- Manifest `local://` source URI parsing now rejects `..` traversal
  segments and validates the resolved path is under `upload_staging_dir`,
  closing a server-side file-read primitive that any user with `upload`
  permission could exploit.
- `e2e/dataset-detail.spec.ts` had two undocumented `test.skip()` calls
  masking editable-field/validation regressions on a top-3 user flow. One
  obsolete skip was deleted; one was re-skipped with a documented
  rationale and a follow-up todo for the next test-cleanup milestone.

### Security

- `.env.demo` boot guard now refuses production use unless
  `GEOLENS_DEMO_MODE=true` is set explicitly. Prevents accidental deploys
  with hardcoded demo credentials and the well-known JWT signing key.
- OAuth `redirect_uri` resolution now requires an explicit `PUBLIC_APP_URL`
  for OAuth flows. The previous fallback to the request `Origin`/`Host`
  header was vulnerable to host-header injection from non-browser clients.
- JWT secret length validator now rejects known-public example values (the
  `.env.example` default and similar). Operators booting with such a value
  must regenerate via `openssl rand -hex 32` — `.env.example` ships with an
  empty `JWT_SECRET_KEY=` to force the choice.
- OAuth email-match auto-link now requires `email_verified=True` from the
  IdP. Previously, accounts could be silently linked on any matching email,
  enabling account takeover via IdPs that allow unverified emails.
- Embed-token `Origin: http://localhost` bypass scoped to loopback TCP
  peer source. Previously honored from any caller, allowing trivial
  domain-locking bypass from non-browser callers.

## [1.0.2] - 2026-05-05

### Added

- GitHub-ready GeoLens organization avatar asset sized to GitHub profile image
  guidance.

### Changed

- Synchronized backend, frontend, CLI, and SDK package metadata for the
  sanitized public-release tag.
- Enterprise-only SAML and lifecycle operator runbooks now live with the private
  `geolens-enterprise` source; public docs keep short ownership stubs only.
- AWS Marketplace environment examples moved out of the public `.env.example`
  and into the enterprise overlay documentation.
- Public issue and discussion templates now use `v1.0.2` examples and generic
  cloud image wording instead of pre-public version or AWS Marketplace labels.

## [1.0.1] - 2026-05-04

### Added

- Manifest-driven catalog automation: schema validation, CLI init/validate/apply commands, backend manifest apply endpoint, example manifests, and generated SDK surfaces.
- Root multi-stage Dockerfile targets for API, worker, and frontend containers.
- Focused CI gates for manifest CLI contracts, backend apply contracts, OpenAPI drift, SDK drift, and published-package verification.

### Changed

- Map and search services were decomposed behind stable facade modules with architecture guards to prevent direct imports of private split modules.
- Advanced sharing, permission, workflow, AI provider, and embedding provider extension contracts were tightened for the open-core boundary.
- Documentation now covers CLI manifest workflows, SDK manifest apply support, and CI verification commands.

### Fixed

- Public map raster tile URL resolution for VRT datasets.
- DEM terrain tiles no longer apply an incorrect rescale path for terrainrgb output.
- Builder styling test locators were hardened for the labels switch flow.

## [1.0.0] - 2026-05-03

### Added — Public package distribution (2026-05-03)

- **Python SDK published to PyPI as `geolens==1.0.0`.** Install with `pip install geolens`; the generated SDK exposes the hand-written `GeolensClient` auth wrapper plus the OpenAPI-generated endpoint clients.
- **CLI published to PyPI as `geolens-cli==1.0.0`.** Install with `pip install geolens-cli`; the executable command remains `geolens`.
- **TypeScript SDK published to npm as `@geolens/sdk==1.0.0`.** Install with `npm install @geolens/sdk`; the package exports `createGeolensClient`.
- **Prebuilt API and frontend images published to GHCR.** Pull `ghcr.io/geolens-io/geolens-api:1.0.0` and `ghcr.io/geolens-io/geolens-frontend:1.0.0`; the same images are also tagged `1.0`, `1`, and `latest`.
- **Clean-machine package verifier added.** `.github/workflows/verify-published.yml` installs `geolens`, `geolens-cli`, and `@geolens/sdk` inside fresh Docker containers and smoke-tests the runtime exports.

### Changed — Pre-public migration squash (2026-05-02)

- **Alembic migration chain squashed from 23 migrations to 2** (`0001_baseline` + `0002_procrastinate`). The pre-public chain `0001_fdn` → `0002_tbl` → `0003_prc` → ... → `t6u7v8w9x0y1` collapses into a single application-schema baseline plus the procrastinate queue infrastructure migration kept separate. Verified by round-tripping every migration against a throwaway database and diffing the resulting `pg_dump` schema-only output against the squashed-baseline output: all 37 tables / 39 indexes / 24 functions / 8 triggers / 3 sequences / 3 types match 1:1; remaining diff is column-ordering only (no functional impact).
- **Existing pre-1.0.0 dev databases** must run a one-shot `UPDATE catalog.alembic_version SET version_num = '0002_procrastinate'` to align with the new chain (alembic-stamp won't work because the prior revision IDs are no longer in the script directory). New clean installs run the 2-migration baseline directly. Per the existing changelog header, no migration path from any pre-1.0.0 version is supported by GeoLens 1.0.0+.

### Fixed — Model ↔ DB drift (2026-05-02)

Resolved 5 instances of model-vs-DB drift uncovered by the migration squash. The squashed baseline now produces the model-defined schema (clean installs) and the SQLAlchemy models accurately describe what's in the database:

- `AITokenUsage.input_tokens` / `output_tokens` — added `server_default="0"` to model (DB had it; model didn't).
- `Record.language` — added `server_default="en"` to model (DB had it; model didn't).
- `MapShareToken.token_hint` — removed `server_default="***"` from model (DB doesn't have it; the migration that created the column did not set a default).
- `MapShareToken.token_hash` — moved inline `unique=True` to a named `UniqueConstraint("token_hash", name="uq_map_share_tokens_token_hash")` in `__table_args__` so the constraint name matches the live DB.
- `Map.chk_maps_visibility` — the live DB's constraint had a stale `'unlisted'` value the model never knew about and no application code ever produced. Tightened the live DB constraint to the model's 3-value form (`'private', 'public', 'internal'`); no rows were affected.

Two further "drift" items are intentional open-core boundaries and are preserved as fixups in `0001_baseline.upgrade()`:

- `OAuthProvider.chk_oauth_providers_type` — the model declares the OSS+enterprise *union* (`'oidc', 'google', 'microsoft', 'saml'`); the OSS baseline narrows the constraint to OSS-only values; enterprise migration `e002_add_saml_columns` re-adds `'saml'` when the overlay is loaded.
- `OAuthProvider` SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) — the model declares them with `deferred=True` so the OSS overlay never selects them; the OSS baseline does not create them; enterprise migration `e002_add_saml_columns` adds them.

### Added — Open-core boundary cleanup (2026-04-30)

- **`AuditSink` Protocol** (Phase 222) — write-side hook for audit-event emission, sibling to the existing `AuditExtension` (read-side export-format gating). Defined in `backend/app/platform/extensions/protocols.py`; default implementation (`DefaultAuditSink`) writes one `audit_logs` row per emit. Enterprise overlays subscribe by appending to `_extensions["audit_sinks"]` via `setdefault + append`. New facade `audit_emit(session, event)` in `backend/app/modules/audit/service.py` wraps each sink in per-sink try/except + `structlog.exception()` so a failed sink never rolls back the surrounding business operation. Mechanically rewrote 65 `log_action(...)` call sites across 19 files to use the new facade. New `make audit-sink-discipline` Makefile target enforces the invariant that no application code calls `log_action()` directly.
- **`BillingExtension` Protocol** (Phase 223) — startup hook for billing-system registration. Defined in `backend/app/platform/extensions/protocols.py` with signature `async def on_startup(self, app: FastAPI) -> None`. Default implementation (`DefaultBillingExtension`) is a no-op. The FastAPI lifespan dispatches each registered extension under `asyncio.wait_for(timeout=10.0)` with per-extension try/except so a hung or buggy overlay cannot block startup or crash the application. The `geolens-enterprise` overlay's `MarketplaceBillingExtension` registers the AWS Marketplace `RegisterUsage` call via this seam.
- **`make billing-extraction-discipline`** Makefile target — architecture guard asserting `app.core.marketplace` is no longer importable from any `backend/app/` module.

### Changed — Open-core boundary cleanup (2026-04-30)

- **AWS Marketplace metering moved out of core** — `backend/app/core/marketplace.py` deleted (the 30-line `register_marketplace_usage` body relocated verbatim to `geolens-enterprise`'s `MarketplaceBillingExtension._register`). The lifespan startup block at `backend/app/api/main.py:184-203` is now a generic `for ext in get_billing_extensions(): ...` dispatch loop that fires zero AWS API calls in community deployments.
- **`AWS_MARKETPLACE_PRODUCT_CODE` and `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` are now enterprise-overlay-only env vars.** Removed from `backend/app/core/config.py:Settings`. The enterprise overlay reads them directly via `os.environ.get(...)` and short-circuits when unset. Operators of the open-core community edition no longer have these settings on the core `Settings` surface.

### Removed — Open-core boundary cleanup (2026-04-30)

- **`backend/app/core/marketplace.py`** — file deleted. AWS Marketplace billing is now exclusively an enterprise-overlay concern.
- **`Settings.aws_marketplace_product_code` / `Settings.aws_marketplace_public_key_version`** — removed from core `Settings`.

### Migration notes — Open-core boundary cleanup

- **Community deployments:** no action required. The marketplace block at `api/main.py:184-203` was inert when `AWS_MARKETPLACE_PRODUCT_CODE` was unset (the default for all community deployments); replacing it with a no-op dispatch loop preserves that behavior byte-identically.
- **Enterprise deployments running the AWS Marketplace AMI:** install the `geolens-enterprise` overlay (already required for SAML/audit-export); the new `MarketplaceBillingExtension` registers automatically via the existing `geolens.extensions` entry-point group. Set `AWS_MARKETPLACE_PRODUCT_CODE` and (optionally) `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` exactly as before — the env-var contract is unchanged. The overlay reads them directly; core no longer does.

### Added — Open-core separation (2026-04-29)

- **`geolens` CLI** (Apache-2.0) — standalone command installed from the `geolens-cli` Python package; supports `login` (OS keyring + `--no-keyring` headless fallback), `scan <dir>` (vector + raster file detection), `publish <file>` (SDK-driven 3-step ingest), `export stac <id>` (STAC API 1.0 raster metadata). Source at `cli/`; published to PyPI as `geolens-cli`.
- **Python + TypeScript SDKs** auto-generated from `backend/openapi.json` — `geolens` (Python via `openapi-python-client`) and `@geolens/sdk` (TypeScript via `@hey-api/openapi-ts`). Source at `sdks/python/` and `sdks/typescript/`; published to PyPI/npm via `.github/workflows/publish-sdks.yml`. Regenerate via `make sdks`; `make sdks-check` is a CI drift gate.
- **Extension hook for enterprise overlays** — `backend/app/core/identity.py` defines `IdentityProtocol`, `RoleProtocol`, and `IdentityExtension`; `backend/app/platform/extensions/__init__.py` exposes `get_identity_extension()` typed accessor. Overlays register via `importlib.metadata` entry_points. The companion `geolens-enterprise` package uses this seam to provide SAML SP-initiated SSO with assertion validation, JIT provisioning via `find_or_create_oauth_user()`, and audited attribute→role mapping.
- **`backend/openapi.json` snapshot committed** as the SDK source of truth — reproducible SDK regeneration from this artifact.
- **SDK and CLI documentation** — user-facing documentation for SDK + CLI surfaces including install, auth modes, exit codes, and known rough edges lives at docs.getgeolens.com.
- **SAML operator documentation** — install + per-IdP configuration walkthroughs, hardening posture, multi-instance limitations, and NameID format guidance for the optional `geolens-enterprise` SAML overlay.

### Changed — Open-core separation (2026-04-29)

- **Open-core boundary closed** — `backend/app/core/` no longer imports from `backend/app/modules/settings/`; `AppSetting` model relocated to `backend/app/core/db/models.py`. New architecture-guard test in `backend/tests/test_layering.py` prevents regression.
- **`backend/app/modules/auth/visibility.py` removed** — visibility/authorization logic moved to `backend/app/modules/catalog/authorization.py`. 23 inbound callers migrated; dataset-visibility semantics unchanged.
- **`IdentityProtocol` introduced** — 51 cross-domain `User` import sites retyped to depend on `Identity` (the Protocol alias) rather than the concrete `User` ORM model. Allowlist guard at `test_layering.py:237` keeps 18 SQL-attribute files on the concrete model. Enables enterprise overlays to register custom identity backends without modifying core.
- **OAuth IdP→role mapping is now enterprise-only** — `group_claim` and `group_role_mapping` are rejected by `OAuthProviderCreate`/`OAuthProviderUpdate` schemas with `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` in community deployments; only applied at the service layer when `is_enterprise()` returns True. Pre-existing OAuth providers without group mapping are unaffected.

### Note on SAML availability

The "**SAML support has been removed**" entry below remains accurate for the **community edition** — the dead scaffold (XML metadata parser, broken `provider_type='saml'` accepted but non-functional, 4 unused `oauth_providers` columns) is gone from core. As of v13.1, working SAML is available via the optional `geolens-enterprise` overlay, which registers via the new auth-extension hook. The community edition is unchanged: no SAML controls in admin UI, `/admin/saml` returns 404, no `provider_type='saml'` accepted by API.

### Security

- **BREAKING: `JWT_SECRET_KEY` must now be at least 32 characters.** The backend validates the length at startup; shorter values fail fast with an actionable error. HS256 requires ≥ 256 bits of entropy — shorter secrets were brute-forceable. See the [upgrade guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) for rotation instructions. The `.env.example` default passes unchanged; only deployments with custom short secrets are affected.
- Secret fields (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `S3_SECRET_ACCESS_KEY`, `TILE_SIGNING_SECRET`) now use Pydantic `SecretStr` internally. Values are masked (`**********`) in `repr()`, structured-log dict coercion, and `ValidationError` output — they can no longer leak into exception traces or log lines by accident. Downstream behavior is unchanged; values are unwrapped via `.get_secret_value()` only at the library boundary (JWT encode/decode, HMAC tile signing, Fernet KDF, boto3, Anthropic/OpenAI clients).
- New `reveal()` helper in `app/config.py` centralizes `SecretStr | None → str | None` unwrapping for optional credential fields.

### Added
- Astro-based marketing site scaffold (phases 212-214)
- `seed_tiles` CLI script for pre-seeding Redis tile cache
- Public map viewer UX improvements and legend unification
- 3D data and maps support feasibility design doc
- `LOG_LEVEL` value validation at startup: typos like `LOG_LEVEL=verbose` now fail fast instead of crashing the stdlib logger at first call.
- `ENV_ONLY_CONFIG` and `GEOLENS_EDITION` documented in `.env.example` (previously undocumented but referenced in code and the admin UI lockdown banner).

### Removed
- **SAML support has been removed.** The OAuth provider system shipped with `provider_type='saml'` accepted by the API but no working SAML login flow ever existed (only an XML metadata parser). An admin could create a SAML provider and have it appear on the login page, but clicking it produced no authentication. The dead code path has been removed across the stack:
  - `provider_type='saml'` is no longer accepted by the OAuth API; the database CHECK constraint has been tightened to `('oidc', 'google', 'microsoft')`.
  - The `oauth_providers` table loses 4 columns: `idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`. Any pre-existing SAML provider rows are deleted by the migration before the constraint tightens.
  - The `chk_users_auth_provider` constraint on `users.auth_provider` is also tightened to `('local', 'oidc', 'oauth')`.
  - The `app/auth/saml/` Python module (XML metadata parser) is removed.
  - The admin UI no longer offers SAML in the OAuth provider dropdown; the metadata-XML upload field, SP Entity ID, and ACS URL display are removed.
  - SAML i18n keys are removed from all 4 locales (en, es, de, fr).

### Changed
- Landing page removed — root route (`/`) now serves the Search page directly. The previous `/search` route is no longer used; existing bookmarks redirect to `/`.
- `SHOW_LANDING_PAGE` environment variable removed from backend config and branding API.
- Internal documentation moved out of the public repository tree; user-facing docs live on docs.getgeolens.com.
- Connection pool pre-ping now defaults to `True` to detect broken connections in managed databases.
- Top-level `CONTRIBUTING.md` consolidated into `.github/CONTRIBUTING.md`.
- OAuth `client_id` and `client_secret` are now required fields when creating a provider (previously optional placeholders for the SAML branch).
- `backend/.env` symlink removed. `app/config.py` now resolves the project-root `.env` via `Path(__file__).resolve().parents[2] / ".env"` so host-side workflows (`cd backend && uv run pytest|uvicorn|alembic`) continue to work without the symlink.
- `VITE_API_PROXY_TARGET` renamed to `API_PROXY_TARGET` in `docker-compose.yml` (frontend service) and `frontend/vite.config.ts`. The old name still works for one release via a fallback in `vite.config.ts` — local compose overrides can migrate at leisure. The var is only consumed by the Node-side Vite dev-server proxy and was never exposed to the browser bundle, so the misleading `VITE_` prefix has been dropped.
- Settings `model_config` is now a typed `SettingsConfigDict` (Pydantic v2) so typos in config keys fail at mypy/runtime instead of being silently ignored.
- `.env.example` cleanup: deprecated `PUBLIC_BASE_URL=...` active default commented out; `API_PORT` and `FRONTEND_PORT` gained per-variable comments matching the rest of the file; `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB_TEST` now carry a pointer to `.env.test.example` for host-side test runs.

### Fixed
- `app/main.py:193` S3 health-check error-branch typo: `settings.s3_endpoint_url` (which does not exist) corrected to `settings.s3_endpoint`. The bug was pre-existing; it would have crashed the app with `AttributeError` the first time the S3 startup health check actually failed, masking the real S3 error behind an unrelated traceback. Found and fixed during the env-audit post-implementation review.
- CI E2E workflow sed commands were silently no-op'ing: they targeted empty values (`^VAR=$`) that never existed in `.env.example`. The patterns were rewritten to match any value (`^VAR=.*`) so the E2E job actually injects the CI-distinct secrets it claims to set. CI `JWT_SECRET_KEY` values were also padded to ≥ 32 characters so the new length validator passes in CI. The 1879-test full backend suite continues to pass.
- Test infrastructure: removed brittle `os.environ.setdefault` / `del sys.modules["app.config"]` blocks from `test_cache.py`, `test_health.py`, `test_metrics.py`, `test_tile_cache.py`, and `test_config.py`. These were workarounds for a module-level import failure that no longer exists now that config.py resolves the project-root `.env` at import time. The old pattern also caused cross-test stale-settings pollution when `test_config.py` ran before `test_auth.py`.
- **Post-impl audit 2026-04-10 follow-ups:**
  - **S1 — source `geom`/`geometry` column collision (P1):** vector uploads with an attribute literally named `geom` or `geometry` no longer crash `ogr2ogr` at CREATE TABLE time. `run_ogr2ogr`/`run_ogr2ogr_service` now use `GEOMETRY_NAME=_geolens_geom` as a placeholder, which `ensure_geom_column` renames to `geom` after `rename_reserved_columns` has moved the source attribute to `src_geom`. Regression test lives in `tests/test_ingest_column_preservation.py::test_source_geom_attribute_renamed_to_src_geom`; the `reserved_names.geojson` fixture once again includes a source `geom` attribute.
  - **S2 — cross-module mypy cleanup (P1):** resolved 7 errors in `app/datasets/service.py` (including the UUID-vs-Dataset attr-defined errors in `get_related_datasets`), 2 in `app/storage/provider.py`, 2 in `app/public_urls.py`, 6 in `app/audit/service.py`, 3 in `app/maps/service.py`, 3 in `app/persistent_config.py`, and 1 in `app/services/preview.py`. `mypy` is now clean across `app/ingest/`, `app/datasets/service.py`, and the audited supporting modules.
  - **S3 — structured ingest warnings surfaced to the UI (P2):** `JobStatusResponse` now exposes `warnings`, `archive_failed`, and `temporal_parse_errors` alongside the existing `warning_message`. A new `IngestWarningsBanner` component renders reserved-name renames, Shapefile DBF collisions, archive failures, and temporal-parse failures in `JobProgress` on the upload success screen AND permanently on the dataset detail page. A new `GET /jobs/by-dataset/{dataset_id}` endpoint powers the persistent banner by looking up the most recent ingest job for a dataset with visibility filtering. Translations added for en/de/es/fr.
  - **Post-impl audit test coverage gaps closed:** added 31 new tests across the helpers introduced by the audit — `_resolve_effective_srid` (5 tests), `_detect_and_override_geometry` (5), `_archive_original_file` (3), `_bind_task_log_context` (3), `_parse_temporal_fields` (8), `create_vrt_job` (5), `GET /jobs/by-dataset/{id}` (6), and `JobStatusResponse` warning surfacing (6). Keeps every new helper regressible in isolation.
  - **Flaky test resolved:** `test_publish_blocked_when_hard_validation_fails` is no longer flaky. Two back-to-back full-suite runs (1848/1848 each) completed cleanly — the `_geolens_geom` collision fix, transaction/session hygiene changes, and the structlog contextvar clearing in `_bind_task_log_context` likely removed the fixture leakage.
  - **N1 — worker log correlation (P3, R-18/R-24):** each ingest task entry point (`ingest_file`, `ingest_service`, `reupload_file`, `reupload_service`, `ingest_raster`, `ingest_vrt`, `regenerate_vrt`) now binds `job_id` + task name to structlog contextvars so operators can correlate log lines from concurrent uploads without manual grep-stitching.
  - **N2 — validation-failure file retention (P3):** removed the inline `Path(file_path).unlink(missing_ok=True)` on validation failure in `ingest_file`. The `finally` block's retry-preserving cleanup is now authoritative so retryable validation failures keep the local upload around.
  - **N3 — quicklook failure phase (P3):** quicklook commit failures are now tagged with `phase="commit"` vs `phase="generate"` so operators can distinguish "PostGIS query died" from "session commit died" when reading logs.
  - **N4 — HTTPException re-raise ordering (P3):** documented the except clause ordering requirement in `router.upload_file` so future refactors don't silently rewrite 4xx → 500.
  - **N5 — temporal parse errors surfaced to UI (P3):** raster ingest now persists unparseable `temporal_start`/`temporal_end` values to `job.user_metadata.temporal_parse_errors`, which the new warnings banner displays so users know which values were dropped.
  - **K1 — `ingest_file` phase helpers (P3, partial):** extracted `_resolve_effective_srid`, `_detect_and_override_geometry`, and `_archive_original_file` helpers from the 260-line `ingest_file` task body.
  - **K3-PRE — VRT test mock warnings:** `test_vrt_source_management_174.py::TestRegenerateVrtTask` no longer emits `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — `mock_session.add` is now explicitly bound to a synchronous `MagicMock` to match real SQLAlchemy semantics.
  - **K5 — `create_vrt` validation moved to service layer (P3, KISS-10):** `create_vrt_job` lives in `app/ingest/service.py`; the router handler is now a 3-line wrapper.
  - **K7 — `_finalize_ingest` IngestContext refactor (P3, KISS-2):** the 11-parameter signature is now a dataclass. Both `ingest_file` and `ingest_service` construct a single `IngestContext` instead of repeating the call-site noise.
- **Post-impl audit 2026-04-10 (B) follow-ups** — a narrow-scope audit of the above remediation work itself surfaced 22 new findings. 5 were fixed in the original session; the remaining 14 landed as a follow-up pass. Fixes landed in this session:
  - **RESILIENCE-1 (P1):** `_archive_original_file` had an unguarded `session.commit()` inside its best-effort exception block. A transient DB error during archive-metadata persistence (deadlock, pooler drop) would propagate out of the helper and flip the already-successful ingest into a `failed` job via the outer task `except Exception`, triggering Procrastinate retries and potentially producing duplicate datasets. The metadata commit is now wrapped in its own try/except with rollback-on-failure, matching the quicklook commit pattern. Regression test: `test_archive_original_file_commit_failure_does_not_raise`.
  - **KISS-1/CLEANUP-1 (P2):** removed the dead `assumes_4326` parameter from `_resolve_effective_srid` that was being `del`'d immediately on entry.
  - **KISS-3/CLEANUP-3/TYPE-6 (P2):** deleted the unused `IngestJobUserMetadata` TypeScript interface that had zero references in the codebase (the named-key + `[key: string]: unknown` index signature also defeated type safety for the listed fields).
  - **RESILIENCE-3 (P3):** `IngestWarningsBanner` on `DatasetPage` now only renders when `datasetJob?.status === 'complete'`, matching the `JobProgress.tsx` gate. Prevents showing warnings from a failed re-import on the still-functional dataset page.
  - **RESILIENCE-4 (P3):** `_archive_original_file` warning log now includes `dataset_id` as a structured kwarg (previously only embedded in `archive_key`), and the error string is consistently truncated to 500 chars.
  - **TYPE-1/TYPE-2/TYPE-3 (P2 + P3):** closed the backend→frontend ingest-warning contract. `_append_job_warning` now accepts an `IngestJobWarning` TypedDict union (`app/ingest/warnings.py`) built via `make_reserved_rename_warning` / `make_dbf_truncation_warning` producers; `JobStatusResponse.warnings` is a Pydantic discriminated union (`ReservedRenameWarning | DbfTruncationCollisionWarning`) validated per-entry in `_job_to_status_response` — malformed or unknown-kind entries are logged and dropped rather than 500ing the endpoint. `JobStatusResponse.temporal_parse_errors` narrowed to `dict[Literal["temporal_start", "temporal_end"], str]`. New regression tests in `test_jobs_router.py` (unknown-kind drop, temporal-key narrowing) and `test_ingest_ogr_pure.py` (producer→Pydantic round-trip).
  - **RESILIENCE-2 (P2):** `create_vrt_job` now wraps `ingest_vrt.defer_async` in a try/except that marks the already-committed IngestJob `failed` before re-raising, so a Procrastinate outage returns a clean 503 instead of leaving a pending orphan that waits 60 minutes for stale-cleanup. Regression test: `test_defer_failure_marks_job_failed_and_raises_503`.
  - **PERF-1 (P3):** `_extract_common_layer_metadata` now populates `columns` from the target layer's `fields`, so shapefile ingest no longer has to spawn a second `run_ogrinfo_preview` subprocess just to get the column list for the DBF collision detector. The text-fallback path (GDAL < 3.7) still falls through to the preview helper.
  - **PERF-2 (P3):** `useDatasetJobStatus` upgraded from `staleTime: 5 min` to `staleTime: Infinity` + `gcTime: 30 min` since the underlying ingest metadata is immutable once the dataset exists. Stops refetch-on-mount and caches 404 ("no job") responses across navigations.
  - **PERF-3 (P3):** added `index=True` to `IngestJob.dataset_id` in the ORM to match the existing `ix_catalog_ingest_jobs_dataset_id` migration. Prevents Alembic autogenerate from re-adding the index and keeps tests that skip migrations honest about the index.
  - **PERF-4 (P3):** `query_audit_logs` switched from two sequential round trips (list + count) to `COUNT(*) OVER ()` on the main query, halving the endpoint's latency for the audit-log page. Empty-slice pagination still falls back to a count-only query so "page out of range" returns the correct total.
  - **CLEANUP-2 (P3):** inlined the redundant `x_column`/`y_column`/`geom_column` locals in `ingest_file` into the `user_wants_geom` boolean — they were re-derived inside `_detect_and_override_geometry` anyway.
  - **CLEANUP-4 (P3):** `reupload_file` now calls `_archive_original_file` via a new `log_message` + `commit=False` knob, removing the inlined duplicate archive block. The reupload path rides the existing `status=complete` commit so the archive-failed flag is durable without a second round trip.
  - **KISS-2 (P3):** `_detect_and_override_geometry` now returns `str | None` instead of `tuple[bool, str | None]` — the bool was always `True` at the only callsite because the caller guarded on the exact inverse condition. Also added a `_validate_table_name` call at the top (**RESILIENCE-5**) to match the rest of `metadata.py`'s defense-in-depth convention.
  - **TYPE-4 (P3):** annotated `**extra: object` in `_bind_task_log_context` instead of implicit `Any`.
- **Security:** upgraded `anthropic` from 0.86.0 to 0.88.0 to patch CVE-2026-34450 and CVE-2026-34452.
- Pydantic constraints added to user-input string fields (basemaps, OAuth, settings) to prevent oversized payloads.
- Embedding backfill now returns a structured 502 on provider failures instead of swallowing exceptions.
- Embedding stats endpoint guards against missing `record_embeddings` table during early bootstrap.
- Embedding OpenAI client uses `max_retries=2` for transient failure resilience.
- Embedding auto-detect and column rebuild log exceptions instead of swallowing them.
- OGC catch-all 500 handler returns RFC 7807 `ProblemDetail` format.
- Datasets router uses HTTP status constants and explicit return type annotations.
- Last-admin guard extracted to a shared private method to prevent admin lockout regressions.
- Settings updates batched into a single query with deferred commits for performance.
- Branding update now routes through the unified settings endpoint with type alignment.
- Admin router authorization, CBAC, and audit logging hardened (admin audit remediation).
- Builder bug-fix sweep: 68 files, 181 findings from the builder audit (filter persistence, layer styling, drag-and-drop, raster controls).
- Database tuning sweep: PostgreSQL `random_page_cost` and `jit` settings, missing foreign-key indexes added on high-traffic tables, backup service hardening.
- Test audit + post-implementation audit remediation: type safety, resilience, KISS refactors across backend.
- Themed demo seeder (Phase 218) post-implementation audit remediation:
  - Orchestrator now propagates non-zero exit codes when any fixture fails to apply, so Docker Compose correctly reports seeder failures instead of hiding them behind a successful bash exit.
  - `apply_fixture` is idempotent across re-runs: GET-by-name is checked before POST so repeated seeder runs update existing demo maps in place instead of accumulating duplicate catalog entries.
  - Seeder `run-seeder.sh` wrapper now installs a SIGTERM/SIGINT/EXIT trap that rotates the `demo-seed` API key on exit (graceful or abnormal), preventing stale keys from accumulating when the container is killed mid-run.
  - Seeder auth + API-key lifecycle extracted from embedded bash heredocs into a lint-testable `scripts/demo/lib/create_api_key.py` module.
  - Bundled demo data (GeoJSON + CSV) is gzipped after checksum validation in Stage 1 of the seeder Dockerfile and decompressed in-place at container start, shaving ~290 MB off the `/data/demo` layer. Combined with the `uv pip install --system httpx` swap (replacing apt's `python3-pip`) and other layer optimizations, the total shipped seeder image shrunk from **637 MB → 261 MB** (~376 MB total savings). Rasters left untouched because they're already DEFLATE-compressed.
  - World Bank GDP CSV is now fetched via `python3 -c "urllib.request..."` instead of curl inside the Dockerfile's data-fetcher stage. Cloudflare started JA3-fingerprinting and blocking curl on `api.worldbank.org`, returning HTTP 502 for every curl request regardless of headers or TLS version; Python's stdlib `ssl` module presents a different TLS fingerprint that Cloudflare accepts. Only the one affected RUN step was changed — all other upstream fetches (NACIS, source.coop, OpenTopography, OWID, Geofabrik, UCDP, UNHCR) still use curl and still work.
  - Seeder service in `docker-compose.demo.yml` now depends on `worker: service_healthy` in addition to `api: service_healthy`, closing a cold-start race where ingest jobs could be submitted before the Celery worker was ready.
  - `BuilderMap` mirrors the `ViewerMap` `data-tiles-loaded` DOM attribute that flips to `true` on the maplibre `idle` event, giving the Playwright demo-smoke suite a deterministic signal on both the authenticated `/maps/:id` editor path and the anonymous public viewer. Replaces 16 s of arbitrary `waitForTimeout(2_000)` across the 8 required demo maps, so the suite now completes ~17 s faster per run.

### Operators
- Environments that created public raster datasets before the anonymous raster viewer fix may still have `catalog.records` rows stuck at `record_status='draft'`. Review and backfill only those public raster rows before the next release:

```sql
SELECT id, title, visibility, record_status, created_at
FROM catalog.records
WHERE record_type = 'raster_dataset'
  AND record_status = 'draft'
  AND visibility = 'public';

UPDATE catalog.records
   SET record_status = 'published',
       published_at = NOW()
 WHERE record_type = 'raster_dataset'
   AND record_status = 'draft'
   AND visibility = 'public';
```

### Added
- Heatmap visualization mode in map builder with gradient legend, opacity controls, and render mode toggle
- Widget system for map builder — measurement tool, layer legend, basemap picker as sidebar widgets
- Layer adapter infrastructure decoupling render logic from map builder core
- Search result card redesigned with 4-band layout, inline thumbnails, and auto-description
- Map thumbnails migrated from inline base64 to storage with `useMapThumbnail` hook
- Static basemap thumbnail assets replacing generated ImageMagick thumbnails
- Public maps browsing for anonymous users
- VRT mosaic creation button on bulk import review page
- Bulk dataset delete endpoint
- Audit log export endpoint (CSV and JSON)
- Config-ops validate endpoint wired into admin frontend
- Centralized query key factory for TanStack Query hooks
- Heatmap gradient legend with Low/High labels
- Anonymous public browsing support
- `language` field added to records via new Alembic migration
- Design guide token system with status-colors utility and WCAG 2.1 AA compliance

### Changed
- Squashed 12 incremental Alembic migrations into single foundational schema
- Datasets router split into sub-routers with `get_dataset_service_url` helper
- Batched collection and map lookup queries to eliminate N+1 patterns
- Filter editor rebuilt with OR combinator and raw JSON toggle for resilience
- Data-driven styling generalized to support radius and width beyond color
- Comprehensive i18n remediation — formatting standards, RTL support, Unicode handling
- Frontend state management refactored with typed search store and centralized query keys
- Widget placement API redesigned with `WidgetAnchor` and `WidgetPlacement` discriminated union
- Basemap toggle redesigned with thumbnail trigger, labeled popover, and right-opening layout

### Fixed
- ArcGIS preview fetches capped with `result_limit=5` and timeout increased to 120s to prevent 502 errors
- Basemap switching now preserves user layers; stable ref prevents `setStyle` race conditions
- Orphaned basemap layers skipped in `transformStyle` to prevent source-not-found errors
- COG download uses browser-native streaming with authenticated fetch
- Export permission check restored on COG download endpoint
- Non-spatial ArcGIS tables skip spatial post-processing
- Trailing slashes normalized across all API routes
- Collection dataset response aligned with canonical dataset response
- AI rate limiting and raster RBAC parity
- OGC/STAC/DCAT standards compliance gaps resolved
- Docker config hardened — restart policies, security headers, PostGIS image pinned to 17-3.5
- PostgreSQL tuned with `random_page_cost=1.1` and `jit=off`
- Missing foreign key indexes added on high-traffic join/cascade tables
- `BuilderMap` mousemove throttled with `requestAnimationFrame`
- Embedding client cached with LLM timeouts to prevent event loop blocking
- OOM risks fixed in S3 upload and reupload file hash
- Deprecated `HTTP_422_UNPROCESSABLE_ENTITY` references replaced
- Raster and spreadsheet types included in default allowed extensions

## [14.0] - 2026-03-30

> *Internal pre-public version. Most marketing-site content listed here was relocated to the [getgeolens.com](https://github.com/geolens-io/getgeolens.com) repo before public release; only the core fixes below remained in this codebase.*

### Fixed
- Shared map raster tile URL path resolution for VRT datasets
- DEM terrain tiles skip rescale for terrainrgb algorithm
- Duplicate Alembic revision ID and broken chain for 3D columns migration
- Post-implementation audit findings across 3D and shared vector staging phases

## [13.0] - 2026-03-27

### Added
- Open-core architecture with enterprise extension points
- Plugin entrypoint system for modular feature loading
- CI pipeline with path-filtered conditional jobs, security scanning (bandit + pip-audit), and E2E tests
- Docker image publishing to GHCR with Trivy scan gate and SBOM attestation

### Changed
- Upgraded all dependencies (backend and frontend) to latest stable versions
- Pinned Docker base images to specific digests for reproducible builds

### Fixed
- IDOR vulnerabilities in dataset and map endpoints
- CORS configuration tightened to explicit allowed origins
- Rate limiting added to authentication endpoints
- Graceful shutdown and init process in Docker containers

## [12.3] - 2026-03-21

### Added
- Keyboard-accessible map builder with full tab navigation
- Builder save/load unit and E2E tests
- Alembic migrations run automatically on API container startup

### Fixed
- Basemap E2E test selector alignment
- Missing i18n keys in builder components

## [12.2] - 2026-03-19

### Added
- No-tile badge for raster datasets without a configured tile URL
- Tile error tracking and hero state machine for raster/VRT previews

### Fixed
- Raster hero state now correctly shows no-tile badge instead of infinite spinner

## [12.1] - 2026-03-17

### Added
- Smart timestamps in audit log (relative for recent, absolute for older entries)
- Client-side search on collections browse page
- Responsive overflow tabs on dataset detail panel

### Fixed
- Login form test selector ambiguity
- Missing i18n keys for dataset card provenance fallback
- Trailing slash on collections/datasets API call causing 307 redirect

## [12.0] - 2026-03-17

### Added
- Record-first discovery architecture -- catalog now surfaces individual records, not just datasets
- Keyword facet picker integrated into filter panel
- Search ranking with faceted filtering backend
- Publish button wired to dataset status endpoint

### Changed
- Catalog search rewritten around record-level results
- Filter panel now supports keyword facets alongside existing filters

### Fixed
- Keyword URL encoding in search queries
- Missing i18n metadata keys

## [11.0] - 2026-03-16

### Added
- Performance regression test suite for 5 critical API paths
- Load test framework with tuning documentation
- Connection pool and query optimization for large catalogs

## [10.1] - 2026-03-15

### Added
- VRT-based raster mosaics from multiple source GeoTIFFs
- Sources tab on dataset detail showing VRT member files
- Delete guard UX showing dependent VRT links on 409 conflict
- VRT i18n keys for all 4 locales (en, de, es, fr)

### Fixed
- VRT regeneration banner and error display
- SQL string concatenation bugs in VRT source link queries
- AlertDialogAction auto-close behavior on 409 delete errors

## [10.0] - 2026-03-14

### Added
- Raster dataset support -- upload GeoTIFF and Cloud-Optimized GeoTIFF (COG) files
- Automatic COG conversion for non-optimized GeoTIFFs
- Raster tile serving via Titiler integration
- Raster layer controls in map builder (opacity, band selection)
- AI chat awareness of raster datasets with set_opacity action
- `layer_type` field round-trip in saved maps

### Changed
- Map builder layer item rendering now conditional on vector vs raster type
- TileToken schema extended to union of vector and raster token types

## [8.2] - 2026-03-10

### Added
- Inline-editable share link settings (title, description, allowed origins)
- PATCH endpoints for share tokens and embed tokens
- SharePanel redesigned with inline editing replacing read-only summary

## [8.0] - 2026-03-09

### Added
- Spatial intelligence -- AI can execute spatial queries and display results as ephemeral map layers
- Ephemeral result layer rendering with dismiss UI
- Backend GeoJSON extraction from spatial query results
- Semantic search powered by pgvector
- Related datasets discovery based on vector similarity
- Semantic search toggle in filter panel

### Changed
- Enterprise configuration consolidated and cleaned up
- AI prompts optimized for spatial query generation

## [7.2] - 2026-03-08

### Added
- pgvector-based semantic search across dataset metadata
- Related datasets API endpoint and frontend card
- Semantic search toggle with store and API support

## [6.2] - 2026-03-07

### Added
- OAuth 2.0 / OIDC authentication support
- Enterprise configuration management UI
- Settings tabs reorganized into sidebar sub-navigation
- Config import/export functionality

### Fixed
- File dialog double-trigger on config import
- Missing sidebar translation keys for config and permissions sections

## [6.0] - 2026-03-03

### Added
- Redis circuit breaker for cache provider resilience
- Procrastinate queue splitting with file-size-based routing
- Upload limits admin UI with database-driven enforcement
- CORS deployment documentation
- Type-safe filter specifications replacing `unknown[]` types

### Changed
- Production hardening across 9 phases (102-110)
- Abort cleanup wired into collection membership manager

## [3.0] - 2026-02-28

### Added
- Collections for organizing datasets into groups
- Batch dataset operations
- Dataset export in multiple formats (GeoJSON, Shapefile, GeoPackage, CSV)
- CRS reprojection on export

## [2.4] - 2026-02-26

### Added
- Theme support (light/dark) with system preference detection
- Admin settings API for basemaps, map defaults, and feature toggles
- Basemap utilities and theme-aware basemap selection
- Admin layout with sidebar navigation

## [2.0] - 2026-02-22

### Added
- Initial public release
- PostGIS-backed spatial data catalog
- Full-text and spatial search
- Vector file upload and ingestion (Shapefile, GeoPackage, GeoJSON, CSV)
- Interactive map preview with MapLibre GL
- OGC API - Features compliance
- JWT authentication with role-based access control
- Docker Compose deployment

[Unreleased]: https://github.com/geolens-io/geolens/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/geolens-io/geolens/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/geolens-io/geolens/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/geolens-io/geolens/releases/tag/v1.0.0
[14.0]: https://github.com/geolens-io/geolens/compare/v13.0...v14.0
[13.0]: https://github.com/geolens-io/geolens/compare/v12.3...v13.0
[12.3]: https://github.com/geolens-io/geolens/compare/v12.2...v12.3
[12.2]: https://github.com/geolens-io/geolens/compare/v12.1...v12.2
[12.1]: https://github.com/geolens-io/geolens/compare/v12.0...v12.1
[12.0]: https://github.com/geolens-io/geolens/compare/v11.0...v12.0
[11.0]: https://github.com/geolens-io/geolens/compare/v10.1...v11.0
[10.1]: https://github.com/geolens-io/geolens/compare/v10.0...v10.1
[10.0]: https://github.com/geolens-io/geolens/compare/v8.2...v10.0
[8.2]: https://github.com/geolens-io/geolens/compare/v8.0...v8.2
[8.0]: https://github.com/geolens-io/geolens/compare/v7.2...v8.0
[7.2]: https://github.com/geolens-io/geolens/compare/v6.2...v7.2
[6.2]: https://github.com/geolens-io/geolens/compare/v6.0...v6.2
[6.0]: https://github.com/geolens-io/geolens/compare/v3.0...v6.0
[3.0]: https://github.com/geolens-io/geolens/compare/v2.4...v3.0
[2.4]: https://github.com/geolens-io/geolens/compare/v2.0...v2.4
[2.0]: https://github.com/geolens-io/geolens/releases/tag/v2.0
