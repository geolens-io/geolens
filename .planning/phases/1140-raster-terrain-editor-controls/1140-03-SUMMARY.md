---
phase: 1140-raster-terrain-editor-controls
plan: "03"
subsystem: builder-editor
tags: [dem, hypsometric, color-relief, maplibre, builder, editor, i18n]
dependency_graph:
  requires: ["1140-02"]
  provides: ["EDITOR-DEM-05 color-relief companion layer"]
  affects: ["DEMEditorScene", "map-sync raster branch", "color-relief-sync module"]
tech_stack:
  added: []
  patterns: ["color-relief companion layer", "hillshade-gated editor section", "builder-private _hypso-* paint keys"]
key_files:
  created:
    - frontend/src/components/builder/color-relief-sync.ts
    - frontend/src/components/builder/__tests__/color-relief-sync.test.ts
  modified:
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx
    - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "color-relief layer recreated (remove+add) on every syncColorReliefLayer call — ColorRampProperty does not support setPaintProperty ramp update (Pitfall 1; conservative correct-by-default approach)"
  - "Section hidden in image mode; terrain mode shows hint only (no toggle/picker); hillshade mode shows full toggle + ColorRampPicker — per critical_constraints and UI-SPEC A-01/A-02"
  - "Fixed 0–4000 m elevation range (Assumption A1) — follow-up min/max-elevation control documented as v1032 candidate in SUMMARY output section"
  - "ColorRampPicker used inline (no Popover) per UI-SPEC A-07, matching HeatmapStyleControls.tsx pattern"
  - "type 'color-relief' cast via 'unknown as hillshade' in color-relief-sync.ts — @maplibre/maplibre-gl-style-spec LayerSpecification union predates color-relief; runtime safe (layer adds correctly)"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-28"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 9
---

# Phase 1140 Plan 03: DEM Hypsometric Tint Summary

One-liner: Native MapLibre `color-relief` companion layer for elevation tinting in hillshade mode, with mode-gated editor section writing builder-private `_hypso-*` paint keys.

## What Was Built

**Task 1 — `color-relief-sync.ts` companion-layer module:**

`buildElevationExpression(rampName, elevMin=0, elevMax=4000)` generates a 7-stop `['interpolate', ['linear'], ['elevation'], ...]` expression from `getRampColors()`. `syncColorReliefLayer(map, input)` adds/removes a `color-relief` layer keyed as `${layerId}-colorrelief` on the existing raster-dem source when `_hypso-enabled === true` AND `render_mode === 'hillshade'`. The layer is always removed+added on every call (ColorRampProperty/Pitfall 1). Defensive guard skips the add if the DEM source is absent. 19 unit tests covering all branches.

**Task 2 — Wiring + UI + i18n:**

`map-sync.ts` imports and calls `syncColorReliefLayer(map, adapterInput)` immediately after `syncContourLayer(...)` in the `is_dem === true` raster branch. `DEMEditorScene.tsx` has a new HYPSOMETRIC TINT `<section>` (after CONTOUR LINES, before VISIBILITY): hillshade mode renders a `Switch` (writes `_hypso-enabled`) + conditionally a `ColorRampPicker` inline (writes `_hypso-ramp`, default 'Viridis'); terrain mode renders a hint-only paragraph; image mode: section absent. Three i18n keys added to all four locales (en/de/es/fr).

## Test Coverage

| File | Tests Added | All Pass |
|------|-------------|----------|
| `color-relief-sync.test.ts` | 19 (new file) | ✓ |
| `DEMEditorScene.test.tsx` | 8 (HYPSOMETRIC TINT describe block) | ✓ |
| `map-sync.raster.test.ts` | 3 (syncColorReliefLayer wiring describe block) | ✓ |
| `resources.test.ts` | 0 new (4-locale parity verified by existing suite) | ✓ |

Total across all plan-03 test files: 88 tests, 88 pass.

`npx tsc -b --noEmit`: clean (0 errors). One cast required: `type: 'color-relief' as unknown as 'hillshade'` in `color-relief-sync.ts` because `@maplibre/maplibre-gl-style-spec` `LayerSpecification` predates the color-relief layer type; the maplibre-gl 5.24 runtime accepts it correctly.

## Deviations from Plan

None — plan executed exactly as written.

The only notable implementation detail: the plan suggested `as LayerSpecification` cast for the `addLayer` call. In practice, `@maplibre/maplibre-gl-style-spec`'s `LayerSpecification` union doesn't include `color-relief`, so casting `type` as `unknown as 'hillshade'` and the whole object as `unknown as AddLayerObject` was cleaner and avoids importing the spec type. Functionally identical.

## Assumption A1 — Elevation Range Follow-Up

The fixed 0–4000 m default range (Assumption A1 from 1140-RESEARCH.md) is documented in `color-relief-sync.ts` via `DEFAULT_ELEV_MIN` / `DEFAULT_ELEV_MAX` constants with a JSDoc note. For DEMs entirely outside this range (e.g. deep sea bathymetry or Himalayan ridgelines above 4000 m) the tint will appear saturated at one end. Recommended v1032 follow-up: add min/max elevation number inputs to the HYPSOMETRIC TINT section, writing `_hypso-elev-min` / `_hypso-elev-max` builder-private paint keys, with defaults 0/4000.

## Known Stubs

None — all controls wire to `handlePaintValue` which dispatches `onPaintChange`; `syncColorReliefLayer` reads `_hypso-*` keys and adds/removes a real MapLibre layer.

## Threat Flags

None — no new network endpoints or auth surfaces. The `_hypso-ramp` string passes through `getRampColors()` which falls back to 'YlOrRd' for unknown names (T-1140-05 mitigated).

## Self-Check

- [x] `color-relief-sync.ts` exists at `frontend/src/components/builder/color-relief-sync.ts`
- [x] Test file exists at `frontend/src/components/builder/__tests__/color-relief-sync.test.ts`
- [x] Commit `3352528d` (Task 1) present in git log
- [x] Commit `d8cace06` (Task 2) present in git log

## Self-Check: PASSED
