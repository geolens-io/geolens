---
phase: quick-260325-f2k
plan: 01
subsystem: frontend
tags: [non-spatial, tables, ui-polish, unit-tests]
dependency_graph:
  requires: [quick-260325-bsk, quick-260325-egu]
  provides: [table-connect-menu, table-search-terminology, structure-tab-dedup, skeleton-sizing]
  affects: [SearchResultCard, ConnectDropdown, StructureTab, DatasetDetailSkeleton, DatasetPage]
tech_stack:
  patterns: [conditional-rendering, i18n-plurals, component-prop-extension]
key_files:
  created:
    - frontend/src/components/dataset/__tests__/ConnectDropdown.test.tsx
    - frontend/src/components/dataset/__tests__/ExportButton.test.tsx
    - frontend/src/components/dataset/__tests__/StructureTab.test.tsx
    - frontend/src/components/dataset/__tests__/DatasetDetailSkeleton.test.tsx
  modified:
    - frontend/src/components/dataset/tabs/StructureTab.tsx
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/dataset/DatasetDetailSkeleton.tsx
    - frontend/src/components/dataset/ConnectDropdown.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    - frontend/src/i18n/locales/en/search.json
    - frontend/src/i18n/locales/es/search.json
    - frontend/src/i18n/locales/fr/search.json
    - frontend/src/i18n/locales/de/search.json
    - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
decisions:
  - ConnectDropdown always rendered for all dataset types; table logic handled internally
  - Renamed "Copy Feature URL" to "Copy API URL" for clarity across all dataset types
metrics:
  duration: 4min
  completed: 2026-03-25
---

# Quick Task 260325-f2k: Non-Spatial Follow-ups Summary

Polish table dataset experience with 4 targeted fixes and comprehensive unit test coverage across 5 test files.

## Completed Tasks

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Implement all 4 follow-up fixes | e9a28cca | StructureTab hides Data Preview for tables, search cards use "rows" for tables, skeleton accepts isTable prop, ConnectDropdown shows only API URL for tables |
| 2 | Write unit tests for all changes | 04bc0d93 | 30 tests across 5 files: SearchResultCard, ConnectDropdown, ExportButton, StructureTab, DatasetDetailSkeleton |

## Changes Made

### Follow-up 1: StructureTab Data Preview Deduplication
Added `recordType` prop to StructureTab. When `recordType === 'table'`, the Data Preview card is hidden since the hero data grid already provides this view.

### Follow-up 2: Search Card Terminology
Table datasets now display "X rows" instead of "X features" in search result card specs. Added `rowCount_one`/`rowCount_other` i18n keys to all 4 locale files (en, es, fr, de).

### Follow-up 3: DatasetDetailSkeleton Layout Shift
Added `isTable` prop. When true, hero skeleton renders at `h-[60vh]` (matching the actual table hero) instead of `h-80 lg:h-96`.

### Follow-up 4: ConnectDropdown Table Visibility
- ConnectDropdown is now always rendered (removed `{!isTable && ...}` guard in DatasetPage)
- Table datasets see only "Copy API URL"; tile URL is hidden
- Renamed "Copy Feature URL" to "Copy API URL" for all non-raster types

## Test Coverage

- **SearchResultCard**: 3 new table tests (badge, row count, vector regression)
- **ConnectDropdown**: 3 tests (spatial, table, raster menu items)
- **ExportButton**: 2 tests (default formats, table shapefile exclusion)
- **StructureTab**: 3 tests (table hides preview, vector shows preview)
- **DatasetDetailSkeleton**: 2 tests (default sizing, isTable sizing)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
