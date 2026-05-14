---
phase: 1041-multi-layer-selection-and-bulk-ops
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 1041: Code Review Report

**Reviewed:** 2026-05-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 1041 delivers multi-layer selection, a bulk action bar, and five bulk operation handlers. The selection model (Cmd/Shift/Space/Arrow), checkbox visual, basemap boundary refusal, and outside-click clearing are all structurally sound. The BulkActionBar confirmation state machine, `autoFocus` on Cancel, and `role="alertdialog"` are implemented correctly.

Two blockers were found:

1. `handleBulkDelete` sends API requests for synthetic `group-XXXXXXXXXX` IDs that exist only in the frontend. Because `isBasemapBoundaryId` does not block folder-group rows from entering `selectedIds`, any user who Cmd-clicks a folder-group row and then hits Delete will always get a 404 rollback and a misleading "Failed to delete" toast.

2. The Escape + Shift+Arrow `keydown` listener is attached to `document`, not to the stack panel element, despite the inline comment claiming otherwise. This means an Escape key pressed anywhere on the page (e.g., inside the LayerEditorPanel flyout, inside a form input in the right rail) clears the multi-selection, violating the UI-SPEC's "Escape key anywhere in the stack panel" scope constraint.

---

## Critical Issues

### CR-01: handleBulkDelete calls removeLayerFromMapApi with synthetic folder-group IDs

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:519-551`

**Issue:** `handleBulkDelete` converts `selectedIds` to `idsToDelete = Array.from(selectedIds)` with no filtering at all. Folder-group rows have synthetic IDs of the form `group-${Date.now()}` that live only in frontend memory — they are never persisted to the backend. `isBasemapBoundaryId` in `MapBuilderPage` blocks only basemap IDs; it does not block `group:folder` rows from entering `selectedIds`. A user can Cmd-click any `FolderGroupRow` (which calls `handleCmdClick` → passes the basemap check → adds the ID), then click Delete → the confirmation fires → `removeLayerFromMapApi(mapId, 'group-1234567890')` → HTTP 404 → `anyFailed = true` → rollback → toast "Failed to delete N layers". The user cannot recover this way because the group ID will never exist on the backend. If the selection is *only* group-folder rows (e.g., via `canUngroup=true` selection), the Delete button is enabled and the operation always fails.

**Fix:** Add a guard in `handleBulkDelete` (and optionally in `handleCmdClick`/`isBasemapBoundaryId`) to filter out synthetic group rows before building `idsToDelete`:

```typescript
// In handleBulkDelete, after line 523:
const idsToDelete = Array.from(selectedIds).filter((id) => {
  const layer = previousLayers.find((l) => l.id === id);
  // Exclude frontend-only group container rows — they have no backend record
  if (!layer) return false;
  if ((layer as GroupedLayer).layer_type === 'group:folder') return false;
  return true;
});
if (idsToDelete.length === 0) return false;
```

Alternatively (and more defensively), extend `isBasemapBoundaryId` to also return `true` for any ID whose layer has `layer_type === 'group:folder'`, so the selection model rejects them at the source. The BulkActionBar's Delete button disable-rule should also exclude selections containing group rows (it already disables Group when groups are selected, but Delete has no such gate).

---

### CR-02: Escape (and Shift+Arrow) keydown listener is attached to `document`, not the stack panel element

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:655-690`

**Issue:** The comment at line 655 reads: *"Both listeners are scoped to the stack panel element (not document) for Shift+Arrow so they don't interfere with global keyboard shortcuts when focus is outside the panel."* The implementation at line 687 contradicts this: `document.addEventListener('keydown', handleKeyDown)`. Because this listener fires for all `keydown` events on the page whenever `selectedIds.size > 0`, pressing Escape anywhere — inside a rename input in the LayerEditorPanel, in a form in the AI chat rail, in a Radix dropdown — will call `onClearSelection()` and lose the user's multi-selection. The UI-SPEC (§6) says: *"Escape key (anywhere in the stack panel) | Clear selectedIds"* — scope is the stack panel, not the document.

Note: The BulkActionBar's own `handleContainerKeyDown` stops propagation for Escape when `confirmingDelete === true`, so that specific path is unaffected. But all other Escape events page-wide are not stopped.

**Fix:** Attach the Escape + Shift+Arrow listener to the `stackPanelRef` element rather than `document`:

```typescript
useEffect(() => {
  if (selectedIds.size === 0) return;
  const el = stackPanelRef.current;
  if (!el) return;
  function handleKeyDown(e: KeyboardEvent) { /* same body */ }
  el.addEventListener('keydown', handleKeyDown);
  return () => el.removeEventListener('keydown', handleKeyDown);
}, [selectedIds.size, selectableRowIds, onClearSelection, onShiftClick]);
```

The `stackPanelRef` is already the `ref` on the `role="listbox"` div. For rows to receive keyboard events on that element, the rows (which have `tabIndex={0}`) need to be inside this div — they are, so events will bubble up to it. The Escape listener for the `mousedown` outside-click handler should remain on `document` (that is correct and by design).

---

## Warnings

### WR-01: handleBulkDelete in MapBuilderPage has no `.catch()` — unhandled promise rejection risk

**File:** `frontend/src/pages/MapBuilderPage.tsx:397-402`

**Issue:**
```typescript
const handleBulkDelete = useCallback((ids: Set<string>) => {
  layers.handleBulkDelete(ids).then((ok) => {
    if (ok) setSelectedIds(new Set());
  });
}, [layers]);
```
`handleBulkDelete` in `use-builder-layers.ts` is `async` and ends with `await queryClient.invalidateQueries(...)`. If `invalidateQueries` throws (e.g., network error during cache sync), the returned `Promise<boolean>` rejects. The `.then()` branch is skipped and the rejection is unhandled, producing an unhandled promise rejection in the browser console and potentially a React error boundary catch depending on the version.

**Fix:**
```typescript
const handleBulkDelete = useCallback((ids: Set<string>) => {
  layers.handleBulkDelete(ids)
    .then((ok) => { if (ok) setSelectedIds(new Set()); })
    .catch(() => {
      // Error already toasted inside handleBulkDelete; swallow here to prevent
      // unhandled rejection if invalidateQueries throws after allSettled.
    });
}, [layers]);
```

---

### WR-02: `aria-live="polite"` is placed on the entire BulkActionBar toolbar container

**File:** `frontend/src/components/builder/BulkActionBar.tsx:108-121`

**Issue:** `aria-live="polite"` is set on the `role="toolbar"` div. This causes screen readers to announce the entire toolbar content whenever any part of it changes — not just the selection count, but also button disable state flips, icon changes (Eye ↔ EyeOff), and slider value updates. The UI-SPEC (§7) specifies: *"The aria-live region announces: '{N} layers selected.' (polite — does not interrupt ongoing speech)."* This implies a dedicated minimal-content announcement region, not the entire toolbar.

Additionally, `bulkActions.liveAnnouncement` is defined in all four locale files and matches the spec's wording exactly, but is never referenced in the component code — it is a dead i18n key.

**Fix:** Replace with a dedicated `sr-only` announcement span that updates only the count:

```tsx
{/* sr-only live region for count changes only */}
<span className="sr-only" aria-live="polite" aria-atomic="true">
  {t('bulkActions.liveAnnouncement', { count: N })}
</span>
```

Remove `aria-live="polite"` from the toolbar container itself (a `role="toolbar"` element should not also carry `aria-live`).

---

### WR-03: `onClearSelection` prop in `BulkActionBarProps` is required but never called

**File:** `frontend/src/components/builder/BulkActionBar.tsx:17,40`

**Issue:** `onClearSelection: () => void` is declared as a non-optional prop in `BulkActionBarProps`. It is destructured as `_onClearSelection` (underscore prefix signals intentional non-use), and is never invoked anywhere in the component. Every call site must pass it, creating a confusing API surface — callers expect it to be called, but it is silently dead. The prop was included in the PATTERNS.md skeleton but the component's actual clearing behavior is handled entirely through the parent's `handleBulk*` wrappers in `MapBuilderPage`.

**Fix:** Remove `onClearSelection` from `BulkActionBarProps` entirely, or make it optional and document that clearing is the caller's responsibility:

```typescript
// Option A: Remove entirely
export interface BulkActionBarProps {
  selectedIds: Set<string>;
  layers: MapLayerResponse[];
  // onClearSelection removed — parent clears via handleBulk* callbacks
  onBulkVisibility: (ids: Set<string>) => void;
  // ...
}

// Option B: Make optional with JSDoc
/** @optional Called if the bar needs to explicitly request selection clear (e.g., future X button) */
onClearSelection?: () => void;
```

---

### WR-04: `handleBulk*` callbacks in MapBuilderPage depend on the `layers` return object — new reference on every render

**File:** `frontend/src/pages/MapBuilderPage.tsx:373-402`

**Issue:** All five `handleBulk*` callbacks use `[layers]` as the `useCallback` dependency. `layers` is the return value of `useBuilderLayers(...)`, which is a plain object literal re-created on every render. This means all five callbacks are recreated on every render — including every opacity slider move, visibility toggle, or layer selection change. These callbacks are passed to `UnifiedStackPanel` and `BulkActionBar`, both of which are `memo`-wrapped. The new callback references defeat `memo` on every render cycle.

Each individual handler (`layers.handleBulkVisibility`, etc.) is itself a stable `useCallback` from `use-builder-layers.ts`. The fix is to depend on the specific stable handler, not the entire `layers` object:

```typescript
const handleBulkVisibility = useCallback((ids: Set<string>) => {
  layers.handleBulkVisibility(ids);
  setSelectedIds(new Set());
}, [layers.handleBulkVisibility]);  // stable — from useCallback in use-builder-layers

const handleBulkDelete = useCallback((ids: Set<string>) => {
  layers.handleBulkDelete(ids).then(/* ... */).catch(/* ... */);
}, [layers.handleBulkDelete]);
```

Note: performance issues are nominally out of v1 scope, but this specific pattern actively breaks the `memo` contract for `BulkActionBar` and `UnifiedStackPanel`, which can cause visible re-renders during slider drag events that fire at ~60fps.

---

## Info

### IN-01: Misleading inline comment claims keydown listener is stack-panel-scoped

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:654-656`

**Issue:** The comment directly above the second `useEffect` reads: *"Both listeners are scoped to the stack panel element (not document) for Shift+Arrow so they don't interfere with global keyboard shortcuts when focus is outside the panel."* The implementation attaches to `document` (line 687), not to `stackPanelRef.current`. Even if the Escape-scope bug (CR-02) is fixed, this comment must be updated to accurately reflect the listener target.

**Fix:** After applying the CR-02 fix (moving the listener to `stackPanelRef`), the comment becomes accurate. If only the comment is updated without the fix, change it to: *"Both listeners are on document; the Shift+Arrow handler guards with closest('[data-row-id]') so it no-ops when focus is outside the panel."*

---

### IN-02: `unifiedStack.listboxLabel` i18n key is used in code but not defined in any locale file

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:848`

**Issue:** `t('unifiedStack.listboxLabel', { defaultValue: 'Map layers' })` references a key that does not exist in `en/builder.json`, `de/builder.json`, `es/builder.json`, or `fr/builder.json`. The `defaultValue` fallback means the UI renders correctly, but the key is untranslatable. The SUMMARY notes this as a known gap (Plan 01 added the key with a defaultValue; Plan 02 was supposed to add the translation). This gap was not closed during Phase 1041.

**Fix:** Add to all four locale files under the `unifiedStack` namespace (first occurrence only, given the pre-existing duplicate-block issue):

```json
"unifiedStack": {
  ...existing keys...
  "listboxLabel": "Map layers"
}
```

---

### IN-03: Dead `console.warn` stubs documented but confirmed removed — pre-existing TODOs remain in MapBuilderPage

**File:** `frontend/src/pages/MapBuilderPage.tsx:238,242,422,432`

**Issue:** Multiple `TODO(Phase 1038)` comments remain in `MapBuilderPage.tsx` marking unimplemented persistence paths for `sublayerState`, `masterOpacity`, and sublayer styling. These are pre-existing from Phase 1035 and are documented as intentional deferrals. They are noted here for visibility — Phase 1038 should address them before any public release of basemap sublayer styling features.

**Fix:** Defer to Phase 1038 (as intended). No action required in Phase 1041.

---

_Reviewed: 2026-05-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
