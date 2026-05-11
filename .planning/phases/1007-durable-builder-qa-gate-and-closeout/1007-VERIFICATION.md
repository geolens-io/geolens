---
phase: 1007-durable-builder-qa-gate-and-closeout
status: passed
verified: 2026-05-11T22:12:00Z
requirements: [QA-01, QA-02, QA-03, QA-04, QA-05, QA-06]
---

# Phase 1007 Verification

## Result

Status: passed

Phase goal verified: builder polish coverage has been converted into repeatable automated checks, with screenshot evidence avoided because state/assertion coverage was sufficient.

## Requirement Check

| Requirement | Status | Evidence |
|-------------|--------|----------|
| QA-01 | Passed | `e2e/builder.spec.ts` creates temporary maps and fallback datasets when needed; demo maps remain opt-in through separate demo smoke gating. |
| QA-02 | Passed | Flaky pointer-drag sidebar resize smoke was replaced with keyboard slider coverage in Playwright and Vitest, asserting ARIA bounds, persisted width, and reload restoration. |
| QA-03 | Passed | Builder Playwright now asserts desktop/tablet shell state and retains existing mobile sheet/editor-tab/back-to-layer-list coverage without relying on screenshots. |
| QA-04 | Passed | `e2e/accessibility.spec.ts` covers the builder and anonymous shared-map public output; exclusions are scoped to MapLibre canvas/control internals. |
| QA-05 | Passed | No visual-judgment screenshots were required. No screenshot paths are recorded as phase evidence. |
| QA-06 | Passed | Focused Vitest run covers touched builder page shell, stack, style/filter/label/popup controls, viewer/public output alignment, save/share state, auth shell, BuilderMap a11y/unit behavior, i18n resources, and status colors. |

## Finding Closure

- F-1002-02: Protected by focused auth shell tests and builder gate selection.
- F-1002-06: Protected by mobile builder sheet/touch target Vitest and mobile Playwright inspector reachability.
- F-1002-08: Protected by BuilderMap a11y/unit coverage and full accessibility gate.

## Verification Commands

- `cd frontend && npm run test -- MapBuilderPage.header-actions MapStackPanel map-stack LayerStyleEditor DataDrivenStyleEditor RasterLayerControls LayerFilterEditor LabelEditor PopupConfigEditor LayerLegend use-viewer-layers ViewerMap.basemap-config PublicViewerPage PublicMapViewerPage MapTitleBar SharePanel use-builder-save MapViewerGate BuilderMap.a11y BuilderMap.unit resources status-colors --run` - passed, 22 files / 215 tests.
- `cd frontend && npm run lint` - passed.
- `npx playwright test e2e/builder.spec.ts --project=chromium` - passed, 18 tests.
- `npx playwright test e2e/accessibility.spec.ts --project=chromium` - passed, 8 tests.
- `npx playwright test e2e/builder-styling.spec.ts --project=chromium` - passed, 5 tests.
- `npm run e2e:smoke:builder` - passed, 22 tests.
- `npm run e2e:smoke` - attempted; stopped in core smoke with `collections.spec.ts:91` Add-button seed/UI drift after 26 passed / 1 failed / 2 did not run.

## Residual Risk

- Full smoke core still has a collections test data-state failure unrelated to the builder QA gate. Builder smoke passes directly.
- Playwright reported `NO_COLOR`/`FORCE_COLOR` warnings only; they did not affect test results.
