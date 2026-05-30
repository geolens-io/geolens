# Map Builder Bug — "Reordering basemap with only labels active shows more than just labels"

READ-ONLY investigation. Root cause confirmed empirically with a throwaway Vitest
reproduction against the real (unmocked) `map-sync` / `map-composition-sync` helpers.

## TL;DR

"Labels only" is **not** a dedicated mode/variant id — it is the emergent result of
the user toggling the basemap's Roads / Buildings / Boundaries sublayers OFF and
leaving Labels ON. The basemap's **base fills** (background, land, water) are **never
hidden** by any sublayer toggle. With the default `basemap_position = 'bottom'` those
opaque fills sit *below* the data layers, so only the label symbols (which are
re-stacked to the top) are visible over the map — giving the *appearance* of
"labels only".

Dragging the basemap row reorders it by flipping `basemap_position` to `'top'`.
`reorderBasemapAboveData` then moves **every** basemap layer — including the opaque
`background` / land / water fills — *above* the data layers. The base fills now paint
over the map and reappear, so the user sees "more than just labels."

The labels-only sublayer state is **not lost** — roads/buildings/boundaries stay
hidden correctly. The regression is purely a **z-order** problem: the always-present
base fills get lifted above the data when the basemap moves to `top`.

## How "labels only" is represented

- No `labelsOnly` flag, no preset/variant id. State lives on `MapBasemapConfig`:
  - `label_mode` (`'full' | 'subtle' | 'hidden'`) + the mirrored `showBasemapLabels`
    boolean (`basemap-state-controller.ts:116`, `:74`).
  - `road_visibility`, `boundary_visibility` (`'full' | 'subtle' | 'hidden'`),
    `building_visibility` (boolean).
- The 4 toggleable sublayers are roads / labels / buildings / boundaries
  (`basemap-state-controller.ts:101-135`, `SUBLAYER_ID_OVERRIDE_KEY` :53-58).
- Translation to MapLibre layers: `applyBasemapConfigToStyle` → `applyBasemapLayerConfig`
  (`frontend/src/lib/basemap-utils.ts:437-491`). It hides road/boundary/building/label
  layers per config via `withVisibility(..., false)`.
- CRITICAL: `background` / land / water fills are classified by `isLandLayer` /
  `isWaterLayer` (`basemap-utils.ts:309-319`) but there is **no sublayer toggle and no
  code path that ever sets `visibility: 'none'` on them** for a real basemap. They are
  only made transparent for the BLANK basemap (`basemap-utils.ts:156-158`, `:179-181`).
  So in "labels only" mode the base fills are still fully opaque and present — they are
  simply painted under the data when position = `bottom`.

## Reorder handler trace

1. Basemap row drag → `MapBuilderPage.tsx:827-839` (`handleDragEnd`). For the basemap
   group it toggles position: `currentPosition === 'top' ? 'bottom' : 'top'` and calls
   `applyBasemapPatch(setBasemapPosition(basemapState, nextPosition))`.
2. `setBasemapPosition` (`basemap-state-controller.ts:172-177`) returns
   `{ basemapConfig: { ...state.config, basemap_position } }`. It **spreads the full
   existing config**, so `road_visibility:'hidden'` etc. are preserved. (Verified — the
   labels-only sublayer state survives the reorder.)
3. `applyBasemapPatch` (`MapBuilderPage.tsx:219-227`) → `setBasemapConfig(...)`.
4. The new `basemap_position` flows to `BuilderMap`. Two effects react:
   - `BuilderMap.tsx:869-894` (dep includes `basemapConfig?.basemap_position`) → `runSync`
     → `syncMapComposition`.
   - `BuilderMap.tsx:923-932` → `applyMapBasemapAppearance` directly.
5. `applyMapBasemapAppearance` (`map-composition-sync.ts:41-63`) runs, in order:
   `reorderBasemapLabels(show)` → `applyBasemapConfigToMap` (re-applies sublayer
   visibility — this correctly re-hides roads/buildings/boundaries) →
   `reorderBasemapAboveData(position)`.

## ROOT CAUSE

`reorderBasemapAboveData` — `frontend/src/components/builder/map-sync.ts:298-319`

```ts
export function reorderBasemapAboveData(map, position, sourcePrefix = 'source-') {
  if (position !== 'top') return;
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const layer of style.layers) {
    const src = ('source' in layer) ? String(layer.source ?? '') : '';
    if (src.startsWith(sourcePrefix)) continue;   // skip data layers
    if (!map.getLayer(layer.id)) continue;
    map.moveLayer(layer.id);                        // move EVERY basemap layer to top
  }
}
```

When `position === 'top'` it moves **all** basemap layers (anything whose source is not
a data source) above the data — including the opaque `background`, land, and water
**fills**. In "labels only" mode those fills are visible (never hidden) and were
previously kept *below* the data. Lifting them above the data makes the basemap's base
imagery paint over everything, so the user sees the full basemap instead of just labels.

### Empirical confirmation

A repro built a fake style (`background`, `water` fill, `building` fill, `road` line,
`boundary` line, `road_label` symbol, `place_label` symbol, plus one data layer
`layer-D1` on `source-D1`) in labels-only config (`road/boundary='hidden'`,
`building=false`, `label_mode='full'`):

- `position='bottom'` order: `[background, water, building, road_primary, boundary_admin,
  road_label, place_label, layer-D1]` → data on top, base fills below = "labels only".
- After `position='top'` via `applyMapBasemapAppearance`:
  `[layer-D1, background, water, building, road_primary, boundary_admin, road_label,
  place_label]` → `background` and `water` fills now ABOVE `layer-D1`.
  Assertions: `background above data? true`, `water above data? true`.
- Sublayer visibility was preserved throughout (`building/road_primary/boundary_admin/
  road_label` all stayed `visibility: 'none'`), confirming the bug is z-order, not a
  lost labels-only state.

## Recommended fix (minimal)

The intent of `basemap_position='top'` is to float the basemap's **labels/details**
above the data (a common "labels over my data" pattern), NOT to repaint the opaque base
fills over the data. The fix is to make `reorderBasemapAboveData` move only the
**non-base** basemap layers — i.e. exclude background / land / water fills (and ideally
any layer whose net contribution is an opaque areal fill).

Concrete change in `frontend/src/components/builder/map-sync.ts:298-319`: skip base-fill
layers when lifting the basemap above data.

```ts
import { isLandLayer, isWaterLayer } from '@/lib/basemap-utils'; // export these (already
// module-private — they exist at basemap-utils.ts:309-319; add to the export surface,
// alongside the existing isRoadLayer/isBoundaryLayer/isTextLabelLayer exports).

export function reorderBasemapAboveData(map, position, sourcePrefix = 'source-') {
  if (position !== 'top') return;
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const layer of style.layers) {
    const src = ('source' in layer) ? String(layer.source ?? '') : '';
    if (src.startsWith(sourcePrefix)) continue;          // data layer
    // Do NOT lift the opaque base fills above data — that re-reveals the basemap
    // imagery and breaks "labels only" / overlay-on-data intent.
    if (layer.type === 'background' || isLandLayer(layer) || isWaterLayer(layer)) continue;
    if (!map.getLayer(layer.id)) continue;
    try { map.moveLayer(layer.id); } catch (err) { /* DEV warn */ }
  }
}
```

Notes / alternatives:
- `isLandLayer` already treats `type === 'background'` as land (`basemap-utils.ts:317-318`),
  so the explicit `background` check is belt-and-suspenders; `isLandLayer(layer) ||
  isWaterLayer(layer)` covers it. Both are currently module-private — they must be added
  to the export list (the file already exports `isRoadLayer`, `isBoundaryLayer`,
  `isTextLabelLayer`, `SUBLAYER_CLASSIFIERS`).
- This keeps roads/boundaries/labels/buildings (the "detail" layers) movable above data
  when the user genuinely wants the basemap detail on top, while leaving the base fills
  below the data where they belong.
- The same base-fill set is also moved by `reorderBasemapLabels` only for symbols (so
  that helper is unaffected) — no change needed there.

## Affected files

- `frontend/src/components/builder/map-sync.ts:298-319` — `reorderBasemapAboveData`
  (the fix site).
- `frontend/src/lib/basemap-utils.ts:309-319` — `isLandLayer` / `isWaterLayer` (need to
  be exported; `isRoadLayer`/`isBoundaryLayer`/`isTextLabelLayer` are already exported
  at :280-296).
- Trigger / context (no change needed, for orientation):
  - `frontend/src/pages/MapBuilderPage.tsx:827-839` — basemap-drag → `setBasemapPosition`.
  - `frontend/src/components/builder/basemap-state-controller.ts:172-177` —
    `setBasemapPosition` patch.
  - `frontend/src/components/builder/map-composition-sync.ts:41-63` —
    `applyMapBasemapAppearance` pipeline order.
  - `frontend/src/components/builder/BuilderMap.tsx:869-894`, `:923-932` — effects that
    re-run the basemap sync on `basemap_position` change.

## Suggested regression test

Add a unit test in `frontend/src/components/builder/__tests__/map-composition-sync.test.ts`
(or a new `reorder-basemap-above-data.test.ts`) using a fake map style containing a
`background` + `water` fill, a data layer on `source-*`, and `basemap_position='top'`;
assert the base fills remain BELOW the data layer in the resulting layer order while the
label/road symbols are above. (The existing composition-sync test mocks these helpers,
so it cannot catch this — the regression test must exercise the real
`reorderBasemapAboveData`.)
