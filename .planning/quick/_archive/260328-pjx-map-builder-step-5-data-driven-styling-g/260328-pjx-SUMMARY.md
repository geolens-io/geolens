---
phase: 260328-pjx
plan: "01"
subsystem: frontend/map-builder
tags: [data-driven-styling, graduated-size, proportional-symbols, legend, i18n]
dependency_graph:
  requires: []
  provides: [graduated-radius-styling, graduated-width-styling, size-legend-entries]
  affects: [DataDrivenStyleEditor, LayerStyleEditor, LegendWidget, StyleConfig]
tech_stack:
  added: []
  patterns: [graduated-step-expression, size-interpolation, tdd]
key_files:
  created:
    - frontend/src/lib/__tests__/color-ramps.test.ts
  modified:
    - frontend/src/types/api.ts
    - frontend/src/lib/color-ramps.ts
    - frontend/src/components/builder/DataDrivenStyleEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/widgets/builtin/LegendWidget.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx
decisions:
  - StyleConfig.target optional with 'color' default keeps all existing graduated-color configs backward compatible
  - computeSizes() linearly interpolates classCount values between sizeRange[0] and sizeRange[1]
  - buildGraduatedSizeExpression mirrors buildGraduatedExpression shape exactly — same step expression, numeric sizes instead of color strings
  - LegendWidget graduated branch dispatches on style_config.target to select circle/line/color renderer
  - Target selector only appears when availableTargets.length > 1 AND mode === 'graduated' — polygons and categorical never show it
metrics:
  duration: 15 min
  completed_date: "2026-03-28"
  tasks_completed: 2
  files_changed: 10
---

# Phase 260328-pjx Plan 01: Map Builder Step 5 — Data-Driven Graduated Size Styling

**One-liner:** Extends data-driven styling from color-only to graduated radius (circle-radius for points) and graduated width (line-width for lines) using MapLibre step expressions, with proportional symbol legend support.

## What Was Built

### Task 1: Type extensions and expression builders (TDD)

Extended `StyleConfig` in `frontend/src/types/api.ts` with three optional fields:
- `target?: 'color' | 'radius' | 'width'` — defaults to 'color' when absent (backward compat)
- `sizes?: number[]` — per-class size values (parallel to `colors`)
- `sizeRange?: [number, number]` — [min, max] size range for UI state restoration

Added two new exported functions to `frontend/src/lib/color-ramps.ts`:
- `buildGraduatedSizeExpression(column, breaks, sizes)` — produces `['step', ['get', column], sizes[0], breaks[0], ...]`
- `getSizeProperty(geometryType, target)` — maps Point+radius → 'circle-radius', Line+width → 'line-width', else null

Created `frontend/src/lib/__tests__/color-ramps.test.ts` with 18 tests covering all behavior spec cases plus getColorProperty regression.

**Commits:**
- `8fa12e23` — test(260328-pjx): add failing tests for graduated size expression and getSizeProperty

### Task 2: DataDrivenStyleEditor target UI, LayerStyleEditor indicators, legend size support, and i18n

**DataDrivenStyleEditor:**
- Added `target` and `sizeRange` state initialized from existing config or defaults
- Computed `availableTargets` from `getLayerType(layer.dataset_geometry_type)`: circle → [color, radius], line → [color, width], fill → [color]
- Target selector row shown only when `availableTargets.length > 1 && mode === 'graduated'`
- Size range UI (two sliders) replaces color ramp picker when target is radius/width
- Size expressions generated via `buildGraduatedSizeExpression` and applied to paint
- `handleClear` resets both color and size paint properties to scalar defaults, resets target to 'color'
- `handleModeChange` forces target back to 'color' when switching to categorical mode

**LayerStyleEditor:**
- Line section: shows "Width by: {column}" when `style_config.target === 'width'`
- Circle section: shows "Radius by: {column}" when `style_config.target === 'radius'`

**LegendWidget:**
- Graduated branch now dispatches on `style_config.target`:
  - `radius` + `sizes`: renders SVG circles with radius proportional to size value
  - `width` + `sizes`: renders SVG horizontal lines with stroke-width proportional to size value
  - color/undefined: existing color swatch rendering unchanged

**i18n (all 4 locales):**
- `dataDriven.title` updated from "Data-Driven Color" to "Data-Driven Style"
- Added: `target`, `targetColor`, `targetRadius`, `targetWidth`, `sizeMin`, `sizeMax`
- Added to style section: `radiusByColumn`, `widthByColumn`

**Tests:**
- Added mock for `@/components/builder/map-sync` in DataDrivenStyleEditor test
- 4 new tests: target selector visibility for point/polygon/categorical, clear resets target

**Commits:**
- `71bfafb9` — feat(260328-pjx): graduated size styling for point/line layers with legend support

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree branch behind main**

- **Found during:** Pre-execution context check
- **Issue:** Worktree branch `worktree-agent-ac5f4c97` was at old v10.0 commit; LegendWidget and other widget infrastructure didn't exist
- **Fix:** Reset worktree branch to `main` (`git reset --hard main`) to include all widget infrastructure from prior quick tasks
- **Impact:** Unblocked execution — all referenced files now present

**2. [Rule 3 - Blocking] DataDrivenStyleEditor in main had richer version**

- **Found during:** Task 2 start — reading the actual file
- **Issue:** The component in main had additional features (per-category/per-class color editing, HexColorPicker, Popover) beyond what the plan's `<interfaces>` section described
- **Fix:** Preserved all existing functionality when writing the new version; only added target selector, size range UI, and size expression generation

**3. [Rule 3 - Blocking] Test file referenced translated text key incorrectly**

- **Found during:** Task 2 test run
- **Issue:** Initial test used `'dataDriven.target'` key string but i18n returns "Target" in test environment
- **Fix:** Changed to match actual rendered text `'Target'`

## Known Stubs

None — all data paths are wired. Size expressions are generated and emitted via `onStyleConfigChange` to the map. Legend widget reads `style_config.target` and `style_config.sizes` directly.

## Self-Check: PASSED
