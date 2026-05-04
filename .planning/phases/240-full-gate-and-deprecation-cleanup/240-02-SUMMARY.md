---
phase: 240-full-gate-and-deprecation-cleanup
plan: "02"
subsystem: testing
tags: [pydantic, alembic, authlib, pytest, deprecations]

requires:
  - phase: 240-full-gate-and-deprecation-cleanup
    provides: DEBT-01 broader-gate evidence from Plan 240-01
provides:
  - Deprecation-warning inventory and cleanup evidence for DEBT-02
  - Phase 240 verification and refreshed v13.6 audit status
affects: [v13.6, DEBT-02, TD-02, backend, close-gate]

tech-stack:
  added: []
  patterns: [Use Pydantic v2 json_schema_extra for OpenAPI examples]

key-files:
  created:
    - .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md
    - .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md
  modified:
    - backend/app/modules/auth/schemas.py
    - backend/app/modules/catalog/collections/schemas.py
    - backend/app/modules/catalog/layers/schemas.py
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/embed_tokens/schemas.py
    - docs-internal/audits/post-impl-20260504-v13-6.md
    - .planning/v13.6-MILESTONE-AUDIT.md
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md

key-decisions:
  - "Project-owned Pydantic warnings were fixed in schema metadata rather than deferred."
  - "Alembic and Authlib warnings were documented as non-blocking follow-up because the safe local Alembic attempt broke migration setup, and Authlib's warning originates inside the installed dependency."

patterns-established:
  - "Warning cleanup must rerun the warning-visible focused gate after every attempted warning fix."

requirements-completed: [DEBT-02]

duration: 26 min
completed: 2026-05-04
---

# Phase 240 Plan 02: Deprecation Warning Close Evidence Summary

**Focused v13.6 backend verification now runs with project-owned Pydantic warnings removed and explicit owner follow-up for the remaining Alembic/Authlib warnings.**

## Performance

- **Duration:** 26 min
- **Started:** 2026-05-04T01:10:00Z
- **Completed:** 2026-05-04T01:22:01Z
- **Tasks:** 5 completed
- **Files modified:** 10

## Accomplishments

- Inventoried the focused warning surface at `176 passed, 16 warnings`.
- Fixed 14 project-owned Pydantic v2 deprecation warnings by moving `Field(example=...)` metadata to `json_schema_extra`.
- Reran the focused maps/search command and reduced the warning surface to 2 non-blocking warnings.
- Refreshed Phase 240 verification, v13.6 close audit evidence, and milestone-audit status for DEBT-02.

## Warning Inventory

| Source | Count before | Count after | Owner | Disposition |
|--------|--------------|-------------|-------|-------------|
| Pydantic `Field(example=...)` in GeoLens schemas | 14 | 0 | Backend schema owners | Fixed in `auth`, `collections`, `layers`, `maps`, and `embed_tokens` schemas. |
| Alembic `path_separator` config warning | 1 | 1 | Backend migrations/platform | Deferred. A minimal `path_separator = os` attempt caused test DB migrations to skip required tables, so this needs a migration-config hardening pass with dedicated migration tests. |
| Authlib `authlib.jose` compatibility shim warning | 1 | 1 | Backend auth dependency | Deferred. Warning originates in installed Authlib internals from `authlib.integrations.starlette_client`; track joserfc/Authlib migration before Authlib 2.0. |

## Command Evidence

| Command | Status | Evidence |
|---------|--------|----------|
| `cd backend && env ... uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q -W default` | pass before fix | `176 passed, 16 warnings in 69.21s`; warnings were 14 Pydantic, 1 Alembic, 1 Authlib. |
| `cd backend && uv run ruff check app/modules/catalog/maps/schemas.py app/modules/auth/schemas.py app/modules/catalog/collections/schemas.py app/modules/embed_tokens/schemas.py app/modules/catalog/layers/schemas.py` | pass | `All checks passed!` |
| `cd backend && uv run ruff format --check app/modules/catalog/maps/schemas.py app/modules/auth/schemas.py app/modules/catalog/collections/schemas.py app/modules/embed_tokens/schemas.py app/modules/catalog/layers/schemas.py` | pass | `5 files already formatted`. |
| `cd backend && env ... uv run pytest ... -q -W default` | pass after Pydantic fix | `176 passed, 2 warnings in 69.95s`; only Alembic and Authlib warnings remained. |
| Alembic `path_separator = os` trial plus `os.pathsep` join | reverted | Rerun failed with `29 passed, 1 warning, 147 errors`; setup could not find `catalog.roles`, proving the change was not safe inside Phase 240. |
| `cd backend && env ... uv run pytest ... -q -W default` | pass after Alembic revert | `176 passed, 2 warnings in 70.22s`. |

## Task Commits

1. **Fix safe project-owned warnings** - `9ad1489b` (`fix(240-02): clear project-owned deprecation warnings`)

**Plan metadata:** pending docs commit for this summary, verification, and audit refresh.

## Files Created/Modified

- `backend/app/modules/auth/schemas.py` - Converts auth request examples to Pydantic v2 schema metadata.
- `backend/app/modules/catalog/collections/schemas.py` - Converts collection create examples.
- `backend/app/modules/catalog/layers/schemas.py` - Converts layer create examples.
- `backend/app/modules/catalog/maps/schemas.py` - Converts map create examples.
- `backend/app/modules/embed_tokens/schemas.py` - Converts embed-token create examples.
- `.planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md` - Records DEBT-02 warning inventory and disposition.
- `.planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md` - Records Phase 240 goal verification.
- `docs-internal/audits/post-impl-20260504-v13-6.md` - Adds warning-cleanup evidence.
- `.planning/v13.6-MILESTONE-AUDIT.md` - Refreshes TD-01/TD-02 status after Phase 240.

## Decisions Made

- Fixed project-owned Pydantic schema metadata because it was small, behavior-neutral, and fully covered by the focused command.
- Deferred the Alembic warning after direct verification showed the apparent one-line config update broke test database migration setup.
- Deferred the Authlib warning because it is emitted from dependency internals and should be handled as an auth dependency migration, not a local suppression.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reverted unsafe Alembic config trial**
- **Found during:** Task 2 (Fix safe project-owned warnings)
- **Issue:** Adding `path_separator = os` and joining dynamic version locations with `os.pathsep` removed the Alembic warning but caused focused tests to error during fixture setup with missing `catalog.roles`.
- **Fix:** Reverted the Alembic config/env change and documented the warning as a migration-platform follow-up.
- **Files modified:** `backend/alembic.ini`, `backend/alembic/env.py` were restored to their prior content.
- **Verification:** Focused maps/search command returned to `176 passed, 2 warnings`.
- **Committed in:** Not committed; reverted before the task commit.

---

**Total deviations:** 1 auto-fixed (Rule 1).
**Impact on plan:** The failed Alembic trial strengthened the evidence that the remaining warning needs a dedicated migration-config pass. No broken Alembic change was committed.

## Issues Encountered

- The broader gates from Plan 240-01 are still not all green locally; this remains recorded as residual release-confidence evidence, not a Phase 240 functional blocker.
- The remaining Alembic/Authlib warnings are not fixed in this phase, but both have explicit owner and follow-up disposition.

## User Setup Required

None.

## Next Phase Readiness

Phase 240 can be verified. DEBT-01 has exact broader-gate evidence, and DEBT-02 has the project-owned warnings fixed plus explicit non-blocking follow-up for the two remaining warnings.

---
*Phase: 240-full-gate-and-deprecation-cleanup*
*Completed: 2026-05-04*
