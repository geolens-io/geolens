---
phase: 1058-multi-layer-gpkg-handling
plan: "01"
subsystem: backend-reupload + frontend-reupload-dialog
tags: [reupload, gpkg, multi-layer, layer-select, state-machine, ogrinfo, ogr2ogr, playwright]

requires:
  - phase: 1057-service-url-reliability
    provides: "ReuploadDialog layer-select design reference (existing 'layer-select' step for Service URL)"

provides:
  - "ReuploadPreviewResponse.all_layers and .previous_source_layer fields (backend schema + frontend type)"
  - "ReuploadPreviewRequest schema with optional layer_name (max_length=500)"
  - "ReuploadCommitRequest.layer_name field for persisting user-chosen layer to IngestJob.source_layer"
  - "reupload_preview endpoint accepts optional body with layer_name; validates layer; surfaces previous_source_layer"
  - "reupload_commit endpoint persists request.layer_name to job.source_layer (D-03)"
  - "_do_reupload_file worker threads layer_name into run_ogrinfo + run_ogr2ogr + run_ogrinfo_preview"
  - "ReuploadDialog 'selecting-file-layer' step: layer-select table + missing-layer warning (D-02)"
  - "e2e/fixtures/multi-layer-gpkg.gpkg (2-layer GPKG: buildings + addresses)"
  - "e2e/reupload-multi-layer-gpkg.spec.ts (2 headless scenarios)"

affects:
  - 1058-02 (GPKG-02 preview pane polish depends on all_layers/previous_source_layer contract)
  - 1060-close-gate (live MCP re-verify exercises selecting-file-layer step)

tech-stack:
  added: []
  patterns:
    - "selecting-file-layer vs layer-select disambiguation: file-path uses 'selecting-file-layer' to avoid colliding with existing service-URL 'layer-select' step"
    - "needsLayerSelect trigger: show step when all_layers.length > 1 OR (any layers AND previous_source_layer missing from new file)"
    - "T-1058A-03 layer_name validation: validate against all_layers in preview endpoint before passing to subprocess"
    - "previous_source_layer sourced from latest completed IngestJob.source_layer (NOT Dataset.source_layer which doesn't exist)"

key-files:
  created:
    - "backend/app/modules/catalog/datasets/domain/schemas.py (ReuploadPreviewRequest class)"
    - "e2e/fixtures/multi-layer-gpkg.gpkg"
    - "e2e/reupload-multi-layer-gpkg.spec.ts"
  modified:
    - "backend/app/modules/catalog/datasets/domain/schemas.py (ReuploadPreviewResponse + ReuploadCommitRequest)"
    - "backend/app/modules/catalog/datasets/api/router_reupload.py (preview + commit endpoints)"
    - "backend/app/processing/ingest/ogr.py (_extract_common_layer_metadata guard)"
    - "backend/app/processing/ingest/tasks_reupload.py (_do_reupload_file layer_name threading)"
    - "backend/tests/test_reupload.py (TestReuploadMultiLayer + mock fixture extension)"
    - "frontend/src/types/api.ts (ReuploadPreviewResponse + ReuploadCommitRequest)"
    - "frontend/src/api/datasets.ts (reuploadPreview + reuploadCommit layerName param)"
    - "frontend/src/components/dataset/hooks/use-dataset.ts (hook layerName threading)"
    - "frontend/src/components/dataset/ReuploadDialog.tsx (selecting-file-layer step)"
    - "frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx (5 new tests)"
    - "frontend/src/i18n/locales/en/dataset.json"
    - "frontend/src/i18n/locales/de/dataset.json"
    - "frontend/src/i18n/locales/es/dataset.json"
    - "frontend/src/i18n/locales/fr/dataset.json"
    - "package.json (e2e:smoke:reupload script)"

key-decisions:
  - "Step named 'selecting-file-layer' (not 'layer-select') to avoid collision with existing service URL step"
  - "needsLayerSelect also triggers for previous_source_layer mismatch on 1-layer files (user must confirm layer swap)"
  - "previous_source_layer sourced from latest completed IngestJob.source_layer, not Dataset.source_layer"
  - "all_layers guard in _extract_common_layer_metadata changed from 'len>1 AND NOT layer_name' to 'len>1' always"
  - "i18n namespace: reupload.fileLayer.* (sibling to reupload.service.*) — 'reupload.file' was already a string key"
  - "T-1058A-03: validate layer_name against all_layers in preview endpoint (HTTP 422 if not found)"

requirements-completed:
  - GPKG-01

duration: 75min
completed: 2026-05-20
---

# Phase 1058 Plan 01: GPKG-01 P0 Reupload File Path Layer-Select Summary

**End-to-end layer_name plumbing from ReuploadDialog 'selecting-file-layer' step through preview + commit endpoints into the reupload worker, closing the silent-data-swap bug for multi-layer GPKG files**

## Performance

- **Duration:** ~75 min
- **Started:** 2026-05-20T01:30:00Z
- **Completed:** 2026-05-20T02:08:00Z
- **Tasks:** 3
- **Files modified:** 16

## Accomplishments

- Backend: `ReuploadPreviewResponse` exposes `all_layers` + `previous_source_layer`; preview endpoint accepts `layer_name` body; commit persists `layer_name` to `IngestJob.source_layer`; worker threads `layer_name` into every `run_ogrinfo*` + `run_ogr2ogr` call
- Frontend: New `'selecting-file-layer'` step in ReuploadDialog state machine; missing-layer warning (D-02); pre-selection from `previous_source_layer`; full i18n parity across en/de/es/fr
- Tests: 4 new backend tests (TestReuploadMultiLayer); 5 new frontend vitest tests; 2-scenario headless Playwright spec; all gates green

## Task Commits

1. **Task 1: Backend wire-up** - `c4ac3a3b` (feat)
2. **Task 2: Frontend wire-up** - `3f2951b3` (feat)
3. **Task 3: E2E Playwright spec + fixture** - `8853a0ef` (feat)

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/schemas.py` — ReuploadPreviewRequest (new), ReuploadPreviewResponse.all_layers + .previous_source_layer, ReuploadCommitRequest.layer_name
- `backend/app/modules/catalog/datasets/api/router_reupload.py` — preview accepts body, validates layer_name, queries prior IngestJob; commit persists source_layer
- `backend/app/processing/ingest/ogr.py` — `_extract_common_layer_metadata` always populates all_layers when len > 1
- `backend/app/processing/ingest/tasks_reupload.py` — snapshots `layer_name = job.source_layer`; passes to run_ogrinfo + run_ogr2ogr + run_ogrinfo_preview
- `backend/tests/test_reupload.py` — TestReuploadMultiLayer (4 tests); mock fixture extended with `all_layers: None` default
- `frontend/src/types/api.ts` — `all_layers?`, `previous_source_layer?` on ReuploadPreviewResponse; `layer_name?` on ReuploadCommitRequest
- `frontend/src/api/datasets.ts` — `reuploadPreview(layerName?)` and `reuploadCommit(layerName?)` params
- `frontend/src/components/dataset/hooks/use-dataset.ts` — hooks accept `layerName?` in mutation arg shape
- `frontend/src/components/dataset/ReuploadDialog.tsx` — 'selecting-file-layer' step; missing-layer warning; handleFileLayerPreview; selectedFileLayer threaded to commit
- `frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx` — 5 new multi-layer tests
- `frontend/src/i18n/locales/{en,de,es,fr}/dataset.json` — `reupload.fileLayer.*` keys + `reupload.descriptions.fileLayerSelect`
- `e2e/reupload-multi-layer-gpkg.spec.ts` — 2-scenario headless Playwright spec
- `e2e/fixtures/multi-layer-gpkg.gpkg` — 127KB 2-layer GPKG (buildings + addresses, both Point)
- `package.json` — `e2e:smoke:reupload` script

## Decisions Made

- **Step naming:** `'selecting-file-layer'` not `'layer-select'` — service URL path already uses `'layer-select'`; collision would break both flows.
- **needsLayerSelect trigger:** Shows the step not only for multi-layer files (>1 layers) but also for 1-layer files where `previous_source_layer` is set but absent from the new file. This is more correct than the plan's "only >1 layers" text — a 1-layer file can still swap layers by rename, and the user must confirm.
- **i18n namespace:** `reupload.fileLayer.*` instead of `reupload.file.*` — `reupload.file` is already a string key (`"File:"`) in all locales; turning it into an object would break existing usage.
- **all_layers guard:** Changed from `len(layers) > 1 AND NOT layer_name` to `len(layers) > 1` in `_extract_common_layer_metadata`. This ensures `all_layers` is populated for the layer-select UI even after a targeted preview call.
- **previous_source_layer source:** Sourced from the most-recent completed `IngestJob.source_layer` (DESC order on `completed_at`), filtered by `status == 'complete'` and `source_layer IS NOT NULL`. Confirmed: `Dataset.source_layer` column does not exist on the Dataset model.
- **T-1058A-03 validation:** Preview endpoint validates `layer_name` appears in `all_layers` before calling subprocess — returns HTTP 422 with named layer if missing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture used fake GPKG bytes that failed content validation**
- **Found during:** Task 1 (backend tests)
- **Issue:** `b"FAKE_GPKG_CONTENT"` does not pass puremagic SQLite magic-byte validation for `.gpkg` files; endpoint returned HTTP 422 before the mock ran
- **Fix:** Changed test fixture uploads to use `.geojson` with valid JSON content (matching the existing test pattern)
- **Files modified:** `backend/tests/test_reupload.py`
- **Committed in:** c4ac3a3b (Task 1 commit)

**2. [Rule 2 - Missing Critical] needsLayerSelect extended to cover 1-layer files with missing previous_source_layer**
- **Found during:** Task 2 (frontend tests — test (d) failed)
- **Issue:** Plan said "Triggered when all_layers.length > 1" but test (d) expected the step to appear for a 1-layer file where `previous_source_layer` is missing. Without this guard, the user has no way to confirm a layer-name change when a file's single layer doesn't match the prior one.
- **Fix:** Updated `needsLayerSelect` to also trigger when `layers.length >= 1 AND previous_source_layer set AND not in layers`
- **Files modified:** `frontend/src/components/dataset/ReuploadDialog.tsx`
- **Committed in:** 3f2951b3 (Task 2 commit)

**3. [Rule 3 - Blocking] i18n namespace conflict — reupload.file is a string**
- **Found during:** Task 2 (i18n key design)
- **Issue:** `reupload.file` already exists as a string key (`"File:"`) in all 4 locale files; adding sub-keys would break existing `t('reupload.file')` usage in the dialog
- **Fix:** Used `reupload.fileLayer.*` namespace instead; updated JSX keys and all locale files consistently
- **Files modified:** `frontend/src/components/dataset/ReuploadDialog.tsx`, `frontend/src/i18n/locales/{en,de,es,fr}/dataset.json`
- **Committed in:** 3f2951b3 (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 Rule 1 bug, 1 Rule 2 missing critical, 1 Rule 3 blocking)
**Impact on plan:** All fixes necessary for correctness. No scope creep.

## Threat Surface Scan

Changes tracked in plan's `<threat_model>`. No new surfaces beyond what was planned:

| Threat ID | Disposition | Implemented |
|-----------|-------------|-------------|
| T-1058A-01 | mitigate | Pydantic `max_length=500` on `layer_name` in both `ReuploadPreviewRequest` and `ReuploadCommitRequest` |
| T-1058A-02 | mitigate | `asyncio.create_subprocess_exec(*cmd)` — argv list, no shell expansion |
| T-1058A-03 | mitigate | Preview endpoint validates `layer_name` in `all_layers`; HTTP 422 if absent |
| T-1058A-04 | accept | `previous_source_layer` is dataset-scoped metadata; no cross-tenant risk |
| T-1058A-05 | mitigate | This plan IS the fix — `IngestJob.source_layer` persisted on every reupload |

No new network endpoints, auth paths, or file-access patterns beyond plan scope.

## Known Stubs

None — all new state machine branches are fully wired. `selectedFileLayer` flows from UI selection through `handleFileLayerPreview` into the second `previewMutation` call and then into `handleConfirm` → `commitMutation` → backend `reupload_commit` → `job.source_layer`. Worker reads `job.source_layer` in Phase 1 of `_do_reupload_file`.

## Issues Encountered

- Docker `docker cp` could not copy from the container path due to a container filesystem quirk; worked around using base64 encoding (`cat file | base64` → `base64 -D`).
- Playwright `getAuthToken()` in Scenario B needed a fallback to browser-based dataset discovery (via `page.locator`) when direct API calls returned empty results in the test runner context.

## Test Results

| Gate | Result | Count |
|------|--------|-------|
| Backend pytest `tests/test_reupload.py` | PASS | 26/26 (22 pre-existing + 4 new TestReuploadMultiLayer) |
| Frontend vitest `ReuploadDialog` | PASS | 14/14 (9 pre-existing + 5 new multi-layer) |
| TypeScript typecheck | PASS | 0 errors |
| i18n parity (`npm run test:i18n`) | PASS | 2/2 |
| Headless Playwright e2e | PASS | 3/3 (1 setup + 2 scenarios) |

## Self-Check

**Created files:**
- `/Users/ishiland/Code/geolens/e2e/fixtures/multi-layer-gpkg.gpkg` — FOUND
- `/Users/ishiland/Code/geolens/e2e/reupload-multi-layer-gpkg.spec.ts` — FOUND
- `/Users/ishiland/Code/geolens/.planning/phases/1058-multi-layer-gpkg-handling/1058-01-SUMMARY.md` — (this file)

**Commits:**
- `c4ac3a3b` — FOUND (feat 1058-01 backend)
- `3f2951b3` — FOUND (feat 1058-01 frontend)
- `8853a0ef` — FOUND (feat 1058-01 e2e)

## Self-Check: PASSED

## Next Phase Readiness

- Plan 1058-02 (GPKG-02): preview pane polishing — depends on `all_layers` + `previous_source_layer` fields now available on `ReuploadPreviewResponse`. The `selecting-file-layer` step exposes `selectedFileLayer` to the preview pane via `previewSourceLabel`/`previewSourceValue`.
- Plan 1058-03 (GPKG-03): Bulk Review ingest-all-layers fan-out — independent of Plan 01 surfaces; touches `BulkReviewList.tsx` only.
- Phase 1060 close gate: live MCP re-verify will exercise the `selecting-file-layer` step against `localhost:8080` using the `e2e/fixtures/multi-layer-gpkg.gpkg` fixture.

---
*Phase: 1058-multi-layer-gpkg-handling*
*Completed: 2026-05-20*
