---
phase: 260331-cuw
plan: "01"
type: quick-task
tags: [frontend, table, ux, dataset]
subsystem: frontend
dependency_graph:
  requires: []
  provides: [attribute-table-scroll-fix, table-expand-collapse, table-ux-polish]
  affects: [DatasetPage, DetailPanel, DataTab, AttributeTable]
tech_stack:
  added: []
  patterns: [tanstack-table-sorting, tanstack-table-visibility, expand-collapse-pattern]
key_files:
  created: []
  modified:
    - frontend/src/components/dataset/AttributeTable.tsx
    - frontend/src/components/dataset/tabs/DataTab.tsx
    - frontend/src/components/dataset/panels/DetailPanel.tsx
    - frontend/src/pages/DatasetPage.tsx
decisions:
  - "Used w-max min-w-full on Table instead of removing the outer border div entirely — preserves the border/rounded styling while fixing scroll"
  - "Density toggle state lives in DataTab (not passed from parent) to keep it local to the component"
  - "Auto-collapse on tab switch implemented in handleTabChange rather than useEffect to avoid stale closure issues"
metrics:
  duration: 8min
  completed_date: "2026-03-31"
  tasks_completed: 2
  files_modified: 4
---

# Phase 260331-cuw Plan 01: Attribute Table UX Fix Summary

**One-liner:** Horizontal scroll fix + expand-to-fullscreen + sorting, column visibility, row striping, density toggle, and truncation tooltips for the dataset attribute table.

## What Was Built

Two auto tasks executed; awaiting human verification (Task 3 checkpoint).

### Task 1: AttributeTable.tsx — Horizontal scroll fix and UX polish

**Root cause fix:** Removed `overflow-auto` from the outer border div; the `<Table>` component's built-in `overflow-x-auto` wrapper now handles horizontal scroll. Applied `className="w-max min-w-full"` to `<Table>` so columns grow beyond container width when needed.

**Polish added:**
- Alternating row striping via `bg-muted/30` on odd rows
- Client-side sorting with `getSortedRowModel()` — clickable column headers with `↑` / `↓` / `ArrowUpDown` indicators
- Column visibility dropdown using `DropdownMenuCheckboxItem` with a `Settings2` icon button
- Truncation tooltips for cell values longer than 30 characters
- `compact?: boolean` prop for row density control (`py-1 text-xs` vs default `py-3`)

### Task 2: Expand/collapse mechanism

**DataTab.tsx** — Full rewrite:
- Added `expanded` and `onToggleExpand` props
- When expanded: full-height flex column layout (`h-[calc(100vh-10rem)]`) with toolbar + scrollable table area
- When normal: Card layout with `Maximize2` expand button in header
- Density toggle (`AlignJustify`/`List` icons) in both modes; state managed internally

**DetailPanel.tsx** — Prop threading:
- Added `isTableExpanded` and `onToggleTableExpand` to interface and passes through to `<DataTab>`

**DatasetPage.tsx** — State management:
- Added `isDataTabExpanded` state and `toggleDataTabExpand` callback
- Hero map section hidden when `isDataTabExpanded` is true (vector datasets)
- Raster quick facts strip hidden when expanded
- Tab switch auto-collapses: `if (value !== 'data') setIsDataTabExpanded(false)` in `handleTabChange`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 64168f6c | feat(260331-cuw-01): fix horizontal scroll and add table UX polish |
| 2 | eb95a83d | feat(260331-cuw-01): add expand/collapse mechanism and wire DataTab toolbar |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all features are fully wired.

## Self-Check: PASSED

Files verified:
- FOUND: frontend/src/components/dataset/AttributeTable.tsx
- FOUND: frontend/src/components/dataset/tabs/DataTab.tsx
- FOUND: frontend/src/components/dataset/panels/DetailPanel.tsx
- FOUND: frontend/src/pages/DatasetPage.tsx

Commits verified:
- FOUND: 64168f6c
- FOUND: eb95a83d
