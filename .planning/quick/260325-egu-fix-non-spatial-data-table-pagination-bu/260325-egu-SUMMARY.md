---
phase: quick-260325-egu
plan: 01
subsystem: ui
tags: [react, pagination, i18n, tanstack-table]

requires:
  - phase: quick-260322-hv0
    provides: Non-spatial table support and AttributeTable component
provides:
  - Fixed pagination display for small tables (exact count fallback)
  - Page size selector (25/50/100) in attribute table
  - Expandable hero data grid toggle for table datasets
affects: [dataset-detail, attribute-table]

tech-stack:
  added: []
  patterns: [effectiveTotal fallback for approximate row counts, page size selector with cursor reset]

key-files:
  created: []
  modified:
    - frontend/src/components/dataset/AttributeTable.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/lib/constants.ts
    - frontend/src/i18n/locales/en/dataset.json
    - frontend/src/i18n/locales/fr/dataset.json
    - frontend/src/i18n/locales/es/dataset.json
    - frontend/src/i18n/locales/de/dataset.json

key-decisions:
  - "effectiveTotal = approximateTotal > 0 ? approximateTotal : rowCount for small-table fallback"
  - "isExact flag drives tilde-free display for tables where approximate_total is 0 but rows exist"
  - "Hero data grid defaults to expanded (h-[60vh]) since it is primary content for non-spatial data"

requirements-completed: [FIX-PAGINATION, EXPANDABLE-HERO, PAGE-SIZE-SELECTOR]

duration: 2min
completed: 2026-03-25
---

# Quick 260325-egu: Fix Non-Spatial Data Table Pagination Bug Summary

**Fixed pagination "0 of ~0" bug for small tables, added page size selector (25/50/100), and expandable hero data grid toggle**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-25T14:28:30Z
- **Completed:** 2026-03-25T14:30:27Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Small tables with approximate_total=0 now show exact count ("Showing 1-3 of 3 rows") instead of "Showing 0-3 of ~0 rows"
- Page size selector dropdown (25/50/100) in pagination footer with cursor reset on change
- Hero data grid for table datasets has collapse/expand toggle between h-64 and h-[60vh]
- All 4 locale files updated with showingExact and rowsPerPage i18n keys

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix pagination display bug and add page size selector** - `72d280ac` (fix)
2. **Task 2: Add expandable hero data grid toggle for table datasets** - `53d13203` (feat)

## Files Created/Modified
- `frontend/src/components/dataset/AttributeTable.tsx` - Fixed pagination display, added page size selector
- `frontend/src/pages/DatasetPage.tsx` - Added expandable hero data grid with Minimize2/Maximize2 toggle
- `frontend/src/lib/constants.ts` - Added PAGE_SIZE_OPTIONS array
- `frontend/src/i18n/locales/en/dataset.json` - Added showingExact and rowsPerPage keys
- `frontend/src/i18n/locales/fr/dataset.json` - Added showingExact and rowsPerPage keys
- `frontend/src/i18n/locales/es/dataset.json` - Added showingExact and rowsPerPage keys
- `frontend/src/i18n/locales/de/dataset.json` - Added showingExact and rowsPerPage keys

## Decisions Made
- Used effectiveTotal fallback (approximateTotal > 0 ? approximateTotal : rowCount) to handle small tables where the backend returns approximate_total=0
- isExact flag controls whether tilde prefix is shown in row count display
- Hero data grid defaults to expanded since it is the primary content view for non-spatial datasets

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Self-Check: PASSED
