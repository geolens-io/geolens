---
phase: 1040
plan: "02"
subsystem: frontend/dnd
tags:
  - dnd
  - drag-drop
  - catalog
  - mapbuilder
  - frontend
dependency_graph:
  requires:
    - "Phase 1040 Plan 01 (DndContext lifted to MapBuilderPage; basemap row useDroppable)"
  provides:
    - "useDraggable on every dataset and basemap row in DatasetSearchPanel"
    - "Cross-context catalog drop handler in MapBuilderPage.handleDragEnd"
    - "i18n keys: toasts.datasetAdded, toasts.basemapChanged, search.dragHandle"
  affects:
    - "frontend/src/components/builder/DatasetSearchPanel.tsx"
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
tech_stack:
  added: []
  patterns:
    - "useDraggable (not useSortable) for cross-context drag source items"
    - "Memo-wrapped inner components (DraggableDatasetRow, DraggableBasemapRow) to bound re-renders"
    - "data.source='catalog' namespace for drag payload discrimination in handleDragEnd"
key_files:
  created: []
  modified:
    - "frontend/src/components/builder/DatasetSearchPanel.tsx"
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/i18n/locales/en/builder.json"
decisions:
  - "useDraggable (not useSortable) used for catalog rows — they are drag sources only, not sortable within the modal"
  - "DraggableDatasetRow and DraggableBasemapRow are memo-wrapped named functions at module scope — hooks are valid inside named function components"
  - "Toast upgrade to toasts.datasetAdded deferred to Plan 03 per plan spec — hook's existing layerAdded toast fires for catalog drops"
  - "Plan 03 placeholder early-returns added for basemap group drop and folder-group drop to keep Plan 02 scope to loose-row adds"
  - "No DndContext wrapper added to DatasetSearchPanel.test.tsx — @dnd-kit/core useDraggable does not throw without a context in jsdom test environment"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 1040 Plan 02: Catalog row useDraggable + loose-row drop Summary

**One-liner:** useDraggable wired to all DatasetSearchPanel rows (catalog:{id} / catalog-basemap:{id} namespace); MapBuilderPage.handleDragEnd branches on data.source='catalog' and calls handleAddDataset without closing the modal (POL-01/02/05).

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add toast i18n keys (datasetAdded + basemapChanged + search.dragHandle) | `c7f6874e` | `frontend/src/i18n/locales/en/builder.json` |
| 2 | Wire useDraggable to dataset and basemap rows in DatasetSearchPanel | `dcc2e1c2` | `frontend/src/components/builder/DatasetSearchPanel.tsx` |
| 3 | Extend MapBuilderPage handleDragEnd for catalog source (loose-row drop) | `1c7be26d` | `frontend/src/pages/MapBuilderPage.tsx` |

## Architecture: Catalog Drag Data Flow

```
DatasetSearchPanel row (useDraggable)
  id: "catalog:{datasetId}" | "catalog-basemap:{basemapId}"
  data: { source: 'catalog', datasetId, recordType, name }
        |
        | cross-context drag within the lifted DndContext (Plan 01)
        v
MapBuilderPage.handleDragEnd
  active.data.current?.source === 'catalog'
    → datasetId extracted
    → basemapGroup drop: early-return (Plan 03)
    → folderGroup drop: early-return (Plan 03)
    → loose-row drop: layers.handleAddDataset(datasetId)  ← modal stays open (POL-05)
```

## i18n Keys Added

| Namespace | Key | Value |
|-----------|-----|-------|
| toasts | datasetAdded | "{{name}} added to map" |
| toasts | basemapChanged | "Basemap changed to {{name}}" |
| search | dragHandle | "Drag to add to map" |

Note: `toasts.datasetAdded` and `toasts.basemapChanged` are added now (co-located with the file change) but consumed starting in Plan 03 when the hook signature is extended for parentGroupId. Plan 02 uses the existing `toasts.layerAdded` generic toast via the hook's mutation onSuccess handler.

## Draggable Namespace Design

| Row Type | Draggable ID | data.recordType |
|----------|-------------|-----------------|
| Vector / raster dataset | `catalog:{record.id}` | `props.record_type ?? 'vector_dataset'` |
| Basemap entry | `catalog-basemap:{entry.id}` | `'basemap'` |

The `catalog:` prefix guarantees no collision with intra-stack sortable ids (which are plain UUIDs / `'basemap-group'`).

## Grip Handle Visual

- Hidden at rest (`opacity-0`)
- Appears on row hover (`group-hover/row:opacity-35`)
- Full opacity on direct hover/focus (`hover:opacity-70 focus-visible:opacity-70`)
- `cursor-grab` / `active:cursor-grabbing` per UI-SPEC §1
- `onPointerDown` and `onClick` both `stopPropagation` so the handle does not trigger row expand

## handleDragEnd Branch Structure (Plan 02 state)

```typescript
handleDragEnd(event) {
  // 1. Always clear drag state
  setDragActiveId(null); classList.remove('dragging-active')
  if (!over) return                          // dropped outside — no-op

  // 2. Catalog drop
  if (data?.source === 'catalog') {
    if (!datasetId) return
    if (basemapGroup && overId === basemapGroup.id) return    // Plan 03 placeholder
    if (targetLayer && isFolderGroupLayer(targetLayer)) return // Plan 03 placeholder
    layers.handleAddDataset(datasetId)                        // modal stays open
    return
  }

  // 3. Intra-stack reorder (unchanged from Plan 01)
  if (active.id === over.id) return
  arrayMove + layers.handleReorder(...)
}
```

## Test Changes

No test file changes were required. The DatasetSearchPanel tests render without a `DndContext` wrapper and pass cleanly — `@dnd-kit/core`'s `useDraggable` hook does not throw in a jsdom environment when no DndContext ancestor is present. All 746 tests continued to pass.

## Verification Results

```bash
cd frontend && npx tsc -b --noEmit              # 0 type errors
cd frontend && npx vitest run src/components/builder/__tests__/DatasetSearchPanel.test.tsx
# ✓ 10/10 tests pass
cd frontend && npx vitest run src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
# ✓ 5/5 tests pass
cd frontend && npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx
# ✓ 19/19 tests pass
cd frontend && npx vitest run src/components/builder/ src/pages/
# ✓ 68 test files, 746 tests pass
```

## Acceptance Criteria Verification

- `grep -c "useDraggable" DatasetSearchPanel.tsx` → 5 (≥2) ✓
- `grep -c "source: 'catalog'" DatasetSearchPanel.tsx` → 2 (≥2) ✓
- `grep -c "GripVertical" DatasetSearchPanel.tsx` → 3 (≥1) ✓
- Template literal `catalog:` → 1 (≥1) ✓
- Template literal `catalog-basemap:` → 1 (≥1) ✓
- `grep -c "active.data.current" MapBuilderPage.tsx` → 1 (≥1) ✓
- `grep -c "source === 'catalog'" MapBuilderPage.tsx` → 1 (≥1) ✓
- `grep -c "isFolderGroupLayer" MapBuilderPage.tsx` → 3 (≥1) ✓
- `grep -c "layers.handleAddDataset(datasetId)" MapBuilderPage.tsx` → 1 (≥1) ✓
- `python3` assertion on datasetAdded, basemapChanged, search.dragHandle → all pass ✓

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

**Plan 03 early-return placeholders in MapBuilderPage.handleDragEnd:**
- Basemap group drop → `return` (no swap logic yet)
- Folder-group drop → `return` (no parentGroupId wiring yet)

These are intentional and documented. Plan 03 replaces both early-returns with the actual swap and group-add behaviors. The loose-row add path (the Plan 02 deliverable) is fully functional.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes. Drag payload contains only datasetId (UUID) and display strings already in scope. Backend endpoint validates dataset access on every addLayer call (T-1040-05 mitigation is the existing gate).

## Self-Check: PASSED

- `c7f6874e` exists in git log ✓
- `dcc2e1c2` exists in git log ✓
- `1c7be26d` exists in git log ✓
- `frontend/src/components/builder/DatasetSearchPanel.tsx` modified ✓
- `frontend/src/pages/MapBuilderPage.tsx` modified ✓
- `frontend/src/i18n/locales/en/builder.json` modified ✓
