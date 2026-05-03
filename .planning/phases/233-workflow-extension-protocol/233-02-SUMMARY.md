---
phase: 233-workflow-extension-protocol
plan: 02
status: complete
subsystem: api
tags:
  - workflow
  - catalog
  - publication
requires:
  - phase: 233-workflow-extension-protocol
    provides: 233-01 WorkflowExtension scaffold
provides:
  - publication status endpoint workflow dispatch
  - target-status workflow-order walking
  - extension-ready StatusUpdate validation
  - route-level overlay block/add/observe tests
affects:
  - 233-03-metadata-custom-state
  - 233-04-guard-and-verification
tech-stack:
  added: []
  patterns:
    - route functions build WorkflowTransitionContext and delegate policy to WorkflowExtension
    - compatibility aliases sourced from DefaultWorkflowExtension
key-files:
  created: []
  modified:
    - backend/app/modules/catalog/datasets/domain/schemas.py
    - backend/app/modules/catalog/datasets/api/router_data.py
    - backend/tests/test_publication_lifecycle.py
    - backend/tests/test_workflow_extension.py
key-decisions:
  - "StatusUpdate now validates syntax only; workflow policy owns status vocabulary and transition validity."
  - "target-status uses workflow.status_order() and calls allowed_transitions/on_transition for each intermediate step."
patterns-established:
  - "Endpoint policy checks use WorkflowTransitionContext(mode='status'|'target_status') before assigning record_status."
requirements-completed:
  - WORK-02
  - WORK-03
  - WORK-04
duration: 5 min
completed: 2026-05-03
---

# Phase 233 Plan 02: Route Publication Endpoints Summary

**Dataset publication endpoints now delegate transition policy and hooks to WorkflowExtension**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-03T16:49:57Z
- **Completed:** 2026-05-03T16:54:46Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Changed `StatusUpdate` to strip status input and reject blanks without hardcoding the Community vocabulary.
- Routed `PATCH /datasets/{id}/status/` through `get_workflow_extension().allowed_transitions()` and `on_transition()`.
- Routed `PATCH /datasets/{id}/target-status/` through `workflow.status_order()` and per-step transition contexts.
- Added direct route-function tests proving overlays can add, observe, and block transitions without modifying router code.

## Task Commits

Each task was committed atomically:

1. **Task 1: Make StatusUpdate validation extension-ready** - `6a555234` (`feat`)
2. **Task 2: Route direct status transitions through WorkflowExtension** - `a89f53cb` (`feat`)
3. **Task 3: Route target-status walking and add endpoint overlay proofs** - `1218d7a0` (`test`)

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/schemas.py` - Moves status membership out of Pydantic validation.
- `backend/app/modules/catalog/datasets/api/router_data.py` - Delegates direct and target publication transitions to `WorkflowExtension`.
- `backend/tests/test_publication_lifecycle.py` - Keeps DB-backed Community lifecycle regressions aligned with workflow-boundary validation and target-status walking.
- `backend/tests/test_workflow_extension.py` - Adds pure route-function overlay tests for add, observe, and block behavior.

## Decisions Made

- `ALLOWED_TRANSITIONS` and `_STATUS_ORDER` remain import-compatible, but are sourced from `DefaultWorkflowExtension`.
- Route errors preserve the existing `Cannot transition from ... Allowed: ...` detail style for denied transitions.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

The full DB-backed lifecycle command still cannot run in this local environment because test session setup fails on `CREATE EXTENSION IF NOT EXISTS vector`; the installed Postgres service lacks pgvector. Pure route-function coverage was run with `POSTGRES_PORT=65432` to bypass DB provisioning, and DB-backed tests remain committed for CI/properly provisioned Postgres.

## Command Evidence

- `python -m compileall backend/app/modules/catalog/datasets/domain/schemas.py backend/app/modules/catalog/datasets/api/router_data.py backend/tests/test_publication_lifecycle.py backend/tests/test_workflow_extension.py` - passed
- `cd backend && POSTGRES_PORT=65432 uv run python - <<'PY' ... StatusUpdate ... PY` - passed (`status-update-validation-ok`)
- `cd backend && POSTGRES_PORT=65432 uv run pytest tests/test_workflow_extension.py` - 8 passed, 3 warnings
- `cd backend && uv run ruff check app/modules/catalog/datasets/domain/schemas.py app/modules/catalog/datasets/api/router_data.py tests/test_publication_lifecycle.py tests/test_workflow_extension.py` - passed
- `cd backend && uv run pytest tests/test_publication_lifecycle.py tests/test_workflow_extension.py` - blocked in session setup by missing `vector` extension before tests executed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 03 can route metadata PATCH status writes through the same workflow seam and relax the persistence constraint for extension-defined statuses.

## Self-Check

PASSED. Summary exists, `233-02` task commits are present, and key modified route/test files are on disk.

---
*Phase: 233-workflow-extension-protocol*
*Completed: 2026-05-03*
