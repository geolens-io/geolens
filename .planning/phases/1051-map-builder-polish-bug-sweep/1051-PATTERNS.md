# Phase 1051: map-builder-polish-bug-sweep — Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 14 new/modified files
**Analogs found:** 13 / 14

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | component | event-driven | `frontend/src/components/builder/UnifiedStackPanel.tsx` (self — modify) | exact |
| `frontend/src/components/builder/StackRow.tsx` | component | event-driven | `frontend/src/components/builder/StackRow.tsx` (self — modify) | exact |
| `frontend/src/components/builder/BasemapGroupRow.tsx` | component | event-driven | `frontend/src/components/builder/FolderGroupRow.tsx` | exact (same grid pattern) |
| `frontend/src/components/builder/FolderGroupRow.tsx` | component | event-driven | `frontend/src/components/builder/StackRow.tsx` | exact |
| `frontend/src/components/builder/SublayerConfigIndicators.tsx` | component | transform | `frontend/src/components/builder/BulkActionBar.tsx` (badge strip) | role-match |
| `frontend/src/components/builder/hooks/use-layer-map-sync.ts` | hook | event-driven | `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (self — modify) | exact |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | hook | event-driven | `frontend/src/components/builder/hooks/use-builder-layers.ts` (self — modify) | exact |
| `frontend/src/components/builder/map-sync.ts` | utility | event-driven | `frontend/src/components/builder/map-sync.ts` (self — modify) | exact |
| `frontend/src/components/builder/SettingsEditorScene.tsx` | component | event-driven | `frontend/src/components/builder/SettingsEditorScene.tsx` (self — modify) | exact |
| `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | component | event-driven | `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` (self — INV-01 remove or fix) | exact |
| `frontend/src/components/builder/BuilderMap.tsx` | component | event-driven | `frontend/src/components/builder/BuilderMap.tsx` (self — modify) | exact |
| `frontend/src/components/map/MapCoordReadout.tsx` | component | event-driven | `frontend/src/components/map/MapCoordReadout.tsx` (self — modify) | exact |
| `frontend/src/pages/MapBuilderPage.tsx` | page | event-driven | `frontend/src/pages/MapBuilderPage.tsx` (self — modify) | exact |
| `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` | config | transform | self — modify | exact |

---

## Pattern Assignments

### `frontend/src/components/builder/StackRow.tsx` (BUG-01: visibility toggle, BUG-02: delete)

**Analog:** self (modify existing file)

**Visibility toggle handler — current wiring** (lines 235–253):
```tsx
<button
  type="button"
  aria-label={t('stackRow.toggleVisibility', { ... })}
  aria-pressed={layer.visible}
  className="flex items-center justify-center h-[22px] w-[22px] ..."
  onClick={(e) => {
    e.stopPropagation();
    onToggleVisibility(layer.id);   // <-- prop call; bug is upstream of this
  }}
>
  {layer.visible ? <Eye ... /> : <EyeOff ... />}
</button>
```

**Delete handler — current wiring** (lines 393–411):
```tsx
{confirmingDelete && (
  <div role="alertdialog" ...>
    <Button
      variant="destructive"
      onClick={() => {
        onRemove(layer.id);   // <-- prop call; bug is upstream of this
        setConfirmingDelete(false);
      }}
    >Delete</Button>
  </div>
)}
```

**Key insight:** The `onToggleVisibility` and `onRemove` props on `StackRow` delegate to `handleToggleVisibility` / `handleRemove` from `use-builder-layers.ts`. The bug is in the plumbing between the prop call and the MapLibre dispatch — trace via grep from `onToggleVisibility` in `UnifiedStackPanel.tsx` prop-pass-through to `MapBuilderPage.tsx` wiring.

**autoFocus pattern for rename input** (lines 262–284) — for BUG-03 reference in BasemapGroupRow:
```tsx
<input
  type="text"
  // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
  autoFocus
  className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm outline-none focus:ring-1 focus:ring-ring"
  value={nameValue}
  onChange={(e) => setNameValue(e.target.value)}
  onBlur={commitRename}
  onKeyDown={(e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitRename(); }
    if (e.key === 'Escape') { escapeRef.current = true; setEditing(false); }
  }}
/>
```

---

### `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (BUG-01: visibility dispatch)

**Analog:** self (modify existing file)

**handleToggleVisibility pattern** (lines 68–93) — the canonical setLayoutProperty chain:
```ts
const handleToggleVisibility = useCallback(
  (layerId: string, visible?: boolean) => {
    const current = layersRef.current.find((l) => l.id === layerId);
    const nextVisible = visible !== undefined ? visible : !current?.visible;
    applyLayerUpdate(
      layerId,
      (l) => ({ ...l, visible: nextVisible }),
      (map) => {
        const newVis = nextVisible ? 'visible' : 'none';
        const mapLayerId = `layer-${layerId}`;
        const outlineId   = `layer-${layerId}-outline`;
        const labelId     = `layer-${layerId}-label`;
        const extrusionId = `layer-${layerId}-extrusion`;
        const clusterId   = `layer-${layerId}-cluster`;
        const clusterCountId = `layer-${layerId}-cluster-count`;
        if (map.getLayer(mapLayerId))     map.setLayoutProperty(mapLayerId, 'visibility', newVis);
        if (map.getLayer(outlineId))      map.setLayoutProperty(outlineId, 'visibility', newVis);
        if (map.getLayer(labelId))        map.setLayoutProperty(labelId, 'visibility', newVis);
        if (map.getLayer(extrusionId))    map.setLayoutProperty(extrusionId, 'visibility', newVis);
        if (map.getLayer(clusterId))      map.setLayoutProperty(clusterId, 'visibility', newVis);
        if (map.getLayer(clusterCountId)) map.setLayoutProperty(clusterCountId, 'visibility', newVis);
      },
    );
  },
  [applyLayerUpdate],
);
```

**applyLayerUpdate guard** (lines 42–66) — existence check prevents false dirty-flag:
```ts
const existing = layersRef.current.find((l) => l.id === layerId);
if (!existing) return;   // early-exit: no layer = no state update, no dirty
```

---

### `frontend/src/components/builder/hooks/use-builder-layers.ts` (BUG-02: delete, UX-03: basemap drag)

**Analog:** self (modify existing file)

**handleRemove pattern** (lines 316–336):
```ts
const handleRemove = useCallback((layerId: string) => {
  if (!mapId) return;
  setExpandedLayerId((prev) => prev === layerId ? null : prev);
  // imperative companion cleanup BEFORE mutation so visual artifacts disappear in lockstep
  removePerLayerCompanions(mapInstanceRef.current, [layerId]);
  removeLayerMutation.mutate(
    { mapId, layerId },
    {
      onSuccess: () => toast.success(t('toasts.layerRemoved')),
      onError:   () => toast.error(t('toasts.layerRemoveFailed')),
    },
  );
}, [mapId, mapInstanceRef, removeLayerMutation, t]);
```

**removePerLayerCompanions helper** (lines 51–63) — imperative MapLibre layer teardown:
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

**useCallback stability pattern for handlers** (lines 218–244):
```ts
// Mirror current layers in a ref so stable callbacks can read fresh state
// without invalidating on every layer mutation.
const layersRef = useRef(localLayers);
useLayoutEffect(() => { layersRef.current = localLayers; }, [localLayers]);

const handleMove = useCallback((layerId: string, direction: 'up' | 'down') => {
  const currentLayers = layersRef.current;
  // ... uses layersRef.current, not localLayers, to keep dep list stable
}, [mapInstanceRef]);
```

---

### `frontend/src/components/builder/BasemapGroupRow.tsx` (BUG-03: autofocus, UX-01: caret, UX-03: drag handle)

**Analog:** `frontend/src/components/builder/FolderGroupRow.tsx` (exact same grid shape + patterns)

**Rename autofocus pattern from FolderGroupRow** (lines 67–85):
```tsx
const inputRef = useRef<HTMLInputElement | null>(null);

// Auto-select input text when entering edit mode
useEffect(() => {
  if (editing && inputRef.current) {
    inputRef.current.select();  // select() implies focus — use for BasemapGroupRow
  }
}, [editing]);
```

**Rename input with autoFocus** (FolderGroupRow lines 231–254):
```tsx
<input
  ref={inputRef}
  type="text"
  className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm font-semibold outline-none focus:ring-1 focus:ring-ring"
  value={nameValue}
  onChange={(e) => setNameValue(e.target.value)}
  onBlur={commitRename}
  onKeyDown={(e) => { ... }}
  onClick={(e) => e.stopPropagation()}
  // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
  autoFocus
/>
```

**Caret button pattern from FolderGroupRow** (lines 163–179) — this is the TARGET pattern for UX-01 fix in BasemapGroupRow (currently uses raw `▸` text):
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
  ▸   {/* <-- replace this with <ChevronRight className="h-4 w-4" /> */}
</button>
```

**Per UI-SPEC UX-01 fix:** Replace the `▸` text in BasemapGroupRow line 103 with:
```tsx
<button
  type="button"
  aria-expanded={isExpanded}
  aria-controls={`basemap-group-children-${groupId}`}
  aria-label={isExpanded
    ? t('basemapGroup.collapseGroup', { defaultValue: 'Collapse group' })
    : t('basemapGroup.expandGroup', { defaultValue: 'Expand group' })}
  onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
  className={cn(
    'flex items-center justify-center h-6 w-6 -mx-1',  // 24px hit target; -mx-1 insets within 16px column
    'text-muted-foreground transition-transform duration-[--motion-fast]',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
>
  <ChevronRight className="h-4 w-4" aria-hidden="true" />
</button>
```

**Drag handle pattern from FolderGroupRow** (lines 182–197) — for UX-03 enabling drag on BasemapGroupRow:
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

**Disable drag during multi-selection** (per UI-SPEC UX-03 conflict note):
```tsx
{/* Gate dragHandleProps spread on !isMultiSelectionActive */}
<button
  ref={dragHandleProps.setActivatorNodeRef}
  {...(isMultiSelectionActive ? {} : dragHandleProps.attributes)}
  {...(isMultiSelectionActive ? {} : dragHandleProps.listeners)}
  className={cn(
    'flex items-center justify-center cursor-grab ...',
    isMultiSelectionActive && 'cursor-not-allowed opacity-20',
  )}
>
```

---

### `frontend/src/components/builder/SublayerConfigIndicators.tsx` (UX-02: new component)

**Analog:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (SublayerRow — Cell 6 slot being replaced)

**No exact analog exists** for a badge-strip indicator component in this codebase. The closest structural analog is the existing `BadgeList` pattern in catalog surfaces — but the UI-SPEC is sufficiently concrete to build from scratch.

**New file imports pattern** (copy from `BasemapGroupRow.tsx` lines 1–14 as base):
```tsx
import { memo, useMemo } from 'react';
import { Filter, Layers, Type, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';
```

**Component skeleton:**
```tsx
interface SublayerConfigIndicatorsProps {
  layer: MapLayerResponse;  // matches BasemapSublayerInfo shape from UnifiedStackPanel
}

export const SublayerConfigIndicators = memo(function SublayerConfigIndicators({
  layer,
}: SublayerConfigIndicatorsProps) {
  const indicators = useMemo(() => {
    const result: Array<{ icon: React.ElementType; label: string }> = [];
    const layout = layer.layout ?? {};
    const paint = layer.paint ?? {};

    // Has labels: layout['text-field'] is set and non-empty
    if (layout['text-field']) result.push({ icon: Type, label: 'Labels enabled' });
    // Has filter: filter array is non-empty
    if (Array.isArray(layer.filter) && layer.filter.length > 0)
      result.push({ icon: Filter, label: 'Filter applied' });
    // Data-driven paint: any paint property is an expression (array value)
    if (Object.values(paint).some((v) => Array.isArray(v)))
      result.push({ icon: Zap, label: 'Data-driven style' });
    // Opacity modified: any *-opacity paint is not 1.0
    const opacityKeys = Object.keys(paint).filter((k) => k.endsWith('-opacity'));
    if (opacityKeys.some((k) => (paint as Record<string, unknown>)[k] !== 1.0))
      result.push({ icon: Layers, label: 'Opacity adjusted' });

    return result.slice(0, 4);  // max 4 indicators per UI-SPEC
  }, [layer.layout, layer.paint, layer.filter]);

  if (indicators.length === 0) return null;

  return (
    <div className="flex items-center gap-1" aria-label="Layer config indicators">
      {indicators.map(({ icon: Icon, label }) => (
        <span
          key={label}
          className="inline-flex items-center justify-center h-4 w-4 rounded-sm bg-[var(--primary-50)] text-[var(--primary-600)]"
          title={label}
        >
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span className="sr-only">{label}</span>
        </span>
      ))}
    </div>
  );
});
```

**Sublayer row grid change** — the current `SublayerRow` in `UnifiedStackPanel.tsx` uses:
```
grid-cols-[16px_14px_22px_22px_1fr_60px_22px]  // col 6 = 60px opacity slider
```
After removing the slider and adding indicators, change to:
```
grid-cols-[16px_14px_22px_22px_1fr_auto_22px]  // col 6 = auto-width indicators
```

---

### `frontend/src/components/builder/UnifiedStackPanel.tsx` (UX-03: basemap drag, UX-02: SublayerRow refactor)

**Analog:** self (modify existing file)

**Current basemap exclusion from sortable IDs** (lines 722–730):
```ts
// sortableIds excludes basemapGroup — basemap is pinned (cannot be reordered)
const sortableIds = useMemo(() => {
  const ids: string[] = [];
  for (const l of layers) ids.push(l.id);
  return ids;  // <-- basemapGroup.id NOT pushed here; that's what UX-03 must change
}, [layers]);
```

**BasemapGroupRowWrapper currently uses useDroppable** (lines 239–256):
```tsx
// Phase 1040: Basemap group is a drop target only — drag-out not supported (AUD-04)
// useDroppable gives it proper drop-target semantics for catalog basemap drops.
const { setNodeRef, isOver } = useDroppable({ id: `basemap-group-${group.id}` });
```

**For UX-03, switch BasemapGroupRowWrapper from useDroppable to useSortable:**
```tsx
// Replace useDroppable with useSortable (same pattern as SortableStackRow, lines 171–185)
const {
  attributes, listeners, setActivatorNodeRef,
  setNodeRef, transform, transition, isDragging,
} = useSortable({ id: group.id });  // group.id added to sortableIds
```

**Add group.id to sortableIds:**
```ts
const sortableIds = useMemo(() => {
  const ids: string[] = [];
  if (basemapGroup) ids.push(basemapGroup.id);  // basemap participates in reorder
  for (const l of layers) ids.push(l.id);
  return ids;
}, [layers, basemapGroup]);
```

**Current SublayerRow opacity slider** (lines 490–509) — remove this block for UX-02:
```tsx
{/* Cell 6: Opacity slider — REMOVE this entire block for UX-02 */}
<div className="flex items-center" onPointerDown={...} onClick={...}>
  <Slider
    aria-label={`Opacity for ${sublayer.name}`}
    value={[safeOpacity]}
    min={0} max={1} step={0.05}
    className="w-[60px]"
    onValueChange={([value]) => onSublayerOpacityChange(sublayer.id, ...)}
  />
</div>
```

**Replace with SublayerConfigIndicators:**
```tsx
{/* Cell 6: Config-state indicators (UX-02) */}
<div className="flex items-center" onClick={(e) => e.stopPropagation()}>
  <SublayerConfigIndicators layer={sublayerAsLayer} />
</div>
```

---

### `frontend/src/components/builder/SettingsEditorScene.tsx` (UX-04: widget toggles)

**Analog:** self (modify existing file — existing widget toggle already correct)

**Current widget toggle pattern** (lines 173–196) — shows that the core Switch is already wired correctly:
```tsx
{widgets.map((widget) => {
  const isEnabled = activeWidgetIds.has(widget.id);
  const widgetLabel = t(widget.labelKey, { defaultValue: widget.id });
  const action = isEnabled
    ? t('settings.disableAction', { defaultValue: 'Disable' })
    : t('settings.enableAction', { defaultValue: 'Enable' });
  return (
    <div
      key={widget.id}
      className="flex h-9 items-center gap-2 px-4 hover:bg-[var(--surface-2,...)]"
    >
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
```

**UX-04 change scope:** The `action` string construction already produces "Enable [name] widget" / "Disable [name] widget". The real UX-04 work is:
1. Audit for any duplicate on-map widget controls rendered outside `SettingsEditorScene` for the same widget IDs — grep for `activeWidgetIds` usages in `MapBuilderPage.tsx` and `BuilderMap.tsx`.
2. If a new `settings.widgetsAvailabilityNote` i18n key is added, follow the existing pattern at lines 942–944 in `en/builder.json`.
3. Gap to fix: aria-label currently says "{{action}} {{name}} widget" — the UI-SPEC prefers "Enable [widget name]" (without the word "widget"). Adjust the `toggleWidget` key or add `settings.enableWidget` / `settings.disableWidget` keys.

**Adding a new i18n key** (pattern from `en/builder.json` lines 942–944):
```json
"settings": {
  "disableAction": "Disable",
  "enableAction": "Enable",
  "toggleWidget": "{{action}} {{name}} widget",
  "widgetsAvailabilityNote": "Controls whether each widget appears on the map."
}
```
Mirror this key to `de/builder.json`, `es/builder.json`, `fr/builder.json` at the same JSON path.

---

### `frontend/src/components/builder/BuilderMap.tsx` (RESP-01: NavigationControl position)

**Analog:** self (modify existing file)

**Current NavigationControl** (line 912):
```tsx
<NavigationControl position="top-right" />
```

**Fix strategy per UI-SPEC RESP-01:** The 64px rail sidebar sits on the right at `<1100px`. The `NavigationControl` at `position="top-right"` collides with the rail. Fix by shifting to `position="top-left"` OR using `marginRight` to push it in from the rail edge. The `isRail` boolean from `useBuilderLayout()` is already consumed in `MapBuilderPage.tsx` — if needed, pass it to `BuilderMap.tsx` via prop and gate the position prop:
```tsx
// BuilderMap.tsx receives isRail prop or reads viewport directly
<NavigationControl position={isRail ? 'top-left' : 'top-right'} />
```

**BuilderMap.tsx imports / prop pattern** (lines 1–30 of BuilderMap):
```tsx
import { Map as MapGL, NavigationControl, ScaleControl } from '@vis.gl/react-maplibre';
```
`MapCoordReadout` is rendered as a sibling overlay (line 923), not inside `MapGL`.

---

### `frontend/src/components/map/MapCoordReadout.tsx` (RESP-02: position overlap)

**Analog:** self (modify existing file)

**Current positioning** (line 111):
```tsx
<div className="absolute top-2 right-14 z-10 pointer-events-none">
```

**Fix strategy per UI-SPEC RESP-02:** At narrow viewports (`isRail`), the `right-14` (56px) offset may collide with the map-widget container. The fix is a responsive offset — either accept an `isRail` or `isEditorHidden` prop, or use a CSS variable set by the parent:
```tsx
// Pattern: accept a className override or responsive prop
<div
  className={cn(
    'absolute top-2 z-10 pointer-events-none',
    isEditorHidden ? 'right-2' : 'right-14',  // pull further right when editor hidden
  )}
>
```

The component currently has no layout-aware props. Follow the `useBuilderLayout()` hook pattern (from `use-builder-layout.ts` lines 1–37) — either import the hook inside `MapCoordReadout` or pass `isRail` / `isEditorHidden` as a prop from `BuilderMap.tsx`.

---

### `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` (INV-01: DETAIL LEVEL disposition)

**Analog:** self (INV-01 will REMOVE or FIX this surface)

**DETAIL LEVEL toggle** (lines 44–121):
```tsx
type DetailLevel = 'off' | 'minimal' | 'default' | 'full';
const DETAIL_LEVELS = [...];  // 4 pill options

// Wiring in MapBuilderPage.tsx line 801:
activeDetailLevel="default"
onDetailLevelChange={() => { /* TODO(Phase 1038): ... */ }}  // <-- no-op stub
```

**INV-01 consumer trace:**
- The prop `onDetailLevelChange` is a no-op stub in `MapBuilderPage.tsx` (line 810).
- `activeDetailLevel` is hard-coded to `"default"` (line 801) — no state, no persistence.
- The toggle renders and fires clicks, but the callback is a no-op and the value never changes.
- **Disposition signal:** No recoverable consumer exists. REMOVE is the expected outcome. Verify by grepping `onDetailLevelChange` across `frontend/src/` — if zero non-stub callers are found, REMOVE.

**If REMOVE:** Delete `DETAIL_LEVELS`, `DetailLevel` type, `activeDetailLevel` prop, `onDetailLevelChange` prop from `BasemapSublayerEditorSceneProps`, and the entire Section 1 JSX block (lines 90–131). Also remove the two hardcoded prop values from `MapBuilderPage.tsx` line 801/810. Clean up orphan i18n keys: `basemapSublayer.detailLevelLabel`, `basemapSublayer.detailLevelOff`, `basemapSublayer.detailLevelMinimal`, `basemapSublayer.detailLevelDefault`, `basemapSublayer.detailLevelFull`.

---

### `frontend/src/pages/MapBuilderPage.tsx` (RESP-01: isRail prop threading, UX-03: basemap drag integration)

**Analog:** self (modify existing file)

**useBuilderLayout usage** (lines 93–94):
```tsx
const { isRail, isEditorHidden } = useBuilderLayout();
```

**Grid class pattern** (lines 931–939) — for reference when adjusting layout:
```tsx
const builderBodyGridClass = cn(
  'flex-1 min-h-0 grid',
  isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]',
  (editingLayer || ...) && !isEditorHidden && (
    isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
  ),
);
```

**UX-03 basemap position persistence:** The `handleReorder` callback in `use-builder-layers.ts` (line 249) manages layer order changes. For basemap drag, wire the basemap group into `handleReorder` via the same `onDragEnd` pattern. The basemap position derives from its index in the unified stack array — no new schema field needed (derive from `sort_order`).

---

### `frontend/src/components/builder/hooks/use-builder-layout.ts` (RESP-01/02: breakpoints reference)

**Analog:** self (read-only reference for planner — no modification expected)

**Breakpoints** (lines 6–7):
```ts
const BUILDER_RAIL_BREAKPOINT = 1100    // sidebar → 64px rail at <1100px
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800  // flyout hidden at <800px
```

**Hook return shape** (lines 30–36):
```ts
return { isRail, isEditorHidden, isCompact: isRail, isMobile: isEditorHidden }
```

---

## Shared Patterns

### Visibility toggle MapLibre dispatch
**Source:** `frontend/src/components/builder/hooks/use-layer-map-sync.ts` lines 68–93
**Apply to:** BUG-01 fix in `use-layer-map-sync.ts` (trace why handleToggleVisibility isn't reaching StackRow)
```ts
if (map.getLayer(mapLayerId)) map.setLayoutProperty(mapLayerId, 'visibility', newVis);
// + 5 companion layers: outline, label, extrusion, cluster, cluster-count
```

### Layer removal pattern
**Source:** `frontend/src/components/builder/hooks/use-builder-layers.ts` lines 316–336
**Apply to:** BUG-02 (trace why handleRemove isn't reaching StackRow `onRemove`)
```ts
removePerLayerCompanions(mapInstanceRef.current, [layerId]);  // before mutation
removeLayerMutation.mutate({ mapId, layerId }, { onSuccess, onError });
```

### autoFocus rename input
**Source:** `frontend/src/components/builder/FolderGroupRow.tsx` lines 67–85, 231–254
**Apply to:** BUG-03 BasemapGroupRow rename UI
```tsx
// useEffect approach (for inputRef.current.select()):
useEffect(() => {
  if (editing && inputRef.current) { inputRef.current.select(); }
}, [editing]);

// OR simpler autoFocus prop (StackRow approach, line 283):
autoFocus  // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
```

### Caret button with ChevronRight icon and 24px hit-target
**Source:** `frontend/src/components/builder/FolderGroupRow.tsx` lines 163–179
**Apply to:** UX-01 BasemapGroupRow caret (replace `▸` text at line 103)
```tsx
className={cn(
  'text-xs text-muted-foreground transition-transform duration-[--motion-fast]',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
  isExpanded && 'rotate-90',
)}
// Upgrade to: 'flex items-center justify-center h-6 w-6 -mx-1 ...'
// with <ChevronRight className="h-4 w-4" aria-hidden="true" />
```

### Drag handle with GripVertical
**Source:** `frontend/src/components/builder/FolderGroupRow.tsx` lines 182–197
**Apply to:** UX-03 BasemapGroupRow drag enable (replace hidden `<span>` at line 107)
```tsx
<button
  ref={dragHandleProps.setActivatorNodeRef}
  {...dragHandleProps.attributes}
  {...dragHandleProps.listeners}
  className="flex items-center justify-center cursor-grab opacity-35 group-hover/row:opacity-70 ..."
  onPointerDown={(e) => e.stopPropagation()}
>
  <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
</button>
```

### Widget Switch row pattern
**Source:** `frontend/src/components/builder/SettingsEditorScene.tsx` lines 173–196
**Apply to:** UX-04 (existing pattern is already correct — focus is on label clarity + duplicate-control audit)
```tsx
<div className="flex h-9 items-center gap-2 px-4 hover:bg-[var(--surface-2,...)]">
  <widget.icon className="h-4 w-4 text-muted-foreground shrink-0" />
  <span className="flex-1 text-xs text-foreground">{widgetLabel}</span>
  <Switch checked={isEnabled} onCheckedChange={() => onToggleWidget(widget.id)} />
</div>
```

### useBuilderLayout responsive hook
**Source:** `frontend/src/components/builder/hooks/use-builder-layout.ts` lines 9–37
**Apply to:** RESP-01 (NavigationControl position), RESP-02 (MapCoordReadout offset)
```ts
const { isRail, isEditorHidden } = useBuilderLayout();
// isRail = viewport < 1100px; isEditorHidden = viewport < 800px
```

### i18n key addition pattern
**Source:** `frontend/src/i18n/locales/en/builder.json` lines 940–944
**Apply to:** UX-04 (widgetsAvailabilityNote), UX-01 (expandGroup/collapseGroup aria), UX-02 (SublayerConfigIndicators aria labels)
```json
// Pattern: add under the relevant section key, then mirror to de/es/fr at the same path
"settings": {
  "widgetsAvailabilityNote": "Controls whether each widget appears on the map."
}
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/components/builder/SublayerConfigIndicators.tsx` | component | transform | No existing badge-strip indicator component in the builder; closest structure is the empty-state eyebrow or BulkActionBar badge, but neither matches the per-config-field indicator shape. UI-SPEC provides a complete spec. |

---

## Key Tracing Notes for Planner

**BUG-01 / BUG-02 root cause tracing sequence:**
1. Start at `StackRow.tsx` — the `onClick` already calls `onToggleVisibility(layer.id)` / `onRemove(layer.id)`.
2. Trace to `SortableStackRow` in `UnifiedStackPanel.tsx` (lines 151–218) — confirm the prop is passed through.
3. Trace to `UnifiedStackPanel` props received at `MapBuilderPage.tsx` — confirm `onToggleVisibility={layers.handleToggleVisibility}` and `onRemove={layers.handleRemove}` are wired.
4. Both handlers live in `use-builder-layers.ts` (delegated to `use-layer-map-sync.ts` for visibility). Stale closure on `mapInstanceRef` or missing `isStyleLoaded()` guard is the most likely source.

**UX-03 basemap drag — saved-map round-trip:**
- Basemap position derives from its `sort_order` relative to data layers — no new API field.
- The save flow in `use-builder-save.ts` already serializes `localLayers` in order; the basemap group must be included in the payload order.
- Normalizer for legacy maps (where basemap has no explicit sort_order) defaults to bottom of stack.

**INV-01 DETAIL LEVEL — expected disposition REMOVE:**
- `onDetailLevelChange` in `MapBuilderPage.tsx` line 810 is `() => { /* TODO(Phase 1038) */ }` — a no-op stub.
- `activeDetailLevel` is hard-coded `"default"` (line 801) — no state backing it.
- The toggle renders 4 pills but clicking them does nothing observable. REMOVE is the clear call unless Phase 1038 context reveals an intent to restore it.

---

## Metadata

**Analog search scope:** `frontend/src/components/builder/`, `frontend/src/components/map/`, `frontend/src/pages/`, `frontend/src/i18n/locales/`
**Files scanned:** 14 primary + 4 locale files
**Pattern extraction date:** 2026-05-17
