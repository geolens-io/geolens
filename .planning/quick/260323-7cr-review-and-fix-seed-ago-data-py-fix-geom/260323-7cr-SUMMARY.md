# Quick Task 260323-7cr: Summary

## What was done

### Root Cause
When `run_ogr2ogr()` imports a file and the PostGIS table already exists from a prior failed ingest, ogr2ogr defaults to **append mode** — silently ignoring `-lco GEOMETRY_NAME=geom`. The pre-existing table retains `wkb_geometry`, and downstream post-processing (`clip_to_mercator_bounds`, `add_4326_column`) crashes because they hardcode `geom`.

### Fixes Applied

**1. Backend: ogr2ogr `-overwrite` flag** (`backend/app/ingest/ogr.py`)
- Added `-overwrite` to both `run_ogr2ogr()` and `run_ogr2ogr_service()`
- Ensures fresh table creation even when stale tables exist from failed ingests

**2. Backend: `ensure_geom_column()` safety net** (`backend/app/ingest/metadata.py`)
- New function queries `geometry_columns` for actual column name
- Renames to `geom` if ogr2ogr used a different name (e.g., `wkb_geometry`)
- Defense-in-depth for any GDAL edge case

**3. Backend: Pipeline wiring** (`backend/app/ingest/tasks.py`)
- Calls `ensure_geom_column()` after ogr2ogr and before `clip_to_mercator_bounds()` in both file and service ingest paths

**4. Script: seed-ago-data.py improvements** (`scripts/seed-ago-data.py`)
- Fixed `get_service_layers()` null handling — ArcGIS returns `null` (not missing key) for layers/tables
- Added `--clean` flag to delete datasets from previous failed runs
- Added `--concurrency` flag (default 3) to control parallelism

### Verification
Tested on actual ArcGIS data that was previously failing:
- `agricultural_priority_areas.geojson.zip` (which had `wkb_geometry`)
- After fix: `-overwrite` drops stale table → ogr2ogr creates with `geom` → `ensure_geom_column` confirms → `clip_to_mercator_bounds` succeeds

## Commit
- `061e72c4` — fix: resolve geometry column naming bug in ingest pipeline
