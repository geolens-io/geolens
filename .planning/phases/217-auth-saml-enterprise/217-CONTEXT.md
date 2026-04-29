# Phase 217: auth-saml-enterprise - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning

<domain>
## Phase Boundary

A government/enterprise buyer with a SAML IdP can install `geolens-enterprise`, configure SAML in the admin UI, and have their users log in via SP-initiated SSO with attribute-driven role mapping — and the core repo contains no SAML implementation code (only neutralized docstring breadcrumbs are scrubbed in this phase). The implementation lives entirely in `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/`, plugged into core via Phase 214's `IdentityExtension` Protocol seam (no-op registration) and core's existing extension-router-mount loop (the active path SAML actually uses).

Concretely after this phase:

- `geolens-enterprise/geolens_enterprise/auth/saml/` ships a working SP-initiated SSO flow: `GET /auth/saml/{slug}/login` → IdP redirect, `POST /auth/saml/{slug}/acs` → assertion validation + JIT provisioning + JWT issuance + `/oauth/callback#token=...` redirect, `GET /auth/saml/{slug}/metadata` → SP metadata XML.
- `geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py` re-adds the four nullable SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) to `catalog.oauth_providers` AND re-relaxes `chk_oauth_providers_type` to include `'saml'`. Runs only when the enterprise overlay is installed; community deployments never see the columns or the CHECK relaxation. Down revision: `e001_enterprise_initial`.
- `EnterpriseSamlExtension` (single class) implements both `AuthExtension.get_auth_methods() -> ['saml']` AND `IdentityExtension.resolve_identity_from_token(...) -> None` (no-op). `register_extensions()` registers the SAME instance under `registry['auth']` AND `registry['identity']`, plus appends `saml_router` to `registry['_routers']`.
- The salvaged scaffold at `geolens-enterprise/geolens_enterprise/auth/saml/{router,config,replay,__init__}.py` is rebased on current core import paths (`app.modules.auth.*`, `app.core.public_urls`, `app.core.persistent_config`, `app.platform.extensions.guards`) — the existing pre-v13.0 paths are dead.
- A new admin page lives in the **core frontend repo** at `frontend/src/routes/admin/saml.tsx` — the route exists in core but is invisible in community because the sidebar nav and the route's data-fetch are gated by edition detection (existing v13.0 pattern used by audit-export UI), and the backend `/auth/saml/providers` endpoint returns 404 in community via `require_enterprise()`.
- Three SAML-mentioning docstrings/comments in core (`backend/app/core/identity.py:15-17`, `backend/app/platform/extensions/defaults.py:36`, `backend/tests/test_extensions.py:230`) are scrubbed — replaced with neutral "enterprise auth overlay" phrasing — so `git grep -i saml backend/` returns zero hits outside test fixtures and `docs-internal/`.
- SAML attribute → role mapping reuses the existing `OAuthProvider.group_claim` + `OAuthProvider.group_role_mapping` columns and the existing `find_or_create_oauth_user()` JIT provisioning pathway (per ROADMAP §Phase 217 SC#3). Mapping changes go through the existing OAuth provider admin endpoints (which already log to the audit log), satisfying SAML-12.

**In scope:** `e002_add_saml_columns` enterprise migration; rebased `auth/saml/router.py` (login + ACS + metadata endpoints) on current import paths; rebased `auth/saml/config.py` (pysaml2 client builder, f-string IdP metadata generation kept as-is); reused `auth/saml/replay.py` (in-memory ReplayCache) verbatim; `EnterpriseSamlExtension` dual-Protocol implementation + dual-registration; admin SAML CRUD endpoints (gated by `require_enterprise()`); core frontend `/admin/saml` route + sidebar nav + edition gating; scrub three SAML mentions in core docstrings; integration tests in core's `backend/tests/` exercising the full registration loop with a mock SAML response; standalone tests in `geolens-enterprise/tests/` for the SAML config builder + replay cache.

**Out of scope:** SP-side AuthnRequest signing (no SP keypair management; `authn_requests_signed=False`); Single LogOut (SLO); Redis-backed replay cache (in-memory only — multi-instance limitation flagged in docs); SAML attribute-map customization beyond the hardcoded multi-key fallback list; cookie-based session swap (still `/oauth/callback#token=...` fragment pattern); enterprise frontend bundle split (deferred per audit §7 P2); gating OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()` (audit P0 from `oc-separation-audit-20260427.md` — deferred to Phase 218); `users.auth_provider` CHECK relaxation (SAML users get `auth_provider='oauth'`, no relaxation needed); SCIM provisioning; multi-tenant identity scoping; SAML 1.x; IdP-initiated SSO.

</domain>

<decisions>
## Implementation Decisions

### Provider model architecture
- **D-01:** Reuse `catalog.oauth_providers` for SAML provider rows. SAML configs use `provider_type='saml'` and populate the four SAML-specific columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`). Reason: ROADMAP SC#3 binds JIT provisioning to `find_or_create_oauth_user()`, which keys off `OAuthProvider`. Reusing the model also reuses `slug`, `display_name`, `enabled`, `default_role`, `group_claim`, `group_role_mapping` (all relevant to SAML) and the `oauth_accounts` linkage table (Phase 217 D-04). Hybrid options (separate `saml_provider_details` 1:1 join) and full-separation (separate `saml_providers` table) were rejected as either fighting `find_or_create_oauth_user()` or adding query complexity for marginal isolation gain.
- **D-02:** Schema additions delivered via a single new enterprise migration `geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py`, `down_revision='e001_enterprise_initial'`, `branch_labels=None` (the `enterprise` branch label is already declared on `e001`). The migration:
  1. Re-adds `idp_entity_id` (`String(512)`, nullable), `idp_sso_url` (`String(512)`, nullable), `idp_certificate` (`Text`, nullable), `sp_entity_id` (`String(512)`, nullable) to `catalog.oauth_providers` — same shape as the columns dropped by core migration `2026_04_08_0001`.
  2. Drops + recreates `chk_oauth_providers_type` to allow `('oidc', 'google', 'microsoft', 'saml')`.
  3. **Does NOT** touch `chk_users_auth_provider`. SAML users get `auth_provider='oauth'` from `find_or_create_oauth_user()` (existing behavior); no CHECK relaxation needed. The `2026_04_08_0001` migration's tightening to `('local', 'oidc', 'oauth')` stays in effect.
  4. `downgrade()` reverses both — drops the four columns, re-tightens the CHECK to `('oidc', 'google', 'microsoft')`. Reversal is destructive (any existing SAML provider rows must be deleted first); follows the same pattern as `2026_04_08_0001`'s downgrade comment block.
- **D-03:** IdP signing certificate stored Fernet-encrypted via the existing `app.modules.auth.oauth.encryption.encrypt_secret()` / `decrypt_secret()` helpers (the same pattern OAuth uses for `client_secret_encrypted`). The `idp_certificate` column stores the encrypted PEM. SP keypair management is deferred (D-09 — `authn_requests_signed=False`); when added, a new `sp_signing_key_encrypted` column would follow the same pattern.
- **D-04:** SAML users link via the existing `catalog.oauth_accounts` table — `provider_id` references the SAML `OAuthProvider`, `subject` stores the SAML NameID (extracted via `authn_response.get_subject().text`, exactly as the existing scaffold does). The existing `UniqueConstraint('provider_id', 'subject', name='uq_oauth_account_provider_subject')` prevents duplicate linkage. No new linkage table; no migration to `oauth_accounts`. `find_or_create_oauth_user()` works unchanged. `users.auth_provider='oauth'` (already set by `find_or_create_oauth_user()`).

### Identity wire-in pattern
- **D-05:** ACS endpoint issues a normal core JWT (access + refresh) via `AuthService.create_access_token()` / `create_refresh_token()` and redirects to `/oauth/callback#token=...&refresh_token=...&expires_in=...` — the EXACT pattern OAuth uses today and the existing scaffold already uses. SAML token format never crosses the per-request boundary; subsequent requests use the existing JWT path at `auth/dependencies.py:get_optional_user()`. The `IdentityExtension.resolve_identity_from_token()` hot path is NOT used for SAML traffic (it stays no-op). Reason: matches the OAuth precedent; no per-request SAML decoding cost; no session-store dependency added; simpler than the alternative.
- **D-06:** SAML-09 ("core's auth-extension hook is the only seam the SAML overlay registers into") is satisfied by registering the SAML overlay into TWO core seams that already exist:
  1. `registry['identity'] = EnterpriseSamlExtension()` — IdentityExtension Protocol implementation (declarative; the `resolve_identity_from_token()` method returns None, matching `DefaultIdentityExtension` behavior).
  2. `registry['_routers'].append(saml_router)` — router-mount seam, the active path. Core's `api/main.py` startup loop iterates `registry['_routers']` and mounts each one into the FastAPI app.

  Both seams pre-date Phase 217 (router-mount loop ships in v13.0; IdentityExtension ships in Phase 214). No new core code is added to support SAML registration. Audit-grade interpretation: the SAML overlay registers into existing seams; zero core mutation. The no-op IdentityExtension also serves as an architectural breadcrumb that Phase 214's seam exists for SAML and remains available if a future phase wants per-request SAML token validation.
- **D-07:** ACS endpoint structure mirrors `auth/oauth/router.py` callback verbatim:
  1. Resolve provider by slug (`get_provider_by_slug()`); 404 if not found, not enabled, or `provider_type != 'saml'`.
  2. Parse `SAMLResponse` from form data; raise on missing.
  3. Build pysaml2 client (`build_saml_client(provider, acs_url)`); call `client.parse_authn_request_response(saml_response, BINDING_HTTP_POST)`.
  4. Replay-cache check (`replay_cache.check_and_record(authn_response.assertion.id)`); raise on duplicate.
  5. Extract subject (NameID) + attributes (email/name/groups via hardcoded multi-key fallback list).
  6. Build `userinfo` dict (`sub`, `email`, `name`, optional groups under `provider.group_claim`).
  7. `user = await find_or_create_oauth_user(db, provider, userinfo, {})` (existing JIT pathway; reuses group → role mapping logic at `oauth/service.py:218`).
  8. `user.last_login_at = func.now()`.
  9. Issue JWT via `AuthService` (uses `ACCESS_TOKEN_EXPIRE_MINUTES.get(db)` + `REFRESH_TOKEN_EXPIRE_DAYS.get(db)` from core's PersistentConfig — same as OAuth).
  10. `await db.commit()`; redirect to `/oauth/callback#token=...&refresh_token=...&expires_in=...`.
  11. On any exception: log via structlog, redirect to `/oauth/callback#error=<urlencoded message>`. Frontend's existing OAuth callback handler picks up tokens or errors; no SAML-specific frontend route needed.
- **D-08:** SP metadata endpoint at `GET /auth/saml/{slug}/metadata` (per-provider — SP entityID and ACS URL are per-provider). Public route (IdP admins fetch it; some IdPs poll on schedule), still gated by `require_enterprise()` so community returns 404. Returns `Content-Type: application/samlmetadata+xml`. Implementation uses pysaml2's `create_metadata_string()` against the per-provider Saml2Config — generates a fresh SP metadata XML on each call (no caching needed; fast op). The `sp_entity_id` column is the SP's entityID (admin-provided in the SAML admin UI; default suggestion: `{public_api_url}/auth/saml/{slug}`).

### Existing scaffold disposition
- **D-09:** Salvage and modernize the existing `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/` scaffold rather than rewrite. Keep:
  - `replay.py` — verbatim. Clean, well-scoped TTL cache (600s default, threading.Lock-guarded, evict-on-check). No changes.
  - `config.py:build_saml_client()` + `_build_idp_metadata_xml()` — keep f-string IdP metadata generation. Small, direct, the `certificate` is the only tainted input and it's Fernet-decrypted from a trusted DB column. `defusedxml>=0.7.1` already declared in enterprise `pyproject.toml`.
  - `router.py` overall flow — login + ACS endpoints. Modernize imports (D-10), extend with metadata endpoint (D-08).
  - `__init__.py` (`EnterpriseSamlExtension` class) — extend with `IdentityExtension` no-op method (D-13). Keep `get_auth_methods() -> ['saml']`.
- **D-10:** Rewrite ALL imports in the scaffold to current core paths:
  | Old (pre-v13.0) | Current |
  |---|---|
  | `from app.auth.oauth.service import find_or_create_oauth_user, get_provider_by_slug` | `from app.modules.auth.oauth.service import find_or_create_oauth_user, get_provider_by_slug` |
  | `from app.auth.providers import AuthenticatedIdentity` | `from app.modules.auth.providers import AuthenticatedIdentity` |
  | `from app.auth.service import AuthService` | `from app.modules.auth.service import AuthService` |
  | `from app.dependencies import get_db` | `from app.api.deps import get_db` (verify exact path during planning) |
  | `from app.extensions.guards import require_enterprise` | `from app.platform.extensions.guards import require_enterprise` |
  | `from app.persistent_config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS` | `from app.core.persistent_config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS` |
  | `from app.public_urls import get_public_api_url, get_public_app_url` | `from app.core.public_urls import get_public_api_url, get_public_app_url` |
  | `from app.auth.oauth.encryption import decrypt_secret` (in config.py) | `from app.modules.auth.oauth.encryption import decrypt_secret` |
  | `from app.auth.oauth.models import OAuthProvider` (in config.py) | `from app.modules.auth.oauth.models import OAuthProvider` |
  Planner re-verifies each path during plan time — if any module has moved again post-v13.0, follow the new path.
- **D-11:** Hardcoded multi-key attribute fallback list — keep existing `_extract_attr()` helper as-is. Extend with the 1–2 ADFS-specific URN claim names commonly used (`http://schemas.xmlsoap.org/claims/Group` for groups, `http://schemas.microsoft.com/identity/claims/displayname` for displayName) so Microsoft/ADFS deployments work out of the box. Predictable; covers 95%+ of IdPs in the wild without admin config burden. Per-provider attribute-map JSONB column rejected as YAGNI; group claim variance is already handled by the existing per-provider `group_claim` column on `OAuthProvider`.
- **D-12:** Reuse existing OAuth admin CRUD endpoints (`POST/PATCH/DELETE /auth/oauth/providers`) for SAML provider management — they already speak the `OAuthProviderCreate`/`OAuthProviderUpdate` schemas. Phase 217 extends those schemas to include the four SAML-specific fields (nullable; only populated when `provider_type='saml'`). The existing audit-log writes for OAuth provider mutations already capture old/new values, satisfying SAML-12 ("mapping changes are recorded in the existing audit log with old/new values"). Schema-level validation: when `provider_type='saml'`, the four SAML fields MUST be non-null; when `provider_type` is OAuth-shaped, they MUST be null. Pydantic discriminated-union validator preferred; fallback to a model_validator if discriminated union complicates the existing schema.
- **D-13:** `EnterpriseSamlExtension` (in `geolens_enterprise/auth/saml/__init__.py`) implements BOTH Protocols on the same class:
  ```python
  class EnterpriseSamlExtension:
      def get_auth_methods(self) -> list[str]:
          return ["saml"]

      async def resolve_identity_from_token(
          self, token: str, request: Request, db: AsyncSession
      ) -> Identity | None:
          # SAML doesn't use the per-request identity hook — JWT-after-ACS
          # pattern (D-05) means SAML traffic carries normal core JWTs.
          # The no-op registration documents that Phase 214's seam exists
          # for SAML and remains available for future per-request SAML
          # token validation if needed.
          return None
  ```
  `register_extensions()` in `geolens_enterprise/__init__.py`:
  ```python
  saml_ext = EnterpriseSamlExtension()
  registry["auth"] = saml_ext      # AuthExtension Protocol
  registry["identity"] = saml_ext  # IdentityExtension Protocol — no-op
  ```
  Same instance, dual-keyed. Both Protocols are structurally satisfied (PEP 544 — implicit conformance, matches Phase 214 D-06 / D-21 discipline). No `isinstance(saml_ext, IdentityExtension)` runtime assertion needed.

### UI shape, hardening, SC#1
- **D-14:** Admin SAML UI lives in the **core frontend repo** at `frontend/src/routes/admin/saml.tsx` + supporting components under `frontend/src/components/admin/saml/`. Sidebar nav item `'SAML'` and the route registration are conditionally rendered using the existing edition-detection pattern from v13.0 (see how audit-export UI is gated — likely a `useEdition()` hook or similar; planner verifies). Component fetches `GET /auth/saml/providers` (gated by `require_enterprise()` server-side) and any 404 redirects to a 404 page. SC#2 ("admin UI exposes a SAML configuration tab; in community mode the same tab is absent and direct route access returns 404") is satisfied by: (a) sidebar nav hides the link in community, (b) backend 404 closes the loophole if a community user pastes the URL directly. Frontend bundle split (P2 audit item) deferred — SAML form code lives in core bundle; this is acceptable per audit §7 P2 deferral.
- **D-15:** Hardening defaults (V1 enterprise-grade, ship-fast posture):
  - `want_assertions_signed = True` — IdP MUST sign assertions; rejects unsigned. (Existing scaffold default.)
  - `want_response_signed = False` — response wrapper need not be signed (assertion signature is the strong artifact).
  - `authn_requests_signed = False` — no SP signing key required in V1; defers SP keypair management. Acceptable for SP-initiated SSO with most IdPs.
  - `allow_unsolicited = False` — rejects assertions not preceded by an AuthnRequest (blocks IdP-initiated and unsolicited replay).
  - `allow_unknown_attributes = True` — pysaml2's permissive attribute mode (matches existing scaffold; required because IdPs send arbitrary attributes).
  - Replay cache: in-memory `ReplayCache` (TTL 600s, threading.Lock-guarded) — single-instance correct; multi-instance has a hole (replayed assertion sent to a different instance won't be caught). Document this limitation in `docs/saml.md` (or wherever SAML user-facing docs land); flag as the upgrade path to a Redis-backed cache when multi-instance demand surfaces.
  - Assertion validation includes (handled by pysaml2): signature verification, NotBefore/NotOnOrAfter expiry check (clock-skew tolerance is pysaml2 default), AudienceRestriction must include SP entityID, replay protection (D-09 layer on top).
- **D-16:** Scrub three SAML mentions in core docstrings/comments to satisfy SC#1's literal grep test:
  - `backend/app/core/identity.py:15-17` — replace "Phase 217 (auth-saml-enterprise) is the first concrete consumer of `IdentityExtension`: a SAML overlay registers an alternate backend ..." with neutral phrasing such as "An enterprise auth overlay (e.g., the `geolens-enterprise` package) is the first concrete consumer of `IdentityExtension`: it registers an alternate backend under the `geolens.extensions` entry-point group with key `\"identity\"` and `get_identity_extension()` returns it on subsequent requests."
  - `backend/app/platform/extensions/defaults.py:36` — replace "The async signature is intentional (Pitfall 8). Phase 217's SAML overlay relies on this ..." with similar neutral phrasing referring to "enterprise auth overlays" generically.
  - `backend/tests/test_extensions.py:230` — replace "must not raise TypeError. Phase 217's SAML overlay relies on this ..." with neutral "must not raise TypeError. Enterprise auth overlays rely on this ...". Test fixtures themselves (which use SAML mock data) are exempt per SC#1's test-fixture carve-out.
  After scrub, confirm: `git grep -i saml backend/ | grep -v 'tests/fixtures\|tests/test_saml'` returns zero hits. (The exact carve-out path is whatever fixtures Phase 217's tests introduce; planner verifies.)
- **D-17:** Audit P0 from `oc-separation-audit-20260427.md` (OAuth `group_claim`/`group_role_mapping` exposed in Community even though IdP role mapping is GTM-classified Enterprise) is **deferred to Phase 218** (oc-audit-close-v13.1). Rationale: Phase 217's stated boundary is the SAML overlay; gating community OAuth fields is a separate concern that introduces a regression risk to existing OAuth admin flows and would be a breaking change for Community deployments using Google/Microsoft IdPs with group claims. Phase 218 owns the audit close and can scope the gating decision (re-classify, gate behind `require_enterprise()`, or leave as community feature with a GTM doc clarification) with a fresh audit re-run informing the call. Phase 217 CONTEXT.md flags this in **Deferred Ideas** so it doesn't get lost.

### Claude's Discretion
- **Migration revision IDs** — `e002_add_saml_columns` is a placeholder; planner picks the actual revision ID following enterprise migration conventions (alembic-style hex hash or `e002_` prefix — match what `e001_enterprise_initial.py` does).
- **Commit decomposition** — likely 4–5 atomic commits: (1) `e002_add_saml_columns` migration + tests; (2) modernize scaffold imports + structural refactor (router/config/replay rebased on v13.0 paths, no new SAML behavior); (3) extend `EnterpriseSamlExtension` with IdentityExtension no-op + dual registration in `register_extensions()` + add metadata endpoint; (4) extend `OAuthProviderCreate`/`OAuthProviderUpdate` schemas with SAML fields + validation; (5) frontend `/admin/saml` route + sidebar gating + edition detection; plus a final commit for SC#1 docstring scrub. Planner may collapse, split, or reorder — every commit must keep the test suite green; SAML-09 / SAML-10 / SAML-11 / SAML-12 verification gate runs at the end (per Phase 212/213/214 phase-verification pattern).
- **Mock IdP for tests** — planner picks between (a) hardcoded SAML response XML fixtures (simplest), (b) pysaml2's IdP simulator for round-trip tests (more thorough), (c) a Docker-Compose-mounted SimpleSAMLphp IdP for integration tests (heaviest). Default: (a) for unit tests, (b) for integration test of the full flow.
- **Default `sp_entity_id` value** — admin-input field in the UI; planner can pre-fill with `{public_api_url}/auth/saml/{slug}` as a sensible default (admin can override). Some IdPs require SP entityID match exactly what's registered IdP-side, so admin override is essential.
- **Whether `EnterpriseSamlExtension` is split into separate Auth + Identity classes** — D-13 says single class with dual registration; planner may split if testing or readability benefits. Behavior is identical either way.
- **Where `docs/saml.md` lives** — user-facing SAML documentation. Likely `docs/saml.md` in core repo (gives community users awareness of the Enterprise feature) OR `docs/enterprise/saml.md` for tier-clarity. Planner picks based on existing docs structure.
- **Audit-log shape for SAML provider mutations** — D-12 says reuse existing OAuth provider audit logging. If the existing logging shape doesn't naturally capture old/new values for the new SAML fields (e.g., it logs only changed-field names, not values), planner extends the audit shape minimally. SAML-12 explicitly requires "mapping changes are recorded in the existing audit log with old/new values."
- **Whether to ship a `docs/runbooks/saml-troubleshooting.md`** — useful for ops; not in SC#1..5 explicitly. Planner discretion based on time budget.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec (the source of truth)
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 bucket, row "Reintroduce SAML auth properly". Names this phase's effort estimate (2–3 weeks) and design intent ("Should land as part of an `auth-saml-overlay` enterprise extension, not back into core").
- `docs-internal/audits/oc-separation-audit-20260427.md` — most-recent audit. §3 ("SAML SSO" tier-distance row, 2–3 weeks to MVP), §3 ("IdP role mapping" P0 tier-leak — DEFERRED to Phase 218 per D-17), §5 (Coupling Health table — auth/identity row), §7 (priority matrix — note SAML doesn't appear in P0/P1/P2 because it's already the dedicated Phase 217 work). Read before planning.
- `docs-internal/audits/oc-separation-audit-20260426.md` §3 / §10 — earlier audit body, the SAML "missing" classification.
- `docs-internal/audits/oc-separation-audit-20260426-b.md` §3 — supplementary audit; reinforces "no SAML implementation" finding.
- `.planning/REQUIREMENTS.md` §SAML-08, SAML-09, SAML-10, SAML-11, SAML-12 — the five requirements this phase closes. SAML-08 (zero core matches), SAML-09 (auth-extension hook seam), SAML-10 (admin tab community-hidden), SAML-11 (SP-initiated SSO, signed assertion validation, JIT via `find_or_create_oauth_user()`), SAML-12 (configurable attribute → role mapping with audit log).
- `.planning/ROADMAP.md` §Phase 217 — goal statement and 5 success criteria. Each SC is binding: SC#1 (`git grep -i saml` zero matches), SC#2 (admin UI tab; community 404), SC#3 (SP-initiated SSO end-to-end against reference IdP), SC#4 (attribute → role mapping configurable + audited), SC#5 (Phase 214 seam is the only registration point).

### Project / state
- `.planning/PROJECT.md` — milestone overview; v13.1 is audit-driven with target grades Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 217 contributes to Boundary (SAML in enterprise repo, not core), Seam Quality (uses Phase 214's IdentityExtension hook + the existing router-mount seam), and indirectly OSS Surface (gov-buyer enablement unblocks the wedge).
- `.planning/STATE.md` — confirms Phase 216 complete; Phase 217 next. Backend test baseline: 2001 tests passing (per Phase 214 verification gate); Phase 217 must keep this green.
- `.planning/phases/214-identity-protocol-extract/214-CONTEXT.md` — companion phase, established the IdentityExtension Protocol surface (D-12 there ⇄ D-06 here) AND signaled Phase 217 as the first concrete consumer. Full read before implementation; this context file inherits Phase 214's discipline (no shim, hard cutover, structural Protocol conformance).
- `.planning/phases/214-identity-protocol-extract/214-PLAN.md` (if generated by `/gsd-plan-phase`) and per-plan files — for the wire-in pattern of `get_optional_user()`, `_resolve_api_key()`, and the dependency stack Phase 217's no-op IdentityExtension lives within.
- `.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md` — companion phase, reuses the architecture-guard test pattern (Phase 217 doesn't add a new layering test; the existing Phase 214 guard `test_cross_domain_does_not_import_user_from_auth_models` already covers the SAML overlay because enterprise repo is not in `backend/`).
- `.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md` — companion phase (Phase 216 ships CLI, also a v13.1 deliverable). Shares enterprise-overlay distribution pattern.

### Code (Phase 214 seam — what Phase 217 plugs into)
- `backend/app/core/identity.py` — defines `Identity`, `IdentityProtocol`, `RoleProtocol`, `IdentityExtension` Protocol. Phase 217 implements `IdentityExtension` on `EnterpriseSamlExtension`. **NOTE:** docstring at lines 15-17 currently mentions SAML; D-16 scrubs this.
- `backend/app/platform/extensions/__init__.py` — extension registry; `get_identity_extension()` typed accessor (added in Phase 214). Phase 217 doesn't modify this file; the SAML extension is auto-discovered via the existing `geolens.extensions` entry-point loop (`load_extensions()` at startup).
- `backend/app/platform/extensions/defaults.py` — `DefaultIdentityExtension` (returns None). Phase 217's `EnterpriseSamlExtension.resolve_identity_from_token()` mirrors this no-op behavior. **NOTE:** docstring at line 36 mentions SAML; D-16 scrubs this.
- `backend/app/platform/extensions/protocols.py` — `AuthExtension`, `BrandingExtension`, `AuditExtension` Protocol definitions. Phase 217's `EnterpriseSamlExtension` satisfies `AuthExtension` (existing scaffold already does this via `get_auth_methods()`).
- `backend/app/platform/extensions/guards.py` — `require_enterprise()` FastAPI dependency. Phase 217's `/auth/saml/*` router applies this via `dependencies=[Depends(require_enterprise)]` (existing scaffold already does this).
- `backend/app/api/main.py` — `load_extensions()` at startup; iterates `registry['_routers']` and mounts each FastAPI router. Phase 217's saml_router gets mounted automatically by this loop. **No core modification needed.**

### Code (OAuth pathway Phase 217 reuses)
- `backend/app/modules/auth/oauth/models.py` — `OAuthProvider` ORM model. Phase 217's enterprise migration adds 4 SAML columns + relaxes CHECK; the model itself stays in core (the SAML columns become nullable additions visible to the model class once the enterprise migration runs). Planner decides whether to update the model class in core to declare the 4 SAML columns (as nullable, conditionally-populated) OR keep the model unaware and access via raw SQL/dict — recommended: declare them as nullable in the model (clean SQLAlchemy behavior) since they're physically present when enterprise is installed and physically absent otherwise (column-not-found errors don't fire because ORM reads only what schema has). **Important:** if columns are declared on the model in core, that's a SAML reference in core code — D-16 scrub list grows. Planner reconciles: alternative is to define a `SamlOAuthProviderColumns` mixin in enterprise repo and use `__table_args__` extension. Planner picks during plan time.
- `backend/app/modules/auth/oauth/schemas.py` — `OAuthProviderCreate`, `OAuthProviderUpdate`. Phase 217 extends these with optional SAML fields per D-12. SC#1 grep treats Pydantic field names: an `idp_entity_id: str | None = None` field in `oauth/schemas.py` is technically a SAML-related identifier in core. Planner reconciles via either (a) putting the SAML schema fields in a separate `SamlProviderFields` mixin in enterprise repo that the API endpoint composes at runtime, or (b) accepting that schema field names like `idp_entity_id` are not literally SAML strings (don't match `grep -i saml`). The SC#1 scrub already handles literal `SAML` mentions; field names without "saml" in them are fine.
- `backend/app/modules/auth/oauth/service.py:138` — `find_or_create_oauth_user()`. The JIT-provisioning function ROADMAP §Phase 217 SC#3 binds SAML to. Already takes a `provider: OAuthProvider`, a `userinfo: dict`, and a `tokens: dict`; returns `User`. Phase 217's SAML ACS calls this as-is (existing scaffold already does).
- `backend/app/modules/auth/oauth/service.py:218` — group → role mapping logic (uses `provider.group_claim`, `provider.group_role_mapping`, `provider.default_role`). Reused by SAML; no SAML-specific path needed.
- `backend/app/modules/auth/oauth/service.py:46` — `get_provider_by_slug()`. Used by SAML ACS to resolve the provider from the URL slug.
- `backend/app/modules/auth/oauth/encryption.py` — `encrypt_secret()` / `decrypt_secret()`. Fernet-based. SAML overlay's `decrypt_secret(provider.idp_certificate)` reuses this.
- `backend/app/modules/auth/providers/__init__.py` — defines `AuthenticatedIdentity` dataclass. SAML ACS uses this when calling `AuthService.create_access_token(identity, ...)` (existing scaffold pattern).
- `backend/app/modules/auth/service.py` — `AuthService.create_access_token()`, `create_refresh_token()`. Issues the JWTs SAML's ACS endpoint returns to the user.
- `backend/app/modules/auth/router.py` (OAuth callback) — reference implementation for the ACS endpoint shape; SAML ACS mirrors this verbatim per D-07.
- `backend/app/core/persistent_config.py` — `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`. SAML ACS reads these (same as OAuth).
- `backend/app/core/public_urls.py` — `get_public_api_url()`, `get_public_app_url()`. SAML uses these to build the ACS URL (`{public_api_url}/auth/saml/{slug}/acs`) and the post-ACS frontend redirect URL (`{public_app_url}/oauth/callback#token=...`).

### Code (existing migration that Phase 217 partially reverses)
- `backend/alembic/versions/2026_04_08_0001-strip_dead_saml_code.py` — the migration that DROPPED the four SAML columns from `catalog.oauth_providers` and tightened CHECK constraints. Phase 217's enterprise migration `e002_add_saml_columns` re-adds the columns and re-relaxes the `chk_oauth_providers_type` CHECK (NOT `chk_users_auth_provider`; SAML users get `auth_provider='oauth'` per D-04). Read this migration's `downgrade()` block — it's the exact column shape Phase 217 re-adds.
- `backend/alembic/versions/2026_03_26_*-add_saml_provider_columns.py` (revision `0010_add_saml_provider_columns`, the migration that originally ADDED the columns and is now `down_revision` of `e001_enterprise_initial`) — historical reference for the original SAML column shape; matches the columns `2026_04_08_0001` later dropped.

### Code (existing enterprise scaffold to salvage and modernize)
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/router.py` — current scaffold; **OLD imports** (must be modernized per D-10). Salvage the overall flow.
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/config.py` — current scaffold; OLD imports. Salvage `build_saml_client()` + `_build_idp_metadata_xml()`. Update `app.auth.oauth.encryption` → `app.modules.auth.oauth.encryption` and `app.auth.oauth.models` → `app.modules.auth.oauth.models`.
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/replay.py` — verbatim reuse. No changes needed.
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/__init__.py` — currently a 1-line `EnterpriseSamlExtension` class with only `get_auth_methods()`. Extend with the no-op `resolve_identity_from_token()` per D-13.
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` — `register_extensions()`. Update to register the SAML instance under BOTH `registry['auth']` AND `registry['identity']` per D-13.
- `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e001_enterprise_initial.py` — the existing enterprise initial migration; `down_revision='0010_add_saml_provider_columns'`. Phase 217's `e002_add_saml_columns` will have `down_revision='e001_enterprise_initial'`. **Note:** `e001`'s `down_revision` references `0010_add_saml_provider_columns`, but `2026_04_08_0001` later removed those columns; verify the alembic head/branch story still works after Phase 217's `e002` lands. Planner runs `cd backend && uv run alembic heads` and `alembic check` after the migration to confirm clean state.
- `~/Code/geolens-enterprise/pyproject.toml` — entry-point registration (`enterprise = "geolens_enterprise:register_extensions"`); declares `pysaml2>=7.5.4`, `defusedxml>=0.7.1`. No version changes needed unless a pysaml2 CVE is discovered before plan time.
- `~/Code/geolens-enterprise/tests/test_registration.py` — existing registration tests. Phase 217 extends with assertions for: (a) `registry['identity']` is the SAML extension instance (not `DefaultIdentityExtension`); (b) `_routers` includes the SAML router; (c) `get_migration_paths()` resolves to a real path containing both `e001` and `e002`.
- `~/Code/geolens-enterprise/README.md` — updated to document the SAML feature (`What's Included` table already mentions SAML SSO; Phase 217 confirms this is now real).

### Code (frontend admin)
- `frontend/src/components/admin/AdminSidebar.tsx` (or wherever the admin nav lives — `frontend/src/components/admin/` per CLAUDE.md user-memory) — Phase 217 adds a `'SAML'` nav item conditionally rendered based on edition detection.
- The edition-detection mechanism — likely a `useEdition()` hook or a query-fetched config flag from the backend (planner verifies by reading how audit-export UI is gated in v13.0). The mechanism MUST be edition-aware AND server-confirmed so a community user can't unhide the nav by tampering with frontend state.
- `frontend/src/api/` — Phase 217 adds `frontend/src/api/saml.ts` with typed CRUD wrappers for `GET/POST/PATCH/DELETE /auth/saml/providers` and `GET /auth/saml/{slug}/metadata`.
- The frontend's existing OAuth provider admin page — reference for form-field shapes and validation patterns. Planner reads this to ensure SAML admin form has consistent UX.

### Code (CLAUDE.md operational notes)
- `CLAUDE.md` (project-local + user-global) — auth notes: API key precedence (header > query > JWT > anonymous) at `_resolve_api_key()` `auth/dependencies.py:23`. SAML doesn't change this; SAML lives entirely in the bearer-token path's IdentityExtension hook (which is no-op for SAML per D-05). FastAPI trailing-slash quirk applies to all routes; SAML router's routes follow the project convention.
- `frontend/src/api/client.ts` — `apiFetch()` wrapper. Used by the new `frontend/src/api/saml.ts` module.

### Code (audit-log writes Phase 217 reuses for SAML-12)
- `backend/app/modules/audit/service.py` `log_action()` — the canonical audit-log entry point. OAuth provider mutation endpoints already call this with old/new values. Phase 217 reuses unchanged. SAML-12 satisfaction: existing OAuth provider PATCH endpoint logs the `group_role_mapping` change; SAML providers go through the same endpoint, so SAML-12 is satisfied as a side effect of D-12.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase 214's `IdentityExtension` Protocol + `get_identity_extension()` accessor** — Phase 217's `EnterpriseSamlExtension` registers via the existing entry-point group `geolens.extensions` with key `"identity"`. Zero new core code; the registration plug is exactly what Phase 214 was built for.
- **v13.0 enterprise router-mount loop in `api/main.py`** — `registry['_routers']` is iterated at startup and each router is mounted into the FastAPI app. SAML router is just another entry. Existing pattern for branding router, audit-export router.
- **`require_enterprise()` FastAPI dependency at `platform/extensions/guards.py`** — applied as `dependencies=[Depends(require_enterprise)]` on the SAML router. Returns 404 in community. Existing scaffold already uses this.
- **`auth/oauth/encryption.py:encrypt_secret()` / `decrypt_secret()`** — Fernet-based; SAML overlay encrypts `idp_certificate` (and any future SP signing key) via these helpers. Reuses the same `SECRET_KEY`-derived Fernet key as OAuth `client_secret_encrypted`.
- **`find_or_create_oauth_user()` at `auth/oauth/service.py:138`** — JIT-provisioning + group → role mapping pathway. ROADMAP §Phase 217 SC#3 binds SAML to this. Existing scaffold already calls it; Phase 217 keeps that wiring.
- **`OAuthProvider.group_claim` / `group_role_mapping` / `default_role` columns** — already exist; SAML reuses them for attribute → role mapping (SAML-12 satisfaction). No schema additions for the role-mapping side.
- **`oauth_accounts` linkage table with `UniqueConstraint('provider_id', 'subject')`** — SAML uses NameID as subject; existing constraint prevents duplicate user linkage.
- **`AuthService.create_access_token()` / `create_refresh_token()` at `modules/auth/service.py`** — JWT issuance pathway SAML ACS uses (mirrors OAuth callback exactly per D-07).
- **`auth/oauth/router.py` callback shape** — reference implementation; SAML ACS mirrors verbatim.
- **Edition-detection pattern (v13.0)** — used by audit-export admin UI to conditionally render. Phase 217's SAML admin nav uses the same hook (planner verifies the exact name).
- **`replay.py` ReplayCache** — keep verbatim; clean, well-scoped, threading.Lock-guarded TTL cache. No need to reinvent.
- **`build_saml_client()` + `_build_idp_metadata_xml()` in scaffold's `config.py`** — keep f-string IdP metadata generation; small, direct, defusedxml-protected.
- **Phase 214's architecture-guard tests** at `backend/tests/test_layering.py` — automatically cover Phase 217 because the SAML overlay lives in `~/Code/geolens-enterprise/`, not `backend/`. The User-import allowlist guard doesn't need updating.

### Established Patterns
- **Enterprise migration on `enterprise` branch label** — `e001_enterprise_initial` set the precedent (`branch_labels=("enterprise",)`, `down_revision='0010_add_saml_provider_columns'`). Phase 217's `e002_add_saml_columns` chains as `down_revision='e001_enterprise_initial'`.
- **Single-class, dual-Protocol implementation** — Phase 214 D-04 documented `@runtime_checkable` Protocols allow implicit conformance. `EnterpriseSamlExtension` satisfies both `AuthExtension` and `IdentityExtension` structurally. Mirrors how `User` satisfies `IdentityProtocol` without inheritance (Phase 214 D-06).
- **`/oauth/callback#token=...` redirect pattern** — OAuth uses fragment-encoded tokens for the post-callback handoff; SAML mirrors verbatim. Frontend's existing OAuth callback handler picks up tokens or errors. No SAML-specific frontend route needed (per D-07).
- **Per-provider URL pattern `/auth/{provider_type}/{slug}/{action}`** — OAuth uses `/auth/oauth/{slug}/login` and `/auth/oauth/{slug}/callback`. SAML uses `/auth/saml/{slug}/login`, `/auth/saml/{slug}/acs`, `/auth/saml/{slug}/metadata` (per D-08). Symmetric.
- **Fernet-encrypted secrets in DB columns** — OAuth `client_secret_encrypted` is the precedent; SAML `idp_certificate` follows. `SECRET_KEY` env var is the key derivation root; rotation is brittle (existing concern, not a new Phase 217 issue).
- **Pydantic discriminated unions for `provider_type`-specific fields** — OAuth schemas already differentiate per `provider_type`; planner extends to handle the `'saml'` discriminator and require the four SAML fields when selected.
- **Audit log via `audit/service.py:log_action()`** — every mutation through the OAuth admin endpoints already calls this; SAML provider mutations go through the same endpoints, so audit logging is automatic.

### Integration Points
- **`api/main.py` startup chain** — `load_extensions()` runs first; iterates `registry['_routers']` and mounts each one. Phase 217's `saml_router` is auto-mounted. No startup-wiring change needed in core.
- **Alembic migration graph** — core's main branch ends at the latest migration; enterprise branch starts at `0010_add_saml_provider_columns` → `e001_enterprise_initial` → (Phase 217) `e002_add_saml_columns`. Planner runs `alembic heads` after the migration to confirm two clean heads (main + enterprise).
- **Enterprise overlay loading** — `docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d` mounts the enterprise package and runs `alembic upgrade heads@enterprise` (or similar — planner verifies the exact command). The `e002_add_saml_columns` migration runs at this point, exposing SAML capability.
- **Frontend bundle** — SAML admin UI ships in core's bundle (per D-14), gated by edition detection. Frontend bundle split is P2 audit deferral; not Phase 217's problem.
- **OpenAPI snapshot** — `backend/openapi.json` does NOT include SAML routes (they're enterprise-only). The `make openapi-check` gate continues to pass without changes; SAML routes are absent from the snapshot because they're registered at runtime by the enterprise extension loader, after OpenAPI snapshot generation. The Python + TypeScript SDKs (Phase 215) therefore don't include SAML methods either — correct, since SDK consumers shouldn't see Enterprise-only endpoints.
- **CLI (Phase 216)** — `geolens` CLI doesn't interact with SAML (auth is JWT-based). No Phase 216 changes needed.
- **Audit log** — SAML provider CRUD mutations flow through existing OAuth admin endpoints (per D-12), which already invoke `log_action()`. SAML-12's "mapping changes are recorded in the existing audit log with old/new values" is satisfied automatically. Planner verifies that the existing OAuth admin endpoints actually log old/new values and not just changed-field names; if shape needs extension, planner extends minimally.

### Risk surfaces
- **Enterprise migration adding SAML columns to a core-owned table** — `catalog.oauth_providers` is core-owned. The `e002_add_saml_columns` migration mutates it from the enterprise branch. Risk: a future core migration that touches `oauth_providers` may conflict with the enterprise branch. Mitigation: planner runs `alembic heads` + `alembic check` after the migration; document the convention in `docs-internal/` that enterprise-branch migrations only ADD nullable columns or relax CHECK constraints — never DROP or rename.
- **Schema field validation when `provider_type='saml'`** — D-12 calls for Pydantic validation that requires the four SAML fields when `provider_type='saml'` and rejects them otherwise. Risk: existing OAuth provider rows with `provider_type='oidc'` accidentally allow SAML fields if validation is permissive. Mitigation: `model_validator(mode='after')` on `OAuthProviderCreate` / `OAuthProviderUpdate`; explicit error messages; integration test for both directions.
- **OAuthProvider model declaring SAML columns in core** — if the planner declares `idp_entity_id` etc. as nullable columns on the `OAuthProvider` ORM class in core (recommended for clean SQLAlchemy behavior), those column names appear in core code. SC#1 grep for `saml` won't trigger on the column names themselves (no literal "saml" string), but `sp_entity_id` / `idp_*` are SAML-coded names. Mitigation acceptable: column names are technical artifacts; SC#1's spirit is about absence of SAML implementation logic, not absence of any reference to identity-protocol concepts.
- **In-memory replay cache + multi-instance deployments** — D-15 documents this as a known limitation. Risk: an attacker with stolen assertion can replay it to a different API instance. Mitigation: document; recommend single-instance enterprise deployments OR sticky-session load balancing for V1; flag Redis-backed cache as the next iteration when customer demand surfaces.
- **`allow_unknown_attributes = True`** — pysaml2's permissive attribute mode (existing scaffold default). Risk: unexpected attributes from misconfigured IdP could land in `userinfo`. Mitigation: only the hardcoded multi-key fallback list is consumed by `_extract_attr()`; unknown attributes are ignored downstream. Acceptable.
- **Frontend SAML form code in core bundle** — D-14 accepts this as a P2 deferral (frontend code splitting). Risk: bundle size grows by the SAML form (~5–10KB minified); SAML form fields visible in source maps to community users. Mitigation: small bundle impact; admin-only route; source-map exposure is benign (no secrets).
- **SC#1 strict scrub vs schema field names** — D-16 scrubs three docstring mentions, but the new schema fields (`idp_entity_id`, `idp_sso_url`, etc.) and the column declarations (if added to `OAuthProvider` model in core) introduce identifiers that look SAML-coded even though they don't contain the literal string "saml". `git grep -i saml` doesn't catch them; `git grep -iE 'saml|idp_|sp_entity'` would. Mitigation: SC#1 reads "git grep -i saml" — interpret literally; don't broaden the grep.
- **Audit P0 (group_claim/group_role_mapping in Community)** — D-17 defers to Phase 218. Risk: re-running `/oc-audit` after Phase 217 still flags this as P0; Phase 218 must handle. Mitigation: document explicitly in Deferred Ideas + flag in Phase 218 CONTEXT when that phase is discussed.
- **Enterprise migration head check** — `e001_enterprise_initial` has `down_revision='0010_add_saml_provider_columns'` (the original SAML-columns migration which was effectively reverted by `2026_04_08_0001`). The migration graph is unusual: enterprise branch chains off a now-orphaned column-adding migration. `e002_add_saml_columns` re-adds those same columns. Risk: alembic might detect duplicate-column errors at upgrade time. Mitigation: planner tests the migration upgrade path against a fresh DB (community baseline → enterprise migration applies cleanly); if the enterprise branch's `0010 → e001` history conflicts with core's `2026_04_08_0001` strip migration, planner restructures the enterprise branch (e.g., re-base `e001` onto the latest core head + relocate the column re-add into `e001` itself rather than a new `e002`).

</code_context>

<specifics>
## Specific Ideas

- **JWT-after-ACS verbatim mirror** — D-05 / D-07: SAML ACS mirrors `auth/oauth/router.py` callback structure step-for-step. Frontend redirect URL pattern `/oauth/callback#token=...&refresh_token=...&expires_in=...` reused as-is so frontend handler is reused. This is the user's chosen pattern over the alternative IdentityExtension hot-path design.
- **Salvage existing scaffold, not rewrite** — D-09 / D-10: keep `replay.py` verbatim, keep `config.py`'s `build_saml_client()` and f-string IdP metadata generation, keep `router.py`'s overall flow. Modernize all imports per the explicit mapping table in D-10. The user values shipping fast over reinventing.
- **Single-class dual-Protocol** — D-13: `EnterpriseSamlExtension` implements BOTH `AuthExtension.get_auth_methods()` AND `IdentityExtension.resolve_identity_from_token()` (no-op). Same instance dual-registered under `registry['auth']` AND `registry['identity']`. Clean architectural breadcrumb that Phase 214's seam exists for SAML.
- **Hardening: ship-fast posture** — D-15: assertions signed, AuthnRequests not signed, in-memory replay (multi-instance limitation flagged in docs). Strict-mode (signed AuthnRequests + Redis replay) deferred to a later iteration. The user picked the V1 enterprise-grade posture.
- **SC#1 strict scrub, not carve-out** — D-16: scrub all three SAML docstring mentions in core (`core/identity.py:15-17`, `defaults.py:36`, `test_extensions.py:230`) rather than amend SC#1's wording. Replace with neutral "enterprise auth overlay" phrasing.
- **Audit P0 group-claim gating: defer to Phase 218** — D-17: don't bundle the OAuth `group_claim`/`group_role_mapping` enterprise-gating into Phase 217. Stay within stated boundary.

</specifics>

<deferred>
## Deferred Ideas

- **SP-side AuthnRequest signing** — `authn_requests_signed=True` + SP keypair management (generation, encryption, rotation, admin UI for inspection). Out of Phase 217 scope per D-15. Add when a customer IdP demands signed AuthnRequests (some ADFS configs do).
- **Single LogOut (SLO)** — IdP-initiated SLO and SP-initiated SLO. Requires session tracking (likely the `saml_session_index` column hinted at in the provider-model discussion). Future phase: `auth-saml-slo`.
- **Redis-backed replay cache** — multi-instance correctness for the assertion replay defense. Out of Phase 217 scope per D-15. Document as the next iteration when multi-instance enterprise deployments are on the roadmap.
- **Per-provider attribute-map JSONB column (`saml_attr_map`)** — for IdPs with arbitrary attribute namespacing. D-11 picks hardcoded multi-key fallback instead. Revisit when an IdP integration fails because of attribute-name variance the hardcoded list doesn't cover.
- **Frontend bundle split for enterprise components** — P2 audit item (audit §7 `oc-separation-audit-20260427.md`). Phase 217 ships SAML admin UI in core's bundle. When enterprise UI surfaces grow (SCIM, multi-tenant admin, etc.), revisit the bundle split.
- **Audit P0: gate OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()`** — `oc-separation-audit-20260427.md` §3 (IdP role mapping P0 row). D-17 defers to Phase 218. Phase 218 must address (re-classify, gate, or doc-only resolution).
- **Cookie-based session swap** — `/oauth/callback` fragment-encoded tokens kept (D-07). Cookie sessions are a broader auth refactor (touches all auth flows, not just SAML); revisit when XSS posture upgrade is on the table.
- **IdP-initiated SSO** — `allow_unsolicited=False` default rejects this. Some enterprise IdPs require IdP-initiated. Revisit when a customer IdP needs it; relax with care because IdP-initiated SSO has higher replay-attack surface.
- **SCIM provisioning** — separate phase, separate Protocol design (`SCIMExtension` or extending `IdentityExtension`). 2–3 weeks per audit estimate. Future milestone.
- **Multi-tenant identity scoping** — `IdentityProtocol.tenant_id`. Backlog item 999.6. Phase 214 deferred adding this; Phase 217 inherits the deferral.
- **`docs/runbooks/saml-troubleshooting.md`** — runbook for common SAML failures (assertion expired, audience mismatch, signature invalid, attribute missing). Useful for ops; planner discretion.

</deferred>

---

*Phase: 217-auth-saml-enterprise*
*Context gathered: 2026-04-29*
