---
phase: quick-260327
plan: 01
subsystem: search-ui
tags: [search, ui, ux, accessibility, polish]
dependency_graph:
  requires: [quick-260326]
  provides: [search-audit-fixes, search-shell-polish]
  affects: [SearchPage, FilterPanel, SpatialFilterPanel, SearchResultCard, SearchBar, SavedSearches, Pagination, useQuicklook, e2e-search]
tech_stack:
  added: []
  patterns: [table-aware search filtering, conditional preview fetching, sticky-shell browse parity]
key_files:
  created:
    - .planning/quick/260327-implement-the-search-page-audit-findings/260327-PLAN.md
    - .planning/quick/260327-implement-the-search-page-audit-findings/260327-SUMMARY.md
    - .planning/quick/260327-implement-the-search-page-audit-findings/260327-VERIFICATION.md
  modified:
    - frontend/src/pages/SearchPage.tsx
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/components/search/SearchBar.tsx
    - frontend/src/components/search/SavedSearches.tsx
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/search/SpatialFilterPanel.tsx
    - frontend/src/components/layout/Pagination.tsx
    - frontend/src/hooks/use-quicklook.ts
    - frontend/src/components/search/__tests__/FilterPanel.test.tsx
    - e2e/search.spec.ts
decisions:
  - Desktop and tablet UX took priority; mobile only received the necessary spillover fixes
  - Table records are now treated as first-class search results in the type controls instead of being implicitly folded into vector counts
  - Unsupported previews are gated before fetch instead of relying on error fallback
metrics:
  duration: 16min
  completed: 2026-03-25
---

# Quick Task 260327: Implement Search Audit Findings Summary

Implemented the concrete findings from quick task 260326 across the search shell, filters, spatial panel semantics, result-card polish, preview fetching, and regression coverage.

## What Was Done

### Search shell and filter behavior
- Preserved sticky filter access after the landing hero scrolls away
- Added table-aware type counts and a `Table` type toggle
- Hid geometry/CRS affordances when the selected record type is `table`
- Lowered the visual weight of the sticky shell and secondary filter row

### Accessibility and preview behavior
- Stopped mounting the spatial search dialog while closed
- Added a backdrop and clean dialog lifecycle for the spatial filter panel
- Prevented quicklook fetches for table records and used a deliberate preview-unavailable state instead

### Style polish
- Softened compact search bar chrome
- Quieted saved-search styling so it reads as supporting UI
- Reduced supporting card metadata emphasis so title/type lead more clearly
- Adjusted pagination layout so it compresses cleanly instead of breaking awkwardly

### Regression coverage
- Expanded `FilterPanel` tests for table-aware counts/state
- Added Playwright coverage for landing scroll sticky access and the closed spatial-dialog regression

## Verification

- `cd frontend && npx tsc --noEmit`
- `cd frontend && npx eslint src/pages/SearchPage.tsx src/components/search/SearchBar.tsx src/components/search/SavedSearches.tsx src/components/search/FilterPanel.tsx src/components/search/SearchResultCard.tsx src/components/search/SpatialFilterPanel.tsx src/hooks/use-quicklook.ts src/components/layout/Pagination.tsx src/components/search/__tests__/FilterPanel.test.tsx`
- `cd frontend && npx vitest run src/components/search/__tests__/FilterPanel.test.tsx src/components/search/__tests__/SearchResultCard.test.tsx`
- `npx playwright test e2e/search.spec.ts --project=chromium`

## Task Commits

1. **Search audit fixes and regression coverage** - `28154160` (feat)
