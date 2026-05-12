---
phase: 1014-browser-baseline-and-responsive-shell
plan: 01
status: complete
completed: 2026-05-12
requirements: [BQA-01, BQA-02, BQA-03, BQA-04, BQA-05]
commits:
  - 003a03ea fix(1002): cap builder sidebar width on tablet
  - 09bee6e0 docs(1014): plan browser baseline hardening
---

# Phase 1014 Summary: Browser Baseline And Responsive Shell

## Completed

- Verified the v1002 follow-up responsive sidebar cap:
  - `useBuilderLayout` exposes `viewportWidth`.
  - `MapBuilderPage` caps rendered desktop-sidebar width by viewport while preserving the stored `geolens-builder-sidebar-width` preference.
  - Resize slider `aria-valuenow` and `aria-valuemax` reflect the rendered/max width.
  - Unit and E2E coverage assert the tablet persisted-width regression.
- Re-ran focused builder unit/component, browser smoke, accessibility, lint, and build gates against the live stack.
- Used Playwright MCP for manual browser evidence of the tablet layout, Map Stack accessibility tree, Add Dataset modal fit, basemap tab states, and console health.

## Requirement Coverage

- **BQA-01:** `npm run e2e:smoke:builder` passed 22/22 against the live app stack, covering desktop/tablet builder shell and Add Dataset modal checks.
- **BQA-02:** Playwright MCP verified Map Stack, Add Dataset modal, basemap states, and tablet layout. Console had 0 errors and 0 warnings; only React DevTools info messages appeared.
- **BQA-03:** The persisted-sidebar regression is covered by `MapBuilderPage.header-actions.test.tsx` and `e2e/builder.spec.ts`; MCP confirmed stored width `600`, rendered sidebar `470`, and map canvas `320` at `834x1112`.
- **BQA-04:** Focused builder accessibility run passed for the map builder page and Add Dataset dialog.
- **BQA-05:** Focused Vitest, lint, and production build passed.

## Verification

- `cd frontend && npm run test -- MapBuilderPage.header-actions DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run`
  - Result: passed — 6 files, 65 tests.
- `npm run e2e:smoke:builder`
  - Result: passed — 22 tests.
- `npx playwright test e2e/accessibility.spec.ts --project=chromium -g "map builder page|Add Dataset dialog"`
  - Result: passed — setup + 2 focused accessibility tests, 3 total.
- `cd frontend && npm run lint`
  - Result: passed.
- `cd frontend && npm run build`
  - Result: passed. Existing large `map-vendor` chunk warning remains unchanged.
- Playwright MCP manual check:
  - URL: `/maps/0a1c16d4-0c5b-4854-a867-40cdd11dcea3`
  - Viewport: `834x1112`
  - Stored sidebar width: `600`
  - Rendered sidebar width: `470`
  - Map canvas width: `320`
  - Add Dataset dialog on Basemap tab: `672x592`, `swap` present, `in use` present, `/import` footer link present.
  - Console: 0 errors, 0 warnings; React DevTools info only.

## Notes

- No source changes were required during this phase beyond the already-committed v1002 follow-up fix `003a03ea`.
- No schema, renderer, catalog API, or import-surface changes were made.
