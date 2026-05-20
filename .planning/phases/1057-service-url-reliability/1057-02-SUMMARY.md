---
phase: 1057-service-url-reliability
plan: "02"
subsystem: backend-probe + frontend-import
tags: [probe, ogcapi, wfs, classification, kind, ogrinfo, performance]
dependency_graph:
  requires: [1057-01]
  provides: [probe-kind-field, no-ogrinfo-probe-enrichment]
  affects:
    - backend/app/modules/catalog/sources/schemas.py
    - backend/app/modules/catalog/sources/classify.py
    - backend/app/modules/catalog/sources/probe.py
    - backend/app/modules/catalog/sources/adapters/ogcapi.py
    - backend/app/modules/catalog/sources/adapters/wfs.py
    - frontend/src/types/api.ts
    - frontend/src/components/import/ServiceUrlForm.tsx
    - backend/tests/test_probe_classification.py
tech_stack:
  added: []
  patterns:
    - classify_layer_kind-pure-function
    - d05-probe-returns-null-geometry-lazy-enrich-at-preview
    - d09-kind-literal-pydantic-default
key_files:
  created:
    - backend/app/modules/catalog/sources/classify.py
    - backend/tests/test_probe_classification.py
  modified:
    - backend/app/modules/catalog/sources/schemas.py
    - backend/app/modules/catalog/sources/probe.py
    - backend/app/modules/catalog/sources/adapters/ogcapi.py
    - backend/app/modules/catalog/sources/adapters/wfs.py
    - frontend/src/types/api.ts
    - frontend/src/components/import/ServiceUrlForm.tsx
    - backend/tests/test_services_wfs_pure.py
    - frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx
decisions:
  - "D-04: orchestrator short-circuit was already correct; bottleneck was enrich_ogcapi_layers / enrich_wfs_layers (per-layer ogrinfo subprocess)"
  - "D-05: dropped ogrinfo enrichment from probe phase entirely; geometry_type=None/feature_count=None at probe time; lazy-enrich at preview time"
  - "D-09: classify_layer_kind helper implements raster rule (stac adapter, geometry_type contains raster, coverage_format/bands/image/* link)"
  - "D-10: ServiceUrlForm.tsx reads layer.kind directly instead of re-deriving from geometry_type string"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-20"
  tasks_completed: 3
  tasks_total: 3
---

# Phase 1057 Plan 02: PROBE-05 + CLASS-07 Paired Fix Summary

**One-liner:** Drop per-layer ogrinfo enrichment from probe phase (≤5s target trivially achievable) and add backend-classified `kind: 'vector' | 'raster'` field to probe response so frontend stops re-deriving VEC/RAS from geometry_type string contents.

## What Was Built

### Task 1 — `kind` field + `classify_layer_kind` helper (TDD)

**`backend/app/modules/catalog/sources/schemas.py`**
- Added `kind: Literal['vector', 'raster'] = Field(default='vector', ...)` to `LayerInfo` after existing fields
- Added `from typing import Literal` import
- Field description references D-09 + Phase 1057 CLASS-07

**`backend/app/modules/catalog/sources/classify.py`** (new file)
- `classify_layer_kind(layer: dict, adapter_type: Literal['wfs', 'ogcapi', 'arcgis', 'stac']) -> Literal['vector', 'raster']`
- Five D-09 raster signals in priority order: (1) stac adapter, (2) geometry_type contains 'raster', (3) coverage_format truthy, (4) bands truthy, (5) any link.type startswith 'image/'
- Defensive: `links` must be a list (malformed responses return 'vector')
- Docstring references D-09, Phase 1057 CLASS-07, and the four invariant inputs

**`backend/tests/test_probe_classification.py`** (new file, TestClassifyLayerKind — 20 tests)
- STAC adapter → raster (2 tests)
- geometry_type containing 'raster' parametrized (5 cases)
- raster signal fields (coverage_format/bands/links) parametrized (6 cases, includes edge case for empty coverage_format → vector)
- Null geometry_type OGC API → vector
- WFS layer → vector
- ArcGIS FeatureServer → vector
- LayerInfo Pydantic default kind='vector'
- LayerInfo rejects kind='invalid' (Literal enforcement)
- Non-image link type → vector
- Malformed links (dict not list) → vector

### Task 2 — Drop ogrinfo enrichment; emit kind at adapter layer-build sites (TDD)

**`backend/app/modules/catalog/sources/adapters/ogcapi.py`**
- `enrich_ogcapi_layers` function **deleted entirely** (was 78 lines of per-layer ogrinfo subprocess logic with Semaphore(5) + 30s wait_for)
- Layer dict construction in `probe_ogcapi` updated: adds `"geometry_type": None`, `"feature_count": None`, `"kind": classify_layer_kind(c, adapter_type="ogcapi")` at build time
- Raw collection dict `c` is passed to `classify_layer_kind` so D-09 raster signals (coverage_format/bands/image/* mediaType) can fire from the OGC API collection JSON
- Module docblock rewritten to explain Phase 1057 D-05 rationale
- Removed `asyncio`, `json`, `os` imports (only used by deleted function)
- Added `from app.modules.catalog.sources.classify import classify_layer_kind`

**`backend/app/modules/catalog/sources/adapters/wfs.py`**
- `enrich_wfs_layers` function **deleted entirely** (was 89 lines of per-layer ogrinfo subprocess logic with Semaphore(5) + asyncio.wait_for(60))
- Layer dict construction in `parse_wfs_capabilities` updated: adds `"geometry_type": None`, `"feature_count": None`, `"kind": "vector"` to every WFS layer (WFS is always vector by OGC spec — no classify_layer_kind call needed)
- Module docblock updated with Phase 1057 D-05 note
- Removed `asyncio`, `json`, `os` imports

**`backend/app/modules/catalog/sources/probe.py`**
- Removed `enrich_ogcapi_layers` and `enrich_wfs_layers` from import
- All four call sites for these functions replaced with direct pass-through using `result["layers"]` (layers already have correct shape from adapter)
- `_build_probe_response` parameter renamed from `enriched_layers` to `layers`; now passes `kind=layer.get("kind", "vector")` to `LayerInfo`
- ArcGIS `enrich_arcgis_feature_counts` calls **preserved** (HTTP-based, not ogrinfo, not the bottleneck)
- Module docblock added explaining D-04 (per-probe short-circuit was already correct) and D-05 (enrichment dropped)

**`backend/tests/test_probe_classification.py`** (TestProbeOrchestratorNoEnrichment — 5 tests added)
- Wall-clock test: 17-collection OGC API probe completes <100ms (mocked HTTP, no subprocess)
- OGC API layers have geometry_type=None, feature_count=None, kind='vector'
- WFS layers have geometry_type=None, feature_count=None, kind='vector'
- Structural assertion: `enrich_ogcapi_layers` not in probe.py namespace (deleted — D-05 confirmed)
- ArcGIS enrichment mock spy: `enrich_arcgis_feature_counts` still called once

**`backend/tests/test_services_wfs_pure.py`** (auto-fix)
- Updated exact-dict assertion at line 41 to include the new `geometry_type`, `feature_count`, `kind` keys that `parse_wfs_capabilities` now returns

### Task 3 — Frontend LayerInfo mirror + ServiceUrlForm.tsx wire-up (TDD)

**`frontend/src/types/api.ts`**
- `LayerInfo` interface: added `kind: 'vector' | 'raster'` as a required (non-optional) field
- Inline JSDoc references Phase 1057 CLASS-07 D-09 / D-10 and explains the classification rule

**`frontend/src/components/import/ServiceUrlForm.tsx`** (line 197 site)
- Replaced: `const isVector = layer.geometry_type && !layer.geometry_type.toLowerCase().includes('raster');`
- With: `<TypeTag kind={layer.kind} size="sm" />` (direct one-deref consumption per D-10)
- Added inline comment referencing D-10 + Phase 1057

**`frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx`** (auto-fix)
- Added `kind: 'vector' as const` to both `LayerInfo` fixture objects that were missing the now-required field

## Enrichment Status

| Adapter | Before | After | Reason |
|---------|--------|-------|--------|
| OGC API | `enrich_ogcapi_layers` called (Semaphore×N×~3-4s) | **Deleted** | D-05: lazy-enrich at preview time |
| WFS | `enrich_wfs_layers` called (Semaphore×N×~3-4s) | **Deleted** | D-05: lazy-enrich at preview time |
| ArcGIS | `enrich_arcgis_feature_counts` called | **Preserved** | HTTP-based (returnCountOnly), not ogrinfo |

## Test Results

**Backend (`test_probe_classification.py`):** 25/25 PASS
- TestClassifyLayerKind: 20 tests
- TestProbeOrchestratorNoEnrichment: 5 tests

**Backend (existing tests):** 17/17 PASS
- `test_ingest_service_geometry_type.py`: 6 tests (Plan 01, unaffected)
- `test_services_wfs_pure.py`: 11 tests (auto-fix for new layer dict shape)

**Frontend typecheck:** 0 new errors introduced (33 pre-existing unrelated errors unchanged)

## Performance Impact

The ≤5s probe target is now trivially achievable without measuring. The unit test `test_ogcapi_probe_completes_fast_without_subprocess` confirms a 17-collection probe completes in <100ms with mocked HTTP (no subprocess). Live wall-clock measurement against `demo.pygeoapi.io/master` deferred to Phase 1060 (Close Gate) per plan's verification section.

**Before (pre-fix):** `demo.pygeoapi.io/master` ~63s wall-clock (17 collections × ~3-4s ogrinfo each with Semaphore(5))
**After (post-fix):** Bounded by HTTP latency only — landing page + `/collections` fetch ≈ 1-2 round-trips

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed failing existing WFS pure test (test_services_wfs_pure.py)**
- **Found during:** Task 2 verification
- **Issue:** `TestParseWfsCapabilities::test_wfs_1_1_namespace` did an exact-dict equality check against `{"name": ..., "title": ..., "crs": ...}`. After adding `geometry_type`, `feature_count`, `kind` to layer dicts in `parse_wfs_capabilities`, the assertion failed.
- **Fix:** Updated test assertion to include the new fields with their expected values (`geometry_type: None`, `feature_count: None`, `kind: 'vector'`)
- **Files modified:** `backend/tests/test_services_wfs_pure.py`
- **Commit:** 908d868c

**2. [Rule 1 - Bug] Fixed new TypeScript error in ReuploadDialog.test.tsx**
- **Found during:** Task 3 typecheck
- **Issue:** Two `LayerInfo` fixture objects in `ReuploadDialog.test.tsx` were missing the now-required `kind` field, causing `TS2741: Property 'kind' is missing in type`.
- **Fix:** Added `kind: 'vector' as const` to both fixture objects.
- **Files modified:** `frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx`
- **Commit:** 41e2c617

**3. [Rule 1 - Minor] Mock response fix in orchestrator tests**
- **Found during:** Task 2 GREEN phase (test run)
- **Issue:** `httpx.Response(200, json=data)` without a `request` attached causes `RuntimeError` when `raise_for_status()` is called inside `probe_ogcapi`.
- **Fix:** Added `_make_response()` helper method that creates responses with `httpx.Request("GET", url)` attached. Also updated `test_enrich_ogcapi_layers_not_called` to use a structural assertion (checking probe.py namespace) rather than a mock patch (more robust since the function was deleted).
- **Files modified:** `backend/tests/test_probe_classification.py`
- **Commit:** 908d868c

## Known Stubs

None — no placeholder data or hardcoded values introduced. Probe responses now return `geometry_type=None`/`feature_count=None` as documented values (not stubs — the lazy-enrich at preview time populates them when the user selects a layer).

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers. `classify_layer_kind` operates on already-fetched JSON via pure-Python value reads (no eval, no subprocess, no SQL). Removing `enrich_ogcapi_layers` and `enrich_wfs_layers` from the probe phase **reduces** attack surface by eliminating per-layer subprocess invocations (T-1057B-04 accepted).

## Self-Check: PASSED

- `backend/app/modules/catalog/sources/classify.py` exists: FOUND
- `backend/app/modules/catalog/sources/schemas.py` contains `kind: Literal`: FOUND
- `backend/app/modules/catalog/sources/probe.py` — no `await enrich_ogcapi_layers` or `await enrich_wfs_layers` calls: CONFIRMED
- `backend/app/modules/catalog/sources/probe.py` — `enrich_arcgis_feature_counts` still called: CONFIRMED (lines 129, 167)
- `backend/tests/test_probe_classification.py` exists with 25 tests: FOUND
- `frontend/src/types/api.ts` `LayerInfo` has `kind: 'vector' | 'raster'`: FOUND
- `frontend/src/components/import/ServiceUrlForm.tsx` — no `geometry_type.*toLowerCase.*raster`: CONFIRMED
- Commit `3fc93b5a` (Task 1 — schemas + classify + tests): FOUND
- Commit `908d868c` (Task 2 — probe + adapters + orchestrator tests): FOUND
- Commit `41e2c617` (Task 3 — frontend types + ServiceUrlForm): FOUND
