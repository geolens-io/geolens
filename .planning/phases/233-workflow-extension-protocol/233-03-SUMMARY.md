---
phase: 233-workflow-extension-protocol
plan: 03
status: complete
subsystem: api
tags:
  - workflow
  - metadata
  - alembic
requires:
  - phase: 233-workflow-extension-protocol
    provides: 233-02 publication endpoint workflow routing
provides:
  - relaxed record_status persistence constraint migration
  - metadata PATCH workflow routing
  - metadata bypass block proof
  - custom workflow status proof
affects:
  - 233-04-guard-and-verification
tech-stack:
  added: []
  patterns:
    - metadata status writes use WorkflowTransitionContext(mode='metadata_patch')
    - extension-defined statuses are policy-owned rather than DB-check-owned
key-files:
  created:
    - backend/alembic/versions/0003_workflow_status_extension.py
  modified:
    - backend/app/modules/catalog/datasets/domain/models.py
    - backend/app/modules/catalog/datasets/domain/service_metadata.py
    - backend/app/modules/catalog/datasets/api/router.py
    - backend/tests/test_workflow_extension.py
    - backend/tests/test_validation.py
key-decisions:
  - "The baseline migration remains unchanged; fresh installs create the old check and 0003 removes it."
  - "Metadata PATCH workflow validation runs before assignment and before the caller-owned commit."
patterns-established:
  - "Metadata update services accept both actor_id for audit fields and actor for extension policy context."
requirements-completed:
  - WORK-02
  - WORK-03
  - WORK-04
duration: 4 min
completed: 2026-05-03
---

# Phase 233 Plan 03: Metadata Custom State Summary

**Metadata PATCH record_status writes now use WorkflowExtension, and persistence can store overlay-defined statuses**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-03T16:54:46Z
- **Completed:** 2026-05-03T16:58:42Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added Alembic revision `0003_workflow_status_extension` to drop `chk_records_record_status` and recreate it on downgrade.
- Removed the hardcoded `Record.record_status` ORM `CheckConstraint`.
- Routed metadata PATCH `record_status` changes through `WorkflowExtension` with mode `metadata_patch`.
- Passed the authenticated `Identity` from `update_dataset_metadata()` into the metadata service for extension policy context.
- Added tests proving metadata PATCH cannot bypass an overlay block and that an overlay-defined `review` state can pass through `/status/`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Relax record_status persistence constraint** - `a9d18277` (`feat`)
2. **Task 2: Route metadata record_status writes through WorkflowExtension** - `facb9be9` (`feat`)
3. **Task 3: Add metadata bypass and custom-state overlay tests** - `16f0a8ed` (`test`)

## Files Created/Modified

- `backend/alembic/versions/0003_workflow_status_extension.py` - Drops/recreates the old Community status check constraint.
- `backend/app/modules/catalog/datasets/domain/models.py` - Removes the hardcoded status check from ORM metadata.
- `backend/app/modules/catalog/datasets/domain/service_metadata.py` - Adds metadata-patch workflow validation and transition hooks.
- `backend/app/modules/catalog/datasets/api/router.py` - Passes `actor=user` into metadata updates.
- `backend/tests/test_workflow_extension.py` - Adds metadata bypass and custom-state route-function coverage.
- `backend/tests/test_validation.py` - Strengthens Community publish assertions for `published_at`.

## Decisions Made

- Kept `0001_baseline.py` intact as planned; `0003` relaxes the schema after baseline creation.
- Same-status metadata writes do not invoke workflow transition hooks because there is no transition to authorize.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

`cd backend && PYTHONPATH=. uv run alembic upgrade head` cannot complete against the local DB because baseline migration setup fails on missing PostGIS before reaching revision `0003`. The session pytest path also remains blocked by missing pgvector. Alembic graph inspection confirms `0003_workflow_status_extension` is the single head.

## Command Evidence

- `python -m compileall backend/app/modules/catalog/datasets/domain/models.py backend/alembic/versions/0003_workflow_status_extension.py backend/app/modules/catalog/datasets/domain/service_metadata.py backend/app/modules/catalog/datasets/api/router.py backend/tests/test_workflow_extension.py backend/tests/test_validation.py` - passed
- `cd backend && POSTGRES_PORT=65432 uv run pytest tests/test_workflow_extension.py` - 10 passed, 3 warnings
- `cd backend && uv run ruff check app/modules/catalog/datasets/domain/models.py app/modules/catalog/datasets/domain/service_metadata.py app/modules/catalog/datasets/api/router.py tests/test_workflow_extension.py tests/test_validation.py` - passed
- `cd backend && PYTHONPATH=. uv run alembic heads` - `0003_workflow_status_extension (head)`
- `cd backend && PYTHONPATH=. uv run alembic upgrade head` - blocked by missing PostGIS in local DB
- selected DB-backed validation pytest command - blocked by missing pgvector during session setup

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 04 can add a narrow architecture guard over `router_data.py` and `service_metadata.py`, then write the phase verification artifact.

## Self-Check

PASSED. Summary exists, migration file exists, and three `233-03` task commits are present.

---
*Phase: 233-workflow-extension-protocol*
*Completed: 2026-05-03*
