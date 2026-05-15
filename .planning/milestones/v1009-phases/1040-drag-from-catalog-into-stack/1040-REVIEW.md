---
phase: 1040-drag-from-catalog-into-stack
reviewed: 2026-05-14T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - frontend/src/components/builder/DatasetSearchPanel.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts
  - frontend/src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/index.css
  - frontend/src/pages/MapBuilderPage.tsx
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 1040: Code Review Report

**Reviewed:** 2026-05-14
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Phase 1040 implements cross-panel drag-and-drop from the catalog modal (DatasetSearchPanel) into the unified layer stack. The architecture is sound: lifting DndContext to MapBuilderPage, adding useDraggable on catalog rows, extending handleAddDataset with parentGroupId, and wiring five catalog-drop cases in handleDragEnd. Most of the implementation is well-reasoned and follows existing conventions correctly.

Two blockers were found: a race condition where the aria-live "drop success" announcement fires before the async mutation resolves (making the announcement a false positive for errors), and the new layer not yet being in localLayers when handleAddLayerToExistingGroup is called inside onSuccess, making group-drop an unreliable no-op. Four warnings address collision detection choice, a drag source component receiving setNodeRef without it serving a functional role, a `key` prop mismatch on the outer div versus the row component, and test coverage gaps around the actual drop success path. Three info items address minor code quality issues.

---

## Critical Issues

### CR-01: "Drop success" aria-live announcement fires before async mutation resolves — false positive for screen readers on error

**File:** `frontend/src/pages/MapBuilderPage.tsx:495-496`

**Issue:** `announce(t('a11y.dragDropped', ...))` is called immediately after `layers.handleAddDataset(datasetId, ...)` at line 495-496. `handleAddDataset` is an async mutation — the actual success or failure is determined inside the `onSuccess` / `onError` callbacks of `addLayerMutation.mutate` (in `use-builder-layers.ts:412-434`). The announce call at line 496 always fires "Dropped. {name} added at position {n}" regardless of whether the network request succeeds or fails. When the mutation errors (e.g., network failure, 403), the `toast.error(t('toasts.layerAddFailed'))` fires correctly, but the screen reader has already announced a success. A screen-reader user is told "Dropped. MyDataset added at position 3" and then hears a separate error toast — the two are contradictory and confusing.

**Fix:** Move the success announcement into the `onSuccess` callback of `handleAddDataset`. The cleanest path is to thread it through the existing `onSuccessCb` parameter:

```typescript
// in handleDragEnd, replace lines 495-496:
layers.handleAddDataset(datasetId, () => {
  announce(t('a11y.dragDropped', { name: datasetName, n: dropPosition > 0 ? dropPosition : 1 }));
}, parentGroupId, datasetName);
```

For the error case, the hook already fires `toast.error(t('toasts.layerAddFailed'))` — the drag cancel announcement can also be added there (or a dedicated `onErrorCb` param added to `handleAddDataset`).

---

### CR-02: handleAddLayerToExistingGroup is called before the new layer exists in localLayers — group drop silently no-ops for the first drag

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:412-417`

**Issue:** When a catalog dataset row is dropped onto a folder group (Case 4 in handleDragEnd), the flow is:

1. `addLayerMutation.mutate(...)` fires the POST to `/maps/{id}/layers`
2. In `useAddLayer` (`use-maps.ts:140-142`), the global `onSuccess` fires first: `qc.invalidateQueries(...)`. This schedules a refetch of the map detail query, but does **not** await it.
3. The per-call `onSuccess` fires next (`use-builder-layers.ts:412`): `handleAddLayerToExistingGroup(createdLayer.id, parentGroupId)` is called.
4. `handleAddLayerToExistingGroup` calls `setLocalLayers(prev => ...)` and searches for `createdLayer.id` in `prev` at line 362: `const targetIdx = prev.findIndex((l) => l.id === layerId)`.
5. The new layer is **not in `localLayers` yet** — it only appears after the invalidation refetch resolves AND is synced in the `useEffect` at `use-builder-layers.ts:126-131`. That sync only runs when `!hasUnsavedChanges`.
6. `targetIdx` is `-1`, the early-return fires (`if (targetIdx < 0) return prev`), and the group assignment is silently dropped.

The layer IS added to the map, but its `parent_group_id` is never set, so it appears as a loose layer at the top rather than inside the target folder group.

**Fix:** The group wiring must happen after the layer is in localLayers. The cleanest approach is to apply the group assignment inside the same `setLocalLayers` updater that processes the refetch result, or to optimistically add the layer to localLayers in the `onSuccess` before calling group wiring:

```typescript
// In handleAddDataset onSuccess:
onSuccess: (createdLayer) => {
  if (parentGroupId && createdLayer?.id) {
    // Optimistically add the layer to localLayers first, THEN group it
    setLocalLayers((prev) => {
      // Check if already present (refetch may have beaten us)
      if (prev.some((l) => l.id === createdLayer.id)) return prev;
      const newLayer: GroupedLayer = {
        ...createdLayer,
        parent_group_id: parentGroupId,
      };
      return [newLayer as MapLayerResponse, ...prev];
    });
    // Now group wiring will find the layer
    handleAddLayerToExistingGroup(createdLayer.id, parentGroupId);
  }
  // ... toast, onSuccessCb
}
```

Alternatively, merge the group assignment directly into the optimistic layer add so only one `setLocalLayers` call is needed.

---

## Warnings

### WR-01: closestCenter collision detection is suboptimal for cross-panel drag — causes ghost to "snap" to wrong drop target

**File:** `frontend/src/pages/MapBuilderPage.tsx:792`

**Issue:** The lifted DndContext uses `collisionDetection={closestCenter}`. `closestCenter` computes distance from the pointer to the **center** of each droppable, which works well for a contained sortable list. For the cross-panel case, where the catalog ghost is dragged from the modal Sheet (which may be positioned over or near the stack panel), `closestCenter` can activate the wrong drop target when multiple droppables (a loose row, a folder group row, and the basemap group row) have overlapping bounding boxes as seen from the pointer's perspective. The `pointerWithin` strategy — which only considers droppables whose rectangle actually contains the pointer — is more correct for this scenario. The spec in PATTERNS.md references `closestCenter` as carried over from the intra-stack case (Plan 01 comment "preserve activationConstraint distance:8 and closestCenter verbatim"), but that verbatim preservation was appropriate for intra-stack reorder, not the new cross-panel drop surface.

**Fix:**
```typescript
import { pointerWithin, closestCenter } from '@dnd-kit/core';

// Use pointerWithin as primary strategy, fall back to closestCenter for
// keyboard navigation (keyboard doesn't move pointer into droppable rects)
<DndContext
  collisionDetection={(args) =>
    pointerWithin(args).length > 0 ? pointerWithin(args) : closestCenter(args)
  }
  ...
>
```

---

### WR-02: `key` prop on DraggableDatasetRow outer `div` duplicates the memo component's `key` — causes reconciler confusion on list re-renders

**File:** `frontend/src/components/builder/DatasetSearchPanel.tsx:233`

**Issue:** At line 233, the outer `<div ref={setNodeRef}` inside `DraggableDatasetRow` has `key={record.id}`. This is a component-internal element — `key` on an element inside a component body is redundant and ignored by React (keys on JSX inside `return` that are not array siblings do nothing). More importantly, the wrapping `<DraggableDatasetRow key={record.id}` at line 701 is already keyed correctly for list reconciliation. The inner `key={record.id}` at line 233 is inside the memo component's render and is not part of a list mapping, so it has no effect and is misleading. This applies identically to `DraggableBasemapRow` (line 324). If a future maintainer sees `key={record.id}` on the div and assumes it is meaningful, they may incorrectly conclude removing the outer key is safe.

**Fix:** Remove the `key` prop from the inner `div` in both `DraggableDatasetRow` (line 233) and `DraggableBasemapRow` (line 324). The list-level keys on the outer component invocations at lines 693-708 are where keys belong.

```tsx
// Remove key={record.id} — it does nothing inside a component body
<div
  ref={setNodeRef}
  className={cn(...)}
>
```

---

### WR-03: Announce timing for basemap-swap success also fires before synchronous state setters complete — minor ordering issue

**File:** `frontend/src/pages/MapBuilderPage.tsx:472`

**Issue:** For the basemap swap case (Case 1, line 463-474), `layers.setLocalBasemap`, `layers.setShowBasemapLabels`, `layers.setBasemapConfig`, and `layers.markDirty` are called synchronously before `announce`. This is correct ordering for synchronous setters — however, the announce fires "Dropped. {name} added at position 1" for a basemap swap. The basemap swap is not adding a layer at a position; it is replacing the current basemap. The `n: 1` argument hardcoded on line 472 maps to the i18n key `a11y.dragDropped` → "Dropped. {{name}} added at position {{n}}." — which reads as "Dropped. Positron added at position 1." This is semantically wrong for a basemap swap.

**Fix:** Use a distinct i18n key for basemap swap success, or override with `defaultValue`:

```typescript
// Either add a new key to builder.json:
// "dragBasemapDropped": "Dropped. Basemap changed to {{name}}."
announce(t('a11y.dragBasemapDropped', { name: datasetName, defaultValue: 'Basemap changed to {{name}}.' }));

// Or reuse basemapChanged copy since the toast already uses it:
announce(t('toasts.basemapChanged', { name: datasetName }));
```

---

### WR-04: Test G for `datasetName` only asserts no-throw — does not verify the named toast key is used vs. fallback

**File:** `frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts:240-251`

**Issue:** Test G ("datasetName provided causes named toast key path (no throw)") calls `handleAddDataset('ds-42', undefined, null, 'My Dataset')` and asserts only that `onSuccess` does not throw. It does not verify that the `toasts.datasetAdded` key is called with `{ name: 'My Dataset' }` instead of the fallback `toasts.layerAdded`. This means a regression where `datasetName` is ignored and the generic toast always fires would not be caught. The toast is triggered inside the mutation's `onSuccess` callback (line 421-427 of `use-builder-layers.ts`) which the test already drives correctly.

**Fix:** Spy on `toast.success` and assert the named key:

```typescript
it('Test G: datasetName provided causes named toast key path', () => {
  const successSpy = vi.spyOn(toast, 'success');
  const layer = makeMockLayer();
  const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

  act(() => {
    result.current.handleAddDataset('ds-42', undefined, null, 'My Dataset');
  });

  const [, { onSuccess }] = mutate.mock.calls[0];
  act(() => { onSuccess({ id: 'new-layer-id' }); });

  // Should have called with the dataset-specific key (interpolated by the i18n mock)
  expect(successSpy).toHaveBeenCalledWith(
    expect.stringContaining('My Dataset'),
    expect.objectContaining({ id: 'add-layer-ds-42' }),
  );
});
```

---

## Info

### IN-01: ZWS character embedded literally in source — fragile and invisible

**File:** `frontend/src/pages/MapBuilderPage.tsx:99`

**Issue:** The `announce` callback appends `'​'` (a zero-width space, U+200B) as a literal character in the source string to force aria-live re-fire. The comment at line 92-94 explains the intent, but the ZWS itself is invisible in the source and will be silently stripped by some auto-formatters or linters. If the ZWS is removed, duplicate identical announcements (e.g., two rapid "Drop cancelled." calls) will be silently swallowed by the aria-live region because the DOM content does not change.

**Fix:** Use an explicit Unicode escape to make the intent visible and lint-safe:

```typescript
const announce = useCallback((text: string) => {
  // ​ = zero-width space; forces aria-live re-fire for identical consecutive strings
  setDragAnnouncement(text + '​' + Date.now());
}, []);
```

---

### IN-02: `DraggableDatasetRow` receives `setNodeRef` from `useDraggable` but the outer div is not the activation element — the handle's `setActivatorNodeRef` already registers the pointer target

**File:** `frontend/src/components/builder/DatasetSearchPanel.tsx:232`

**Issue:** `useDraggable` returns both `setNodeRef` (the "draggable element" ref, used by @dnd-kit for size/position measurement during drag) and `setActivatorNodeRef` (the pointer-event activation target). In `DraggableDatasetRow`, `setNodeRef` is placed on the outer card `<div>` (line 232) and `setActivatorNodeRef` on the grip button (line 242). This is the correct pattern per @dnd-kit docs. However, the outer card div does not receive `{...attributes}` or `{...listeners}` — only the button does. This means pointer events on the card body (not the grip handle) will NOT start a drag, which is correct per UI-SPEC §1 ("grab handle is the ONLY new affordance"). This is not a bug, but the code could be confusing because `setNodeRef` on the outer div looks like it should make the whole row draggable. A comment clarifying the distinction would help future maintainers.

**Fix:** Add a comment:
```tsx
<div
  ref={setNodeRef}  {/* registers element for @dnd-kit size measurement only; drag activation is on the grip button below */}
  className={...}
>
```

---

### IN-03: Missing `popup_config` and `is_dem` fields in `makeMockLayer` fixture — will cause TypeScript errors if strict MapLayerResponse type is tightened

**File:** `frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts:69-93`

**Issue:** `makeMockLayer` omits several optional fields that exist on `MapLayerResponse` (`popup_config`, `is_dem`, `dem_vertical_units`, `show_in_legend`). Currently these are optional (`?`) in the type, so TypeScript passes. If the type is tightened to require these (or if a new required field is added), the fixture will fail silently at the type level. The `satisfies MapLayerResponse` operator is not used, so type drift goes undetected.

**Fix:** Use `satisfies` or add the missing optional fields to the factory:

```typescript
function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    // ... existing fields
    popup_config: null,
    show_in_legend: true,
    is_dem: null,
    dem_vertical_units: null,
    ...overrides,
  } satisfies MapLayerResponse;
}
```

---

_Reviewed: 2026-05-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
