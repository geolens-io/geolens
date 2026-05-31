# Phase 1158: Builder Layer Visibility & DEM Consolidation - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with audited fix shapes from REQUIREMENTS.md + STATE.md + `.planning/backlog/qa-260530-builder-visibility.md`

<domain>
## Phase Boundary

Four map-builder **rendering/visibility bug fixes** to existing components (no new UI, no new features — milestone is explicitly "fixes to existing files only"). The map builder should render basemap/data ordering, DEM rows, and DEM/terrain visibility toggles the way users expect:
- **BLDR-01 (#120):** raster/imagery basemaps must NOT occlude data when `basemap_position='top'`.
- **BLDR-02 (#123):** the visibility eye on a terrain-mode DEM layer must actually toggle 3D terrain.
- **BLDR-03 (#123):** one clearly-labeled DEM row instead of up to three confusing rows.
- **BLDR-04 (#125):** hiding a hypsometric-tint (color-relief) DEM also hides its color-relief companion.

**UI process note:** ui-phase/ui-review are intentionally skipped — these are rendering bug fixes to existing components, not new design surfaces. Visual behavior is proven in the Phase 1160 live Playwright MCP close-gate (QA-01 items b/c/d).

</domain>

<decisions>
## Implementation Decisions (all audited — lowest-touch options)

### BLDR-01 — raster basemap must stay below data at position='top'
- `reorderBasemapAboveData` (`frontend/src/components/builder/map-sync.ts:298-322`) currently skips only vector base fills (`isLandLayer`/`isWaterLayer`/`background`). **Extend it to also skip non-data raster basemap layers** (`layer.type==='raster'` whose source is NOT the data `sourcePrefix`). Pinned by a unit test in `UnifiedStackPanel.basemap-drag.test.tsx` asserting a raster basemap layer is not lifted above data at `position='top'`.

### BLDR-02 — terrain eye toggles 3D
- In `applyTerrainConfig` (`frontend/src/components/builder/BuilderMap.tsx:~394`; `demLayer` in scope at `:389`) compute `effectiveTerrainEnabled = terrainConfig.enabled && demLayer.visible`. Terrain is currently driven solely by `terrainConfig.enabled` and ignores the layer's `visible` flag, so the eye is a no-op (`map.getTerrain()` stays set).
- Extend `terrainLayerKey` (`:413-418`) with `:${String(layer.visible)}` so the effect re-runs when visibility changes. Lowest-touch option. Pinned by a test: `getTerrain()` becomes null when the terrain DEM layer is hidden and re-attaches when shown.

### BLDR-03 — one DEM row, not three
- `UnifiedStackPanel` renders one `StackRow` per `MapLayerResponse` (1:1, no synthesis), so the three rows ("DEM hillshade (1m)", "DEM hillshade (1m) rendering", "3D terrain (DEM)") come from the DEM being added as multiple layer records. Render modes are mutually exclusive per layer (`DEMEditorScene` pills).
- **Consolidate to one DEM row** with the render-mode pill; treat terrain as the **map-level setting it already is** (no separate terrain layer row). Surface duplicate "Copy N of M" metadata to flag accidental double-adds — reuse the `MapStackDuplicateMetadata` logic (`map-stack.ts:299-337`, currently unshown).
- NOTE: `map-stack.ts`/`buildMapStack` is **dead in the live UI** (only `normalize-saved-map.ts` + tests reference it) — do NOT wire fixes through it expecting live effect; the live stack is `UnifiedStackPanel`. Keep `e2e:smoke:builder` and vitest green.

### BLDR-04 — color-relief companion hides with parent
- `syncColorReliefLayer` (`frontend/src/components/builder/color-relief-sync.ts:97-112`) adds `${layerId}-colorrelief` WITHOUT a `layout.visibility` and is never passed the parent's visible state.
- `AdapterLayerInput` already carries `visible` (`types.ts:23`) and the call site (`map-sync.ts:957-959`) passes `adapterInput` with `visible` populated — so **thread the parent `visible` flag in and apply `setLayoutProperty('${layerId}-colorrelief','visibility', input.visible ? 'visible' : 'none')` on add AND on sync**. No signature change needed. Pinned by a test asserting the colorrelief companion hides with its parent.

</decisions>

<code_context>
## Existing Code Insights

### Files to change (frontend)
- `frontend/src/components/builder/map-sync.ts` (BLDR-01 `reorderBasemapAboveData`; BLDR-04 call site)
- `frontend/src/components/builder/BuilderMap.tsx` (BLDR-02 `applyTerrainConfig` + `terrainLayerKey`)
- `frontend/src/components/builder/color-relief-sync.ts` (BLDR-04 `syncColorReliefLayer`)
- `frontend/src/components/builder/UnifiedStackPanel*.tsx` (BLDR-03 DEM-row consolidation) + the DEM layer-record source
- Tests: `UnifiedStackPanel.basemap-drag.test.tsx` (BLDR-01) + new/extended vitest specs for BLDR-02/03/04.

### Patterns & gotchas (from project memory)
- **@vis.gl/react-maplibre v8:** `transformRequest` prop is ignored — use `onLoad` + imperative APIs. Declarative `<Source type="vector">` may not add tiles; use imperative `map.addSource`/`addLayer` (GeoJSON sources are fine declaratively).
- **isStyleLoaded race:** useEffect gates on `map.isStyleLoaded()` can be permanently unreachable — use `map.once('idle', retry)` recovery, not just `return`.
- **3D extrusion convention:** vector fixtures opt into 3D via `paint._height_column`; gated at `minzoom=14`.

### Test/build recipe (frontend)
- From `frontend/`: `npm run typecheck` (must be 0), `npm test` / vitest for unit specs, `npm run test:e2e -- e2e/...builder...` for the builder smoke subset (`e2e:smoke:builder`).
- Live behavior is NOT verified here — that's the Phase 1160 orchestrator-driven Playwright MCP close-gate.

</code_context>

<specifics>
## Specific Ideas

- BLDR-01 pin: `UnifiedStackPanel.basemap-drag.test.tsx` — raster basemap not lifted above data at `position='top'`.
- BLDR-02 pin: `getTerrain()` null when terrain DEM hidden, re-attaches when shown.
- BLDR-04 pin: colorrelief companion `visibility` follows parent.
- BLDR-03: keep e2e:smoke:builder + vitest green; one DEM row + render-mode pill; terrain not a separate row.
- Full root-cause analysis: `.planning/backlog/qa-260530-builder-visibility.md`. GitHub issues #120, #123, #125.

</specifics>

<deferred>
## Deferred Ideas

- Broader builder layer-stack redesign — out of scope (BLDR-03 is a targeted DEM-row consolidation, not a redesign).

</deferred>
