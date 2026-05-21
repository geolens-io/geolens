---
phase: quick-260425-lbc
plan: 01
subsystem: map-builder/overlay-positioning
tags: [positioning, z-index, overlay, map-builder, filter-chips, widgets]
dependency_graph:
  requires: []
  provides: [non-overlapping map overlay layout]
  affects:
    - frontend/src/components/builder/ActiveFilterChips.tsx
    - frontend/src/components/builder/EphemeralBadge.tsx
    - frontend/src/components/map-widgets/WidgetHost.tsx
tech_stack:
  added: []
  patterns: [absolute positioning, z-index hierarchy, CSS Tailwind offsets]
key_files:
  modified:
    - frontend/src/components/builder/ActiveFilterChips.tsx
    - frontend/src/components/builder/EphemeralBadge.tsx
    - frontend/src/components/map-widgets/WidgetHost.tsx
decisions:
  - "CSS-only positioning fix — no structural refactor, no prop-coupling between components"
  - "z-index hierarchy: z-20 (flyout) > z-10 (widgets) > z-[8] (chips/badge) > z-[5] (toolbar)"
  - "ActiveFilterChips offset increased to top-24 to clear MeasurementWidget panel height"
  - "EphemeralBadge raised to bottom-8 to clear MapLibre ScaleControl (~24px)"
  - "LegendWidget anchor raised to bottom-14 to clear both EphemeralBadge and ScaleControl"
metrics:
  duration: "84s"
  completed_date: "2026-04-25"
  tasks_completed: 2
  tasks_total: 3
  files_modified: 3
---

# Quick Task 260425-lbc: Map Overlay Positioning Fix Summary

**One-liner:** CSS-only repositioning of ActiveFilterChips (top-12->top-24), EphemeralBadge (bottom-4->bottom-8), and LegendWidget anchor (bottom-10->bottom-14) to eliminate all top-left and bottom-left overlay collisions in the map builder.

## What Was Built

Fixed two spatial conflicts in the map builder canvas overlay layout:

**Conflict 1 (CRITICAL): ActiveFilterChips vs MeasurementWidget — top-left collision**
- Both elements were anchored at `top-12 left-3 z-10` — identical position, same z-index
- ActiveFilterChips moved to `top-24 left-3 z-[8]`: 96px from top clears the toolbar region and provides space below where the MeasurementWidget panel sits
- z-index lowered from z-10 to z-[8] so widgets render above chips when both visible

**Conflict 2 (MODERATE): EphemeralBadge / LegendWidget / ScaleControl — bottom-left stack**
- EphemeralBadge at `bottom-4` (16px) was below the ScaleControl (~24px tall at bottom-0)
- LegendWidget at `bottom-10` (40px) could overlap a raised badge
- EphemeralBadge raised to `bottom-8` (32px) — clears ScaleControl
- LegendWidget anchor raised to `bottom-14` (56px) — clears both EphemeralBadge and ScaleControl with ~24px gap
- EphemeralBadge z-index lowered to z-[8] so LegendWidget renders above it if legend grows tall

## z-index Hierarchy After Fix

| z-index | Elements |
|---------|----------|
| `z-50` | WebGL context lost overlay |
| `z-20` | LayerEditorPanel flyout, sidebar collapse button |
| `z-10` | WidgetHost (all anchors), MapCoordReadout, tile loading bar |
| `z-[8]` | ActiveFilterChips, EphemeralBadge |
| `z-[5]` | MapToolbar |
| default | MapLibre controls (NavigationControl, ScaleControl) |

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | ActiveFilterChips: top-12->top-24, z-10->z-[8] | 9b2c31f8 |
| 2 | EphemeralBadge: bottom-4->bottom-8, z-10->z-[8]; WidgetHost bottom-left: bottom-10->bottom-14 | f1f876c8 |
| 3 | Human visual verification (checkpoint — awaiting) | — |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None — changes are CSS positioning only, no new network endpoints or auth paths.

## Self-Check: PASSED

- `frontend/src/components/builder/ActiveFilterChips.tsx` — FOUND, contains `top-24`
- `frontend/src/components/builder/EphemeralBadge.tsx` — FOUND, contains `bottom-8`
- `frontend/src/components/map-widgets/WidgetHost.tsx` — FOUND, contains `ANCHOR_POSITIONS` with `bottom-14`
- Commit 9b2c31f8 — FOUND in git log
- Commit f1f876c8 — FOUND in git log
