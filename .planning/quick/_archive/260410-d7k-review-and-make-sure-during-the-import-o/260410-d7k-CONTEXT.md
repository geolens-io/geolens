---
name: 260410-d7k-CONTEXT
description: Context for quick task 260410-d7k — audit whether all source columns are preserved through the backend ingest pipeline
type: quick-context
---

# Quick Task 260410-d7k: Review Import Operations — All Columns Imported - Context

**Gathered:** 2026-04-10
**Status:** Ready for planning

<domain>
## Task Boundary

Review the backend ingestion pipeline (`backend/app/ingest/`) end-to-end and make sure that every source attribute from uploaded files is preserved in the resulting dataset. Find any silent column drops, fix bugs, and add regression tests.

**In scope:**
- `backend/app/ingest/tasks.py` — Celery/background ingestion entry points
- `backend/app/ingest/ogr.py` — ogr2ogr invocation and column handling
- `backend/app/ingest/service.py` — ingest orchestration
- `backend/app/ingest/metadata.py`, `schemas.py`, `validation.py` — supporting modules
- Any shared helpers these import

**Out of scope (for this task):**
- Frontend UI (UploadForm, ImportMetadataForm, BulkReviewList)
- VRT/raster ingestion pipeline
- CLI seeder scripts
- `backend/tests/test_vrt_ingest_tasks.py`

</domain>

<decisions>
## Implementation Decisions

### Scope
- Review backend ingest pipeline only (`backend/app/ingest/`).
- Trace column flow from upload → ogr2ogr/parse → database → dataset schema.
- Do **not** touch frontend, raster, or seeder code paths.

### Column Preservation Semantics
- "All columns" means: every source attribute that exists in the uploaded file ends up queryable in the resulting dataset. No silent drops.
- Investigate common drop points:
  - ogr2ogr `-select` / field filters
  - Schema coercion stripping fields
  - Reserved name collisions (`id`, `geom`, `geometry`, internal columns)
  - Encoding-related dropped columns (Shapefile DBF field length, non-ASCII names)
  - JSON/array/date/boolean type coercion
  - Silent exceptions on a single row's field value that skip the whole field
- The audit should cover geometry + all supported file formats (Shapefile, GeoJSON, GeoPackage, CSV, FGB, etc.) per whatever the pipeline currently supports.

### Outcome
- **Audit + Fix + Tests**:
  1. Audit: produce findings in SUMMARY.md with file:line references for every code path that could drop columns.
  2. Fix: change code for any real bugs found.
  3. Tests: add regression tests that prove columns survive import.
- Fixes should be focused — do not refactor unrelated ingest code.

### Trigger
- General audit, no specific symptom observed.
- No known bug report to reproduce; we are looking for latent issues.

### Research-surfaced decisions (locked post-research)
- **`-lco PRECISION=NO` (ogr2ogr)**: **Leave it, document why.** Add an inline comment at the call sites explaining the tradeoff. Add a test that documents the current behavior (numeric/decimal source → `double precision`). Do NOT change behavior.
- **Reserved-name collisions** (source field named `gid`, `geom`, `geom_4326`, `fid`, `ogc_fid`): **Auto-rename with warning.** Rename source column to a safe name (e.g. `src_gid`, `src_geom`), log a warning with original + renamed name so the user can see what happened. Column must still be preserved in the dataset.
- **Shapefile DBF 10-char truncation collisions** (e.g. `population_2020` + `population_2021` both truncate to `population`): **Warn-only.** Detect the collision post-ingest, log a warning listing both original names, let GDAL keep whichever it keeps. No import rejection.

### Claude's Discretion
- Depth of test coverage — integration-level tests that actually hit the ingest pipeline are preferred, but unit-level tests for column-handling helpers are acceptable if an integration harness is unavailable.
- Exact format of the audit findings section inside SUMMARY.md.
- Whether to add a single new test file or extend an existing one.
- Exact naming scheme for auto-renamed reserved columns (prefer `src_*`).
- Where the warning log is emitted (structured logger vs. warnings attached to ingest task result).

</decisions>

<specifics>
## Specific Ideas

- Pay attention to the recent uncommitted change in `backend/app/ingest/tasks.py` (7 lines added) — understand it and make sure it doesn't interact badly with column preservation.
- Check whether ogr2ogr is called with any field allow-list/deny-list flags (`-select`, `-where`, `-fieldmap`).
- Check whether SRID/geometry column naming collides with any common source attribute name.
- Consider Shapefile DBF 10-character field name truncation as a real-world column identity hazard.

</specifics>

<canonical_refs>
## Canonical References

- GDAL `ogr2ogr` docs — https://gdal.org/programs/ogr2ogr.html
- Project CLAUDE.md / conventions
- Existing tests: `backend/tests/` — use them as a harness reference if possible
- Known project memory: `GDAL ogrinfo JSON coordinateSystem is often nested inside geometryFields[0]` (treat as related GDAL gotcha)

</canonical_refs>
