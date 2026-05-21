---
phase: 260329-kq7
plan: 01
subsystem: frontend/search
tags: [search, dataset-card, ui, i18n, skeleton]
dependency_graph:
  requires: []
  provides: [enhanced-search-card]
  affects: [frontend/src/components/search/SearchResultCard.tsx, frontend/src/components/search/DatasetCardSkeleton.tsx]
tech_stack:
  added: []
  patterns: [icon+text specs, auto-description, buildAutoDescription]
key_files:
  created: []
  modified:
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/search/DatasetCardSkeleton.tsx
    - frontend/src/i18n/locales/en/search.json
    - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
decisions:
  - No pill/chip backgrounds on specs; pills reserved for keyword tags only
  - buildAutoDescription returns real description if present, otherwise type-specific generated text
  - 120px thumbnail replaces 80px to give more visual weight
  - Middle-dot separator between specs keeps density without borders
metrics:
  duration: 10min
  completed: 2026-03-29
  tasks: 2
  files: 4
---

# Phase 260329-kq7 Plan 01: Enhance Dataset Cards Summary

**One-liner:** SearchResultCard upgraded with auto-generated descriptions, icon+plain-text specs (no pills), 120px thumbnail, and matching skeleton.

## What Was Built

### Task 1: SearchResultCard refactor
- `buildCardSpecs` now returns `CardSpec[]` (icon + label pairs) instead of plain strings
- New `buildAutoDescription` function generates contextual descriptions per record type when `properties.description` is empty
- All non-collection dataset cards show a description line (real or auto-generated)
- Specs render as `LucideIcon + plain text` with middle-dot separators; no `rounded-full` or `bg-muted` pill backgrounds
- Thumbnail container changed from 80px to 120px square across all 6 size references in the grid
- Outer flex gap tightened from `gap-3` to `gap-2` to compensate for added description
- Tags (Band 3) retain pill/chip styling — clear visual distinction from specs
- Added `card.autoDesc.*` and `card.sourceCount_one/other` i18n keys in `search.json`

### Task 2: Skeleton + tests
- `DatasetCardSkeleton` updated to match: 120px thumbnail, description skeleton row, plain-rect spec skeletons (no `rounded-full`), `gap-2` outer spacing
- 6 new tests added: 4 in "Description display" suite (real, auto-generated vector, auto-generated raster, collections excluded), 2 in "Spec styling" suite (no `rounded-full`, no `bg-muted` in specs)
- All 28 tests pass (22 existing + 6 new)

## Decisions Made

- **Icon selection for specs:** `geometryIcon()` from geo-utils for geometry type (fallback `Shapes`), `Layers` for band count, `Ruler` for GSD, `Combine` for VRT type, `FolderOpen` for source count, `Hash` for feature/row count, `Globe` for CRS
- **Collection description:** Collections keep existing behavior (show real description if present, no auto-description); the non-collection description block is separate
- **Middle-dot as spec separator:** Rendered between items (not after last) using `&middot;` at `text-muted-foreground/40`

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `frontend/src/components/search/SearchResultCard.tsx` modified
- [x] `frontend/src/components/search/DatasetCardSkeleton.tsx` modified
- [x] `frontend/src/i18n/locales/en/search.json` updated with autoDesc keys
- [x] `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` updated with 6 new tests
- [x] Commits: `3ba509ec` (Task 1), `df7a10b9` (Task 2)
- [x] All 28 tests pass

## Self-Check: PASSED
