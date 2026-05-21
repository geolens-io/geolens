---
phase: quick-260331-9wb
plan: 01
subsystem: database
tags: [alembic, migration, settings, upload, raster]

requires: []
provides:
  - "Alembic data migration c5d6e7f8a9b0 that removes the stale upload_allowed_extensions DB override"
affects: [settings, upload, raster-ingestion]

tech-stack:
  added: []
  patterns: ["Data migration via DELETE to let PersistentConfig env default take precedence"]

key-files:
  created:
    - backend/alembic/versions/2026_03_31_0001-reset_upload_allowed_extensions.py
  modified: []

key-decisions:
  - "Downgrade is intentionally a no-op — old row was stale (pre-v10.0) and has no valid restore value"

patterns-established: []

requirements-completed: [QUICK-9wb]

duration: 5min
completed: 2026-03-31
---

# Quick Task 260331-9wb: Add Raster Extensions to Default Allowed Summary

**Alembic data migration that deletes the stale `upload_allowed_extensions` DB override, restoring the env default which includes .tif, .tiff, .xlsx, .xls**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-31T00:00:00Z
- **Completed:** 2026-03-31T00:05:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created migration `c5d6e7f8a9b0` that DELETEs the stale `catalog.app_settings` row for `upload_allowed_extensions`
- After running `alembic upgrade head`, PersistentConfig falls through to the env default: `.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls`
- Admin Storage settings page will display the full extension list including raster and spreadsheet types

## Task Commits

1. **Task 1: Create Alembic data migration to delete stale upload_allowed_extensions override** - `cc313ad3` (chore)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified
- `backend/alembic/versions/2026_03_31_0001-reset_upload_allowed_extensions.py` - Data migration deleting the stale DB override row

## Decisions Made
- Downgrade is a no-op: the deleted row contained a value saved before raster support (v10.0) and cannot meaningfully be restored. No data is lost.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. Run `alembic upgrade head` to apply.

## Next Phase Readiness
- Upload allowed extensions will include .tif, .tiff, .xlsx, .xls once migration is applied
- No blockers

---
*Phase: quick-260331-9wb*
*Completed: 2026-03-31*
