---
phase: 1034
plan: "01"
subsystem: frontend/builder
tags: [layout, grid, breakpoints, flyout, sidebar, responsive]
dependency_graph:
  requires: [1033-02]
  provides: [1034-02, 1034-03]
  affects: [frontend/src/pages/MapBuilderPage.tsx, frontend/src/components/builder/LayerEditorPanel.tsx, frontend/src/components/builder/hooks/use-builder-layout.ts]
tech_stack:
  added: []
  patterns: [three-column-css-grid, tdd-red-green]
key_files:
  created:
    - frontend/src/components/builder/hooks/__tests__/use-builder-layout.test.ts
    - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
  modified:
    - frontend/src/components/builder/hooks/use-builder-layout.ts
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
decisions:
  - "Breakpoints locked at 1100px (rail) and 800px (editor-hidden) per UI-SPEC §Responsive breakpoints"
  - "LayerEditorPanel now requires onClose (not onBack) and enableLegacyTabs flag (default true) preserves tabs until Plan 03"
  - "onRemove added as required field to LayerEditorHandlers — Plan 03 wires the footer Delete button"
  - "Pre-existing Phase 1033 TS errors in normalize test files are out-of-scope for this plan (documented as deferred)"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 7
  tests_added: 21
---

# Phase 1034 Plan 01: Layout Shell and Flyout Chrome Summary

Three-column CSS grid layout scaffold with locked 1100/800 breakpoints, revived LayerEditorPanel chrome, and removal of the legacy resizable sidebar.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | useBuilderLayout 1100/800 breakpoints | a28e7245 | use-builder-layout.ts + test |
| 2 | LayerEditorPanel chrome scaffold | d7759b15 | LayerEditorPanel.tsx + test |
| 3 | MapBuilderPage three-column grid | f7824eea | MapBuilderPage.tsx + updated tests |

---

## What Was Shipped

### Task 1 — `useBuilderLayout` breakpoint update (TDD)

Replaced `BUILDER_COMPACT_BREAKPOINT=1024` / `BUILDER_MOBILE_BREAKPOINT=768` with `BUILDER_RAIL_BREAKPOINT=1100` / `BUILDER_EDITOR_HIDDEN_BREAKPOINT=800` locked from UI-SPEC §"Responsive breakpoints".

New hook return shape:
- `isRail: boolean` — true at <1100px (sidebar collapses to 64px icon rail in Plan 02)
- `isEditorHidden: boolean` — true at <800px (flyout column hidden)
- `viewportWidth: number` — current window.innerWidth
- `isCompact: boolean` — backward-compat alias for `isRail`
- `isMobile: boolean` — backward-compat alias for `isEditorHidden`

8 Vitest tests cover: wide (1200px), rail (1024px), editor-hidden (600px), resize handler, listener cleanup on unmount, and boundary values (1099, 800).

### Task 2 — `LayerEditorPanel` chrome (TDD)

Refactored existing `LayerEditorPanel` to the new chrome structure:

**Header** (`data-testid="layer-editor-header"`):
- Close `×` button (`aria-label="Close layer editor"`, Lucide `X` icon, triggers `onClose`)
- Layer name (`id="layer-editor-title"`, text-sm semibold, truncated)
- `ColorizedGeometryIcon` type indicator
- Back `‹` button shown only when `isDrillDown=true` (drill-down fallback at <800px)

**Body** (`data-testid="layer-editor-body"`): empty when `enableLegacyTabs=false`; legacy tab content preserved when `enableLegacyTabs=true` (default)

**Footer** (`data-testid="layer-editor-footer"`): empty placeholder (Plan 03 wires Delete)

New props: `onClose: () => void` (required, replaces `onBack`), `isDrillDown?: boolean`, `enableLegacyTabs?: boolean` (default true)

Added `onRemove: (layerId: string) => void` to `LayerEditorHandlers` interface for Plan 03's footer.

9 Vitest tests cover: layer name in header, display_name priority, close button aria-label, click→onClose, body testid, empty body with `enableLegacyTabs=false`, legacy tabs with `enableLegacyTabs=true`, footer testid, onRemove interface acceptance.

### Task 3 — `MapBuilderPage` three-column grid

**Removed:**
- `SIDEBAR_WIDTH_KEY`, `SIDEBAR_MIN`, `SIDEBAR_MAX`, `SIDEBAR_MIN_MAP_WIDTH`, `BUILDER_RAIL_WIDTH` constants
- `sidebarWidth` state + `sidebarWidthRef` + `sidebarElRef` + `sidebarMaxForViewport` computed
- `handleDragStart`, `handleSeparatorKeyDown` drag handlers
- `SidebarContent` memo component (editor was stacked inside sidebar; now it's a sibling grid column)
- Resize handle JSX, edge collapse button, drag handle JSX

**Added:**
- `builderBodyGridClass` computed from `isRail`, `isEditorHidden`, `editingLayer`:
  - No editor: `grid-cols-[340px_1fr]` or `grid-cols-[64px_1fr]` (rail)
  - Editor open: `grid-cols-[340px_380px_1fr]` or `grid-cols-[64px_380px_1fr]` (rail)
- `data-testid="builder-sidebar"` `<aside>` (column 1) — still renders `MapStackPanel` until Plan 02
- `data-testid="builder-layer-editor"` `<aside>` (column 2) — rendered when `editingLayer && !isEditorHidden`
- Map canvas `<div>` (column 3 or 2) — `relative min-h-0 min-w-0` (no flex-1; grid handles sizing)
- `onRemove: layers.handleRemove` wired to `layerEditorHandlers`
- Updated focus return in `handleCloseEditor` to resolve `stack-row-${id}` (Plan 02) **or** legacy `layer-expand-${id}` (MapStackItem)

**Mobile path (isEditorHidden = <800px):** Still uses Sheet-based sidebar (identical to old `isMobile` path). Rail UI deferred to Plan 02.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `LayerEditorHandlers.onRemove` required field broke existing test file**
- **Found during:** Task 3 (build verification)
- **Issue:** Adding `onRemove` as a required field to `LayerEditorHandlers` caused TypeScript errors in `LayerStyleEditor.test.tsx` (4 usages of `LayerEditorPanel` without `onRemove` and with old `onBack` prop)
- **Fix:** Added `onRemove: vi.fn()` to the test `handlers` object; updated `onBack={vi.fn()}` → `onClose={vi.fn()} isDrillDown={true}` on the drill-down test case
- **Files modified:** `frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx`
- **Commit:** f7824eea (bundled with Task 3 commit)

### Pre-existing Issues (Out of Scope)

**Phase 1033 TypeScript errors in test files** — `src/api/__tests__/maps.normalize.test.ts` and `src/lib/__tests__/normalize-saved-map.test.ts` have 8 TypeScript errors introduced by Phase 1033. These are pre-existing at the start of this plan (verified by running `npm run build` before and after our changes). The `npx tsc --noEmit` (source files only) shows zero errors; the `npm run build` fails because `tsc -b` includes test files. The vite bundle itself (`npx vite build`) compiles and produces the `MapBuilderPage-*.js` chunk successfully. These errors are out of scope for Plan 1034-01 and should be addressed in the Phase 1033 wave or a follow-up plan.

---

## Verification Results

| Check | Result |
|-------|--------|
| `vitest run use-builder-layout.test.ts` | 8/8 PASS |
| `vitest run LayerEditorPanel.test.tsx` | 9/9 PASS |
| `vitest run MapBuilderPage.header-actions.test.tsx` | 4/4 PASS |
| `npx tsc --noEmit` (source files) | 0 errors |
| `npm run lint` (changed files) | 0 errors |
| `npx vite build` (bundle) | SUCCESS |
| `npm run build` (tsc -b + vite) | FAIL (pre-existing Phase 1033 test TS errors — out of scope) |

---

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Plan removes `localStorage.getItem/setItem` for sidebar width (net reduction in storage surface). No new threat flags.

## Known Stubs

- `data-testid="builder-layer-editor"` flyout column renders `LayerEditorPanel` with `enableLegacyTabs={true}` — the legacy tab body renders inside the flyout. Plan 03 replaces it with section-based content by setting `enableLegacyTabs={false}`. This is an intentional transition stub.

## Self-Check: PASSED

All 6 source files found. All 3 task commits verified (a28e7245, d7759b15, f7824eea). 21 tests pass. Zero typecheck errors on source. Vite bundle builds successfully.
