---
phase: 1073-audit-remediation
reviewed: 2026-05-21T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - backend/app/platform/jobs/schemas.py
  - backend/app/platform/jobs/models.py
  - backend/app/platform/jobs/router.py
  - backend/app/platform/storage/titiler_url.py
  - backend/alembic/versions/0022_ingest_jobs_progress_columns.py
  - backend/app/processing/ingest/tasks_common.py
  - backend/app/processing/ingest/tasks_vector.py
  - backend/app/processing/ingest/tasks_raster.py
  - backend/app/processing/tiles/router.py
  - backend/app/modules/catalog/sources/stac_router.py
  - frontend/src/components/dataset/hooks/use-dataset.ts
  - frontend/src/components/import/hooks/use-vrt.ts
  - frontend/src/components/import/hooks/use-ingest.ts
  - backend/tests/test_jobs_router.py
  - backend/tests/test_ingest_progress.py
  - backend/tests/test_tasks_common_phase_brackets.py
  - backend/tests/test_titiler_url_helper.py
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues_found
---

# Phase 1073: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 1073 closes four P2 audit findings: TanStack cache invalidation (REMED-01), JobStatusResponse progress fields (REMED-02), `_job_phase_session` context manager extraction (REMED-03), and Titiler URL helper consolidation (REMED-04). The implementation is sound overall. One blocker is a hardcoded absolute path in a test that will fail on any machine other than the author's. Two warnings cover a dead Literal value in the API schema and a subtle missing-rollback path in the context manager's None branch.

## Critical Issues

### CR-01: Hardcoded absolute developer path in test fixture reference

**File:** `backend/tests/test_ingest_progress.py:140`
**Issue:** `fixture` is set to the literal string `"/Users/ishiland/Code/geolens/backend/tests/fixtures/ingest/basic_attrs.geojson"`. This path does not exist on any CI runner or another developer's checkout. The test will pass locally for the author but raise `FileNotFoundError` (likely during phase-1 `resolve_file_path` or `_validate_upload_file_safety`) on every other machine. The test is specifically the load-bearing brief-session pin (`test_vector_worker_writes_ogr2ogr_step_before_subprocess`) that the plan calls out as the contract guard for the mid-flight progress write.

**Fix:**
```python
# Use a Path-relative reference so the test is portable
from pathlib import Path

fixture = str(
    Path(__file__).parent / "fixtures" / "ingest" / "basic_attrs.geojson"
)
```

## Warnings

### WR-01: `"archiving"` Literal value in JobStatusResponse has no writer — dead contract surface

**File:** `backend/app/platform/jobs/schemas.py:87`
**Issue:** `current_step` Literal includes `"archiving"` as a valid value. No code path in the ingest workers ever writes `current_step = "archiving"` — `ingest_file` calls `_archive_original_file` inside the phase-2 block without updating `current_step` first, and `ingest_service` explicitly documents it never archives. The SUMMARY for Plan 02 notes the same (no archiving step for services) but the file-path never sets it either. The Literal value is therefore dead: it can never be produced by the current workers, but it validates as a legal value, which is misleading to future developers and API consumers.

This is correctness-adjacent: if a future developer adds `current_step = "archiving"` without also updating the step sequence, the progress value could be non-monotonic. The structural test `test_named_step_progress_is_non_decreasing` does not include "archiving" in the vector_steps sequence, confirming it is intentionally absent from actual writes.

**Fix:** Either remove `"archiving"` from the Literal entirely (the clean option), or add a `current_step = "archiving"` write site before `_archive_original_file` in `ingest_file`:
```python
# Option A — remove dead value from schema
current_step: (
    Literal[
        "validating",
        "ogr2ogr",
        "finalize",
        "complete",
        "cog_convert",
        "quicklook",
    ]
    | None
) = None

# Option B — add write site in tasks_vector.py phase-2, before _archive_original_file:
job.current_step = "archiving"
# (then update test_named_step_progress_is_non_decreasing to include it)
```

### WR-02: `_job_phase_session` None-job branch lacks rollback on caller exception

**File:** `backend/app/processing/ingest/tasks_common.py:229-230`
**Issue:** When `job is None` (row vanished), the helper does `yield session, None; return`. The `yield` is outside the `try/except: rollback; raise` block that wraps the found-job branch. If a caller raises an exception inside the `async with` block after receiving `(session, None)` — whether by accident or by a future caller that does something with the bare session in the None branch — the exception propagates out of the `async with async_session()` without an explicit `session.rollback()`. SQLAlchemy's `AsyncSession.__aexit__` calls `close()`, not `rollback()`, so any staged (unflushed) state is lost without a clean rollback.

All current callers guard with `if job is None: return` so this cannot be triggered today. However the contract test `test_phase_session_yields_none_when_job_missing` does not cover the exception-in-None-branch path, leaving the gap unpinned.

**Fix:**
```python
if job is None:
    structlog.get_logger().warning(
        "Ingest job not found in phase, skipping",
        job_id=str(job_uuid),
        phase=phase,
    )
    try:
        yield session, None
    except Exception:
        await session.rollback()
        raise
    return
```

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

## Fix Iteration 1

_Fixed: 2026-05-21_

| Finding | Disposition | Commit |
|---------|-------------|--------|
| CR-01 | FIXED — replaced hardcoded `/Users/ishiland/...` path with `str(Path(__file__).parent / "fixtures" / "ingest" / "basic_attrs.geojson")` in `test_ingest_progress.py:141`; added `from pathlib import Path` import. Fixture confirmed present at resolved path. | `255bead8` |
| WR-01 | FIXED — removed `"archiving"` from `JobStatusResponse.current_step` Literal in `schemas.py`. No worker writes this value; structural test `test_named_step_progress_is_non_decreasing` already excluded it. Both structural tests pass. | `f33b895d` |
| WR-02 | FIXED — wrapped None-job `yield session, None` in `_job_phase_session` with the same `try/except: rollback; raise` guard as the found-job branch. Added `test_job_phase_session_none_branch_rolls_back_on_exception` to `test_tasks_common_phase_brackets.py` to pin exception-propagates-from-None-branch contract. Syntax check passes; DB-requiring tests need running stack. | `90e939b7` |
