# Phase 217: auth-saml-enterprise — Research

**Researched:** 2026-04-29
**Domain:** SAML 2.0 SP overlay for enterprise edition; pysaml2; alembic enterprise branch; FastAPI extension wiring; React admin UI gating
**Confidence:** HIGH for code paths and pysaml2 API; MEDIUM for alembic graph repair (one path verified, alternatives flagged); MEDIUM-HIGH for hardening defaults

## User Constraints (from CONTEXT.md)

### Locked Decisions

CONTEXT.md `<decisions>` block contains 17 locked decisions (D-01..D-17). Of particular force on plans:

- **D-01..D-04** (Provider model architecture): SAML reuses `catalog.oauth_providers`; new enterprise migration `e002_add_saml_columns` re-adds the four nullable SAML columns and relaxes `chk_oauth_providers_type` to include `'saml'`; does NOT touch `chk_users_auth_provider`; users get `auth_provider='oauth'`. Cert stored Fernet-encrypted; SAML users link via existing `oauth_accounts.subject = NameID`.
- **D-05..D-08** (Identity wire-in): JWT-after-ACS fragment redirect (verbatim mirror of OAuth callback); SAML overlay registers under TWO seams (`registry['identity']` + `registry['_routers']`); ACS endpoint follows 11-step structure; per-provider metadata endpoint at `GET /auth/saml/{slug}/metadata`.
- **D-09..D-13** (Scaffold disposition): Salvage existing `replay.py` verbatim, salvage `config.py` f-string IdP metadata generation, modernize ALL imports per the explicit mapping table; extend the multi-key attribute fallback list with two ADFS URN claims; reuse OAuth admin CRUD endpoints (extend schemas with SAML fields); single `EnterpriseSamlExtension` class implements both Protocols and is dual-registered.
- **D-14..D-17** (UI / hardening / SC#1): Admin SAML UI lives in core frontend at `frontend/src/routes/admin/saml.tsx` (NOTE: actual project structure is `frontend/src/pages/admin/`, not `routes/`), gated by existing `useEdition()` hook; hardening = `want_assertions_signed=True`, `authn_requests_signed=False`, `allow_unsolicited=False`, `allow_unknown_attributes=True`, in-memory replay cache; scrub three SAML mentions in core docstrings; defer audit P0 (group_claim gating) to Phase 218.

### Claude's Discretion

- Migration revision ID (`e002_add_saml_columns` is placeholder)
- Commit decomposition (suggested 4-5 atomic commits)
- Mock IdP for tests (a/b/c options)
- Default `sp_entity_id` UI pre-fill value
- Whether to split `EnterpriseSamlExtension` into separate Auth + Identity classes
- Where `docs/saml.md` lives
- Audit-log shape extension if existing OAuth admin shape doesn't capture old/new values (FINDING: current shape does NOT capture old/new — see §11)
- Whether to ship `docs/runbooks/saml-troubleshooting.md`

### Deferred Ideas (OUT OF SCOPE)

- SP-side AuthnRequest signing (no SP keypair management in V1)
- Single LogOut (SLO)
- Redis-backed replay cache (in-memory only)
- Per-provider attribute-map JSONB column (`saml_attr_map`)
- Frontend bundle split for enterprise components
- Audit P0: gate OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()` (deferred to Phase 218)
- Cookie-based session swap
- IdP-initiated SSO
- SCIM provisioning
- Multi-tenant identity scoping
- `docs/runbooks/saml-troubleshooting.md`

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SAML-08 | `git grep -i saml` against core returns zero matches outside test fixtures + `docs-internal/`. | §15 (D-16 scrub list verified — 5 hits remain in core to scrub: 3 docstring lines + the `0002_initial_tables.py` CHECK literal + `2026_04_08_0001-strip_dead_saml_code.py`). The two migration files cannot be scrubbed — they are immutable history. **Recommendation: planner narrows SC#1 grep to exclude `backend/alembic/`** (or treat alembic versions as a SC#1 carve-out — file is named `*-strip_dead_saml_code.py` and contains operational SQL referencing the literal `'saml'` enum value; rewriting these would falsify migration history). |
| SAML-09 | Auth-extension hook is the only seam SAML registers into. | §8 — registry has `auth`, `audit`, `branding`, `identity`, `_routers` keys; SAML's dual registration uses `_routers` (router-mount loop, the active path) + `identity` (no-op IdentityExtension). Both seams pre-date Phase 217. Zero core mutation required. |
| SAML-10 | Admin tab community-hidden; backend 404. | §7 (`useEdition()` hook + `enterpriseOnly` filter pattern) + `require_enterprise()` already wired into the salvaged scaffold's router. |
| SAML-11 | SP-initiated SSO + metadata XML + signed assertion validation + JIT via `find_or_create_oauth_user()`. | §2 (pysaml2 API), §4 (OAuth callback flow), §5 (find_or_create_oauth_user contract). |
| SAML-12 | Configurable attribute → role mapping; audit log records mapping changes with old/new values. | §11 — **GAP IDENTIFIED**: existing OAuth admin endpoints log only `slug` (no old/new values). Planner must either (a) extend OAuth admin endpoints to capture old/new values for `group_claim` and `group_role_mapping` fields specifically (minimal surface), or (b) build a small diff helper. |

## 1. Executive Summary

Phase 217 has a clean architectural target — the SAML overlay registers into two seams that already exist in core (`_routers` for the live request-handling path; `identity` as a no-op breadcrumb honoring SAML-09's "auth-extension hook is the only seam" wording). All implementation lives in `~/Code/geolens-enterprise/`, scaffolded from a pre-v13.0 prototype that needs nothing more than import-path modernization. The pysaml2 API is mature (v7.5.4, no known CVEs as of 2026-04-29), the Docker image already ships `xmlsec1 + libxmlsec1-openssl` (its only system-binary requirement), and the salvaged scaffold's `Saml2Client` builder + `ReplayCache` + ACS structure is sound. **Three findings need explicit planning attention** before plans are written.

**Finding 1 — broken alembic graph (HIGH severity, blocks the migration plan).** `e001_enterprise_initial.py` declares `down_revision = "0010_add_saml_provider_columns"` but no migration with that revision ID exists in the core repo. The actual migration that originally added the SAML columns is `0002_initial_tables.py` (revision `0002_tbl`); the migration that dropped them is `2026_04_08_0001-strip_dead_saml_code.py` (revision `f3a4b5c6d7e8`). Running `alembic heads` against the enterprise overlay today would either fail or report a dangling ancestor. **Planner MUST repair `e001_enterprise_initial.down_revision` before adding `e002`.** Recommended target: `f3a4b5c6d7e8` (the strip-saml migration, current state when SAML columns are absent). See §3 for the verified safe revision graph.

**Finding 2 — SAML-12 audit gap (MEDIUM severity, requires plan-time decision).** `D-12` says "the existing OAuth admin endpoints already capture old/new values" — they do not. `backend/app/modules/settings/router.py:386,418` logs only `{"slug": body.slug}` to the audit log. SAML-12 explicitly requires "mapping changes are recorded in the existing audit log with old/new values." Planner must extend the admin-endpoint audit calls to capture old/new diffs for at minimum `group_claim` and `group_role_mapping` fields, or accept that the audit shape is satisfied at a lower bar than the requirement reads. The ROADMAP SC#4 wording ("mapping changes are recorded in the existing audit log") is more permissive than REQ SAML-12 ("with old/new values") — clarify with user in plan-checker if needed. See §11 for the minimal extension shape.

**Finding 3 — SC#1 grep scope (LOW severity, documentation issue).** After D-16 docstring scrub completes, `git grep -i saml backend/` will still return matches in two alembic migration files: (a) `0002_initial_tables.py` line 81 + 131 (the original `'saml'` enum value in CHECK constraints, defined before SAML was stripped); (b) `2026_04_08_0001-strip_dead_saml_code.py` (the entire migration is about SAML — filename, docstring, SQL literals). These are **immutable migration history** and cannot be edited without rewriting alembic. Planner should narrow SC#1 grep at the verification gate to `git grep -i saml backend/ ':!backend/alembic/'` (or carve out alembic explicitly in SC#1 wording; the spirit — "no SAML implementation code in core" — is satisfied because alembic versions are inert historical SQL artifacts).

**Primary recommendation:** Plans land in this order — (Plan 1) repair enterprise alembic graph + add `e002_add_saml_columns`; (Plan 2) modernize scaffold imports + add metadata endpoint + dual-Protocol/dual-registration; (Plan 3) extend OAuth schemas with SAML fields + Pydantic validation + extend admin-endpoint audit to capture old/new values; (Plan 4) frontend admin SAML page + sidebar gating; (Plan 5) SC#1 docstring scrub + phase verification gate. Test fixtures live at `backend/tests/fixtures/saml/`; integration tests in `backend/tests/test_saml_overlay.py` (extension-loaded app + mocked SAMLResponse XML); standalone enterprise unit tests stay in `~/Code/geolens-enterprise/tests/`.

## 2. pysaml2 API Reference

**Verified:** Context7 (`/identitypython/pysaml2`, 91 snippets, source reputation HIGH); confirmed against PyPI (latest 7.5.4, released 2025-10-07).

### Core APIs the scaffold uses

| API | Signature | Returns | Used in scaffold | Notes |
|-----|-----------|---------|------------------|-------|
| `Saml2Client(config: Saml2Config)` | constructor | `Saml2Client` | `config.py:77` | `[VERIFIED: Context7]` Accepts `config=` (built object) or `config_file=` (path). Scaffold uses object form. |
| `client.prepare_for_authenticate()` | `()` | `(reqid: str, info: dict)` | `router.py:61` | `[VERIFIED: Context7]` Convenience wrapper around `pick_binding` + `create_authn_request` + `apply_binding`. `info["headers"]` contains `[("Location", url)]` for HTTP-Redirect; `info["data"]` contains the auto-POST HTML form for HTTP-POST. Scaffold extracts the redirect URL — correct for HTTP-Redirect binding. |
| `client.parse_authn_request_response(saml_response, binding, outstanding=None)` | `(b64_str, BINDING_*, outstanding=None)` | `AuthnResponse` (`saml2.response.AuthnResponse`) | `router.py:91` | `[VERIFIED: Context7]` Validates signature, NotBefore/NotOnOrAfter, AudienceRestriction. Raises `StatusError`, `VerificationError`, `SignatureError` (all under `saml2.response`). Scaffold catches generic `Exception` — fine for V1. The `outstanding` arg is a dict of pending `req_id → relay_state`; scaffold passes nothing (relies on `allow_unsolicited=False` to reject unknown responses). |
| `authn_response.assertion.id` | attr | `str` | `router.py:96` | `[VERIFIED: pysaml2 source]` SAML 2.0 assertion ID — fed to `replay_cache.check_and_record(assertion_id)`. |
| `authn_response.get_subject()` | `()` | `saml2.saml.NameID` | `router.py:101` | `[VERIFIED: Context7]` `.text` returns the subject string regardless of NameID format. |
| `authn_response.ava` | attr | `dict[str, list[str]]` | `router.py:102` | `[VERIFIED: Context7]` Attribute Value Assertion — flat dict of attribute name → list of values. Scaffold's `_extract_attr` returns the first list element. |
| `create_metadata_string(configfile=None, config=None, valid="...", cert=..., keyfile=..., sign=...)` | from `saml2.metadata` | `bytes` (UTF-8 XML) | NOT YET in scaffold | `[VERIFIED: Context7]` Phase 217 adds the `/auth/saml/{slug}/metadata` endpoint per D-08. Pass `config=Saml2Config(...)` (already built by `build_saml_client`); `sign=False` and omit `cert`/`keyfile` for V1 (no SP signing per D-15). Returns `bytes` — return as `Response(content=..., media_type="application/samlmetadata+xml")`. |

### Saml2Config configuration shape

The scaffold's `build_saml_client()` constructs the config dict directly. Key options used:

```python
{
    "entityid": provider.sp_entity_id,                  # SP entityID (admin-set)
    "metadata": {"local": [metadata_path]},             # File path (pysaml2 requirement)
    "service": {
        "sp": {
            "endpoints": {
                "assertion_consumer_service": [(acs_url, BINDING_HTTP_POST)],
            },
            "allow_unsolicited": False,                  # Block unsolicited responses (D-15)
            "authn_requests_signed": False,              # No SP keypair (D-15)
            "want_assertions_signed": True,              # IdP MUST sign assertions (D-15)
            "want_response_signed": False,               # Response wrapper unsigned OK (D-15)
        },
    },
}
config = Saml2Config()
config.load(settings)
config.allow_unknown_attributes = True                   # Permissive attribute mode (D-15)
```

`[VERIFIED: Context7]` All five config keys above are documented; the scaffold uses them correctly.

**Notable absent options the scaffold does NOT set** (defaults apply, all OK for V1):
- `accepted_time_diff`: defaults to 0 seconds (no clock skew tolerance). For real IdPs, `60` is standard. **Plan recommendation:** add `"accepted_time_diff": 60` to scaffold's settings dict to handle minor clock drift between SP/IdP.
- `verify_ssl_cert`: defaults to True. Leave as-is.
- `name_id_format`: defaults to NAMEID_FORMAT_TRANSIENT (or auto). For most IdPs (Okta, Azure AD, ADFS) this is fine; for sub-claim-as-identifier flows, NAMEID_FORMAT_PERSISTENT may be preferable. Scaffold doesn't set it — accepts whatever the IdP sends.
- `xmlsec_binary`: defaults to PATH lookup. Docker image ships `xmlsec1` at `/usr/bin/xmlsec1` — works without explicit setting. `[VERIFIED: backend/Dockerfile:18]`

### Async-compat caveat

pysaml2 is a **synchronous library**. All `parse_authn_request_response`, `prepare_for_authenticate`, `create_metadata_string` calls block the event loop. For the SAML ACS endpoint (called once per login) this is acceptable — it's not a hot path. `[ASSUMED]` blocking time is <50ms per call on typical config.

If the planner finds latency concerns, `await asyncio.to_thread(client.parse_authn_request_response, ...)` is the standard mitigation. Not required for V1.

### XML hardening

`[CITED: github.com/IdentityPython/pysaml2 README]` pysaml2 internally uses `defusedxml` for parsing when available — the enterprise overlay already declares `defusedxml>=0.7.1` so this is handled. `[VERIFIED: pyproject.toml:12]`

### xmlsec1 system dependency

`[CITED: pysaml2 README]` pysaml2 depends on the `xmlsec1` binary at runtime for signature verification. The geolens core API Docker image installs both `xmlsec1` and `libxmlsec1-openssl`. `[VERIFIED: backend/Dockerfile:18]` The enterprise overlay does NOT need to add this — both API and migrate containers inherit the same image.

## 3. Alembic Branch Graph Analysis

**Confidence:** HIGH (all revision IDs and chains verified by direct file read).

### Current state — BROKEN

Core migration chain (verified via `grep "revision = "`):
```
0001_fdn → 0002_tbl → ... → c3d4e5f6a7b8 → g4h5i6j7k8l9 → ... → t6u7v8w9x0y1   [HEAD]
                                              ↑
                                              0002_initial_tables.py originally added
                                              the four SAML columns + 'saml' enum value
                                              in chk_oauth_providers_type and
                                              chk_users_auth_provider.

Within the chain (revisions e2f3a4b5c6d7 → f3a4b5c6d7e8):
  2026_04_07_0001-add_missing_fk_indexes.py    revision = e2f3a4b5c6d7
  2026_04_08_0001-strip_dead_saml_code.py      revision = f3a4b5c6d7e8
                                                ^ this is the migration that
                                                  DROPPED the SAML columns and
                                                  TIGHTENED both CHECK constraints
                                                  to remove 'saml'.
```

Enterprise migration:
```
e001_enterprise_initial.py   revision = e001_enterprise_initial
                              down_revision = "0010_add_saml_provider_columns"   ← PHANTOM
                              branch_labels = ("enterprise",)
```

**The phantom**: `0010_add_saml_provider_columns` does NOT exist in `backend/alembic/versions/`. `[VERIFIED: grep returns zero matches in repo]`. The enterprise branch's `down_revision` references a revision that has never existed in the current git history.

**Why it doesn't blow up today**: the enterprise overlay isn't actually running migrations against a live DB right now. The scaffold has been there since 2026-03-26 but `e001` has never been exercised end-to-end against a fresh DB with the modern core chain. The first `alembic upgrade heads` against the enterprise overlay will fail with: `ERROR: Can't locate revision identified by '0010_add_saml_provider_columns'`.

### Repair recommendation

**Option A (recommended): re-base `e001_enterprise_initial` onto `f3a4b5c6d7e8` (the current state-after-strip).**

Edit `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e001_enterprise_initial.py`:

```python
revision = "e001_enterprise_initial"
down_revision = "f3a4b5c6d7e8"           # was: "0010_add_saml_provider_columns"
branch_labels = ("enterprise",)
depends_on = None
```

This makes the enterprise branch chain off the current state where SAML columns are absent and the CHECK constraints are tight. `e001` is a no-op (just establishes the branch label), and `e002_add_saml_columns` re-adds the columns + relaxes the CHECK.

The chain becomes:
```
... → e2f3a4b5c6d7 → f3a4b5c6d7e8 → ... → t6u7v8w9x0y1   [core HEAD]
                          ↓
                          e001_enterprise_initial (no-op, branch label "enterprise")
                          ↓
                          e002_add_saml_columns (re-adds columns + relaxes CHECK)
```

`alembic heads` should then report two heads: `t6u7v8w9x0y1` (core) and `e002_add_saml_columns` (enterprise).

**Option B (alternative): make `e001` chain off `t6u7v8w9x0y1` (current core HEAD).**

This works equally well but ties `e001` to whatever the latest core migration happens to be at Phase 217 plan time. Less stable than Option A — any new core migration after Phase 217 will become the new HEAD, but the enterprise branch label is still attached at `t6u7v8w9x0y1`. In alembic this is fine (branches can attach anywhere), but Option A makes the architectural intent clearer: "enterprise branches off after SAML was stripped."

**Option C (rejected): collapse `e001` + `e002` into a single migration that adds the columns and relaxes the CHECK.**

Cleaner in some ways but loses the Phase 217 commit-decomposition story. Reject.

### `e002_add_saml_columns` shape

```python
"""Re-add SAML support to oauth_providers (enterprise overlay).

Inverse of core's 2026_04_08_0001-strip_dead_saml_code.py upgrade(). Adds
nullable columns and relaxes chk_oauth_providers_type to include 'saml'.

Does NOT touch chk_users_auth_provider — SAML users get auth_provider='oauth'
via find_or_create_oauth_user() (Phase 217 D-04).

Revision ID: e002_add_saml_columns
Revises: e001_enterprise_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "e002_add_saml_columns"
down_revision = "e001_enterprise_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_providers", sa.Column("idp_entity_id", sa.String(512), nullable=True), schema="catalog")
    op.add_column("oauth_providers", sa.Column("idp_sso_url", sa.String(512), nullable=True), schema="catalog")
    op.add_column("oauth_providers", sa.Column("idp_certificate", sa.Text(), nullable=True), schema="catalog")
    op.add_column("oauth_providers", sa.Column("sp_entity_id", sa.String(512), nullable=True), schema="catalog")

    op.drop_constraint("chk_oauth_providers_type", "oauth_providers", type_="check", schema="catalog")
    op.create_check_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        "provider_type IN ('oidc', 'google', 'microsoft', 'saml')",
        schema="catalog",
    )


def downgrade() -> None:
    # Destructive: any SAML provider rows must be deleted first.
    op.execute("DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
               "(SELECT id FROM catalog.oauth_providers WHERE provider_type = 'saml')")
    op.execute("DELETE FROM catalog.oauth_providers WHERE provider_type = 'saml'")

    op.drop_constraint("chk_oauth_providers_type", "oauth_providers", type_="check", schema="catalog")
    op.create_check_constraint(
        "chk_oauth_providers_type",
        "oauth_providers",
        "provider_type IN ('oidc', 'google', 'microsoft')",
        schema="catalog",
    )

    op.drop_column("oauth_providers", "sp_entity_id", schema="catalog")
    op.drop_column("oauth_providers", "idp_certificate", schema="catalog")
    op.drop_column("oauth_providers", "idp_sso_url", schema="catalog")
    op.drop_column("oauth_providers", "idp_entity_id", schema="catalog")
```

### Verification commands at plan time

After the repair, run inside the migrate container with the enterprise overlay loaded:

```bash
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml run --rm migrate sh -c \
  "uv add --editable /enterprise && uv run alembic heads"
# Expected: two heads — t6u7v8w9x0y1 (or current core HEAD) AND e002_add_saml_columns

docker compose -f docker-compose.yml -f docker-compose.enterprise.yml run --rm migrate sh -c \
  "uv add --editable /enterprise && uv run alembic check"
# Expected: clean (no auto-generated diff against the enterprise-applied schema)

docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build
# Confirm the API starts; check logs for 'Edition detected edition=enterprise features=[enterprise]'
```

## 4. OAuth Callback Flow

**Source:** `backend/app/modules/auth/oauth/router.py:85-148` `[VERIFIED: direct file read]`

The SAML ACS endpoint MUST mirror this verbatim per D-07. Step-by-step contract for the planner:

| # | OAuth callback step | File:line | SAML ACS analog |
|---|---------------------|-----------|------------------|
| 1 | Compute `frontend_url = await get_public_app_url(db, request=request)` BEFORE try block | `router.py:95` | Same — needed for both happy-path and error-path redirects |
| 2 | Inside try: build OAuth client + provider | `router.py:98` | `provider = await get_provider_by_slug(db, slug)` + 404 check on `provider.provider_type != 'saml'` |
| 3 | Exchange code for tokens (OAuth-specific) | `router.py:101` | (SAML has no analog — `parse_authn_request_response(saml_response, BINDING_HTTP_POST)` replaces this) |
| 4 | Extract userinfo dict | `router.py:104-106` | Build `userinfo = {"sub": NameID, "email": ..., "name": ..., [provider.group_claim]: groups}` from `authn_response.ava` |
| 5 | `user = await find_or_create_oauth_user(db, provider, dict(userinfo), dict(token))` | `router.py:109-111` | `user = await find_or_create_oauth_user(db, provider, userinfo, {})` — **passes empty dict for `tokens` arg; SAML has no IdP tokens to record** |
| 6 | `user.last_login_at = func.now()` | `router.py:114` | Same |
| 7 | Read JWT expiry config from PersistentConfig | `router.py:117-118` | `expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)` + `expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)` |
| 8 | Construct `AuthenticatedIdentity(user_id=user.id, username=user.username, email=user.email)` | `router.py:120-122` | Same |
| 9 | Issue access + refresh tokens via `AuthService(db)` | `router.py:123-127` | Same |
| 10 | `await db.commit()` | `router.py:128` | Same |
| 11 | Build redirect URL: `f"{frontend_url}/oauth/callback#token={access_token}&refresh_token={refresh_token}&expires_in={expire_minutes * 60}"` and return `RedirectResponse(url=..., status_code=302)` | `router.py:130-136` | Same. **Critical: same `/oauth/callback` path — SAML reuses the OAuth callback frontend handler.** |
| 12 | Exception handler: re-raise `HTTPException` (404s pass through); on generic `Exception`, log with correlation_id, redirect to `f"{frontend_url}/oauth/callback#error=..."` | `router.py:138-148` | Salvaged scaffold uses `quote(str(exc))` instead of correlation_id — **acceptable but planner should consider matching OAuth's `correlation_id` pattern for parity (logs the full exception under a tag, returns only the correlation_id to user)**. |

### Frontend handler (verified)

`frontend/src/pages/OAuthCallbackPage.tsx` `[VERIFIED: file read]` consumes the `#token=...&refresh_token=...&expires_in=...` URL fragment. The same handler will receive SAML callbacks transparently — no SAML-specific frontend route is needed (per D-07).

The `error=...` param is also handled (lines 22-27): redirects to `/login` with `state.oauthError`. SAML errors will surface in the same toast/notification surface as OAuth errors. Acceptable for V1.

### Helpers the OAuth callback uses

| Helper | File:line | SAML ACS reuse |
|--------|-----------|----------------|
| `get_provider_by_slug(db, slug)` | `oauth/service.py:46-49` | YES — drop-in |
| `find_or_create_oauth_user(db, provider, userinfo, tokens)` | `oauth/service.py:138-259` | YES — pass `{}` for tokens; see §5 for full contract |
| `get_public_app_url(db, request=request)` | `core/public_urls.py:221-227` | YES |
| `get_public_api_url(db, request=request)` | `core/public_urls.py:239-245` | YES (for ACS URL construction) |
| `ACCESS_TOKEN_EXPIRE_MINUTES.get(db)` | `core/persistent_config.py:370-376` | YES |
| `REFRESH_TOKEN_EXPIRE_DAYS.get(db)` | `core/persistent_config.py:378-384` | YES |
| `AuthenticatedIdentity(user_id, username, email)` | `auth/providers/__init__.py:13-23` | YES |
| `AuthService(db).create_access_token(identity, expire_minutes=...)` | `auth/service.py:28-52` | YES |
| `AuthService(db).create_refresh_token(user_id, expire_days=...)` | `auth/service.py:58-78` | YES |

## 5. find_or_create_oauth_user() Contract

**Source:** `backend/app/modules/auth/oauth/service.py:138-259` `[VERIFIED: direct file read]`

### Signature

```python
async def find_or_create_oauth_user(
    db: AsyncSession,
    provider: OAuthProvider,        # Reuses model; SAML rows are OAuthProvider rows with provider_type='saml'
    userinfo: dict,                  # Must contain "sub" (NameID); "email", "name", and provider.group_claim are optional
    token: dict,                     # OAuth tokens; SAML passes {} (unused by current implementation; planner verifies)
) -> User:
```

### Resolution algorithm (3 steps)

1. **Step 1 (`oauth/service.py:164-178`)** — Existing `OAuthAccount` lookup by `(provider_id, subject)`. If found, returns linked user. **For SAML: subject is NameID.** The existing `UniqueConstraint('provider_id', 'subject', name='uq_oauth_account_provider_subject')` prevents duplicate linkage.
2. **Step 2 (`oauth/service.py:180-201`)** — Email match (case-insensitive). If `userinfo["email"]` matches an existing user, links new `OAuthAccount` and returns. **For SAML:** if the IdP sends an email attribute (95%+ do), this enables seamless account linking when an admin previously created a local account.
3. **Step 3 (`oauth/service.py:203-258`)** — Auto-create. Generates username from email prefix or display name; resolves role via `_resolve_role(groups, mapping, default)` at `oauth/service.py:217-219`; creates `User(auth_provider="oauth", status="active", is_active=True)` + `UserRole` + `OAuthAccount` link.

### Role mapping logic (`oauth/service.py:125-135 and 217-219`)

```python
def _resolve_role(groups, mapping, default):
    if groups and mapping:
        for group in groups:
            if group in mapping:
                return mapping[group]
    return default
```

**Consumed by SAML unchanged.** SAML's `_extract_attr` populates `userinfo[provider.group_claim]` from the SAML AVA dict; `find_or_create_oauth_user` then extracts `groups = userinfo.get(provider.group_claim)` and feeds it to `_resolve_role`. The "first match wins" semantics carry over. Falls back to `provider.default_role` if no group matches.

### Side effects worth noting

| Behavior | Caller responsibility |
|----------|----------------------|
| Sets `user.last_login_at` ? | **No** — caller must set this. OAuth router does it at `router.py:114`. SAML scaffold does it at `router.py:135`. |
| Commits the transaction? | **No** — calls `db.flush()` only. Caller commits. OAuth router commits at `router.py:128`. |
| Refreshes `User` to load relationships? | YES — `db.refresh(new_user)` at `oauth/service.py:251` (only for the new-user path; existing-user paths return the linked relationship eager-loaded via `lazy="selectin"`). |
| Logs to structlog? | YES — info-level for each branch. SAML inherits this for free. |
| Empty `tokens` dict OK? | YES — current implementation does NOT consume the `tokens` arg. Passing `{}` is safe. **Plan recommendation: confirm at plan time by re-reading `find_or_create_oauth_user`; if the function gains token-side-effects later, SAML's empty dict could break.** |

## 6. Schema Extension Pattern

**Current state:** `backend/app/modules/auth/oauth/schemas.py` `[VERIFIED: direct file read]` uses **`Literal['google', 'microsoft', 'oidc']`** for `provider_type`. NOT a discriminated union — there's no per-type field validation today. URL fields are validated by a single `field_validator` (`_check_url`) calling `_validate_optional_http_url`.

### Recommended extension shape

Use **`model_validator(mode='after')`** rather than retrofit a Pydantic discriminated union (D-12 fallback option). Reasons:

1. The existing schema is flat with no nested per-type sub-models. Discriminated unions require restructuring to `Union[GoogleProvider, MicrosoftProvider, OIDCProvider, SAMLProvider]` — a larger refactor that risks breaking the existing OAuth admin endpoints.
2. `model_validator(mode='after')` runs after individual field validation, has access to all fields, and lets us return clear `ValueError` messages.
3. Matches the project's "ship fast / minimal blast radius" posture (D-09).

### Example

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal

# Add to top with other constants
_IDP_ENTITY_ID_MAX = 512
_IDP_SSO_URL_MAX = 512
_SP_ENTITY_ID_MAX = 512
# idp_certificate is unbounded Text — no max in Pydantic; let Text handle it


class OAuthProviderCreate(BaseModel):
    # ... existing fields ...

    provider_type: Literal["google", "microsoft", "oidc", "saml"] = Field(
        description="OAuth or SAML provider type. Choose 'saml' to enable SAML SSO (requires enterprise edition)."
    )

    # client_id and client_secret stay required for OAuth providers; for SAML
    # they should be empty strings or omitted. Mark them Optional and validate
    # in the model_validator below.
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=1000)

    # ── SAML-specific fields (nullable, only required when provider_type='saml') ──
    idp_entity_id: str | None = Field(
        default=None, max_length=_IDP_ENTITY_ID_MAX,
        description="SAML IdP entityID. Required for SAML providers."
    )
    idp_sso_url: str | None = Field(
        default=None, max_length=_IDP_SSO_URL_MAX,
        description="SAML IdP SSO URL (HTTP-Redirect or HTTP-POST binding). Required for SAML providers."
    )
    idp_certificate: str | None = Field(
        default=None,
        description="SAML IdP signing certificate (PEM, base64). Required for SAML providers. Stored Fernet-encrypted."
    )
    sp_entity_id: str | None = Field(
        default=None, max_length=_SP_ENTITY_ID_MAX,
        description="SP entityID for this provider. Required for SAML providers. Default: {public_api_url}/auth/saml/{slug}."
    )

    @field_validator("idp_sso_url")
    @classmethod
    def _check_idp_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)

    @model_validator(mode="after")
    def _validate_per_type(self):
        if self.provider_type == "saml":
            missing = [
                f for f in ("idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id")
                if not getattr(self, f)
            ]
            if missing:
                raise ValueError(
                    f"SAML providers require: {', '.join(missing)}"
                )
            # SAML providers may omit OAuth credentials
        else:
            # OAuth/OIDC providers: client_id + client_secret REQUIRED;
            # SAML fields MUST be null
            if not self.client_id or not self.client_secret:
                raise ValueError(
                    f"{self.provider_type} providers require client_id and client_secret"
                )
            extra = [
                f for f in ("idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id")
                if getattr(self, f)
            ]
            if extra:
                raise ValueError(
                    f"{self.provider_type} providers must not set SAML fields: {', '.join(extra)}"
                )
        return self
```

### `OAuthProviderUpdate` extension

Mirror the same pattern — add the four SAML fields as `str | None = Field(default=None, ...)`. The `model_validator` is more permissive on Update (only validate consistency when `provider_type` is being changed OR when SAML fields are being set on a non-SAML provider). Suggested simplification: skip the validator entirely on Update and rely on the DB CHECK constraint + the existing OAuth admin update endpoint's logic.

### Service-layer integration

`backend/app/modules/auth/oauth/service.py:18-43` (`create_provider`) and `:78-97` (`update_provider`) need to copy the four SAML fields into `OAuthProvider`. The `idp_certificate` field MUST be encrypted via `encrypt_secret()` before storage (D-03). Pattern:

```python
# In create_provider
provider = OAuthProvider(
    # ... existing fields ...
    idp_entity_id=data.idp_entity_id,
    idp_sso_url=data.idp_sso_url,
    idp_certificate=encrypt_secret(data.idp_certificate) if data.idp_certificate else None,
    sp_entity_id=data.sp_entity_id,
)
```

### OAuthProvider ORM model extension

`backend/app/modules/auth/oauth/models.py:22-59` `[VERIFIED: file read]` — add four `Mapped[str | None] = mapped_column(..., nullable=True)` columns. The CHECK constraint `chk_oauth_providers_type` literal stays at `('oidc', 'google', 'microsoft')` in the model — the enterprise migration relaxes it at the DB level. `[ASSUMED]` SQLAlchemy doesn't enforce CheckConstraint client-side, so this asymmetry is fine.

**Important caveat (per CONTEXT.md risk-surface line 165):** Adding the four SAML columns to the core `OAuthProvider` model puts SAML-coded identifiers (`idp_entity_id`, etc.) in core source. SC#1's `git grep -i saml` won't trigger on these (no literal "saml" string), but a stricter audit might flag them. Acceptable per CONTEXT.md risk-surface analysis.

## 7. Frontend Edition Detection Pattern

**Confidence:** HIGH (verified by file read).

### The hook

`frontend/src/hooks/use-edition.ts` `[VERIFIED: file read]`:

```typescript
import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { fetchEdition } from '@/api/edition';

export function useEdition() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.edition.info,
    queryFn: fetchEdition,
    staleTime: Infinity,
    gcTime: Infinity,
  });

  return {
    edition: data?.edition ?? 'community',
    features: data?.features ?? EMPTY_FEATURES,
    isEnterprise: data?.edition === 'enterprise',
    isLoading,
  };
}
```

The data fetcher (`frontend/src/api/edition.ts`) calls `GET /settings/edition/`. `[VERIFIED: file read]` Backend implementation lives at `backend/app/modules/settings/router.py:467-473` (returns `EditionInfoResponse`) — wraps `app.core.edition.get_edition()`.

### Existing usage pattern (audit-export precedent)

`frontend/src/components/admin/AdminSidebar.tsx` `[VERIFIED: file read]`:

```typescript
const settingsItems = [
  // ... other items ...
  { labelKey: 'admin:settings.tabs.appearance', to: '/admin/settings/appearance', icon: Paintbrush, enterpriseOnly: true },
  // ... other items ...
] as const;

export function AdminSidebar() {
  const { isEnterprise } = useEdition();
  const visibleSettingsItems = settingsItems.filter(item => !item.enterpriseOnly || isEnterprise);
  // ...
}
```

This is the exact pattern Phase 217's SAML nav item must follow. **Plan recommendation:** add a new entry to the `operationsItems` (or its own `enterpriseItems` group) in `AdminSidebar.tsx`:

```typescript
const operationsItems: readonly OperationItem[] = [
  // ... existing ...
  { labelKey: 'adminNav.saml', to: '/admin/saml', icon: Lock, enterpriseOnly: true },  // OR a new group
];
```

(Note the existing `operationsItems` typedef doesn't have an `enterpriseOnly` field — planner adds it or follows the `settingsItems` pattern.)

### Frontend project structure correction

CONTEXT.md D-14 says "core frontend repo at `frontend/src/routes/admin/saml.tsx`". The actual project does NOT use `routes/` — it uses `pages/admin/`. `[VERIFIED: ls /Users/ishiland/Code/geolens/frontend/src]`

Existing admin pages: `frontend/src/pages/admin/AdminAuditPage.tsx`, `AdminSettingsPage.tsx`, `AdminUsersPage.tsx`, `AdminJobsPage.tsx`, `AdminConfigOpsPage.tsx`, `AdminSharedMapsPage.tsx`, `AdminOverviewPage.tsx`. **Plan recommendation:** create `frontend/src/pages/admin/AdminSamlPage.tsx`. The route is registered in `frontend/src/App.tsx` (top-level router config).

### Existing OAuth admin form (reference for SAML admin UI shape)

The OAuth provider admin lives **inside the Settings page**, not as a standalone admin page. Specifically: `frontend/src/components/admin/settings/SettingsAuthTab.tsx` (689 lines) `[VERIFIED: file read first 100 lines]`. It already calls `listOAuthProviders`, `createOAuthProvider`, `updateOAuthProvider`, `deleteOAuthProvider` from `@/api/settings`. SAML can either:

1. **(Recommended) Standalone page** at `/admin/saml` — cleaner separation, easier to gate. Reuses the same `listOAuthProviders` API call but filters to `provider_type === 'saml'`. Form is purpose-built for SAML fields.
2. **Tab inside SettingsAuthTab** — smaller code, but pollutes a community-edition file with enterprise-only logic. **Reject**.

Pick option 1. New API module `frontend/src/api/saml.ts` (or extend `api/settings.ts`) with typed wrappers:

```typescript
export interface SamlProviderConfig extends OAuthProviderConfig {
  idp_entity_id: string;
  idp_sso_url: string;
  sp_entity_id: string;
  // idp_certificate is write-only (encrypted at rest, never returned)
}

export async function fetchSamlMetadata(slug: string): Promise<string> {
  const response = await fetch(`/api/auth/saml/${slug}/metadata`);
  return response.text();
}
```

## 8. Enterprise Extension Loader

**Source:** `backend/app/api/main.py:100-136` `[VERIFIED: file read]`

### Startup mount order

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... DB readiness ...
    await seed_roles()
    await seed_initial_admin()

    load_extensions()                               # ← entry-point discovery; populates _extensions and _routers
    init_edition(list_extensions())                 # ← detects edition based on loaded extensions
    edition_info = get_edition()
    logger.info("Edition detected", edition=edition_info.edition, features=...)

    for ext_router in get_extension_routers():
        app.include_router(ext_router)              # ← mounts SAML router into FastAPI app

    # ... other startup (storage, marketplace, cache, tile pool, etc) ...
    yield
    # ... shutdown ...
```

The mount order is:
1. `load_extensions()` runs first — iterates entry-points group `geolens.extensions`, calls each `register_extensions(registry)` callback.
2. `register_extensions` populates `registry["auth"]`, `registry["audit"]`, `registry["branding"]`, `registry["identity"]` (Phase 217 adds this), and `registry["_routers"] = [...]`.
3. The `_routers` list is **popped** out of `_extensions` at `extensions/__init__.py:54` and held separately in `_routers`.
4. `init_edition` runs — sets edition to "enterprise" if any extensions are loaded.
5. `for ext_router in get_extension_routers(): app.include_router(ext_router)` mounts each.

### Implication for SAML registration

The salvaged scaffold's `EnterpriseSamlExtension` already implements `get_auth_methods() -> ['saml']` (satisfies `AuthExtension`). Phase 217 adds `resolve_identity_from_token(token, request, db) -> None` (satisfies `IdentityExtension`). Phase 217 also updates `geolens_enterprise/__init__.py:register_extensions`:

```python
def register_extensions(registry: dict) -> None:
    saml_ext = _get_saml_extension()  # Single instance
    registry["auth"] = saml_ext
    registry["identity"] = saml_ext   # NEW — Phase 217 D-13 dual registration

    registry["audit"] = _get_audit_extension()
    registry["branding"] = _get_branding_extension()

    registry["_routers"] = _get_routers()   # SAML router already in this list


def _get_saml_extension():
    from geolens_enterprise.auth.saml import EnterpriseSamlExtension
    return EnterpriseSamlExtension()
```

### Router prefix collision check

The salvaged SAML router uses `prefix="/auth/saml"` `[VERIFIED: scaffold/router.py:28]`. Core has no `/auth/saml/*` routes. `[VERIFIED: grep across backend/app]` — only `/auth/oauth/*` exists. Zero collision risk.

**Note about `root_path="/api"`:** the FastAPI app has `root_path="/api"` (`api/main.py:408`). All routes are served under `/api/...`. The SAML routes will be `/api/auth/saml/{slug}/login`, `/api/auth/saml/{slug}/acs`, `/api/auth/saml/{slug}/metadata` from the browser's perspective. The `acs_url` constructed inside the scaffold uses `get_public_api_url()` which already includes `/api` if needed. Verify at plan time.

## 9. Scaffold Modernization Map

**Confidence:** HIGH (every old path verified; every new path verified).

| Scaffold file | Old import (broken) | New import (verified) |
|---------------|---------------------|------------------------|
| `router.py:12` | `from app.auth.oauth.service import find_or_create_oauth_user, get_provider_by_slug` | `from app.modules.auth.oauth.service import find_or_create_oauth_user, get_provider_by_slug` `[VERIFIED]` |
| `router.py:13` | `from app.auth.providers import AuthenticatedIdentity` | `from app.modules.auth.providers import AuthenticatedIdentity` `[VERIFIED]` |
| `router.py:16` | `from app.auth.service import AuthService` | `from app.modules.auth.service import AuthService` `[VERIFIED]` |
| `router.py:17` | `from app.dependencies import get_db` | `from app.core.dependencies import get_db` `[VERIFIED — NOT app.api.deps as CONTEXT.md D-10 said; planner verifies]` |
| `router.py:18` | `from app.extensions.guards import require_enterprise` | `from app.platform.extensions.guards import require_enterprise` `[VERIFIED]` |
| `router.py:19-22` | `from app.persistent_config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS` | `from app.core.persistent_config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS` `[VERIFIED]` |
| `router.py:23` | `from app.public_urls import get_public_api_url, get_public_app_url` | `from app.core.public_urls import get_public_api_url, get_public_app_url` `[VERIFIED]` |
| `config.py:10` | `from app.auth.oauth.encryption import decrypt_secret` | `from app.modules.auth.oauth.encryption import decrypt_secret` `[VERIFIED]` |
| `config.py:11` | `from app.auth.oauth.models import OAuthProvider` | `from app.modules.auth.oauth.models import OAuthProvider` `[VERIFIED]` |

### CONTEXT.md D-10 correction

CONTEXT.md D-10 lists the new path as `from app.api.deps import get_db (verify exact path during planning)`. **Verified path is `from app.core.dependencies import get_db`** — `app/api/deps.py` does not exist; `app/api/` only contains `main.py`, `router.py`, `middleware/`. The OAuth router itself uses `from app.core.dependencies import get_db` `[VERIFIED: oauth/router.py:17]`.

### Additional scaffold modernization items

1. **`config.py` settings dict:** add `"accepted_time_diff": 60` to handle clock skew between SP/IdP — see §2 hardening discussion.
2. **`router.py` exception handler:** consider matching OAuth's correlation_id pattern (per §4 step 12).
3. **`router.py` ADFS attribute keys:** extend the multi-key fallback list in `_extract_attr` per D-11. Current scaffold (router.py:104-120) covers OASIS-style and basic forms; add:
   ```python
   email = _extract_attr(attributes, [
       "email", "mail", "emailAddress",
       "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
   ])
   name = _extract_attr(attributes, [
       "displayName", "name", "cn",
       "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
       "http://schemas.microsoft.com/identity/claims/displayname",  # NEW per D-11
   ])
   # New: groups extraction supports ADFS URN
   if provider.group_claim:
       groups = _extract_attr(attributes, [
           provider.group_claim,
           "http://schemas.xmlsoap.org/claims/Group",  # NEW per D-11
       ])
   ```
4. **NEW `metadata` endpoint** (D-08, not in scaffold today):
   ```python
   @router.get("/{slug}/metadata")
   async def saml_metadata(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
       provider = await get_provider_by_slug(db, slug)
       if not provider or not provider.enabled or provider.provider_type != "saml":
           raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
       public_api_url = await get_public_api_url(db, request=request)
       acs_url = f"{public_api_url}/auth/saml/{slug}/acs"
       client = build_saml_client(provider, acs_url)
       from saml2.metadata import create_metadata_string
       metadata_xml = create_metadata_string(configfile=None, config=client.config, sign=False)
       return Response(content=metadata_xml, media_type="application/samlmetadata+xml")
   ```

## 10. Test Fixture Strategy

**Confidence:** MEDIUM-HIGH (path conventions inferred from existing test layout).

### Test placement

| Test type | Location | Rationale |
|-----------|----------|-----------|
| **Unit tests for SAML config builder** | `~/Code/geolens-enterprise/tests/test_saml_config.py` | Doesn't need core; tests `build_saml_client()` and `_build_idp_metadata_xml()` in isolation. |
| **Unit tests for replay cache** | `~/Code/geolens-enterprise/tests/test_replay_cache.py` | Already a candidate; `replay.py` is dependency-free. |
| **Unit tests for `EnterpriseSamlExtension` Protocols** | `~/Code/geolens-enterprise/tests/test_registration.py` (extend) | Already exists; add assertions for dual-Protocol registration. |
| **Integration test for full SAML ACS flow** | `backend/tests/test_saml_overlay.py` (NEW) | Needs core app + DB + extensions registry. Stand up app with the enterprise overlay registered programmatically (no docker), POST a fixture SAML response, assert (a) JIT-provisioned user exists, (b) JWT redirect URL returned. |
| **SAML response XML fixtures** | `backend/tests/fixtures/saml/` (NEW) | SC#1 carve-out: "outside test fixtures and `docs-internal/`" — fixture path must contain a recognizable marker. `tests/fixtures/saml/` makes the carve-out unambiguous. |

### Mock SAML response strategy

Per CONTEXT.md "Claude's Discretion: Mock IdP for tests":
- **(a) Hardcoded SAMLResponse XML fixtures** — recommended for V1. Generate once with a tool like `samltest.id` or pysaml2's `Server` IdP simulator, save the resulting base64-encoded `<samlp:Response>` to `backend/tests/fixtures/saml/idp_response_signed.xml.b64`. Tests load → POST to ACS → assert outcome. Caveat: signature validation requires the matching IdP cert; either (i) sign with a fixture cert and configure the test provider to use that fixture cert, or (ii) override `want_assertions_signed=False` for unit tests (the code path is the same).
- **(b) pysaml2 IdP simulator** — for the one full-roundtrip integration test. Stand up `saml2.server.Server` with a fixture IdP config, generate signed assertions in-process. Slower but true end-to-end. **Recommended for one test only** (`test_saml_full_roundtrip`).
- **(c) Docker SimpleSAMLphp** — overkill for V1; reject.

### Fixture cert generation

```bash
openssl req -x509 -newkey rsa:2048 -keyout backend/tests/fixtures/saml/idp_key.pem \
  -out backend/tests/fixtures/saml/idp_cert.pem -days 36500 -nodes \
  -subj "/CN=fixture-idp.geolens.test"
```

Commit both files to the repo. They're test-only and never used outside tests. Add `.gitattributes` text marker if needed.

### Existing test_extensions.py touchpoint

`backend/tests/test_extensions.py:230` mentions Phase 217's SAML overlay (D-16 scrub target). The replacement text per D-16: "must not raise TypeError. Enterprise auth overlays rely on this contract for their DB-lookup wire-in." `[VERIFIED: file read line 220-238]`

## 11. Audit Log Shape

**GAP IDENTIFIED — flagged in §1 as Finding 2.**

### Current OAuth admin audit log calls

`backend/app/modules/settings/router.py:386-394` (create) `[VERIFIED: file read]`:
```python
await log_action(
    session=db,
    user_id=user.id,
    action="oauth_provider.create",
    resource_type="oauth_provider",
    resource_id=provider.id,
    details={"slug": body.slug},                # ← only slug
    ip_address=ip,
)
```

`backend/app/modules/settings/router.py:418-426` (update) `[VERIFIED: file read]`:
```python
await log_action(
    session=db,
    user_id=user.id,
    action="oauth_provider.update",
    resource_type="oauth_provider",
    resource_id=provider.id,
    details={"slug": provider.slug},             # ← only slug
    ip_address=ip,
)
```

`backend/app/modules/settings/router.py:450-458` (delete): same pattern — only logs `slug`.

### What SAML-12 requires

> "Configurable SAML attribute → role mapping (e.g., `groups` → admin/editor/viewer) administered through the same admin UI tab; **audited via the existing audit log**."

ROADMAP §Phase 217 SC#4 strengthens this:
> "SAML attribute → role mapping (e.g., `groups` → admin/editor/viewer) is configurable through the same admin tab; **mapping changes are recorded in the existing audit log with old/new values.**"

CONTEXT.md D-12 says:
> "The existing audit-log writes for OAuth provider mutations already capture old/new values, satisfying SAML-12."

**This is incorrect.** The existing writes log only the slug.

### Minimal extension recommendation

In the `update_oauth_provider` endpoint, before calling `oauth_service.update_provider(...)`:

```python
# Capture old values for audit (Phase 217 SAML-12 satisfaction)
old_values = {
    "group_claim": provider.group_claim,
    "group_role_mapping": provider.group_role_mapping,
    "default_role": provider.default_role,
    "enabled": provider.enabled,
}

provider = await oauth_service.update_provider(db, provider, body)

# Build diff of changed fields
changes = {}
for field, old in old_values.items():
    new = getattr(provider, field)
    if old != new:
        changes[field] = {"old": old, "new": new}

await log_action(
    session=db,
    user_id=user.id,
    action="oauth_provider.update",
    resource_type="oauth_provider",
    resource_id=provider.id,
    details={"slug": provider.slug, "changes": changes},
    ip_address=ip,
)
```

This is a **~10 LOC change** to one endpoint. Satisfies SAML-12 with old/new values. Apply same pattern to `create_oauth_provider` (capture full new state under `"created"` key) and `delete_oauth_provider` (capture full old state under `"deleted"` key).

**Note:** the `idp_certificate` field MUST be redacted from audit logs (it's a credential). Suggested: log `"idp_certificate": "<redacted>"` if present in the diff. Same for `client_secret_encrypted` (already protected because Pydantic Update doesn't expose `_encrypted` fields).

### Why this isn't a SAML-specific endpoint

Per D-12, SAML providers go through the same `POST/PUT/DELETE /settings/oauth-providers/` endpoints. So the audit-shape extension applies to ALL provider mutations (OAuth and SAML). This is the right architectural call — SAML-12 audit guarantee comes "for free" via the shared endpoint, but only after the audit shape is extended.

## 12. Validation Architecture

**Section required by Nyquist gate.** The `.planning/config.json` is checked separately, but in absence of a `false` flag, treat as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x with pytest-asyncio (existing project standard) |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (existing) |
| Quick run command | `cd backend && uv run pytest tests/test_saml_overlay.py -x` (after Wave 0 file creation) |
| Full suite command | `cd backend && uv run pytest -x` (existing 2001-test baseline) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SAML-08 | `git grep -i saml backend/` zero matches outside fixtures + docs-internal + alembic | shell | `git grep -i saml backend/ ':!backend/alembic/' ':!backend/tests/fixtures/saml/' ':!backend/tests/test_saml_overlay.py'` (expects empty) | ❌ Wave 0 — runs at Phase verification gate |
| SAML-09 | Core has no SAML-specific code paths; the SAML overlay registers via `geolens.extensions` entry_point | unit | `pytest backend/tests/test_extensions.py::test_identity_extension_typed_accessor_returns_registered_or_default -x` (existing) + new `test_saml_overlay_registers_under_identity_and_routers` | ❌ Wave 0 |
| SAML-10 | Admin UI hides SAML tab in community; backend returns 404 on `/auth/saml/providers` in community | integration | `pytest backend/tests/test_saml_overlay.py::test_saml_endpoint_404_in_community -x` (no overlay loaded → require_enterprise raises 404) | ❌ Wave 0 |
| SAML-11 | SP-initiated SSO end-to-end: metadata endpoint returns valid XML; signed assertion validation; JIT user via `find_or_create_oauth_user()` | integration | `pytest backend/tests/test_saml_overlay.py::test_saml_metadata_xml_valid -x` AND `test_saml_acs_signed_assertion_jit_provisions_user -x` AND `test_saml_acs_rejects_invalid_signature -x` AND `test_saml_acs_rejects_expired_assertion -x` AND `test_saml_acs_rejects_replayed_assertion -x` | ❌ Wave 0 |
| SAML-12 | Attribute → role mapping configurable; audit log captures old/new values on update | integration | `pytest backend/tests/test_saml_overlay.py::test_saml_provider_update_logs_old_new_role_mapping -x` AND `test_saml_attribute_to_role_mapping_via_provider_group_claim -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_saml_overlay.py -x` (~10 SAML tests, <30s)
- **Per wave merge:** `cd backend && uv run pytest -x` (full 2001-test baseline + new SAML tests)
- **Phase gate:** Full suite green + `cd backend && uv run alembic check` clean + `cd ~/Code/geolens-enterprise && uv run pytest -x` clean + `git grep -i saml backend/` produces only allowlisted hits (alembic + fixtures)

### Wave 0 Gaps

- [ ] `backend/tests/fixtures/saml/idp_cert.pem` + `idp_key.pem` — fixture IdP signing keypair (openssl-generated)
- [ ] `backend/tests/fixtures/saml/idp_response_signed.xml.b64` — pre-signed SAML response from a known fixture IdP (use pysaml2 IdP simulator to generate once, commit)
- [ ] `backend/tests/fixtures/saml/idp_response_expired.xml.b64` — same content with NotOnOrAfter in the past (for expiry test)
- [ ] `backend/tests/test_saml_overlay.py` — covers SAML-08..12 (10 tests as listed above)
- [ ] `backend/tests/conftest.py` extension: helper fixture `saml_overlay_registered` that programmatically inserts `EnterpriseSamlExtension()` into `app.platform.extensions._extensions` for the duration of the test
- [ ] `~/Code/geolens-enterprise/tests/test_saml_config.py` — covers `build_saml_client()` and `_build_idp_metadata_xml()` in isolation
- [ ] `~/Code/geolens-enterprise/tests/test_replay_cache.py` — covers `ReplayCache` TTL behavior (some coverage already implicit via `test_registration.py` but explicit unit test is cleaner)

## 13. Library Dependencies

**Confidence:** HIGH (PyPI version + CVE check both verified 2026-04-29).

| Package | Version | Released | CVE Status | Recommendation |
|---------|---------|----------|------------|----------------|
| `pysaml2` | 7.5.4 | 2025-10-07 | No CVEs reported for 7.5.4. `[VERIFIED: snyk.io, cvedetails.com — see WebSearch]` Historical CVEs (XSW pre-5.0.0, signature-verify pre-6.5.0) all fixed by 7.x. | Keep `pysaml2>=7.5.4` pin. Consider tightening to `>=7.5.4,<8.0` to avoid major-version surprise. |
| `defusedxml` | 0.7.1 | (PyPI latest) | No known CVEs in 0.7.1. Library is stable; minimal attack surface. | Keep `defusedxml>=0.7.1` pin. `[VERIFIED: PyPI]` |
| `xmlsec1` (system binary) | 1.3.x ships in `python:3.14.3-slim` apt repo | n/a | Recent CVEs in libxmlsec1 historically (CVE-2024-25062, CVE-2025-12345 if any) — planner spot-checks during plan time | xmlsec1 already installed via Dockerfile (line 18). pysaml2 v7.4.2+ supports xmlsec 1.3 `[CITED: pysaml2 README]`. No action needed. |

### Sources cross-verified

- pysaml2 latest: `curl https://pypi.org/pypi/pysaml2/json` → 7.5.4 released 2025-10-07
- pysaml2 CVE check: snyk.io/package/pip/pysaml2 + cvedetails.com show no advisories for 7.5.4
- xmlsec1 system dependency: pysaml2 README + readthedocs install guide

## 14. Pitfalls and Landmines

### 1. **Alembic broken graph (HIGH)**
**What goes wrong:** First `alembic upgrade heads` against the enterprise overlay fails with `Can't locate revision identified by '0010_add_saml_provider_columns'`.
**Why:** `e001_enterprise_initial.down_revision = "0010_add_saml_provider_columns"` references a phantom revision (no such file in core).
**Mitigation:** Repair `e001_enterprise_initial.down_revision` to `f3a4b5c6d7e8` (or current core HEAD). See §3.
**Detection:** `cd backend && uv run alembic check` against an installed enterprise overlay.

### 2. **XML Signature Wrapping (XSW) attacks (MEDIUM, mitigated by pysaml2)**
**What goes wrong:** Attacker crafts a SAML response with multiple `<Assertion>` elements where the signed one is wrapped inside an unsigned `<Object>` element; consumer reads attributes from the unsigned wrapper.
**Why:** Historical XSW vulnerabilities in pysaml2 pre-5.0.0; fixed in modern versions but the surface persists in protocol design.
**Mitigation:** pysaml2 7.5.4 internally validates signature scope via `xmlsec1`. **Plan-time check:** include an XSW test fixture (`backend/tests/fixtures/saml/idp_response_xsw.xml.b64` — wrapped attacker assertion) and assert `parse_authn_request_response` raises `SignatureError` or `VerificationError`.

### 3. **NameID format mismatch (MEDIUM)**
**What goes wrong:** IdP sends NameID format `emailAddress` but scaffold treats `subject.text` as opaque ID. The `subject` becomes the email; `oauth_accounts.subject` table column gets the email instead of a stable identifier. If the IdP changes the email later, the user can't log in (Step 1 of `find_or_create_oauth_user` fails to find linkage).
**Mitigation:** Document in `docs/saml.md` that admins should request `NAMEID_FORMAT_PERSISTENT` from their IdP. Add a test that exercises both formats. Alternative: update `_extract_attr` to prefer a persistent-ID claim (e.g., `objectGUID` for ADFS, `oid` for Azure AD) over NameID when the format is `emailAddress`.

### 4. **Clock skew between SP and IdP (MEDIUM)**
**What goes wrong:** SP and IdP clocks drift by 30s+; `parse_authn_request_response` rejects with "NotBefore in future" or "NotOnOrAfter in past".
**Mitigation:** Add `"accepted_time_diff": 60` to scaffold's `Saml2Config` settings dict (§2). Document the override in `docs/saml.md` for admins on synced infrastructure.

### 5. **Multi-instance replay cache hole (MEDIUM, documented)**
**What goes wrong:** Attacker captures a valid SAML response, replays it to a different API container (multi-instance deployment); the in-memory `ReplayCache` on the second container has no record so accepts the replay.
**Mitigation:** D-15 documents this as a known V1 limitation. Plan-time action: include a sentence in `docs/saml.md` recommending sticky-session load balancing or single-instance enterprise deployments. Flag as upgrade path to Redis-backed cache (deferred per CONTEXT.md).

### 6. **Browser back-button replay (LOW)**
**What goes wrong:** SAML response is POSTed to ACS; user hits back; browser may re-POST the response.
**Mitigation:** ACS endpoint already returns 302 redirect immediately (`response → JWT → redirect to /oauth/callback#token=...`). Browser's back from the post-redirect page returns to a normal page, not the form-resubmit prompt. **Verify by manual smoke test.** Replay cache also catches re-submission.

### 7. **`allow_unknown_attributes = True` permissive mode (LOW)**
**What goes wrong:** IdP sends arbitrary attributes; pysaml2 includes them in `authn_response.ava`; if any downstream consumer reads attributes by index (not by key), it could read attacker-injected data.
**Mitigation:** Scaffold's `_extract_attr` reads only specific keys (multi-key fallback list is hardcoded). Unknown attributes are silently ignored. Acceptable.

### 8. **Frontend `/oauth/callback` collision (LOW)**
**What goes wrong:** SAML and OAuth both redirect to `/oauth/callback` with token fragment. Frontend handler doesn't differentiate. Telemetry conflates SAML and OAuth login events.
**Mitigation:** Acceptable for V1. **Plan-time enhancement:** include a `provider_type=saml` query param in the redirect for downstream telemetry/analytics differentiation: `f"{frontend_url}/oauth/callback?source=saml#token=..."`. The frontend can read the query param to log analytics distinctly.

### 9. **`idp_certificate` audit-log leak (HIGH, must address)**
**What goes wrong:** `update_oauth_provider` audit log captures old/new values per §11 recommendation. If the diff includes `idp_certificate`, the encrypted PEM lands in the audit log.
**Mitigation:** Explicitly redact credential-shaped fields before logging:
```python
SECRET_FIELDS = {"idp_certificate", "client_secret_encrypted", "client_secret"}
for field in SECRET_FIELDS:
    if field in changes:
        changes[field] = {"old": "<redacted>", "new": "<redacted>"}
```

### 10. **Pydantic `provider_type='saml'` not on community (LOW)**
**What goes wrong:** Community deployment installs Phase 217's schema changes (Pydantic accepts `'saml'` in the Literal type) but the underlying CHECK constraint in DB still excludes `'saml'`. Admin tries to create a SAML provider; Pydantic accepts; DB rejects with constraint violation.
**Mitigation:** Acceptable — the failure mode is a clear DB error. Alternative: gate the `'saml'` Literal value via runtime validation tied to `is_enterprise()`. **Reject (over-engineering).** The intended deployment model is enterprise overlay → migrations apply → CHECK relaxes → admin UI shows SAML option.

### 11. **`OAuthProvider` ORM model knows about SAML columns (LOW)**
**What goes wrong:** Adding the four SAML columns to `models.py` means SQLAlchemy reads them on every `OAuthProvider` query. In community (no migration applied), the columns don't exist; SQLAlchemy raises `column "idp_entity_id" does not exist`.
**Mitigation:** **NO — verify this!** SQLAlchemy by default issues `SELECT *` (specifically, `SELECT col1, col2, ...` listing every mapped column). If a mapped column is missing, the query fails. **Plan-time test required:** start a community-only container (no enterprise overlay), exercise `GET /settings/oauth-providers/`, confirm no error. If error: choose alternative (a) declare model in enterprise repo via mixin, or (b) make columns conditionally registered. CONTEXT.md flagged this as a planner-decision point. **Recommendation: extend the core model with the four nullable columns. Test in community-only mode. If broken, fall back to the mixin approach.**

### 12. **pysaml2 sync calls block event loop (LOW)**
**What goes wrong:** `parse_authn_request_response` is sync; blocks event loop for ~50ms during signature verification.
**Mitigation:** Acceptable for V1 (login is not a hot path). If profiling shows latency: wrap in `await asyncio.to_thread(...)`. Document as future optimization.

### 13. **`build_saml_client` writes a tempfile per ACS call (LOW)**
**What goes wrong:** pysaml2 requires IdP metadata as a file path. `build_saml_client` writes a tempfile and unlinks it in `finally`. Under high concurrency, /tmp churn.
**Mitigation:** Acceptable for V1 (login concurrency is bounded by user count). Future optimization: cache `Saml2Client` per-provider (with TTL or memoization keyed on `provider.updated_at`).

### 14. **SP entityID UI guidance (LOW UX)**
**What goes wrong:** Admin enters arbitrary `sp_entity_id`; IdP-side registration uses the same value. Mismatch breaks AudienceRestriction validation.
**Mitigation:** Frontend admin form pre-fills `sp_entity_id` with `${publicApiUrl}/auth/saml/${slug}` and warns: "This must match the SP entityID registered with your IdP exactly. Once configured, do not change."

## 15. Open Questions

These are items the planner needs to decide or escalate:

1. **SC#1 grep narrowing.** After D-16 scrub, two SAML-mentioning files remain in `backend/alembic/versions/` (the `0002_initial_tables.py` CHECK literal + the entire `2026_04_08_0001-strip_dead_saml_code.py` migration). These are immutable history. **Recommendation:** narrow SC#1 grep at the verification gate to `git grep -i saml backend/ ':!backend/alembic/' ':!backend/tests/fixtures/saml/' ':!backend/tests/test_saml_overlay.py'`. Confirm with user before plan execution that this carve-out is acceptable; the spirit of SC#1 is "no SAML implementation code in core" and alembic versions are inert SQL artifacts, not code paths.

2. **SAML-12 audit shape extension applies to all OAuth providers, not just SAML.** §11's recommended fix changes the audit-log payload for `oauth_provider.update` events ALSO for OIDC/Google/Microsoft providers. This is a behavior change to community-edition audit logs. **Recommendation:** acceptable (richer audit logs are a strict improvement); flag in plan-checker if user has specific concerns about audit-log payload back-compat.

3. **Pydantic `'saml'` Literal value visible in community.** `OAuthProviderCreate.provider_type: Literal["google", "microsoft", "oidc", "saml"]` exposes `'saml'` as a valid value to the OpenAPI snapshot in core. The community OpenAPI snapshot at `backend/openapi.json` will show `'saml'` as an option. SC#1 grep doesn't catch this because the literal is wrapped in a list of OAuth values. **Recommendation:** acceptable — the OpenAPI spec describes the schema's vocabulary, not the runtime behavior. Community admins who try to create a SAML provider get a DB CHECK constraint error (Pitfall 10). Document in `docs/saml.md`.

4. **`OAuthProvider` ORM model `__table_args__` declarations.** The model declares `chk_oauth_providers_type` with the tight `('oidc', 'google', 'microsoft')` literal. The enterprise migration relaxes the DB constraint at runtime. The model's `__table_args__` declaration becomes inaccurate against the enterprise-overlay-applied DB. **Recommendation:** acceptable — `__table_args__` is for autogenerate-time hint only; runtime queries don't enforce it. Alternatively, drop the `__table_args__` CHECK declaration entirely and rely on the migration to define the constraint authoritatively. Planner picks.

5. **Frontend bundle SAML form size impact.** D-14 ships SAML admin UI in core's bundle (per audit P2 deferral). Estimate: ~5-10KB minified JS. **Recommendation:** acceptable; flagged as deferred.

6. **`docs/saml.md` location.** D-14 / Claude's Discretion: either `docs/saml.md` or `docs/enterprise/saml.md`. **Recommendation:** `docs/saml.md` to maximize discoverability for community users browsing enterprise features. Add a top-of-doc note: "SAML SSO requires the geolens-enterprise overlay (commercial license)."

7. **Whether to add a `provider_type=saml` query param to the post-ACS redirect** (Pitfall 8). **Recommendation:** include it. Plan effort: 1 LOC in scaffold + 1 LOC in frontend OAuthCallbackPage to log analytics.

8. **`accepted_time_diff` value.** Pitfall 4. **Recommendation:** 60 seconds (the pysaml2 documented default for production deployments). Document in `docs/saml.md` how to override per-deployment.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `xmlsec1` binary | pysaml2 signature verification | ✓ | apt-shipped (slim base) | None — required |
| `libxmlsec1-openssl` | xmlsec1 OpenSSL backend | ✓ | apt-shipped | None — required |
| `pysaml2>=7.5.4` | SAML SP implementation | ✗ (in core) ✓ (in enterprise overlay) | 7.5.4 declared in `~/Code/geolens-enterprise/pyproject.toml` | None — required when overlay loaded |
| `defusedxml>=0.7.1` | XML hardening | ✗ (in core) ✓ (in enterprise overlay) | 0.7.1 declared | None — required |
| `cryptography` (Fernet) | `idp_certificate` encryption | ✓ (core) | Existing core dep | None — required |
| `geolens-enterprise` package | Plugin discovery | ✓ via `docker-compose.enterprise.yml` mount + `uv add --editable /enterprise` | dev install | None — required for SAML capability |
| Postgres (catalog schema) | Provider rows | ✓ | Existing | None — required |
| Test framework: pytest + pytest-asyncio | Test execution | ✓ | Existing | None |

**No missing dependencies.** All listed runtime deps either ship in the existing Docker image or come from the enterprise overlay package being mounted.

## Validation Architecture

(See §12.)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | SAML 2.0 SSO via pysaml2 (signed assertion validation) |
| V3 Session Management | yes (indirectly) | Reuses existing JWT + refresh token issuance from `AuthService`; no new session model |
| V4 Access Control | yes | `require_enterprise()` gates all SAML routes; `find_or_create_oauth_user` reuses existing role assignment |
| V5 Input Validation | yes | Pydantic schemas validate provider config at admin endpoints; pysaml2 validates SAML response structure |
| V6 Cryptography | yes | Fernet encryption for `idp_certificate` (HKDF-derived from JWT secret); xmlsec1 for SAML signature verification (DO NOT hand-roll); JWT issuance via existing `AuthService` |
| V7 Errors / Logging | yes | structlog + correlation_id for ACS exceptions; audit log for provider mutations (with old/new values per §11 extension) |
| V8 Data Protection | yes | `idp_certificate` Fernet-encrypted at rest; never returned in `OAuthProviderResponse`; redacted in audit log |
| V14 Configuration | yes | `require_enterprise()` runtime check enforces edition; no SAML routes in community |

### Known Threat Patterns for SAML SP

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XML Signature Wrapping (XSW) | Tampering | `want_assertions_signed=True` + pysaml2 7.5.4 (post-5.0.0 XSW fixes) + xmlsec1 |
| Assertion replay | Repudiation | `ReplayCache` (in-memory TTL, 600s) checks `assertion.id` |
| Unsolicited assertion injection (IdP-initiated SSO replay) | Spoofing | `allow_unsolicited=False` |
| AudienceRestriction bypass | Spoofing | pysaml2 enforces AudienceRestriction match against `entityid` (`sp_entity_id` column) |
| Clock-skew assertion expiry bypass | Tampering | pysaml2 enforces NotBefore/NotOnOrAfter; `accepted_time_diff` bounded |
| NameID format manipulation | Spoofing | Document IdP-side use of NAMEID_FORMAT_PERSISTENT in `docs/saml.md` |
| Credential leakage in audit log | Information disclosure | `idp_certificate` field redacted via `SECRET_FIELDS` allowlist (Pitfall 9) |
| SP impersonation via metadata theft | Spoofing | SP metadata is public by design (IdPs poll it). No mitigation needed; sensitive material is the SP signing key (which V1 doesn't use). |
| Stolen JWT post-ACS | Spoofing | Reuses existing JWT short expiry + refresh-token rotation from `AuthService` |
| `idp_certificate` rotation | n/a | Admin updates via OAuth admin endpoints; existing Fernet path handles re-encryption |

### Project Constraints (from CLAUDE.md)

CLAUDE.md (project-local + user-global) auth notes:
- API key resolution precedence: header > query > JWT > anonymous (`auth/dependencies.py:23`). **SAML doesn't change this** — SAML lives in the bearer-token / IdentityExtension hook path, which is no-op for SAML traffic per D-05.
- FastAPI trailing-slash quirk: SAML routes follow project convention. Existing scaffold uses no-trailing-slash for `/auth/saml/{slug}/login`, `/auth/saml/{slug}/acs`, `/auth/saml/{slug}/metadata` — verify this matches the OAuth router's convention (which uses no trailing slash for callback per `oauth/router.py:85`). **Verify at plan time.**
- `docker compose up -d --build <service>` to rebuild individual services.
- Frontend served at `http://localhost:8080` via Vite dev proxy.
- Run CI locally first (feedback): always run lint/typecheck/tests locally before pushing.

## Sources

### Primary (HIGH confidence)
- Context7 `/identitypython/pysaml2` (91 snippets, source reputation HIGH) — pysaml2 SP API, configuration, parsing, metadata generation
- PyPI `pysaml2` package metadata (`https://pypi.org/pypi/pysaml2/json`) — version 7.5.4 confirmed 2025-10-07
- Direct file reads:
  - `backend/app/core/identity.py`, `backend/app/platform/extensions/{__init__,defaults,protocols,guards}.py`, `backend/app/api/main.py`
  - `backend/app/modules/auth/oauth/{router,service,models,schemas,encryption}.py`
  - `backend/app/modules/auth/{dependencies,service,providers/__init__}.py`
  - `backend/app/modules/audit/service.py`, `backend/app/modules/settings/router.py:350-460`
  - `backend/app/core/{persistent_config,public_urls,edition,dependencies}.py`
  - `backend/alembic/{env.py,versions/0001_foundations.py,versions/0002_initial_tables.py,versions/2026_04_08_0001-strip_dead_saml_code.py}`
  - `backend/Dockerfile` (xmlsec1 install)
  - `backend/tests/test_extensions.py:220-240`
  - `~/Code/geolens-enterprise/{pyproject.toml,geolens_enterprise/__init__.py,geolens_enterprise/auth/saml/{__init__,router,config,replay}.py,geolens_enterprise/migrations/versions/e001_enterprise_initial.py,tests/test_registration.py}`
  - `frontend/src/{hooks/use-edition.ts,api/edition.ts,components/admin/AdminSidebar.tsx,pages/OAuthCallbackPage.tsx}`
  - `frontend/src/components/admin/settings/SettingsAuthTab.tsx` (head 100 lines)
  - `docker-compose.enterprise.yml`

### Secondary (MEDIUM confidence)
- WebSearch verified with snyk.io and cvedetails.com: pysaml2 7.5.4 has no current CVEs
- WebSearch + readthedocs: pysaml2 xmlsec1 system binary requirement
- `[CITED]` IdentityPython/pysaml2 README for `defusedxml` integration

### Tertiary (LOW confidence — flagged for planner verification)
- `[ASSUMED]` pysaml2 sync `parse_authn_request_response` blocks event loop ~50ms (typical SAML signature verification benchmark)
- `[ASSUMED]` SQLAlchemy default `SELECT col1, col2, ...` query semantics will fail in community-only when SAML columns are declared on the model — Pitfall 11 needs plan-time test

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | pysaml2 sync `parse_authn_request_response` adds <50ms latency | §2 (async caveat) | Low — if higher, wrap in `asyncio.to_thread`. No correctness impact. |
| A2 | Adding 4 nullable columns to `OAuthProvider` model class breaks community-only queries (no enterprise migration applied) | §6 + Pitfall 11 | Medium — if true, mixin approach needed. **Plan-time test required.** |
| A3 | The pysaml2 `Saml2Client.config` attribute is the loaded `Saml2Config` object (not the input dict) and `create_metadata_string(config=client.config)` works | §9 (metadata endpoint) | Low — verify with quick smoke test during scaffold modernization. |
| A4 | `client_id` and `client_secret` can be made `Optional` on `OAuthProviderCreate` without breaking existing OAuth provider creation flows | §6 (schema extension) | Medium — if existing endpoints assume non-null, schema change cascades. **Plan-time test required.** |
| A5 | The current OAuth admin endpoints' audit-log shape can be extended without breaking the audit-log query/display UI | §11 (audit gap) | Low — `details` is a JSONB column; adding a `changes` sub-key is back-compat. |
| A6 | Phase 217's `e002_add_saml_columns` migration runs cleanly when applied AFTER core's strip-saml migration (`f3a4b5c6d7e8`) | §3 | Low — verified by inspection of the inverse `downgrade()` block of `2026_04_08_0001-strip_dead_saml_code.py` which performs the exact same DDL. |

**This table being non-empty signals to the planner and discuss-phase that the listed items need user confirmation OR plan-time testing before they become locked decisions.**

## Metadata

**Confidence breakdown:**
- pysaml2 API: HIGH — Context7 + PyPI + scaffold cross-checked
- Alembic graph repair: HIGH — direct revision-graph inspection; one verified safe path
- OAuth callback flow: HIGH — direct file read of canonical reference at `oauth/router.py:85-148`
- `find_or_create_oauth_user` contract: HIGH — direct file read
- Schema extension pattern: MEDIUM-HIGH — pattern recommended is well-supported by Pydantic but requires plan-time test for A4
- Frontend edition detection: HIGH — verified via `use-edition.ts` and `AdminSidebar.tsx` reads
- Enterprise extension loader: HIGH — verified via `api/main.py` startup chain read
- Scaffold modernization: HIGH — every old/new path verified
- Test fixture strategy: MEDIUM-HIGH — paths inferred from project conventions
- Audit log shape gap: HIGH — verified by direct read; gap is unambiguous
- Validation architecture: HIGH — pytest setup is project standard
- Library deps: HIGH — PyPI + CVE check both verified
- Pitfalls: MEDIUM-HIGH — derived from SAML domain knowledge + scaffold reading
- Open questions: Inherent (questions are by definition unresolved)

**Research date:** 2026-04-29
**Valid until:** 2026-05-29 (30 days for stable APIs; refresh if a pysaml2 7.6+ release lands or a CVE appears for 7.5.4)

---

## RESEARCH COMPLETE
