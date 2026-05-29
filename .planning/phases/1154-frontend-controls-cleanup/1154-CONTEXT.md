# Phase 1154: Frontend Controls + Cleanup - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped) — enriched with v1034 research + live code reconnaissance by the orchestrator

<domain>
## Phase Boundary

The RasterEditor exposes stretch controls for multi-band rasters, lets users configure percentile bounds + sigma, shows a coupling hint on single-band rasters, and the v1033 cleanup is done — without breaking existing vitest or smoke tests.

Requirements: **RASTER-STRETCH-03** (frontend gate), **RASTER-STRETCH-UI-01** (frontend controls), **RASTER-STRETCH-UI-02** (hint), **CLEANUP-01**.

Backend (phase 1153) already accepts `pmin`/`pmax`/`sigma` query params on the tile route and applies per-band stretch. This phase wires the frontend to send them.
</domain>

<decisions>
## Implementation Decisions

### Locked from live code reconnaissance (orchestrator-verified — do not re-investigate)
- **RasterEditor** (`frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`): the COLORMAP+STRETCH `<section>` is currently gated as ONE block on `layer.band_count === 1` (line ~186). `_colormap` and `_stretch` are builder-private paint keys written via `onPaintProp` and consumed by `buildColormapTileUrl`.
- **RASTER-STRETCH-03 frontend (gate widen):** SPLIT the gate — the **STRETCH** control becomes visible for `band_count >= 1` (i.e. multi-band too), while the **COLORMAP** control STAYS gated on `band_count === 1`. Restructure the single `band_count===1` wrapper into: colormap row (=== 1) + stretch row (>= 1). Out-of-scope reminder: NO colormap for multi-band.
- **RASTER-STRETCH-UI-01 frontend (controls):** add builder-private paint keys `_pmin`, `_pmax`, `_sigma` via `onPaintProp`, and forward them in `buildColormapTileUrl` (`raster-adapter.ts`).
  - When `_stretch === 'percentile'`: show two compact numeric inputs — pmin (default 2) and pmax (default 98). Validate client-side: `0 <= pmin < pmax <= 100`.
  - When `_stretch === 'stddev'`: show a sigma segmented control with options 1 / 2 / 3 (default 2). Mirror the existing select/segmented patterns + token classes already in RasterEditor (`h-8 text-xs`, etc.).
  - `buildColormapTileUrl` must append `pmin=`/`pmax=` only when `_stretch === 'percentile'` AND the values differ from defaults (2/98), and `sigma=` only when `_stretch === 'stddev'` AND value ≠ 2. Keep the existing "only forward non-default" discipline so default behavior produces the same URL as today.
- **RASTER-STRETCH-UI-02 (hint):** a copy-only hint ("Stretch sets the input range for the colormap" — new i18n key `style.raster.stretchColormapHint`) shown below the stretch control ONLY when `band_count === 1` AND `_stretch !== 'minmax'` AND `_colormap !== 'gray'`. No behavior change. 4-locale i18n (en/de/es/fr).

### CLEANUP-01 — SCOPED CORRECTION (orchestrator-verified, IMPORTANT)
- **`onRenderModeChange` "dead member in types.ts": ALREADY ABSENT.** Grep confirms `LayerStyleEditor/types.ts` has NO `onRenderModeChange` member (full file read — 44 lines, not present). The v1033 deferred note was a misdiagnosis or the member was already removed. **DO NOT touch the LIVE `onRenderModeChange`** that exists in `LayerEditorPanel.tsx:32` + `:265` (render-as confirm flow), wired in `MapBuilderPage.tsx:378` to `handleRenderModeChange`, with passing tests in `LayerEditorPanel.test.tsx`. CLEANUP-01 for this item = a no-op verification: confirm types.ts is clean and document it. Removing the live handler would break the render-as switch flow.
- **`hillshadeTerrainNote` unreachable advisory: REMOVE it.** Per the v1033 audit, switching a terrain-bound DEM to hillshade detaches terrain FIRST (`isTerrainBound` becomes false), so the `{isTerrainBound && (...)}` note at `DEMEditorScene.tsx:280-288` never renders in the natural flow. Resolution: **remove the note JSX block (lines ~280-288) and its 4 i18n keys** (`demEditor.hillshadeTerrainNote` in en/de/es/fr `builder.json:994`). The skip-arm guard in `map-sync.ts` (`isHillshadeTerrainBound`) is a separate, still-valid error-suppression mechanism — leave it untouched; only the unreachable UI note + its strings are removed. Update/remove any DEMEditorScene test that asserts the note.
</decisions>

<code_context>
## Existing Code Insights
- `RasterEditor.tsx`: stretch/colormap section ~line 182-241; uses shadcn `Select`, `Label`, token classes `h-8 text-xs`. Reads `paint['_stretch'] ?? 'minmax'`, `paint['_colormap'] ?? 'gray'`.
- `raster-adapter.ts` `buildColormapTileUrl(baseUrl, paint)` (~line 55): reads `_colormap`/`_stretch`, sets `colormap_name`/`stretch` params, "only forward non-default" pattern. Add `_pmin`/`_pmax`/`_sigma` here.
- `DEMEditorScene.tsx`: `isTerrainBound` prop (line 50/150), note block at 280-288.
- i18n: `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — `style.raster.*` keys + `demEditor.hillshadeTerrainNote` at line 994.
- Tests: `frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx`, `layer-adapters/__tests__/raster-adapter.test.ts`. Gates: `npm run typecheck`, `npm run test` (vitest), `npm run test:i18n` (4-locale parity), `e2e:smoke:builder`.
</code_context>

<specifics>
## Specific Ideas
- Build order: (1) `buildColormapTileUrl` pmin/pmax/sigma forwarding + unit tests; (2) RasterEditor gate split + percentile inputs + sigma segmented + hint + i18n; (3) CLEANUP-01 hillshade note removal + i18n + test; (4) typecheck/vitest/i18n green.
- i18n: add `style.raster.stretchColormapHint`, `style.raster.pminLabel`, `style.raster.pmaxLabel`, `style.raster.sigmaLabel` (or reuse minimal labels) across all 4 locales; REMOVE `demEditor.hillshadeTerrainNote` from all 4. Keep `test:i18n` parity green (equal key sets).
- Live verification of these controls happens in phase 1155 (Playwright MCP). This phase's gate is typecheck + vitest + i18n + smoke.
</specifics>

<deferred>
## Deferred Ideas
- Histogram visualizer, manual per-band min/max — out of scope.
- Live browser proof — phase 1155.
</deferred>
