---
phase: 240-full-gate-and-deprecation-cleanup
plan: "01"
subsystem: testing
tags: [pytest, coverage, ruff, react, vitest, playwright, e2e]

requires:
  - phase: 239-close-audit-and-verification
    provides: Focused maps/search close-gate evidence and v13.6 audit debt record
provides:
  - Broader backend, frontend, and Playwright gate evidence for DEBT-01
  - Exact local blockers and residual risks for full-suite release confidence
affects: [v13.6, DEBT-01, TD-01, testing, release-gates]

tech-stack:
  added: []
  patterns: [Evidence-only closeout for broader validation gates without widening implementation scope]

key-files:
  created:
    - .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
  modified:
    - docs-internal/audits/post-impl-20260504-v13-6.md

key-decisions:
  - "No fix-forward patches were applied because broad-gate failures were outside Phase 240/v13.6 maps-search ownership or were local prerequisite/data issues."
  - "Focused v13.6 maps/search backend gates were rerun as the nearest owned backend equivalent after the full backend suite exposed unrelated failures."

patterns-established:
  - "Broader gate debt can close with exact pass/fail/blocker evidence while preserving unrelated dirty work and avoiding out-of-scope fixes."

requirements-completed: [DEBT-01]

duration: 13 min
completed: 2026-05-04
---

# Phase 240 Plan 01: Broader Confidence Gates Summary

**Broader v13.6 validation evidence now records full backend, frontend, and Playwright outcomes with scoped blockers for DEBT-01.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-05-04T00:56:50Z
- **Completed:** 2026-05-04T01:09:54Z
- **Tasks:** 5 completed
- **Files modified:** 2 planned evidence files, plus required GSD metadata after summary generation

## Baseline

Initial `git status --short --untracked-files=all` showed the known unrelated dirty files:

- `docs/aws-security-groups.md`
- `frontend/src/components/builder/BuilderMap.tsx`
- `frontend/src/components/builder/hooks/use-builder-save.ts`
- `frontend/src/components/dataset/AttributeTable.tsx`
- `frontend/src/components/import/UploadForm.tsx`
- `frontend/src/lib/external-links.ts`
- `frontend/src/pages/MapBuilderPage.tsx`

Prerequisites:

- Docker Compose stack was running; `api` and `db` were healthy, with API on `127.0.0.1:8001`, DB on `127.0.0.1:5434`, frontend on `8080`.
- `frontend/node_modules` and root `node_modules` were present.
- `playwright.config.ts` defines `npm run e2e:smoke` as core, builder, and fixture browser slices.

During execution, additional frontend files became dirty in the shared worktree. They were not modified by this plan and were not staged.

## Accomplishments

- Ran the broadest documented backend gate, `make test-cov`, and recorded the exact failure surface instead of claiming full backend confidence.
- Ran backend ruff check, full format check, focused maps/search pytest, and focused maps/search format check to isolate the v13.6-owned backend surface.
- Ran frontend build, lint, and coverage gates successfully.
- Ran Playwright smoke and separately captured core, builder, and fixture slice outcomes after the chained smoke command stopped at the core failure.
- Updated the v13.6 close audit with DEBT-01 broader-gate evidence.

## Command Evidence

| Command | Status | Evidence |
|---------|--------|----------|
| `git status --short --untracked-files=all` | pass | Recorded known unrelated dirty files before validation. |
| `docker compose ps --format json` | pass | `api` and `db` healthy; `frontend`, `worker`, and `titiler` running. |
| `make test-cov` | fail | `5 failed, 2052 passed, 15 skipped, 5 deselected, 44 warnings, 33 errors in 407.31s`; coverage still exceeded threshold at `75.01%`. |
| `cd backend && uv run ruff check .` | pass | `All checks passed!` |
| `cd backend && uv run ruff format --check .` | fail | 8 files would be reformatted: `router_data.py`, `router_export.py`, `router_reupload.py`, `router_vrt.py`, `sources/router.py`, `embed_tokens/schemas.py`, `platform/extensions/defaults.py`, `tests/test_workflow_extension.py`. These are outside Phase 240 owned scope. |
| `cd backend && env ... uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q` | pass | `176 passed, 16 warnings in 71.13s`. |
| `cd backend && uv run ruff format --check app/modules/catalog/maps app/modules/catalog/search tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py tests/test_layering.py` | pass | `28 files already formatted`. |
| `cd frontend && npm run build` | pass | Production build completed; Vite emitted existing large-chunk warnings only. |
| `cd frontend && npm run lint` | pass | ESLint exited 0. |
| `cd frontend && npm run test:coverage` | pass | `115 passed` test files; `1012 passed`, `8 todo`; coverage completed. Node emitted existing `--localstorage-file` warnings. |
| `npm run e2e:smoke` | fail | Core smoke stopped with `5 failed`, `2 skipped`, `5 did not run`, `19 passed` in 43.2s. |
| `npm run e2e:smoke:builder` | fail | `2 failed`, `15 did not run`, `1 passed` in 13.1s; failures could not find dataset fixtures. |
| `npm run e2e:smoke:fixtures` | fail | `2 failed`, `3 did not run`, `1 passed` in 1.3m; upload/import UI did not reach expected completion links. |

## Backend Failure Triage

`make test-cov` exposed broad-suite failures outside the v13.6 maps/search decomposition scope:

- SAML/lifecycle setup errors: `ModuleNotFoundError: No module named 'geolens_enterprise'`.
- Reupload fixture errors: tests patch `router_reupload.run_ogrinfo_preview`, which is absent from the current module.
- Embed token failure: `test_tile_access_expired_token` expected token creation `201` but received `422`; targeted rerun reproduced the same failure.
- Architecture guard failures in Phase 232/233 and Phase 238 guard tests appeared in the full run, but current host line counts for maps/search service modules are within caps and focused maps/search gates passed.
- A targeted container rerun of `test_maps_search_service_modules_stay_within_size_budgets` was blocked during test DB setup by `Required extension "postgis" is not installed`; the host-based focused maps/search gate passed against the documented Compose DB.

No backend fix-forward patch was applied because none of the broad failures was attributable to Phase 240 or the v13.6 maps/search split.

## Frontend Failure Triage

Frontend build, lint, and coverage passed despite unrelated frontend worktree changes.

Playwright smoke did not pass:

- `collections.spec.ts` strict locator conflict: `getByRole('button', { name: 'Create' })` matched both `Create` and `Create your first collection`.
- `dataset-detail.spec.ts`, `search.spec.ts`, `builder.spec.ts`, and `builder-styling.spec.ts` could not find stable searchable/vector dataset fixtures.
- `non-spatial.spec.ts` and `upload.spec.ts` did not reach expected import completion UI links.

These are local E2E fixture/data and existing spec robustness issues, not Phase 240 maps/search backend regressions. No frontend fix-forward patch was applied.

## Task Commits

Validation-only tasks produced no code commits. The evidence and required GSD metadata are committed in the plan metadata commit.

## Files Created/Modified

- `.planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md` - Records DEBT-01 broader-gate evidence.
- `docs-internal/audits/post-impl-20260504-v13-6.md` - Adds the Phase 240 broader-gate evidence addendum.

## Decisions Made

- Broader backend gate failures were recorded instead of fixed because the failure surface is outside the owned Phase 240/v13.6 maps-search scope.
- Focused maps/search backend pytest and format checks were used as nearest owned backend evidence after full backend coverage failed.
- Playwright smoke failures were documented as E2E fixture/spec prerequisites rather than fixed in this plan.

## Deviations from Plan

None - plan executed as written. The plan allowed recording environmental or out-of-scope blockers and applying no fix when failures were not directly attributable to Phase 240/v13.6.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** DEBT-01 is closed as evidence debt, not as proof that all broader gates are currently green.

## Issues Encountered

- Full backend coverage is not green in this local stack. The exact failures are recorded above.
- Full backend format is not green because 8 out-of-scope backend files need formatting.
- Playwright smoke is not green because local E2E data/spec prerequisites are not stable.
- Shared-worktree frontend changes expanded during execution; they were preserved and excluded from commits.

## User Setup Required

None - no external service configuration required for this evidence pass. A future full-green pass needs E2E fixture/data cleanup and, if SAML/lifecycle tests are intended in community-only local runs, the relevant enterprise overlay or marker selection.

## Next Phase Readiness

Ready for Plan 240-02. DEBT-01 now has exact broader-gate outcomes and residual risks. DEBT-02 remains pending for deprecation-warning close evidence.

---
*Phase: 240-full-gate-and-deprecation-cleanup*
*Completed: 2026-05-04*
