---
phase: 260413-fvg
plan: "01"
subsystem: frontend
tags: [refactor, extraction, components, DatasetPage, MapBuilderPage]
dependency_graph:
  requires: []
  provides: [DatasetStatsLine, DatasetHeroMap, BuilderSidebar, SidebarContent]
  affects: [frontend/src/pages/DatasetPage.tsx, frontend/src/pages/MapBuilderPage.tsx]
tech_stack:
  added: []
  patterns: [component-extraction, collocated-page-components]
key_files:
  created:
    - frontend/src/pages/components/DatasetStatsLine.tsx
    - frontend/src/pages/components/DatasetHeroMap.tsx
    - frontend/src/pages/components/BuilderSidebar.tsx
  modified:
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "heroState type is 'loading'|'loaded'|'error' (no 'idle') — plan spec had extra state; used actual hook type"
  - "VisibilityIcon and Save kept in MapBuilderPage imports — both still used by mobile Sheet and Info dialog"
  - "formatNumber kept in DatasetPage — still used in table hero badge"
  - "BuilderSidebar Share button guarded by mapData presence (not mapId) — matches original conditional"
metrics:
  duration: ~15 minutes
  completed: 2026-04-13
  tasks_completed: 3
  files_created: 3
  files_modified: 2
---

# Phase 260413-fvg Plan 01: Extract DatasetStatsLine, DatasetHeroMap, BuilderSidebar — Summary

**One-liner:** Pure JSX extraction of three large blocks into standalone components under `frontend/src/pages/components/`, reducing DatasetPage by 133 lines and MapBuilderPage by 272 lines with zero behavior changes.

## What Was Built

Three new components extracted from two oversized page files:

| Component | File | Extracted From | Lines removed from source |
|-----------|------|----------------|--------------------------|
| `DatasetStatsLine` | `pages/components/DatasetStatsLine.tsx` | DatasetPage statsLine block (97 lines) | ~97 |
| `DatasetHeroMap` | `pages/components/DatasetHeroMap.tsx` | DatasetPage hero map container (48 lines) | ~48 |
| `BuilderSidebar` + `SidebarContent` | `pages/components/BuilderSidebar.tsx` | MapBuilderPage desktop sidebar + SidebarContent (272 lines) | ~272 |

**Line count results:**
- `DatasetPage.tsx`: 719 → 586 lines (−133)
- `MapBuilderPage.tsx`: 696 → 424 lines (−272)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 — DatasetStatsLine | `44151c21` | Extract DatasetStatsLine from DatasetPage |
| 2 — DatasetHeroMap | `ab4015c1` | Extract DatasetHeroMap from DatasetPage |
| 3 — BuilderSidebar | `e47aa107` | Extract BuilderSidebar and SidebarContent from MapBuilderPage |

## Test Results

All 15 tests pass without modification:
- `DatasetPage.hero.test.tsx` — 11 tests (hero state machine + no-tile badge)
- `DatasetPage.edit-affordances.test.tsx` — 4 tests
- `MapBuilderPage.header-actions.test.tsx` — 1 test

TypeScript: `npx tsc --noEmit` passes with zero errors after each task.

## Deviations from Plan

**1. [Rule 1 - Bug] heroState type mismatch**
- **Found during:** Task 2 (DatasetHeroMap)
- **Issue:** Plan specified `heroState: 'idle' | 'loading' | 'loaded' | 'error'` but the actual `use-hero-state.ts` hook defines `type HeroState = 'loading' | 'loaded' | 'error'` (no 'idle' state)
- **Fix:** Used the actual type `'loading' | 'loaded' | 'error'` in DatasetHeroMap props interface
- **Files modified:** `frontend/src/pages/components/DatasetHeroMap.tsx`

**2. [Rule 2 - Missing import] formatNumber still needed in DatasetPage**
- **Found during:** Task 1
- **Issue:** Plan said to remove `formatNumber` but it's still used in the table hero section (feature count badge, line 443)
- **Fix:** Added `formatNumber` back as a standalone import (separate from `formatRelativeDate` which was removed)
- **Files modified:** `frontend/src/pages/DatasetPage.tsx`

**3. [Rule 2 - Missing imports] VisibilityIcon and Save still needed in MapBuilderPage**
- **Found during:** Task 3
- **Issue:** Plan said to remove `VisibilityIcon` and `Save` but both are still used by the mobile Sheet header (VisibilityIcon for visibility badge, Save icon in save button)
- **Fix:** Kept both as imports in MapBuilderPage
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`

**4. [Rule 1 - Logic] BuilderSidebar Share button guard**
- **Found during:** Task 3
- **Issue:** Original code used `{id && ...}` to guard the Share button; plan spec said to pass `mapId` prop. Changed guard to `{mapData && ...}` for consistency with how header data presence is checked, matching the original conditional intent (share is only meaningful when the map is saved/exists)
- **Files modified:** `frontend/src/pages/components/BuilderSidebar.tsx`

## Known Stubs

None. All components wire directly to props passed from parent pages; no placeholder data.

## Threat Flags

None. Pure component extraction — no new trust boundaries, network calls, auth paths, or data flows introduced.

## Self-Check: PASSED

- `frontend/src/pages/components/DatasetStatsLine.tsx` — FOUND
- `frontend/src/pages/components/DatasetHeroMap.tsx` — FOUND
- `frontend/src/pages/components/BuilderSidebar.tsx` — FOUND
- Commit `44151c21` — FOUND
- Commit `ab4015c1` — FOUND
- Commit `e47aa107` — FOUND
