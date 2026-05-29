---
phase: "1136"
name: "Per-Render-Mode Editor Polish"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1136: Per-Render-Mode Editor Polish — Context

<domain>
## Phase Boundary

Close per-editor table-stakes gaps via v1026 owned-property contracts extension. NO new `map.setPaintProperty` callsites. NO new owned-property contracts beyond extension.

**Requirements:** EDITOR-RASTER-01..04, EDITOR-LINE-01, EDITOR-LINE-02, EDITOR-FILL-04, EDITOR-BASEMAP-02, EDITOR-BASEMAP-03.

**5 ROADMAP success criteria:**
1. RasterEditor: 4 sliders (brightness, contrast, saturation, hue-rotate) + Reset; route through `RasterAdapter` `*_OWNED_PAINT_PROPERTIES` extension + v1010 `coalesceFrame` (100ms opacity / 200ms color+filter debounces). Pitfall #9: no direct setPaintProperty.
2. LineEditor: `line-cap` (butt/round/square) + `line-join` (bevel/round/miter); LineAdapter extends `*_OWNED_LAYOUT_PROPERTIES` (NOT paint — MapLibre layout properties).
3. FillEditor 3D extrusion: when `paint._height_column` present, show "Range: X–Y, N features" hint from `dataset_sample_values`.
4. BasemapEditor "No basemap" preset → transparent/single-color background; persists round-trip; renders in viewer/embed. DETAIL LEVEL toggle STAYS absent from `BasemapSublayerEditorScene` (v1011 INV-01); positive-form regression pin asserts surface stays gone.
5. Save→reload symmetry vitest covers every new control per render mode (Pitfall #2); style-JSON round-trip test verifies no paint leak or drop; grep guard for `setPaintProperty` / `setLayoutProperty` outside `layer-adapters/` + `map-sync.ts` (Pitfall #9).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion (discuss skipped). ROADMAP success criteria + Phase 1133 audit + Phase 1134 adapter post-state are the spec.

### Key Pre-Decided Anchors (from STATE.md / ROADMAP / Phase 1133)
- **Pitfall #9 (no direct setPaintProperty):** All new editor controls route through `RasterAdapter` / `LineAdapter` `*_OWNED_*_PROPERTIES` extension + v1010 `coalesceFrame` debounce. Grep guard pinned (no new hits outside `layer-adapters/` and `map-sync.ts`).
- **Pitfall #2 (save→reload symmetry):** Every new control writes AND reads from style JSON cleanly. Vitest covers serialize → deserialize → renders identically.
- **v1011 INV-01 (DETAIL LEVEL stays gone):** DO NOT restore DETAIL LEVEL toggle to BasemapSublayerEditorScene. Add positive-form `queryByRole/Text` regression pin asserting the UI surface stays absent.
- **LineEditor line-cap/line-join are LAYOUT properties (NOT paint):** MapLibre spec. Adapter extends `*_OWNED_LAYOUT_PROPERTIES` not `*_OWNED_PAINT_PROPERTIES`.
- **No new contracts:** No new owned-property categories. No new BuilderLayerAction variants. No widening BuilderActionSource.

</decisions>

<code_context>
## Existing Code Insights

Anchor files:
- `frontend/src/components/builder/RasterEditor.tsx` (stub today — 4 sliders + Reset)
- `frontend/src/components/builder/LineEditor.tsx` (add line-cap + line-join)
- `frontend/src/components/builder/FillEditor.tsx` (add 3D extrusion range hint)
- `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` (add "No basemap" preset; KEEP DETAIL LEVEL absent)
- `frontend/src/builder/layer-adapters/raster-adapter.ts` (extend `RASTER_OWNED_PAINT_PROPERTIES`)
- `frontend/src/builder/layer-adapters/line-adapter.ts` (extend `LINE_OWNED_LAYOUT_PROPERTIES`)
- `frontend/src/builder/layer-adapters/basemap-adapter.ts` (or basemap-style-mutation.ts for "No basemap" preset)
- `frontend/src/lib/builder/raf-coalesce.ts` (v1010 `coalesceFrame`)
- `frontend/src/components/builder/__tests__/` (Save-reload symmetry test pins per Pitfall #2)

</code_context>

<specifics>
## Specific Ideas

- **RasterEditor sliders:** brightness/contrast each 0–1 (default ~0.5 per MapLibre defaults); saturation -1 to 1; hue-rotate 0–360 degrees. Use existing Slider component from shadcn registry (sketch-findings-geolens).
- **Reset button:** restores all 4 to MapLibre defaults. Position consistent with FillEditor Reset position if one exists.
- **LineEditor cap/join:** dropdowns with 3 options each. Default `butt` / `miter` (MapLibre defaults).
- **FillEditor range hint:** read from `dataset_sample_values[height_column].min` / `.max` / `.count`. Format: `"Range: 12–340, 1,247 features"`. Hide if metadata absent.
- **"No basemap" preset:** new entry in basemap preset list. Background = `bg-background` (uses CSS variable so dark mode works). Persists as `basemap_id: 'none'` or similar canonical sentinel.
- **Pitfall #9 grep guard:** existing test from Phase 1133 audit. Extend with new adapter file content checks.

</specifics>

<deferred>
## Deferred Ideas

- New owned-property contracts beyond *_OWNED_PAINT_PROPERTIES / *_OWNED_LAYOUT_PROPERTIES — explicitly out of scope per "no new contracts" invariant.
- Per-feature color picker (already addressed via paint expressions in v13.8).

</deferred>
