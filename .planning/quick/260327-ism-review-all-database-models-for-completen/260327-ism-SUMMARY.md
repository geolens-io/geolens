---
phase: 260327-ism
plan: 01
subsystem: database/schema
tags: [database, sqlalchemy, schema, migrations, indexes, constraints, alembic]
dependency_graph:
  requires: []
  provides: [db-model-review-report]
  affects: [backend/app/*/models.py, backend/alembic/versions/]
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - .planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md
  modified: []
decisions:
  - Documentation-only output — no source code or migrations changed
  - Main repo model files used as authoritative source (worktree was behind on raster models)
  - 32 models inventoried (research initially counted 31; DatasetAsset confirmed as additional model)
metrics:
  duration: 15 min
  completed: 2026-03-27
  tasks_completed: 2
  files_created: 1
---

# Phase 260327-ism Plan 01: Database Model Review Summary

**One-liner:** Comprehensive 865-line schema audit covering 32 SQLAlchemy models — 31 verified findings across 9 HIGH, 15 MEDIUM, 7 LOW severities, with a 4-tier prioritized action plan.

## What Was Done

**Task 1 — Verify research findings against current source**

Read all 12 model files and 10 Alembic migrations. Cross-referenced every research finding:
- Confirmed all 5 missing FK index findings (H1-H5) — no btree indexes exist for `api_keys.user_id`, `ingest_jobs.created_by`, `maps.created_by`, `records.created_at DESC`, or `records.source_organization` in any migration.
- Confirmed 3 model/migration drift findings (H6, H7, L4) and added 2 more (H8, L7).
- Updated M7 — `VrtSourceLink` DOES have `uq_vsl_vrt_source` in the DB; the finding was a model-drift issue (constraint exists in DB but not in model), not a missing constraint as originally classified.
- Updated M9 — `RecordContact.role` DOES have `chk_contact_role` in the DB; again a model-drift issue, not a purely missing constraint.
- Discovered 6 new findings not in the original research.

**Task 2 — Write the comprehensive review report**

Created `260327-ism-REPORT.md` (865 lines) at the specified path. Report includes:
- Model inventory table (32 models, all modules)
- 31 findings organized by severity with file paths, line numbers, impact descriptions, and SQL/Python fix recommendations
- Positive observations section (10 strong patterns)
- 4-tier prioritized action plan
- Relationship loading strategy audit appendix

## Deviations from Plan

### Auto-fixed Issues

None — pure documentation task.

### Research Corrections

**1. M7 Finding Reclassified**
- **Finding:** Research classified M7 as "missing unique constraint" on VrtSourceLink
- **Actual state:** `uq_vsl_vrt_source UNIQUE (vrt_dataset_id, source_dataset_id)` EXISTS in the DB (`initial_schema.sql:1732`). Both FK columns also have explicit `index=True` in the model.
- **Report treatment:** Reclassified as L7 (model drift — constraint exists in DB but not in model `__table_args__`), consistent with H6/H7 pattern.

**2. M9 Finding Updated**
- **Finding:** Research said `RecordContact.role` has no CHECK constraint at all.
- **Actual state:** `chk_contact_role` EXISTS in the DB enforcing the full ISO 19115 role vocabulary. The model simply doesn't declare it.
- **Report treatment:** Reclassified as M8 (model drift / autogenerate risk), updated with the actual constraint values from the schema.

**3. New Findings Discovered**

Six findings not in the original research were added to the report:
- **H8:** `RasterAsset` model missing `chk_raster_assets_status` and `chk_raster_assets_vrt_type` (both exist in DB)
- **H9:** `chk_records_record_type` model includes `'table'` value not in the initial_schema.sql constraint (forward drift — missing migration)
- **M9 (new):** `RecordKeyword` model missing `chk_keyword_type` that exists in DB
- **M13:** `MapLayer.layer_type` has no CHECK constraint (new, not in research)
- **M14:** `RasterAsset.storage_backend` has no CHECK constraint (new)
- **M15:** `DatasetAsset.key` has no CHECK constraint (new)

**4. Model Count Updated**
Research counted 31 models; actual count is 32. `DatasetAsset` (`catalog.dataset_assets`) is present in the main repo raster models but was missing from the research inventory.

## Key Decisions Made

- Used main repo model files (not the worktree files) since the worktree's `raster/models.py` was 54 lines vs 179 lines in main — the worktree was behind and missing VrtGeneration, VrtSourceLink, and DatasetAsset models.
- Severity H9 assigned to the `chk_records_record_type` forward-drift because a missing migration could cause `CheckViolationError` on fresh schema initialization if `'table'` record types exist in production.

## Self-Check

- [x] REPORT.md exists at `.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md`
- [x] Report is 865 lines (> 200 minimum)
- [x] All 25 research findings represented (confirmed, updated, or reclassified)
- [x] 6 new findings added beyond the research
- [x] No source code files modified
- [x] Report includes model inventory, findings, positive observations, action plan, appendix

## Self-Check: PASSED
