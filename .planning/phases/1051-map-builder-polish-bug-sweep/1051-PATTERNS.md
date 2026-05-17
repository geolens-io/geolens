# Phase 1051: map-builder-polish-bug-sweep - Pattern Map

**Mapped:** 2026-05-17
**Shape:** Hygiene close — 11 user-reported polish/bug fixes + INV-01 disposition + EMRG-01 triage + CTRL-01 gate.
**Files analyzed:** 14 surfaces touched across 13 plans
**Analogs found:** 13 / 13 (1 plan is policy-only — Plan 12 EMRG-01)

## File Classification

| Plan | Touched file | Role | Data flow | Closest analog | Match quality | Notes |
|------|--------------|------|-----------|----------------|---------------|-------|
| 01 BUG-01 | `frontend/src/components/builder/hooks/use-layer-map-sync.ts` | hook | event-driven | self (mature handler) | exact | Verify visibility dispatch survives `syncFromState`; suspect overwrite |
| 01 BUG-01 | `frontend/src/components/builder/StackRow.tsx` | component | request-response | self | exact | Toggle button at line 235-253 — likely OK |
| 01 BUG-01 | `frontend/src/components/builder/map-sync.ts` `syncFromState` | service | event-driven | self | exact | `syncFromState` calls `adapter.syncVisibility` at line 634 — may overwrite |
| 02 BUG-02 | `frontend/src/components/builder/hooks/use-builder-layers.ts` `handleRemove` | hook | request-response | self | exact | Already imperatively removes companions (line 316-336) |
| 02 BUG-02 | `frontend/src/hooks/use-maps.ts` `useRemoveLayer` | hook | CRUD | self | exact | DELETE mutation — verify mapId param wired |
| 02 BUG-02 | `frontend/src/components/builder/map-sync.ts` `removeStaleSourcesAndLayers` | service | event-driven | self | exact | Confirmed source/layer prune path (line 642-668) |
| 03 BUG-03 | `frontend/src/components/builder/FolderGroupRow.tsx` (rename input) | component | request-response | self (already correct) | exact | Has `autoFocus` + `inputRef.current?.select()` |
| 03 BUG-03 | `frontend/src/components/builder/BasemapGroupRow.tsx` | component | request-response | `FolderGroupRow.tsx:230-254` | exact | NO rename input exists; must add per BasemapGroupRow analog |
| 04 UX-01 | `frontend/src/components/builder/BasemapGroupRow.tsx` (caret) | component | UI | `BasemapSublayerEditorScene.tsx:152-156` + `FolderGroupRow.tsx:163-180` | exact | Replace `▸` glyph at line 103 with Lucide `ChevronRight` |
| 04 UX-01 | `frontend/src/components/builder/FolderGroupRow.tsx` (caret) | component | UI | self | role-match | Uses `▸` text glyph (line 178) — same fix |
| 04 UX-01 | `frontend/src/components/builder/StackRow.tsx` (caret column reserved space) | component | UI | self | exact | Has `▸` hidden span (line 207-213) — must preserve 16px column width |
| 05 UX-02 (NEW) | `frontend/src/components/builder/SublayerConfigIndicators.tsx` | component | UI | `LayerEditorTypePill` in `LayerEditorPanel.tsx:84-109` | role-match | New badge component; reuse same chip pattern |
| 05 UX-02 | `frontend/src/components/builder/UnifiedStackPanel.tsx` (SublayerRow Cell 6) | component | UI | self | exact | Currently has Slider in Cell 6 (line 490-509); swap with indicators |
| 06 UX-03 | `frontend/src/components/builder/UnifiedStackPanel.tsx` | component | event-driven | `FolderGroupRowWrapper` (line 312-389) | exact | Lift basemap from `useDroppable` to `useSortable` |
| 06 UX-03 | `frontend/src/components/builder/BasemapGroupRow.tsx` (grip cell) | component | UI | `FolderGroupRow.tsx:183-197` | exact | Replace hidden span (line 107) with real GripVertical button |
| 06 UX-03 | `frontend/src/components/builder/hooks/use-builder-layers.ts` (`handleReorder`) | hook | event-driven | self | exact | Already calls `reorderDataLayers` (line 249-259) |
| 06 UX-03 | `frontend/src/components/builder/hooks/use-builder-save.ts` | hook | CRUD | self | exact | Add basemap-position via derived-from-layer-order (no schema change) |
| 06 UX-03 | `frontend/src/components/builder/map-sync.ts` `reorderDataGeometry` | service | event-driven | self (line 757-776) | exact | Existing reorder loop — verify basemap moveLayer participation |
| 07 UX-04 | `frontend/src/components/builder/SettingsEditorScene.tsx` (lines 146-201) | component | UI | self | exact | Already uses shadcn Switch — only label clarity + duplicate audit |
| 07 UX-04 | `frontend/src/components/map-widgets/registry.ts` / `widget-availability.ts` | config | UI | self | exact | Widget enable/disable state — already exists |
| 07 UX-04 | `frontend/src/stores/map-widget-store.ts` | store | event-driven | self | exact | Confirm activeWidgetIds Set semantics |
| 08 RESP-01 | `frontend/src/components/builder/BuilderMap.tsx` (NavigationControl) | component | UI | self (line 912) | exact | `position="top-right"` — shift left or add margin at rail mode |
| 09 RESP-02 | `frontend/src/components/map/MapCoordReadout.tsx` | component | UI | self (line 111) | exact | Currently `top-2 right-14` — collides with NavigationControl, NOT widgets |
| 09 RESP-02 | `frontend/src/components/map-widgets/WidgetHost.tsx` (top-right anchor) | component | UI | self (line 17) | exact | Anchor `absolute top-12 right-3` |
| 10 RESP-03 | `frontend/src/components/builder/LayerEditorPanel.tsx` (header close X) | component | UI | self (line 316-325) | exact | Single close button in header chrome |
| 10 RESP-03 | `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | component | UI | self | exact | No internal close button — confirm |
| 10 RESP-03 | `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | component | UI | self | exact | No internal close button — confirm |
| 10 RESP-03 | `frontend/src/pages/MapBuilderPage.tsx` (Sheet at <800px) | component | UI | self (line 1138-1230) | exact | Sheet overlay variant — confirm only 1 close button |
| 11 INV-01 | `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` (DETAIL LEVEL block) | component | UI | self (line 90-132) | exact | Toggle currently calls NO-OP handler in `MapBuilderPage.tsx:810` |
| 11 INV-01 | `frontend/src/pages/MapBuilderPage.tsx` (DETAIL LEVEL consumer) | wiring | UI | self (line 791-828) | exact | `onDetailLevelChange={() => { /* TODO */ }}` — DEAD WIRING confirmed |
| 12 EMRG-01 | `.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` | doc | n/a | `.planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md` (v1009.1) | role-match | Per-finding triage matrix |
| 13 CTRL-01 | `CHANGELOG.md` `[Unreleased]` | doc | n/a | v1010.2 `[Unreleased]` shape | exact | One bullet per BUG/UX/RESP + INV/EMRG outcome |

---

## Pattern Assignments

### Plan 01 — BUG-01: Layer visibility toggle no-op

**Toggle handler chain** (already correctly wired):

`StackRow.tsx:235-253` (eye button calls `onToggleVisibility(layer.id)`):
```tsx
<button
  type="button"
  aria-label={t('stackRow.toggleVisibility', { ... })}
  aria-pressed={layer.visible}
  onClick={(e) => {
    e.stopPropagation();
    onToggleVisibility(layer.id);
  }}
>
  {layer.visible ? <Eye .../> : <EyeOff .../>}
</button>
```

`use-layer-map-sync.ts:68-93` (`handleToggleVisibility` — already dispatches to MapLibre):
```ts
const handleToggleVisibility = useCallback((layerId: string, visible?: boolean) => {
  const current = layersRef.current.find((l) => l.id === layerId);
  const nextVisible = visible !== undefined ? visible : !current?.visible;
  applyLayerUpdate(
    layerId,
    (l) => ({ ...l, visible: nextVisible }),
    (map) => {
      const newVis = nextVisible ? 'visible' : 'none';
      const mapLayerId = `layer-${layerId}`;
      // ... iterates companion layers
      if (map.getLayer(mapLayerId)) map.setLayoutProperty(mapLayerId, 'visibility', newVis);
      // ... outlineId, labelId, extrusionId, clusterId, clusterCountId
    },
  );
}, [applyLayerUpdate]);
```

**Suspected root cause** (orchestrator-confirmed via Playwright MCP repro):
- The chain LOOKS wired correctly — toggle dispatches `setLayoutProperty('visibility','none')`. But `syncFromState` in `map-sync.ts:634` calls `adapter.syncVisibility(map, adapterInput)` on every state pass, which writes `visibility` based on `layer.visible`. If `layer.visible` state is correctly updated, this should also produce `none` — so the chain SHOULD work.
- **Hypothesis A** (most likely): the eye `aria-pressed={layer.visible}` reads `layer.visible` but the dispatch reads `current?.visible` from the ref. If `current` is undefined (e.g. layer was just added and `layersRef` hasn't caught up via `useLayoutEffect`), `nextVisible` becomes `!undefined === true`, so toggling never fires.
- **Hypothesis B**: a downstream effect (e.g. `syncFromState` invoked on every render via the `localLayers` change after toggle) rebuilds layers without the visibility change because the state shape is mis-cloned.
- **Hypothesis C**: the `applyLayerUpdate` early-return at line 51-52 (`if (!existing) return;`) is firing because `layerId` does not match. Less likely given `aria-pressed` reflects correct state.

**Fix strategy:** Playwright MCP capture the actual console + `aria-pressed` state at repro URL; trace the dispatch with `console.log` at `applyLayerUpdate` entry; assert `existing` found vs not.

**Regression test pattern** (see existing `use-builder-layers.bulk-ops.test.ts` for the shape):
```ts
// Toggle visible→hidden→visible and assert setLayoutProperty fired both times
const setLayoutProperty = vi.fn();
const map = { isStyleLoaded: () => true, getLayer: () => true, setLayoutProperty } as unknown as MaplibreMap;
// ... call handleToggleVisibility twice; assert setLayoutProperty called with 'none' then 'visible'
```

---

### Plan 02 — BUG-02: Delete-layer no-op

**Existing implementation** (`use-builder-layers.ts:316-336` — looks correct):
```ts
const handleRemove = useCallback((layerId: string) => {
  if (!mapId) return;
  setExpandedLayerId((prev) => prev === layerId ? null : prev);
  // WR-01 (Phase 1050-rev): imperatively clean per-layer companions
  removePerLayerCompanions(mapInstanceRef.current, [layerId]);
  removeLayerMutation.mutate(
    { mapId, layerId },
    {
      onSuccess: () => { toast.success(t('toasts.layerRemoved')); },
      onError: () => { toast.error(t('toasts.layerRemoveFailed')); },
    },
  );
}, [mapId, mapInstanceRef, removeLayerMutation, t]);
```

**Companion cleanup helper** (`use-builder-layers.ts:51-63`):
```ts
function removePerLayerCompanions(map: MaplibreMap | null, layerIds: Iterable<string>): void {
  if (!map || !map.isStyleLoaded()) return;
  const suffixes = ['', '-outline', '-label', '-extrusion', '-arrow', '-cluster', '-cluster-count'];
  for (const id of layerIds) {
    for (const suffix of suffixes) {
      const lid = `layer-${id}${suffix}`;
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}
```

**Suspected root cause:**
- **Hypothesis A**: `removeLayerMutation.mutate` 404s silently (returns `onError` but toast does not surface, or the optimistic state update never reverts the layer back). The sidebar would still show the layer because the mutation didn't update `localLayers`.
- **Hypothesis B**: there is NO optimistic `setLocalLayers((prev) => prev.filter(...))` in `handleRemove` — the layer only disappears from the sidebar when the React-Query invalidation refetches `apiLayers` and the useEffect at line 181-186 re-syncs. If `hasUnsavedChanges` is `true` at the moment of refetch, the sync gate (`!hasUnsavedChanges`) blocks the resync. Compare with `handleBulkDelete` (line 597-602) which DOES optimistically filter.
- **Hypothesis C**: the `removeLayerMutation` succeeds but the React-Query invalidation does not fire (missing `queryClient.invalidateQueries` in the mutation hook).

**Confirm by reading** `frontend/src/hooks/use-maps.ts:182-188`:
```ts
export function useRemoveLayer() {
  return useMutation({
    mutationFn: ({ mapId, layerId }) => removeLayerFromMapApi(mapId, layerId),
    // CHECK: does this have onSuccess with queryClient.invalidateQueries?
  });
}
```

**Fix strategy:** Add optimistic `setLocalLayers((prev) => prev.filter((l) => l.id !== layerId).map((l, i) => ({ ...l, sort_order: i })))` to `handleRemove` BEFORE `removeLayerMutation.mutate` (mirroring `handleBulkDelete` line 597-602). On `onError`, roll back. Confirm `useRemoveLayer` invalidates the map query on success.

**Reference for optimistic + rollback** (`handleBulkDelete` in `use-builder-layers.ts:580-661`):
```ts
const previousLayers = layersRef.current;
const idsToDeleteSet = new Set(idsToDelete);
setLocalLayers((prev) =>
  prev
    .filter((l) => !idsToDeleteSet.has(l.id))
    .map((l, i) => ({ ...l, sort_order: i })),
);
// ... call API; on error, setLocalLayers(previousLayers)
```

---

### Plan 03 — BUG-03: Rename-group autofocus

**FolderGroupRow** (already correct — `FolderGroupRow.tsx:230-254`):
```tsx
<input
  ref={inputRef}
  type="text"
  aria-label={t('folderGroup.renameInputPlaceholder', { defaultValue: 'Group name' })}
  placeholder={t('folderGroup.renameInputPlaceholder', { defaultValue: 'Group name' })}
  className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm font-semibold outline-none focus:ring-1 focus:ring-ring"
  value={nameValue}
  onChange={(e) => setNameValue(e.target.value)}
  onBlur={commitRename}
  onKeyDown={(e) => { if (e.key === 'Enter') { ... } if (e.key === 'Escape') { ... } }}
  onClick={(e) => e.stopPropagation()}
  // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
  autoFocus
/>
```

And `FolderGroupRow.tsx:81-85` selects the text on mount:
```ts
useEffect(() => {
  if (editing && inputRef.current) {
    inputRef.current.select();
  }
}, [editing]);
```

**BasemapGroupRow** (line 165-173) has NO rename input — it's a static span:
```tsx
{/* Cell 5: Layer name — static, no inline rename for basemap */}
<div className="min-w-0">
  <span className="truncate text-sm block">
    Basemap · {presetName}
    ...
  </span>
</div>
```

**Where does the user-reported autofocus bug live?**
- Probably in the FOLDER group flow (`FolderGroupRow.tsx`). Per the kebab `onSelect` at line 293-298:
```tsx
<DropdownMenuItem
  onSelect={(_e) => {
    _e.preventDefault(); // keep menu open while we set editing=true
    handleStartRename();
  }}
>
```
- The `_e.preventDefault()` keeps the menu open. The menu CONTAINS the trigger button, which still owns focus. When `setEditing(true)` fires, React renders the input with `autoFocus`, but the menu (DropdownMenu portal) may steal focus back when it closes shortly after.

**Fix strategy:**
1. Remove `_e.preventDefault()` so the dropdown menu closes cleanly before the input mounts.
2. Defer focus to a `setTimeout(() => inputRef.current?.focus(), 0)` after the menu close to win the focus race vs Radix's `restoreFocus`.
3. OR use `requestAnimationFrame(() => inputRef.current?.focus())`.

**Vitest pattern** (see `FolderGroupRow.test.tsx`):
```ts
import { fireEvent, render, screen } from '@testing-library/react';

it('rename input autofocuses on mount', async () => {
  render(<FolderGroupRow ... />);
  fireEvent.click(screen.getByRole('button', { name: /group options/i }));
  fireEvent.click(screen.getByText('Rename group'));
  const input = await screen.findByRole('textbox');
  expect(document.activeElement).toBe(input);
});
```

---

### Plan 04 — UX-01: Caret hit target ≥24×24 px

**Reference pattern — Lucide ChevronRight in `BasemapSublayerEditorScene.tsx:3` + similar**:
```tsx
import { ChevronRight } from 'lucide-react';
// ...
<ChevronRight
  className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', widgetsOpen && 'rotate-90')}
  aria-hidden="true"
/>
```

**Current — `BasemapGroupRow.tsx:89-104`** (replace `▸` text):
```tsx
<button
  type="button"
  aria-expanded={isExpanded}
  aria-controls={`basemap-group-children-${groupId}`}
  onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
  className={cn(
    'text-xs text-muted-foreground transition-transform duration-[--motion-fast] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
  aria-label={t('basemapGroup.toggleExpand', { defaultValue: 'Toggle basemap group' })}
>
  ▸
</button>
```

**Current — `FolderGroupRow.tsx:163-180`** (same `▸` text glyph):
```tsx
<button
  type="button"
  aria-expanded={isExpanded}
  aria-controls={`folder-group-children-${groupId}`}
  aria-label={t('folderGroup.toggleExpand', { defaultValue: 'Toggle folder group' })}
  onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
  className={cn(
    'text-xs text-muted-foreground transition-transform duration-[--motion-fast]',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
>
  ▸
</button>
```

**Fix (apply to BOTH `BasemapGroupRow` and `FolderGroupRow`):**
- Replace text glyph `▸` with `<ChevronRight className="h-4 w-4" aria-hidden="true" />`
- Add `flex items-center justify-center h-6 w-6 -mx-1` to the button so hit target is 24×24 inside the 16px grid column (negative margin overflows the column 4px each side without breaking grid layout).
- Confirm `transition-transform duration-[--motion-fast]` rotate stays consistent.

**Caret column grid lock** — `StackRow.tsx:174` reserves 16px column:
```tsx
'group/row grid grid-cols-[16px_14px_22px_22px_1fr_22px] gap-2 items-center py-2 px-2 ...'
```
This must NOT change. The hit-target expansion uses `-mx-1` to extend within the visual cell without altering grid columns. Per UI-SPEC §"Spacing Scale" exceptions.

---

### Plan 05 — UX-02: SublayerConfigIndicators (NEW component)

**Existing slider slot to REPLACE** (`UnifiedStackPanel.tsx:490-512`):
```tsx
{/* Cell 6: Opacity slider */}
<div
  className="flex items-center"
  onPointerDown={(e) => e.stopPropagation()}
  onClick={(e) => e.stopPropagation()}
>
  <Slider
    aria-label={`Opacity for ${sublayer.name}`}
    aria-valuetext={`${Math.round(safeOpacity * 100)}%`}
    value={[safeOpacity]}
    min={0} max={1} step={0.05}
    className="w-[60px]"
    onValueChange={([value]) => {
      onSublayerOpacityChange(sublayer.id, Number((value ?? safeOpacity).toFixed(2)));
    }}
  />
</div>
```

The grid template at line 423 is `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]`. The `60px` column hosts the slider; UX-02 must either keep `60px` for the indicators row OR change to `auto` and let badges flow. Recommendation: keep `60px` so the layout is stable across rows.

**Sublayer data shape** (`BasemapSublayerInfo` at `UnifiedStackPanel.tsx:49-55`):
```ts
interface BasemapSublayerInfo {
  id: string;
  name: string;
  visible: boolean;
  opacity: number;
  kind: 'vector' | 'raster';
}
```

**For UX-02 indicators, NEW component must accept full layer shape** (not just the slim BasemapSublayerInfo). Either:
- (a) extend `BasemapSublayerInfo` to carry `labelConfigPresent`, `filterPresent`, etc.
- (b) the indicators sit only on **regular layer rows in StackRow**, NOT on basemap sublayers, because basemap sublayers don't have user-editable filter/label config in this build.

**Read UI-SPEC §"UX-02 SublayerConfigIndicators"** — UI-SPEC explicitly says replace basemap sublayer opacity slider. So we go with (a):
- Plumb the live `MapLayerResponse` for each basemap sublayer through `BasemapSublayerInfo` OR pass a parallel `layer: MapLayerResponse | undefined` prop. Basemap sublayers in v1011 do not yet have user-editable filter/label — most indicators will be absent for the typical basemap (correctly per spec). The UI-SPEC intent appears to assume sublayers WILL have these properties soon; in v1011 indicators may render as a 0-badge empty fragment for basemap sublayers, which still satisfies the requirement to "remove the slider".

**Reference pattern for indicator badge — `LayerEditorTypePill` at `LayerEditorPanel.tsx:84-109`**:
```tsx
function LayerEditorTypePill({ layer }: { layer: MapLayerResponse }) {
  // ...
  return (
    <span className={cn(
      'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]',
      caps.kind === 'vector' && 'bg-[var(--type-vector-bg)] text-[var(--type-vector)]',
      // ...
    )}>
      {label}
    </span>
  );
}
```

**New component skeleton** (per UI-SPEC §"UX-02 SublayerConfigIndicators"):
```tsx
// frontend/src/components/builder/SublayerConfigIndicators.tsx
import { Filter, Layers, Type, Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { MapLayerResponse } from '@/types/api';

interface Props { layer: MapLayerResponse | null }

export function SublayerConfigIndicators({ layer }: Props) {
  const { t } = useTranslation('builder');
  if (!layer) return null;
  const indicators: Array<{ id: string; Icon: typeof Type; label: string }> = [];
  if (layer.label_config?.column) indicators.push({ id: 'labels', Icon: Type, label: t('indicators.labels', { defaultValue: 'Labels enabled' }) });
  if (Array.isArray(layer.filter) && layer.filter.length > 0) indicators.push({ id: 'filter', Icon: Filter, label: t('indicators.filter', { defaultValue: 'Filter applied' }) });
  // data-driven: any paint value is an array (expression)
  const dataDriven = Object.values(layer.paint ?? {}).some((v) => Array.isArray(v));
  if (dataDriven) indicators.push({ id: 'dd', Icon: Zap, label: t('indicators.dataDriven', { defaultValue: 'Data-driven style' }) });
  if (typeof layer.opacity === 'number' && layer.opacity !== 1) indicators.push({ id: 'opacity', Icon: Layers, label: t('indicators.opacityModified', { defaultValue: 'Opacity adjusted' }) });
  if (indicators.length === 0) return null;
  return (
    <div className="flex items-center gap-1">
      {indicators.slice(0, 4).map(({ id, Icon, label }) => (
        <span key={id} title={label} className="inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]">
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span className="sr-only">{label}</span>
        </span>
      ))}
    </div>
  );
}
```

**Test reference** — see `__tests__/BasemapAppearanceControls.test.tsx` for shape of an isolated component test with `MapLayerResponse` fixture.

---

### Plan 06 — UX-03: Draggable basemap row

**Current — `UnifiedStackPanel.tsx:244-287`** (basemap is `useDroppable`, NOT sortable):
```tsx
const BasemapGroupRowWrapper = memo(function BasemapGroupRowWrapper({...}) {
  const { setNodeRef, isOver } = useDroppable({
    id: group.id,
    data: { source: 'stack', kind: 'basemap-group' },
  });
  // ...
  return (
    <div ref={setNodeRef} data-basemap-drop-target={isOver ? 'true' : undefined}>
      <BasemapGroupRow
        // ...
        dragHandleProps={{ attributes: {} as DraggableAttributes, listeners: undefined, setActivatorNodeRef: NOOP }}
        // ...
      />
    </div>
  );
});
```

**Reference — `FolderGroupRowWrapper` at line 312-389**:
```tsx
const FolderGroupRowWrapper = memo(function FolderGroupRowWrapper({...}) {
  const {
    attributes, listeners, setActivatorNodeRef, setNodeRef,
    transform, transition, isDragging, isOver,
  } = useSortable({ id: layer.id });
  // ...
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} ...>
      <FolderGroupRow
        // ...
        dragHandleProps={{ attributes, listeners, setActivatorNodeRef }}
        // ...
      />
    </div>
  );
});
```

**Reference — `BasemapGroupRow.tsx:107` (current hidden grip)**:
```tsx
{/* Cell 2: Grip — hidden: basemap group is not user-draggable (AUD-04) */}
<span aria-hidden="true" className="h-[14px] w-[14px]" />
```

**Reference — `FolderGroupRow.tsx:183-197` (real grip pattern)**:
```tsx
<button
  ref={dragHandleProps.setActivatorNodeRef}
  type="button"
  {...dragHandleProps.attributes}
  {...dragHandleProps.listeners}
  aria-label={t('stackRow.dragHandle', { defaultValue: 'Drag to reorder {{name}}', name: groupName })}
  className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded active:cursor-grabbing"
  onPointerDown={(e) => e.stopPropagation()}
  onClick={(e) => e.stopPropagation()}
>
  <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
</button>
```

**Fix strategy:**
1. `UnifiedStackPanel.tsx:244-287` — swap `useDroppable` for `useSortable` (same shape as `FolderGroupRowWrapper`). Add `data: { source: 'stack', kind: 'basemap-group' }` via the `useSortable` `data` option if drop-target semantics need to be preserved.
2. Include `basemapGroup.id` in `sortableIds` at line 726-730 (currently excluded — see comment at line 722-725).
3. `BasemapGroupRow.tsx:107` — replace hidden span with the real GripVertical button from FolderGroupRow pattern.
4. `MapBuilderPage.tsx` — pass real `dragHandleProps` to `BasemapGroupRowWrapper` (in the wrapper itself, threaded from `useSortable`).
5. Gate drag on `!isMultiSelectionActive` per UI-SPEC cross-plan check (UX-03 vs Phase 1041 POL-11).
6. `handleReorder` in `use-builder-layers.ts:249-259` already handles the array reorder correctly via `reorderDataLayers(map, reorderedLayers)`. No backend schema change — basemap position derives from `sort_order` index.
7. `reorderDataGeometry` in `map-sync.ts:757-776` operates over data layers (prefixed `layer-${id}`). Basemap **style** layers (loaded by MapLibre from the basemap URL) are different — they're symbol/fill layers with NON-`source-` prefixes (`reorderBasemapLabels` at line 188-205 handles them). When basemap is "at top of stack," the existing `reorderBasemapLabels(map, false, ...)` path needs to be augmented to also `moveLayer()` the basemap fill/raster layers ABOVE data geometry layers.

**Saved-map round-trip** — per Out-of-Scope row 6 (REQUIREMENTS.md): no new schema field. Basemap position is implicit in `sort_order` of the basemap entry in the layer array. Backend already preserves `sort_order` for layers; basemap is currently NOT a layer in the API sense (it's `map.basemap_style` at the map root). UX-03 must decide:
- (a) Encode a new client-side-only "basemap_sort_order" in `MapBasemapConfig` (existing nullable field, see `setBasemapConfig` at `use-builder-layers.ts:114-120`) and round-trip via `use-builder-save.ts:439`.
- (b) Compute it from the index where `basemap-group` appears in the unified stack render order, persist as a separate numeric field on `MapResponse`. Requires backend schema addition — out of scope per REQUIREMENTS.md.

Recommendation: (a) — add `basemap_position?: 'top' | 'bottom'` to `MapBasemapConfig` since that's already a free-form jsonb in storage. Single new key, no migration needed.

---

### Plan 07 — UX-04: Map Settings → Widgets enable/disable toggles

**Existing implementation already uses shadcn Switch** (`SettingsEditorScene.tsx:146-201`):
```tsx
<Collapsible open={widgetsOpen} onOpenChange={setWidgetsOpen}>
  <CollapsibleTrigger asChild>
    <button ...>
      <ChevronRight className={...} aria-hidden="true" />
      <span className={eyebrowClassName}>
        {t('settings.widgetsLabel', { defaultValue: 'WIDGETS' })}
      </span>
      {!widgetsOpen && (
        <span className="ml-auto text-xs text-muted-foreground">
          {t('settings.widgetsEnabledCount', { count: activeWidgetIds.size, defaultValue: '{{count}} enabled' })}
        </span>
      )}
    </button>
  </CollapsibleTrigger>
  <CollapsibleContent>
    {widgets.length === 0 ? (
      <p className="px-4 py-2 text-xs text-muted-foreground">...</p>
    ) : (
      <div role="group" aria-label={...}>
        {widgets.map((widget) => {
          const isEnabled = activeWidgetIds.has(widget.id);
          const widgetLabel = t(widget.labelKey, { defaultValue: widget.id });
          const action = isEnabled
            ? t('settings.disableAction', { defaultValue: 'Disable' })
            : t('settings.enableAction', { defaultValue: 'Enable' });
          return (
            <div key={widget.id} className="flex h-9 items-center gap-2 px-4 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))]">
              <widget.icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
              <span className="flex-1 text-xs text-foreground">{widgetLabel}</span>
              <Switch
                checked={isEnabled}
                onCheckedChange={() => onToggleWidget(widget.id)}
                aria-label={t('settings.toggleWidget', {
                  defaultValue: '{{action}} {{name}} widget',
                  action,
                  name: widgetLabel,
                })}
              />
            </div>
          );
        })}
      </div>
    )}
  </CollapsibleContent>
</Collapsible>
```

**Fix focus** (per UI-SPEC §"UX-04 Widget toggles"):
- Label clarification only — already calls `toggleWidget` correctly. UX-04 is mostly a sanity check + duplicate-control audit.
- Audit: search for "duplicate on-map widget controls" — see `frontend/src/components/map-widgets/` registry. Confirm there is no parallel place where the user enables/disables widgets (e.g. inside `WidgetPanel.tsx`). Likely just label clarity needed.
- Per UI-SPEC: align row gap to `gap-2` (currently `gap-2` ✓), confirm `h-9` row height (line 182 ✓).
- i18n: add `settings.enableWidget` / `settings.disableWidget` / `settings.widgetsAvailabilityNote` keys in en/de/es/fr (4 locales × 3 keys = 12 new strings).

**Existing translation files** — `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (770-key parity per MEMORY.md v1009).

---

### Plan 08 — RESP-01: NavigationControl collision

**Current — `BuilderMap.tsx:912`**:
```tsx
<NavigationControl position="top-right" />
<ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
```

**Layout breakpoints** (`use-builder-layout.ts:6-7`):
```ts
const BUILDER_RAIL_BREAKPOINT = 1100
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800
```

`MapBuilderPage.tsx:93-94` consumes via `const { isRail, isEditorHidden } = useBuilderLayout();`.

**Grid layout at `MapBuilderPage.tsx:934`**:
```tsx
isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]',
// when editor open:
isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
```

**Collision analysis:**
- At rail mode (<1100px), the LayerEditorPanel column is 380px wide on the right side of the page (per the grid). MapLibre's `NavigationControl position="top-right"` anchors to the **MapGL container** (the rightmost column), not the page. So the zoom buttons should sit cleanly INSIDE the map column, not over the LayerEditorPanel.
- HOWEVER: when the editor is CLOSED (no layer selected), the map fills the right column starting after sidebar (340px or 64px). The NavigationControl is still at the right edge of the map — no overlap.
- Re-check the user report: the "collapsed right sidebar" overlaps zoom — they likely mean the 380px LayerEditorPanel is INSIDE the right edge of the map at narrow viewports because they sit in adjacent grid columns. In that case the NavigationControl is in the map column on its right edge, and the LayerEditorPanel column is to its right. They should not overlap. Unless the LayerEditorPanel is rendered as an absolutely-positioned overlay on top of the map.

**Recommended fix strategy** (Playwright MCP-verified):
- Capture the actual DOM tree + bounding boxes at 1024px, 900px, 800px viewports.
- If `LayerEditorPanel` IS overlaying the map (positioned `absolute`), shift `NavigationControl` to `position="top-left"` at rail mode OR add `marginRight: 'var(--editor-width)'` to the NavigationControl wrapper.
- If `LayerEditorPanel` is a sibling grid column (more likely based on `grid-cols-[64px_380px_1fr]`), the bug is in the `1fr` map column being too narrow at 800-1099px — and the user's perception of "overlap" might be the right rail (`BuilderRail` at line 1276) sitting over the zoom buttons. Check `BuilderRail.tsx` positioning.

**Likely actual fix**: shift `NavigationControl` to `position="top-left"` so it does not collide with the right rail / editor panel. Confirm by MCP measurement.

---

### Plan 09 — RESP-02: Coord readout overlap

**Current — `MapCoordReadout.tsx:110-127`**:
```tsx
return (
  <div className="absolute top-2 right-14 z-10 pointer-events-none">
    <div className="font-mono text-2xs tracking-wide text-muted-foreground/70 bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5">
      {Math.abs(coords.lat).toFixed(2)}° {latDir}
      {' · '}
      {Math.abs(coords.lng).toFixed(2)}° {lngDir}
      {' · '}
      <span className="text-foreground/50">z</span> {coords.zoom.toFixed(1)}
      ...
    </div>
  </div>
);
```

**IMPORTANT correction to UI-SPEC**: `MapCoordReadout` is positioned `top-2 right-14` (top-right of map canvas, offset 56px from right edge so the NavigationControl fits). It is NOT `bottom-right` as UI-SPEC stated.

**WidgetHost top-right anchor** (`WidgetHost.tsx:17`):
```ts
'top-right': 'absolute top-12 right-3 z-10 flex flex-col gap-2',
```
This sits 12 units (48px) from top vs MapCoordReadout's `top-2` (8px from top). They do NOT collide vertically.

**Hypothesis: the actual "map-widget container" the user refers to is the bottom-left ScaleControl + EphemeralBadge stack** (`WidgetHost.tsx:18`: `'bottom-left': 'absolute bottom-14 left-4 z-10 ...'`). MapCoordReadout's `right-14` puts it at the right edge — no horizontal overlap with bottom-left.

OR: at narrow viewport widths, the coord readout pill text wraps/extends and pushes into the NavigationControl's top-right zone. Likely Playwright MCP capture will reveal the actual overlap.

**Fix strategy:**
- MCP-capture the exact overlap. The fix is one of: (a) move coord readout to `bottom-left` adjacent to ScaleControl (out of NavigationControl space) at narrow widths, (b) use `right-${20 + EDITOR_WIDTH}px` when LayerEditorPanel is visible, or (c) clip the representative-fraction display at narrow widths.

---

### Plan 10 — RESP-03: Duplicate close button audit

**Single close button confirmed** (`LayerEditorPanel.tsx:316-325`):
```tsx
<button
  type="button"
  onClick={onClose}
  aria-label={isPureSettings
    ? t('settings.closePanel', { defaultValue: 'Close settings' })
    : t('layerEditor.close', { defaultValue: 'Close layer editor' })}
  className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
>
  <X className="h-4 w-4" aria-hidden="true" />
</button>
```

A drill-down back arrow ALSO renders at line 271-282 when `isDrillDown=true`. This is the `<800px` `Sheet` overlay path.

**Sheet overlay** (`MapBuilderPage.tsx:1138-1230`) — Sheet from shadcn has its own built-in close X (from `Sheet`/`SheetContent` component). If `LayerEditorPanel` is rendered INSIDE the Sheet with `isDrillDown=false` or unset, the Sheet's auto-close X AND the LayerEditorPanel's own X both appear → 2 close buttons.

**Fix strategy:**
- At `<800px` viewport (`isEditorHidden=true`), the Sheet wraps LayerEditorPanel. Set `isDrillDown={true}` so the back arrow shows AND/OR remove `LayerEditorPanel`'s internal X when inside a Sheet.
- OR: set `<SheetContent>`'s built-in close X to `<SheetContent showClose={false}>` (if shadcn supports that prop) and let `LayerEditorPanel` own the close.
- Audit: read `MapBuilderPage.tsx:1138-1230` to see the Sheet+LayerEditorPanel composition.

**Vitest regression pattern**:
```ts
it('Sheet overlay renders exactly one close button', async () => {
  // Set viewport to <800px (matchMedia mock)
  render(<MapBuilderPage ... />);
  // Open a layer
  // Assert query for buttons with aria-label matching /close/i returns exactly 1
  expect(screen.getAllByRole('button', { name: /close/i })).toHaveLength(1);
});
```

---

### Plan 11 — INV-01: DETAIL LEVEL toggle disposition

**Toggle component** (`BasemapSublayerEditorScene.tsx:90-132`):
```tsx
<section className="border-b">
  <div className="px-4 py-2">
    <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
      {t('basemapSublayer.detailLevelLabel', { defaultValue: 'DETAIL LEVEL' })}
    </p>
    <div role="radiogroup" className="flex flex-wrap gap-1.5">
      {DETAIL_LEVELS.map((pill) => {
        const isActive = pill.id === activeDetailLevel;
        return (
          <button key={pill.id} type="button" role="radio" aria-checked={isActive}
            data-active={isActive ? 'true' : 'false'}
            className={cn('rounded-full border border-transparent px-[10px] py-[5px] text-[12px] transition-colors', isActive ? 'bg-primary text-primary-foreground border-transparent' : 'bg-[var(--surface-2,...)] text-foreground hover:bg-[var(--surface-3,...)]')}
            onClick={() => { if (!isActive) { onDetailLevelChange(pill.id); } }}
          >
            {t(pill.labelKey, { defaultValue: pill.defaultLabel })}
          </button>
        );
      })}
    </div>
    {activeDetailLevel !== 'default' && isCustomized && (
      <p className="text-[12px] text-muted-foreground italic mt-2">
        {t('basemapSublayer.customizedHint', { sublayer: sublayerName, defaultValue: '{{sublayer}} is currently customized' })}
      </p>
    )}
  </div>
</section>
```

**Confirmed DEAD WIRING** (`MapBuilderPage.tsx:801-810`):
```tsx
<BasemapSublayerEditorScene
  sublayerId={sublayer.id}
  sublayerName={sublayer.name}
  activeDetailLevel="default"                                          // <-- hardcoded
  isCustomized={false}                                                  // <-- hardcoded
  strokeColor="#888888"
  strokeWidth={1}
  casingColor="#FFFFFF"
  casingWidth={0}
  opacity={sublayer.opacity}
  minZoom={0}
  maxZoom={22}
  onDetailLevelChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
  onStrokeColorChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
  // ... all callbacks no-op
/>
```

**Other no-op callbacks in same call site**: `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange` all share the same "Phase 1038 TODO" comment. INV-01 is symptomatic of a wider unfinished sublayer-editor surface, NOT a one-off bug.

**Disposition decision points:**
- **REMOVE**: delete the whole DETAIL LEVEL `<section>` from `BasemapSublayerEditorScene.tsx:91-132`, drop the `activeDetailLevel`/`isCustomized`/`onDetailLevelChange` props from the interface, clean up the i18n keys (`basemapSublayer.detailLevel*` × 4 locales). Also evaluate whether the entire scene is dead (all callbacks no-op).
- **FIX**: persist `detail_level` in a new field on `MapBasemapConfig.sublayer_overrides[sublayerId].detail_level`, wire `onDetailLevelChange` to update that state via `setBasemapConfig`, plumb to `applyBasemapConfigToMap` in `map-sync.ts:222`. Requires real implementation of the 4 detail levels (off/minimal/default/full) in terms of MapLibre style mutations — likely 3-5 days of work.

Per ROADMAP Plan 11 task 4: "REMOVE if no recoverable consumer; FIX if a clear consumer + intent can be reconstructed." Since the entire scene is no-op stubs, recommendation is **REMOVE** for the v1011 close — track FIX as a backlog item if user value justifies a future milestone.

**Reference for REMOVE shape** — search for orphan keys:
```bash
grep -rn "detailLevel\|DETAIL LEVEL\|basemapSublayer\.detail" frontend/src/
```

---

### Plan 12 — EMRG-01: FINDINGS.md template

**Reference shape** — see `.planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md` (v1009.1 close) per MEMORY.md. Per-finding entries:
```markdown
## EMRG-FN-01: <title>

- **Severity:** P0 / P1 / P2
- **Scope:** <surface + flow>
- **Disposition:** fix-now / defer
- **Rationale:** <one paragraph>
- **Follow-up:** <commit hash if fix-now, target file path if defer>
```

If 0 emergent findings, the file still exists with:
```markdown
## 0 emergent findings

Playwright MCP inspection passes for plans 01-11 surfaced no unrelated regressions.
Verified <date> on <commit hash> against the v1010.2 baseline.
```

---

### Plan 13 — CTRL-01: CHANGELOG `[Unreleased]`

**Reference shape** — see CHANGELOG `[Unreleased]` from v1010.2 (one bullet per requirement, grouped by type). One bullet per BUG-01..03, UX-01..04, RESP-01..03, INV-01 disposition (REMOVE vs FIX), EMRG-01 outcome, CTRL-01 gate evidence.

**Smoke gate commands** (per ROADMAP Plan 13 task 1-3):
```bash
cd frontend
npx tsc --noEmit
npm test -- --run                            # full vitest
npm run e2e:smoke:builder                    # Playwright e2e smoke
# Plus Playwright MCP re-verify on fresh `docker compose down -v && up -d --build`
```

---

## Shared Patterns

### Pattern A: Imperative MapLibre dispatch with style-loaded guard

**Source:** `use-layer-map-sync.ts:60-66` (`applyLayerUpdate` side-effect closure)
**Apply to:** BUG-01 (visibility), BUG-02 (delete), UX-03 (basemap reorder)

```ts
const map = mapInstanceRef.current;
if (!map || !map.isStyleLoaded()) return;
applyFn(map, updated);
```

Always gate map mutations on `isStyleLoaded()`. Companion layers must be checked via `if (map.getLayer(id))` before each `setLayoutProperty` / `removeLayer` call.

### Pattern B: Optimistic state update + API mutation + rollback

**Source:** `use-builder-layers.ts:578-661` (`handleBulkDelete`)
**Apply to:** BUG-02 (delete-layer)

```ts
const previousLayers = layersRef.current;
setLocalLayers((prev) => prev.filter((l) => !idsToDelete.has(l.id)).map((l, i) => ({ ...l, sort_order: i })));
removePerLayerCompanions(mapInstanceRef.current, idsToDelete);
try {
  const result = await mutation;
  if (result.failed.length === 0) { /* success */ }
  else { setLocalLayers(previousLayers); /* rollback */ }
} catch { setLocalLayers(previousLayers); }
```

### Pattern C: Stable callback identity for React.memo

**Source:** `use-builder-layers.ts:225-244` (`handleMove` + `useCallback` with `mapInstanceRef`)
**Apply to:** all hooks producing handler props for memoized row components

```ts
const handleX = useCallback((arg) => {
  const currentLayers = layersRef.current; // read fresh state from ref, not deps
  // ...
}, [mapInstanceRef]); // only stable refs in deps
```

The `layersRef.current` ref pattern (lines 134-137) ensures handlers don't re-create on every layer mutation, preserving `React.memo()` on `StackRow`.

### Pattern D: data-* markers on portal/sticky widgets for outside-click guards

**Source:** `BulkActionBar.tsx` (per Phase 1045 SP-01 / MEMORY.md feedback_review_findings_inline.md)
**Apply to:** RESP-03 if Sheet overlay close-button audit reveals dropdown/portal interaction issues

`data-bulk-action-bar="true"` marker pattern — when a sticky/portaled widget is clicked, the outside-click guard scopes by data-attribute so the widget itself is excluded from "outside" detection.

### Pattern E: Lucide icon swap for text-glyph carets

**Source:** `SettingsEditorScene.tsx:152-156` + `BasemapSublayerEditorScene.tsx:3`
**Apply to:** UX-01 (replace `▸` in `BasemapGroupRow` + `FolderGroupRow`)

```tsx
import { ChevronRight } from 'lucide-react';
<ChevronRight
  className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', isExpanded && 'rotate-90')}
  aria-hidden="true"
/>
```

Wrap in a `h-6 w-6 -mx-1` button to achieve 24×24 hit target within the 16px grid column.

### Pattern F: i18n key addition

**Source:** `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` (770-key parity per MEMORY.md v1009)
**Apply to:** UX-04 (Enable/Disable widget labels), Plan 11 INV-01 if FIX disposition adds new strings.

Add the same key shape to all 4 locales; CI runs an i18n parity check.

---

## No Analog Found

| File | Role | Data flow | Reason |
|------|------|-----------|--------|
| `frontend/src/components/builder/SublayerConfigIndicators.tsx` | component (NEW) | UI | Net-new component. Closest visual analog is `LayerEditorTypePill` (`LayerEditorPanel.tsx:84-109`) — reuse the inline rounded chip pattern with badge tint per UI-SPEC. |

The `SublayerConfigIndicators` component is the only NEW file in this phase. Every other plan modifies existing surfaces in-place.

---

## Cross-Cutting Notes

### v1010.2 SF-04..08 surfaces to spot-check during MCP re-verify

Per CONTEXT.md decisions + MEMORY.md v1010.2:
- **SF-04 dedupe** (`map-sync.ts:374` `getSourceIdForLayer`) — verify BUG-02 + UX-03 do not regress source dedupe. Source ids are `source-data-${dataset_table_name}` for non-cluster vectors.
- **SF-05 blob revoke** — quicklook blob lifecycle in `use-quicklook.ts:67-74`. Not directly touched here but verify still clean.
- **SF-06 anonymous probe gating** — `enabled: !!token && isAdmin()` on `useEmbeddingStats` / `useAIStatus` / `useSavedSearches`. Verify no regression.
- **SF-07 thumbnail latch** — module-level `autoCapturedMapIds: Set<string>` survives StrictMode unmount. Plan 06 saved-map round-trip should not write to thumbnail.
- **SF-08 basemap latch** — `basemapLoadedAtRef` 3000ms save-flow window. Plan 06 must not regress this — `handleReorder` only fires on user drag, not on initial load.

### Code-review findings policy (CTRL-01)

Per `feedback_review_findings_inline.md` (MEMORY.md): at CTRL-01 close-gate, any reviewer findings (BLOCKER + WARNING + MINOR) get fixed inline before tagging. No deferral to v1011.1. Apply when a sibling-shape audit is warranted (e.g. if Plan 01 visibility fix surfaces a related dispatch bug in `handleBulkVisibility`, fix in same PR).

### Plan filename convention

Per MEMORY.md `feedback_plan_naming_must_end_with_PLAN_md.md`: plan files MUST end with `-PLAN.md`. ROADMAP already names them correctly (`1051-01-bug-layer-visibility-toggle-PLAN.md` etc.) — preserve this when writing plans.

---

## Metadata

**Analog search scope:**
- `frontend/src/components/builder/` (all `.tsx` + `__tests__/`)
- `frontend/src/components/builder/hooks/` (`use-builder-layers.ts`, `use-layer-map-sync.ts`, `use-builder-layout.ts`, `use-builder-save.ts`)
- `frontend/src/components/map/MapCoordReadout.tsx`
- `frontend/src/components/map-widgets/` (registry, host)
- `frontend/src/pages/MapBuilderPage.tsx` (lines 780-830, 928-1290)
- `frontend/src/components/builder/map-sync.ts` (visibility/reorder paths)

**Files read in full:** 5
**Files read in targeted ranges:** 9
**Files confirmed via grep only:** 4 (BasemapPicker dead, normalize-saved-map absent, basemap_position absent, use-maps mutation hook)

**Pattern extraction date:** 2026-05-17
