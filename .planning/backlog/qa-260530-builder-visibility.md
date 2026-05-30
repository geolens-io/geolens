# QA 260530 — Map Builder visibility-toggle blast radius (issue #123)

READ-ONLY audit. No files edited. Goal: determine whether the visibility-eye no-op
is isolated to terrain-mode DEM, or whether other layer types/render modes also fail
to respond. Plus: trace the DEM "three rows" issue and recommend the terrain-toggle fix.

All line refs are against the tree at audit time (branch `main`, HEAD `8d99d894`).

---

## TL;DR

- The visibility eye works correctly for **every vector render mode and for raster/hillshade
  parent layers**, INCLUDING their companion layers (fill outline + extrusion, line arrow,
  cluster circle + cluster count). Those adapters honor `input.visible` both at `addLayers`
  time and in `syncVisibility`.
- **Two real failures:**
  1. **Terrain-mode DEM** — total no-op (the known #123 bug). The `terrain` render_mode layer
     is `continue`d out of the sync loop entirely (`map-sync.ts:919-921`) so no MapLibre layer
     exists; the actual 3D surface is driven by `terrain_config.enabled`, never by the layer's
     `visible` flag.
  2. **Color-relief (hypsometric tint) companion** — partial no-op. The `${layerId}-colorrelief`
     companion is added with NO visibility and is never passed the parent's visible state, so
     hiding a hillshade DEM that has hypso-tint enabled hides the hillshade but leaves the tint
     painted. (`color-relief-sync.ts:66-113`.)

---

## Task 1 + 2 — Per-render-mode toggle table

Legend: WORKS = hides all MapLibre layers incl. companions; PARTIAL = parent hides but a
companion stays; NO-OP = eye does nothing.

| Render mode / layer type | Toggle result | Companion layers | Evidence |
|---|---|---|---|
| **fill** (polygon) | WORKS | `-outline` + `-extrusion` both hidden | `fill-adapter.ts:221-235` (`syncVisibility` sets vis on layer + outline + extrusion); add-time honors `visible` at `:95-105`, `:125`, and extrusion inherits via syncVisibility |
| **fill-extrusion / 3D** | WORKS | extrusion is the companion above; hidden with parent | `fill-adapter.ts:232-234` |
| **line** | WORKS | `-arrow` (symbol) hidden too | `line-adapter.ts:235-238` (`syncVisibility` covers layerId + arrowLayerId); add-time `:198`, arrow add-time `:120` |
| **line-gradient** | WORKS | gradient is a paint prop on the single line layer — no extra layer | same as line; `line-adapter.ts:235-238` |
| **arrow** (line render_mode='arrow') | WORKS | arrow symbol layer hidden | `line-adapter.ts:237` |
| **circle** (point) | WORKS | none | `circle-adapter.ts:72-74` |
| **symbol / icon** | WORKS | text consolidated into the symbol layer | `symbol-adapter.ts:154-156`; layout carries `visibility` at `:89` |
| **text-label (companion of fill/line/circle)** | WORKS | the `-label` layer is hidden by map-sync directly, NOT the adapter | `map-sync.ts:855-858` (after `adapter.syncVisibility`, label vis set from `layer.visible`); add-time `:836`, `:839` |
| **heatmap** | WORKS | label layer force-hidden (`'none'`) since heatmap suppresses labels | `heatmap-adapter.ts:105-107`; label handling `map-sync.ts:846-848` |
| **cluster** | WORKS | `-cluster` circle + `-cluster-count` text BOTH hidden | `cluster-adapter.ts:262-266` (`syncVisibility` covers circle + count + unclustered); add-time `:140`, `:162`, `:186` |
| **raster** (raster_geolens / image) | WORKS | none | `raster-adapter.ts:211-217` (`syncVisibility`); also synced inside `syncPaint` `:205-208`; add-time `:178-183` |
| **hillshade** (DEM render_mode='hillshade') | WORKS for the hillshade layer itself | none of its own — BUT see color-relief below | `hillshade-adapter.ts:181-187`; also in `syncPaint` `:175-178`; add-time `:152-154` |
| **color-relief / hypsometric tint companion** | **PARTIAL NO-OP** | `${layerId}-colorrelief` stays visible when parent hidden | `color-relief-sync.ts:97-112` — `addLayer` sets no `layout.visibility`; the helper has no visibility branch and is never given `input.visible` |
| **terrain** (DEM render_mode='terrain') | **TOTAL NO-OP** | n/a — no MapLibre layer is ever created | `map-sync.ts:919-921` skips the layer; surface driven by `terrain_config.enabled` via `BuilderMap.tsx:379-410` |

### Key architectural note on why most modes are safe
`syncVectorLayer` always calls `adapter.syncVisibility(map, adapterInput)` at the end
(`map-sync.ts:785` for the GeoJSON branch, `:854` for the vector-tile branch), and then
separately reconciles the label companion (`:855-858`). Every vector adapter's `syncVisibility`
enumerates ITS companion layer ids. So the vector path is structurally sound.

`syncRasterLayer` (`map-sync.ts:629-694`) is different: it **never calls `adapter.syncVisibility`**.
It relies on:
- `addLayers` honoring `visible` at create time (raster `:178-183`, hillshade `:152-154`), and
- `syncPaint` re-asserting visibility on every subsequent sync (raster `:205-208`, hillshade `:175-178`).

That is sufficient for the raster/hillshade PARENT layers (they self-heal each paint sync), which
is why raster + hillshade toggles work in practice. The gap is the **color-relief companion**:
`syncColorReliefLayer` is called from `map-sync.ts:957-959` right after `syncRasterLayer`, but it
neither reads `input.visible` nor is covered by any `syncVisibility`. It is gated only on
`_hypso-enabled === true && render_mode === 'hillshade'`.

### Companion-visibility audit (Task 2 explicit answers)
- fill `-outline`: hidden with parent ✓ (`fill-adapter.ts:229-231`)
- fill `-extrusion`: hidden with parent ✓ (`fill-adapter.ts:232-234`)
- line `-arrow`: hidden with parent ✓ (`line-adapter.ts:237`)
- cluster `-cluster` (circle): hidden ✓ (`cluster-adapter.ts:263`)
- cluster `-cluster-count` (text): hidden ✓ (`cluster-adapter.ts:264`)
- data `-label`: hidden ✓ (`map-sync.ts:855-858`)
- **color-relief `-colorrelief`: NOT hidden ✗ (the one companion bug)**

---

## Task 3 — DEM "three rows" trace

### How the stack renders rows
The live builder uses `UnifiedStackPanel.tsx`, which renders **one `StackRow` per
`MapLayerResponse`** (1:1; it iterates the `layers` array, no row synthesis). `StackRow`
chooses the glyph from `render_mode` (`StackRow.tsx:70-75`: `⛰` hillshade, `◬` terrain).
NOTE: `map-stack.ts` / `buildMapStack` (the old grouped Surface/Relief/Basemap model that
DID synthesize a derived terrain row) is **dead in the live UI** — only referenced by
`normalize-saved-map.ts` and tests. So the three rows are NOT synthetic; they are three real
layer records on the same DEM dataset.

### Why one DEM dataset yields three rows
A DEM layer's render mode is **mutually exclusive** per layer — the DEM editor pills
(`image | hillshade | terrain`, `DEMEditorScene.tsx:198-202`) flip `style_config.render_mode`
in place on a single layer (`:165-189`), they do NOT spawn new layers. Therefore three rows =
the same DEM dataset added to the map as **three separate `MapLayerResponse` records**, e.g. via
the catalog "another rendering" affordance (`builder.json:451` "another rendering" lets a dataset
be added again as a new layer). The observed titles are user/auto display names:
- "DEM hillshade (1m)" — a DEM layer, `render_mode='hillshade'` → renders + has a working eye
- "DEM hillshade (1m) rendering" — a second DEM layer on the same dataset (the "another rendering"
  duplicate) → also renders + working eye
- "3D terrain (DEM)" — a DEM layer with `render_mode='terrain'` → suppressed from the map
  (`map-sync.ts:919-921`), but still shows a row whose eye is a no-op

The confusion is twofold: (a) two of the rows are near-duplicate hillshade renderings of the same
dataset, and (b) the terrain row looks like a normal toggleable layer but is actually a proxy for
the map-level `terrain_config`.

### Consolidation recommendation (secondary item of #123)
Terrain is **map-level config**, not a layer, yet authoring it currently requires a placeholder
DEM layer carrying `render_mode='terrain'`. Recommended minimal fix, in priority order:

1. **Make terrain a property of the DEM layer, not a third row.** The DEM editor already has the
   `image/hillshade/terrain` pill group and already calls `onTerrainBind`/`onTerrainUnbind`
   (`DEMEditorScene.tsx:184-188`). Keep ONE DEM row per dataset with that render-mode selector;
   when the user picks "Terrain", set `terrain_config` AND keep the row visibly distinct
   (badge "Terrain · drives 3D surface"), but DO NOT create/keep a separate `render_mode='terrain'`
   layer row. This collapses 3 rows → 1 row + a render-mode pill, matching how vector layers expose
   render modes inside one row.
2. If a separate terrain row must remain for discoverability, **relabel + repurpose its eye**: the
   eye on a terrain row should toggle `terrain_config.enabled` (see Task 4), and the row should be
   labelled "3D terrain surface (map setting)" with a distinct (non-layer) treatment so users don't
   read it as a stackable data layer.
3. Independently, dedupe the two near-identical hillshade rows by surfacing the existing
   `MapStackDuplicateMetadata` "Copy N of M" disambiguation (already computed in `map-stack.ts:299-337`
   but not shown by `UnifiedStackPanel`/`StackRow`) so accidental double-adds are obvious.

---

## Task 4 — Terrain-toggle fix shape

**Where terrain enable is computed:** `BuilderMap.tsx:379-410` (`applyTerrainConfig`).
The gate is purely `currentTerrainConfig?.enabled && currentTerrainConfig.source_dataset_id`
(`:384`), then it finds the DEM layer by dataset id + `render_mode==='terrain'` (`:389-393`).
**`layer.visible` is never consulted** — that is the no-op.

**Where the DEM layer's `visible` flag is available:** the matched layer is `demLayer`
(`BuilderMap.tsx:389`), a full `MapLayerResponse`, so `demLayer.visible` is in scope right there.

**Recommended change (illustrative — do NOT apply in this audit):**

```ts
// BuilderMap.tsx, inside applyTerrainConfig, after the demLayer/token resolution (~:394)
const demLayerVisible = demLayer?.visible !== false;
const effectiveTerrainEnabled =
  currentTerrainConfig.enabled === true && demLayerVisible;
if (!demLayer || token?.kind !== 'raster' || !effectiveTerrainEnabled) {
  map.setTerrain(null);
  return;
}
```

Then add `demLayer?.visible` to the dependency surface. The effect's dep array is at
`BuilderMap.tsx:907-912` (`terrainConfig?.enabled`, `source_dataset_id`, `exaggeration`,
`terrainLayerKey`). Either:
- extend `terrainLayerKey` (`BuilderMap.tsx:413-418`) to include `layer.visible`
  (e.g. append `:${String(layer.visible)}` to the per-layer key string), which is the lowest-touch
  option since the effect already re-runs on `terrainLayerKey`; **or**
- add an explicit `demLayer?.visible` dependency.

`terrainLayerKey` is the cleaner hook — it already encodes per-DEM-layer identity and render_mode,
so adding `visible` keeps the toggle reactive without a new dependency.

**Companion fix for color-relief (separate, small):** give `syncColorReliefLayer` the parent's
visibility. `AdapterLayerInput` already carries `visible` (`types.ts:23`), and the call site
(`map-sync.ts:957-959`) passes `adapterInput` which has `visible` populated (`map-sync.ts:937`).
So `syncColorReliefLayer` can set `layout: { visibility: input.visible ? 'visible' : 'none' }`
on `addLayer` (`color-relief-sync.ts:97-112`) — no signature change needed.

---

## Files of record
- `frontend/src/components/builder/map-sync.ts` — `isDemTerrainVisualSuppressed` (:52-58), terrain-suppress skip (:919-921), `syncRasterLayer` (no syncVisibility call) (:629-694), `syncVectorLayer` visibility + label (:785, :854-858)
- `frontend/src/components/builder/BuilderMap.tsx` — `applyTerrainConfig` (:379-411), `terrainLayerKey` (:413-418), effect deps (:907-912)
- `frontend/src/components/builder/color-relief-sync.ts` — companion add without visibility (:66-113)
- `frontend/src/components/builder/layer-adapters/{fill,line,circle,symbol,heatmap,cluster,raster,hillshade}-adapter.ts` — per-mode `syncVisibility`
- `frontend/src/components/builder/DEMEditorScene.tsx` — render-mode pills + terrain bind/unbind (:165-202)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` / `StackRow.tsx` — 1:1 layer→row rendering (StackRow glyphs :70-75)
- `frontend/src/components/builder/map-stack.ts` — DEAD in live UI (old grouped model); duplicate disambiguation logic (:299-337) reusable for row dedupe
