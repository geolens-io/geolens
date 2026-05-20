---
phase: 1058-multi-layer-gpkg-handling
reviewed: 2026-05-19T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - backend/app/processing/ingest/router.py
  - backend/app/processing/ingest/schemas.py
  - backend/app/processing/ingest/service.py
  - backend/app/processing/ingest/tasks_reupload.py
  - backend/app/processing/ingest/ogr.py
  - backend/app/modules/catalog/datasets/api/router_reupload.py
  - backend/app/platform/jobs/models.py
  - backend/alembic/versions/0017_ingest_job_fanned_out_status.py
  - backend/tests/test_reupload.py
  - backend/tests/test_ingest_fan_out.py
  - frontend/src/components/dataset/ReuploadDialog.tsx
  - frontend/src/components/import/BulkReviewList.tsx
  - frontend/src/components/import/UploadForm.tsx
  - frontend/src/api/datasets.ts
  - frontend/src/i18n/locales/en/dataset.json
  - frontend/src/i18n/locales/en/import.json
  - frontend/src/processing/ingest/tasks_vector.py
  - e2e/reupload-multi-layer-gpkg.spec.ts
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: clean
fixed_at: 2026-05-20T03:05:00Z
---

# Phase 1058: Code Review Report

**Reviewed:** 2026-05-19T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 1058 adds multi-layer GPKG handling across three scopes: (1) `layer_name` plumbing through the reupload preview/commit flow (GPKG-01), (2) a frontend schema-change advisory banner (GPKG-02), and (3) a backend `POST /ingest/commit-fan-out/{job_id}` endpoint with matching frontend fan-out handler (GPKG-03/04). The Alembic migration for the `'fanned_out'` status and the ingest task plumbing are structurally sound. Most key decisions from the spec are correctly implemented.

Two critical issues were found:

1. **`all_layers` is never persisted to `job.user_metadata`** on the new-upload path, so the `/ingest/commit-fan-out/{job_id}` endpoint always sees an empty `all_layers` list and accepts (or rejects) every layer name — the security validation on line 706 silently passes because `known_layer_names` is empty, making the "unknown layer" guard a no-op.
2. **The partial-failure fan-out marks the original job `'fanned_out'` even when all layers fail**, rendering the file unreachable for retry without a new upload.

Three warnings and two informational findings round out the report.

## Critical Issues

### CR-01: `all_layers` not persisted to `job.user_metadata` — fan-out layer validation is a no-op

**File:** `backend/app/processing/ingest/router.py:706`

**Issue:** `commit_fan_out` validates requested layer names against `job.user_metadata.get("all_layers", [])`. However, `all_layers` is **never written into `job.user_metadata`** anywhere in the upload or commit flow. The upload endpoint (`/ingest/upload`) creates the job, the preview endpoint (`/ingest/preview/{job_id}`) reads `all_layers` from ogrinfo but only returns it in the `PreviewResponse` — it never persists it back to `job.user_metadata`. The commit endpoint (`/ingest/commit/{job_id}`) merges commit body fields but `all_layers` is not a commit field.

Consequence: `known_layer_names` at line 714 is always an empty set for jobs going through the new-upload flow. The guard at line 716 computes:
```python
unknown = [layer.layer_name for layer in request.layers
           if layer.layer_name not in known_layer_names]
```
With `known_layer_names = set()`, every requested layer name is in `unknown`. This means the endpoint either:
- Rejects every fan-out request with a 422 ("Unknown layer name(s)"), OR
- If the job was created via a path that _does_ store `all_layers` (e.g., the test helper `_make_pending_job` that injects `all_layers` directly into `user_metadata`), validation passes only for that synthetic case.

The integration tests in `test_ingest_fan_out.py` bypass this bug by constructing the job directly with `all_layers` in `user_metadata` via `_make_pending_job`. A real user uploading a GPKG then calling `/commit-fan-out` will hit a 422 on every layer.

**Fix:** In `preview_file` (router.py), after ogrinfo succeeds, stamp `all_layers` into `job.user_metadata` if it is non-null:

```python
# After line 567 (inside the vector preview branch):
if info.get("all_layers"):
    job.user_metadata = {
        **(job.user_metadata or {}),
        "all_layers": info["all_layers"],
    }
    await db.commit()
```

Alternatively, stamp it during `commit_import` by including `all_layers` in the commit request schema — but that requires a client change. The preview-time persistence is the simpler fix and is consistent with how `file_type: raster` is stamped at upload time.

---

### CR-02: Original job marked `'fanned_out'` unconditionally even when all layer dispatches fail

**File:** `backend/app/processing/ingest/router.py:738-740`

**Issue:** After the per-layer loop at lines 733-735 (`for layer in request.layers: result = await create_fan_out_jobs(...)`), the original job is unconditionally set to `status='fanned_out'` regardless of how many layers actually succeeded:

```python
# Lines 738-740
job.status = "fanned_out"
job.completed_at = datetime.now(timezone.utc)
await db.commit()
```

`create_fan_out_jobs` returns a `FanOutLayerResult` with `status='failed'` on per-layer errors rather than raising — so the outer loop never short-circuits. If every layer fails (e.g., Procrastinate is unavailable), the original job is marked `'fanned_out'` (terminal) and `file_path` remains on it, but there is no way to retry: the job is no longer `'pending'`, and the endpoint rejects non-pending jobs at line 699.

A user who triggers a fan-out during a brief queue outage loses all layers permanently and must re-upload the entire file.

**Fix:** Conditionally mark `'fanned_out'` only when at least one layer was queued successfully:

```python
queued_count = sum(1 for r in results if r.status == "queued")
if queued_count > 0:
    job.status = "fanned_out"
    job.completed_at = datetime.now(timezone.utc)
else:
    # All layers failed — keep job 'pending' so the user can retry.
    job.status = "pending"
await db.commit()
```

The response already surfaces per-layer outcomes, so the client can show the full failure without the original job being destroyed.

---

## Warnings

### WR-01: `runWithConcurrency` is dead code after Plan 04 rewrote `handleIngestAllLayers`

**File:** `frontend/src/components/import/UploadForm.tsx:51-71`

**Issue:** Plan 03 introduced `runWithConcurrency` as a parallelism helper. Plan 04 replaced the entire `handleIngestAllLayers` implementation with a single `commitFanOut` API call that requires none of this helper. The function is defined at lines 51-71 but never called anywhere in the codebase (confirmed by grep). It ships as dead code in the production bundle.

**Fix:** Delete lines 51-71 (`async function runWithConcurrency<T, R>(...)`) from `UploadForm.tsx`.

---

### WR-02: `reupload_preview` validation runs ogrinfo once (with `layer_name`) but validates `layer_name` against `all_layers` from that same targeted call — misses the single-layer edge case

**File:** `backend/app/modules/catalog/datasets/api/router_reupload.py:346-356`

**Issue:** The validation sequence in `reupload_preview` is:

```python
info = await get_catalog_port().run_ogrinfo_preview(file_path, layer_name=layer_name)
all_layers = info.get("all_layers")  # None for single-layer files
if layer_name is not None and all_layers is not None:
    layer_names_in_file = {lyr["name"] for lyr in all_layers}
    if layer_name not in layer_names_in_file:
        raise HTTPException(...)
```

`all_layers` is `None` when the file has exactly one layer (per `ogr.py:250`: `if len(layers) > 1: all_layers = [...]`). If a user passes a `layer_name` that doesn't exist in a single-layer GPKG, the condition `all_layers is not None` is False, validation is skipped, and ogrinfo silently falls back to the default layer (index 0). The response will show data for the wrong layer while appearing to succeed.

This is unlikely to produce data corruption (ogr2ogr will ingest from the correct single-layer file), but the API returns data for a layer the user didn't request, which is misleading.

**Fix:** When `layer_name` is provided and `all_layers` is None (single-layer file), validate that `layer_name` matches `info["layer_name"]`:

```python
if layer_name is not None:
    if all_layers is not None:
        layer_names_in_file = {lyr["name"] for lyr in all_layers}
        if layer_name not in layer_names_in_file:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Layer '{layer_name}' not found in this file.",
            )
    elif info["layer_name"] and layer_name != info["layer_name"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Layer '{layer_name}' not found in this file (single-layer file contains '{info['layer_name']}').",
        )
```

---

### WR-03: Migration 0017 downgrade will violate the CHECK constraint if any `'fanned_out'` rows exist — no guard, no documented operator step

**File:** `backend/alembic/versions/0017_ingest_job_fanned_out_status.py:43-56`

**Issue:** The migration downgrade drops the new constraint and recreates the old one:

```python
def downgrade() -> None:
    # Revert to original constraint. Any rows with status='fanned_out'
    # must be manually updated before downgrade or they will violate the
    # constraint.
    op.execute("ALTER TABLE ... DROP CONSTRAINT ...")
    op.execute("ALTER TABLE ... ADD CONSTRAINT ... CHECK (status IN (...no fanned_out...))")
```

The comment acknowledges this, but the migration takes no action to prevent or handle it. Postgres will apply the new CHECK to existing rows at `ADD CONSTRAINT` time, and if any row has `status='fanned_out'` the constraint will fail and the downgrade will abort with an error. The comment says "must be manually updated before downgrade" but no SKIP-INVALID or pre-downgrade guard is included.

This is a latent operational hazard: any production system that has fanned out even one GPKG and then attempts a rollback will have a broken downgrade.

**Fix (option A — safe, immediate):** Add a pre-check that clears or resets fanned_out rows:

```python
def downgrade() -> None:
    # Reset any 'fanned_out' rows to 'complete' so the constraint can be applied.
    op.execute(
        "UPDATE catalog.ingest_jobs SET status = 'complete' WHERE status = 'fanned_out'"
    )
    op.execute("ALTER TABLE catalog.ingest_jobs DROP CONSTRAINT IF EXISTS chk_ingest_jobs_status")
    op.execute(
        "ALTER TABLE catalog.ingest_jobs ADD CONSTRAINT chk_ingest_jobs_status "
        "CHECK (status IN ('pending', 'running', 'complete', 'failed', 'cancelled'))"
    )
```

**Fix (option B — document):** If intentional data loss is unacceptable, replace the silent failure with an explicit pre-downgrade assertion that aborts cleanly with a message rather than a confusing PostgreSQL constraint error.

---

## Info

### IN-01: Duplicate `from datetime import datetime, timezone` in `commit_fan_out`

**File:** `backend/app/processing/ingest/router.py:695`

**Issue:** `datetime` and `timezone` are already imported at the module level (line 6: `from datetime import datetime, timezone`). Line 695 inside `commit_fan_out` adds a redundant local import:

```python
from datetime import datetime, timezone  # line 695 — already imported at module scope
```

This is dead import noise; the local import shadows (without effect) the module-level import.

**Fix:** Delete the redundant local import at line 695.

---

### IN-02: `formatNumber` called with potentially-null `feature_count` in `ReuploadDialog` file-layer table without null check at call site

**File:** `frontend/src/components/dataset/ReuploadDialog.tsx:771`

**Issue:** In the file-layer selection table (step `'selecting-file-layer'`), `layer.feature_count` is passed directly to `formatNumber`:

```tsx
<TableCell>{formatNumber(layer.feature_count)}</TableCell>
```

`LayerPreview.feature_count` is typed `int | None` on the backend, and `formatNumber` accepts `number | null | undefined` — so this is type-safe and will render "N/A" for null. However, the service-path table at line 701 shows an explicit null check before rendering:

```tsx
{layer.feature_count !== null ? formatNumber(layer.feature_count) : '-'}
```

The inconsistency between the two tables (dash vs. "N/A") for null feature counts will produce different fallback strings in the UI depending on which path the user takes. Neither is wrong, but it is inconsistent.

**Fix:** Use a consistent pattern. The file-layer table can match the service table with an explicit null check:

```tsx
<TableCell>
  {layer.feature_count !== null ? formatNumber(layer.feature_count) : '—'}
</TableCell>
```

---

_Reviewed: 2026-05-19T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Fixes Applied (2026-05-20)

All 7 findings fixed inline before Phase 1059. Commits on `main`:

| Finding | Commit | Status |
|---------|--------|--------|
| CR-01 | `ceb8f977` | fixed — `all_layers` stamped into `job.user_metadata` in `preview_file` |
| CR-02 | `f880868a` | fixed — job kept `'pending'` when all fan-out dispatches fail |
| WR-01 | `47fbea67` | fixed — `runWithConcurrency` dead code deleted from `UploadForm.tsx` |
| WR-02 | `6324d90b` | fixed — single-layer `layer_name` validation added to `reupload_preview` |
| WR-03 | `f17caf37` | fixed — migration downgrade pre-clears `fanned_out` rows before constraint |
| IN-01 | `07a01009` | fixed — redundant `from datetime import ...` local import removed |
| IN-02 | `9d112b06` | fixed — `feature_count` null fallback consistent with service-path table |

Regression tests for CR-01 added in `backend/tests/test_ingest_fan_out.py` (2 new tests in `TestCR01PreviewStampsAllLayers`).

**Verification:** `pytest tests/test_ingest_fan_out.py tests/test_reupload.py` — 42/42 passed. Frontend vitest 31/31 passed. `tsc --noEmit` 0 errors. `grep runWithConcurrency frontend/src` → 0 matches.
