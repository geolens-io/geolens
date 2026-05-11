---
phase: 1007-durable-builder-qa-gate-and-closeout
plan: 01
subsystem: qa
tags: [playwright, vitest, accessibility, map-builder, closeout]
requires:
  - phase: 1002-kepler-guided-builder-workflow-audit-and-triage
    provides: QA inventory and visual evidence boundaries
  - phase: 1003-map-stack-inspector-interaction-polish
    provides: stable Map Stack row and inspector contracts
  - phase: 1004-styling-and-cartography-control-polish
    provides: style/filter/label/popup contract coverage
  - phase: 1005-preview-save-share-output-parity
    provides: public-output layer identity and save/share state
  - phase: 1006-responsive-accessibility-copy-hardening
    provides: auth shell, mobile, and basemap recovery coverage
provides:
  - Seed-independent focused builder QA gate
  - Deterministic sidebar resize coverage replacing pointer-drag flake
  - Desktop/tablet/mobile Playwright builder state assertions
  - Builder and public saved-map accessibility coverage
  - Updated builder-styling smoke selectors aligned with Map Stack polish
affects: [map-builder, e2e, accessibility, catalog-badges]
tech-stack:
  added: []
  patterns: [API-created temporary test maps, keyboard slider coverage, MapLibre-only axe exclusions]
key-files:
  created: []
  modified:
    - e2e/builder.spec.ts
    - e2e/builder-styling.spec.ts
    - e2e/accessibility.spec.ts
    - frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
    - frontend/src/index.css
requirements-completed: [QA-01, QA-02, QA-03, QA-04, QA-05, QA-06]
duration: 2h
completed: 2026-05-11
---

# Phase 1007 Plan 01: Durable Builder QA Gate Summary

**The builder QA gate now runs repeatable, seed-independent checks for polished workflow state, accessibility, and public-output alignment.**

## Accomplishments

- Added desktop and tablet Playwright assertions for the builder shell, Map Stack, Data group, layer rows, save/share actions, and absence of hidden inert content.
- Replaced the known flaky pointer-drag sidebar resize smoke with deterministic keyboard slider coverage that asserts ARIA bounds, persisted localStorage width, and reload restoration.
- Added focused Vitest coverage for the same sidebar resize slider behavior in `MapBuilderPage.header-actions.test.tsx`.
- Extended accessibility E2E coverage to create a temporary public map/share token and run axe against the anonymous shared-map output with only MapLibre canvas/control exclusions.
- Fixed a raster record-type badge contrast failure exposed by the full accessibility gate.
- Updated `builder-styling.spec.ts` away from stale pre-polish selectors and icon assumptions, using current sidebar-local inspector and Map Stack row contracts.

## Task Commits

1. **Plan artifacts** - `0e2155a0` (docs)
2. **Deterministic builder resize and viewport state coverage** - `1712dcd6`, `14ded1cd` (test)
3. **Public output accessibility coverage** - `e8efe612` (test)
4. **Raster badge contrast fix** - `4059be3e` (fix)
5. **Builder styling smoke alignment** - `99184c7b`, `5d55014e`, `5472ad79`, `03609483`, `f964a461`, `59d6d8cb` (test)

## Decisions Made

- Keyboard resize is the durable replacement for sidebar pointer-drag smoke. Pointer dragging remains a UI capability, but the automated gate now proves the persisted resize contract without coordinate/hit-target flake.
- Focused builder QA uses API-created maps and fallback upload data. Demo-themed maps remain opt-in via `E2E_DEMO_SEEDED=1`.
- Screenshots were not used as acceptance evidence because the added checks assert DOM, ARIA, viewport, and accessibility state directly. Playwright failure screenshots were generated during failed intermediate runs but are not Phase 1007 visual-judgment evidence.

## Deviations from Plan

- Full `npm run e2e:smoke` was attempted, but the core segment failed before builder smoke on an existing collections data-state assertion: `collections.spec.ts:91` expected an `Add` button that was absent in the current seeded state. The phase still ran the relevant builder smoke segment directly.
- The full accessibility spec initially exposed a real non-builder raster badge contrast issue. It was fixed inline because it blocked the accessibility gate.

## Verification

- `cd frontend && npm run test -- MapBuilderPage.header-actions --run` - passed, 1 file / 3 tests.
- `cd frontend && npm run test -- MapBuilderPage.header-actions MapStackPanel map-stack LayerStyleEditor DataDrivenStyleEditor RasterLayerControls LayerFilterEditor LabelEditor PopupConfigEditor LayerLegend use-viewer-layers ViewerMap.basemap-config PublicViewerPage PublicMapViewerPage MapTitleBar SharePanel use-builder-save MapViewerGate BuilderMap.a11y BuilderMap.unit resources status-colors --run` - passed, 22 files / 215 tests.
- `cd frontend && npm run lint` - passed.
- `npx playwright test e2e/builder.spec.ts --project=chromium` - passed, 18 tests.
- `npx playwright test e2e/accessibility.spec.ts --project=chromium` - passed, 8 tests.
- `npx playwright test e2e/builder-styling.spec.ts --project=chromium` - passed, 5 tests.
- `npm run e2e:smoke:builder` - passed, 22 tests.
- `npm run e2e:smoke` - attempted; core segment result was 26 passed / 1 failed / 2 did not run due collections seed/UI drift before builder smoke.

## Next Phase Readiness

This is the final v1001 phase. The milestone is ready for closeout once Phase 1007 roadmap, state, requirements, verification, and milestone audit artifacts are updated.

## Self-Check: PASSED
