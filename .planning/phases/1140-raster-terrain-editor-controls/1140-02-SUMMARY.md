---
phase: 1140-raster-terrain-editor-controls
plan: 02
subsystem: ui
tags: [maplibre, dem, contour, builder, editor, maplibre-contour, i18n]

# Dependency graph
requires:
  - phase: 1140-raster-terrain-editor-controls
    provides: hillshade-adapter with raster-dem source (encoding=mapbox), DEMEditorScene anatomy

provides:
  - contour-sync.ts: ensureDemSource (lazy DemSource registry keyed by sourceId) + syncContourLayer (add/remove/update companion line layer from _contour-* keys)
  - DEMEditorScene CONTOUR LINES section: toggle + interval + color + weight in hillshade/terrain modes
  - syncContourLayer wired into syncLayersToMap raster branch for is_dem layers
  - maplibre-contour@0.1.0 installed in frontend/package.json
  - 4-locale i18n parity (en/de/es/fr) for 5 new demEditor keys

affects: [DEMEditorScene, map-sync, contour-sync, builder tests, i18n resources test]

# Tech tracking
tech-stack:
  added:
    - "maplibre-contour@0.1.0 (client-side contour vector tiles from raster-dem tiles, BSD-3, zero deps)"
  patterns:
    - "Builder-private _contour-* paint keys: never added to RASTER_OWNED_PAINT_PROPERTIES, never reach MapLibre setPaintProperty"
    - "Companion line layer keyed by ${layerId}-contour, companion vector source by ${sourceId}-contour"
    - "DemSource registry: module-level Map<string, DemSource>, keyed by sourceId, setupMaplibre called exactly once"
    - "interval→threshold mapping: {9:[N*5], 11:[N,N*5], 13:[max(10,N/2),N]} — standard cartographic multi-zoom density"
    - "vite.config.ts resolve alias for packages with non-standard exports (module/browser conditions not import)"

key-files:
  created:
    - "frontend/src/components/builder/contour-sync.ts"
    - "frontend/src/components/builder/__tests__/contour-sync.test.ts"
  modified:
    - "frontend/src/components/builder/map-sync.ts"
    - "frontend/src/components/builder/DEMEditorScene.tsx"
    - "frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx"
    - "frontend/src/components/builder/__tests__/map-sync.raster.test.ts"
    - "frontend/src/i18n/locales/en/builder.json"
    - "frontend/src/i18n/locales/de/builder.json"
    - "frontend/src/i18n/locales/es/builder.json"
    - "frontend/src/i18n/locales/fr/builder.json"
    - "frontend/package.json"
    - "frontend/package-lock.json"
    - "frontend/vite.config.ts"

key-decisions:
  - "maplibre-contour CJS alias added to vite.config.ts resolve.alias (maplibre-contour uses module/browser export conditions, not import; vitest node env requires CJS)"
  - "DemSource type derived via InstanceType<typeof mlcontour.DemSource> — package exports the class inside the default object, not as a named type export"
  - "syncContourLayer placed in separate contour-sync.ts module (not inside map-sync.ts) to keep map-sync below 500 LOC addition threshold and make testing cleaner"
  - "vi.hoisted() used for mockSyncContourLayer in map-sync.raster.test.ts to avoid ReferenceError from vi.mock hoisting"
  - "Companion line layer inserted BEFORE (below) the hillshade layer via map.addLayer(spec, input.layerId) so hillshade shading renders on top"

requirements-completed: [EDITOR-DEM-04]

# Metrics
duration: 25min
completed: 2026-05-28
---

# Phase 1140 Plan 02: DEM Contour-Line Overlay Summary

**maplibre-contour companion line layer for DEM editor: client-side contour tiles from raster-dem source via _contour-* builder-private paint keys, toggle/interval/color/weight controls in DEMEditorScene hillshade+terrain modes**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-28T10:40:00Z
- **Completed:** 2026-05-28T10:49:00Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- `maplibre-contour@0.1.0` installed in `frontend/package.json` (T-1140-SC re-verified: version=0.1.0, repo=onthegomap/maplibre-contour, BSD-3, zero deps)
- `contour-sync.ts` created: `ensureDemSource` (lazy DemSource per sourceId, setupMaplibre called ≤1× per source) + `syncContourLayer` (add/remove/update companion `line` layer from `_contour-*` keys, interval→threshold multi-zoom mapping, try/catch degradation guard)
- `syncContourLayer` wired into `syncLayersToMap` raster branch for `is_dem===true` layers, passing `desiredSources` to keep contour source alive while enabled
- CONTOUR LINES section added to `DEMEditorScene` between APPEARANCE and VISIBILITY (hillshade/terrain modes only, hidden in image mode per UI-SPEC A-01): toggle + interval [10,500m] + StyleColorPicker + weight [0.5,4px]
- 69 tests passing (10 contour-sync unit + 21 DEMEditorScene + 32 map-sync.raster + 6 i18n resources); tsc clean

## Task Commits

1. **Task 1: Install maplibre-contour + contour-sync companion-layer module** - `5dca3118` (feat)
2. **Task 2: Wire syncContourLayer into map-sync loop + render CONTOUR LINES editor section** - `afa91e19` (feat)

## Files Created/Modified

- `frontend/src/components/builder/contour-sync.ts` — new: DemSource registry + syncContourLayer
- `frontend/src/components/builder/__tests__/contour-sync.test.ts` — new: 10 unit tests
- `frontend/src/components/builder/map-sync.ts` — import + call syncContourLayer for DEM layers
- `frontend/src/components/builder/DEMEditorScene.tsx` — import Switch + CONTOUR LINES section
- `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx` — 7 new CONTOUR LINES tests
- `frontend/src/components/builder/__tests__/map-sync.raster.test.ts` — 4 syncContourLayer wiring tests
- `frontend/src/i18n/locales/en/builder.json` — 5 new demEditor keys
- `frontend/src/i18n/locales/de/builder.json` — 5 new demEditor keys (DE)
- `frontend/src/i18n/locales/es/builder.json` — 5 new demEditor keys (ES)
- `frontend/src/i18n/locales/fr/builder.json` — 5 new demEditor keys (FR)
- `frontend/package.json` — maplibre-contour^0.1.0 dependency
- `frontend/vite.config.ts` — maplibre-contour CJS alias for vitest node env

## Decisions Made

- **vite.config.ts CJS alias:** maplibre-contour uses `module`/`browser` export conditions (not `import`). Vitest running in node environment could not resolve the package. Added `resolve.alias['maplibre-contour']` pointing to `dist/index.cjs` so tests work without changing the runtime bundle path (Vite browser builds resolve `module` condition natively).
- **DemSource type via InstanceType:** The package exports `DemSource` as a property of the default object, not as a named export. `import type { DemSource } from 'maplibre-contour'` fails. Used `type DemSource = InstanceType<typeof mlcontour.DemSource>` to derive the instance type.
- **vi.hoisted() in map-sync.raster.test.ts:** vi.mock factory is hoisted before variable declarations, so `const mockSyncContourLayer = vi.fn()` above the factory causes `ReferenceError: Cannot access before initialization`. Fixed with `vi.hoisted(() => ({ mockSyncContourLayer: vi.fn() }))` which runs inside the hoisted zone.
- **contour-sync.ts as separate module:** Kept contour sync logic out of map-sync.ts to avoid adding >300 LOC to an already large file and to make the companion-layer logic independently testable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] maplibre-contour export resolution in vitest**
- **Found during:** Task 1 (contour-sync.test.ts first run)
- **Issue:** `maplibre-contour` package exports only `module`/`browser` conditions; vitest node env couldn't resolve `.` from the exports field
- **Fix:** Added `resolve.alias['maplibre-contour']` to `vite.config.ts` pointing to `dist/index.cjs`
- **Files modified:** `frontend/vite.config.ts`
- **Committed in:** `5dca3118` (Task 1 commit)

**2. [Rule 1 - Bug] vi.mock hoisting ReferenceError in map-sync.raster.test.ts**
- **Found during:** Task 2 (first test run after adding contour-sync mock)
- **Issue:** `mockSyncContourLayer` declared with `const` above `vi.mock` factory; vi.mock is hoisted before `const` declarations → ReferenceError
- **Fix:** Wrapped the spy in `vi.hoisted(() => ...)` which executes inside the hoisted zone
- **Files modified:** `frontend/src/components/builder/__tests__/map-sync.raster.test.ts`
- **Committed in:** `afa91e19` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs — both package/test tooling issues, not behavioral)
**Impact on plan:** Both fixes necessary for tests to run. No scope creep. Plan logic delivered exactly as specified.

## Issues Encountered

- `MockDemSource` in contour-sync.test.ts initially written as an arrow function (`vi.fn().mockImplementation(() => ({...}))`); vitest's `new Mock(...)` requires a constructor function. Fixed by declaring `function MockDemSource()` (constructor-compatible function expression).

## Known Stubs

None — the CONTOUR LINES section writes real `_contour-*` paint keys; syncContourLayer reads them and wires a real companion layer. No hardcoded empty values flowing to UI rendering.

## Threat Flags

None — `_contour-*` keys are client-side style state, never reach the backend or a network query. `maplibre-contour` was pre-audited (T-1140-SC, slopcheck OK, BSD-3, zero deps) and re-verified before install.

## Self-Check: PASSED

Files exist:
- `frontend/src/components/builder/contour-sync.ts` ✓
- `frontend/src/components/builder/__tests__/contour-sync.test.ts` ✓

Commits exist:
- `5dca3118` ✓
- `afa91e19` ✓

## Next Phase Readiness

- EDITOR-DEM-04 complete; contour-sync.ts is the integration surface for any follow-up (e.g. level-aware styling — major vs minor lines via the `level` property on the `contours` source-layer).
- Phase 1140 Plan 03 (EDITOR-DEM-05 hypsometric tint) can build on the same companion-layer pattern established here.
- Manual contour rendering verified at Phase 1143 Playwright MCP close-gate (headless WebGL cannot paint — see VALIDATION.md Manual-Only).

---
*Phase: 1140-raster-terrain-editor-controls*
*Completed: 2026-05-28*
