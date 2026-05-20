---
phase: 1057-service-url-reliability
plan: "03"
subsystem: backend-ingest + frontend-import
tags: [crs, uri-parsing, ogcapi, wfs, ogr, regex, tdd]
dependency_graph:
  requires: [1057-01]
  provides: [uri-urn-crs-parsing, crs-override-auto-hide]
  affects:
    - backend/app/modules/catalog/sources/crs_uri.py
    - backend/app/processing/ingest/ogr.py
    - backend/tests/test_crs_uri_parsing.py
    - frontend/src/components/import/ImportMetadataForm.tsx
    - frontend/src/components/import/__tests__/ImportMetadataForm.test.tsx
tech_stack:
  added: []
  patterns:
    - compiled-regex-allowlist-for-uri-parsing
    - third-fallback-guard-in-extract_srid_from_json
    - d08-crs-override-auto-hide-option-b
key_files:
  created:
    - backend/app/modules/catalog/sources/crs_uri.py
    - backend/tests/test_crs_uri_parsing.py
  modified:
    - backend/app/processing/ingest/ogr.py
    - frontend/src/components/import/ImportMetadataForm.tsx
    - frontend/src/components/import/__tests__/ImportMetadataForm.test.tsx
decisions:
  - "D-07: four URI/URN forms covered via allowlist regex; unrecognised URIs return None"
  - "D-08 option B: show read-only EPSG confirmation when detectedCrs non-null; editable input hidden"
  - "D-14: helper placed in shared utility module (crs_uri.py) not inline in ogcapi.py — reusable for WFS URN forms"
  - "Third-fallback ordering: projjson → WKT → URI (URI only fires when both prior paths return None)"
  - "Arbitrary EPSG integer codes accepted without upper bound (EPSG authority controls namespace)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-20"
  tasks_completed: 3
  tasks_total: 3
---

# Phase 1057 Plan 03: CRS-06 URI/URN-form CRS Parsing Summary

**One-liner:** Shared `parse_crs_uri` regex helper covering four D-07 URI/URN forms wired into `extract_srid_from_json` as third fallback; frontend CRS Override input hidden when probe carries non-null CRS.

## What Was Built

### Task 1 — `parse_crs_uri` helper module (TDD)

**`backend/app/modules/catalog/sources/crs_uri.py`** (new file)

Pure helper function `parse_crs_uri(value: str | None) -> int | None` with four compiled regex constants (module-level, compiled once):

| Constant | Pattern | Maps to |
|----------|---------|---------|
| `_RE_OGC_CRS84_HTTP` | `^https?://www\.opengis\.net/def/crs/OGC/1\.3/CRS84/?$` | 4326 |
| `_RE_EPSG_HTTP` | `^https?://www\.opengis\.net/def/crs/EPSG/0/(\d+)/?$` | `int(N)` |
| `_RE_EPSG_URN` | `^urn:ogc:def:crs:EPSG::(\d+)$` | `int(N)` |
| `_RE_OGC_CRS84_URN` | `^urn:ogc:def:crs:OGC:1\.3:CRS84$` | 4326 |

Default-deny: anything that doesn't match returns `None`. No artificial upper bound on EPSG codes (EPSG authority controls the namespace; downstream PostGIS rejects unknown SRIDs at Find_SRID/ST_Transform time).

Placement: `backend/app/modules/catalog/sources/crs_uri.py` — chosen per D-14 planner discretion (shared utility, not inline in `ogcapi.py`) because WFS URN-form DefaultCRS declarations benefit from the same parsing at preview time via `extract_srid_from_json`.

**`backend/tests/test_crs_uri_parsing.py`** — `TestParseCrsUri` with 16 tests:
- Parametrized per form (forms 1+2, 3, 4, 5)
- Fallthrough cases: None input, empty string, unknown HTTP URI, unknown URN
- Defensive cases: bare `EPSG:N` string → None, non-numeric code → None, large integer → accepted

### Task 2 — Wire into `extract_srid_from_json` (TDD)

**`backend/app/processing/ingest/ogr.py`**

Added `from app.modules.catalog.sources.crs_uri import parse_crs_uri` import and appended third fallback block in `extract_srid_from_json` (lines ~185-197 in modified file):

```
projjson → WKT → URI/URN (via coordinateSystem.name)
```

The `name` field is read defensively (`coord_system.get("name")`); the helper is called only when projjson + WKT both return None. A 10-line comment block references Phase 1057 CRS-06 + D-07 + the unrecognised-fallthrough rationale.

Existing projjson and WKT extraction blocks are unchanged — D-07 ordering invariant preserved.

**`TestExtractSridFromJsonUriFallback`** (7 tests added to `test_crs_uri_parsing.py`):
- URI fallback fires when projjson + WKT absent (CRS84 + EPSG URN)
- projjson wins over URI (ordering test)
- WKT wins over URI (ordering test)
- Unrecognised URI → None (fallthrough)
- Empty dict → None (early-out)
- `name: None` → None (defensive)

### Task 3 — Frontend CRS Override auto-hide (TDD, option B)

**`frontend/src/components/import/ImportMetadataForm.tsx`** (lines 205–230 replaced)

Conditional render on `detectedCrs`:
- `detectedCrs` non-null → read-only confirmation `"Detected CRS: EPSG:{N} (auto-detected — no override needed)"` via `t('metadata.crsDetected', { crs: N, defaultValue: ... })`. Editable `#import-crs` spinbutton hidden.
- `detectedCrs` null → existing editable `#import-crs` input, unchanged (escape hatch for unrecognised URIs and probe-CRS-unknown).

`srid_override` commit semantics unchanged: lines 134-137 are untouched; when the input is hidden, `sridOverride` stays at its initial empty string so `srid_override` resolves to `null` in the commit request.

Inline comment block references D-08 + Phase 1057 + escape-hatch rationale.

**Option chosen:** B (non-editable confirmation line) — preferred per planner-discretion note in the plan interface section. D-08-A (hide everything) would also be acceptable per strict reading, but B provides visual confirmation that detection succeeded.

**`ImportMetadataForm.test.tsx`** — 4 new tests appended (27 total):
- `hides the CRS input when detectedCrs is non-null`
- `shows CRS input when detectedCrs is null (escape hatch preserved)`
- `shows a non-editable confirmation when detectedCrs is non-null`
- `srid_override is null in commit when CRS input is hidden`

## CRS Extraction Wiring Path

**Path chosen: `extract_srid_from_json` third fallback** (not a separate probe-time HTTP GET to `/collections/{id}`).

The plan's objective explicitly chose this path: "Wire into `extract_srid_from_json` at `backend/app/processing/ingest/ogr.py:163` as the third fallback (after projjson and WKT) — this covers every preview-time srid extraction in one place, which catches OGC API + WFS + any other URN-emitting source."

This means CRS extraction fires at preview time (when the user selects a single layer and the preview path runs ogrinfo), not at probe time. The probe still returns `crs=None` for all layers per D-05; the URI/URN parsing kicks in at the single-layer ogrinfo invocation where `coordinateSystem.name` carries the URI.

## Test Results

**Backend (`test_crs_uri_parsing.py`):** 23/23 PASS
- TestParseCrsUri: 16 tests (4 D-07 forms + fallthrough + defensive)
- TestExtractSridFromJsonUriFallback: 7 tests (ordering + fallthrough)

**Backend (existing tests, unaffected):**
- `test_ingest_service_geometry_type.py`: 6/6 PASS (Plan 01)
- `test_probe_classification.py`: 25/25 PASS (Plan 02)

**Total backend (3-plan suite):** 54/54 PASS

**Frontend (`ImportMetadataForm.test.tsx`):** 27/27 PASS (23 pre-existing + 4 new)

**Frontend TypeScript:** 0 errors (`npx tsc --noEmit` clean)

## Live MCP Verification Deferred

Live MCP re-verify against `demo.pygeoapi.io/master → Large Lakes → import without CRS Override interaction` deferred to Phase 1060 (Close Gate) per plan verification section. Unit and integration tests pin the parsing and conditional-render behavior.

## Deviations from Plan

None — plan executed exactly as written. All three options from the plan's implementation notes were taken as specified:
- Helper placed in shared utility module (`crs_uri.py`) per D-14
- Third-fallback position in `extract_srid_from_json` (after projjson + WKT) per D-07
- Frontend option B (non-editable confirmation) per planner-discretion note

## Known Stubs

None — no placeholder data, hardcoded empty values, or TODO-marked surfaces introduced.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers. `parse_crs_uri` uses anchored `^...$` regex patterns against a known-form allowlist (T-1057C-01 mitigated). No eval, no SQL, no subprocess invocations. Frontend conditional render introduces no new trust boundary (`detectedCrs: number | null` is already a validated TypeScript type).

## Self-Check: PASSED

- `backend/app/modules/catalog/sources/crs_uri.py` exists with `parse_crs_uri` and 4 compiled regex constants: FOUND
- Module docstring references "Phase 1057 CRS-06": FOUND
- `backend/tests/test_crs_uri_parsing.py` exists with 23 tests: FOUND
- `grep -n "parse_crs_uri" backend/app/processing/ingest/ogr.py` — import at line 10 + call at line 195: CONFIRMED
- `backend/app/processing/ingest/ogr.py` third-fallback block references "Phase 1057 CRS-06 + D-07": CONFIRMED
- `frontend/src/components/import/ImportMetadataForm.tsx` conditional render on `detectedCrs`: CONFIRMED (line 211)
- `ImportMetadataForm.test.tsx` has 4 new CRS visibility tests: CONFIRMED
- Commit `aafba7fa` (Task 1 helper + tests): FOUND
- Commit `86b47544` (Task 2 ogr.py wire-up): FOUND
- Commit `52e529cd` (Task 3 frontend conditional + tests): FOUND
