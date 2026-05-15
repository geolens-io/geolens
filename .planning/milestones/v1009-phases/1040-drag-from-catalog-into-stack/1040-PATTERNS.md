# Phase 1040: drag-from-catalog-into-stack — Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 4 files to modify + 1 CSS rule
**Analogs found:** 4 / 4

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | component | event-driven | `frontend/src/components/builder/StackRow.tsx` (drag handle) + `UnifiedStackPanel.tsx` (useDraggable pattern) | role-match |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | component | event-driven | itself (existing DndContext / DragOverlay / handleDragStart / handleDragEnd) | exact — extend in-place |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | hook | CRUD | itself (`handleAddDataset` at lines 396–420, `handleBasemapSwap` via `setLocalBasemap`) | exact — no new logic needed |
| `frontend/src/index.css` | config | — | itself (lines 512–522: `.dragging-active` rules block) | exact — add rule to existing block |

---

## Pattern Assignments

### `frontend/src/components/builder/DatasetSearchPanel.tsx` (component, event-driven)

**Role:** Add `useDraggable` to each catalog result row (dataset rows and basemap rows). This is a new DnD role for the panel — it currently has no drag behavior.

**Analog for drag handle visual:** `frontend/src/components/builder/StackRow.tsx` lines 173–188

**Grab handle pattern** (lines 173–188 of `StackRow.tsx`):
```tsx
{/* Cell 2: Grip handle */}
<button
  ref={dragHandleProps.setActivatorNodeRef}
  type="button"
  {...dragHandleProps.attributes}
  {...dragHandleProps.listeners}
  aria-label={t('stackRow.dragHandle', {
    defaultValue: 'Drag to reorder {{name}}',
    name: displayName,
  })}
  className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing"
  onPointerDown={(e) => e.stopPropagation()}
  onClick={(e) => e.stopPropagation()}
>
  <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
</button>
```

**Adaptation for DatasetSearchPanel:** Modal rows are flex (not grid), so the handle floats at the left edge inside `px-2` padding. No column reservation. The `aria-label` should use `'Drag to add to map'` per the UI-SPEC copywriting contract (not "drag to reorder").

**Analog for useDraggable:** `UnifiedStackPanel.tsx` uses `useSortable` for intra-stack items. For cross-context catalog drag, the correct primitive is `useDraggable` from `@dnd-kit/core` (not `useSortable`). The import already exists in the package — just not yet imported in `DatasetSearchPanel.tsx`.

**useDraggable call pattern** (mirror of `useSortable` at `UnifiedStackPanel.tsx` lines 143–157, simplified to draggable-only):
```tsx
import { useDraggable } from '@dnd-kit/core';

// Inside each dataset result row component:
const { attributes, listeners, setActivatorNodeRef, isDragging } = useDraggable({
  id: `catalog:${record.id}`,   // namespaced to avoid collisions with stack ids
  data: {
    source: 'catalog',
    datasetId: record.id,
    recordType: props.record_type ?? 'vector_dataset',
    name: props.title,
  },
});
```

**Basemap row useDraggable call pattern:**
```tsx
const { attributes, listeners, setActivatorNodeRef, isDragging } = useDraggable({
  id: `catalog-basemap:${entry.id}`,
  data: {
    source: 'catalog',
    datasetId: entry.id,
    recordType: 'basemap',
    name: entry.label,
  },
});
```

**Row dragging state** (matches `StackRow.tsx` line 154 `isDragging` class):
```tsx
className={cn(
  // existing row classes...
  isDragging && 'opacity-40 bg-[var(--surface-2)]',
)}
```

**dragging-active class pattern** (matches `UnifiedStackPanel.tsx` lines 525–528):
```tsx
// In onDragStart for the catalog DndContext wrapper:
document.documentElement.classList.add('dragging-active');

// In onDragEnd / onDragCancel:
document.documentElement.classList.remove('dragging-active');
```

**DndContext wrapper for DatasetSearchPanel:** The panel itself needs to be wrapped in (or contain) a `DndContext` that can communicate with the stack's `DndContext`. Per `@dnd-kit` cross-context drag pattern, the catalog rows must be draggable items registered in the SAME `DndContext` as the stack drop targets — OR the panel provides its own `DndContext` and the cross-context coordination happens at the page level (`MapBuilderPage`). The simpler approach (no new context) is to lift the `DndContext` up to `MapBuilderPage` so both the catalog rows and the stack share one context. See Shared Patterns section below.

---

### `frontend/src/components/builder/UnifiedStackPanel.tsx` (component, event-driven)

**Role:** Extend existing `DndContext` to accept drops from catalog-sourced draggables (items with `data.source === 'catalog'`). Add group drop-target detection, insertion-line rendering for catalog drags, and basemap group drop detection.

**Analog:** itself — the existing `handleDragStart` / `handleDragEnd` / `DragOverlay` / `dragging-active` pattern is the direct base.

**Existing DragStart pattern** (lines 524–528):
```tsx
const handleDragStart = useCallback((event: DragStartEvent) => {
  setActiveId(String(event.active.id));
  onSelectLayer(null);
  document.documentElement.classList.add('dragging-active');
}, [onSelectLayer]);
```

**Existing DragEnd pattern** (lines 530–540):
```tsx
const handleDragEnd = useCallback((event: DragEndEvent) => {
  setActiveId(null);
  document.documentElement.classList.remove('dragging-active');
  const { active, over } = event;
  if (!over || active.id === over.id) return;
  const oldIndex = layers.findIndex((layer) => layer.id === active.id);
  const newIndex = layers.findIndex((layer) => layer.id === over.id);
  if (oldIndex < 0 || newIndex < 0) return;
  onReorder(arrayMove(layers, oldIndex, newIndex));
}, [layers, onReorder]);
```

**Extended handleDragEnd for cross-context catalog drops:**
```tsx
const handleDragEnd = useCallback((event: DragEndEvent) => {
  setActiveId(null);
  document.documentElement.classList.remove('dragging-active');
  const { active, over } = event;
  if (!over) return;

  // --- Catalog drop (cross-context) ---
  const isCatalogDrag = active.data.current?.source === 'catalog';
  if (isCatalogDrag) {
    const { datasetId, recordType, name } = active.data.current as {
      datasetId: string; recordType: string; name: string;
    };

    if (recordType === 'basemap') {
      // Drop onto basemap group row → swap basemap
      if (String(over.id) === basemapGroup?.id) {
        onBasemapSwap?.(datasetId);   // new callback prop — see Props section
      }
      return;
    }

    // Drop onto a folder-group row → add with parent_group_id
    const targetLayer = layers.find((l) => l.id === String(over.id));
    const isFolderGroup = targetLayer && isFolderGroupLayer(targetLayer);
    const parentGroupId = isFolderGroup ? String(over.id) : null;

    // Use existing onAddDataset callback (already on props)
    onAddDataset?.(datasetId, parentGroupId);
    return;
  }

  // --- Intra-stack reorder (unchanged) ---
  if (active.id === over.id) return;
  const oldIndex = layers.findIndex((layer) => layer.id === active.id);
  const newIndex = layers.findIndex((layer) => layer.id === over.id);
  if (oldIndex < 0 || newIndex < 0) return;
  onReorder(arrayMove(layers, oldIndex, newIndex));
}, [layers, onReorder, basemapGroup, onAddDataset, onBasemapSwap]);
```

**New prop needed on UnifiedStackPanel:**
```tsx
// Add to UnifiedStackPanelProps interface:
onBasemapSwap?: (basemapId: string) => void;
// NOTE: onAddDataset already exists at line 86 but currently only takes (datasetId: string).
// Extend signature to: onAddDataset?: (datasetId: string, parentGroupId?: string | null) => void;
```

**DragOverlay ghost pattern** (lines 793–814 — existing):
```tsx
<DragOverlay dropAnimation={null}>
  {activeId ? (() => {
    const activeLayer = layers.find((l) => l.id === activeId);
    return activeLayer ? (
      <div className="opacity-40 scale-[0.98] pointer-events-none bg-[var(--surface-2)] rounded shadow-md">
        <StackRow
          layer={activeLayer}
          selected={false}
          isDragging={true}
          dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
          onSelectLayer={NOOP}
          onToggleVisibility={NOOP}
          onOpacityChange={NOOP}
          onRemove={NOOP}
          onRename={NOOP}
          onDuplicate={NOOP}
        />
      </div>
    ) : null;
  })() : null}
</DragOverlay>
```

**Catalog ghost (extend DragOverlay conditional):**
```tsx
<DragOverlay dropAnimation={null}>
  {activeId ? (() => {
    // Intra-stack ghost (existing)
    const activeLayer = layers.find((l) => l.id === activeId);
    if (activeLayer) {
      return (
        <div className="opacity-40 scale-[0.98] pointer-events-none bg-[var(--surface-2)] rounded shadow-md">
          <StackRow layer={activeLayer} selected={false} isDragging={true}
            dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
            onSelectLayer={NOOP} onToggleVisibility={NOOP} onOpacityChange={NOOP}
            onRemove={NOOP} onRename={NOOP} onDuplicate={NOOP} />
        </div>
      );
    }
    // Catalog ghost (new) — compact pill: type-icon swatch + name
    if (catalogDragMeta) {
      return (
        <div
          className="pointer-events-none flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 cursor-grabbing"
          style={{ boxShadow: '0 4px 12px oklch(0 0 0 / 15%)', maxWidth: 260, minHeight: 36 }}
        >
          <CatalogTypeIcon recordType={catalogDragMeta.recordType} />
          <span className="truncate text-sm">{catalogDragMeta.name}</span>
        </div>
      );
    }
    return null;
  })() : null}
</DragOverlay>
```

**Group drop-target tint pattern** — group rows receive `isOver` from `useSortable`. For catalog drops onto a folder group, the `FolderGroupRowWrapper`'s `data-dnd-over` attribute triggers the existing CSS at `index.css:515`. The group-specific tint (primary-50 fill + left rail) needs a new CSS data attribute variant or an inline `isGroupDropTarget` prop forwarded to `FolderGroupRow`. The cleanest approach matches the existing `data-dnd-over` pattern in `SortableStackRow` (line 165):
```tsx
// In FolderGroupRowWrapper — already has isOver from useSortable:
<div ref={setNodeRef} style={style} data-group-drop-target={isOver && isCatalogDragActive ? 'true' : undefined}>
  <FolderGroupRow ... />
</div>
```

**Insertion line** — the existing `[data-dnd-over="true"]` rule in `index.css` (line 515–517) produces a 2px `border-top: 2px solid var(--primary)` on the drop target row. This fires for both intra-stack and catalog drags when `isOver` is true on a `SortableStackRow`. No new component needed — the CSS rule already handles it. The executor must verify that `isOver` from `useSortable` activates during a catalog drag (cross-DndContext) — if the stack and catalog share one lifted `DndContext`, it will. If they use separate contexts it will not, confirming the "lift to MapBuilderPage" architecture is required.

---

### `frontend/src/components/builder/hooks/use-builder-layers.ts` (hook, CRUD)

**Role:** Extend `handleAddDataset` to accept an optional `parentGroupId` for group-targeted drops. No new API calls — uses existing `addLayerMutation`.

**Existing handleAddDataset** (lines 396–420):
```ts
const handleAddDataset = useCallback(
  (datasetId: string, onSuccessCb?: (newLayerId: string) => void) => {
    if (!mapId) return;
    addLayerMutation.mutate(
      { mapId, data: { dataset_id: datasetId, sort_order: 0 } },
      {
        onSuccess: (createdLayer) => {
          toast.success(t('toasts.layerAdded'));
          if (onSuccessCb && createdLayer?.id) {
            onSuccessCb(createdLayer.id);
          }
        },
        onError: () => {
          toast.error(t('toasts.layerAddFailed'));
        },
      },
    );
  },
  [mapId, addLayerMutation, t],
);
```

**Extended signature for drag-drop:**
```ts
const handleAddDataset = useCallback(
  (
    datasetId: string,
    onSuccessCb?: (newLayerId: string) => void,
    parentGroupId?: string | null,
  ) => {
    if (!mapId) return;
    addLayerMutation.mutate(
      { mapId, data: { dataset_id: datasetId, sort_order: 0 } },
      {
        onSuccess: (createdLayer) => {
          // If a parentGroupId is provided, wire the created layer into the group
          if (parentGroupId && createdLayer?.id) {
            handleAddLayerToExistingGroup(createdLayer.id, parentGroupId);
          }
          toast.success(t('toasts.layerAdded'));
          if (onSuccessCb && createdLayer?.id) {
            onSuccessCb(createdLayer.id);
          }
        },
        onError: () => {
          toast.error(t('toasts.layerAddFailed'));
        },
      },
    );
  },
  [mapId, addLayerMutation, t, handleAddLayerToExistingGroup],
);
```

**Basemap swap callback** — `setLocalBasemap` is the existing setter (line 69). `handleBasemapChange` already exists via `DatasetSearchPanel`'s `handleBasemapSwap` (lines 285–290 of `DatasetSearchPanel.tsx`). For drag-drop from catalog, the same `onBasemapChange` prop already passed to `DatasetSearchPanel` is reused — no new hook logic needed. The `UnifiedStackPanel` calls the callback, which is wired at `MapBuilderPage` as `layers.setLocalBasemap`.

**Toast keys in use:**
- `t('toasts.layerAdded')` → `"Layer added"` (line 574 of `en/builder.json`)
- `t('toasts.layerAddFailed')` → `"Failed to add layer"` (line 575)

**New toast keys needed** (per UI-SPEC copywriting):
- `t('toasts.datasetAdded', { name })` → `"{name} added to map"`
- `t('toasts.basemapChanged', { name })` → `"Basemap changed to {name}"`

Add to `frontend/src/i18n/locales/en/builder.json` under `"toasts"`:
```json
"datasetAdded": "{{name}} added to map",
"basemapChanged": "Basemap changed to {{name}}"
```

---

### `frontend/src/index.css` (config)

**Role:** Add `.dragging-active .kebab { opacity: 0 !important }` rule for cross-panel catalog drag (AUD-03 finding). Also add group drop-target tint rules and updated insertion line spec per UI-SPEC.

**Existing dragging-active block** (lines 512–522):
```css
/* ── Phase 1038 BSR-24 drag polish ───────────────────────────────────────── */

/* Phase 1038 BSR-24: DnD insertion line — 2px primary line at drop target */
[data-dnd-over="true"] {
  border-top: 2px solid var(--primary);
}

/* Phase 1038 BSR-24: hide kebabs on non-dragging rows during drag */
.dragging-active [data-testid^="stack-row-"] [data-kebab-trigger] {
  opacity: 0 !important;
}
```

**New rules to append after line 522:**
```css
/* Phase 1040: hide kebabs during catalog→stack drag (AUD-03) */
.dragging-active .kebab {
  opacity: 0 !important;
}

/* Phase 1040: cursor-grabbing on html during any drag to prevent flicker */
html.dragging-active {
  cursor: grabbing !important;
}

/* Phase 1040: folder-group drop target — primary-50 tint + left rail */
[data-group-drop-target="true"] {
  background: var(--primary-50, oklch(0.97 0.02 250));
  box-shadow: inset 2px 0 0 var(--primary);
}

/* Phase 1040: basemap group drop target — same tint */
[data-basemap-drop-target="true"] {
  background: var(--primary-50, oklch(0.97 0.02 250));
  box-shadow: inset 2px 0 0 var(--primary);
}
```

---

## Shared Patterns

### DndContext Architecture (lift to MapBuilderPage)

**Source:** `UnifiedStackPanel.tsx` lines 703–815 (current DndContext wraps only the stack list)

**The cross-context problem:** `@dnd-kit` collision detection only fires between items in the SAME `DndContext`. If `DatasetSearchPanel` (inside a Sheet) and `UnifiedStackPanel` (in the sidebar) each have their own `DndContext`, `onDragOver` and `isOver` from `useSortable` in the stack will never fire during a catalog drag.

**Solution pattern:** Lift a single `DndContext` to `MapBuilderPage`, wrapping both the sidebar column (containing `UnifiedStackPanel`) and the Sheet (containing `DatasetSearchPanel`). The `UnifiedStackPanel` `DndContext` at line 703 is removed and replaced by props threaded from the lifted context (`sensors`, `activeId`, event handlers).

**Analog for lifted DndContext:** `PopupConfigEditor.tsx` uses its own `DndContext` for field reorder (a contained case). The pattern for prop-threading the lifted context follows the standard `@dnd-kit` multi-container pattern. No existing analog in this codebase — planner should use `@dnd-kit` docs pattern as reference.

### Toast Pattern

**Source:** `frontend/src/components/builder/hooks/use-builder-layers.ts` lines 268–274, 408–415

**Apply to:** All drag-drop success/error paths in `UnifiedStackPanel.tsx` (or the lifted handler in `MapBuilderPage`)

```ts
import { toast } from 'sonner';

// Success
toast.success(t('toasts.datasetAdded', { name }));

// Success with dedup key (UI-SPEC requirement)
toast.success(t('toasts.datasetAdded', { name }), { id: `add-layer-${datasetId}` });

// Error
toast.error(t('toasts.addLayerFailed', { defaultValue: 'Failed to add layer — try again' }));
```

**Error dedup key:** Use `id: 'add-layer-${datasetId}'` to prevent duplicate toasts when the user drags the same dataset multiple times quickly. Pattern matches `BuilderMap.tsx` lines 390–400 `id: 'builder-map-auth-error'`.

### handleAddDataset Callback Wiring

**Source:** `MapBuilderPage.tsx` lines 662–665

```tsx
onAddDataset={(datasetId: string) => {
  layers.handleAddDataset(datasetId, (newLayerId) => {
    handleSelectLayer(newLayerId);
  });
}}
```

**For drag-drop:** The same wiring is used but the `onSuccessCb` is omitted (modal stays open, no auto-select flyout on drag-drop per UI-SPEC § 5). The `parentGroupId` is threaded as the third argument:

```tsx
// In the lifted onDragEnd handler:
layers.handleAddDataset(datasetId, undefined, parentGroupId ?? null);
```

### Keyboard Sensor

**Source:** `UnifiedStackPanel.tsx` lines 508–512

```tsx
useSensor(KeyboardSensor, {
  coordinateGetter: sortableKeyboardCoordinates,
}),
```

**Apply to:** The lifted `DndContext` sensors array. `sortableKeyboardCoordinates` is already imported from `@dnd-kit/sortable`. The keyboard sensor is reused as-is; Space/Arrow/Enter/Escape are handled by `@dnd-kit` natively. The ARIA live region announcement (`aria-live="polite"`) for keyboard position is a new element — no existing analog; planner should create a new hidden `<div aria-live="polite" aria-atomic="true">` in `MapBuilderPage` or `DatasetSearchPanel`.

### handleBasemapSwap in DatasetSearchPanel

**Source:** `DatasetSearchPanel.tsx` lines 285–290

```tsx
function handleBasemapSwap(entry: BasemapEntry) {
  const nextConfig = normalizeBasemapConfig(basemapConfig, showBasemapLabels);
  onBasemapChange(entry.id);
  onBasemapLabelsChange(nextConfig.label_mode !== 'hidden');
  onBasemapConfigChange(nextConfig);
}
```

**For drag-drop basemap swap:** The drag path calls the same `onBasemapChange(entry.id)` callback — no new prop needed. The `UnifiedStackPanel` receives a new `onBasemapSwap?: (basemapId: string) => void` prop wired to a shim in `MapBuilderPage` that calls `handleBasemapSwap` with the matching `BasemapEntry`. Alternative: pass the full entry via `active.data.current` so the handler can call `handleBasemapSwap` directly.

---

## Test Analog

**Source:** `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` lines 1–80

**Pattern for new drag-drop tests:**
```tsx
import { fireEvent, render, screen } from '@/test/test-utils';
// vi.mock react-i18next (same block as UnifiedStackPanel.test.tsx lines 5–21)
// vi.mock layer-icons (same block as lines 23–29)

it('fires onAddDataset when a catalog drag is dropped on the stack', async () => {
  const onAddDataset = vi.fn();
  render(<UnifiedStackPanel ... onAddDataset={onAddDataset} />);
  // Simulate DnD drop via fireEvent or @testing-library/user-event pointer events
  // Verify onAddDataset called with (datasetId, null) for loose insert
  expect(onAddDataset).toHaveBeenCalledWith('dataset-id', null);
});
```

**Vitest worker-exit risk note:** Per comments in `use-builder-layers.add-dataset.test.ts` lines 1–59: avoid file-local `vi.mock` blocks for transitive deps (react-router, sonner, etc.). Prefer the shared `renderHook` from `@/test/test-utils`. If the test file mocks many modules, it will trigger the V8 heap OOM that Phase 1039 fixed.

---

## No Analog Found

No files in this phase are entirely novel — all files modify existing surfaces with existing DnD infrastructure already present.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | All modifications extend existing patterns |

The only partially-novel element is the **lifted cross-context DndContext** architecture. No existing example in this codebase lifts a `DndContext` above two sibling panel components. The `@dnd-kit` multi-container sortable example is the external reference for this pattern — the planner should reference that when structuring the lifted context at `MapBuilderPage`.

---

## Metadata

**Analog search scope:** `frontend/src/components/builder/`, `frontend/src/components/builder/hooks/`, `frontend/src/index.css`, `frontend/src/i18n/locales/en/builder.json`
**Files scanned:** 8 source files read in full; 4 grep searches
**Pattern extraction date:** 2026-05-14
