# Phase 217: auth-saml-enterprise - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 217-auth-saml-enterprise
**Areas discussed:** Provider model architecture, Identity wire-in pattern, Existing scaffold disposition, UI shape + hardening + SC#1

---

## Provider model architecture

### Q1 — Where should SAML provider config live in the database?

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse OAuthProvider (re-add 4 SAML columns) | Enterprise migration re-adds idp_entity_id/idp_sso_url/idp_certificate/sp_entity_id; reuses provider list endpoints, group_claim/group_role_mapping, default_role, oauth_accounts, find_or_create_oauth_user(). Cons: enterprise migration mutates a core-owned table. | ✓ |
| Separate SamlProvider model in enterprise schema | New table catalog.saml_providers defined entirely in geolens-enterprise/migrations/. Pros: clean tier boundary. Cons: duplicates provider CRUD/admin UI, separate find_or_create_saml_user() needed. | |
| Hybrid: reuse OAuthProvider, SAML-specific columns in new enterprise table | catalog.saml_provider_details joined 1:1. Pros: no core-column drift. Cons: 1:1 join adds query complexity. | |

**User's choice:** Reuse OAuthProvider (recommended). Drives schema additions into the enterprise migration; preserves the existing JIT pathway.

### Q2 — How should the enterprise migration restore SAML schema additions?

| Option | Description | Selected |
|--------|-------------|----------|
| New enterprise migration on the 'enterprise' branch | e002_add_saml_columns; down_revision='e001_enterprise_initial'; re-adds 4 nullable SAML columns + re-relaxes chk_oauth_providers_type. | ✓ |
| Single enterprise migration that also touches users.auth_provider CHECK | Same as above PLUS re-relaxes chk_users_auth_provider to include 'saml'. | |
| Two enterprise migrations (columns first, CHECK second) | Split for diff readability; more complex revision graph. | |

**User's choice:** New enterprise migration on the 'enterprise' branch (recommended). Single logical change in one migration; users.auth_provider CHECK stays tight because SAML users get auth_provider='oauth'.

### Q3 — How should the IdP signing certificate and SP private key be stored?

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse encrypt_secret/decrypt_secret from auth/oauth/encryption.py | Fernet-encrypted PEM in idp_certificate column; mirrors OAuth client_secret_encrypted. | ✓ |
| Filesystem keystore (mount path via env var) | SP private key + IdP cert at configured filesystem path; only path stored in DB. | |
| DB-stored, no SP signing key for now (assertions-signed only) | Skip SP-side signing entirely; only store IdP idp_certificate. | |

**User's choice:** Reuse encrypt_secret/decrypt_secret. Existing pattern; SP signing deferred per hardening discussion.

### Q4 — How should SAML providers be discriminated in oauth_accounts and find_or_create_oauth_user()?

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse oauth_accounts unchanged; SAML 'subject' = NameID from assertion | OAuthAccount.subject stores SAML NameID; UniqueConstraint(provider_id, subject) prevents duplicates; auth_provider='oauth'. | ✓ |
| Reuse oauth_accounts; add nullable saml_session_index column | Forward-looking for SLO. Phase 217 doesn't implement SLO. | |
| New saml_accounts table parallel to oauth_accounts | Cleaner separation but fights ROADMAP SC#3 (binds JIT to find_or_create_oauth_user). | |

**User's choice:** Reuse oauth_accounts unchanged. SAML NameID = OAuthAccount.subject; users.auth_provider stays 'oauth'.

---

## Identity wire-in pattern

### Q5 — Where in the request lifecycle should SAML translate to a GeoLens identity?

| Option | Description | Selected |
|--------|-------------|----------|
| JWT-after-ACS (existing scaffold pattern, no IdentityExtension use) | ACS validates assertion → JIT-provisions → issues core JWT (access + refresh) → redirects to /oauth/callback#token=... | ✓ |
| IdentityExtension.resolve_identity_from_token() per-request (Phase 214 design) | ACS stores opaque session token; per-request decode via IdentityExtension. Adds session-store dependency. | |
| Hybrid: ACS issues JWT AND IdentityExtension is implemented but returns None | Forward-compatible without complexity now. (Effectively combined with the dual-registration choice in Q6.) | |

**User's choice:** JWT-after-ACS. Mirrors existing OAuth callback pattern; no per-request SAML decode cost; no session-store dep.

### Q6 — How does Phase 217 satisfy SAML-09 if SAML doesn't actually call IdentityExtension at request time?

| Option | Description | Selected |
|--------|-------------|----------|
| Register router via _routers + register a no-op IdentityExtension | Dual-seam registration: registry['identity'] = no-op + registry['_routers'].append(saml_router). Demonstrates Phase 214's seam exists for SAML. | ✓ |
| Register router via _routers only; do NOT register IdentityExtension | Lighter; no dead Protocol implementation. Weaker SAML-09 trace. | |
| Register IdentityExtension AND have it own JWT issuance | Forces hot path through Phase 214 seam. Duplicates JWT vs SAML-token state; rejected. | |

**User's choice:** Register router + no-op IdentityExtension (recommended). Same instance dual-registered under registry['auth'] and registry['identity']; saml_router appended to registry['_routers'].

### Q7 — How should the SAML ACS endpoint reuse the existing OAuth/JWT issuance path?

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror oauth/router.py callback shape verbatim | Validate assertion → userinfo dict → find_or_create_oauth_user() → AuthService JWT → /oauth/callback#token=...&refresh_token=...&expires_in=... | ✓ |
| Dedicated SAML callback frontend route | Redirect to /saml/callback#... — accurate UX, requires net-new frontend route. | |
| Issue cookie-based session instead of #fragment tokens | XSS posture upgrade but diverges from OAuth flow; out of Phase 217 scope. | |

**User's choice:** Mirror oauth/router.py callback verbatim. Frontend's existing OAuth callback handler picks up tokens; no SAML-specific frontend route.

### Q8 — How should the SP metadata XML endpoint be exposed?

| Option | Description | Selected |
|--------|-------------|----------|
| GET /auth/saml/{slug}/metadata returning application/samlmetadata+xml | Per-provider; mirrors /login + /acs URL pattern; gated by require_enterprise(). | ✓ |
| Single global GET /auth/saml/metadata | One SP metadata for the whole deployment. Doesn't model per-provider sp_entity_id. | |
| Admin-only download endpoint (no public XML route) | Friction; some IdPs prefer to fetch metadata URL on schedule. | |

**User's choice:** Per-provider /auth/saml/{slug}/metadata returning application/samlmetadata+xml.

---

## Existing scaffold disposition

### Q9 — What should we do with the existing geolens-enterprise/auth/saml/ scaffold?

| Option | Description | Selected |
|--------|-------------|----------|
| Salvage — modernize imports + rebase on current core APIs | Keep router/config/replay; rewrite imports to v13.0 paths; add metadata endpoint + IdentityExtension no-op. | ✓ |
| Rewrite — fresh implementation following Phase 217 design | Throws away working pysaml2 config and replay cache. | |
| Hybrid: salvage replay.py + extension shape, rewrite router.py and config.py | Use pysaml2's create_metadata_string() instead of f-string XML. | |

**User's choice:** Salvage. Saves work; existing scaffold's SAML XML wiring (build_idp_metadata_xml, pysaml2 client config, ReplayCache) is sound.

### Q10 — IdP metadata XML generation: f-string vs pysaml2 builders vs upload?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep f-string IdP metadata generation | _build_idp_metadata_xml() is small/direct; defusedxml dep already declared; certificate is Fernet-decrypted. | ✓ |
| Switch to pysaml2's mdstore / mdex builders | More structured; less ergonomic; covers edge cases not needed for Phase 217. | |
| Skip IdP metadata generation — require admin to upload IdP metadata XML | Large schema change; conflicts with column-based provider model chosen in Q1. | |

**User's choice:** Keep f-string. Less abstraction, fewer pysaml2 surprises; covers Phase 217 scope.

### Q11 — How aggressively should attribute extraction handle Microsoft/Okta/ADFS variations?

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded multi-key fallback list per attribute | Existing _extract_attr() walks email/name/ADFS-URN claim names; covers 95%+ of IdPs without admin config. | ✓ |
| Configurable per-provider attribute map (new columns) | saml_attr_map JSONB column. YAGNI for Phase 217. | |
| Hardcoded list + provider.group_claim override for non-email/name attributes | Best-of-both. | |

**User's choice:** Hardcoded multi-key fallback list. Extend with 1–2 ADFS-specific URN claim names; group_claim already handles role-mapping variance.

### Q12 — EnterpriseSamlExtension class shape — single class or split?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep get_auth_methods() AND add IdentityExtension no-op (single class) | Same instance dual-registered under registry['auth'] AND registry['identity']. Two Protocols, one class. | ✓ |
| Split into two classes: SamlAuthExtension and SamlIdentityExtension | Cleaner SRP but two classes for the no-op case. | |
| Drop IdentityExtension registration; only register get_auth_methods() + router | Weakens SAML-09 trace; loses architectural breadcrumb. | |

**User's choice:** Single class, dual Protocol implementation, dual registration.

---

## UI shape + hardening + SC#1

### Q13 — Where does the admin SAML configuration live in the frontend?

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone /admin/saml route, edition-gated by backend | New route in core frontend; sidebar nav conditionally rendered; backend 404 in community. | ✓ |
| Extend existing /admin/auth-providers page with SAML provider type | OAuth admin page gets SAML tab/dropdown. Code reuse but SC#2's "tab" interpreted loosely. | |
| Standalone tab inside /admin/auth-providers page (sub-tab) | Two horizontal tabs: 'OAuth/OIDC' and 'SAML'. | |

**User's choice:** Standalone /admin/saml route, edition-gated by backend.

### Q14 — Where does the SAML admin frontend code physically live — core or enterprise?

| Option | Description | Selected |
|--------|-------------|----------|
| Core repo, edition-detection guards visibility | Single frontend bundle; sidebar nav and route check edition; backend 404 enforces server-side. | ✓ |
| Enterprise repo with frontend-bundle injection | Stronger SC#1 spirit but forces frontend split (P2 audit deferral). Significant scope expansion. | |
| Server-rendered admin SAML UI (no React route) | Backend serves HTML at /auth/saml/admin. Awful UX disparity with OAuth React admin. | |

**User's choice:** Core repo, edition-detection guards visibility. Frontend bundle split is P2 deferral; SC#1 covers backend git grep, not frontend.

### Q15 — Hardening defaults out-of-box?

| Option | Description | Selected |
|--------|-------------|----------|
| want_assertions_signed=True; authn_requests_signed=False; in-memory replay cache | Existing scaffold defaults. Multi-instance has a hole; flag in docs as upgrade path. | ✓ |
| Same defaults + Redis-backed replay cache | Multi-instance correct; requires Redis as hard dep. | |
| Strict: signed assertions + signed AuthnRequests (SP keypair) + Redis replay | Full enterprise-grade; SP keypair UX is non-trivial; YAGNI for V1. | |

**User's choice:** Existing scaffold defaults — assertions signed, AuthnRequests not signed, in-memory replay. Multi-instance limitation flagged in docs.

### Q16 — SC#1 SAML mentions in core docstrings — scrub or carve-out?

| Option | Description | Selected |
|--------|-------------|----------|
| Scrub all 3 docstring mentions (replace 'SAML' with 'enterprise auth overlay') | Tightest interpretation; SC#1 grep returns zero hits. Loses helpful breadcrumb. | ✓ |
| Add a SC#1 carve-out for docstring mentions; leave them as-is | Update SC#1 to 'zero IMPLEMENTATION matches'. Loosens spec. | |
| Replace 'SAML' with 'sample IdP backend' (deliberate misspelling) | Cleverness over clarity; rejected. | |

**User's choice:** Scrub all 3 docstring mentions. core/identity.py:15-17, platform/extensions/defaults.py:36, tests/test_extensions.py:230.

### Q17 — Audit P0 (group_claim/group_role_mapping in Community) in scope for Phase 217?

| Option | Description | Selected |
|--------|-------------|----------|
| Out of scope for Phase 217 — document and defer to Phase 218 audit close | Phase 217 ships SAML using existing group_claim/group_role_mapping fields as-is. Phase 218 owns the audit close. | ✓ |
| Bundle into Phase 217 (gate group_claim/group_role_mapping behind require_enterprise()) | Closes audit P0 alongside SAML. Scope creep; regression risk; breaking change for Community OAuth. | |
| Compromise: hide group_claim/group_role_mapping fields in Community OAuth admin UI only | Frontend hide; backend boundary still leaks; cosmetic-only. | |

**User's choice:** Out of scope for Phase 217 — defer to Phase 218.

---

## Claude's Discretion

- Migration revision IDs (planner picks alembic-style hash or `e002_` prefix matching `e001_enterprise_initial.py`).
- Commit decomposition (likely 4–5 atomic commits — planner may collapse/split based on diff cleanliness).
- Mock IdP test strategy (hardcoded SAML response XML fixtures vs pysaml2 IdP simulator vs Docker SimpleSAMLphp).
- Default value for sp_entity_id form field in the admin UI (suggested pre-fill: `{public_api_url}/auth/saml/{slug}`).
- Whether EnterpriseSamlExtension is split into separate Auth + Identity classes (D-13 says single; planner may split if testing benefits).
- Where docs/saml.md user-facing docs live (`docs/saml.md` vs `docs/enterprise/saml.md`).
- Audit-log shape extension if existing OAuth admin endpoints don't naturally capture old/new values for SAML field mutations.
- Whether to ship docs/runbooks/saml-troubleshooting.md.

## Deferred Ideas

- SP-side AuthnRequest signing + SP keypair management (V2 hardening).
- Single LogOut (SLO) — IdP-initiated and SP-initiated.
- Redis-backed replay cache (multi-instance correctness).
- Per-provider attribute-map JSONB column for IdPs with arbitrary attribute namespacing.
- Frontend bundle split for enterprise components (P2 audit deferral).
- **Audit P0: gate OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()`** — explicitly deferred to Phase 218.
- Cookie-based session swap (broader auth refactor).
- IdP-initiated SSO support (`allow_unsolicited=True`).
- SCIM provisioning (separate phase, separate Protocol design).
- Multi-tenant identity scoping (`IdentityProtocol.tenant_id`) — backlog 999.6.
- `docs/runbooks/saml-troubleshooting.md`.
