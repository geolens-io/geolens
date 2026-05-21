---
phase: 260318-jqi
plan: 01
subsystem: frontend/search
tags: [ux, search, filters, toolbar]
dependency_graph:
  requires: []
  provides: [compact-toolbar, spatial-result-count, ghost-save-search]
  affects: [SearchPage, FilterPanel, SavedSearches]
tech_stack:
  added: []
  patterns: [spatial-aware-result-count, sticky-toolbar-with-filters]
key_files:
  created: []
  modified:
    - frontend/src/components/search/SavedSearches.tsx
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/pages/SearchPage.tsx
decisions:
  - Ghost variant for SaveSearchButton to visually demote it below filter actions
  - FilterPanel integrated into sticky bar for active mode, separate in body for landing
  - Spatial result count uses bbox OR geometry presence for contextual text
metrics:
  duration: 1min
  completed: "2026-03-18T18:17:43Z"
---

# Phase 260318-jqi Plan 01: Product Concerns - Save Search, Hero Compression, Spatial Count Summary

Ghost Save Search button after sort control, FilterPanel in sticky toolbar for active mode, spatial-aware result count

## What Was Done

### Task 1: Demote Save Search and reorder in FilterPanel
- Changed SaveSearchButton variant from `outline` to `ghost` for visual demotion
- Moved SaveSearchButton from after clear filters to after the sort select control
- Added `geometry` subscription to FilterPanel for spatial filter detection
- Result count now shows "Showing N in selected area" when bbox or geometry is active, falls back to standard count text otherwise
- **Commit:** 8b68ba62

### Task 2: Compress hero into compact toolbar in active search mode
- Moved FilterPanel into the sticky search bar when `!isLanding` (active search mode)
- Hidden SavedSearches in active mode to reduce visual clutter
- Applied `py-2` and `shadow-sm` to sticky bar in active mode for toolbar feel
- FilterPanel only renders in page body for landing mode, preventing duplication
- **Commit:** bd490363

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- TypeScript compiles without errors
- All 6 FilterPanel tests pass
- No duplicate FilterPanel rendering in active mode

## Self-Check: PASSED
