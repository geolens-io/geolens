---
phase: 260318-8mp
plan: 01
subsystem: frontend/search
tags: [i18n, ux, search, filters]
dependency_graph:
  requires: []
  provides: [search-ux-consistency]
  affects: [search-page, filter-panel]
tech_stack:
  added: []
  patterns: [conditional-secondary-row, dataset-only-count]
key_files:
  created: []
  modified:
    - frontend/src/i18n/locales/en/search.json
    - frontend/src/i18n/locales/de/search.json
    - frontend/src/i18n/locales/es/search.json
    - frontend/src/i18n/locales/fr/search.json
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/components/search/__tests__/FilterPanel.test.tsx
decisions:
  - All tab count sums only dataset record types (vector + raster + vrt), excluding collections
  - Secondary filter row conditionally rendered based on whether controls would appear
metrics:
  duration: 3min
  completed: "2026-03-18T10:21:00Z"
---

# Quick Task 260318-8mp: Fix Remaining Search Page UX Issues Summary

Fixed five discrete search page UX inconsistencies: subtitle wording, tab pluralization, All tab count excluding collections, empty secondary filter row suppression, and date filter label alignment across 4 locales.

## What Was Done

### Task 1: Fix i18n strings across all locales (0db1e3d4)
- Updated subtitle from "datasets" to "geospatial data" in en/de/es/fr
- Changed dateRange label from "Upload Date" to "Date Added" equivalents in all locales
- Added plural `filters.collections` key in all 4 locale files

### Task 2: Fix FilterPanel count logic, tab label, and empty row (8bd5682a)
- Changed "All" tab count to sum only `vector_dataset + raster_dataset + vrt_dataset` (excludes `collection`)
- Applied same fix in both desktop and mobile toggle groups
- Changed Collection tab label to use `t('filters.collections')` (plural) on desktop and mobile
- Added condition to secondary filter row: only renders when `vector_dataset` OR when org/CRS data exists
- Updated test assertions for new count (15 not 18) and plural label
- Added new test: "does not render secondary filter row for raster type when no org/crs available"

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- All 6 FilterPanel tests pass
- i18n verification script confirms all 4 locales updated correctly

## Commits

| # | Hash | Message |
|---|------|---------|
| 1 | 0db1e3d4 | fix(260318-8mp): update i18n strings for search page UX consistency |
| 2 | 8bd5682a | fix(260318-8mp): fix FilterPanel count logic, tab label, and empty row |
