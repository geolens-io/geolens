---
phase: 1058-multi-layer-gpkg-handling
verified: 2026-05-20T03:20:00Z
status: human_needed
score: 3/3 must-haves verified
overrides_applied: 0
gaps: []
deferred: []
human_verification:
  - test: "Open ReuploadDialog for a multi-layer GPKG dataset, upload multi-layer-gpkg.gpkg, and verify layer-select step renders with both 'buildings' and 'addresses' rows; 'buildings' is pre-selected; clicking Preview Layer transitions to preview pane showing 'Layer: buildings'; Confirm Re-Upload completes."
    expected: "Selecting-file-layer step appears (data-testid=reupload-file-layer-select), previous source_layer pre-highlighted, preview pane shows File + Layer lines, final IngestJob.source_layer = 'buildings'. Mirrors live MCP GPKG-01 acceptance from Phase 1060 checklist."
    why_human: "Requires live localhost:8080 with Playwright MCP (disconnected in this session, deferred to Phase 1060 close gate per objective scope)"
  - test: "In the Reupload preview pane after choosing a layer from a multi-layer GPKG, observe the schema-change advisory banner when columns differ."
    expected: "Preview pane shows 'File: {name}' and 'Layer: {chosen}' stacked vertically; advisory banner 'Schema differs from previous version: N columns added, M removed.' appears above SchemaDiffView when column sets differ; single-layer files show no Layer line and no banner when columns are identical."
    why_human: "Visual rendering and advisory-banner conditional display require live browser (Playwright MCP deferred to Phase 1060)"
  - test: "Upload multi-layer-gpkg.gpkg to Bulk Review, click 'Ingest all N layers as separate datasets', observe the results modal, verify N datasets appear in the catalog."
    expected: "Results modal shows per-layer checkmarks; catalog lists separate datasets named '{filename}: buildings' and '{filename}: addresses'; GET /jobs/{new_job_id} returns completed dataset_id for each layer within ~30s."
    why_human: "End-to-end fan-out path (POST /ingest/commit-fan-out → Procrastinate task → dataset creation) requires live stack with running worker (Playwright MCP + live API; deferred to Phase 1060)"
---

# Phase 1058: Multi-Layer GPKG Handling Verification Report

**Phase Goal:** A user reuploading a multi-layer GPKG dataset is shown a layer-select step and a schema-diff preview that mirrors the Service URL flow; a user importing a multi-layer GPKG through Bulk Review can choose to ingest all layers as separate datasets.
**Verified:** 2026-05-20T03:20:00Z
**Status:** human_needed — all 3 must-haves verified at source+test level; live MCP gates deferred to Phase 1060 per objective scope
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User reuploading a multi-layer GPKG via File path is shown a layer-select step before preview; chosen layer honored end-to-end; previous source_layer pre-selected as default | VERIFIED | `ReuploadDialog.tsx:58` (`'selecting-file-layer'` in `ReuploadStep`); `L126-128` state hooks; `L734` (`data-testid="reupload-file-layer-select"`); `L341-365` handler; `router_reupload.py:341,467` wire-up; `tasks_reupload.py:126,167` worker threading; 9 vitest tests (5 GPKG-01 + 4 GPKG-02 guard) all PASS |
| 2 | User viewing Reupload preview pane for multi-layer file sees explicit "Layer: {name}" line + column-level schema diff + schema-change warning when columns differ | VERIFIED | `ReuploadDialog.tsx:818-826` (two-line File+Layer header); `L836-843` (`hasSchemaChange` advisory banner, `data-testid="schema-change-advisory"`); `L457-461` (`schemaChangeCount`/`hasSchemaChange` derivation); `reupload.schemaChangeAdvisory` key present in all 4 locales (en:264, de:302, es:302, fr:302); 4 new GPKG-02 vitest tests PASS (19/19 total ReuploadDialog suite) |
| 3 | User dragging a multi-layer GPKG into Bulk Review can ingest every layer as a separate dataset via "Ingest all layers" fan-out path | VERIFIED | `BulkReviewList.tsx:173` (`onIngestAllLayers?` prop); `L367` (button conditional); `UploadForm.tsx:275` (`handleIngestAllLayers` single-call via `commitFanOut`); `router.py:680` (`POST /ingest/commit-fan-out/{job_id}`, 202 Accepted); `service.py:509` (`create_fan_out_jobs`); `schemas.py:491-549` (4 FanOut Pydantic models); migration 0017 adds `'fanned_out'` status; 4 BulkReviewList + 5 UploadForm fan-out vitest tests PASS |

**Score:** 3/3 truths verified at source+test level

### Deferred Items

No roadmap-level items deferred to later phases. Phase 1060 close gate is required for live MCP verification.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/modules/catalog/datasets/domain/schemas.py` | `ReuploadPreviewResponse.all_layers`, `.previous_source_layer`, `ReuploadCommitRequest.layer_name` | VERIFIED | L462: `all_layers: list[dict[str, Any]] | None = None`; L466: `previous_source_layer: str | None = None`; L481: `layer_name: str | None = Field(default=None, max_length=500)` |
| `backend/app/modules/catalog/datasets/api/router_reupload.py` | Preview accepts `layer_name` body; validates; surfaces `previous_source_layer`; commit persists `source_layer` | VERIFIED | L287-408: preview endpoint; L341 layer_name threading; L354-369 WR-02 validation (multi + single layer); L383-394 prior-job query; L406-408 response fields; L467 `job.source_layer = request.layer_name` |
| `backend/app/processing/ingest/tasks_reupload.py` | Worker reads `job.source_layer` and passes as `layer_name` to `run_ogrinfo` + `run_ogr2ogr` | VERIFIED | L126 `layer_name = job.source_layer`; L144 `run_ogrinfo(..., layer_name=layer_name)`; L167 `run_ogr2ogr(..., layer_name=layer_name)`; L214 `run_ogrinfo_preview(..., layer_name=layer_name)` |
| `backend/app/processing/ingest/router.py` | `POST /ingest/commit-fan-out/{job_id}` endpoint (CR-01 + CR-02 fixed) | VERIFIED | L680-759: full endpoint; L551-561 CR-01 fix stamps `all_layers` to `job.user_metadata` in `preview_file`; L747-757 CR-02 fix conditionally marks `'fanned_out'` only when `queued_count > 0` |
| `backend/app/processing/ingest/schemas.py` | `FanOutLayerRequest`, `FanOutCommitRequest`, `FanOutLayerResult`, `FanOutCommitResponse` | VERIFIED | L491-549: all 4 models with correct field constraints (`max_length=50` on layers list, `max_length=500` on `layer_name`) |
| `backend/app/processing/ingest/service.py` | `create_fan_out_jobs()` + `_user_safe_error()` | VERIFIED | L488-506: `_user_safe_error()` with regex path stripping; L509-614: `create_fan_out_jobs()` clones job, merges metadata, defers `ingest_file` task |
| `backend/alembic/versions/0017_ingest_job_fanned_out_status.py` | Migration extends CHECK constraint; WR-03 downgrade guard | VERIFIED | L27-40: upgrade (DROP + ADD with `'fanned_out'`); L43-60: downgrade with WR-03 fix (`UPDATE ... SET status='complete'` before constraint recreate) |
| `frontend/src/types/api.ts` | `ReuploadPreviewResponse.all_layers?`, `.previous_source_layer?`; `ReuploadCommitRequest.layer_name?`; `FanOutCommitResponse`; `FanOutLayerResult` | VERIFIED | L688: `all_layers?`; L689: `previous_source_layer?`; L702: `layer_name?`; L411-424: fan-out types |
| `frontend/src/components/dataset/ReuploadDialog.tsx` | `'selecting-file-layer'` step; `data-testid="reupload-file-layer-select"`; warning banner; Layer line; advisory banner | VERIFIED | L58: step type; L126-128: state hooks; L734 + testid; L741-744: missing-layer warning; L818-826: two-line header; L836-843: advisory banner |
| `frontend/src/components/import/BulkReviewList.tsx` | `onIngestAllLayers?` prop; button conditional | VERIFIED | L173: prop interface; L184: destructuring; L367: button block with guard `layers.length > 1 && onIngestAllLayers` |
| `frontend/src/components/import/UploadForm.tsx` | `handleIngestAllLayers` single `commitFanOut` call; results modal; `onIngestAllLayers` prop wired; `runWithConcurrency` dead code removed | VERIFIED | L4: `commitFanOut` import; L271-354: handler; L354: prop wired; WR-01 fix: `runWithConcurrency` absent (grep returns 0 matches) |
| `frontend/src/api/datasets.ts` | `commitFanOut()` client + `FanOutCommitResponse` + `FanOutLayerResult` types | VERIFIED | L411-424: types; L433-439: `commitFanOut` POSTs to `/ingest/commit-fan-out/${jobId}` |
| `e2e/fixtures/multi-layer-gpkg.gpkg` | 2-layer fixture (buildings + addresses, ~127KB) | VERIFIED | File exists at path, size 126976 bytes |
| `e2e/reupload-multi-layer-gpkg.spec.ts` | 2-scenario headless Playwright spec | VERIFIED | File exists, 10785 bytes |
| `backend/tests/test_reupload.py` | `TestReuploadMultiLayer` 4 tests | VERIFIED (via suite) | Full suite needs DB to run; test class structure confirmed in SUMMARY (26/26 reported PASS by executor) |
| `backend/tests/test_ingest_fan_out.py` | 14 tests (9 endpoint + 5 unit) | PARTIALLY VERIFIED | 5 `TestUserSafeError` unit tests PASS without DB; 9 integration tests ERROR on DB unavailability (local test DB not running) — this is an environment constraint, not a test-code defect |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `ReuploadDialog.tsx` selecting-file-layer step | `previewMutation.mutateAsync({ layerName })` | `handleFileLayerPreview` at L343 | WIRED | L343-365: handler sets `selectedFileLayer`, calls `previewMutation.mutateAsync` with `layerName`; L383 commits with `layerName: selectedFileLayer` |
| `router_reupload.py reupload_preview` | `run_ogrinfo_preview(file_path, layer_name=...)` | `layer_name = request.layer_name if request else None` at L341 | WIRED | L341-346: threading; L354-369: validation |
| `router_reupload.py reupload_commit` | `job.source_layer = request.layer_name` | `# GPKG-01 Phase 1058` at L467 | WIRED | L463-467 confirmed |
| `tasks_reupload._do_reupload_file` | `run_ogr2ogr(..., layer_name=...)` | `layer_name = job.source_layer` at L126 | WIRED | L126,144,167,214 confirmed |
| `UploadForm.handleIngestAllLayers` | `commitFanOut(jobId, layers)` | Single call replaces N per-layer commits | WIRED | L289: `const response = await commitFanOut(...)` |
| `router.py commit_fan_out` | `create_fan_out_jobs()` per layer | L743-745 loop | WIRED | Dispatches `ingest_file` Procrastinate task per layer |
| `preview_file` (ingest router) | `job.user_metadata["all_layers"]` stamped | CR-01 fix L556-561 | WIRED | Stamps `all_layers` so fan-out layer validation is non-empty |
| `commit_fan_out` conditional terminal | `job.status = "fanned_out"` only when `queued_count > 0` | CR-02 fix L750-756 | WIRED | Job stays `'pending'` on all-dispatch-failure for retry |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `ReuploadDialog.tsx` selecting-file-layer step | `allLayers` | `previewMutation` → `ReuploadPreviewResponse.all_layers` → `router_reupload.py` → `_extract_common_layer_metadata` | Yes — ogrinfo-sourced layer list | FLOWING |
| `ReuploadDialog.tsx` preview step Layer line | `selectedFileLayer` | State set from `handleFileLayerPreview` after user selection | Yes — user-selected, flows from ogrinfo layer list | FLOWING |
| `ReuploadDialog.tsx` advisory banner | `schemaChangeCount` | `preview.schema_diff.columns_added.length + columns_removed.length` | Yes — `compute_schema_diff()` in `router_reupload.py:371-377` | FLOWING |
| `BulkReviewList.tsx` "Ingest all layers" button | `entry.previewData.layers` | `FilePreviewResponse.layers` from `PreviewResponse.layers` (ingest `preview_file`) | Yes — ogrinfo-sourced | FLOWING |
| `UploadForm.handleIngestAllLayers` modal | `fanOutResults` | `commitFanOut()` → `FanOutCommitResponse.results[]` from backend | Yes — per-layer `status: queued|failed` | FLOWING |

---

## Behavioral Spot-Checks

Backend test DB is unavailable in this verification environment (test DB `geolens_test_*` not running). Integration tests that require DB are categorized as ENV-BLOCKED, not test failures.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `_user_safe_error()` strips paths | `uv run pytest tests/test_ingest_fan_out.py::TestUserSafeError -q` | 5/5 PASS | PASS |
| ogr.py guard populates `all_layers` when `len > 1` | Source inspection L251 | `if len(layers) > 1:` (no `and not layer_name`) | PASS |
| `runWithConcurrency` removed (WR-01) | `grep runWithConcurrency frontend/src/...` | 0 matches | PASS |
| TypeScript typecheck | `npx tsc --noEmit` | 0 errors (empty output) | PASS |
| Frontend vitest full suite | `npm test -- --run` | 2053/2053 PASS | PASS |
| i18n parity (4 locales) | `npm run test:i18n` | 2/2 PASS | PASS |

---

## Probe Execution

No phase-declared probes. Step 7c: SKIPPED (no `probe-*.sh` files for this phase; integration probes deferred to Phase 1060).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| GPKG-01 | 1058-01 | Layer-select step on File reupload path; layer honored end-to-end | SATISFIED | `ReuploadDialog.tsx` state machine; backend plumbing confirmed; 9 vitest tests |
| GPKG-02 | 1058-02 | Layer line + schema diff advisory in preview pane | SATISFIED | `schemaChangeAdvisory` in ReuploadDialog + all 4 locale files; 4 vitest tests |
| GPKG-03 | 1058-03 + 1058-04 | Bulk Review "Ingest all layers" fan-out | SATISFIED | `BulkReviewList` button; `UploadForm.handleIngestAllLayers`; `/ingest/commit-fan-out` endpoint; migration 0017; 9 vitest tests |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/tests/test_ingest_ogr_pure.py` | 405 | `assert meta["all_layers"] is None` — assertion now fails because Plan 01 changed the `all_layers` guard in `_extract_common_layer_metadata` from `len > 1 and not layer_name` to `len > 1` | WARNING | Test `test_multi_layer_picks_named_layer` FAILS (1 failure in 80 tests). The Plan 04 SUMMARY classified this as "Pre-existing Failures (Out of Scope)" but it was introduced by Plan 01's intentional guard change. The test should have been updated alongside the guard change. The test comment says "all_layers is None when a specific layer was requested" — this invariant no longer holds by design. The test needs updating to assert `meta["all_layers"]` is a non-null list when `len > 1`. |

**Debt marker gate:** No TBD/FIXME/XXX markers found in any Phase 1058-modified files. Gate: PASS.

---

## Human Verification Required

### 1. GPKG-01 Live: Layer-Select Step in ReuploadDialog

**Test:** Log in to localhost:8080 as admin. Find a dataset originally ingested from a single-layer file. Open "More" → "Re-Upload" → "File". Upload `e2e/fixtures/multi-layer-gpkg.gpkg`. Observe the dialog state.
**Expected:** Dialog transitions to a step showing a table with "buildings" and "addresses" rows. If the original dataset was ingested from a GPKG with `source_layer="buildings"`, the "buildings" row is pre-selected (highlighted) and the Preview Layer button is enabled without further clicks. Click Preview Layer, confirm the preview pane shows both "File: multi-layer-gpkg.gpkg" and "Layer: buildings" lines. Click Confirm Re-Upload and verify the job completes.
**Why human:** Requires live localhost:8080 + Playwright MCP (disconnected in this session). Deferred to Phase 1060 GPKG-01 re-verify item.

### 2. GPKG-02 Live: Schema-Change Advisory in Preview Pane

**Test:** Complete the GPKG-01 live test above. After choosing a layer, observe the preview pane content.
**Expected:** When the newly uploaded file's chosen layer has different columns from the existing dataset: a yellow/warning-toned advisory banner reading "Schema differs from previous version: N columns added, M removed." appears above the SchemaDiffView component. When columns are identical: no advisory banner. The existing red "Warning: This re-upload includes schema changes" text (hasWarning) can coexist with the advisory banner.
**Why human:** Conditional advisory banner rendering requires live DOM observation. Deferred to Phase 1060 GPKG-02 re-verify item.

### 3. GPKG-03 Live: "Ingest all layers" Fan-Out in Bulk Review

**Test:** In the Import panel, drag `e2e/fixtures/multi-layer-gpkg.gpkg` into the upload area. After preview completes (both "buildings" and "addresses" shown), click "Ingest all 2 layers as separate datasets". Observe the results modal. Wait ~30 seconds, then check the catalog.
**Expected:** Results modal appears listing two rows: "buildings: succeeded" and "addresses: succeeded" (both with CheckCircle2 icon). Catalog shows two new datasets named approximately "multi-layer-gpkg: buildings" and "multi-layer-gpkg: addresses". Single-layer files continue to show the standard single-commit affordance without the new button.
**Why human:** Full fan-out path (POST /ingest/commit-fan-out → Procrastinate tasks → _finalize_ingest → dataset creation) requires live stack with running worker process. Deferred to Phase 1060 GPKG-03 re-verify item.

---

## Test Regression Note

`backend/tests/test_ingest_ogr_pure.py::TestExtractCommonLayerMetadata::test_multi_layer_picks_named_layer` FAILS in the current codebase (1 failure, 79 pass in the 80-test file). This was caused by Phase 1058 Plan 01's intentional change to `_extract_common_layer_metadata` in `ogr.py`: the guard changed from `if len(layers) > 1 and not layer_name:` to `if len(layers) > 1:` so `all_layers` is always populated for multi-layer sources regardless of whether a specific layer was targeted. The test's comment ("all_layers is None when a specific layer was requested") documents the old invariant that Plan 01 deliberately broke.

The test needs to be updated: the assert at line 405 should become `assert meta["all_layers"] is not None` with a check that both layers appear in the list. This is a WARNING-level issue: the test failure is a documentation/regression-pin failure, not a functional defect. The production code behavior is correct and intentional. The failing test does not block Phase 1059.

---

## Gaps Summary

No blocking gaps. All 3 success criteria are met at source + Vitest + TypeScript level. The one anti-pattern (test regression in `test_ingest_ogr_pure.py`) is a WARNING — the test was not updated to match the intentional guard change in `ogr.py`. This should be fixed before Phase 1060 tagging.

---

## Scope Guardrail Audit

| Guardrail | Status | Evidence |
|-----------|--------|---------|
| D-12: No FileGDB/KML multi-layer support added | CLEAN | grep for `.gdb`, `FileGDB`, `KML` in modified files: 0 matches |
| D-13: No schema transformation (informational only) | CLEAN | Advisory banner is display-only; no column migration logic added |
| D-14: No changes to Service URL Reupload flow | CLEAN | `router_reupload.py` service-URL endpoints unchanged; Service URL layer-select step in `ReuploadDialog.tsx` untouched; `'layer-select'` step distinct from new `'selecting-file-layer'` |

---

*Verified: 2026-05-20T03:20:00Z*
*Verifier: Claude (gsd-verifier)*
