---
phase: 1152-single-band-raster-fixture
plan: "01"
subsystem: seed-script / raster-ingest
tags: [seed, raster, fixture, testdata, idempotency]
dependency_graph:
  requires: []
  provides: [TESTDATA-01]
  affects: [phases/1154, phases/1155]
tech_stack:
  added: []
  patterns:
    - "ingest_raster_fixture(): three-step upload/preview/commit reusing existing poll_job + download_or_load_cache helpers"
    - "Zip-extraction pattern: extract .tif from CDN zip before upload so server _stamp_raster_metadata fires"
    - "Idempotency via existing_by_filename keyed on tif_filename (source_filename as stored by server)"
key_files:
  created: []
  modified:
    - scripts/seed-natural-earth.py
decisions:
  - "Upload GRAY_50M_SR.tif (extracted from zip), not GRAY_50M_SR.zip — server raster detection requires .tif/.tiff extension"
  - "RASTER_FIXTURE has two filename keys: filename (CDN zip, cache key) and tif_filename (uploaded/stored source_filename)"
  - "Idempotency check uses tif_filename (GRAY_50M_SR.tif), not zip filename — matches what server stores as source_filename"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-29"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 1
---

# Phase 1152 Plan 01: Single-Band Raster Fixture Summary

**One-liner:** Seeded GRAY_50M_SR uint8 single-band raster via `ingest_raster_fixture()` extension to seed-natural-earth.py — verified `is_dem=false`, `band_count==1`, and idempotent re-run.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add idempotent ingest_raster_fixture() to seed script | `7cae72ee` | scripts/seed-natural-earth.py |
| 2 | Run seed + verify band_count=1, is_dem=false, idempotency | `761469df` | scripts/seed-natural-earth.py |

## What Was Built

Extended `scripts/seed-natural-earth.py` with:

1. **`RASTER_FIXTURE` manifest constant** — GRAY_50M_SR, single-band uint8 grayscale shaded relief from NACIS CDN (same CDN used by the vector seed path). Public domain Natural Earth terms-of-use. Two filename keys: `filename` (CDN zip, used as download cache key) and `tif_filename` (the uploaded filename, stored as `source_filename` by the server).

2. **`ingest_raster_fixture()` coroutine** — idempotent three-step ingest (upload → preview → commit → poll). Reuses `download_or_load_cache`, `poll_job`. Extracts the `.tif` from the zip before uploading so the server's `_stamp_raster_metadata` extension-check fires. Tags applied best-effort via records API (same pattern as `ingest_dataset`). Failures return `{"status": "failed", ...}` without raising.

3. **`main()` wiring** — called after the vector `asyncio.TaskGroup` and before `create_collections()`. Result appended to `results` list so summary counters (`succeeded`/`skipped`/`failed`) include the fixture.

## Verified Gates

All three acceptance gates PASS against the live dev stack:

| Gate | Check | Result |
|------|-------|--------|
| Band count | `GET /api/datasets/{id}.raster.band_count` | `1` |
| DEM classification | `SELECT ra.is_dem FROM catalog.raster_assets ... WHERE d.source_filename = 'GRAY_50M_SR.tif'` | `f` (false) |
| Idempotency | Second seed run prints "Skipping GRAY_50M_SR (already imported)"; `count(*) WHERE source_filename = 'GRAY_50M_SR.tif'` | `1` |

**Combined DB gate:**
```
SELECT (count(*) = 1 AND bool_or(NOT ra.is_dem)) FROM catalog.datasets d
JOIN catalog.raster_assets ra ON ra.dataset_id = d.id
WHERE d.source_filename = 'GRAY_50M_SR.tif';
```
Result: `t` — PASS.

## Fixture Reference (for phases 1154/1155)

- **dataset_id:** `4767fc35-f6d6-4985-a28e-aecb158fbc1b`
- **source_filename:** `GRAY_50M_SR.tif`
- **band_count:** `1`
- **is_dem:** `false`
- **duplicate_count:** `1` (idempotent)
- **title:** "Natural Earth Shaded Relief (1:50m)"
- **visibility:** public

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Upload .tif extracted from zip, not .zip directly**

- **Found during:** Task 2 (first seed run — 422 on preview step)
- **Issue:** Plan said "upload the .zip, do not extract." However, `_stamp_raster_metadata` (ingest/router.py:334) gates raster detection on filename ending `.tif`/`.tiff`/`.vrt`. Uploading `GRAY_50M_SR.zip` routed to the vector preview path (ogrinfo), which returned 422 because the zip contains a TIF, not a shapefile.
- **Fix:** Extract the `.tif` bytes from the zip using `zipfile.ZipFile` before uploading. Upload as `GRAY_50M_SR.tif` so the raster detection fires. Added `tif_filename` key to `RASTER_FIXTURE` to separate the CDN download name (zip, used as cache key) from the upload filename (tif, stored as `source_filename`). Updated idempotency check to key on `tif_filename`.
- **Files modified:** `scripts/seed-natural-earth.py`
- **Commit:** `761469df`

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. The seed script is an operator-run tool; the fixture is a public-domain Natural Earth raster from the NACIS CDN already trusted by the vector seed path.

## Known Stubs

None — the fixture is fully ingested and verified. No placeholder data.

## Self-Check: PASSED

- [x] `scripts/seed-natural-earth.py` exists and loads cleanly via importlib
- [x] `RASTER_FIXTURE` dict present with correct `url`, `filename`, `tif_filename` keys
- [x] `ingest_raster_fixture` coroutine present
- [x] Commits `7cae72ee` and `761469df` exist in git log
- [x] Fixture dataset_id `4767fc35-f6d6-4985-a28e-aecb158fbc1b` verified in catalog
- [x] `band_count == 1` confirmed via API
- [x] `is_dem = f` confirmed via DB
- [x] Idempotency: second run skips, count stays 1
