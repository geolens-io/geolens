---
phase: 260318-9hl
plan: 01
subsystem: search
tags: [search, synthetic-data, filter, badges, zustand]

requires:
  - phase: v12.0
    provides: Record model with keywords, record_status, search service
provides:
  - exclude_synthetic API filter parameter (default True)
  - "Show test data" toggle in desktop and mobile search UI
  - Synthetic "Test Data" badge on DatasetCard
  - Complete publication status badge styles (draft, ready, internal, archived, deprecated)
affects: [search, catalog, dataset-cards]

tech-stack:
  added: []
  patterns:
    - "NOT EXISTS subquery for keyword-based dataset exclusion"
    - "Boolean filter in zustand store with server-default-true pattern"

key-files:
  created: []
  modified:
    - backend/app/search/schemas.py
    - backend/app/search/service.py
    - backend/app/search/router.py
    - frontend/src/stores/search-store.ts
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/components/search/DatasetCard.tsx

key-decisions:
  - "Keyword-based synthetic detection using NOT EXISTS subquery on RecordKeyword for 'synthetic'"
  - "Purple badge for Test Data to distinguish from amber draft and other badge colors"
  - "Filter synthetic/perf-seed keywords from card tag display to reduce noise"

patterns-established:
  - "exclude_synthetic=true server default; frontend only sends param when false"

requirements-completed: [TRUST-01, TRUST-02, TRUST-03]

duration: 4min
completed: 2026-03-18
---

# Phase 260318-9hl: Data Trust & Catalog Hygiene - Hide Test Data Summary

**Backend exclude_synthetic filter with NOT EXISTS keyword subquery, frontend toggle in FilterPanel, purple Test Data badge, and complete status badge styles**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T10:55:28Z
- **Completed:** 2026-03-18T10:59:22Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- Synthetic/test datasets hidden from search results and facet counts by default
- "Show test data" toggle available on desktop and mobile filter UI
- Synthetic datasets display purple "Test Data" badge when visible
- All publication statuses (draft, ready, internal, archived, deprecated) have distinct colored badges
- synthetic and perf-seed keywords filtered from card tag display

## Task Commits

Each task was committed atomically:

1. **Task 1: Backend - Add exclude_synthetic filter to search API** - `5016956f` (feat)
2. **Task 2: Frontend - Add exclude_synthetic to search store and toggle in FilterPanel** - `33b3ca8f` (feat)
3. **Task 3: Frontend - Add synthetic badge and complete status styles on DatasetCard** - `f7e78654` (feat)

## Files Created/Modified
- `backend/app/search/schemas.py` - Added exclude_synthetic field to SearchParams
- `backend/app/search/service.py` - NOT EXISTS filter in search_datasets and get_facet_counts
- `backend/app/search/router.py` - Wired exclude_synthetic param through all search endpoints
- `frontend/src/stores/search-store.ts` - Added exclude_synthetic boolean to search state
- `frontend/src/components/search/FilterPanel.tsx` - Show test data Switch toggle (desktop + mobile)
- `frontend/src/components/search/DatasetCard.tsx` - Synthetic badge, complete status styles, keyword filtering

## Decisions Made
- Used keyword-based detection (NOT EXISTS on RecordKeyword where keyword='synthetic') rather than a dedicated boolean column
- Purple badge color for Test Data to visually distinguish from amber (draft) and blue (ready) status badges
- Only send exclude_synthetic=false to API when user toggles it; server defaults to true

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Synthetic data filtering is complete and ready for use
- To tag datasets as synthetic, add the keyword "synthetic" to their record keywords

---
*Phase: 260318-9hl*
*Completed: 2026-03-18*
