---
phase: 1136-per-render-mode-editor-polish
plan: "01"
subsystem: ui
tags: [builder, raster, layer-adapter, coalesce-frame, owned-properties, slider, vitest]

# Dependency graph
requires:
  - phase: 1134-map-functionality-and-smaller-screen-polish
    provides: raster-adapter.ts with RASTER_PAINT_DEFAULTS and WALK-R-05 split-guard
  - phase: 1010-builder-performance
    provides: coalesceFrame from raf-coalesce.ts (rAF debounce contract)
provides:
  - RASTER_OWNED_PAINT_PROPERTIES exported readonly tuple (4 user-facing raster paint keys)
  - RasterEditor 4-slider implementation (brightness/contrast/saturation/hue-rotate) + Reset collapsible
  - Save→reload symmetry (Pitfall #2) for all 4 raster controls
  - 9 raster-adapter tests + 8 RasterEditor tests (17 total, all passing)
affects:
  - 1136-07 (MCP smoke verification of RasterEditor on live raster layer)
  - Any future plan extending raster paint controls

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RASTER_OWNED_PAINT_PROPERTIES as editor source of truth — no hard-coded keys in editor component"
    - "coalesceFrame per-layer per-property key pattern (`raster-paint:{layer.id}:{property}`)"
    - "Slider mock with vi.mock('@/components/ui/slider') + coalesceFrame mock for synchronous test dispatch"

key-files:
  created:
    - frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx
  modified:
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
    - frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts

key-decisions:
  - "Expose single Brightness slider mapped to raster-brightness-min only; raster-brightness-max stays at default 1 (UI-SPEC Surface 1 design note)"
  - "coalesceFrame mock (synchronous invoke) needed in RasterEditor tests because jsdom defines requestAnimationFrame, preventing the SSR fallback from firing"
  - "Pitfall #9 comment text must not contain the literal 'map.setPaintProperty' string — grep guard catches comments too"

patterns-established:
  - "RasterEditor slider mock: vi.mock('@/components/ui/slider') + vi.mock('@/lib/builder/raf-coalesce') to get synchronous test dispatch"
  - "Reset collapsible button targeting: container.querySelectorAll('button[type=button]')[1] after opening trigger"

requirements-completed:
  - EDITOR-RASTER-01
  - EDITOR-RASTER-02
  - EDITOR-RASTER-03
  - EDITOR-RASTER-04

# Metrics
duration: 6min
completed: 2026-05-27
---

# Phase 1136 Plan 01: RasterEditor 4 Sliders + RASTER_OWNED_PAINT_PROPERTIES Summary

**RasterEditor stub replaced with 4 functional sliders (brightness/contrast/saturation/hue-rotate) + Reset collapsible routed through RASTER_OWNED_PAINT_PROPERTIES + coalesceFrame, closing EDITOR-RASTER-01..04**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-27T20:27:25Z
- **Completed:** 2026-05-27T20:33:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Exported `RASTER_OWNED_PAINT_PROPERTIES` readonly tuple (4 user-facing raster paint keys, excluding brightness-max/resampling/fade-duration/opacity) — the single source of truth editors use
- Replaced 17-line stub with 197-line RasterEditor: APPEARANCE section (4 slider rows) + Reset collapsible mirroring `BasemapSublayerEditorScene` anatomy verbatim
- All slider writes route through `coalesceFrame` + `onPaintProp` — zero new `map.setPaintProperty` callsites (Pitfall #9 clean)
- Save→reload symmetry: reads `paint` props with `RASTER_PAINT_DEFAULTS` fallback, verified via Test 7 (`aria-valuetext` round-trip)
- Reset iterates `RASTER_OWNED_PAINT_PROPERTIES` and calls `onPaintProp(key, RASTER_PAINT_DEFAULTS[key])` — non-destructive, no confirm step

## Task Commits

1. **Task 1: Export RASTER_OWNED_PAINT_PROPERTIES + extend raster-adapter test** — `4fc23978` (feat, TDD RED→GREEN)
2. **Task 2: Replace RasterEditor stub with 4 sliders + Reset, routed via coalesceFrame** — `7ea2b429` (feat, TDD RED→GREEN)

## Files Created/Modified

- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — Added `export const RASTER_OWNED_PAINT_PROPERTIES` after existing internal `RASTER_PAINT_PROPERTIES`; kept internal const unchanged (consumed by `getSupportedRasterPaint` + `syncPaint`)
- `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` — Appended 2 new tests in `describe('RASTER_OWNED_PAINT_PROPERTIES export', ...)` block; 9/9 total pass
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — Full replacement: 4 slider rows + Reset collapsible; uses existing `style.raster.*` i18n keys; Pitfall #9 clean
- `frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` — New file: 8 tests covering slider render, per-slider dispatch, Reset 4x dispatch, save/reload symmetry, default==named export

## Decisions Made

- Single Brightness slider maps to `raster-brightness-min`; `raster-brightness-max` stays at default 1 — matches UI-SPEC Surface 1 design note and common user mental model
- Used existing `style.raster.*` i18n keys (plan constraint: "DO NOT add a parallel style.rasterBrightness key set")
- Mocked `coalesceFrame` to synchronous invocation in tests because jsdom defines `requestAnimationFrame`, preventing the SSR synchronous fallback from activating

## Deviations from Plan

None — plan executed exactly as written.

**Diagnostic finding (not a deviation):** The Pitfall #9 grep guard (`grep -cE "map\.set(Paint|Layout)Property"`) was triggered by a JSDoc comment that contained the literal string. Fixed by rephrasing the comment to avoid the grep false positive. This is not a code deviation — just a comment wording fix.

## Pitfall Compliance

- **Pitfall #9:** `grep -cE "map\.set(Paint|Layout)Property" frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` → 0 (clean)
- **Pitfall #2:** Test 7 (save→reload symmetry) verifies `aria-valuetext` reflects supplied paint values for all 4 props
- **BuilderActionSource + BuilderLayerAction:** `git diff frontend/src/components/builder/builder-action-contract.ts` → empty (unchanged)

## Test Counts

- `raster-adapter.test.ts`: 9/9 (7 existing + 2 new RASTER_OWNED_PAINT_PROPERTIES tests)
- `RasterEditor.test.tsx`: 8/8 (new file)
- **Combined:** 17/17 passing

## Issues Encountered

None.

## Next Phase Readiness

- EDITOR-RASTER-01..04 closed; RasterEditor ready for MCP smoke verification in Plan 07
- Plan 02 (LineEditor line-cap/line-join) can proceed independently

## Self-Check: PASSED

- `frontend/src/components/builder/layer-adapters/raster-adapter.ts`: FOUND
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`: FOUND
- `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts`: FOUND
- `frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx`: FOUND
- Commit `4fc23978`: FOUND
- Commit `7ea2b429`: FOUND

---
*Phase: 1136-per-render-mode-editor-polish*
*Completed: 2026-05-27*
