---
phase: 1041
plan: "01"
subsystem: builder
tags:
  - mapbuilder
  - selection
  - a11y
  - listbox
dependency_graph:
  requires:
    - 1040-04 (DnD lifted to MapBuilderPage; handleDragStart wiring site)
  provides:
    - selectedIds Set<string> in MapBuilderPage
    - handleCmdClick / handleShiftClick / handleCheckboxClick handlers
    - isMultiSelectionActive derived boolean
    - Checkbox visual in StackRow + FolderGroupRow caret column
    - cursor-not-allowed on BasemapGroupRow during multi-select
    - aria-multiselectable="true" + aria-label on listbox
    - outside-click + Escape + Shift+Arrow clearing
  affects:
    - 1041-02 (BulkActionBar consumes selectedIds + isMultiSelectionActive)
    - 1041-03 (bulk handlers consumed from MapBuilderPage)
    - 1041-04 (selection tests assert on this plan's behavior contract)
tech_stack:
  added: []
  patterns:
    - Lifted state (selectedIds) to MapBuilderPage — mirrors Phase 1040 DndContext lift
    - Boundary guard (isBasemapBoundaryId) before any selectedIds mutation
    - Outside-click via document mousedown + stackPanelRef.contains guard
    - Escape + Shift+Arrow via document keydown effect keyed on selectedIds.size
    - Radix Checkbox swap in caret column (already installed component)
key_files:
  created: []
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
decisions:
  - "Lifted selectedIds + lastToggleAnchor + handlers to MapBuilderPage (vs keeping in UnifiedStackPanel): MapBuilderPage already owns the DndContext and handleDragStart — putting selectedIds there allows handleDragStart to call setSelectedIds(new Set()) directly without prop drilling a clearSelection ref. Mirrors the Phase 1040 DndContext lift pattern exactly."
  - "Route-change clearing via natural unmount (not useLocation watcher): UnifiedStackPanel is re-keyed by mapId when the route changes, so selectedIds initializes to empty Set on remount. No explicit location listener needed; the React lifecycle handles it."
  - "BasemapGroupRow receives NO cmd/shift/checkbox handlers: boundary refusal lives in the parent handlers (isBasemapBoundaryId guard in handleCmdClick/handleShiftClick). The basemap row is silently non-selectable — cursor-not-allowed is the only visual signal (per POL-11 silent refusal contract)."
  - "onClearSelection callback prop added to UnifiedStackPanel: since selectedIds is lifted, the panel needs a way to tell the parent to clear. A simple () => void callback is the minimal surface — no ref pattern needed."
metrics:
  duration: "8m"
  completed_date: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 5
---

# Phase 1041 Plan 01: Selection model + multi-selection visual + Shift+Arrow keyboard extension

**One-liner:** Multi-row selection model with Cmd/Shift/Space/Shift+Arrow handlers, Checkbox-in-caret visual, basemap boundary guard, and Escape/outside-click/drag-start clearing — foundation for Plan 02 BulkActionBar.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Selection state, outside-click, Escape, drag-start clearing | b385578e | MapBuilderPage.tsx, UnifiedStackPanel.tsx |
| 2 | Checkbox + Cmd/Shift/Space handlers + multi-selection visual in row components | b385578e | StackRow.tsx, FolderGroupRow.tsx, BasemapGroupRow.tsx |

Note: Tasks 1 and 2 were committed together because they are mutually dependent — TypeScript requires both interface definitions and usage to be consistent in a single compilation pass.

## What Was Built

### Selection State (Task 1)

`selectedIds: Set<string>` and `lastToggleAnchor: React.MutableRefObject<string | null>` lifted to `MapBuilderPage`. Three handlers memoized with `useCallback`:

- `handleCmdClick(id)` — toggle id; set anchor; boundary guard first
- `handleShiftClick(id)` — range from anchor to id using `selectableRowIds`; boundary guard per-id
- `handleCheckboxClick(id)` — alias to `handleCmdClick`

All three refuse ids passing `isBasemapBoundaryId()` (checks `basemapGroup.id` and all sublayer ids).

`selectableRowIds` is derived from `layers.localLayers` — the flat ordered array of all overlay layer ids. Basemap group and sublayer ids are structurally excluded because they never appear in `localLayers`.

### Clearing Rules (Task 1)

- **Drag-start**: `handleDragStart` calls `setSelectedIds(new Set())` immediately after `handleSelectLayer(null)`.
- **Outside-click**: `useEffect` keyed on `selectedIds.size` mounts a `document mousedown` listener; guard `stackPanelRef.current?.contains(e.target)` prevents clearing on row clicks; fires `onClearSelection()`.
- **Escape**: same `useEffect` — `keydown` handler fires `onClearSelection()` when `e.key === 'Escape'`.
- **Shift+Arrow**: `keydown` handler detects `e.shiftKey && (ArrowUp | ArrowDown)`, resolves `data-row-id` from `document.activeElement`, computes adjacent index in `selectableRowIds`, calls `onShiftClick(adjacentId)` and moves DOM focus via `stackPanelRef.querySelector`.
- **Route change**: natural unmount — component re-keyed by `mapId`.

### ARIA (Task 1)

`aria-multiselectable="true"` and `aria-label={t('unifiedStack.listboxLabel', { defaultValue: 'Map layers' })}` on the `role="listbox"` element. (Old `aria-multiselectable="false"` removed.)

`data-row-id={layer.id}` on `SortableStackRow` and `FolderGroupRowWrapper` outer divs for Shift+Arrow keyboard navigation.

### Row Components (Task 2)

**StackRow:**
- 5 new optional props: `isMultiSelected`, `isMultiSelectionActive`, `onCmdClick`, `onShiftClick`, `onCheckboxClick`
- `handleRowClick`: Cmd/Ctrl+click → `onCmdClick`; Shift+click → `onShiftClick`; plain → `onSelectLayer`
- `onKeyDown`: Enter → `onSelectLayer`; Space → `onCmdClick` (toggle multi-selection)
- Cell 1: `{isMultiSelectionActive ? <Checkbox .../> : <span hidden>▸</span>}`
- Visual: `(selected || isMultiSelected) && 'bg-[var(--primary-50,...)] shadow-[inset_2px_0_0_var(--primary)]'`
- `aria-selected={selected || isMultiSelected}`

**FolderGroupRow:**
- Same 5 props; same modifier-aware click; same Space handler; caret ↔ Checkbox swap
- Visual tint extends to `isMultiSelected`; `aria-selected` includes multi-state

**BasemapGroupRow:**
- 1 new prop: `isMultiSelectionActive`
- `cursor-not-allowed` appended to row className when `isMultiSelectionActive` is true
- No cmd/shift/checkbox handlers — boundary refusal is at parent level

## Decisions Made

1. **Lifted selectedIds to MapBuilderPage** — direct `setSelectedIds(new Set())` call in `handleDragStart`; mirrors Phase 1040 pattern.
2. **Route-change clearing via unmount** — no `useLocation` watcher; component re-keyed by `mapId`.
3. **Boundary refusal at parent handler level** — `BasemapGroupRow` has no selection handlers; `isBasemapBoundaryId` guard in MapBuilderPage handlers is the single enforcement point.
4. **`onClearSelection` callback prop** — minimal surface for panel to signal parent; avoids ref forwarding complexity.

## Notes for Downstream Plans

- **Plan 02 (BulkActionBar):** Add `t('bulkActions.selectRow', ...)` and `t('bulkActions.selectGroup', ...)` keys to `frontend/src/i18n/locales/en/builder.json`. These i18n keys are referenced with `defaultValue` fallbacks in StackRow and FolderGroupRow respectively — the UI is functional but translation keys are pending.
- **Plan 04 (tests):** Behavior contract for Tests 1-8 (Task 1) and Tests 1-12 (Task 2) defined in PLAN.md `<behavior>` blocks. Selection tests assert on `selectedIds`, `handleCmdClick`, `handleShiftClick`, keyboard events, and basemap boundary refusal.

## Deviations from Plan

**Auto-deviation:** Added `onClearSelection?: () => void` prop to `UnifiedStackPanel` (not in original plan step list, but required because `selectedIds` is lifted to `MapBuilderPage` and the panel's outside-click/Escape handlers cannot call `setSelectedIds` directly). This is a straightforward consequence of the step-8 architecture decision (lift to MapBuilderPage) and does not change behavior.

## Known Stubs

None — all visual and behavioral connections are wired. The `t('bulkActions.selectRow', ...)` keys use `defaultValue` fallbacks until Plan 02 adds them to `en/builder.json`, which is explicitly noted in the plan.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surfaces introduced. Selection state is ephemeral in-memory only.

## Self-Check: PASSED

- `frontend/src/pages/MapBuilderPage.tsx` exists and contains `selectedIds`, `setSelectedIds`, `handleCmdClick`, `handleShiftClick`, `handleCheckboxClick`, `isMultiSelectionActive`
- `frontend/src/components/builder/UnifiedStackPanel.tsx` exists and contains `aria-multiselectable="true"`, `stackPanelRef`, `onClearSelection`, `data-row-id`
- `frontend/src/components/builder/StackRow.tsx` exists and contains `isMultiSelected`, `Checkbox`, `metaKey`, `onCmdClick`
- `frontend/src/components/builder/FolderGroupRow.tsx` exists and contains `isMultiSelected`, `Checkbox`
- `frontend/src/components/builder/BasemapGroupRow.tsx` exists and contains `cursor-not-allowed`, `isMultiSelectionActive`
- Commit `b385578e` exists in git log
- tsc: 0 errors; vitest: 709 passed; build: success
