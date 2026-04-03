# Test Audit — 2026-04-03

## Scorecard

| Dimension | Grade | Prior (04-01) | Notes |
|-----------|-------|---------------|-------|
| **Coverage** | C+ | B- | Backend 21/22 routers have test files but only ~42% of endpoints exercised. Frontend 32.6% line coverage (stores 98%, lib 80%, components 13%, pages 19%, API 11%). 155/194 components untested. |
| **Test Quality** | B | B | Good naming (zero weak names), 91 status-only assertions, only 3/107 files use parametrize. Mock-heavy but mostly at appropriate boundaries. |
| **Flaky Resistance** | C+ | B | 2 high-severity global-state issues (test_config.py env.clear, test_persistent_config.py logger mutation), 6 medium ordering assumptions, 2 timing races. |
| **Missing Tests** | C | B- | 3 P0 data-loss risks newly identified (settings embedding-dim delete, admin user delete cascade, force backfill). ~40 untested endpoints. Spatial edge cases absent. |
| **Infrastructure** | B- | B | Dead factories.py (unused by any test), 23 duplicate _create_dataset helpers, no per-test DB rollback, CI/local pytest flag mismatch on -m 'not perf'. |
| **Frontend Patterns** | B | B+ | 91 test files, strong a11y query ratio (2:1), good store coverage (100%). Loading state coverage poor (78 test lines vs 562 production usages). 22/40 hooks untested. |

**Overall Test Health: C+** (was B- on 04-01)

> The prior audit was conducted post-remediation in the same session, so its grades reflected fixes applied during the audit. This audit reflects the current codebase state with a deeper endpoint-level analysis.

---

## Executive Summary

GeoLens has 107 backend test files and 91 frontend test files — a solid structural foundation. However, endpoint-level analysis reveals only ~42% of backend API routes are exercised, with 3 newly-identified P0 data-loss risks: the settings endpoint that silently deletes all embeddings on dimension change, the admin user deletion endpoint with unverified cascades, and the force-backfill endpoint that mass-deletes embedding data. Frontend line coverage is 32.6%, with `src/stores` (98%) and `src/lib` (80%) well-tested but `src/components` (13%), `src/pages` (19%), and `src/api` (11%) severely undercovered. Two high-severity flaky test patterns — module-level `os.environ.clear()` in test_config.py and global logger mutation in test_persistent_config.py — risk corrupting the entire test process.

---

## 1. Coverage Analysis

### 1a. Backend Coverage

**Router-level coverage (22 routers):**

| Module | Test File(s) | Status |
|--------|-------------|--------|
| admin | test_admin_stats.py, test_settings_admin.py | Covered (partial — many admin endpoints untested) |
| ai | test_ai_chat.py, test_ai_metadata.py, test_ai_send_sample_values.py | Covered (generate-map untested) |
| audit | test_audit.py | Covered |
| auth | test_auth.py, test_auth_refresh_logout.py, test_api_key_auth.py | Covered (user self-service API keys untested) |
| auth/oauth | test_oauth.py, test_arcgis_auth.py, test_saml.py | Partial |
| collections | test_collections.py | Covered |
| config_ops | test_config_ops.py, test_config_ops_unit.py | Covered |
| datasets | test_datasets.py, test_dataset_rows.py, test_related_datasets.py | Covered |
| embed_tokens | test_embed_tokens.py | Covered |
| export | test_export.py | Covered |
| features | test_features_crud.py | Covered |
| ingest | test_ingest.py, test_raster_ingest.py | Covered |
| jobs | test_jobs_router.py | Covered |
| layers | test_layers.py | Covered |
| maps | test_maps.py | Covered (thumbnails, layer delete untested) |
| ogc | test_ogc_*.py (8 files) | Covered |
| records | test_records_related.py | Covered |
| search | test_search.py, test_search_facets.py, test_search_datetime.py | Covered (saved search GET/DELETE untested) |
| services | test_services_endpoints.py | Covered |
| settings | test_settings_router.py, test_branding_settings.py | Covered (OAuth CRUD, reset, detect-dims untested) |
| stac | test_stac_*.py (6 files) | Covered (individual collection/item endpoints untested) |
| tiles | test_tiles.py, test_raster_tiles.py, test_tile_cache.py, test_seed_tiles.py | Covered |

**Endpoint-level**: ~55 unique path patterns tested out of ~130 defined endpoints (~42%).

### 1b. Frontend Coverage

| Directory | Stmts % | Branch % | Funcs % | Lines % |
|-----------|---------|----------|---------|---------|
| **All files** | **31.83** | **30.26** | **28.10** | **32.57** |
| src/api | 10.67 | 10.68 | 5.00 | 11.29 |
| src/components | 12.50 | 20.00 | 15.38 | 13.15 |
| src/hooks | 32.63 | 25.91 | 30.78 | 32.38 |
| src/i18n | 60.81 | 35.44 | 70.27 | 60.95 |
| src/lib | 77.46 | 67.39 | 84.69 | 80.10 |
| src/pages | 19.00 | 22.72 | 12.88 | 19.09 |
| src/pages/admin | 0.00 | 0.00 | 0.00 | 0.00 |
| src/stores | 79.51 | 77.27 | 96.55 | 98.30 |

**848 frontend tests, all passing.**

### 1c. Zero-Coverage Modules

**Backend — untested endpoint clusters:**
- Admin AI/embedding management (4 endpoints)
- Settings OAuth provider CRUD (3 endpoints)
- Settings reset, detect-dims, tile-config (3 endpoints)
- User self-service API keys (3 endpoints)
- STAC individual collection/item (4 endpoints)
- Maps thumbnails, layer delete (3 endpoints)

**Frontend — high-value untested areas:**
- `import/` — 12/12 components (entire upload workflow)
- `admin/settings/` — 11/11 components (every settings tab)
- `builder/` — 16/17 components (BuilderMap, LayerPanel, etc.)
- `search/` — 9/9 additional components (SearchTypeahead, SpatialFilterPanel)
- `collections/` — 7/8 components
- `viewer/` — 2/2 components (ViewerMap, LayerLegend)

---

## 2. Test Quality & Patterns

| Pattern | Count | Severity | Details |
|---------|-------|----------|---------|
| **Status-only assertions** | 91 of 504 (18%) | Medium | Tests check status code without body validation. Worst: test_export.py (10), test_embed_tokens.py (15), test_persistent_config.py (8) |
| **Missing parametrize** | 3/107 files use it | Medium | 67 files with >8 tests and zero parametrize. Best candidates: test_raster_validation.py (38 tests), test_sql_safety.py (19), test_geometry_detection.py (22) |
| **Implementation-coupled mocks (BE)** | ~65 occurrences, 14 files | Low | Most in VRT tests (subprocess arg inspection — reasonable). test_embedding_pipeline.py ORM mock assertions most fragile |
| **Implementation-coupled mocks (FE)** | ~164 occurrences, ~30 files | Low | Concentrated in hook/adapter tests. use-builder-save.test.ts has 22 mock calls |
| **Hardcoded test data** | 56 geometry + 46 auth literals | Low | Zero shared geometry fixtures in conftest. test_reupload.py repeats empty FeatureCollection 7x |
| **Weak test names** | 0 | None | Excellent naming discipline across entire suite |
| **Broad exception handling** | 5 in 4 files | Low | All in setup/teardown contexts, not assertions |

---

## 3. Flaky & Slow Test Detection

### High Severity

| Test | Risk Type | Details | Fix |
|------|-----------|---------|-----|
| `test_config.py:26-38` | Global state | Module-level `os.environ.clear()` during import can wipe env vars for entire test process if collection order causes early load | Move env manipulation into fixture with `monkeypatch` |
| `test_persistent_config.py:248-253` | Global state | Mutates `logging.getLogger().level` (root logger) without guaranteed teardown. Test failure leaves dirty global state | Use `monkeypatch` or fixture with guaranteed restore |

### Medium Severity

| Test | Risk Type | Details | Fix |
|------|-----------|---------|-----|
| `test_embed_tokens.py:203,236` | Timing | `datetime.now()` race between server computation and test assertion | Freeze time with `time_machine` |
| `test_raster_ingest.py:63` | Non-determinism | `np.random.randint()` without seed for raster pixel data | Add `np.random.seed(42)` |
| `test_audit.py:133` | Ordering | `entries[0]["action"]` without sort guarantee | Sort before indexing |
| `test_ogc_record_properties.py:264` | Ordering | `contacts[0]["name"]` without sort | Sort or use set-based check |
| `test_ogc_records_conformance.py:171,202` | Ordering | `scheme_themes[0]` and `contacts[0]` without sort | Sort or use membership check |
| `test_ogc_record_enrichment.py:436` | Ordering | `dists[0]["format"]` without sort | Sort by stable key |
| `test_worker.py:192` | Ordering | Assumes stale job iteration order | Use set-based assertion |
| `VrtCreatorForm.test.tsx:104` | Sleep-based | `setTimeout(r, 200)` for debounce timing | Use `vi.useFakeTimers()` |

### Low Severity (Noted, Not Actionable)

- `test_tile_signing.py` — time.time() used as input, not race-prone assertion
- `test_health.py:68` — asyncio.sleep(60) intentionally cancelled by patched timeout
- `auth-store.test.ts:28` — Date.now() >= comparison, safe unless clock jumps
- Module-level immutable test data (test_features_crud.py, test_dataset_rows.py) — safe if never mutated

---

## 4. Missing Test Identification

### 4a. P0 — Auth / Data-Loss / Security

| Endpoint | File | Risk | Notes |
|----------|------|------|-------|
| `PUT /settings/` — embedding dim change | settings/router.py:147 | Silently deletes ALL embeddings | No test for destructive side effect |
| `DELETE /admin/users/{id}` | admin/router.py:252 | Cascade to API keys, maps, datasets | No cascade verification test |
| `POST /admin/backfill-embeddings/?force=true` | admin/router.py:536 | Mass-deletes all embeddings | No test |
| `GET/POST/DELETE /auth/api-keys/` (user self-service) | auth/router.py:241-304 | Auth boundary | 3 endpoints, 0 tests |
| `POST /admin/users/{id}/approve` | admin/router.py:197 | Access control | No test |
| `POST /admin/users/{id}/reject` | admin/router.py:225 | Access control | No test |
| OAuth callback CSRF | auth/oauth/router.py:84 | Account takeover | No malicious state param test |
| Features GET — private dataset auth | features/router.py:48 | Data leakage | No auth denial test for private datasets |
| `POST /ingest/upload/presigned/{job_id}/complete` | ingest/router.py:170 | Data integrity | No test |

### 4b. P1 — Core Features

| Endpoint | File | Notes |
|----------|------|-------|
| `POST /ai/generate-map/` | ai/router.py:160 | Core feature, no functional test |
| `POST /ai/generate-map/stream/` | ai/router.py:210 | No test |
| `GET /maps/{id}/visibility-check/` | maps/router.py:265 | No test |
| `PUT/GET /maps/{id}/thumbnail/` | maps/router.py:594,657 | No test |
| `DELETE /maps/{id}/layers/{layer_id}` | maps/router.py:773 | No test |
| `GET /datasets/{id}/quicklook` | datasets/router.py:284 | No test |
| `POST /datasets/create-empty/` | datasets/router.py:160 | No test |
| STAC individual collection/item (4 endpoints) | stac/router.py:410-686 | No tests |
| Settings OAuth CRUD (3 endpoints) | settings/router.py:266-323 | No tests |
| Settings reset, detect-dims, tile-config | settings/router.py:190-413 | No tests |
| Admin AI/embedding management (4 endpoints) | admin/router.py:464-583 | No tests |
| `DELETE /admin/share-tokens/{id}` | admin/router.py:649 | No test |
| `DELETE /search/saved/{id}` | search/router.py:614 | No test |
| `GET /search/saved/{id}` | search/router.py:598 | No test |

### 4c. Spatial Operation Coverage

| PostGIS Function | Production Usage | Tested | Gap |
|------------------|-----------------|--------|-----|
| ST_Intersects | search, features, tiles | Implicit via search | No direct spatial assertion |
| ST_DWithin | features/service.py | No | Distance queries untested |
| ST_Buffer | ai/sql_generator.py | No | Buffer operations untested |
| ST_Contains | ai/sql_generator.py, utils/geo.py | No | Containment queries untested |
| ST_Transform | ingest pipeline | Implicit | No SRID transformation validation |
| ST_MakeValid | ingest pipeline, quicklook | No | Invalid geometry handling untested |
| ST_SetSRID | ingest pipeline | No | SRID assignment untested |

**Missing edge cases:** antimeridian crossing (±180), empty geometries, self-intersecting polygons, GEOMETRYCOLLECTION, null geometries in tile queries.

### 4d. Vector Operation Coverage

Embedding/similarity operations tested through test_embedding_service.py, test_embedding_pipeline.py, test_hybrid_search.py. **Gap:** dimension mismatch after model change (what happens when embedding dims don't match column).

### 4e. Auth & Permission Coverage

- **Tested**: Login, registration, RBAC roles, API key query param, JWT validation, refresh, logout
- **Untested**: User self-service API key CRUD, deactivated-user token invalidation, self-role-escalation prevention, OAuth callback CSRF, private dataset feature listing auth

### 4f. Error Path Coverage

- **HTTPException raises in production**: ~331
- **Error assertions in tests**: ~293
- **Key gaps**: 502 (service probe), 503 (LLM unavailable), 504 (probe timeout), malformed config import, STAC spatial intersection errors

---

## 5. Test Infrastructure Health

| Aspect | Status | Details | Recommendation |
|--------|--------|---------|----------------|
| **conftest.py organization** | Good | Single root conftest with 7 fixtures. Clear naming. Not overloaded. | No change needed |
| **Fixture scoping** | Good | Session: DB lifecycle, anyio backend. Function: client, auth headers, db session. | Appropriate scoping |
| **Database isolation** | Warning | No per-test transaction rollback. Tests commit to shared DB. Manual cleanup in some files (test_embed_tokens: 16 cleanup calls). Cleanup doesn't run on test failure. | Consider savepoint-based rollback or move cleanup to fixtures with `yield` |
| **Factory module** | Critical | `tests/factories.py` exists with `create_dataset()`, `create_map_via_api()`, `create_collection_via_api()` but **zero test files import it**. Dead code. | Either delete or migrate the 23 test files with inline `_create_dataset()` helpers to use it |
| **CI/local alignment** | Warning | Local pyproject.toml: `-m 'not perf'`. CI pytest command: no `-m` flag. Perf tests run in CI but not locally. | Add `-m 'not perf'` to CI or remove from local |
| **Coverage thresholds** | Good | Backend: `fail_under = 55`. Frontend: statements 30, branches 25, functions 25, lines 30. Both enforced in CI. | Ratchet up as coverage improves |
| **Frontend test setup** | Good | Comprehensive maplibre-gl/react-maplibre mocks, localStorage polyfill (Node 25), i18n init, Zustand cleanup via afterEach | Well-implemented |
| **Frontend test-utils** | Good | Custom render/renderHook with QueryClient (retry:false), MemoryRouter, TooltipProvider | Standard pattern |

---

## 6. Frontend Test Patterns

| Pattern | Count | Health | Recommendation |
|---------|-------|--------|----------------|
| **Behavior-focused queries** (render, screen, getByRole, getByText, userEvent) | 1,328 lines | Good | Primary Testing Library API used correctly |
| **A11y queries** (getByRole, getByLabelText, getByAltText) | 196 | Good | 2:1 ratio vs non-a11y queries |
| **Implementation queries** (getByTestId, querySelector) | 109 (99 testId + 10 querySelector) | Acceptable | getByTestId concentrated in map tests where semantic queries impractical |
| **Hook test coverage** | 18/40 hooks tested (45%) | Warning | 22 production hooks lack tests. Priority: use-builder-layout, use-feature-editing, use-viewer-layers |
| **Store test coverage** | 4/4 (100%) | Good | All Zustand stores tested |
| **Error state assertions** | 167 test lines vs 562 production | Warning | ~30% coverage ratio |
| **Loading state assertions** | 78 test lines vs 562 production | Poor | Significantly undertested |
| **Empty state assertions** | 36 test lines | Poor | Minimal coverage |
| **MSW usage** | 0 | N/A | All API mocking via vi.mock — consistent but no contract validation |
| **Map component coverage** | 1/3 tested | Warning | BasemapToggle, HeatmapStyleControls untested |

---

## 7. Test Debt Summary

| Metric | Count |
|--------|-------|
| Backend endpoints with zero test coverage | ~75/130 (58%) |
| Frontend components with zero test coverage | 155/194 (80%) |
| Frontend pages with zero test coverage (admin) | All admin pages (0%) |
| Frontend hooks with zero test coverage | 22/40 (55%) |
| Spatial operations tested vs untested | 1 implicit / 6 untested |
| Error paths: raises vs test assertions | 331 vs 293 (gaps in 502/503/504) |
| Flaky-risk tests | 2 high, 8 medium, 5 low |
| P0 untested endpoints (security/data-loss) | 9 |
| P1 untested endpoints (core features) | 21 |
| P2 untested endpoints (edge cases) | ~45 |
| Dead code | factories.py (unused by any test) |
| Estimated hours for P0 fixes | 20-28h |
| Estimated hours for P0+P1 fixes | 52-68h |

---

## 8. Prioritized Action Items

| # | Priority | Action | Dimension | Effort | Risk if Unfixed |
|---|----------|--------|-----------|--------|-----------------|
| 1 | **P0** | Fix `test_config.py` module-level `os.environ.clear()` — move to monkeypatch fixture | Flaky | 1h | Entire test process env corruption |
| 2 | **P0** | Fix `test_persistent_config.py` global logger mutation — use fixture with guaranteed teardown | Flaky | 1h | Test pollution across suite |
| 3 | **P0** | Test `PUT /settings/` embedding dim change (silently deletes all embeddings) | Missing | 3h | Silent data loss in production |
| 4 | **P0** | Test `DELETE /admin/users/{id}` cascade (API keys, maps, datasets) | Missing | 3h | Orphaned data, FK violations |
| 5 | **P0** | Test `POST /admin/backfill-embeddings/?force=true` mass delete | Missing | 2h | Unverified mass data deletion |
| 6 | **P0** | Test user self-service API key CRUD (3 endpoints) | Missing | 3h | Auth boundary untested |
| 7 | **P0** | Test admin approve/reject user endpoints | Missing | 2h | Access control gap |
| 8 | **P0** | Test OAuth callback CSRF (malicious state param) | Missing | 2h | Account takeover vector |
| 9 | **P0** | Test private dataset feature listing auth denial | Missing | 2h | Data leakage |
| 10 | **P1** | Delete or adopt `tests/factories.py` — consolidate 23 duplicate `_create_dataset` helpers | Infra | 4h | Maintenance burden, dead code |
| 11 | **P1** | Fix 6 medium-severity ordering assumptions (sort before index assertion) | Flaky | 2h | Intermittent CI failures |
| 12 | **P1** | Test `POST /ai/generate-map/` with mocked LLM | Missing | 3h | Core feature untested |
| 13 | **P1** | Test maps thumbnail PUT/GET and layer DELETE | Missing | 3h | Map builder functionality gap |
| 14 | **P1** | Test STAC individual collection/item (4 endpoints) | Missing | 4h | Public API compliance |
| 15 | **P1** | Test settings OAuth CRUD + reset + detect-dims (6 endpoints) | Missing | 4h | Admin configuration gap |
| 16 | **P1** | Align CI/local pytest flags (`-m 'not perf'`) | Infra | 0.5h | Perf tests run in CI but not locally |
| 17 | **P1** | Seed `np.random` in test_raster_ingest.py | Flaky | 0.5h | Non-deterministic test data |
| 18 | **P1** | Add frontend hook tests for 22 untested hooks (prioritize use-builder-layout, use-feature-editing, use-viewer-layers) | Frontend | 8h | Core data-fetching hooks at 0% |
| 19 | **P1** | Add loading/empty state tests to existing hook test files | Frontend | 3h | Poor state coverage (78 vs 562 production usages) |
| 20 | **P2** | Add body validation to 91 status-only assertions | Quality | 6h | Malformed responses pass undetected |
| 21 | **P2** | Introduce `@pytest.mark.parametrize` in test_raster_validation.py, test_sql_safety.py, test_geometry_detection.py | Quality | 4h | Repetitive tests, edge case gaps |
| 22 | **P2** | Add spatial edge case tests (antimeridian, empty geom, ST_DWithin, ST_MakeValid) | Missing | 4h | Spatial bugs at boundaries |
| 23 | **P2** | Move manual DB cleanup (test_embed_tokens.py 16 calls) to yield fixtures | Infra | 2h | Cleanup doesn't run on failure |
| 24 | **P2** | Add shared geometry fixtures to conftest.py | Quality | 1h | Test data duplication |
| 25 | **P2** | Replace VrtCreatorForm.test.tsx setTimeout with fake timers | Flaky | 0.5h | Brittle timing in CI |
| 26 | **P2** | Test embedding dimension mismatch after model change | Missing | 2h | Silent corruption |
| 27 | **P2** | Add frontend import/ workflow tests (12 untested components) | Frontend | 6h | Entire upload flow untested |
| 28 | **P2** | Add frontend admin/settings tests (11 untested components) | Frontend | 6h | All settings tabs at 0% |
| 29 | **P2** | Ratchet coverage thresholds upward (backend 55% → 60%, frontend 30% → 35%) | Infra | 0.5h | Silent coverage regression |

---

## 9. Comparison to Prior Audit (2026-04-01)

| Dimension | 04-01 Grade | 04-03 Grade | Change | Notes |
|-----------|-------------|-------------|--------|-------|
| Coverage | B- | C+ | ↓ | Prior audit post-remediation grades inflated. Deeper endpoint-level analysis reveals 58% of endpoints untested (prior reported 51%). Frontend actual coverage measured at 32.6%. |
| Test Quality | B | B | → | No change. Status-only assertions remain at ~91. Parametrize adoption unchanged. |
| Flaky Resistance | B | C+ | ↓ | Two high-severity issues newly identified (env.clear, logger mutation). 6 ordering assumptions found (prior identified 4). |
| Missing Tests | B- | C | ↓ | 3 new P0 data-loss risks identified (settings embedding delete, admin user delete, force backfill). Prior audit's P0 list was 16; this audit identifies 9 distinct P0 gaps at higher specificity. |
| Infrastructure | B | B- | ↓ | factories.py confirmed dead code (zero imports). Prior noted it as "needs work" but didn't verify adoption. |
| Frontend | B+ | B | ↓ | Actual coverage data (32.6% lines) vs prior's file-count estimate (36.9%). Loading/empty state testing quantified as poor. |

**Key delta**: The prior audit was conducted and remediated in the same session, inflating post-remediation grades. This audit uses deeper analysis (endpoint-level coverage, actual coverage percentages, dead-code verification) and finds the suite in a C+ state rather than B-.

**New findings not in prior audit:**
1. `PUT /settings/` silently deletes embeddings on dim change (P0)
2. `POST /admin/backfill-embeddings/?force=true` mass delete (P0)
3. `test_config.py` module-level `os.environ.clear()` (High flaky risk)
4. `test_persistent_config.py` global logger mutation (High flaky risk)
5. `factories.py` confirmed dead code (zero imports)
6. Frontend actual line coverage measured at 32.6% (848 passing tests)
7. 22/40 frontend hooks untested (prior estimated 26/39)
