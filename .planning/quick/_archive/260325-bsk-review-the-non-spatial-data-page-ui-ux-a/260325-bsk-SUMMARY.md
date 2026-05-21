---
phase: quick-260325-bsk
plan: 01
subsystem: frontend
tags: [ui, ux, non-spatial, table-datasets]
dependency_graph:
  requires: []
  provides: [table-type-badge, table-detail-page-ux]
  affects: [DatasetPage, RecordTypeBadge, OverviewTab, VectorDetailPanel, ExportButton, AccessTab, AccessSharingTab]
tech_stack:
  added: []
  patterns: [conditional-rendering-by-record-type, prop-drilling-recordType]
key_files:
  created:
    - .planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-REVIEW.md
  modified:
    - frontend/src/components/search/RecordTypeBadge.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/components/dataset/tabs/OverviewTab.tsx
    - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    - frontend/src/components/dataset/ExportButton.tsx
    - frontend/src/components/dataset/tabs/AccessTab.tsx
    - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
    - frontend/src/i18n/locales/en/search.json
    - frontend/src/i18n/locales/fr/search.json
    - frontend/src/i18n/locales/es/search.json
    - frontend/src/i18n/locales/de/search.json
decisions:
  - Table datasets use conditional rendering gated on record_type === 'table' rather than separate component hierarchy
  - Shapefile export filtered client-side via recordType prop rather than backend format restriction
metrics:
  duration: 2min
  completed: 2026-03-25
---

# Quick Task 260325-bsk: Non-Spatial Data Page UI/UX Review Summary

Orange Table badge, hidden spatial controls, row terminology, deduplicated data tab, filtered exports for non-spatial table datasets.

## What Was Done

### Task 1: Table type badge and spatial control visibility
- Added `table` entry to `RecordTypeBadge` TYPE_CONFIG with `Table2` icon and orange badge styling
- Added `card.table` i18n key in all 4 locale files (en/fr/es/de)
- Wrapped `AddToMapButton` and `ConnectDropdown` in `{!isTable && (...)}` conditionals
- Changed stats line text from "features" to "rows" for table datasets
- **Commit:** ea2b30ae

### Task 2: Overview fields, data tab deduplication, export filtering
- Changed geometry type field condition to also check `dataset.geometry_type` truthiness (hides for tables)
- Changed "Feature Count" label to "Row Count" for table datasets in OverviewTab
- Hidden Data tab trigger and content in VectorDetailPanel for table datasets (hero is the data grid)
- Added `recordType` prop to ExportButton, filtering Shapefile for table datasets
- Updated AccessTab and AccessSharingTab to pass `recordType` prop
- **Commit:** 4aac62f8

### Task 3: Review report
- Documented all 8 fixes applied
- Noted SRID display already handled by existing null-check
- Listed 4 remaining recommendations for future work
- **Commit:** f1710022

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
