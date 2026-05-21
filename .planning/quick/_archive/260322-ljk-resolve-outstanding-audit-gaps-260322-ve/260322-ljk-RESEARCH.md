# Quick Task 260322-ljk: Resolve Outstanding Audit Gaps - Research

**Researched:** 2026-03-22
**Domain:** Playwright e2e tests, multi-part geometry safety
**Confidence:** HIGH

## Summary

Two audits have non-Verified status: **260322** (Gaps -- stale Playwright selectors + multi-part geometry) and **260319-qu1** (Needs Review -- 6 human verification items). The multi-part geometry gap was fully resolved by 260320-m42. The Playwright selectors in `dataset-detail.spec.ts` were also fixed by 260320-m42. The remaining work is running the e2e suite to verify live browser behavior.

**Primary recommendation:** Run the full Playwright e2e suite against the live Docker dev environment. If all tests pass, update both audit statuses to Verified.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Fix stale Playwright selectors to unblock e2e test suite
- Run Playwright tests to verify live browser behavior for both audits
- Update audit statuses to Verified once gaps are confirmed resolved

### Claude's Discretion
- Which Playwright selectors need updating
- Whether to add new e2e test cases or fix existing ones
- How to verify the multi-part geometry fix is still intact
</user_constraints>

## Finding 1: Playwright Selectors Are Already Fixed

**Confidence: HIGH** -- verified by reading current source code

The 260322 audit reported `openWorldCountriesDataset()` used an obsolete search input placeholder. Task 260320-m42 already fixed this:

- `dataset-detail.spec.ts` now uses `openAdminCountriesDataset()` which navigates via `page.goto('/?q=Admin+0+Countries')` and clicks a link by role, bypassing the search input entirely
- The search spec (`search.spec.ts`) uses `page.getByRole('combobox', { name: 'Search geospatial data...' })` which matches the current i18n placeholder in `search.json`
- No reference to `openWorldCountriesDataset` exists anywhere in the codebase

**No selector fixes are needed.** The gap was already closed.

## Finding 2: Multi-Part Geometry Fix Is Complete

**Confidence: HIGH** -- verified by reading current source code

All three parts of the fix from 260320-m42 are present:

1. **Backend ST_Multi promotion** (`backend/app/features/service.py:29-38`): `_geometry_sql()` wraps with `ST_Multi()` when dataset column is Multi* type. Used in insert, update, and replace paths.

2. **Frontend editing guard** (`frontend/src/hooks/use-feature-editing.ts:267-270`): `isMultiPartGeometry()` checks `coordinates.length > 1` for Multi* types. If true, shows info toast and returns early -- never enters edit mode.

3. **Frontend decomposition** (`frontend/src/hooks/use-terra-draw.ts:59-72`): `extractSingleGeometry()` safely converts single-part Multi* to simple types for Terra Draw. Only called after the guard passes (so it only handles `coordinates.length === 1` cases).

4. **Tests**: `use-terra-draw.test.ts` has 7 tests for `isMultiPartGeometry` and 5 for `extractSingleGeometry`. Backend has 4 ST_Multi promotion tests.

**No code changes needed.** Verification is already automated at the unit level.

## Finding 3: E2E Test Suite Inventory

**Confidence: HIGH** -- read all spec files

11 spec files in `/Users/ishiland/Code/geolens/e2e/`:

| File | Tests | Project | Dependencies |
|------|-------|---------|--------------|
| `auth.setup.ts` | 1 | setup | None -- authenticates as admin |
| `auth.spec.ts` | 1 | chromium | Logged-out storage state |
| `search.spec.ts` | 1 | chromium | Seed data with "Reefs" dataset |
| `dataset-detail.spec.ts` | 3 (1 skipped) | chromium | Seed data with "Admin 0 Countries" |
| `upload.spec.ts` | 1 | chromium | `e2e/fixtures/sample.geojson` |
| `accessibility.spec.ts` | 6 | chromium | @axe-core/playwright, seed data |
| `admin.spec.ts` | 9 | chromium | Admin auth |
| `permissions.spec.ts` | 4 | chromium | Admin auth |
| `collections.spec.ts` | 6 | chromium | Seed data, "World Countries" dataset |
| `builder.spec.ts` | 8 | chromium | Creates test map via API |
| `export-runtime.spec.ts` | 8 | api | No browser -- pure API tests |
| `record-detail-ux-audit.spec.ts` | 8 | chromium | External qa-targets.json manifest |

**Total: ~56 tests** (varies by manifest targets).

### Key Configuration

- **Playwright version**: `@playwright/test@^1.58.2`
- **Config**: `/Users/ishiland/Code/geolens/playwright.config.ts`
- **Test dir**: `./e2e` (from project root)
- **Base URL**: `http://localhost:8080` (nginx proxy)
- **Auth**: Saves `playwright/.auth/user.json` after setup
- **Run command**: `npm run e2e` or `npx playwright test`
- **Run specific**: `npx playwright test e2e/dataset-detail.spec.ts --project=chromium`

### Prerequisite: Live Docker Environment

Tests require the full stack running via Docker: nginx (port 8080), API, PostGIS, and seed data. The `auth.setup.ts` logs in as admin/admin and saves storage state.

### Known Skip

`dataset-detail.spec.ts` test 3 ("context guard choices...") is marked `test.skip` -- this tests validation troubleshoot dialog which is not yet implemented.

### Record Detail UX Audit Dependency

`record-detail-ux-audit.spec.ts` reads from `.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/qa-targets.json` which contains hardcoded dataset UUIDs. These IDs must exist in the running database for the audit tests to pass.

## Finding 4: 260319-qu1 Human Verification Items

**Confidence: HIGH** -- read verification report

The 6 human verification items from 260319-qu1 are all live-browser rendering checks:

1. Vector tile rendering (Point, Line, Polygon) -- covered by existing e2e tests navigating to dataset detail
2. Raster hero state machine -- needs raster dataset in seed data
3. No-tile badge -- needs raster dataset without tile_url
4. VRT raster path -- needs VRT dataset in seed data
5. Edit geometry button -- partially covered by `dataset-detail.spec.ts` editable markers test
6. Fullscreen toggle -- not covered by any existing test

Items 1 and 5 are covered by `dataset-detail.spec.ts` tests running against the live app. Items 2-4 require specific dataset types in seed data. Item 6 (fullscreen) is not tested but is low risk.

## Common Pitfalls

### Pitfall 1: Missing Seed Data
**What goes wrong:** Tests fail because expected datasets (Admin 0 Countries, Reefs, qa-targets UUIDs) are not in the database.
**How to avoid:** Ensure the development database has Natural Earth sample data loaded before running tests.

### Pitfall 2: Stale Auth State
**What goes wrong:** `playwright/.auth/user.json` contains expired JWT tokens from a previous session.
**How to avoid:** Delete `playwright/.auth/` before running tests, or let the setup project regenerate it.

### Pitfall 3: record-detail-ux-audit Manifest
**What goes wrong:** The qa-targets.json contains dataset IDs that may not exist in the current database.
**How to avoid:** Either update the manifest or skip that spec file when running verification.

## Sources

### Primary (HIGH confidence)
- Direct code reading of all 11 e2e spec files
- Direct code reading of `use-terra-draw.ts`, `use-feature-editing.ts`, `features/service.py`
- 260320-m42 SUMMARY.md confirming fix was shipped
- 260322 VERIFICATION.md documenting the original gaps
- 260319-qu1 VERIFICATION.md documenting human verification items
