---
phase: 260329-ga7
plan: "01"
subsystem: frontend/search
tags: [ui, search, card, layout]
dependency_graph:
  requires: []
  provides: [4-band SearchResultCard layout]
  affects: [SearchResultCard, SearchResultCard.test]
tech_stack:
  added: []
  patterns: [4-band vertical layout, inline preview, footer status badge]
key_files:
  created: []
  modified:
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
decisions:
  - "Status badges (Draft/Internal/Ready) relocated from header badge row to footer right side"
  - "Max visible tags increased from 2 to 3 given recovered space from smaller preview"
  - "Tags now use plain span chip styling identical to facts row (not Badge variant)"
  - "Updated attribution simplified to 'Updated {time}' — removed 'Updated by {identity}' pattern"
  - "Collections render no preview column in header (no FolderOpen placeholder either)"
metrics:
  duration: "4min"
  completed: "2026-03-29"
  tasks_completed: 2
  files_modified: 2
---

# Phase 260329-ga7 Plan 01: Search Results Card UI/UX Restructure Summary

**One-liner:** 4-band SearchResultCard layout with 80x80 inline header preview, unified chip styling for facts and tags rows, and footer-positioned status badge.

## What Was Built

Rewrote SearchResultCard from a 2-column grid (content + 14rem preview sidebar) to a single-container 4-band vertical layout with consistent gap-3 spacing throughout.

**Band 1 — Header:** `grid-cols-[1fr_80px]` grid with left column (type badge, title, source/description) and right column (80x80 preview, `hidden md:block`, absent for collections). Preview downsized from 140px height × full 14rem column to a compact 80×80 box.

**Band 2 — Facts:** Specs chips using `inline-flex rounded-full border` style. Unchanged from prior implementation.

**Band 3 — Tags:** Keywords using identical chip style as facts row (plain `<span>`, not `<Badge>`). Max visible tags increased from 2 to 3 ("+1 more" overflow for 4+ tags).

**Band 4 — Footer:** `flex justify-between` row with updated time on left and visibility/status Badge on right. Status badges moved from header area to here; published records show nothing on the right.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Restructure SearchResultCard to 4-band layout with inline preview | e7f0c331 |
| 2 | Update SearchResultCard tests for new layout and behavior | 4fe3c243 |

## Test Results

- 22 tests pass (20 existing updated + 2 new)
- Full search directory suite: 50/50 tests pass
- ESLint: 0 errors

## Deviations from Plan

### Auto-fixed Issues

None.

### Notable Implementation Details

1. **Removed `resolveProvenanceIdentity` import** — The simplified footer no longer renders "Updated by {identity}", only "Updated {time}". The import was unused after removing the old attribution display, so it was dropped (Rule 2 cleanup).

2. **Removed `FolderOpen` import** — Collections no longer show a preview placeholder icon in the header (no right column for collections at all). Import removed to avoid unused-import lint warning.

3. **`hasMissingProvenance` simplified** — Old logic checked `updatedByIdentity === unknownIdentityLabel` which required calling `resolveProvenanceIdentity`. New logic only needs `!properties.updated_by_display` since we no longer render identity text.

## Known Stubs

None. All data paths are wired.

## Self-Check

- [x] `frontend/src/components/search/SearchResultCard.tsx` exists and contains `gap-3`
- [x] `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` exists with updated tests
- [x] Commit e7f0c331 exists
- [x] Commit 4fe3c243 exists
- [x] 22/22 tests pass
- [x] ESLint clean

## Self-Check: PASSED
