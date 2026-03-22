---
phase: quick-260322-kec
plan: 01
subsystem: datasets, frontend
tags: [foreign-key, auto-detection, related-records, read-only-click]

requires:
  - phase: quick-260322-hv0
    provides: DatasetRelationship model, RelatedRecordsPanel component
  - phase: quick-260322-irw
    provides: FK endpoint polish, visibility checks
provides:
  - auto_detect_relationships() for ingestion-time FK discovery
  - Read-only feature click activates RelatedRecordsPanel
  - table record_type support in RelatedRecordsPanel guard
affects: [dataset-ingestion, dataset-detail-page, related-records]

tech-stack:
  added: []
  patterns: [column-name-matching FK detection, effectiveGid merge pattern]

key-files:
  created: []
  modified:
    - backend/app/datasets/service.py
    - frontend/src/components/dataset/DatasetMap.tsx
    - frontend/src/pages/DatasetPage.tsx

key-decisions:
  - "FK candidates filtered by _id suffix, excluding PK names (gid, ogc_fid, fid, objectid, id)"
  - "Idempotent relationship creation via existence check before insert"
  - "Read-only click handler only fires when activeMode is null (no drawing/select mode)"
  - "effectiveGid merges selectedFeatureGid (editing) and readOnlyFeatureGid (read-only)"

patterns-established:
  - "auto_detect_relationships: column-name matching against semantic_role='identifier' in other datasets"
  - "effectiveGid: merge editing and read-only feature selection for downstream consumers"

requirements-completed: [FK-AUTO, PANEL-READONLY, TABLE-VALIDATION]

duration: 2min
completed: 2026-03-22
---

# Quick Task 260322-kec: FK Auto-Detection and Read-Only Panel Activation Summary

**FK auto-detection on ingestion via column-name matching, plus read-only map click activation of RelatedRecordsPanel including table datasets**

## What Changed

### Task 1: FK auto-detection on ingestion
- Added `auto_detect_relationships()` in `backend/app/datasets/service.py` (~line 944)
- Extracts candidate columns ending with `_id` (excluding PK names: gid, ogc_fid, fid, objectid, id)
- Queries `attribute_metadata` for matching columns with `semantic_role='identifier'` in other datasets
- Skips self-references via `record_id` comparison
- Idempotent: checks for existing relationship before inserting
- Called from `create_dataset()` after `generate_attribute_metadata`

### Task 2: Read-only feature click + table guard fix
- Added `onFeatureClick` prop to `DatasetMap` component
- Added read-only click handler that fires only when `activeMode` is null (no drawing/select mode active)
- Added `readOnlyFeatureGid` state in `DatasetPage` with `effectiveGid` merging editing and read-only selections
- Fixed guard condition to include `record_type === 'table'` for RelatedRecordsPanel
- Editing selection clears read-only selection via useEffect

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 6b4e46bb | feat(260322-kec): add FK auto-detection on dataset ingestion |
| 2 | d7be5cd7 | feat(260322-kec): read-only feature click activates RelatedRecordsPanel |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. `auto_detect_relationships` function exists in service.py -- PASS
2. Function called from `create_dataset()` after `generate_attribute_metadata` -- PASS
3. TypeScript compiles with no errors -- PASS
4. `onFeatureClick` prop added to DatasetMap -- PASS
5. `effectiveGid` merges editing and read-only gids -- PASS
6. Guard includes `record_type === 'table'` -- PASS
