---
phase: 209-saml-sso
plan: 01
subsystem: auth
tags: [saml, pysaml2, sso, enterprise, xmlsec1, defusedxml]

requires:
  - phase: 116-120
    provides: OAuth provider model, encryption helpers, enterprise gating pattern
provides:
  - SAML provider CRUD via existing OAuthProvider model with provider_type="saml"
  - SAML metadata XML parsing (entity_id, sso_url, certificate extraction)
  - SP-initiated SSO login endpoint (GET /auth/saml/{slug}/login)
  - ACS endpoint with assertion validation and user provisioning (POST /auth/saml/{slug}/acs)
  - Assertion replay cache with TTL-based eviction
  - Dynamic pysaml2 config builder from database provider
affects: [209-02-frontend-saml-ui]

tech-stack:
  added: [pysaml2>=7.5.4, xmlsec1, libxmlsec1-openssl]
  patterns: [dynamic-saml-client-from-db, metadata-xml-parse-on-save, enterprise-gated-auth-router]

key-files:
  created:
    - backend/app/auth/saml/__init__.py
    - backend/app/auth/saml/config.py
    - backend/app/auth/saml/metadata.py
    - backend/app/auth/saml/replay.py
    - backend/app/auth/saml/router.py
    - backend/alembic/versions/0010_add_saml_provider_columns.py
    - backend/tests/test_saml.py
  modified:
    - backend/app/auth/oauth/models.py
    - backend/app/auth/oauth/schemas.py
    - backend/app/auth/oauth/service.py
    - backend/app/main.py
    - backend/Dockerfile
    - backend/pyproject.toml
    - backend/uv.lock

key-decisions:
  - "pysaml2 7.5.4 used per STATE.md roadmap decision (python3-saml lacks Python 3.13 support)"
  - "SAML columns added as nullable to existing oauth_providers table (no new tables)"
  - "metadata_xml parsed on create/update to populate extracted IdP fields (entity_id, sso_url, certificate)"
  - "IdP certificate stored encrypted via existing Fernet encryption for consistency"
  - "In-memory TTL replay cache (sufficient for single-instance; Redis upgrade path available)"

patterns-established:
  - "Dynamic pysaml2 config: build Saml2Client from DB provider per-request, temp file for metadata"
  - "Enterprise gating on router level: Depends(require_enterprise) as router dependency"
  - "SAML attribute extraction: fallback chain across common claim names"

requirements-completed: [SAML-01, SAML-02, SAML-03, SAML-04]

duration: 5min
completed: 2026-03-26
---

# Phase 209 Plan 01: SAML SSO Backend Summary

**pysaml2-based SAML SSO backend with SP-initiated login, ACS assertion validation, replay protection, and enterprise gating via extended OAuthProvider model**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-26T23:36:41Z
- **Completed:** 2026-03-26T23:41:16Z
- **Tasks:** 3
- **Files modified:** 14

## Accomplishments
- SAML provider CRUD works via existing /settings/oauth-providers/ API with provider_type="saml" and metadata_xml field
- Metadata XML parsing extracts entity_id, sso_url, and certificate with validation for malformed/missing fields
- SAML login endpoint builds AuthnRequest and redirects to IdP SSO URL
- ACS endpoint validates assertions (signature, expiry, audience) and provisions users via find_or_create_oauth_user
- Replay cache prevents assertion reuse with configurable TTL
- All SAML endpoints return 404 in community edition (enterprise gating)
- 12 unit tests passing covering metadata parsing, replay cache, and schema validation

## Task Commits

Each task was committed atomically:

1. **Task 1: Database migration, model/schema extensions, and SAML module** - `097d0f9f` (feat)
2. **Task 2: SAML router with login, ACS, enterprise gating** - `e03fc324` (feat)
3. **Task 3: SAML backend tests** - `c03d7c0b` (test)

## Files Created/Modified
- `backend/alembic/versions/0010_add_saml_provider_columns.py` - Migration adding idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id
- `backend/app/auth/saml/__init__.py` - Package init
- `backend/app/auth/saml/config.py` - Dynamic pysaml2 Saml2Client builder from DB provider
- `backend/app/auth/saml/metadata.py` - IdP metadata XML parser using defusedxml
- `backend/app/auth/saml/replay.py` - TTL-based assertion replay cache
- `backend/app/auth/saml/router.py` - SAML login and ACS endpoints with enterprise gating
- `backend/app/auth/oauth/models.py` - Added 4 nullable SAML columns to OAuthProvider
- `backend/app/auth/oauth/schemas.py` - Added "saml" to provider_type literals, metadata_xml field, SAML response fields
- `backend/app/auth/oauth/service.py` - SAML metadata parsing on create/update
- `backend/app/main.py` - Registered saml_router
- `backend/Dockerfile` - Added xmlsec1 libxmlsec1-openssl
- `backend/pyproject.toml` - Added pysaml2>=7.5.4
- `backend/tests/test_saml.py` - 12 unit tests for metadata, replay, schemas

## Decisions Made
- pysaml2 7.5.4 selected per STATE.md roadmap decision (python3-saml abandoned, no Python 3.13 support)
- SAML columns added as nullable to existing oauth_providers table rather than creating a separate table
- metadata_xml is parsed on save and extracted fields stored; raw XML is not persisted
- IdP certificate encrypted via existing Fernet helpers for consistency with client_secret pattern
- In-memory replay cache with TTL (single-instance sufficient; Redis upgrade path exists)
- client_id/client_secret made optional in OAuthProviderCreate (defaulting to "saml-not-applicable" placeholders for DB constraints)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all data paths are fully wired.

## Next Phase Readiness
- SAML backend is complete and ready for frontend plan (209-02) to add admin UI and login page integration
- OAuthProviderPublic already returns provider_type which frontend can use to render SAML-specific login buttons

## Self-Check: PASSED

All 7 created files verified present. All 3 task commits verified in git log.

---
*Phase: 209-saml-sso*
*Completed: 2026-03-26*
