---
phase: 1040
plan: "01"
subsystem: frontend/dnd
tags:
  - dnd
  - drag-drop
  - mapbuilder
  - frontend
  - react
dependency_graph:
  requires:
    - "Phase 1039 (ux-audit shipped — AUD-03, AUD-04 identified)"
  provides:
    - "Shared DndContext at MapBuilderPage level (foundational for Plan 02 catalog drag)"
    - "Basemap row as useDroppable target — accepts catalog drops in Plan 02"
    - ".dragging-active .kebab CSS rule — hides kebabs during cross-panel drag"
  affects:
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/index.css"
tech_stack:
  added: []
  patterns:
    - "Lifted DndContext pattern: single context at page level wraps multiple sibling panels"
    - "useDroppable for non-draggable drop-only targets (vs useSortable for drag+drop)"
key_files:
  created: []
  modified:
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/index.css"
decisions:
  - "DndContext lifted to MapBuilderPage so sidebar stack and Add Dataset modal share one collision-detection scope"
  - "onReorder prop kept in UnifiedStackPanelProps interface but not destructured — MapBuilderPage.handleDragEnd calls layers.handleReorder directly"
  - "activeDragId (not activeId) used in MapBuilderPage to avoid symbol collision with any future activeId"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 1040 Plan 01: Lift DndContext + AUD-03/AUD-04 Fixes Summary

**One-liner:** DndContext lifted from UnifiedStackPanel to MapBuilderPage; basemap row converted from no-op useSortable to useDroppable; cross-panel drag CSS rules added.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add CSS drag-polish rules for cross-panel drag (AUD-03) | `04084501` | `frontend/src/index.css` |
| 2 | Replace basemap row useSortable with useDroppable (AUD-04) | `f63f1c0b` | `frontend/src/components/builder/UnifiedStackPanel.tsx` |
| 3 | Lift DndContext from UnifiedStackPanel into MapBuilderPage | `31d831cc` | `frontend/src/pages/MapBuilderPage.tsx`, `frontend/src/components/builder/UnifiedStackPanel.tsx` |

## Architecture: Lifted DndContext Ancestor Chain

**Before (Plan 01):**
```
MapBuilderPage
  └─ UnifiedStackPanel
       └─ DndContext (sensors, handlers, activeId)
            └─ SortableContext
  └─ BuilderDialogs          ← OUTSIDE DndContext (cross-panel drag impossible)
```

**After (Plan 01):**
```
MapBuilderPage
  └─ DndContext (sensors, handlers, dragActiveId)  ← LIFTED HERE
       ├─ sidebar <aside>
       │    └─ UnifiedStackPanel
       │         └─ SortableContext + DragOverlay (activeDragId prop)
       └─ BuilderDialogs  ← NOW INSIDE DndContext (ready for Plan 02 catalog drag)
```

## AUD-03 Rationale

The `.dragging-active` body class was already toggled on `document.documentElement` by UnifiedStackPanel's drag handlers. However `frontend/src/index.css` had no `.dragging-active .kebab` rule — only a more specific `[data-testid^="stack-row-"] [data-kebab-trigger]` rule. Any element marked `.kebab` outside of a stack row (e.g., catalog-row kebabs in the Add Dataset modal) would remain visible during drag, causing visual noise. Three rules added:
- `.dragging-active .kebab { opacity: 0 !important }` — the missing AUD-03 rule
- `html.dragging-active { cursor: grabbing !important }` — prevents cursor flicker during cross-panel drag
- `[data-basemap-drop-target="true"]` — primary-50 tint + left rail (pre-wired for Task 2 basemap drop)

## AUD-04 Rationale

The `BasemapGroupRowWrapper` was registered via `useSortable({ id: group.id })` but `group.id` ('basemap-group') was deliberately excluded from `sortableIds`. This made the basemap row appear draggable (grab cursor, `useSortable` hook registered) but any drag attempt silently did nothing — the `handleDragEnd` only looked in `layers[]` for matching ids, which never includes 'basemap-group'. Replaced with `useDroppable({ id: group.id, data: { source: 'stack', kind: 'basemap-group' } })`. The row now:
- Has proper drop-target semantics (isOver fires correctly)
- Exposes `data-basemap-drop-target="true"` when a drag hovers it (activates CSS tint)
- Passes a stable noop `dragHandleProps` stub (grip column renders but is non-interactive)

## Test Commands That Passed

```bash
cd frontend && npx tsc -b --noEmit              # 0 type errors
cd frontend && npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx
# ✓ 19/19 tests pass
cd frontend && npx vitest run src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
# ✓ 5/5 tests pass
cd frontend && npx vitest run src/components/builder/ src/pages/
# ✓ 68 test files, 746 tests pass
cd frontend && npm run build
# ✓ built in 372ms
```

## Acceptance Criteria Verification

- `grep -c "DndContext" frontend/src/pages/MapBuilderPage.tsx` → 6 (≥1) ✓
- `grep -c "DndContext" frontend/src/components/builder/UnifiedStackPanel.tsx` → 0 ✓
- `grep -c "useSensors" frontend/src/pages/MapBuilderPage.tsx` → 3 (≥1) ✓
- `grep -c "useSensors" frontend/src/components/builder/UnifiedStackPanel.tsx` → 0 ✓
- `grep -c "dragging-active" frontend/src/pages/MapBuilderPage.tsx` → 3 (≥2) ✓
- `grep -v '^[[:space:]]*/\*' frontend/src/index.css | grep -c "\.dragging-active \.kebab"` → 1 (≥1) ✓
- `grep -c "useDroppable" frontend/src/components/builder/UnifiedStackPanel.tsx` → 4 (≥1) ✓

## Deviations from Plan

**1. [Rule 1 - Bug] onReorder not destructured in UnifiedStackPanel**
- **Found during:** Task 3 (TypeScript reported TS6133 — declared but never read)
- **Issue:** After lifting `handleDragEnd` to MapBuilderPage, `onReorder` prop was destructured in UnifiedStackPanel but had no callsite — TypeScript correctly flagged it.
- **Fix:** Removed `onReorder` from the destructured parameter list; kept it in `UnifiedStackPanelProps` interface (MapBuilderPage still passes it and MapBuilderPage.handleDragEnd calls `layers.handleReorder` directly). Added comment explaining the intent.
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx`
- **Commit:** `31d831cc` (included in Task 3 commit)

**2. [Rule 1 - Bug] DndContext references in UnifiedStackPanel comments blocked acceptance criteria**
- **Found during:** Task 3 acceptance check
- **Issue:** Comment text mentioning "DndContext" in the panel file caused `grep -c "DndContext"` to return 2 instead of 0.
- **Fix:** Reworded comment to "lifted drag context" instead of "DndContext".
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx`
- **Commit:** `31d831cc`

## Known Stubs

None — this plan is a pure refactor. No new data sources or UI stubs introduced.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes. Changes are limited to frontend component structure and CSS.

## Self-Check: PASSED
