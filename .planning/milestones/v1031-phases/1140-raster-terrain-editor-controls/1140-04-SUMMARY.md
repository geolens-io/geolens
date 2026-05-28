---
phase: 1140-raster-terrain-editor-controls
plan: 04
subsystem: ui
tags: [raster, colormap, titiler, builder, editor, react, i18n, maplibre]

requires:
  - phase: 1140-01
    provides: band_count on MapLayerResponse (frontend type + backend schema)
  - phase: 1140-03
    provides: shared map-sync.ts with syncContourLayer/syncColorReliefLayer from Plans 02/03

provides:
  - buildColormapTileUrl(baseUrl, paint) exported from raster-adapter.ts
  - syncRasterLayer in map-sync.ts routes _colormap/_stretch through buildColormapTileUrl before URL-diff comparison
  - COLORMAP section in RasterEditor gated on band_count===1 with colormap Select (8 options) + stretch Select (minmax active; percentile/stddev disabled with "coming soon" affordance)
  - 15 style.raster.* i18n keys in en/de/es/fr (sectionColormap, colormapLabel, stretchLabel, 3 stretch options, stretchComingSoon, 8 colormap labels)

affects: [Phase 1143 close-gate (live Playwright MCP verification), Phase 1140-05 if exists]

tech-stack:
  added: []
  patterns:
    - "buildColormapTileUrl: builder-private _colormap/_stretch paint keys mutate tile URL (never reach MapLibre setPaintProperty — Pitfall 6)"
    - "DESIGN DECISION Option A: disabled Select options with coming-soon suffix for unimplemented stretch variants — non-selectable, no silent no-op"
    - "syncRasterLayer: compute effectiveTileUrl before tile-URL-diff so colormap change triggers existing source teardown/recreate path"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
    - frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts
    - frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "DESIGN DECISION Option A: minmax is the only active stretch; percentile + stddev render as DISABLED SelectItems with 'coming soon' suffix — they never fire onValueChange, preventing any silent no-op UX; backend stats-based computation is the v1032 follow-up"
  - "buildColormapTileUrl applied only on the non-hillshade raster path (useHillshade gate) — DEM/terrainrgb tiles must NOT receive colormap params"
  - "effectiveTileUrl computed once before both adapterInput.tileUrl assignment and absolutizeTileUrl call so the URL-diff teardown/recreate sees the colormap-bearing URL"
  - "Colormap proper nouns (Viridis, Inferno, Plasma, Magma, Terrain) untranslated across all 4 locales; functional labels (Grayscale, Yellow-Red, Blue-Green) get real translations"

patterns-established:
  - "Stretch coming-soon pattern: disabled Radix/shadcn SelectItem with i18n 'coming soon' suffix key — one new key (stretchComingSoon), not two rewritten label keys"

requirements-completed: [EDITOR-RASTER-COLORMAP]

duration: 5min
completed: 2026-05-28
---

# Phase 1140 Plan 04: Single-Band Raster Colormap Frontend Control Summary

**RasterEditor COLORMAP section gated on band_count===1 writes _colormap/_stretch paint keys; buildColormapTileUrl converts them to Titiler ?colormap_name= tile URL params that trigger syncRasterLayer's existing source-teardown/recreate diff**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-28T14:59:59Z
- **Completed:** 2026-05-28T15:05:04Z
- **Tasks:** 2 (TDD)
- **Files modified:** 9

## Accomplishments

- `buildColormapTileUrl(baseUrl, paint)` exported from `raster-adapter.ts`: appends `?colormap_name=viridis` (and optionally `&stretch=...`) when `_colormap` is a non-gray value; gray and empty paint return baseUrl unchanged; handles any stretch value robustly (UI only emits minmax this phase)
- `syncRasterLayer` in `map-sync.ts` now computes `effectiveTileUrl = buildColormapTileUrl(token.tile_url, paint)` on the non-hillshade path, sets `adapterInput.tileUrl` and `desiredTileUrl` from it — existing tile-URL-diff teardown/recreate re-fetches tiles on colormap change with no new mechanism
- `RasterEditor.tsx` COLORMAP section: shown only when `layer.band_count === 1`; colormap Select with 8 Titiler options writing `_colormap`; stretch Select with minmax enabled + percentile/stddev disabled with "coming soon" suffix (Option A — no silent no-op)
- 15 `style.raster.*` i18n keys in all 4 locales with real translations; `stretchComingSoon` key present in en/de/es/fr
- 10 new RasterEditor unit tests (Tests 9-18) covering band_count gating, Select interactions, disabled state; existing Tests 1-8 (4 sliders + Reset) stay green
- 9 new `buildColormapTileUrl` unit tests + 1 Pitfall 6 regression assertion; 72 total tests in the full verification suite pass

## Task Commits

1. **Task 1 (TDD): buildColormapTileUrl + syncRasterLayer** — `d9cc41d7` (feat)
2. **Task 2: COLORMAP section in RasterEditor + i18n** — `38fe0d55` (feat)

## Files Created/Modified

- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — Added exported `buildColormapTileUrl`; `_colormap`/`_stretch` NOT in `RASTER_OWNED_PAINT_PROPERTIES` (Pitfall 6)
- `frontend/src/components/builder/map-sync.ts` — Import + apply `buildColormapTileUrl` in `syncRasterLayer`; `effectiveTileUrl` gates the non-hillshade path
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — COLORMAP section (band_count===1 gate), colormap Select, stretch Select (Option A); imported shadcn Select components
- `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` — `describe('buildColormapTileUrl')` block (9 tests) + Pitfall 6 regression assertion
- `frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` — Tests 9-18 for COLORMAP section; Select mock (native `<select>`/`<option>`); updated `t()` to cover all 15 new keys; imported `within`
- `frontend/src/i18n/locales/en/builder.json` — 15 new `style.raster.*` keys
- `frontend/src/i18n/locales/de/builder.json` — 15 new `style.raster.*` keys (German)
- `frontend/src/i18n/locales/es/builder.json` — 15 new `style.raster.*` keys (Spanish)
- `frontend/src/i18n/locales/fr/builder.json` — 15 new `style.raster.*` keys (French)

## Decisions Made

**DESIGN DECISION Option A — Stretch Select:** minmax is the only active option; percentile and stddev render as `<SelectItem disabled>` with the `stretchComingSoon` i18n suffix. They never fire `onValueChange`, eliminating any silent no-op path. The v1032 follow-up will add backend statistics computation and un-disable those options. This is the honest UX: the roadmap is signaled, the feature is not falsely implied to work.

**Hillshade gate on effectiveTileUrl:** DEM layers using hillshade mode use Titiler's terrainrgb algorithm, which must not receive colormap params. The `useHillshade` branch gets `token.tile_url` unchanged; only the raster branch goes through `buildColormapTileUrl`.

**No coalesceFrame on Select writes:** Selects fire exactly once per interaction (unlike sliders which fire continuously during drag). `onPaintProp` is invoked directly without rAF debouncing — consistent with how LineEditor cap/join selects are implemented.

## Deviations from Plan

None — plan executed exactly as written. The only inline adjustment was correcting a test assertion in Test 15 that initially matched against Titiler value IDs (`ylorrd`) rather than accessible option names ("Yellow-Red") — caught on first test run and fixed before commit.

## Known Stubs

**Stretch percentile/stddev — INTENTIONAL (DESIGN DECISION Option A):** The percentile and stddev stretch SelectItems are disabled with a "coming soon" suffix. This is not a bug or accidental stub — it is the explicit design decision to signal the roadmap without providing non-functional controls. Backend statistics computation (Titiler /cog/statistics sub-call + rescale range derivation) is the v1032 follow-up. The stub is intentional and documented.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. The `_colormap`/`_stretch` values reach the backend only as tile URL query params on the existing `/raster-tiles/` endpoint (validated in Plan 01 backend with Literal allowlist). No new trust surface.

## Issues Encountered

TypeScript error on the vi.mock factory: initial `require('react')` in the Select mock triggered `TS2591 Cannot find name 'require'` in the ESM project. Fixed by using `async () => { const { createElement, Fragment } = await import('react'); ... }` pattern — consistent with how other async mocks work in the codebase.

## Next Phase Readiness

- `buildColormapTileUrl` is exported and tested; any future phase that needs to extend colormap behavior can import it from `raster-adapter.ts`
- The `_colormap`/`_stretch` paint keys are established builder-private conventions; v1032 can add stats-based percentile/stddev by simply adding backend computation + removing `disabled` from those SelectItems
- Phase 1143 (close-gate): live Playwright MCP must verify that selecting a colormap on a single-band raster layer produces visible tile re-fetch with the new colormap (headless WebGL can't paint — per VALIDATION.md Manual-Only annotation)

---

## Self-Check

- [x] `buildColormapTileUrl` exported in `raster-adapter.ts`
- [x] `buildColormapTileUrl` imported and applied in `map-sync.ts` syncRasterLayer
- [x] COLORMAP section in `RasterEditor.tsx` gated on `band_count === 1`
- [x] `_colormap`/`_stretch` absent from `RASTER_OWNED_PAINT_PROPERTIES` (Pitfall 6)
- [x] 15 i18n keys in all 4 locales
- [x] 72 tests pass (raster-adapter + RasterEditor + map-sync.raster + resources.test)
- [x] `npx tsc -b --noEmit` clean
- [x] Task commits d9cc41d7 and 38fe0d55 exist

*Phase: 1140-raster-terrain-editor-controls*
*Completed: 2026-05-28*
