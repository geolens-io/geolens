---
phase: 260418-d1g
plan: 01
subsystem: import-pipeline
tags: [ogc-api, wfs, gdal, import, i18n]
dependency_graph:
  requires:
    - adapters/wfs.py (adapter pattern reference)
    - adapters/arcgis.py (adapter pattern reference)
    - probe.py (detection orchestration)
    - preview.py (GDAL source building)
    - tasks_common.py (service type resolution)
    - ogr.py (ogr2ogr token handling)
  provides:
    - adapters/ogcapi.py (OGC API Features probe and enrichment)
    - alembic migration d1e2f3a4b5c6 (CHECK constraint update)
  affects:
    - probe.py (slow-path detection order)
    - preview.py (GDAL source string, token env)
    - tasks_common.py (resolve_service_type)
    - ogr.py (run_ogr2ogr_service token guard)
    - models.py (chk_datasets_source_format CHECK constraint)
tech_stack:
  added:
    - GDAL OAPIF driver (OAPIF:{url} prefix for OGC API Features ingestion)
  patterns:
    - WFS adapter pattern cloned for ogcapi.py (probe + enrich with Semaphore(5) + 30s timeout)
    - GDAL_HTTP_HEADERS env var for Bearer token auth (same as WFS)
key_files:
  created:
    - backend/app/modules/catalog/sources/adapters/ogcapi.py
    - backend/alembic/versions/2026_04_18_0001-add_ogcapi_features_source_format.py
  modified:
    - backend/app/modules/catalog/sources/probe.py
    - backend/app/modules/catalog/sources/preview.py
    - backend/app/processing/ingest/tasks_common.py
    - backend/app/processing/ingest/ogr.py
    - backend/app/modules/catalog/datasets/domain/models.py
    - frontend/src/i18n/labels.ts
    - frontend/src/i18n/locales/en/common.json
    - frontend/src/i18n/locales/en/import.json
    - frontend/src/i18n/locales/fr/common.json
    - frontend/src/i18n/locales/fr/import.json
    - frontend/src/i18n/locales/de/common.json
    - frontend/src/i18n/locales/de/import.json
    - frontend/src/i18n/locales/es/common.json
    - frontend/src/i18n/locales/es/import.json
    - frontend/src/components/import/ServiceUrlForm.tsx
    - frontend/src/components/import/WorkflowRail.tsx
decisions:
  - "OGC API probe placed in slow path only (no URL fast path) — landing page JSON is the reliable signal per CONTEXT.md"
  - "Detection order: WFS fast path → ArcGIS fast path → OGC API probe → WFS slow → ArcGIS slow"
  - "source_format value is ogcapi_features to match GDAL OAPIF driver convention"
  - "Bearer token auth via GDAL_HTTP_HEADERS env var — identical to existing WFS pattern"
  - "One collection = one layer in layer picker, no batch multi-collection import"
metrics:
  duration: "~15 minutes execution"
  completed: "2026-04-18T13:52:30Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 16
---

# Quick Task 260418-d1g: Implement OGC API Import Support — Summary

**One-liner:** OGC API Features import via GDAL OAPIF driver with landing-page detection, collection listing, and Bearer token auth, following the existing WFS adapter pattern exactly.

## What Was Built

Added OGC API -- Features as a third supported service type in the GeoLens import pipeline alongside WFS and ArcGIS FeatureServer. Users can paste an OGC API root URL into the Service tab — GeoLens detects it via landing page conformance probe, presents collections as selectable layers, and imports the selected collection using GDAL's `OAPIF:` driver.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | OGC API adapter, detection wiring, and GDAL integration | 135def12 | ogcapi.py (new), probe.py, preview.py, tasks_common.py, ogr.py, models.py, migration |
| 2 | Frontend labels and supported-type display | 2fa666e4 | labels.ts, 4x common.json, 4x import.json, ServiceUrlForm.tsx, WorkflowRail.tsx |

## Backend Changes

### New: `adapters/ogcapi.py`

`probe_ogcapi(url, client, token)`:
- Fetches landing page with `Accept: application/json`
- Checks `conformsTo` array for `"ogcapi-features"` URIs; falls back to fetching `rel: "conformance"` link if no top-level `conformsTo`; accepts secondary `rel: "data"` link as weak signal
- Fetches `{url}/collections`, maps each collection to `{name, title, crs: None}`
- Returns `None` on any HTTP/parse error (probe fails silently)

`enrich_ogcapi_layers(url, layers, client, token)`:
- `asyncio.Semaphore(5)` concurrency, 30s per-layer timeout
- Runs `ogrinfo -json -so OAPIF:{url} {layer_name}` per collection
- Parses `geometryFields[0].type` and `featureCount` from ogrinfo JSON output
- Falls back to `geometry_type=None, feature_count=None` on any failure

### Modified files

| File | Change |
|------|--------|
| `probe.py` | Import ogcapi adapter; add `_build_ogcapi_response()`; insert OGC API probe in slow path before WFS; update `ServiceNotRecognized` message |
| `preview.py` | `build_gdal_source()` returns `OAPIF:{url}` for `OGC API*`; `run_service_preview()` sets `GDAL_HTTP_HEADERS` for `OAPIF:` sources |
| `tasks_common.py` | `resolve_service_type()` maps `"OGC API*"` → `("ogcapi_features", "ogcapi_features")` |
| `ogr.py` | `run_ogr2ogr_service()` token env guard extended to `service_type in ("wfs", "ogcapi_features")` |
| `models.py` | `chk_datasets_source_format` CHECK constraint includes `'ogcapi_features'` |
| `alembic migration` | Drops and recreates the CHECK constraint to include `ogcapi_features` (revision `d1e2f3a4b5c6`) |

## Frontend Changes

- `labels.ts`: `ogcapi_features` key added to `SOURCE_FORMAT_KEYS` and `SOURCE_FORMAT_DEFAULTS`
- All 4 locale `common.json` files: `"ogcapiFeatures": "OGC API Features"` in `enums.sourceFormat`
- All 4 locale `import.json` files: `serviceUrl.placeholder` and `serviceUrl.helpText` updated to mention OGC API Features
- `ServiceUrlForm.tsx`: third `<code>` badge `OGC API Features` added to supported types display
- `WorkflowRail.tsx`: `rail.serviceDesc` defaultValue updated to mention OGC API Features

## Verification Results

1. Backend adapter imports successfully — `probe_ogcapi` and `enrich_ogcapi_layers` importable
2. `build_gdal_source("OGC API Features", ...)` returns `("OAPIF:{url}", layer_name)` — verified by source inspection
3. `resolve_service_type("OGC API Features")` returns `("ogcapi_features", "ogcapi_features")` — verified by source inspection
4. TypeScript compiles without errors (exit 0)
5. Detection order correct: WFS fast path → ArcGIS fast path → OGC API probe → WFS slow → ArcGIS slow

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all integration points are fully wired. The probe, enrichment, GDAL source, ingestion token handling, DB constraint, and frontend labels are all live.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. The `probe_ogcapi()` function routes through the same probe router path as WFS/ArcGIS, inheriting the existing `url_is_safe` SSRF guard (T-d1g-01). Bearer token handling is strictly via subprocess env (T-d1g-03). Concurrency capped at Semaphore(5) + 30s timeout (T-d1g-04).

## Self-Check: PASSED

Files created:
- `backend/app/modules/catalog/sources/adapters/ogcapi.py` — FOUND
- `backend/alembic/versions/2026_04_18_0001-add_ogcapi_features_source_format.py` — FOUND

Commits:
- `135def12` — FOUND (Task 1)
- `2fa666e4` — FOUND (Task 2)
