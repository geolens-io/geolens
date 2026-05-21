# Test Coverage Audit Report (Deep Dive)

**Date:** 2026-03-19
**Project:** GeoLens
**Audit depth:** Hands-on — ran suites, sampled test quality, inspected configs, identified easy wins

---

## 1. Current State Summary

| Layer | Test Files | Source Files | Tests | Coverage | CI Status |
|-------|-----------|-------------|-------|----------|-----------|
| Backend (pytest) | 90 | 189 | 1,326 | **70.86%** stmts | Passing (PostGIS container) |
| Frontend Unit (vitest) | 50 | ~244 | 299 (289 pass, 2 fail, 8 todo) | **22.12%** stmts | 2 failing |
| E2E (Playwright) | 10 | N/A | ~50 scenarios | N/A | Runs after all gates |
| Linting (eslint + ruff) | N/A | All | N/A | N/A | Separate CI jobs |
| Security (bandit + pip-audit) | N/A | Backend | N/A | N/A | Separate CI job |

### Frontend Coverage Breakdown (vitest v8)

| Metric | Coverage |
|--------|----------|
| Statements | **22.12%** |
| Branches | **22.63%** |
| Functions | **18.86%** |
| Lines | **22.76%** |

### Backend Coverage (pytest-cov)

| Metric | Coverage | Covered / Total |
|--------|----------|-----------------|
| Statements | **70.86%** | 7,227 / 10,199 |

### 2 Pre-Existing Failing Tests

1. `src/i18n/resources.test.ts` — locale parity check expects `nav.importData` key that was removed
2. `src/components/layout/__tests__/PageShell.test.tsx` — expects `py-6`/`space-y-6` but component now uses `py-4`/`space-y-4`

---

## 2. Test Quality Assessment

### Frontend Test Infrastructure — Grade: B+

**Strengths:**
- Custom `test-utils.tsx` with auto-wrapped QueryClientProvider + MemoryRouter + route-aware rendering
- Proper QueryClient config: `retry: false`, `gcTime: 0` for deterministic tests
- Complete maplibre-gl mock suite (Map, Marker, Popup, NavigationControl) with method chaining
- Zustand persist store cleanup in `afterEach()` via localStorage.clear()
- Consistent `userEvent.setup()` for user interactions (not fireEvent)
- Heavy use of `getByRole()` — semantically correct queries
- Zero snapshot tests (good — no brittle snapshots)
- `vi.useFakeTimers()` / `vi.useRealTimers()` used properly in time-based tests

**Weaknesses:**
- **No MSW integration** — 236 manual `vi.mock()` calls across 50 test files. Every test re-mocks dependencies individually.
- **Page tests are over-mocked** — e.g., `DatasetPage.edit-affordances.test.tsx` mocks DatasetMap, tabs, dialogs, store, router. Tests internal wiring, not user behavior.
- **No shared test fixtures** — each file has inline factories (`mockUser()`, `makeCogSource()`, `createAction()`) that duplicate logic.
- **`--passWithNoTests` flag** on test scripts hides when tests get deleted.
- **No coverage thresholds** — CI collects coverage but never fails on regression.

### Backend Test Infrastructure — Grade: A-

**Strengths:**
- Session-scoped DB creation with Alembic migrations (one DB per session, not per test)
- Function-scoped `AsyncClient` + dedicated async engine per test
- Role-based auth fixtures: `admin_auth_header`, `editor_auth_header`, `viewer_auth_header` with unique UUID-based users
- `fakeredis.aioredis` for cache tests (real async interface, no DB needed)
- `moto` for S3 tests (clean boto3 mocking)
- 65% of tests are `async def` — native async handling
- Mocks focused on external boundaries only (LLM, S3, Redis), not internal functions

**Weaknesses:**
- **No automatic transaction rollback** — tests share session-scoped DB, rely on manual `_cleanup_table()` calls. Order-dependent failures possible if cleanup fails.
- **Minimal `@pytest.mark.parametrize`** — only 3 tests use it. Auth RBAC tests, visibility tests, and OGC pagination tests manually repeat similar assertions across roles.
- **5 completely untested modules**: `public_urls.py` (224 lines), `worker_health.py` (60 lines), `marketplace.py` (30 lines), `logging_config.py` (69 lines), `database.py` (34 lines)
- **Quicklook generation untested** — both `raster/quicklook.py` and `vector/quicklook.py` have no unit tests.

### E2E Infrastructure — Grade: B+

**Strengths:**
- Dual project setup: chromium (with persistent auth) + api (export tests)
- Proper fixtures: `deriveDistinctDraft`, `openWorldCountriesDataset`, `setStoredUserRoles`
- Screenshots on failure, video on retry, 2 retries in CI
- Good parallelization control: `fullyParallel: false`, `workers: 1`

**Weaknesses:**
- Inline selectors — no Page Object Model pattern
- 10 specs total — missing critical flows (map builder, VRT creation, settings)

---

## 3. CI Pipeline Assessment

### Pipeline Structure (`.github/workflows/ci.yml`)

```
backend-lint ──┐
backend-test ──┤
frontend-lint ─┼──► e2e-test (depends on all 5)
frontend-test ─┤
security-scan ─┘
```

### Quality Gates Currently Enforced

| Gate | Enforced | Tool |
|------|----------|------|
| Python linting | Yes | ruff check |
| Python formatting | Yes | ruff format --check |
| TypeScript type safety | Yes | tsc --noEmit |
| ESLint rules | Yes | eslint (typescript-eslint, react-hooks, jsx-a11y) |
| i18n key parity | Yes | test:i18n |
| Frontend tests pass | Yes | vitest run |
| Backend tests pass | Yes | pytest |
| E2E tests pass | Yes | Playwright |
| Security scan | Yes | bandit + pip-audit |
| **Frontend coverage threshold** | **NO** | — |
| **Backend coverage threshold** | **NO** | — |
| **Bundle size budget** | **NO** | — |
| **Dead code detection** | **NO** | — |

---

## 4. Frontend Unit Test Gaps (Priority Order)

### Coverage by Directory

| Directory | Stmts % | Test Files | Source Files | Status |
|-----------|---------|-----------|-------------|--------|
| stores/ | **75.38%** | 3 | 3 | Well tested |
| layout/ | **71.00%** | 6 | 9 | Good |
| lib/ | **63.12%** | 5 | 15 | Moderate |
| auth/ | **58.57%** | 5 | 7 | Moderate |
| dataset/ | **34.69%** | 10 | 43 | Large gap |
| drawing/ | **36.61%** | 0 | 2 | Indirect only |
| search/ | **32.14%** | 5 | 14 | Moderate gap |
| create/ | **26.92%** | 0 | 1 | Low |
| maps/ | **21.05%** | 0 | 5 | No tests |
| import/ | **20.86%** | 1 | 14 | Large gap |
| hooks/ | **18.81%** | 5 | 27 | Major gap |
| pages/ | **18.80%** | 3 | 19 | Major gap |
| builder/ | **12.57%** | 2 | 15 | Major gap |
| api/ | **12.40%** | 1 | 17 | Major gap |
| collections/ | **4.79%** | 0 | 8 | No tests |
| admin/ | **3.38%** | 1 | 27 | Nearly untested |
| map/ | **2.77%** | 0 | 2 | No tests |
| settings/ | **0%** | 0 | 1 | No tests |
| viewer/ | **0%** | 0 | 2 | No tests |

### Components Without Any Test Files (7 directories)

1. **collections/** (8 files) — CollectionCard, CreateDialog, DatasetList, DeleteDialog, EditDialog, MembershipManager, PermissionBadges, CardSkeleton
2. **maps/** (5 files) — MapCard, MapCardGrid, CreateDialog, DeleteDialog, CardSkeleton
3. **drawing/** (2 files) — AttributeForm, DrawingToolbar
4. **map/** (2 files) — FeaturePopup, MapLegend
5. **viewer/** (2 files) — LayerLegend, ViewerMap
6. **create/** (1 file) — CreateDatasetDialog
7. **settings/** (1 file) — ApiKeySection

### Pages Without Tests (10 of 12 + 7 admin)

Tested: DatasetPage (2 test files), CollectionDetailPage (1 test file)

**Untested:**
- `SearchPage.tsx` — most-used page, 0% coverage
- `CollectionsPage.tsx` — browse collections, 0% coverage
- `ImportPage.tsx` — data import workflow, 0% coverage
- `LoginPage.tsx` — authentication entry, 0% coverage
- `RegisterPage.tsx` — user registration, 0% coverage
- `MapBuilderPage.tsx` — map builder (1085 lines), 0% coverage
- `MapsPage.tsx` — map gallery, 0% coverage
- `OAuthCallbackPage.tsx` — OAuth flow, 0% coverage
- `PublicViewerPage.tsx` — public embed, 0% coverage
- `SettingsPage.tsx` — user settings, 0% coverage

**Admin pages (all 0%):** AdminAuditPage, AdminConfigOpsPage, AdminJobsPage, AdminOverviewPage, AdminSettingsPage, AdminSharedMapsPage, AdminUsersPage

### Hooks Without Tests (22 of 27)

Tested: use-auth, use-collections, use-debounce, use-document-title, use-tile-token

| Hook | Lines | Priority | Rationale |
|------|-------|----------|-----------|
| `use-search.ts` | 30 | **P1** | Core search functionality |
| `use-dataset.ts` | 177 | **P1** | Dataset CRUD operations |
| `use-records.ts` | 85 | **P1** | Record data access |
| `use-permissions.ts` | 19 | **P1** | Access control logic |
| `use-settings.ts` | 87 | **P2** | App settings management |
| `use-ingest.ts` | 85 | **P2** | Data ingestion workflow |
| `use-vrt.ts` | 66 | **P2** | VRT management |
| `use-maps.ts` | 206 | **P2** | Map builder hooks |
| `use-features.ts` | 93 | **P2** | Feature CRUD |
| `use-admin.ts` | 278 | **P2** | Admin panel operations |
| `use-embed-tokens.ts` | 43 | **P3** | Embed token management |
| `use-api-keys.ts` | 26 | **P3** | API key management |
| `use-config-ops.ts` | 68 | **P3** | Config operations |
| `use-ai-metadata.ts` | 24 | **P3** | AI metadata features |
| `use-ai-availability.ts` | 8 | **P3** | AI availability check |
| `use-saved-searches.ts` | 31 | **P3** | Saved searches |
| `use-quicklook.ts` | 54 | **P3** | Quicklook thumbnails |
| `use-mobile.ts` | 11 | **P4** | Mobile detection |
| `use-terra-draw.ts` | 388 | **P4** | Drawing integration (complex) |
| `use-url-search-sync.ts` | 61 | **P4** | URL sync |
| `use-abort-signal.ts` | 20 | **P4** | Abort controller utility |
| `use-dataset-edit-capabilities.ts` | small | **P4** | Edit capability check |

### API Modules Without Tests (16 of 17)

Only `client.ts` has tests (92.59% statement coverage).

| Module | Lines | Priority |
|--------|-------|----------|
| `auth.ts` | 104 | **P1** — login/register/token |
| `datasets.ts` | 332 | **P1** — largest API module |
| `search.ts` | 35 | **P1** — core search |
| `records.ts` | 46 | **P1** — record access |
| `collections.ts` | 76 | **P2** |
| `ingest.ts` | 166 | **P2** |
| `features.ts` | 47 | **P2** |
| `vrt.ts` | 51 | **P2** |
| `maps.ts` | 361 | **P2** |
| `settings.ts` | 162 | **P3** |
| `tiles.ts` | 45 | **P3** |
| `embed-tokens.ts` | 34 | **P3** |
| `admin.ts` | 183 | **P3** |
| `saved-searches.ts` | 26 | **P4** |
| `ai-metadata.ts` | 41 | **P4** |
| `config-ops.ts` | 65 | **P4** |

---

## 5. Backend Test Gaps

### Completely Untested Modules

| Module | Lines | Risk | Notes |
|--------|-------|------|-------|
| `app/public_urls.py` | 224 | **Medium** | URL resolution for STAC/OGC responses, share links, embeds. Complex header parsing logic. Pure functions — easy to unit test. |
| `app/worker_health.py` | 60 | **Low** | Procrastinate worker health endpoints (`/health/live`, `/health/ready`, `/metrics`). Lightweight Starlette app. |
| `app/marketplace.py` | 30 | **Low** | AWS Marketplace metering. Single boto3 call. Moto could mock. |
| `app/logging_config.py` | 69 | **Low** | structlog + stdlib bridge setup. Config-level, hard to test. |
| `app/database.py` | 34 | **Low** | SQLAlchemy engine creation. Thin wrapper. |

### Partially Tested Modules (thin coverage)

| Module | Gap |
|--------|-----|
| `app/raster/quicklook.py` | No direct unit tests — only indirect via integration |
| `app/vector/quicklook.py` | No direct unit tests |
| `app/ogc/filtering.py` | CQL2 filter parsing tested via endpoint tests, no unit test for edge cases |
| `app/tiles/pool.py` | Titiler connection pool — no dedicated tests |

### Anti-Patterns Found

- **Minimal `@pytest.mark.parametrize`** — only 3 tests use it across 1,326 test functions. Auth RBAC, visibility, and pagination tests manually repeat similar assertions.
- **No transaction rollback fixture** — tests rely on manual `_cleanup_table()`. Could add SAVEPOINT-based isolation.

---

## 6. E2E Test Deep Dive — Grade: C+

### Infrastructure

- **Config**: `playwright.config.ts` — 3 projects (setup, chromium, api), sequential execution (workers: 1), 60s test timeout, 2 retries in CI
- **Auth**: `auth.setup.ts` — single admin login, persists to `playwright/.auth/user.json` (localStorage JWT). **Only admin role tested.**
- **CI**: Docker Compose full stack → Playwright Chromium. 15-min timeout. Depends on all 5 other CI jobs.
- **Test data**: Relies on seeded DB (Alembic migrations). No explicit setup/cleanup between tests. Depends on datasets like "Wetlands", "World Countries" existing.
- **Fixtures**: Single file — `e2e/fixtures/sample.geojson` (180 bytes, 1 point feature)
- **Helpers**: No shared library. Each spec has inline helpers (no Page Object Model).

### Spec-by-Spec Audit

| Spec | Lines | Tests | Depth | Flakiness Risk | Key Finding |
|------|-------|-------|-------|---------------|-------------|
| `accessibility.spec.ts` | 96 | 5 | Good | Low | Axe WCAG 2AA on 5 pages, excludes WebGL canvas properly |
| `admin.spec.ts` | 213 | 10 | Shallow | Moderate | All admin pages load, but **no actual admin actions** (no saves, no user creation) |
| `auth.spec.ts` | 47 | 1 | Shallow | Moderate | Single happy path: login→dashboard→logout. **No error cases** (bad creds, locked account) |
| `collections.spec.ts` | 212 | 7 | Good | Moderate | Full CRUD cycle + dataset association. Missing permission-based visibility. |
| `dataset-detail.spec.ts` | 257 | 3 | Deep | Moderate-High | Map rendering, editing lifecycle, context guard. Best-tested spec. Uses data-testid well. |
| `export-runtime.spec.ts` | 712 | 8 | Deep | High | API-only tests. Validates binary formats (GPKG, SHP, CSV), CRS reprojection, audit trail. Complex dataset discovery logic. |
| `permissions.spec.ts` | 112 | 4 | Moderate | Low | Permission matrix, admin lockout, API endpoint, navbar. **Only tests admin role.** |
| `record-detail-ux-audit.spec.ts` | 393 | 2 | Deep | Moderate-High | Desktop + mobile viewports. Axe scan, keyboard focus, heading hierarchy. Depends on external JSON manifest. |
| `search.spec.ts` | 30 | 1 | Minimal | High | Only tests keyboard typeahead for "Wetlands". **No full-text search, filters, empty results.** |
| `upload.spec.ts` | 35 | 1 | Minimal | **Very High** | 30-second timeouts(!), regex button match, **no verification dataset was created**. |

### Selector Quality

| Category | Usage | Risk |
|----------|-------|------|
| `getByRole()` | Excellent — most specs | Low |
| `getByTestId()` | dataset-detail, record-audit | Low |
| `getByLabel()` | Auth forms | Low |
| `getByText()` | Everywhere — fragile to copy changes | Medium |
| `locator('#id')` | Auth (#password), collections (#description) | Medium |
| `locator('[class*=...]')` | admin.spec.ts | **High** — breaks on CSS changes |
| Regex button match | upload.spec.ts (`/Import|Commit/i`) | **High** |

### Wait Strategy Issues

- **Hardcoded 30s timeouts** in upload.spec.ts — indicates fundamental slowness, not a testing problem
- **15s typeahead timeouts** in search.spec.ts, dataset-detail.spec.ts — search is slow
- **No explicit XHR waits** in admin.spec.ts — race conditions likely
- **4-12s `page.waitForTimeout()`** in record-detail audit — bad practice, should wait for conditions

### 10 Major Coverage Gaps

| Gap | Severity | What's Missing |
|-----|----------|---------------|
| **1. Error paths** | Critical | Zero tests for bad credentials, 403/401 responses, invalid form input, 404 pages, network failures |
| **2. Map builder** | Critical | Entire feature untested — create, layers, styles, sharing, embed tokens |
| **3. Non-admin roles** | Critical | Only admin tested. No viewer/editor role enforcement validation. |
| **4. Search & filtering** | Major | Only keyboard typeahead. No full-text search, facets, date filters, empty results, special chars. |
| **5. Upload reliability** | Major | Single happy path with 30s waits. No format variety, error cases, or ingestion verification. |
| **6. VRT creation** | Major | Completely untested — multi-step form with source selection. |
| **7. Settings (user & admin)** | Major | Admin pages load but never save. User settings page untested. |
| **8. Dark mode / themes** | Moderate | Zero theme testing. |
| **9. Mobile interactions** | Moderate | Record audit checks layout, but no touch interactions, mobile nav, or responsive forms. |
| **10. Concurrent operations** | Moderate | No multi-user scenarios, simultaneous uploads, or edit conflicts. |

### What's Actually Good

- `export-runtime.spec.ts` is **excellent** — validates binary formats, semantic CRS reprojection, audit trail. Best spec in the suite.
- `dataset-detail.spec.ts` has **deep UX coverage** — editing lifecycle, pending edits bar, context switching, permission-gated fields.
- `collections.spec.ts` covers **full CRUD cycle** including dataset association.
- `accessibility.spec.ts` uses **Axe Core properly** with maplibre canvas exclusion.
- `record-detail-ux-audit.spec.ts` validates **desktop + mobile** viewports with heading hierarchy and keyboard focus.

---

## 7. Code Quality Gates Assessment

### Currently Enforced

| Tool | Scope | Purpose | CI Job |
|------|-------|---------|--------|
| ESLint | Frontend | typescript-eslint, react-hooks, jsx-a11y | frontend-lint |
| TypeScript `--noEmit` | Frontend | Strict type checking | frontend-lint |
| Ruff check | Backend | Python linting | backend-lint |
| Ruff format | Backend | Format enforcement | backend-lint |
| Bandit | Backend | Static security analysis (high severity) | security-scan |
| pip-audit | Backend | Dependency vulnerability scanning | security-scan |
| i18n parity | Frontend | Locale key completeness | frontend-lint |

### Missing Gates

| Gate | Effort | Value | Notes |
|------|--------|-------|-------|
| Frontend coverage threshold | **5 min** | **High** | Add `thresholds` to vitest config — set at 20% (current floor) and ratchet up |
| Backend coverage threshold | **5 min** | **High** | Add `--cov-fail-under=70` to pytest CI step |
| Remove `--passWithNoTests` | **2 min** | **Medium** | Catches accidentally deleted test files |
| `eslint-plugin-testing-library` | **15 min** | **Medium** | Catches common testing-library anti-patterns |
| `knip` dead code detection | **30 min** | **Medium** | Find unused exports, files, dependencies |
| Bundle size budget | **1 hr** | **Low** | Add size-limit or bundlesize to CI |
| Playwright visual regression | **Large** | **Medium** | Screenshot comparison for map components |

---

## 8. Easy-Win Enhancements (Actionable Now)

### Tier 1: Under 15 Minutes Each

| # | Enhancement | Effort | Impact | Details |
|---|------------|--------|--------|---------|
| **E1** | Fix 2 failing tests | 10 min | **High** | PageShell: change `py-6`→`py-4`, `space-y-6`→`space-y-4`. i18n: remove `nav.importData` from expected keys. Restores green CI. |
| **E2** | Add frontend coverage thresholds | 5 min | **High** | Add `thresholds: { statements: 20, branches: 20, functions: 15, lines: 20 }` to vitest config. Set at current floor — prevents regression, ratchet up over time. |
| **E3** | Add backend coverage threshold | 5 min | **High** | Change pytest CI command to `pytest ... --cov-fail-under=68`. Set 2% below current 70.86% as safety net. |
| **E4** | Remove `--passWithNoTests` | 2 min | **Medium** | Remove flag from `test` and `test:coverage` scripts in package.json. Catches silently deleted tests. |

### Tier 2: Under 1 Hour Each

| # | Enhancement | Effort | Impact | Details |
|---|------------|--------|--------|---------|
| **E5** | Extract shared test fixtures | 45 min | **Medium** | Create `frontend/src/test/fixtures/index.ts` with `mockUser()`, `mockDataset()`, `mockCogSource()`, etc. Currently duplicated across 15+ test files. |
| **E6** | Add `eslint-plugin-testing-library` | 15 min | **Medium** | `npm i -D eslint-plugin-testing-library` + add to eslint config. Catches anti-patterns: `container.querySelector` instead of `getByRole`, missing `await` on user events, wrong query types. |
| **E7** | Unit test `app/public_urls.py` | 45 min | **Medium** | 224 lines of pure functions (URL resolution, header parsing). No DB needed. ~30 test cases covering header combinations, fallbacks, normalization. Highest-value untested backend module. |
| **E8** | Parametrize backend RBAC tests | 30 min | **Medium** | Convert ~80 manually repeated role-based assertions (admin can X, viewer cannot X) into `@pytest.mark.parametrize` across auth, datasets, maps tests. Reduces code by ~40%. |
| **E9** | Add `knip` dead code detection | 30 min | **Medium** | `npm i -D knip` + add `knip` script. Finds unused exports, files, dependencies. One-time cleanup + CI gate to prevent accumulation. |

### Tier 3: Under 1 Day Each

| # | Enhancement | Effort | Impact | Details |
|---|------------|--------|--------|---------|
| **E10** | Set up MSW for API mocking | 2-3 hrs | **High** | Install `msw`, create `handlers.ts` with endpoint mocks, wire into `setup.ts`. Eliminates 236 manual `vi.mock()` calls. Every new test benefits immediately. |
| **E11** | Test P1 hooks (4 hooks) | 3-4 hrs | **High** | `use-search`, `use-dataset`, `use-records`, `use-permissions`. These back the core UI. Use `renderHook()` from existing test-utils. |
| **E12** | Test P1 API modules (4 modules) | 3-4 hrs | **High** | `auth.ts`, `datasets.ts`, `search.ts`, `records.ts`. Mock fetch at the network level (MSW or globalThis.fetch). These are the data layer for every feature. |
| **E13** | Add E2E Page Object Model | 2-3 hrs | **Medium** | Create `e2e/pages/` with LoginPage, SearchPage, DatasetPage, AdminPage classes. Reduces selector duplication across 10 specs. Makes new specs faster to write. |
| **E14** | Backend transaction rollback fixture | 2-3 hrs | **Medium** | Add SAVEPOINT-based isolation to `conftest.py`. Auto-rollback each test instead of manual `_cleanup_table()`. Eliminates order-dependent failures. |
| **E15** | Fix upload.spec.ts flakiness | 2-3 hrs | **High** | Replace 30s timeouts with `page.waitForResponse()`. Add dataset creation verification after commit. Add more file format fixtures (Shapefile, GPKG). |
| **E16** | Add auth error path E2E tests | 2-3 hrs | **High** | Bad credentials, locked account, session expiry, redirect when already authed. Currently zero negative auth testing. |
| **E17** | Add non-admin role E2E tests | 3-4 hrs | **Critical** | Create viewer/editor auth storage states. Verify viewers can't edit, editors can't admin. Currently only admin role tested in entire E2E suite. |
| **E18** | Add search & filter E2E tests | 3-4 hrs | **High** | Full-text search, facet filters, empty results, special characters. Current search.spec.ts is 30 lines covering only keyboard typeahead. |

---

## 9. Recommended Implementation Order

### Phase 1: Immediate Wins (1-2 hours)

Fix E1-E4 in a single commit. This restores green CI, adds regression gates, and costs almost nothing.

**Expected outcome:** CI now enforces coverage floors. All tests pass.

### Phase 2: Test Infrastructure (1-2 days)

1. E5 — Extract shared fixtures (reduces duplication)
2. E10 — Set up MSW (biggest single improvement to test DX)
3. E6 — eslint-plugin-testing-library (catches anti-patterns going forward)

**Expected outcome:** Writing new tests becomes 50% faster. Existing tests can be migrated to MSW incrementally.

### Phase 3: Critical Path Coverage (3-5 days)

1. E11 — Test P1 hooks
2. E12 — Test P1 API modules
3. Test SearchPage (most-used page, 0% coverage)
4. Test CollectionsPage

**Expected outcome:** Frontend coverage jumps from 22% to ~35-40%.

### Phase 4: Backend Hardening (2-3 days)

1. E7 — Unit test `public_urls.py`
2. E8 — Parametrize RBAC tests
3. E14 — Transaction rollback fixture
4. CQL2 filter edge case tests

**Expected outcome:** Backend coverage stabilizes at 75%+, test isolation improves.

### Phase 5: E2E Hardening (3-5 days)

**Priority order — fix foundations first, then expand coverage:**

1. E17 — **Add non-admin role tests** (critical — only admin tested today)
2. E15 — Fix upload.spec.ts flakiness (replace 30s waits with XHR monitoring)
3. E16 — Add auth error path tests (bad creds, locked account, session expiry)
4. E13 — Page Object Model (makes all subsequent E2E work faster)
5. E18 — Expand search & filter tests (current spec is 30 lines)

**Expected outcome:** E2E suite tests all 3 user roles, has error path coverage, and is less flaky.

### Phase 6: E2E Expansion (3-5 days)

1. Map builder e2e flow (create, layers, styles, share)
2. VRT creation e2e flow (multi-step form, source selection)
3. Settings page e2e (user + admin settings with save verification)
4. Dark mode / theme switching
5. Mobile touch interaction tests

**Expected outcome:** All critical user workflows have E2E coverage. Major gap list drops from 10 to 2-3.

### Phase 7: Long Tail (2-3 weeks)

- Remaining hooks (22 untested)
- Remaining components (7 directories with zero tests)
- Admin pages
- Visual regression for map components
- Bundle size budget
- Concurrent operation testing

---

## 10. Missing Test Scenarios (Not Covered Anywhere)

These test scenarios don't exist in either unit or E2E tests:

1. **Error boundary recovery** — no tests for React error boundaries catching component crashes
2. **Network retry logic** — 401 refresh tested in `client.ts`, but not in hooks that use the client
3. **Concurrent TanStack Query** — no tests for query deduplication, stale-while-revalidate, or race conditions
4. **Map interaction sequences** — unit tests mock the map entirely; no real maplibre-gl behavior tested
5. **Export/download flows** — only E2E coverage, no unit tests for export logic
6. **Theme switching persistence** — ThemeProvider has no unit tests for dark/light mode toggle + localStorage
7. **Zustand persistence** — store tests don't verify localStorage actually persists across page loads
8. **Backend quicklook generation** — both raster and vector quicklook modules untested
9. **Backend CQL2 edge cases** — malformed expressions, type mismatches, invalid operators not tested

---

## Summary

**Overall Grade: B-**

| Area | Grade | Key Finding |
|------|-------|-------------|
| Backend tests | **A-** | 1,326 tests, 70.86% coverage, excellent fixtures. Gaps: 5 untested modules, no parametrize, no auto-rollback. |
| Frontend unit tests | **C+** | 289 passing tests, 22% coverage. Good patterns but massive gaps: 16/17 API modules, 22/27 hooks, 10/12 pages untested. |
| E2E tests | **C+** | 10 specs but mostly shallow smoke tests. Only admin role tested. Zero error paths. upload.spec has 30s timeouts. Missing map builder, VRT, search depth, role enforcement. |
| CI quality gates | **B+** | Comprehensive pipeline (6 jobs). Missing coverage thresholds and dead code detection. |
| Test infrastructure | **B** | Good setup files and utils. Missing MSW, shared fixtures, and Page Object Model. |

**Biggest bang-for-buck improvements:**
1. Fix 2 failing tests + add coverage thresholds (15 min, prevents regression)
2. Add non-admin role E2E tests (3-4 hrs, closes biggest E2E blind spot)
3. Set up MSW (2-3 hrs, transforms unit test DX)
4. Fix upload.spec.ts flakiness + add error path E2E tests (4-5 hrs, makes suite trustworthy)
5. Test P1 hooks + API modules (1 day, jumps frontend coverage from 22% → 35%)
