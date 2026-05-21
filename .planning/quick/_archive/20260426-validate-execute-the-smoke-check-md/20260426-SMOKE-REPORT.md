# Quick Task 20260426 Smoke Report

Generated: 2026-05-04T20:59:47Z

## Result

Status: PARTIAL PASS with regressions/blockers recorded.

The main existing smoke buckets are individually runnable on the current local stack:

- Core smoke: PASS, 29 passed, 2 skipped.
- Builder smoke: PASS, 18 passed.
- Fixture smoke: PASS, 6 passed.

The aggregate smoke command is not currently repeatable after prior fixture runs because duplicate `sample` datasets make the search typeahead strict locator ambiguous.

## Environment

- App origin: `http://localhost:8080`
- Admin credentials used by Playwright setup: `admin` / `admin`
- Stack status: reachable before test execution.
- Product code changes: none.
- Commit created: none.

Pre-flight API checks passed:

- `GET /health`: 200 backend health JSON.
- `GET /api/settings/edition/`: 200 JSON with `edition`.
- `GET /api/`: 200 OGC landing JSON with `links`.
- `GET /api/conformance`: 200.
- `GET /api/collections`: 200.
- `GET /api/settings/basemaps/`: 200.
- `GET /api/settings/map-defaults/`: 200.

## Commands

| Command | Exit | Result |
| --- | ---: | --- |
| `npm run e2e:smoke:core -- --list` | 0 | Listed 31 tests in 7 files. |
| `npm run e2e:smoke:core` | 0 | 29 passed, 2 skipped. |
| `npm run e2e:smoke:builder` | 0 | 18 passed. |
| `npm run e2e:smoke:fixtures` | 0 | 6 passed. |
| `npm run e2e:smoke` | 1 | Failed in core search typeahead after earlier fixture-created duplicate data. |
| `npm run e2e:export` | 1 | Failed before export assertions because selected dataset/features had no usable extent. |
| `npx playwright test e2e/accessibility.spec.ts --project=chromium` | 1 | 5 passed, 2 failed on WCAG color contrast. |
| `npx playwright test e2e/demo-smoke.spec.ts --project=chromium` | 0 | 1 passed, 10 skipped because `E2E_DEMO_SEEDED` was not set. |
| `npx playwright test e2e/demo-smoke-anonymous.spec.ts --project=chromium` | 0 | 1 passed, 10 skipped because `E2E_DEMO_SEEDED` was not set. |

## Flows Covered

- Authentication: admin login, dashboard/search landing, logout.
- Admin: overview, users, jobs, audit log, settings subsections, published maps, sidebar navigation.
- Search/discovery: root search page, query params, typeahead navigation, mobile card readability.
- Dataset detail: map canvas, attribute table, export action, editable metadata markers, pending edit lifecycle, context guard, validation guidance, freshness guidance.
- Collections: list, create, detail, edit, add dataset, remove dataset, delete.
- Permissions: matrix UI, admin lockout, `/auth/me/permissions`, navbar/admin create menu.
- Map builder: load map, canvas visibility, sidebar behavior, add-data dialog, map info, share, save, duplicate, basemap switch, keyboard navigation, zoom to layer, resizing, collapsed persistence, raster tile 404 toast guard.
- Builder styling: categorical styling, color persistence, filter icon, labels icon.
- Fixture ingestion: vector upload and non-spatial CSV upload/detail/access/attribute-table flows.
- Export runtime: attempted, blocked by export fixture extent precondition.
- Accessibility: public search, login, dataset detail, maps list, builder, admin overview.
- Demo maps: specs discoverable and setup runs, map assertions skipped because demo seed flag was absent.

## Failures And Owners

### 1. Aggregate smoke is stateful after fixture runs

- Command: `npm run e2e:smoke`
- Failing spec: `e2e/search.spec.ts:45`, `Search Flow > prefix search supports keyboard typeahead navigation`
- Failure: `getByRole('option', { name: 'sample', exact: true })` resolved to 2 elements.
- Evidence path from run output: `test-results/search-Search-Flow-prefix--574f5-yboard-typeahead-navigation-chromium/test-failed-1.png`; error context path: `test-results/search-Search-Flow-prefix--574f5-yboard-typeahead-navigation-chromium/error-context.md`.
- Likely owner: E2E fixture isolation/search test setup. The standalone core run passed before fixture ingestion created duplicate `sample` datasets, so the aggregate failure appears data-order dependent rather than a product search crash.

### 2. Export runtime fixture selection has no extent

- Command: `npm run e2e:export`
- Failing spec: `e2e/export-runtime.spec.ts:520`, first serial export test.
- Failure location: setup assertion at `e2e/export-runtime.spec.ts:516`.
- Failure: `expect(extentFromDataset ?? extentFromFeatures).toBeTruthy()` received `null`.
- Likely owner: export runtime test fixture selection or seeded dataset metadata/features. The API suite did not reach GeoPackage, GeoJSON, Shapefile, CSV, CRS reprojection, bbox, where, or audit assertions.

### 3. Accessibility color contrast regression

- Command: `npx playwright test e2e/accessibility.spec.ts --project=chromium`
- Failing specs:
  - `e2e/accessibility.spec.ts:51`, public search page.
  - `e2e/accessibility.spec.ts:77`, dataset detail page.
- Rule: `color-contrast`, serious, WCAG 2 AA.
- Details: badge text foreground `#00884b` on background `#d7f4e0` had contrast ratio 3.87; expected 4.5:1.
- Likely owner: frontend badge/status color tokens used by search result cards and dataset detail type/status badges.

## Skips And Prerequisites

- Demo smoke required map assertions were skipped because `E2E_DEMO_SEEDED=1` was not set. The specs explicitly skip when demo data is not declared seeded.
- The current stack had enough data for core, builder, collection, upload, non-spatial, and permissions smoke. Full checklist prerequisites for raster/VRT/shared demo map coverage were not independently proven by this pass beyond the existing specs that ran.

## Report Paths

- Latest Playwright HTML report: `playwright-report/index.html`.
- Latest Playwright run metadata: `test-results/.last-run.json`.
- Failure screenshot/error-context paths above were emitted by Playwright during failing runs; later Playwright invocations may have overwritten `test-results/`.
