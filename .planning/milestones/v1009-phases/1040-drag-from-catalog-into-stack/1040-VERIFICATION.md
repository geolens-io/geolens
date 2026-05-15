---
phase: 1040-drag-from-catalog-into-stack
verified: 2026-05-14T13:35:00Z
status: human_needed
score: 6/6
overrides_applied: 0
human_verification:
  - test: "Open the Map Builder, click Add Data, hover a dataset row — confirm grab cursor and grip handle appear at left edge. Drag the row onto the unified stack and confirm the 2px blue insertion line renders during the drag."
    expected: "Cursor changes to cursor-grab; GripVertical handle fades in at ~35% opacity on hover; a 2px primary-color line appears between rows during the drag indicating the drop position."
    why_human: "Visual affordance (cursor shape, handle opacity, insertion line color/placement) cannot be verified programmatically in jsdom — requires a real browser rendering cycle."
  - test: "With the Add Dataset modal open, drag a dataset row onto the stack and drop it. Confirm the modal stays open and a toast fires with the dataset name."
    expected: "Modal remains open; toast reads 'Test Dataset added to map' (or equivalent named toast); layer appears in the stack."
    why_human: "Modal-open state and toast display are visual browser-level behaviors that jsdom tests cannot reliably cover for the full interaction."
  - test: "Drag a dataset row onto an existing folder-group row (or its expanded children). Confirm the layer is added as a child of that group."
    expected: "The new layer appears indented under the folder-group row in the stack, indicating parent_group_id was set correctly."
    why_human: "Visual rendering of group membership (indented child row) requires a browser."
  - test: "On the Basemap tab, drag a basemap row onto the basemap group row at the top of the stack. Confirm the basemap swaps and no new overlay layer is created."
    expected: "The basemap thumbnail in the sidebar changes; the layer count does not increase; a 'Basemap changed to X' toast fires."
    why_human: "Basemap-swap visual confirmation and the absence of an extra layer require browser rendering."
  - test: "Tab into a dataset row in the Add Dataset modal, press Space to pick up (screen reader should announce 'Picked up [name]. Use arrow keys...'), press ArrowDown to move, then press Space/Enter to drop. Confirm the layer is added and the modal stays open."
    expected: "The aria-live 'dnd-announcement' region receives the announcement strings; the layer is added; the modal stays open."
    why_human: "Screen-reader announcement behavior and keyboard-drag UX must be verified in a real browser with accessibility tools or Playwright. Phase 1044 will add the Playwright UAT spec."
  - test: "During a keyboard drag, press Escape. Confirm the drag is cancelled, the layer is NOT added, and the 'Drop cancelled.' announcement fires."
    expected: "No new layer in stack; toast does not fire; screen reader announces 'Drop cancelled.'"
    why_human: "Keyboard-drag cancel flow requires a real browser + accessibility tooling."
---

# Phase 1040: drag-from-catalog-into-stack — Verification Report

**Phase Goal:** Let users drag vector, raster, or basemap rows from the Add Dataset modal directly onto the unified layer stack to add a layer (or swap a basemap) without click-through, while keeping the modal open for repeated adds and supporting a keyboard-only fallback.
**Verified:** 2026-05-14T13:35:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Hovering a dataset row in Add Dataset modal shows grab cursor + grab handle; drag shows in-stack 2px insertion line (POL-01, POL-02) | VERIFIED (code) / ? HUMAN (visual) | `DraggableDatasetRow` and `DraggableBasemapRow` in `DatasetSearchPanel.tsx` both render a `<button>` with `cursor-grab opacity-0 group-hover/row:opacity-35` + `GripVertical`. The in-stack insertion line is the pre-existing `[data-dnd-over="true"] { border-top: 2px solid var(--primary) }` rule (Phase 1038 BSR-24, line 515 of `index.css`), which fires on all `SortableStackRow` wrappers that receive `isOver=true`. Visual confirmation requires browser. |
| 2 | Dropping at a position adds the layer at that position; dropping onto a folder-group adds with parent_group_id (POL-02, POL-03) | VERIFIED | `handleDragEnd` in `MapBuilderPage.tsx` (lines 437-508): Case 4 computes `parentGroupId = isFolderGroupLayer(targetLayer) ? overId : null` and calls `layers.handleAddDataset(datasetId, undefined, parentGroupId, datasetName)`. The hook's `handleAddDataset` (lines 396-439 of `use-builder-layers.ts`) chains `handleAddLayerToExistingGroup(createdLayer.id, parentGroupId)` when `parentGroupId` is non-null. Hook tests pass (97/97). |
| 3 | Dragging a basemap row swaps the basemap, no new overlay layer (POL-04) | VERIFIED | `handleDragEnd` Case 1 (lines 462-474): when `recordType === 'basemap' && basemapGroup && overId === basemapGroup.id`, calls the four-step `normalizeBasemapConfig` shim (`setLocalBasemap`, `setShowBasemapLabels`, `setBasemapConfig`, `markDirty`) matching `DatasetSearchPanel.handleBasemapSwap` exactly. No `handleAddDataset` call in this branch — no new layer created. |
| 4 | Modal stays open after drag-drop; toast confirms each add; multiple adds can be chained (POL-05) | VERIFIED | `handleDragEnd` calls `layers.handleAddDataset(datasetId, undefined, ...)` — `onSuccessCb` parameter is `undefined`, so the click-add path's `dialogs.setShowAddData(false)` is never invoked. Named toasts fire: `toasts.datasetAdded` = `"{{name}} added to map"` and `toasts.basemapChanged` = `"Basemap changed to {{name}}"` exist in `en/builder.json` and are used at the call sites. Toast dedup via `sonner` `id` option prevents stacking on rapid drops. |
| 5 | Keyboard fallback works (aria-live announcements for pick-up/position/drop/cancel) | VERIFIED (code) / ? HUMAN (e2e) | `KeyboardSensor` with `sortableKeyboardCoordinates` is wired in `MapBuilderPage.tsx` (lines 107-109). `aria-live="polite"` `sr-only` region with `data-testid="dnd-announcement"` renders at lines 756-764. `announce()` is called from `handleDragStart`, `handleDragEnd`, `handleDragCancel`, and `handleDragOver`. All four `a11y.*` i18n keys verified in `en/builder.json`. Phase 1044 owns Playwright UAT (POL-23/24). |
| 6 | All existing tests still pass — no regressions | VERIFIED | Full builder vitest sweep: **714 tests / 56 files — 0 failures, 0 unhandled worker errors**. TypeScript `tsc -b --noEmit` exits with 0 errors. |

**Score:** 6/6 truths verified (all code-level truths confirmed; visual/keyboard behaviors deferred to human verification per standard practice for browser-rendered interactions)

### Deferred Items

No items from this phase's goal are deferred to later phases. Note that Phase 1044 extends this work with Playwright UAT and full a11y verification (POL-23, POL-24) — those were intentionally out of scope for Phase 1040.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/pages/MapBuilderPage.tsx` | DndContext at page level wrapping sidebar + BuilderDialogs; drag handlers; aria-live region | VERIFIED | DndContext wraps lines 790-1121 enclosing both `<aside>` (with UnifiedStackPanel) and `<BuilderDialogs>`. `handleDragStart/End/Cancel/Over` all present. `data-testid="dnd-announcement"` div at lines 756-764. |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | SortableContext; DragOverlay with catalog-ghost branch; basemap row useDroppable; folder-group data-group-drop-target | VERIFIED | `SortableContext` present (line 738). `DragOverlay` branches at lines 824-861: catalog path → `CatalogDragGhost`, intra-stack path → StackRow ghost. `BasemapGroupRowWrapper` uses `useDroppable` (line 218). `FolderGroupRowWrapper` emits `data-group-drop-target` when `isOver && isCatalogDragActive` (line 318). `CatalogDragGhost` exported function at lines 474-523. |
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | Per-row useDraggable; grip handle; catalog: and catalog-basemap: id namespacing | VERIFIED | `DraggableDatasetRow` (line 208): `useDraggable({ id: \`catalog:${record.id}\`, data: { source: 'catalog', ... } })`. `DraggableBasemapRow` (line 302): `useDraggable({ id: \`catalog-basemap:${entry.id}\`, ... })`. Both render `GripVertical` button with `cursor-grab opacity-0 group-hover/row:opacity-35`. |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | Extended handleAddDataset(datasetId, onSuccessCb?, parentGroupId?, datasetName?) | VERIFIED | Signature at lines 396-438. When `parentGroupId` non-null: `handleAddLayerToExistingGroup(createdLayer.id, parentGroupId)`. When `datasetName` provided: `toast.success(t('toasts.datasetAdded', { name: datasetName }), { id: \`add-layer-${datasetId}\` })`. |
| `frontend/src/index.css` | `.dragging-active .kebab`, `html.dragging-active`, `[data-basemap-drop-target]`, `[data-group-drop-target]` rules | VERIFIED | Lines 526-546: all four Phase 1040 CSS rules present with correct OKLCH fallbacks and `!important` guards. |
| `frontend/src/i18n/locales/en/builder.json` | toasts.datasetAdded, toasts.basemapChanged, search.dragHandle, a11y.dragPickup, a11y.dragPosition, a11y.dragDropped, a11y.dragCancelled | VERIFIED | All seven keys confirmed via `python3` assertion. Values match UI-SPEC copywriting contract. |
| `frontend/src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx` | New test file covering catalog: / catalog-basemap: namespacing + drag handle aria-label | VERIFIED | File exists. 6 tests: dataset grip handle, catalog:rec-1 id, data.source=catalog, catalog-basemap: namespace, basemap data.recordType=basemap, basemap grip handle. All pass. |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` | Phase 1040 describe blocks for CatalogDragGhost variants + onAddDataset wiring | VERIFIED | Contains `describe('Phase 1040 catalog drop — CatalogDragGhost')` and `describe('Phase 1040 catalog drop — onAddDataset wiring')` blocks at lines 484+529. 7 new tests all pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `MapBuilderPage.tsx` (DndContext) | `UnifiedStackPanel` + `BuilderDialogs` | DndContext wraps `<aside>` (containing UnifiedStackPanel) and `<BuilderDialogs>` in the same return tree (lines 790-1121) | WIRED | Confirmed by reading JSX structure. Both panels share one collision-detection scope. |
| `DatasetSearchPanel.tsx` (useDraggable) | `MapBuilderPage.tsx` (handleDragEnd) | `data: { source: 'catalog', datasetId, recordType, name }` payload read via `active.data.current` in `handleDragEnd` | WIRED | `grep "active.data.current"` → line 452. `grep "source === 'catalog'"` → line 456. |
| `MapBuilderPage.tsx` (handleDragEnd) | `use-builder-layers.ts` (handleAddDataset) | `layers.handleAddDataset(datasetId, undefined, parentGroupId, datasetName)` at line 495 — `undefined` onSuccessCb keeps modal open | WIRED | Modal-stays-open semantic confirmed. Named-toast path wired through hook. |
| `MapBuilderPage.tsx` (handleDragEnd Case 1) | `normalizeBasemapConfig` + layer setters | Mirrors `DatasetSearchPanel.handleBasemapSwap`: `normalizeBasemapConfig` → `setLocalBasemap` → `setShowBasemapLabels` → `setBasemapConfig` → `markDirty` (lines 464-468) | WIRED | Import of `normalizeBasemapConfig` confirmed at line 29. |
| `FolderGroupRowWrapper` | `useDndContext` active data | `const { active } = useDndContext()` at line 298; `isCatalogDragActive` at line 299 | WIRED | `data-group-drop-target` emitted only when both `isOver` and `isCatalogDragActive` are true. |
| `UnifiedStackPanel` (DragOverlay) | `CatalogDragGhost` | `if (catalogData?.source === 'catalog') return <CatalogDragGhost ...>` at lines 831-838 | WIRED | Active data read via panel-scope `useDndContext()` at line 569. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `handleDragEnd` (catalog branch) | `datasetId` from `active.data.current` | `useDraggable` payload set in `DatasetSearchPanel.tsx` at render time | Yes — real dataset UUIDs from API search results | FLOWING |
| `handleAddDataset` | mutation POST to backend addLayer | `addLayerMutation.mutate({ mapId, data: { dataset_id: datasetId } })` — real API call | Yes — backend creates the layer record | FLOWING |
| `handleAddDataset` parentGroupId path | `handleAddLayerToExistingGroup(createdLayer.id, parentGroupId)` | `setLocalLayers` mutation that sets `parent_group_id` on the new layer | Yes — local state updated, persisted on Save | FLOWING |
| Basemap swap shim | `layers.basemapConfig`, `layers.showBasemapLabels` | From `use-builder-layers` hook state, populated from `mapData` API response | Yes — real basemap state | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles cleanly | `cd frontend && npx tsc -b --noEmit` | 0 errors | PASS |
| UnifiedStackPanel + DatasetSearchPanel.dragdrop + MapBuilderPage tests | `npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx src/components/builder/__tests__/DatasetSearchPanel.dragdrop.test.tsx src/pages/__tests__/MapBuilderPage.header-actions.test.tsx` | 37 tests / 3 files — all pass | PASS |
| use-builder-layers hook tests (parentGroupId + datasetName extension) | `npx vitest run src/components/builder/hooks/` | 97 tests / 8 files — all pass | PASS |
| Full builder vitest sweep | `npx vitest run src/components/builder/ src/pages/__tests__/MapBuilderPage.header-actions.test.tsx` | 714 tests / 56 files — 0 failures | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| POL-01 | 1040-01, 1040-02 | Drag affordance (cursor + grab handle) on Add Dataset modal rows | SATISFIED | `DraggableDatasetRow` + `DraggableBasemapRow` both render `GripVertical` button with `cursor-grab opacity-0 group-hover/row:opacity-35`. |
| POL-02 | 1040-02 | Drop on stack adds at position; reuses 1038-02 insertion line | SATISFIED | `handleDragEnd` Case 4/5 calls `handleAddDataset`. Pre-existing `[data-dnd-over="true"]` insertion-line rule applies to `SortableStackRow` wrappers. |
| POL-03 | 1040-03 | Drop on folder-group sets `parent_group_id` | SATISFIED | `parentGroupId = isFolderGroupLayer(targetLayer) ? overId : null` in `handleDragEnd`; hook chains `handleAddLayerToExistingGroup`. |
| POL-04 | 1040-03 | Basemap drop = swap, not add | SATISFIED | Case 1 in `handleDragEnd` calls basemap-swap shim (no `handleAddDataset`). Case 3 (non-basemap → basemap) is a silent reject. |
| POL-05 | 1040-02, 1040-03, 1040-04 | Modal stays open + per-add toast | SATISFIED | `onSuccessCb=undefined` keeps modal open. Named toasts `toasts.datasetAdded` / `toasts.basemapChanged` fire with dataset/basemap name. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `MapBuilderPage.tsx` | 230, 234, 313, 323, 603, 633-647 | `TODO(Phase 1038)` comments for sublayer persistence | Info | Pre-existing from Phase 1035/1036, not introduced by Phase 1040. Phase 1038 shipped; these TODOs reference work intentionally deferred past Phase 1038. Not Phase 1040 debt. |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 1040 modified files.

### Human Verification Required

The six items in the frontmatter `human_verification` section require browser-level testing:

**1. Grab cursor + grip handle visual affordance**

**Test:** Open the Map Builder, click Add Data, hover a dataset row.
**Expected:** Cursor changes to grab hand; GripVertical handle fades in at left edge of row (~35% opacity). No layout shift.
**Why human:** CSS `cursor-grab` and hover opacity transitions are not testable in jsdom.

**2. Modal stays open + named toast after drag-drop**

**Test:** Drag a dataset row from the modal onto the stack and release.
**Expected:** Modal remains open; "Test Dataset added to map" toast appears briefly; layer appears in stack.
**Why human:** Full interaction flow (drag release → mutation success → toast → modal state) requires a real browser event loop.

**3. Folder-group drop visual**

**Test:** Drag a dataset row onto a folder-group row in the stack.
**Expected:** Group row shows blue tint + left rail (data-group-drop-target hover state) during drag-over; after drop, layer appears indented under the group.
**Why human:** Visual rendering of group membership and hover tint requires a browser.

**4. Basemap swap via drag**

**Test:** Switch to the Basemap tab in the modal, drag a basemap row onto the basemap group row at the top of the stack.
**Expected:** Basemap thumbnail changes in the sidebar; layer count does not increase; "Basemap changed to [name]" toast fires.
**Why human:** Basemap thumbnail rendering and layer count are visual browser behaviors.

**5. Keyboard drag pick-up and drop (screen reader)**

**Test:** Tab to a dataset row in the modal, press Space, press ArrowDown, press Space/Enter to drop.
**Expected:** aria-live region announces "Picked up [name]. Use arrow keys..." then "Current position: N of M" then "Dropped. [name] added at position N."; layer added; modal stays open.
**Why human:** Screen-reader announcement flow and keyboard event capture require Playwright or browser + AT. Phase 1044 owns POL-23/24 Playwright UAT spec.

**6. Keyboard drag cancel (Escape)**

**Test:** Tab to a dataset row, press Space to pick up, press Escape to cancel.
**Expected:** "Drop cancelled." announced; no new layer added; no toast.
**Why human:** Same as above — requires Playwright or browser interaction testing.

### Gaps Summary

No gaps. All must-have code-level truths are VERIFIED. The `human_needed` status reflects visual and accessibility behaviors that are standard browser-verification items; they are not implementation failures.

---

_Verified: 2026-05-14T13:35:00Z_
_Verifier: Claude (gsd-verifier)_
