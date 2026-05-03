---
phase: 234-governance-contract-verification
status: passed
verified: true
score: 5/5
verified_at: 2026-05-03T18:00:00Z
requirements:
  SHARE-01: passed
  SHARE-02: passed
  SHARE-03: passed
---

# Phase 234 Verification

## Summary

Phase 234 is verified as passed. The advanced-sharing Branch A contract is now enforced and documented consistently across schema validators, service guards, builder UI affordances, API descriptions/docstrings, GTM docs, and the generated OpenAPI snapshot.

## Requirement Verification

### SHARE-01: passed

Community rejects advanced sharing controls consistently:

- `EmbedTokenCreate` rejects `expires_in_days != 30` and non-empty `allowed_origins` in Community.
- `EmbedTokenUpdate` rejects non-empty `allowed_origins` in Community.
- `ShareTokenRequest` rejects non-null `expires_at` in Community.
- Embed-token service and map-share service guards reject advanced controls before DB mutation so callers cannot bypass schema construction.
- Builder sharing controls hide expiration and domain-restriction inputs outside Enterprise, and Community token creation/regeneration omits `allowedOrigins`.

Enterprise behavior is preserved by the same tests under the `enterprise_edition` fixture and route-level DB-backed coverage.

### SHARE-02: passed

Product-contract copy now matches the enforced implementation:

- GTM docs classify basic share/embed behavior as Community and advanced expiring/domain-restricted sharing as paid Enterprise/Team behavior.
- API schema descriptions distinguish default Community embed lifetimes, Enterprise-only custom embed lifetimes, Enterprise-only domain restrictions, Community non-expiring share links, and Enterprise-only expiring share links.
- Route docstrings describe owner/admin behavior and enforced advanced-control requirements without stale shorthand.
- Builder Community failure copy is operational and no longer implies domain restrictions may be applied in Community-only paths.
- `backend/openapi.json` was regenerated from the final FastAPI app and `make openapi-check` passed.

### SHARE-03: passed

Basic Community sharing remains intact:

- Default embed-token creation remains accepted.
- Basic share-link creation with no expiration remains accepted.
- Embed-token update/revoke and share-token revoke flows remain covered by focused DB-backed endpoint tests.
- Builder Community tests confirm basic share-link controls remain visible and basic embed-token generation sends a Community-safe payload.

## Commands Run

- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_advanced_sharing_schema.py tests/test_embed_tokens.py::TestCreateEmbedToken tests/test_embed_tokens.py::TestCreateEmbedTokenWithOrigins tests/test_embed_tokens.py::TestUpdateEmbedToken tests/test_embed_tokens.py::TestRevokeEmbedToken tests/test_maps.py::TestShareToken tests/test_maps.py::TestUpdateShareToken -q` -> 37 passed, 16 warnings
- `cd backend && uv run ruff check app/modules/embed_tokens app/modules/catalog/maps tests/test_advanced_sharing_schema.py tests/test_embed_tokens.py tests/test_maps.py` -> passed
- `cd frontend && npm run test -- src/components/builder/__tests__/SharePanel.test.tsx src/components/builder/hooks/__tests__/use-embed-tokens.test.ts` -> 2 files passed, 9 tests passed
- `cd frontend && npm run lint` -> passed with 5 pre-existing warnings outside this phase's changed files
- `make openapi-check` -> passed
- `bash -lc '! rg -n "\(enterprise only\)|domain restriction may not be applied|ungated|without enforcement" backend/app/modules/embed_tokens backend/app/modules/catalog/maps frontend/src/i18n/locales/en/builder.json docs-internal/GTM'` -> passed

## Negative Control

The Community custom embed lifetime schema guard was temporarily weakened by removing the `expires_in_days != 30` condition from `EmbedTokenCreate.validate_enterprise_controls`.

Command:

- `cd backend && POSTGRES_PORT=65432 uv run pytest tests/test_advanced_sharing_schema.py::test_community_rejects_custom_embed_lifetime -q`

Result:

- The test failed as expected with `Failed: DID NOT RAISE <class 'pydantic_core._pydantic_core.ValidationError'>`.
- The mutation was reverted immediately.
- The same focused test then passed with the restored guard.

## OpenAPI Review

`make openapi` regenerated `backend/openapi.json`. The accepted OpenAPI diff is limited to advanced-sharing descriptions and route text for:

- `EmbedTokenCreate.allowed_origins`
- `EmbedTokenCreate.expires_in_days`
- `EmbedTokenUpdate.allowed_origins`
- `ShareTokenRequest.expires_at`
- embed-token create/update route descriptions
- share-token create/update route descriptions

During review, unrelated `StacImportRequest.visibility` enum drift appeared because the source type had become `str`. The source enum was restored in `backend/app/modules/catalog/sources/stac_router.py` before accepting the snapshot; `make openapi-check` then passed.

## Environment Notes

- DB-backed tests were run against the Docker database on `POSTGRES_PORT=5434`.
- The default local Postgres service on port 5432 was not suitable for the focused DB-backed checks in this environment.
- DB-light schema and negative-control checks used `POSTGRES_PORT=65432` where appropriate so the session fixture did not depend on a reachable database.

## Gaps

None.

## Human Verification

None required for Phase 234 goal achievement.

## Residual Risks

- This was a focused governance-contract verification pass, not a full backend or frontend suite run.
- Existing Pydantic deprecation warnings remain in schema tests.
- Existing frontend lint warnings remain outside the modified sharing files.
