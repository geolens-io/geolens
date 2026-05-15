---
phase: 1040
plan: "03"
subsystem: frontend/dnd
tags:
  - dnd
  - drag-drop
  - basemap
  - groups
  - mapbuilder
  - frontend
dependency_graph:
  requires:
    - "Phase 1040 Plan 01 (DndContext lifted to MapBuilderPage; basemap row useDroppable)"
    - "Phase 1040 Plan 02 (useDraggable on catalog rows; loose-row handleDragEnd branch)"
  provides:
    - "handleAddDataset extended with parentGroupId + datasetName params"
    - "FolderGroupRowWrapper emits data-group-drop-target when catalog drag is over it"
    - "MapBuilderPage.handleDragEnd: all five catalog-drop cases handled (basemap-swap, folder-group, loose-row, two silent-reject cases)"
    - "CSS rule [data-group-drop-target='true'] — primary-50 tint + inset left rail"
  affects:
    - "frontend/src/components/builder/hooks/use-builder-layers.ts"
    - "frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/index.css"
tech_stack:
  added: []
  patterns:
    - "useDndContext from @dnd-kit/core — reads active.data.current inside FolderGroupRowWrapper to detect catalog-drag source"
    - "normalizeBasemapConfig four-step mirror of DatasetSearchPanel.handleBasemapSwap on the drag path"
    - "Toast dedup via sonner id option: add-layer-{datasetId} and swap-basemap-{datasetId}"
key_files:
  created: []
  modified:
    - "frontend/src/components/builder/hooks/use-builder-layers.ts"
    - "frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts"
    - "frontend/src/components/builder/UnifiedStackPanel.tsx"
    - "frontend/src/pages/MapBuilderPage.tsx"
    - "frontend/src/index.css"
decisions:
  - "useDndContext (not a prop) used in FolderGroupRowWrapper to detect catalog drag — keeps the catalog-drag awareness encapsulated without threading an extra prop through FolderGroupRowWrapperProps"
  - "parentGroupId is null (not omitted) for loose-row drops — explicit null is clearer than undefined and matches the hook's string|null union type"
  - "handleDragEnd dep array expanded to include all layers.* setters consumed in Case 1 — more precise than the broad layers object to avoid stale closure"
  - "TDD RED/GREEN/REFACTOR followed for Task 1: RED commit 523ed38b, GREEN commit a170aa5b"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-14"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 5
---

# Phase 1040 Plan 03: Folder-group drop + basemap swap + named toasts Summary

**One-liner:** handleAddDataset extended with parentGroupId + datasetName; FolderGroupRowWrapper gets data-group-drop-target; handleDragEnd handles all five catalog-drop cases including basemap-swap via normalizeBasemapConfig mirror.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 (RED) | Add failing tests for handleAddDataset extended signature | `523ed38b` | `use-builder-layers.add-dataset.test.ts` |
| 1 (GREEN) | Extend handleAddDataset with parentGroupId + datasetName | `a170aa5b` | `use-builder-layers.ts` |
| 2 | FolderGroupRowWrapper data-group-drop-target + CSS rule | `de1f8e4b` | `UnifiedStackPanel.tsx`, `index.css` |
| 3 | handleDragEnd: basemap-swap + folder-group + silent-reject branches | `0137b602` | `MapBuilderPage.tsx` |

## Architecture: Five Catalog-Drop Cases

```
handleDragEnd (catalog branch)
  ├── Case 1: recordType === 'basemap' AND over === basemapGroup.id
  │     → normalizeBasemapConfig(basemapConfig, showBasemapLabels)
  │     → setLocalBasemap(datasetId)
  │     → setShowBasemapLabels(nextConfig.label_mode !== 'hidden')
  │     → setBasemapConfig(nextConfig)
  │     → markDirty()
  │     → toast.success(t('toasts.basemapChanged', { name }), { id: 'swap-basemap-{id}' })
  │
  ├── Case 2: recordType === 'basemap' AND over !== basemapGroup.id
  │     → silent return (no toast, no action — UI-SPEC §3d)
  │
  ├── Case 3: recordType !== 'basemap' AND over === basemapGroup.id
  │     → silent return (UI-SPEC §3d)
  │
  ├── Case 4: non-basemap AND targetLayer is folder group
  │     → layers.handleAddDataset(datasetId, undefined, overId, datasetName)
  │     → hook chains: handleAddLayerToExistingGroup(createdLayer.id, parentGroupId)
  │     → hook fires: toast.success(t('toasts.datasetAdded', { name }), { id: 'add-layer-{id}' })
  │
  └── Case 5: non-basemap AND loose row (or no target)
        → layers.handleAddDataset(datasetId, undefined, null, datasetName)
        → hook fires: toast.success(t('toasts.datasetAdded', { name }), { id: 'add-layer-{id}' })
```

## Basemap Swap Shim

The drag-drop basemap swap mirrors `DatasetSearchPanel.handleBasemapSwap` exactly (lines 475-479):

```typescript
// DatasetSearchPanel (reference):
const nextConfig = normalizeBasemapConfig(basemapConfig, showBasemapLabels);
onBasemapChange(entry.id);
onBasemapLabelsChange(nextConfig.label_mode !== 'hidden');
onBasemapConfigChange(nextConfig);

// handleDragEnd (drag path — same four steps):
const nextConfig = normalizeBasemapConfig(layers.basemapConfig, layers.showBasemapLabels);
layers.setLocalBasemap(datasetId);
layers.setShowBasemapLabels(nextConfig.label_mode !== 'hidden');
layers.setBasemapConfig(nextConfig);
layers.markDirty();
```

## FolderGroupRowWrapper data-group-drop-target Gating

```tsx
const { active } = useDndContext();
const isCatalogDragActive = (active?.data?.current as { source?: string } | undefined)?.source === 'catalog';
// In JSX:
data-group-drop-target={isOver && isCatalogDragActive ? 'true' : undefined}
```

- `isOver` from `useSortable` — true when pointer is over the row
- `isCatalogDragActive` from `useDndContext` — true only when a catalog drag is in flight
- Both must be true → attribute emitted → CSS rule applies
- Intra-stack drag: `isCatalogDragActive` is false → no attribute → existing `[data-dnd-over='true']` insertion-line rule handles the visual instead

## Named Toast Keys

| Action | Key | Dedup ID |
|--------|-----|---------|
| Dataset added to map | `toasts.datasetAdded` → `"{{name}} added to map"` | `add-layer-{datasetId}` |
| Basemap swapped | `toasts.basemapChanged` → `"Basemap changed to {{name}}"` | `swap-basemap-{datasetId}` |
| Fallback (no name) | `toasts.layerAdded` → `"Layer added"` | none |

## Threat Mitigations Applied

- **T-1040-07** (basemap ID spoofing): `layers.setLocalBasemap(datasetId)` routes through `resolveBasemapId()` in the hook internals; unknown IDs fall back to the default basemap — graceful.
- **T-1040-08** (crafted parentGroupId): `handleAddLayerToExistingGroup` is invoked only via the hook's `handleAddDataset` success path when `parentGroupId` is non-null; Case 4 in `handleDragEnd` only sets `parentGroupId = overId` when `isFolderGroupLayer(targetLayer)` is true, so the group existence and type check gate access.
- **T-1040-09** (name in toast): accepted by design — user owns the dataset.

## TDD Gate Compliance

Task 1 followed TDD:
- RED commit: `523ed38b` — `test(1040-03):` prefix
- GREEN commit: `a170aa5b` — `feat(1040-03):` prefix

Tasks 2 and 3 do not have `tdd="true"` in the plan (Task 2 acceptance is verified by existing tests passing; Task 3 acceptance is verified by existing tests + lint + build). Plan 04 owns cross-context drop test coverage.

## Verification Results

```
cd frontend && npx tsc -b --noEmit    # 0 errors
cd frontend && npx vitest run src/components/builder/ src/pages/
  # 750 tests pass (68 test files)
cd frontend && npm run build          # ✓ built in 387ms
```

## Acceptance Criteria Verification

- `grep -c "parentGroupId" use-builder-layers.ts` → ≥1 (3) ✓
- `grep -c "datasetName" use-builder-layers.ts` → ≥1 (3) ✓
- `grep -c "toasts.datasetAdded" use-builder-layers.ts` → ≥1 (1) ✓
- `grep -c "add-layer-" use-builder-layers.ts` → ≥1 (1) ✓
- `grep -c "useDndContext" UnifiedStackPanel.tsx` → ≥1 (2) ✓
- `grep -c "isCatalogDragActive" UnifiedStackPanel.tsx` → ≥1 (2) ✓
- `grep -c "data-group-drop-target" UnifiedStackPanel.tsx` → ≥1 (2) ✓
- `grep -c "data-group-drop-target" index.css` → ≥1 (1) ✓
- `grep -c "normalizeBasemapConfig" MapBuilderPage.tsx` → ≥1 (2) ✓
- `grep -c "recordType === 'basemap'" MapBuilderPage.tsx` → ≥1 (2) ✓
- `grep -c "isFolderGroupLayer" MapBuilderPage.tsx` → ≥1 (3) ✓
- `grep -c "toasts.basemapChanged" MapBuilderPage.tsx` → ≥1 (1) ✓
- `grep -c "swap-basemap-" MapBuilderPage.tsx` → ≥1 (1) ✓
- `grep -c "parentGroupId" MapBuilderPage.tsx` → ≥1 (3) ✓

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all catalog-drop cases are functional. Plan 03 placeholders from Plan 02 have been replaced.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes. All drag-drop logic is client-side only; backend access control enforced by existing addLayer mutation endpoint (T-1040-05).

## Self-Check: PASSED

- `523ed38b` exists in git log ✓
- `a170aa5b` exists in git log ✓
- `de1f8e4b` exists in git log ✓
- `0137b602` exists in git log ✓
- `frontend/src/components/builder/hooks/use-builder-layers.ts` modified ✓
- `frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` modified ✓
- `frontend/src/components/builder/UnifiedStackPanel.tsx` modified ✓
- `frontend/src/pages/MapBuilderPage.tsx` modified ✓
- `frontend/src/index.css` modified ✓
