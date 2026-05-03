---
phase: 231-embedding-provider-extension-protocol
plan: 03
subsystem: testing
tags: [architecture, guard, embeddings, provider-sdk, invariant]

requires:
  - phase: 231-02
    provides: "Removed module-level OpenAI SDK import from processing/embeddings/helpers.py"
provides:
  - "Architecture guard renamed to test_no_module_level_provider_sdk_imports_in_processing"
  - "Provider-SDK import guard broadened to backend/app/processing/"
  - "Negative-control proof that a reintroduced OpenAI import in embeddings/helpers.py is caught"
affects: [phase-229, post-impl-audit, open-core-boundaries]

tech-stack:
  added: []
  patterns:
    - "Use git grep architecture guards for module-level provider SDK import invariants"

key-files:
  created:
    - .planning/phases/231-embedding-provider-extension-protocol/231-03-SUMMARY.md
  modified:
    - backend/tests/test_layering.py

key-decisions:
  - "Kept the provider SDK regex unchanged and broadened only the pathspec to backend/app/processing/."

patterns-established:
  - "Architecture guard negative controls can be run as transient inject-fail-revert demos without committed artifacts."

requirements-completed: [EMBPROV-04]

duration: 2 min
completed: 2026-05-03
---

# Phase 231 Plan 03: Architecture Guard Rename Summary

**Provider-SDK import architecture guard now covers all backend/app/processing/ paths, including embeddings.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-03T14:33:53Z
- **Completed:** 2026-05-03T14:36:07Z
- **Tasks:** 2
- **Files modified:** 1 code file plus this summary

## Accomplishments

- Renamed `test_no_module_level_provider_sdk_imports_in_processing_ai` to `test_no_module_level_provider_sdk_imports_in_processing`.
- Broadened the guard pathspec from `backend/app/processing/ai/` to `backend/app/processing/` and removed the embeddings carve-out paragraph.
- Ran the D-15 negative-control demo: injected `from openai import OpenAI` into `backend/app/processing/embeddings/helpers.py`, confirmed the renamed guard failed with the offending line surfaced, then reverted and confirmed the guard passed again.

## Task Commits

1. **Task 1: Rename architecture guard + broaden pathspec** - `d6fd169c` (test)
2. **Task 2: Negative-control verification** - no commit; transient inject-fail-revert verification only

**Plan metadata:** this docs commit

## Files Created/Modified

- `backend/tests/test_layering.py` - Renamed the architecture guard, broadened the pathspec, updated docstrings, and credited Phase 231 in the module docstring.
- `.planning/phases/231-embedding-provider-extension-protocol/231-03-SUMMARY.md` - Records Plan 03 execution, verification, and local environment limitations.

## Decisions Made

Kept the regex `r"^(from|import) (anthropic|openai)( |$)"` unchanged because it already covers both provider SDKs; only the guard pathspec needed to broaden.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Local full-suite verification is blocked by the currently running Postgres services, not by the Plan 03 code:

- `uv run pytest -x -q --tb=short` failed during test DB setup on `POSTGRES_PORT=5432` because `spatialflow-postgres` lacks the `vector` extension.
- `POSTGRES_PORT=5434 uv run pytest ...` reached `geolens-db-1`, but fresh migration setup failed the baseline `postgis` extension check.
- `PYTHONPATH=. uv run alembic check` ran but reported `Target database is not up to date` against the default local DB.

The architecture-specific checks do pass, and the negative-control proof confirms the renamed guard fires correctly.

## Verification

- `POSTGRES_PORT=1 uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -x -q` - passed
- `uv run pytest tests/test_layering.py -m architecture -x -q` - passed, `12 passed`
- `uv run ruff check tests/test_layering.py` - passed
- Negative-control pipeline - passed; `/tmp/231-negative-control-result.txt` contains `Module-level provider-SDK import found in backend/app/processing/.` and `backend/app/processing/embeddings/helpers.py:7:from openai import OpenAI`
- `uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing_ai -q` - old name not collected
- `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` - zero hits after revert

## User Setup Required

None - no external service configuration required for the code change. Local full-suite verification needs a GeoLens test Postgres instance with both PostGIS and pgvector available.

## Next Phase Readiness

Phase 231 has all three plan summaries. EMBPROV-04 is closed from the code perspective, and Phase 229 can audit Phase 231 after full-suite verification is rerun against a correctly provisioned test database.

---
*Phase: 231-embedding-provider-extension-protocol*
*Completed: 2026-05-03*
