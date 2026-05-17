---
phase: 1049
plan: 01
status: complete
date_completed: 2026-05-17
commits:
  - 3360021c docs(1049): resume handoff after seeding 8-layer test map (Tasks 1-2 complete)
  - c4576717 fix(1049): SF-01 BulkActionBar confirm-click clears selection before onBulkDelete fires
  - 8713b73f fix(1049): SF-02 render-mode swap leaks stale layout keys across adapter boundaries
  - 3df84554 fix(1049): SF-03 StyleJsonDialog lazy() resolves on mount instead of dialog open
  - cffe15b5 docs(1049): SMOKE-FINDINGS.md — 8 findings, 3 P0/P1 shipped inline, post-fix re-smoke PASS
requirements_satisfied: [SMOKE-01, SMOKE-02, SMOKE-03, SMOKE-04, SMOKE-05, SMOKE-06, SMOKE-07]
---

# Phase 1049 — MCP Smoke Verification (v1010.1) — Summary

## Goal

Fresh-stack interactive Playwright MCP smoke check against the five v1010 win surfaces (lazy-load, debounce+rAF, bulk-delete, LayerStyleEditor split, popup_config). Produce a classified `SMOKE-FINDINGS.md` report; ship P0/P1 fixes inline or defer-with-rationale; re-smoke after fixes.

## What shipped

### Smoke findings (8 total)

| ID | Severity | Surface | Disposition |
|----|----------|---------|-------------|
| SF-01 | P0 | BULK-DELETE | shipped-inline (`c4576717`) |
| SF-02 | P0 | LAYER-STYLE-SPLIT | shipped-inline (`8713b73f`) |
| SF-03 | P1 | LAZY-LOAD | shipped-inline (`3df84554`) |
| SF-04 | P1 | GENERAL (duplicate tile sources) | deferred-with-rationale (>1hr refactor) |
| SF-05 | P2 | GENERAL (thumbnail blob lifecycle) | deferred to tech_debt |
| SF-06 | P2 | GENERAL (pre-auth probes) | deferred to tech_debt |
| SF-07 | P2 | GENERAL (2× PUT thumbnail on load) | deferred to tech_debt |
| SF-08 | P2 | POPUP-CONFIG (basemap toast on save) | deferred to tech_debt |

### Inline fixes

**SF-01 — Bulk-delete confirm click silently no-ops.** Root cause: `UnifiedStackPanel`'s outside-click guard only scopes the inner `<div role="listbox">` (`stackPanelRef`). The BulkActionBar is rendered as a sibling sticky footer, so any mousedown inside it fired `onClearSelection()`, set `selectedIds` to `new Set()`, and unmounted the bar before React's click handler could dispatch `onBulkDelete(selectedIds)`. v1010 PERF-03 batched bulk-delete was entirely unreachable through the UI even though the backend endpoint worked. Fix: add `data-bulk-action-bar="true"` marker; extend the guard's portal-exception to skip clears inside it. Mirror of existing SP-01 (Phase 1045) hatch for the Radix DropdownMenu portal.

**SF-02 — Render-mode swap Line→Arrow throws MapLibre validation.** Root cause: `LayerEditorPanel`'s "Render as" chip row unsafely cast `option.id as 'points' | 'heatmap' | 'symbol' | 'cluster'` even though `getRenderAsOptions()` surfaces the full `RenderAsId` union (incl. `arrow`, `line`, `fill`, `stroke`, `fill-stroke`, `extrusion-3d`, `image`, `hillshade`). `handleRenderModeChange` then fell through to its default circle-adapter branch for `arrow`, leaking `line-cap`/`line-join` layout keys into a circle-layer addLayer call, which MapLibre rejected with `unknown property` errors. Fix: widen the prop type to `RenderAsId`, drop the cast, and route non-circle modes through `handleRenderAsChange` (which uses `buildRenderAsPatch()` to compute the destination's correct paint/layout).

**SF-03 — StyleJsonDialog defective `lazy()`.** Root cause: `MapBuilderPage` rendered the dialog inside `<Suspense>` unconditionally (only gated on `id` truthy, not on `showStyleJson`). React.lazy() resolves a dynamic import the moment its component mounts, regardless of what that component returns — so the chunk fetched on initial builder paint. Fix: gate the mount on `{id && showStyleJson && (...)}` so the chunk only fetches on first dialog open. Aligns with the other 4 lazy scenes.

### Deferrals

**SF-04 — Duplicate tile sources per layer.** Each layer registers its own MapLibre source even when multiple layers share the same `dataset_table_name`, causing ~4-5× tile-fetch duplication on the test map. Source-keying refactor would touch `swapLayerOnMap` / removeSource / dataset token signing / cluster-source override — coordinated migration risk well above 1hr budget. Tracked as `BUILDER-PERF-DEDUPE-SOURCES` tech-debt.

**SF-05/06/07/08 — Polish noise.** Thumbnail blob `ERR_FILE_NOT_FOUND` after login, anonymous pre-auth probes to authed endpoints, 2× initial-load `PUT /thumbnail/`, and a false-positive "Basemap connection issue" toast on save. All non-blocking; bundle into a future hygiene sweep.

## Post-fix re-smoke

| Surface | Result | Evidence |
|---|---|---|
| SF-01 bulk-delete | ✅ PASS | Exactly 1 `POST /layers/bulk-delete`; `"3 layers deleted"` toast; listbox 5 → 2 layers |
| SF-02 render-mode swap | ✅ PASS | Line ↔ Arrow round-trip clean, zero console errors |
| SF-03 StyleJsonDialog lazy | ✅ PASS | 0 hits on initial mount; chunk fetched at request #322 on first open |

## v1010 surface coverage matrix (final)

- **Lazy-load (PERF-05):** ✅ 3/5 scenes verified (Settings, BasemapGroup, StyleJsonDialog). DEM + BasemapSublayer not exercised — no DEM layer in seed; not a v1010.1 blocker.
- **Debounce + rAF (PERF-04):** ✅ Working — zero PUTs during opacity drag, zero console errors.
- **Bulk-delete (PERF-03):** ✅ Fixed inline — 1 batched POST per confirm, ~98% network reduction vs sequential DELETE preserved.
- **LayerStyleEditor split (CODE-02/CB-07):** ✅ Fixed inline — render-mode swap clean across Line/Arrow + polygon Fill/Stroke modes.
- **popup_config error (FOLLOWUP-01):** ✅ Working — named error toast on invalid template; success toast on clear + save.

## Quality gates

- TypeScript: clean (`tsc --noEmit`)
- Vitest targeted suites: 42/42 (`BulkActionBar.test.tsx` + `UnifiedStackPanel.multi-select.test.tsx`), 20/20 (`renderAs.test.ts`), 86/86 (`LayerEditorPanel.test.tsx` + `LayerStyleEditor.test.tsx`)
- Backend bulk-delete endpoint regression-checked via direct fetch — `200 + {deleted: [3 ids], failed: []}`

## Files modified

- `frontend/src/components/builder/BulkActionBar.tsx` — `data-bulk-action-bar` marker
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — outside-click guard accepts the new marker
- `frontend/src/components/builder/LayerEditorPanel.tsx` — `onRenderModeChange` prop widened to `RenderAsId`, unsafe cast removed
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — `handleRenderModeChange` dispatches non-circle modes through `handleRenderAsChange`
- `frontend/src/pages/MapBuilderPage.tsx` — `StyleJsonDialog` render gated on `showStyleJson`

## Followups / notes

- Phase 1049 introduced 1 new tech-debt entry: `BUILDER-PERF-DEDUPE-SOURCES` (SF-04 — share MapLibre sources across layers that read from the same `dataset_table_name`).
- 4 P2 polish items (SF-05/06/07/08) stacked into the next hygiene sweep.
- DEM scene + BasemapSublayer scene lazy-load remain unverified for this milestone — gating on a future seeded DEM layer test fixture.
