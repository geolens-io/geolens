---
phase: 1035-basemap-group-folder-groups-and-dem-raster
plan: "04"
subsystem: frontend/builder
tags: [dem, scene-a, render-mode, hillshade, compass-widget, terrain-bind, type-icon]

requires:
  - phase: 1035-01
    provides: "editorScene dispatch prop on LayerEditorPanel, handleDEMTerrainBind handler in use-builder-layers, demEditor i18n keys"

provides:
  - "DEMEditorScene component (Scene A): render-as pill strip, compass widget, hillshade sliders + color swatches, terrain hint"
  - "StackRow TypeIcon: DEM raster glyph reflects render_mode (▦ image / ⛰ hillshade / ◬ terrain)"
  - "DemRenderMode type export for Plan 05 wiring"

affects:
  - 1035-05
  - frontend/builder/MapBuilderPage.tsx (Plan 05 wires DEMEditorScene via sceneContent prop)

tech-stack:
  added: []
  patterns:
    - dem-render-mode-pill-strip
    - compass-widget-hand-authored-css
    - hillshade-paint-key-write-pattern
    - render-mode-boundary-cast-not-global-type-change

key-files:
  created:
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx
  modified:
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/__tests__/StackRow.test.tsx

key-decisions:
  - "'terrain' not added to StyleConfig.render_mode union — cast at boundary (read as string, write via as StyleConfig). Defer global type extension to Phase 1038 or backend alignment."
  - "Altitude slider stored under '_dem-sun-altitude' custom paint key (MapLibre ignores unknown keys). Documents user intent; swap key if MapLibre adds native altitude support."
  - "DEMEditorScene is a standalone component, not wired through LayerEditorPanel.sceneContent yet — full wiring deferred to Plan 05 per plan spec."

patterns-established:
  - "Compass widget pattern: 90x90 circular div with N-S/E-W crosshair divs + needle div with transform-origin: center bottom; transform: translate(-50%, -100%) rotate({azimuth}deg)"
  - "DEM render mode glyph switching: layer.is_dem === true gates glyph selection; style_config.render_mode string comparison picks ⛰/◬; default is ▦"

requirements-completed: [BSR-08, BSR-09]

duration: ~12min
completed: 2026-05-13
---

# Phase 1035 Plan 04: DEMEditorScene + StackRow DEM TypeIcon Summary

**DEMEditorScene Scene A with 90x90 compass widget, hillshade sliders + color swatches, terrain-bind wiring, and StackRow TypeIcon reflecting DEM render-mode glyph (▦/⛰/◬)**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-13T15:38:00Z
- **Completed:** 2026-05-13T15:43:30Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 4 (2 new, 2 modified)

## Accomplishments

- Created `DEMEditorScene.tsx` (435 lines) with all three render-mode appearances: Image hint, Hillshade (compass + sliders + swatches), Terrain hint
- Compass widget is hand-authored CSS: 90x90 circular div with N-S/E-W crosshair lines, primary-colored 2px needle rotating to azimuth degrees
- Three hillshade sliders (Azimuth 0-360°, Altitude 0-90°, Exaggeration 0-5×) and three StyleColorPicker swatches (Highlight/Shadow/Accent)
- Terrain mode calls `onTerrainBind(layerId)` AND `onStyleConfigChange` with `render_mode: 'terrain'`
- Extended StackRow `TypeIcon` to switch glyph based on `layer.is_dem` and `style_config.render_mode` while preserving raster color tokens
- 14 DEMEditorScene behavior tests + 6 StackRow DEM type icon tests all pass (31 total across both files)

## Task Commits

Each task was committed atomically:

1. **Task 1: DEMEditorScene component (Scene A)** - `9affe960` (feat)
2. **Task 2: Update StackRow TypeIcon to show DEM render-mode glyph** - `341355ee` (feat)

## Files Created/Modified

- `frontend/src/components/builder/DEMEditorScene.tsx` — New Scene A component: render-as pill strip, compass widget, hillshade controls, terrain hint, visibility section, footer
- `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx` — 14 behavior tests covering all render modes, compass widget ARIA, slider attributes, paint key writes, color picker callbacks, terrain bind
- `frontend/src/components/builder/StackRow.tsx` — TypeIcon function extended: `if (isDEM)` glyph switch inside raster/vrt branch
- `frontend/src/components/builder/__tests__/StackRow.test.tsx` — 6 new "DEM type icon" tests: hillshade glyph, terrain glyph, image glyph, non-DEM regression, vector regression, raster token regression

## Decisions Made

1. **No global StyleConfig.render_mode type extension for 'terrain'** — The existing union is `'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster'`. Adding `'terrain'` globally would require backend alignment and touches many files. Instead, we cast `nextConfig as StyleConfig` when writing and compare `m === 'terrain'` as a string comparison when reading. Flagged for Phase 1038 type-cleanup.

2. **Altitude slider custom key `'_dem-sun-altitude'`** — MapLibre hillshade spec has no altitude parameter (`hillshade-illumination-direction` is azimuth; no elevation angle property exists). The Altitude slider stores under a custom paint key. MapLibre silently ignores unknown paint keys. This preserves user intent and is round-trippable via the existing paint dict. Comment added explaining the key is builder-side only.

3. **DEMEditorScene not wired into LayerEditorPanel.sceneContent yet** — Plan spec says full wiring is Plan 05's job. DEMEditorScene is standalone for this plan; Plan 05 connects it via `MapBuilderPage` passing `editorScene='dem'` and `sceneContent={<DEMEditorScene ... />}`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixtures needed layer_type='raster_geolens' for raster capability detection**
- **Found during:** Task 2 (StackRow DEM type icon tests)
- **Issue:** Initial test fixtures used `layer_type: null` — `getLayerCapabilities()` gates raster branch on `layer_type === 'raster_geolens'`, so the TypeIcon raster span wasn't rendered
- **Fix:** Changed DEM test fixtures to `layer_type: 'raster_geolens'` (the correct value for a DEM raster layer)
- **Files modified:** `frontend/src/components/builder/__tests__/StackRow.test.tsx`
- **Verification:** 6 DEM type icon tests now pass
- **Committed in:** 341355ee (Task 2 commit)

**2. [Rule 3 - Blocking] Worktree had no node_modules for vitest**
- **Found during:** Task 1 setup
- **Issue:** Worktree at `.claude/worktrees/agent-a5fe0cab6802fa724/frontend/` has no local `node_modules`
- **Fix:** Created symlink `frontend/node_modules -> /Users/ishiland/Code/geolens/frontend/node_modules` (same fix as Plan 01 used)
- **Files modified:** Symlink only — not tracked in git
- **Committed in:** N/A

---

**Total deviations:** 2 auto-fixed (1 bug fix in tests, 1 blocking setup)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Verification Results

| Check | Result |
|-------|--------|
| `vitest run DEMEditorScene.test.tsx` | 14/14 passed |
| `vitest run StackRow.test.tsx` | 17/17 passed (11 pre-existing + 6 new) |
| `vitest run both files` | 31/31 passed |
| `tsc --noEmit` source errors | 0 new errors |
| `eslint DEMEditorScene.tsx` | 0 errors |
| `eslint StackRow.tsx` | 0 errors |
| DEMEditorScene.tsx line count | 435 lines (≥220 ✓) |

## BSR Requirements Status

- **BSR-08** (DEM as regular raster row, render-as property, type icon reflects mode): Partially satisfied — scene exists + row glyph reflects mode. Full wiring through MapBuilderPage in Plan 05.
- **BSR-09** (render-mode switch preserves source binding, terrain mode wires map-level terrain config): Partially satisfied — switch handler preserves paint dict + calls onTerrainBind. Full wiring in Plan 05.

## Known Stubs

None — all plan contracts fully implemented in isolation. DEMEditorScene is not yet wired into MapBuilderPage (by plan design; Plan 05 does the wiring).

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes. All changes are frontend-only UI components. T-1035-04-01 (render_mode from closed enum only), T-1035-04-02 (slider values bounded by min/max), and T-1035-04-03 (layerId already shown in UI) mitigations are all applied.

## Self-Check: PASSED
