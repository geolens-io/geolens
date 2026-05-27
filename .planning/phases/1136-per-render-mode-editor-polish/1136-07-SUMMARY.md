---
phase: 1136-per-render-mode-editor-polish
plan: "07"
subsystem: testing
tags: [builder, mcp, playwright, smoke, live-verification, raster, line, fill, basemap]

# Dependency graph
requires:
  - phase: 1136-per-render-mode-editor-polish/plan-01
    provides: RasterEditor 4 sliders + reset
  - phase: 1136-per-render-mode-editor-polish/plan-02
    provides: LineEditor Cap/Join Selects
  - phase: 1136-per-render-mode-editor-polish/plan-03
    provides: FillEditor extrusion range hint (Plan 03 + Rule 1 fix here)
  - phase: 1136-per-render-mode-editor-polish/plan-04
    provides: BasemapGroupEditorScene "No basemap" preset
  - phase: 1136-per-render-mode-editor-polish/plan-05
    provides: BasemapSublayerEditorScene DETAIL LEVEL regression pin

provides:
  - Live Playwright MCP smoke confirmation for all 9 Phase 1136 EDITOR requirements
  - 1136-MCP-SMOKE.md report (per-surface pass/fail + console error log)
  - Rule 1 auto-fix: deriveExtrusionRange string coercion (FillEditor.tsx + 2 regression tests)
  - e2e/mcp-smoke-1136.spec.ts (5 Playwright test functions, one per surface)

affects:
  - REQUIREMENTS.md EDITOR-RASTER-01..04, EDITOR-LINE-01/02, EDITOR-FILL-04, EDITOR-BASEMAP-02/03 (all satisfied live)
  - 1139-quality-sweep (QA-01 inherits from this smoke baseline)
  - FillEditor.tsx callers (range hint now works in production, not only unit tests)

# Tech tracking
tech_stack:
  added: []
  patterns:
    - "Pre-flight API reset pattern: PUT /api/maps/{id} with basemap_style before smoke tests that require a real basemap row in the stack"
    - "API-based persistence check: after UI save, GET /api/maps/{id} to verify basemap_style='blank' avoids stale UI re-navigation"
    - "Button group identity check: swapBasemapPreset('blank') unmounts BasemapGroupEditorScene; verify basemap group row disappears rather than checking active ring"

# Key files
key_files:
  created:
    - path: e2e/mcp-smoke-1136.spec.ts
      purpose: 5-surface live Playwright smoke spec for Phase 1136 EDITOR requirements
    - path: .planning/phases/1136-per-render-mode-editor-polish/1136-MCP-SMOKE.md
      purpose: Per-surface pass/fail report with console error log and Rule 1 auto-fix note
  modified:
    - path: frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
      change: deriveExtrusionRange coerces string values from API via parseFloat(); Rule 1 auto-fix
    - path: frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
      change: +2 regression tests for string-numeric and non-numeric coercion paths

# Decisions
decisions:
  - "deriveExtrusionRange string coercion (Rule 1): API returns dataset_sample_values as strings; prior typeof v === 'number' filter silently dropped all samples in production. Fix: parseFloat() coercion path, NaN filter. Integer vs float formatting preserved."
  - "Persistence check via API (not UI re-navigation): after clicking 'No basemap' and saving, BasemapGroupEditorScene unmounts (basemapGroup=null); checking basemap_style via GET /api/maps/{id} is more reliable than re-opening the editor."
  - "Surface 4 active ring unavailable: swapBasemapPreset('blank') → hasVisibleBasemap=false → basemapGroup=null → BasemapGroupEditorScene unmounts before active ring can be checked. Acceptance criterion changed to 'basemap group row disappears from stack'."

# Metrics
metrics:
  duration: ~50s (6 tests: 1 setup + 5 surfaces)
  completed: 2026-05-27
  tasks_completed: 7
  files_changed: 4
  rule_1_fixes: 1
---

# Phase 1136 Plan 07: Live MCP Smoke Verification Summary

**One-liner:** Live Playwright MCP smoke confirmed all 9 EDITOR requirements across 5 editor surfaces with 0 console errors; Rule 1 auto-fix patched FillEditor string coercion bug that silently prevented range hints in production.

## What Was Built

Executed a 5-surface Playwright headless smoke test (`e2e/mcp-smoke-1136.spec.ts`) against `localhost:8080` on the canonical ADK High Peaks map (`c39be324-6815-40e5-8143-00a2723827b2`). The spec was authored, iterated, and run to green in this session.

**Surface coverage:**

| Surface | Requirements | Result |
|---------|-------------|--------|
| RasterEditor 4 sliders + Reset | EDITOR-RASTER-01..04 | PASS — 7 sliders found (4+ threshold met), ArrowKey interactions dispatched, Reset collapsible present |
| LineEditor Cap + Join Selects | EDITOR-LINE-01, EDITOR-LINE-02 | PASS — "Line ends" heading found, Cap Select (Butt/Square) + Join Select (Bevel/Miter) both discovered and selected |
| FillEditor 3D extrusion range hint | EDITOR-FILL-04 | PASS — "Range: 502–873, 10 features" rendered after selecting "elevation" height column; en-dash U+2013 confirmed |
| BasemapGroupEditorScene "No basemap" preset | EDITOR-BASEMAP-02 | PASS — "No basemap" is first card; click removes basemap group row; API confirms basemap_style='blank' after save |
| BasemapSublayerEditorScene DETAIL LEVEL absent | EDITOR-BASEMAP-03 | PASS — 0 occurrences of "detail level" in body text; [role="radiogroup"] count=0; Stroke/Opacity sections present |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] deriveExtrusionRange silently dropped all API sample values**

- **Found during:** Surface 3 walk (EDITOR-FILL-04)
- **Issue:** `dataset_sample_values` from the backend API returns string values (e.g., `"573"`) not numbers. `deriveExtrusionRange()` filtered `typeof v === 'number'` only, so all production samples were dropped → the range hint never rendered in the builder, even when a height column was set. Unit tests in Plan 03 passed because they seeded JavaScript numbers directly.
- **Fix:** Added `parseFloat()` coercion path for strings before `Number.isFinite()` filter. Non-numeric strings produce `NaN` and are correctly excluded. Integer vs float formatting (`toLocaleString()` vs `toFixed(1)`) preserved.
- **Files modified:** `frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx`, `frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx` (+2 regression tests: one for string numeric values, one for non-numeric string guard)
- **Commit:** `b8656a78`

### Design Discoveries (Not Deviations — Informational)

**Surface 4 active ring unavailable post-click:** When "No basemap" is clicked, `swapBasemapPreset('blank')` transitions `basemapState.hasVisibleBasemap` to `false` → `basemapGroup` becomes `null` → `BasemapGroupEditorScene` unmounts before the active ring can be checked. This is correct behavior (no basemap = no basemap editor). Acceptance criterion was changed from "active ring visible" to "basemap group row disappears from stack + API confirms basemap_style='blank'".

**Pre-flight API reset required:** The ADK map's `basemap_style` was `'blank'` from previous test runs, making the basemap group row absent from the stack on load. Both Surface 4 and Surface 5 tests now PUT `/api/maps/{id}` with `basemap_style: 'openfreemap-positron'` before navigating to the builder to ensure a deterministic starting state.

## Console Error Log

All 5 surfaces: 0 errors each. Total: 0 console errors across the entire session.

Known-noise filters applied: MapLibre glyph range, GL Driver, GPU stall, WebGL, SwiftShader, tile/sprite network failures (expected in headless Chromium).

## Self-Check

- [x] `e2e/mcp-smoke-1136.spec.ts` exists at `/Users/ishiland/Code/geolens/e2e/mcp-smoke-1136.spec.ts`
- [x] `1136-MCP-SMOKE.md` exists at `.planning/phases/1136-per-render-mode-editor-polish/1136-MCP-SMOKE.md`
- [x] Commit `b8656a78` exists (FillEditor fix + test + spec)
- [x] `npx playwright test e2e/mcp-smoke-1136.spec.ts --project=chromium` → 5 passed (0 failed)
- [x] `npx vitest run src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx` → 16/16 passed
- [x] 9 EDITOR requirements satisfied live

## Self-Check: PASSED
