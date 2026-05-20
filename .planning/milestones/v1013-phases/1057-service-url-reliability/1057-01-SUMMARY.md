---
phase: 1057-service-url-reliability
plan: "01"
subsystem: backend-ingest
tags: [wfs, ogr2ogr, geometry-type, postgis, regression-test]
dependency_graph:
  requires: []
  provides: [constraint-free-geometry-column-on-service-ingest]
  affects: [backend/app/processing/ingest/ogr.py, backend/tests/test_ingest_service_geometry_type.py]
tech_stack:
  added: []
  patterns: [nlt-GEOMETRY-for-constraint-free-column, argv-monkeypatch-test-pattern]
key_files:
  modified:
    - backend/app/processing/ingest/ogr.py
  created:
    - backend/tests/test_ingest_service_geometry_type.py
decisions:
  - "D-01: replaced -nlt PROMOTE_TO_MULTI with -nlt GEOMETRY on service path only; file path unchanged"
  - "D-02: get_geometry_type(metadata.py:165) supplies concrete subtype post-ingest; no column-level constraint needed"
  - "GDAL token chosen: -nlt GEOMETRY (canonical flag for constraint-free column; verified by test assertion)"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-19"
  tasks_completed: 2
  tasks_total: 2
---

# Phase 1057 Plan 01: WFS Abstract Geometry Type Fix Summary

**One-liner:** Replace `-nlt PROMOTE_TO_MULTI` with `-nlt GEOMETRY` on the service-ingest path so PostGIS accepts any concrete geometry subtype without column-constraint errors.

## What Was Built

### Task 1 — `run_ogr2ogr_service` fix (`backend/app/processing/ingest/ogr.py`)

Changed the spatial branch of `run_ogr2ogr_service` (line ~567-601):
- **Removed:** `-nlt PROMOTE_TO_MULTI`
- **Added:** `-nlt GEOMETRY`

`-nlt GEOMETRY` instructs ogr2ogr to emit a generic `geometry(Geometry, 4326)` PostGIS column with no subtype constraint. Any concrete geometry subtype (MultiPolygon, MultiLineString, etc.) can be stored freely, regardless of what abstract OGC type the WFS service declared in its schema (MultiSurface, MultiCurve, etc.).

Added a 15-line inline comment block explaining:
- (a) Why the flag changed — asyncpg `InvalidParameterValueError` on `MultiSurface vs MultiPolygon` during `clip_to_mercator_bounds`
- (b) That `Dataset.geometry_type` is derived via `get_geometry_type()` (`metadata.py:165`) post-ingest
- (c) That the file-ingest sibling `run_ogr2ogr` is unchanged and still uses `PROMOTE_TO_MULTI`
- References: D-01 and Phase 1057

The file-ingest `run_ogr2ogr` function (line ~470-486) is untouched; it still uses `PROMOTE_TO_MULTI`.

### Task 2 — Regression test (`backend/tests/test_ingest_service_geometry_type.py`)

Created `TestRunOgr2ogrServiceArgv` with **6 tests** (all passing):

| Test | What it pins |
|------|-------------|
| `test_wfs_spatial_branch_omits_promote_to_multi` | `PROMOTE_TO_MULTI` absent from argv (D-01 regression guard) |
| `test_wfs_spatial_branch_emits_nlt_geometry` | `-nlt GEOMETRY` present as adjacent pair |
| `test_wfs_spatial_branch_includes_geometry_name` | `GEOMETRY_NAME=_geolens_geom` and `SPATIAL_INDEX=NONE` preserved |
| `test_wfs_spatial_branch_includes_t_srs_4326` | `-t_srs EPSG:4326` preserved |
| `test_wfs_spatial_branch_includes_page_size_config` | `OGR_WFS_PAGE_SIZE` present for `service_type='wfs'` |
| `test_non_spatial_branch_omits_geometry_flags` | `is_non_spatial=True` emits no geometry flags |

Test pattern: monkey-patches `app.processing.ingest.ogr.asyncio.create_subprocess_exec` to capture argv. No network, no DB, no GDAL subprocess required. Uses `pytest.mark.anyio` to match the project's async test convention.

## GDAL Flag Verification

**Flag chosen:** `-nlt GEOMETRY`

This is the canonical GDAL ogr2ogr flag for "no subtype constraint." It produces a PostGIS column typed `geometry(Geometry, SRID)` — the unparameterized base type — which accepts any concrete geometry subtype without a column-level type check.

Verification command (documents the intent for future maintainers):
```bash
grep -A1 '"-nlt"' backend/app/processing/ingest/ogr.py | grep run_ogr2ogr_service -A3
```

Static verification (both pass):
- `grep -n "PROMOTE_TO_MULTI" backend/app/processing/ingest/ogr.py` — only line 474 (`run_ogr2ogr` file-ingest, untouched)
- `grep -n "Phase 1057\|D-01" backend/app/processing/ingest/ogr.py` — comment block present at line 571

## Test Results

```
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_wfs_spatial_branch_omits_promote_to_multi PASSED
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_wfs_spatial_branch_emits_nlt_geometry PASSED
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_wfs_spatial_branch_includes_geometry_name PASSED
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_wfs_spatial_branch_includes_t_srs_4326 PASSED
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_wfs_spatial_branch_includes_page_size_config PASSED
tests/test_ingest_service_geometry_type.py::TestRunOgr2ogrServiceArgv::test_non_spatial_branch_omits_geometry_flags PASSED

6 passed in 0.98s
```

Existing pure tests unaffected: `test_ingest_ogr_pure.py` + `test_services_wfs_pure.py` → 91 passed.

## Deviations from Plan

None — plan executed exactly as written. The plan recommended `-nlt GEOMETRY` as the preferred token; this is what was implemented.

## Live MCP Repro Deferred

Live MCP re-verify against `ahocevar.com/geoserver/wfs → Countries of the World → Import` is deferred to Phase 1060 (Close Gate) per the plan's verification section. The unit-test argv pin in Task 2 provides the regression guard for this plan.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The change is a flag substitution in an existing subprocess call. Threat model T-1057A-01 (argv is a Python list, no shell expansion) is confirmed unchanged. No threat flags.

## Known Stubs

None — no placeholder data, hardcoded empty values, or TODO-marked surfaces introduced.

## Self-Check: PASSED

- `backend/app/processing/ingest/ogr.py` exists and contains `-nlt GEOMETRY` at the service path: FOUND
- `backend/tests/test_ingest_service_geometry_type.py` exists with 6 tests: FOUND
- Commit `c6f13906` (ogr.py fix): FOUND
- Commit `cd539051` (test file): FOUND
- `PROMOTE_TO_MULTI` absent from `run_ogr2ogr_service` spatial branch argv: CONFIRMED (grep shows only line 474 file-ingest + comment lines)
