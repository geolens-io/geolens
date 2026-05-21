---
phase: 260318-mhz
plan: 01
subsystem: search
tags: [frontend, backend, search, cards, unified-component]
dependency_graph:
  requires: []
  provides: [SearchResultCard, useQuicklook]
  affects: [SearchPage, FilterPanel, search-api]
tech_stack:
  added: []
  patterns: [extracted-hook, unified-card-component, type-discriminated-rendering]
key_files:
  created:
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/hooks/use-quicklook.ts
    - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
  modified:
    - backend/app/search/router.py
    - backend/app/search/service.py
    - frontend/src/types/api.ts
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/pages/SearchPage.tsx
decisions:
  - Single SearchResultCard with type-discriminated rendering replaces DatasetCard + CollectionSearchCard in search results
  - useQuicklook hook extracted for blob URL lifecycle management across card types
  - VRT source_count fetched via VrtGeneration join on current_generation_id
metrics:
  duration: 5min
  completed: "2026-03-18T20:29:19Z"
---

# Quick Task 260318-mhz: Search Result Cards Overhaul Summary

Unified card system where all record types (vector, raster, VRT, collection) render through one SearchResultCard component with type-specific metadata slots, VRT field enrichment from backend, and extracted quicklook hook.

## What Changed

### Task 1: Backend VRT fields + TypeScript type updates (8ec2c935)

- Added `vrt_type` and `resolution_strategy` to the bulk raster metadata query in the search endpoint
- Added `source_count` via a secondary VrtGeneration join for VRT datasets in both bulk search and single-item endpoints
- Added `vrt_type`, `source_count` enrichment to `dataset_to_ogc_record` service function
- Added `dataset_count`, `vrt_type`, `source_count`, `gsd` fields to `OGCRecordProperties` TypeScript interface

### Task 2: Unified SearchResultCard + useQuicklook hook (3de16644)

- Created `useQuicklook` hook extracting quicklook fetch logic with blob URL cleanup
- Created `SearchResultCard` component with 2-column layout handling all 4 record types:
  - **Vector**: geometry type, feature count, CRS, source org, quality badge
  - **Raster**: band count, GSD resolution, CRS, source org, quality badge
  - **VRT**: vrt_type label (Mosaic/Band Stack), source count, band count, CRS
  - **Collection**: dataset count badge, folder icon preview, description footer
- Fixed FilterPanel bug: secondary filter row no longer shows for collection type
- Updated SearchPage to render all results via single SearchResultCard
- Added 15 tests covering all record types, tags, and status badges

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- TypeScript compiles cleanly (`tsc --noEmit`)
- All 41 search card tests pass across 5 test files
- All 15 new SearchResultCard tests pass

## Self-Check: PASSED
