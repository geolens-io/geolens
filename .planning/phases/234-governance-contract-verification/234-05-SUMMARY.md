---
phase: 234-governance-contract-verification
plan: 05
status: complete
subsystem: docs
tags:
  - sharing
  - openapi
  - governance
requires:
  - 234-02-embed-token-service-contract
  - 234-03-share-token-service-contract
  - 234-04-builder-sharing-ui-contract
provides:
  - Contract-aligned advanced sharing copy across API, UI, and GTM docs
  - Regenerated OpenAPI snapshot for final advanced sharing descriptions
  - Goal-backward phase verification with negative-control evidence
affects:
  - 235-post-impl-audit-v13.5
tech-stack:
  added: []
  patterns:
    - OpenAPI refresh reviewed for scoped contract-description drift
key-files:
  created:
    - .planning/phases/234-governance-contract-verification/234-VERIFICATION.md
    - docs-internal/GTM/free-vs-enterprise.md
  modified:
    - backend/app/modules/embed_tokens/schemas.py
    - backend/app/modules/embed_tokens/router.py
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/catalog/sources/stac_router.py
    - backend/openapi.json
    - frontend/src/i18n/locales/en/builder.json
requirements-completed:
  - SHARE-02
duration: 36 min
completed: 2026-05-03
---

# Phase 234 Plan 05: Copy, OpenAPI, and Verification Summary

**Advanced-sharing product contract copy, OpenAPI snapshot, and phase verification aligned to the enforced Community/Enterprise gates**

## Performance

- **Duration:** 36 min
- **Started:** 2026-05-03T17:45:00Z
- **Completed:** 2026-05-03T18:21:00Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Aligned API field descriptions, route docstrings, builder copy, and GTM docs with the implemented advanced-sharing gates.
- Regenerated `backend/openapi.json` and reviewed the diff so the snapshot only carries advanced-sharing contract text.
- Wrote the phase verification artifact mapping SHARE-01, SHARE-02, and SHARE-03 to command evidence and residual risks.
- Ran a negative control by temporarily removing the Community custom embed lifetime schema guard and confirming the focused test failed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Align API, UI, and GTM copy** - `8ae7c341` (`docs`)
2. **Task 2: Regenerate advanced sharing OpenAPI snapshot** - `3d492d26` (`docs`)

Plan metadata and verification artifact are captured in the phase artifact commit after this summary.

## Files Created/Modified

- `backend/app/modules/embed_tokens/schemas.py` - Describes default Community lifetime, Enterprise-only custom lifetime, and Enterprise-only origin restrictions.
- `backend/app/modules/embed_tokens/router.py` - Describes enforced custom-lifetime and domain-restriction requirements in route docstrings.
- `backend/app/modules/catalog/maps/schemas.py` - Describes non-expiring Community share links and Enterprise-only expiring links.
- `backend/app/modules/catalog/maps/router.py` - Describes enforced share-link expiration behavior in route docstrings.
- `frontend/src/i18n/locales/en/builder.json` - Keeps Community failure copy operational and avoids domain-restriction implications.
- `docs-internal/GTM/pricing-to-tiers.md` - Keeps advanced sharing controls in the paid tier.
- `docs-internal/GTM/free-vs-enterprise.md` - Records Community basic sharing and Enterprise advanced sharing classification.
- `backend/openapi.json` - Regenerated FastAPI snapshot for final advanced-sharing descriptions.
- `.planning/phases/234-governance-contract-verification/234-VERIFICATION.md` - Records goal-backward phase verification.

## Decisions Made

- Kept Community copy plain and operational rather than introducing upgrade messaging in the builder share dialog.
- Treated OpenAPI diff review as a scope gate: unrelated schema drift was corrected before accepting the generated snapshot.
- Used the Docker-backed test database on `POSTGRES_PORT=5434` for DB-backed sharing endpoint verification because the default local Postgres service was not provisioned for these tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Restore STAC import visibility enum to keep OpenAPI refresh scoped**
- **Found during:** Task 2 (Regenerate and check OpenAPI snapshot)
- **Issue:** `make openapi` surfaced unrelated `StacImportRequest.visibility` snapshot drift because the source type was `str`, which removed the visibility enum from the generated schema.
- **Fix:** Restored `Visibility = Literal["private", "restricted", "internal", "public"]` in `backend/app/modules/catalog/sources/stac_router.py` before accepting the OpenAPI refresh.
- **Files modified:** `backend/app/modules/catalog/sources/stac_router.py`
- **Verification:** `make openapi-check` passed, and the final OpenAPI diff was limited to advanced-sharing descriptions/docstrings.
- **Committed in:** `3d492d26`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** The auto-fix prevented unrelated OpenAPI contract drift and preserved the plan's intended verification scope.

## Issues Encountered

- DB-backed pytest commands must not run concurrently in this repo because session fixtures drop and recreate `geolens_test`.
- The default local Postgres service on port 5432 was not suitable for the DB-backed checks; the Docker database on `POSTGRES_PORT=5434` passed the focused backend suite.

## Command Evidence

- `bash -lc '! rg -n "\(enterprise only\)|domain restriction may not be applied|ungated|without enforcement" backend/app/modules/embed_tokens backend/app/modules/catalog/maps frontend/src/i18n/locales/en/builder.json docs-internal/GTM'` - passed
- `make openapi-check` - passed
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_advanced_sharing_schema.py tests/test_embed_tokens.py::TestCreateEmbedToken tests/test_embed_tokens.py::TestCreateEmbedTokenWithOrigins tests/test_embed_tokens.py::TestUpdateEmbedToken tests/test_embed_tokens.py::TestRevokeEmbedToken tests/test_maps.py::TestShareToken tests/test_maps.py::TestUpdateShareToken -q` - 37 passed
- `cd backend && uv run ruff check app/modules/embed_tokens app/modules/catalog/maps tests/test_advanced_sharing_schema.py tests/test_embed_tokens.py tests/test_maps.py` - passed
- `cd frontend && npm run test -- src/components/builder/__tests__/SharePanel.test.tsx src/components/builder/hooks/__tests__/use-embed-tokens.test.ts` - 9 passed
- `cd frontend && npm run lint` - passed with 5 pre-existing warnings outside this plan's changes
- Negative control: temporarily removed the `expires_in_days != 30` Community schema guard and ran `cd backend && POSTGRES_PORT=65432 uv run pytest tests/test_advanced_sharing_schema.py::test_community_rejects_custom_embed_lifetime -q`; the test failed as expected with `Failed: DID NOT RAISE`. Restoring the guard made the same focused test pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 235 can use the verification artifact and regenerated OpenAPI snapshot to audit the v13.5 governance boundary without rediscovering the advanced-sharing implementation details.

## Self-Check

PASSED. Summary exists, key created verification file exists, Plan 05 commits are present, and final verification evidence is recorded.

---
*Phase: 234-governance-contract-verification*
*Completed: 2026-05-03*
