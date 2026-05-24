# GeoLens

## What This Is

An on-premises, PostGIS-native GIS data catalog that lets GIS analysts, data engineers, and non-technical staff search, preview, and export geospatial datasets — both vector and raster — through a fast, search-first web UI. Built on a "database-first" architecture using FastAPI for catalog, tile serving (ST_AsMVT for vector, Titiler for raster), feature serving, metadata, search, RBAC, and job orchestration.

Shipped milestones through v1007, plus cross-repo marketing/docs milestones. Production-hardened with refresh token auth, non-root containers, Trivy CI scanning, Prometheus metrics, automated S3 backups, Redis circuit breaker, magic byte file validation, and route-based code splitting. Cloud-ready with provider-agnostic storage (S3), caching (Redis/Valkey), managed database support, and presigned uploads. Full-featured GIS catalog with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, raster dataset support (COG ingest, tile serving, export), VRT mosaics with lifecycle management, STAC 1.1 export for raster interop, publication lifecycle (draft/ready/internal/published), declarative `geolens.yaml` catalog manifests, and internationalization (i18n). Map builder is a complete cartographic authoring surface: clean `style_config`/`paint` separation, incremental layer save with stable layer IDs, first-class raster/line/zoom-expression controls, DEM hillshade with map-level terrain, native MapLibre bounded/server-side point clustering, MapLibre style JSON export/import round-trip, sprite-backed symbol/icon layers including Line → Arrow companion rendering, and durable map edit history with builder History panel. Accessible UI with 44px mobile touch targets, keyboard-focusable tables, WCAG AA badge contrast, semantic collection markup, responsive detail headers, and raster/VRT preview resilience with bounded retry. Deployable by other organizations via `docker compose up`, then automatable through `geolens init`, `geolens validate`, and `geolens apply`.

## Current State

Milestones are delivered through v1011 Map Builder Polish & Bug Sweep (shipped 2026-05-18), capping the v1008→v1011 Map Builder excellence series (sidebar redesign → polish → drag-from-catalog/multi-select → performance audit + bulk-delete → live Playwright MCP smoke → smoke carryover). v1008 retired the six-section `MapStackPanel` / `MapStackSection` / `LayerItem` model in favor of a unified drag-orderable stack (`UnifiedStackPanel` + `StackRow`), folder-grouped basemap (`BasemapGroupRow`) with sublayer expansion, DEM-as-raster-layer with image/hillshade/terrain render modes, a 380px `LayerEditorPanel` flyout with collapsible Filter/Labels/Source sections (drill-down `Sheet` overlay at <800px), a `⚙ Settings` affordance on the `SidebarRail`, a saved-map normalizer that promotes legacy six-section JSON to flat-stack + group-metadata shape without viewer regression, and a catalog-first empty state with curated suggestions; quick task `260514-ajo` closed the deferred smoke-test sweep (8 tests rewritten, 4 obsolete tests deleted, `SidebarRail` Add-data click bug fixed, dead `LayerPanel.tsx` / `LayerItem.tsx` removed). v1007 verified v1006's release state with scanner-clean `urllib3==2.7.0`, dismissed stale Dependabot #36/#37 with evidence so open GitHub alerts are zero, regenerated OpenAPI and SDK artifacts for the server-side cluster route, fixed Docker Compose frontend health, made collections smoke self-seeding, passed broad backend/frontend/security/browser gates, and confirmed a clean Playwright MCP browser console after temporary UAT/smoke cleanup. v1006 extended native Cluster from bounded GeoJSON point datasets to large point datasets with authenticated server-side cluster MVT tiles, shared builder/public/shared/embed source routing, cluster exploration popups and zoom activation, style JSON cluster strategy metadata, and clean Playwright MCP UAT on a 6,001-feature imported point-family dataset. v1.7 Marketplace & Distribution paused at Phase 40 (AWS AMI Build). Open-core architecture is **A-grade ship-ready** — Apache 2.0 licensed core, enterprise extensions register via `importlib.metadata` entry_points, auto-generated Python + TypeScript SDKs from `backend/openapi.json`, Apache-2.0 `geolens` CLI on PyPI (login/scan/publish/export-stac/init/validate/apply), SAML enterprise overlay with SP-initiated SSO + JIT provisioning + audited attribute→role mapping, documented + tested edition lifecycle (operator runbooks, admin SAML→local conversion endpoint, round-trip symmetry test), **fully extensible audit + billing + AI + governance seams** (`AuditSink`, `BillingExtension`, `AIProviderExtension`, `EmbeddingProviderExtension`, `PermissionExtension`, `WorkflowExtension`), bidirectional catalog/processing boundaries enforced through `ProcessingPort` + `CatalogPort` architecture guards, maps/search service facades protected by private-module import guards plus size-budget checks, declarative manifest automation for first-catalog adoption, and a complete map-builder cartographic authoring stack with full MapLibre line-gradient authoring, Line → Arrow rendering, bounded/server-side Point Cluster rendering, style JSON round-trip, and the schema-preserving sidebar/Add Dataset redesign hardened in v1002-v1003.

The marketing and documentation web properties (v14.0 + v15.0 + 999.5 cross-repo style alignment) and their planning artifacts moved to the `getgeolens.com` repo on 2026-04-26 — see `~/Code/getgeolens.com/.planning/` for active docs-site work.

## Current Milestone: v1024 ADK High Peaks Marketing-Ready

**Goal:** Upgrade the Adirondack High Peaks marketing maps from dogfooding-shippable to screenshot/demo-ready: higher-fidelity source data, expanded map content, a bonus 3D relief variant, and a builder surface that can reorder layers and adjust terrain settings without browser-console noise.

**Target features:**
- Swap the soft 3.5 MB ArcGIS REST aerial for a TNM/NAIP 0.6m aerial source where available, with an explicit documented fallback if the TNM API does not publish NAIP for this AOI.
- Add NHD hydrography and the remaining ADK 46er peaks to the ADK High Peaks marketing catalog and saved-map composition.
- Compose the deferred bonus 3D relief variant Map 2 for the ADK High Peaks map set.
- Fix builder mixed raster/vector layer reorder so vectors can be dragged above DEM/aerial rasters and the visual MapLibre stack updates immediately and persists after reload.
- Fix terrain DEM tile min/max zoom, preserve explicit `terrain_config.enabled=false`, and smoke-check terrain source/exaggeration controls in the builder.
- Stop terrain/internal MapLibre errors from surfacing as basemap-connection toasts, move the toast away from map controls, and resolve or suppress the Positron `road_` / `us-state_` sprite warnings.

**Key context:**
- Phase numbering continues from 1101 (no `--reset-phase-numbers`)
- Public tag target: `v1.5.9` (SemVer patch — data/script + UI/rendering bug fixes; avoid API/schema/migration changes unless a verified fix requires them)
- Source context: `.planning/quick/260524-o57-adk-high-peaks-data/` (especially `NEXT-MILESTONE-DRAFT.md`, `260524-o57-SUMMARY.md`, and `260524-o57-API-ISSUES.md`)
- HARD INVARIANT: a freshly composed ADK map at `localhost:8080/maps/{new_id}` opens in the builder with zero browser console errors/warnings, vectors above rasters after reorder, and working terrain settings/exaggeration controls verified through Playwright MCP.

## Recent Shipped Milestone: v1022 Parallel-Test Cascade Closure + Hygiene Tail

**Shipped:** 2026-05-24
**Tag:** `v1022` (local) + `v1.5.7` (public) at commit `48707fb1`

**Goal delivered:** Closed v1021's three test-infra carry-forwards in a single hygiene-shape milestone. 4 of 5 requirements satisfied locally; CI-01 (`pytest-parallel-isolation` live-verify on real GH Actions) deferred to v1023 due to GitHub Actions billing block at push time. Degraded close authorized by user via AskUserQuestion.

**Delivered (4/5 reqs satisfied + 1 deferred, 4 phases 1094-1097, 6 plans):**

- **Cascade Spike (Phase 1094)** — PARA-01 (e): `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` (5 sections, 314 lines). v1021 Run 3 cascade NOT reproducing on HEAD (distinct 14/14/21). NEW dominant root cause: `_init_tile_pool_for_tests` (3 sibling fixtures at `test_tiles.py:151` + `test_embed_tokens.py:56` + `test_tile_signing.py:107` bypass conftest envelopes). Fix Shape A* chosen; WR-02 disposition INDEPENDENT. Hypothesis-miss as positive spike outcome.

- **Cascade Fix + WR-02 Closure (Phase 1095)** — PARA-01 fix (Shape A*): wrap 3 `asyncpg.create_pool` sites in existing `_run_with_too_many_clients_retry` envelope. Regression pin `test_init_tile_pool_retries_on_transient_too_many_clients` at `test_fixture_isolation_v1020.py:1144`. `-n auto` 3-run baseline 20/8/16 → 3/2/3 distinct. PARA-02 (Shape Y2): WR-02 closed via load-bearing rationale (Y1 empirically failed — `asyncio.run() cannot be called from a running event loop`). Regression pin `test_engine_retry_yields_event_loop_during_backoff` at line 1253.

- **Hygiene Tail (Phase 1096)** — HYG-01: WR-03 narrow except expanded to `(TypeError, AttributeError, InvalidRequestError)` per SQLAlchemy 2.x event-API + WR-04 listener teardown via `_RetryingAsyncEngine.dispose()` override + `event.remove(...)`. 3 new regression pins: `test_engine_retry_do_connect_event_handler_retries_on_transient_error` (L1391, exercises load-bearing event-handler path) + `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` (L1557) + `test_init_tile_pool_propagates_non_transient_error` (L1666). `-n auto` 5/2/2 distinct preserved.

- **Live-Verify + Close Gate (Phase 1097)** — CLOSE-01: sequential `3 failed (OOS triad: layering + phase_275 + ssrf_redirect) / 3060 passed / 38 skipped`; `-n 4` `4 failed (2 OOS + 2 oauth flake) / 3059 passed / 38 skipped`; `-n auto` 3-run 2/3/2 distinct deterministic + 0 ICN frames. CHANGELOG `[1.5.7]` + tags `v1022` (local) + `v1.5.7` (public) cut at SHA `48707fb1`. **CI-01 DEFERRED to v1023** — GitHub Actions billing block at push (run 26359374410: 0/13 jobs executed, all failed/skipped at runner-allocation). Gate-shape verified locally; external live-verify pending billing resolution.

**Audit verdict:** `tech_debt` (CLEAR-TO-TAG degraded) — 1 v1023 carry-forward (CI-01-v1023). See `.planning/milestones/v1022-MILESTONE-AUDIT.md`.

**Patterns established:**
- **Spike-first preserved (4th milestone in a row)** — v1019/v1020/v1021/v1022 all opened with audit-only spike before fix.
- **Hypothesis-miss as positive outcome** — Phase 1094 spike found v1021 cascade NOT reproducing; reclassified surface to a different code path. Spike worked exactly as intended.
- **Y1 → Y2 fallback per documented fork rule** — Plan 02 Task 2 fork rule named both alternatives upfront; Y1 attempted, empirically failed, reverted to Y2. No revert-and-replan needed.
- **WR-* finding family closure pattern** — Phase 1093 review WR-01..04 carried forward to v1022 HYG-01 (1 plan, 4 sub-items, 3 new pins) — clean carry-forward pattern.
- **Degraded close with documented carry-forward** — when infrastructure (not code) blocks a final acceptance criterion, ship the milestone with the local-evidence requirements GREEN and register the external-evidence gap as a Future Requirement carry-forward. User-authorized via AskUserQuestion.

**Deferred to v1023 (1 item):** CI-01-v1023 — live-verify the `pytest-parallel-isolation` CI gate on real GitHub Actions infrastructure (post-billing-resolution). Operator action: resolve billing → `gh run rerun 26359374410` → document GREEN evidence in v1023 follow-up phase.

**Migrations:** None. All v1022 changes are test-infra hygiene (conftest + test fixtures + REQUIREMENTS.md + CHANGELOG + planning docs).

## Recent Shipped Milestone: v1021 Docker Rebuild Sweep + Engine-level Retry

**Shipped:** 2026-05-23
**Tag:** `v1021` (local) + `v1.5.6` (public) at commit `35596a7a`

**Goal delivered:** Closed the operational findings surfaced by the 2026-05-23 docker rebuild sweep (quick task `260523-at1`) and retired v1020's engine-level retry carry-forward.

**Delivered (6/6 reqs, 3 phases 1091-1093, 8 plans):**

- **Ingest correctness (Phase 1091)** — INGEST-01: `urban_areas_landscan_10m` quicklook `MissingGreenlet: greenlet_spawn has not been called` async-context bug closed at `backend/app/processing/ingest/tasks_common.py:898-906` via fresh `_job_phase_session("quicklook")` wrap (Shape A from spike audit) + iter-2 post-upload `await session.rollback()` recovery for the `sqlalchemy.org/e/20/8s2b` poisoned-cursor state on the timeout path. 4 regression pins at `backend/tests/test_quicklook_async_context.py`. Live: 109/109 datasets seed clean with `quicklook_256_uri` populated. OPS-01: `reconcile_failed_jobs()` in `scripts/seed-natural-earth.py:723` queries `GET /api/admin/jobs/?status=failed&limit=200` with run-window filter, exits non-zero on failure. 4 unit tests + 2 main() exit-code regression pins.

- **Routing + infra hygiene (Phase 1092)** — ROUTE-01: `redirect_slashes=False` at `backend/app/api/main.py:443-487` + ~28 manual dual-shape decorators across `auth/router.py`, `settings/router.py`, `catalog/maps/router.py`, `admin/router.py`, etc. + `_add_trailing_slash_aliases(app)` programmatic hook covering remaining ~72 routes + Vite proxy `Location` rewrite at `frontend/vite.config.ts:90-128` (scheme-preserving). 8 tests at `backend/tests/test_redirect_slashes.py`. Live: 11 routes spot-checked, zero `api:8000` leaks. INFRA-01: `migrate` service `entrypoint: []` override at `docker-compose.yml:124`; alembic single-fire confirmed via `Context impl PostgresqlImpl` grep count = 1 (was 2). INFRA-02 (ACCEPT): `db/Dockerfile:1-18` inline rationale + CHANGELOG `[Unreleased]` entry for the `--platform=linux/amd64` pin.

- **Engine-level retry envelope (Phase 1093)** — TEST-01 (closes v1020 carry-forward): `_RetryingAsyncEngine` composition wrapper class at `backend/tests/conftest.py:711` + `_install_dbapi_connect_retry` `do_connect` event handler at `:664`. REUSES `_TRANSIENT_CONTENTION_EXCEPTIONS` + `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` verbatim. 4 regression pins at `backend/tests/test_fixture_isolation_v1020.py`. In-test contention reduced 126/139 → 11/12 distinct per `-n auto` run (-91%) on Runs 1+2. Post-fix `pytest -n auto` 8/9/3 failed per run (literal ≤10 criterion satisfied — Option A disposition).

**Audit verdict:** tech_debt (6/6 reqs satisfied; CLEAR-TO-TAG). See `.planning/milestones/v1021-MILESTONE-AUDIT.md`.

**Patterns established:**
- **Spike-first preserved** — Phase 1091 spike at `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` identified the exact `tasks_common.py:826` async-context boundary line BEFORE the fix; matches v1019/v1020 spike-first precedent.
- **Iter-2 in-checkpoint diagnostic** — Plan 1091-02 caught the URI-persistence gap during live verification (blank canvas in storage but URI null in DB), iterated to add `await session.rollback()` recovery between upload and commit, re-verified GREEN. Inline checkpoint iteration > revert-and-replan when the surface is one missing recovery step.
- **Composition wrapper preserves `.pool` accessor** — Phase 1093's `_RetryingAsyncEngine` uses `@property pool` delegation, NOT inheritance, so `test_conftest_pool_sizing.py:261,281` pins on `type(engine.pool).__name__` continue to pass.
- **`do_connect` event handler ≠ wrapper `.connect()` override** — `async_sessionmaker(wrapper)` bypasses the AsyncEngine wrapper's `.connect()` override because it extracts `wrapper.sync_engine` directly. The production-effective retry path is the `do_connect` event handler installed on the sync engine.
- **Dual-shape decorator + programmatic alias hook** — instead of registering both shapes by hand on every route (~100 routes), `_add_trailing_slash_aliases(app)` walks `app.routes` at startup and registers slash-variants for routes that don't already have them.

**Deferred to v1022 (1 item):** Category 4.1 per-worker DB lifecycle parallel-mode cascade. `pytest -n auto` Runs 3+4 produced 709/1020 distinct failures with `InvalidCatalogNameError` cascade — different architectural surface than TEST-01's in-test wrapper. Findings at `.planning/phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md`. Recommended path: spike-first on `_test_db_lifecycle:~661-674` per-worker race OR `max_connections` dynamic-sizing. Phase 1093 review findings WR-01..04 (test pin coverage + edge cases) also queued for v1022 alongside this work.

## Recent Shipped Milestone: v1020 Fixture Isolation

**Shipped:** 2026-05-22
**Tag:** `v1020` (local) + `v1.5.5` (public) at commit `8a924bb6`

**Goal delivered:** Restored `pytest -n auto` to a robust baseline. Cascade reduction 648 → 76 (-88.3%); per-worker DB lifecycle race (407 failures) and setup-phase contention (150 failures) fully resolved; in-test contention (87 → 48) reduced with flake-class disposition. New CI gate (`pytest-parallel-isolation` job in `.github/workflows/ci.yml`) blocks parallel-test regressions on `-n 4`. `make test` now runs parallel by default (sequential opt-in via `make test-sequential`). PERF-01 baseline documented at `.planning/audits/PYTEST-XDIST-PERF-v1020.md` (`-n 4` chosen as data-justified optimal: 1.53× speedup vs `-n auto`'s 1.23×, with 99% cascade reduction).

**Delivered (9/9 reqs, 4 phases 1087-1090, 11 plans):**

- **Fixture-isolation spike (Phase 1087)** — FI-01: classified 648 failures into 5 root-cause categories; **NONE of the four v1019 hypotheses reproduced** (Redis singleton, storage provider override, dependency_overrides leak, autouse-fixture coupling all = 0 failures). The actual dominant root cause was a per-worker DB lifecycle race (gw15 setup failed silently in `_test_db_lifecycle`).

- **Fixture-isolation fixes (Phase 1088)** — FI-02 + FI-03: replaced silent-swallow `except Exception` at `conftest.py:275-278` with structured `OperationalError` handler (retry-with-backoff for transient `TooManyConnections`; loud-fail-on-exhaust). Added 3 retry helpers: `_create_test_db_with_retry`, `_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`. 11 regression pins in `backend/tests/test_fixture_isolation_v1020.py` covering canonical + asyncpg-raw + propagate-non-contention + exhaust-budget branches. WR-02 PEP-343 fix (gate `__aexit__` on successful `__aenter__`) applied inline post-review.

- **CI gate + perf + parallel default (Phase 1089)** — CI-01: new `pytest-parallel-isolation` job in `.github/workflows/ci.yml:499-595`, sister to v1017's `alembic-clean-db`. CI-02: `make test` → `-n 4` default; `make test-sequential` for debugging. PERF-01: `.planning/audits/PYTEST-XDIST-PERF-v1020.md` with reproducibility section + recommended default.

- **Close-gate + tags (Phase 1090)** — HYG-01: 38 sequential skips all dispositioned KEEP (platform/env-gated). HYG-02: 3× `-n 4` = 0/0/0 (100% deterministic) AND 3× `-n auto` = 89/69/62 (confirms 4.3 residual is flake-class, defer to v1021). HYG-03: CHANGELOG `[1.5.5]` paper-trail for v1019 WR-01 (`frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script preserved). Tags `v1020` + `v1.5.5` cut at `8a924bb6`.

**Audit verdict:** tech_debt (9/9 reqs satisfied; 1 v1021 carry-forward + 1 threshold-relaxation + 1 CI live-verify deferred). See `.planning/milestones/v1020-MILESTONE-AUDIT.md`.

**Inline review fixes (1):** WR-02 PEP-343 gate fix at `conftest.py:572` (commit `19dcfd51`).

**Patterns established (4):**
- Hypothesis-miss as a positive spike outcome (validates measurement-before-fix discipline)
- Structured `OperationalError` handler with retry-with-backoff + loud-fail-on-exhaust (replaces silent-swallow anti-pattern)
- Multi-source cross-verification before CI/Makefile/audit-doc consistency commits
- PERF-01-driven CI default (`-n 4` not `-n auto` — data-justified per REQUIREMENTS.md Out-of-Scope exception)

**Deferred to v1021 (1 item):** Engine-level retry envelope for `pytest -n auto` cascade flake-class. The 4.3 residual at 48 failures (above audit's <30 threshold) is non-deterministic per HYG-02 (only 6 of 179 union-IDs reproduced across 3 consecutive runs). Engine-level retry would unlock full parallelism beyond the chosen `-n 4` ceiling. Documented in REQUIREMENTS.md FI-02 acceptance text + CHANGELOG `[1.5.5]` Known Limitations + v1020 audit Tech Debt section.

**Migrations:** None. All v1020 changes are test-infra hygiene (conftest fixtures + CI yaml + Makefile + docs).

**Milestone close:** 9/9 reqs satisfied; tags `v1020` + `v1.5.5` at commit `8a924bb6`. See `.planning/milestones/v1020-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1019 Hygiene Tail — v1018 Frontend + xdist + Process

**Shipped:** 2026-05-22
**Tag:** `v1019` (local) + `v1.5.4` (public) at commit `02cb25db`

**Goal delivered:** Closed 4 v1018-deferred tech-debt items (frontend TS hygiene + `/maps/new` 422 noise + `/api/api/` doubled prefix + `pytest -n auto` Postgres cascade) plus 2 new items surfaced during v1019 planning (process tightening to prevent v1018-style REQ/executor drift, runtime symmetry verification for v1018 Phase 1080-02 ssl=False line). Live Playwright MCP 5/5 surfaces green; tags cut + recorded.

**Delivered (6/6 reqs, 3 phases 1084-1086, 7 plans):**

- **Frontend hygiene (Phase 1084)** — TD-09: 37 TS errors / 15 files → 0 (zero suppressions; added missing `typecheck` npm script; vitest 2105/2105 preserved). TD-11: `/maps/new` 422 console-noise eliminated via 1-line route-level `<Navigate to="/maps">` redirect in `App.tsx` (verified live via Playwright MCP — zero `/api/maps/new` requests, zero 422s). TD-12: `/api/api/` doubled prefix fixed at `use-quicklook.ts:58` (dropped leading `/api/` from path literal; only outlier in codebase).

- **pytest -n auto stabilization (Phase 1085)** — TD-10: spike-first measurement reproduced **2452 cascade errors** (628 `TooManyConnectionsError` + 1824 `CannotConnectNowError`); fix shape (a) per-worker pool sizing chosen + iterated to NullPool + 5s startup stagger (root cause was setup-phase concurrent connections, not runtime pool). Result: **2452 → 0 cascade errors**; sequential baseline 3025→3036 (+11); 11 regression tests pin the per-worker invariant.

- **Process tightening (Phase 1086 / Plan 01)** — TD-13: repo retro at `.planning/retros/v1019-process.md` covers 3 v1018 drift incidents (paraphrased test names, `tasks_common.py` path/line drift, Plan 1081-02 SUMMARY checkbox-flip miss). Global skill updates (additive): `~/.claude/agents/gsd-planner.md` (+18 lines `<req_citation_pinning>`), `~/.claude/agents/gsd-executor.md` (+20 lines `<requirements_traceability_flip>`), `~/.claude/get-shit-done/templates/requirements.md` (+14 lines Code-Pinned Examples).

- **Runtime symmetry + close gate (Phase 1086 / Plan 02)** — TD-14: `docker compose up -d --build api worker` rebuilt both images; `docker exec geolens-api-1 grep -n "ssl=False" app/core/config.py` → line 309 confirmed (same for worker). Close gate: sequential pytest 3036/0/38 (+11 over v1018 baseline), e2e:smoke:builder 25/0/1 (matches v1017/v1018), frontend typecheck exit 0, live Playwright MCP 5/5 surfaces.

**Audit verdict:** PASSED (tech_debt — 1 v1020 carry-forward) — 6/6 reqs · 3/3 phases · 6/6 cross-phase integration · 5/5 live MCP smoke surfaces. See `.planning/milestones/v1019-MILESTONE-AUDIT.md`.

**Inline review fixes (5):** WR-01 (Plan 1084 lint companion script `902875bf`); WR-01+WR-02 (Plan 1085 stagger docstring + NullPool sentinel `6488fdf3`); WR-03 (Plan 1085 warning on malformed worker ID `37b86244`); CR-02 (Plan 1085 real NullPool branch coverage via `_make_test_async_engine` helper `ea24168c`).

**Patterns established (3):** fixed-point bootstrap of new rules (audit-time retroactive flip for pre-rule plans); spike-first when fix shape non-obvious (surface measurement is right answer even when deeper mechanism iterates); live Playwright MCP as canonical close-gate verification (catches `/api/api/` and 422 patterns that headless e2e misses).

**Deferred to v1020 (1 item):** 192 pytest fixture-scope failures exposed by `-n auto` parallelism (not asyncpg cascade — that is closed; not a regression of TD-10 — sequential mode clean). Documented in CHANGELOG `[1.5.4]` Known Limitations.

**Migrations:** None. All v1019 changes are non-schema (frontend hygiene + test-infra knob + process docs + container probe).

**Milestone close:** 6/6 reqs satisfied; tags `v1019` + `v1.5.4` at commit `02cb25db`. See `.planning/milestones/v1019-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1018 Hygiene — v1017 Tech-Debt Tail

**Shipped:** 2026-05-21
**Tag:** `v1018` (local) + `v1.5.3` (public) at commit `d1b76061`

**Goal delivered:** Closed the 8 tech-debt items deferred from v1017 audit. Restored full-suite pytest signal (0 InvalidCatalogNameError sequentially; 3025/0/38), closed one minor production-code defect (`database_connect_args["ssl"]=False` on disable branch), and capped the v1017 hygiene tail.

**Delivered (8/8 reqs, 4 phases 1080-1083, 8 plans):**

- **Phase 1080 Production-Code Drift + Config Hygiene** — TD-01 `# broad:` justification at `tasks_common.py:232,238` + bonus line-1030 third broad-except (macOS `git grep -E \s` BSD-vs-GNU portability bug caught and fixed inline at `test_layering.py:1577` — `\s+` → `[ \t]+`); TD-07 `connect_args["ssl"]=False` on disable branch + 3-case unit pin + bonus dead-test repair (`test_verify_full_returns_ssl_context_with_verify` constructed verify-full Settings but asserted on require-mode).
- **Phase 1081 Test Fixture & Assertion Drift** — TD-02/03 password fixture upgraded (`securepass123` → `TestPass1234!` SEC-S16 fixture); TD-05 `validate_url_for_ssrf` mocked at defining module (lazy from-import); TD-06 `client` fixture arg added to `test_job_phase_session_none_branch_rolls_back_on_exception` — transitively monkey-patches `db_module.async_session`, eliminating asyncpg cross-loop pool contamination.
- **Phase 1082 Test Environmental** — TD-04 `run_service_preview` AsyncMock caller-namespace patch (module-top from-import → caller) drives existing 502 branch, preserves IDOR assertion, removes ogrinfo CLI host dependency.
- **Phase 1083 Close Gate** — TD-08 CHANGELOG `[1.5.3] - 2026-05-21`; backend pytest 3025/0/38 sequential (539s); frontend `tsc -b` exit 0 on touched files + vitest 2105/2105; e2e:smoke:builder 25/1 (matches v1017 baseline); live Playwright MCP smoke 5/5 surfaces PASS on `localhost:8080` (0 console errors aggregated, 0 failed network requests).

**Audit verdict:** PASSED — 8/8 reqs · 4/4 phases · 8/8 cross-phase integration · 5/5 live MCP smoke surfaces. See `.planning/milestones/v1018-MILESTONE-AUDIT.md`.

**Patterns established (3 new):**
- `# broad:` same-line justification per `test_layering.py` substring-match contract (Phase 1080).
- Caller-namespace vs defining-module mock-patch target rule: module-top from-import → caller namespace; lazy body-level from-import → defining module (Phase 1082).
- macOS BSD vs GNU `grep -E` `\s` portability — always use `[ \t]+` (Phase 1080 WR-01).

**Tech-debt followups for v1019 (4 items, all logged in REQUIREMENTS.md Future Requirements):**
- 36 pre-existing TS errors in 14 untouched frontend test files (frontend hygiene)
- `pytest -n auto` Postgres recovery cascade on 16 xdist workers (test-infra)
- `/maps/new` 422 console-noise — 2 spurious 422s before Create dialog short-circuits (v1008 quirk)
- Doubled `/api/api/` prefix on legacy quicklook proxy URLs (cosmetic; all return 200 OK)

**Milestone close:** 8/8 reqs satisfied; zero v1019 deferrals from audit; tag `v1018` + `v1.5.3` at commit `d1b76061`. See `.planning/milestones/v1018-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1017 Test Infra & Audit Tail

**Shipped:** 2026-05-21
**Tag:** `v1017` (local) + `v1.5.2` (public) at commit `c968392b`

**Goal delivered:** Closed the v1015/v1016 hygiene tail. Restored test signal accuracy by refactoring the broken conftest test-DB lifecycle (eliminated 1363 `asyncpg.exceptions.InvalidCatalogNameError` errors) and fixing all 11 v1015 baseline pytest failures at root cause. Closed 7 deferred backend/frontend ingest P2 findings. Wired `test_alembic_upgrade_clean_db.sh` into GitHub Actions CI. Re-verified the Phase 1071 KNOWN-02 docker-smoke gap (caught and fixed 3 latent script bugs inline). Captured post-fix pytest baseline. Archived the 196-item quick_tasks tail.

**Delivered (13/13 reqs, 5 phases 1075-1079, 20 plans):**

- **Test infrastructure (Phase 1075)** — `backend/tests/conftest.py` refactored to use per-worker test-DB isolation via `PYTEST_XDIST_WORKER`; eliminated the 1363 `InvalidCatalogNameError` errors. `pytest-xdist>=3.6.0` added to dev dependencies; 6 regression tests pin lifecycle invariants. All 11 v1015 baseline pytest failures fixed at root cause (no skips): 3 mock-fixture drift (v1015 `fde5d9ae` IDOR closure), 3 mock signature drift + SSRF re-validation (v1016 IA-P0-02/03), 5 snake_case canonicalization (Phase 1060 `a400eb89`).
- **Backend ingest P2 closure (Phase 1076)** — ING-02: `metadata.py` 4 internal commits removed (`_finalize_ingest` is single phase-2 commit point); regression test pins rollback. ING-03: New `StorageProvider.get_stream()` Protocol + local 1 MiB chunked impl (5 GB COG no longer pins 5 GB resident memory). ING-04: Worker exports temp-dir sweep gated on `stat.st_mtime > 1h`. ING-06: `_apply_reupload_swap` single retry on `LockNotAvailableError` with 15s timeout + 200ms sleep. ING-07: New optional `RasterCommitRequest.strict_cog: bool = False` field (backward-compat default).
- **Frontend ingest P2 closure (Phase 1077)** — ING-01: `getCogDownloadUrl(id)` helper extracted to `datasets.ts`; `JobProgress.tsx` no longer string-concats. ING-05: New `frontend/src/api/_presignedUpload.ts` with `uploadChunks(urls, file, partSize)` helper; both `ingest.ts` and `datasets.ts` now share the canonical helper.
- **CI hardening (Phase 1078)** — New `alembic-clean-db` job in `.github/workflows/ci.yml`. Triggers on push-to-main + PRs touching alembic/scripts/models/db paths. Wraps `backend/scripts/test_alembic_upgrade_clean_db.sh`. Closes SEC-OBSV-03 from v1016 Phase 1072.
- **Verification + hygiene (Phase 1079)** — TI-03: Pytest baseline at `.planning/audits/PYTEST-BASELINE-2026-05-21.md` (3018/0 InvalidCatalogNameError sequentially). VG-01: Docker-smoke verified against rebuilt stack — **caught and fixed 3 latent bugs in the Phase 1071 script** (PYTHONPATH=., PGSSLMODE=disable, init-db.sh heredoc quoting) before the script ran cleanly. Same fixes benefit CI-01. HYG-01: 196 quick_tasks archived (exceeded <50 target).

**Close-gate results:** Backend pytest 3018/0 (sequential, 0 InvalidCatalogNameError); frontend `tsc -b` exit 0 on touched files; vitest 2105/2105; e2e:smoke:builder 25/26 (1 skipped); live Playwright MCP smoke 5/5 surfaces green on `localhost:8080`; CHANGELOG `[1.5.2] - 2026-05-21` covers all 13 requirements.

**Audit verdict:** PASSED — 13/13 reqs · 5/5 phases · 5/5 integration · 5/5 MCP surfaces. See `.planning/v1017-MILESTONE-AUDIT.md`.

**Tech-debt followups for v1018 (8 items):**

- 7 Phase 1075 NEW-DISCOVERY failures (test_layering broad-except justification, test_phase_279_user_lifecycle ×2 password policy drift, test_reupload_idor environmental ogrinfo gap, test_reupload_service ×2 SSRF gate drift, test_tasks_common_phase_brackets async loop contamination)
- 1 production-code defect from Phase 1079-03 fix-discovery: `backend/app/core/config.py:database_connect_args` should set `connect_args["ssl"]=False` when `database_ssl_mode=='disable'` (low priority — production never sets `disable`)

**Migrations:** None. All v1017 changes are internal refactors + helper extraction + optional schema field (`strict_cog` default False).
**Milestone close:** 13/13 reqs satisfied; tag `v1017` + `v1.5.2` at commit `c968392b`. See `.planning/milestones/v1017-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1016 Hardening Sweep

**Shipped:** 2026-05-21
**Tag:** `v1016` (local) + `v1.5.1` (public) at commit `70241f96`

**Goal delivered:** Closed the v1015 tech-debt tail (7 KNOWN items) + 5 v1014 INFO pending todos + Dependabot #40 (idna ≥ 3.15), ran fresh `/sec-audit` + `/ingest-audit` (both returned PASS at all HIGH/MEDIUM tiers — first clean double-pass), and remediated 4 P2 ingest/frontend audit findings. Full close-gate protocol enforced in Phase 1074 (full backend pytest + `e2e:smoke:builder` + `npm run typecheck` + live Playwright MCP smoke).

**Delivered (26/26 reqs, 4 phases 1071-1074, 12 plans):**

- **Known-items closure (Phase 1071)** — Dependabot #40 idna ≥ 3.15 bump (CVE-2026-45409); 5 v1014 INFO doc/test closures (PASSWORD env docs, whitespace symbol class, `exp.Dot` AST test, `_sanitize_authorization_token` 8-char doc, `StacSearchBody` Pydantic bounds); `_resolve_download_user` JWT sub claim consumption; `gdal_safe_env` helper applied to all 4 GDAL CLI subprocesses; `VRT_VSI_ALLOWED_PREFIXES` single source of truth; export 403 for revoked-export-on-viewer; `test_alembic_upgrade_clean_db.sh` script.
- **Fresh audit sweep (Phase 1072)** — `SECURITY-AUDIT-2026-05-21.md` (PASS, 0 findings); `INGEST-AUDIT-2026-05-21.md` (PASS, 0 P0/P1, 9 P2); `TRIAGE-2026-05-21.md` maps 12 findings: 4 → Phase 1073, 8 → v1017. REQUIREMENTS.md expanded from 24 → 26 reqs.
- **Audit remediation (Phase 1073)** — TanStack `jobStatusByDataset` invalidation wired into all re-upload/VRT mutations (REMED-01); `JobStatusResponse` extended with `progress`/`current_step`/`rows_processed` + Alembic migration 0022 + worker step-write sites (REMED-02); `_job_phase_session` async context manager replacing 14+ session-bracket boilerplate sites (REMED-03); `build_titiler_cog_url` helper + SEC-OBSV-01/02 docstrings (REMED-04).
- **Close gate (Phase 1074)** — CHANGELOG `[1.5.1] - 2026-05-21`; full backend pytest 1636/1647 PASS (11 failures are v1015 carryover, not regressions); vitest exit 0; e2e:smoke:builder 25/1; typecheck exit 0; live Playwright MCP smoke 5/5 PASS including REMED-02 live `JobStatusResponse` contract verification; tags cut + pushed.

**Key wins:**
- Security merge gate: **PASS** (0 HIGH / 0 MEDIUM / 0 LOW — all 36 v1014/v1015 prior findings confirmed closed + 11 KNOWN closures verified)
- Ingest lifecycle: 4 P2 findings closed; `_job_phase_session` eliminates 14+ copy-pasted boilerplate sites
- `gdal_safe_env`: every GDAL subprocess shares one env-overlay helper — no subprocess inherits an unclamped env
- `JobStatusResponse` progress fields: 10-min raster ingests now show live step-transition progress in UI
- `build_titiler_cog_url`: 3 inlined `http://titiler:8000` f-strings consolidated; SEC-OBSV docstring contracts pinned

**Migrations:** `0022_ingest_jobs_progress_columns` (reversible).
**Milestone close:** 26/26 reqs; tag `v1016` + `v1.5.1` at commit `70241f96`. See `.planning/milestones/v1016-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1015 Ingest/Export Lifecycle Hardening

**Shipped:** 2026-05-20

**Goal delivered:** Closed the 4 P0 + 5 P1 findings from `/ingest-audit` 2026-05-19 + the `router_reupload.py` IDOR that v1014 acknowledged but deferred + v1014's hygiene tail. Public tag `v1.5.0`. Local tag `v1015` at `e4a7026b`.

**Delivered (13/13 reqs, 6 phases 1065-1070, live MCP re-verify):**

- **Tier A — ship-blocking (Phases 1065-1067)** — Wired `POST /api/auth/download-token/{id}` mint endpoint + frontend `downloadCog()` async refactor (IA-P0-01); closed reupload IDOR across all 6 `router_reupload.py` handlers + deleted pre-commit exclusion (REUPLOAD-IDOR-01); added `_assert_compatible_record_type` to `reupload_service_preview` with new `service_type` keyword-only arg (IA-P1-02); chunked size enforcement in `save_upload_file` raising HTTP 413 (IA-P0-02); `commit_import` + `ingest_service` + `reupload_service` workers re-validate `validate_url_for_ssrf` (IA-P0-03); option (b) heartbeat decision — dropped `last_heartbeat_at` column via Alembic 0021 + `recover_stale_jobs` uses `started_at < JOB_TIMEOUT_SECONDS` so 6-min ingests survive rolling deploy (IA-P0-04).
- **Tier B — P1 follow-ups (Phases 1068-1069)** — `run_ogr2ogr_service` switched from `GDAL_HTTP_HEADERS` env to 0600 tempfile via `GDAL_HTTP_HEADER_FILE` (IA-P1-06); 3-layer VRT hardening — `validate_vrt_body` XML sniff + `<SourceFilename>` traversal guard with 7-prefix VSI allowlist + `_VRT_SAFE_ENV` overlay on `gdalbuildvrt` (IA-P1-03); `validate_where_clause` rejects `;`/`--`/`/* */`/unbalanced single-quotes before the AST allowlist (IA-P1-04); `export_dataset_endpoint` gated by `require_permission("export")` (IA-P1-01).
- **Tier C — hygiene close-gate (Phase 1070)** — 5 pending-todo files for v1014 deferred INFO findings (HYG-01); 6 retroactive REQUIREMENTS.md ticks discovered already-checked at v1014 archive (HYG-02); 2 cheap v1014 INFO todos closed inline + moved to resolved/ (HYG-03).

**Smoke gate:** Backend pytest 59/59 new v1015 + 134/134 pure-unit in modified areas. Live orchestrator-driven Playwright MCP smoke on `localhost:8080` against rebuilt containers — 5/5 surfaces PASS: IA-P0-01 mint returns 200 + correct JWT shape; IA-P1-04 statement terminator/comment/unbalanced-quote return 400; IA-P1-01 anonymous export returns 401 (capability dependency fires); catalog + dataset detail + maps pages load with 0 console errors.

**Migrations:** `0021_drop_ingest_job_last_heartbeat_at` (reversible).

**Inline review-fix discipline:** Zero v1015.1 deferrals — 21 atomic commits across 6 phases, all tests green at HEAD.

**Tech-debt followups (7 items deferred to next housekeeping pass):**

- Phase 1065: pre-existing `_resolve_download_user` no-sub JWT consumption gap (anonymous download token issued but not consumed; not a v1015 regression).
- Phase 1067: `alembic upgrade head` against a clean DB not exercised in close-gate (test-DB-bound; ordering verified via `down_revision` linkage).
- Phase 1068: `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` clamp scoped only to `_build_vrt`; other GDAL subprocesses (raster ingest, COG conversion) inherit unclamped env.
- Phase 1068: VRT VSI allow-list (7 prefixes) requires dual-edit (validator + env overlay) when adding a new scheme.
- Phase 1069: IA-P1-01 verified via signature inspection + live 401 anonymous; full 403-for-revoked-export-on-viewer left to v1014 SEC-S04 parity.
- Phase 1070: `e2e:smoke:builder` + `npm run typecheck` not run in close-gate (covered by per-plan verification + live MCP).
- Phase 1070: backend pytest locally restricted to touched-area + new v1015 files (CI runs full suite).

**Milestone close:** 13/13 reqs satisfied; tag `v1015` + `v1.5.0` at commit `e4a7026b`. See `.planning/milestones/v1015-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1014 Security Audit Remediation

**Shipped:** 2026-05-20

**Goal delivered:** Closed all 27 findings from `/sec-audit` 2026-05-19 (7 HIGH + 9 MEDIUM + 10 LOW + 1 architectural guardrail), restoring the merge gate from BLOCK → PASS and pinning the visibility-filter coverage pattern into AGENTS.md + pre-commit hooks. Public tag `v1.4.0`.

**Delivered (28/28 reqs, 4 phases 1061-1064, 17 plans, live MCP re-verify):**

- **HIGH severity remediation (Phase 1061)** — STAC catalog visibility filter (SEC-S01); dataset metadata mutation IDOR closed across 3 + 2 CR-01 handlers (SEC-S02); column DDL IDOR closed across 4 handlers (SEC-S03); SSRF redirect-bypass closed via `make_safe_client()` factory with per-hop `_revalidate_redirect` hook + `GDAL_HTTP_FOLLOWLOCATION=NO` (SEC-S04); pgvector related-datasets IDOR closed (SEC-S05); `.env.demo` → `.env.demo.example` + `scripts/init-demo-env.sh` per-deploy generator + 3-literal unconditional `validate_demo_credentials_guard` (SEC-S06); MinIO `:?required` fail-closed defaults (SEC-S07); AGENTS.md 3-rule Security checklist + 2 pre-commit hooks (SEC-GUARD-01).
- **MEDIUM severity remediation (Phase 1062)** — Dynamic `frame-ancestors` CSP on embed iframes from `EmbedToken.allowed_origins` (SEC-S08); sqlglot AST allowlist for ogr2ogr `-where` (SEC-S09); basemap api_key public-key docstring + rate limit (SEC-S10); per-route rate limits on `/search/datasets/` + `/datasets/{id}/related/` (SEC-S11); `simple`-regconfig GIN index for non-English FTS (SEC-S12); `max_length=1000` on `/search/facets/?q=` (SEC-S13); ESLint `no-restricted-syntax` ban on `localStorage.setItem('*token*', ...)` + httpOnly migration ADR (SEC-S14); JWT `jti` + `token_version` revocation primitives (SEC-S15); password complexity validator (12-char + 3-of-4 class diversity, configurable via `PASSWORD_MIN_LENGTH`/`PASSWORD_REQUIRE_CLASSES`) (SEC-S16).
- **LOW follow-up tickets (Phase 1063)** — STAC 5xx fixture (SEC-FU-01); DEMO_JWT_SECRET literal regression pin (SEC-FU-02); `react/no-danger` ESLint rule (SEC-FU-03); GDAL Authorization base64url charset sanitizer (SEC-FU-04); STAC `intersects` `max_length=10000` (SEC-FU-05); `math.isfinite()` guard in `parse_bbox` (SEC-FU-06); ILIKE escape via shared `escape_ilike` helper across 4 sites (SEC-FU-07); column-DDL audit feed endpoint gated by `check_dataset_access` (SEC-FU-08); nginx `server_tokens off` (SEC-FU-09); `.env.example` `DATABASE_URL_OVERRIDE` least-privilege role guidance + GRANT SQL recipe (SEC-FU-10).
- **Close Gate (Phase 1064)** — Backend pytest 288/0; vitest 2092/2092; i18n 2/2; CHANGELOG `[1.4.0]`; live MCP smoke 6/6 surfaces PASS; tags `v1014` + `v1.4.0` cut at `8c7b20e1`.

**Merge-gate transition:** Audit 2026-05-19 → **BLOCK** (7 HIGH); after v1014 → **PASS**. 21 inline review fixes applied across the milestone (6 BLOCKER + 13 WARNING + 2 INFO). 1 VERIFICATION-found BLOCKER (layering invariant on `manifest_service.py` module-level import) closed inline by commit `5f8a6b86` via function-scope lazy import. Zero v1014.1 deferrals.

**Headline architectural pattern pinned (SEC-GUARD-01):** Visibility-filter coverage is the #1 regression surface. Any new handler that fetches a `Record`/`Dataset`/`Map`/`RecordEmbedding` by ID must either call `check_dataset_access_or_anonymous` (read) or `check_dataset_access` + ownership check (write/destructive), OR apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying query. Pre-commit `visibility-filter-coverage` + `ssrf-safe-client` hooks scan route decorators on commit.

**Tech-debt followups (5 INFO deferred without pending todo files):**

- Phase 1062 IN-01: `.env.example` missing `PASSWORD_MIN_LENGTH`/`PASSWORD_REQUIRE_CLASSES` documentation
- Phase 1062 IN-02: `validate_password_complexity` whitespace treated as a symbol class
- Phase 1062 IN-03: `where_validator.py` no test for `exp.Dot` AST bypass path
- Phase 1063 IN-01: `_sanitize_authorization_token` 8-char minimum undocumented
- Phase 1063 IN-02: `StacSearchBody.limit`/`offset` no Pydantic `ge`/`le` constraints
- `router_reupload.py` resource-level IDOR gap (tracked in `.pre-commit-config.yaml:76-79`; candidate for next security hardening phase)

**Milestone close:** 28/28 reqs satisfied; tag `v1014` + `v1.4.0` at commit `8c7b20e1`. See `.planning/milestones/v1014-ROADMAP.md` for full archive.

## Recent Shipped Milestone: v1013 Ingest Hardening

**Shipped:** 2026-05-20

**Goal delivered:** Closed all 7 candidate findings from the 2026-05-19 v1012 post-ship smoke (Service URL ingest reliability + multi-layer GPKG handling), shipped the deferred Basemap Sublayer Path B FIX (full per-sublayer styling persistence), and cleaned up the fixture datasets used as smoke repros. Public tag `v1.3.0` (per Phase 1060 A-01 disposition — v1012 shipped as v1.2.1, so this milestone gets v1.3.0 not v1.4.0).

**Delivered (10/10 reqs, 4 phases 1057-1060, 15 plans, live MCP re-verify):**

- **Service URL Reliability (Phase 1057)** — WFS abstract-geometry mapping (`MultiSurface` → `MultiPolygon`, etc.); `try_all_probes()` first-success short-circuit (63s → 1.5s); URI-form CRS parser; VEC fallback when probe missing `geometry_type`.
- **Multi-Layer GPKG Handling (Phase 1058)** — Reupload File path layer-select step with schema diff; chosen-layer-name surfaced; multi-commit "ingest all layers" path in Bulk Review.
- **Basemap Sublayer Editor (Phase 1059)** — Restored per-sublayer styling persistence (3-5 day feature phase) via `MapBasemapConfig.sublayer_overrides` jsonb-additive; idle-retry recovery; round-trip across builder/viewer/shared/embed.
- **Close Gate (Phase 1060)** — Deleted 3 smoke repro datasets; all smoke gates green; CHANGELOG `[1.3.0]`; tag `v1013` + `v1.3.0` (local).
- **Inline close-gate fixes (5):** WFS-04 layer 2 (`5b965cfd`), GPKG-03 3-bug close (`831b691f`), BSE-01 load-time apply (`d24371ed`), e2e contract drift + duplicate camelCase (`a400eb89`), close-gate hygiene + CONTEXT amendment.

**Milestone close:** 10/10 reqs satisfied; tag `v1013` + `v1.3.0` at commit `470a5723` (CHANGELOG entry). Post-smoke inline fixes for 3 findings landed same-session (F1-F3 commits `54d1a8a3` / `9ad6eeb4` / `38ef49b2`) without a v1013.1 tag.

## Recent Shipped Milestone: v1012 New-User Hardening + Reupload

**Shipped:** 2026-05-19

**Goal delivered:** Made the literal new-user install and first-hour exploration of GeoLens work end-to-end. Closed the 17 still-open M001-7n8vpc audit findings + 6 enhancements (EW-01..06) and shipped the missing Reupload affordance (IMPORT-04). Public tag `v1.3.0`.

**Delivered (23/23 reqs, verified live MCP smoke):**

- **Quickstart docs (cross-repo)** — DOC-01..05 closed via PRs in `~/Code/getgeolens.com/` (commits including `d50b9ec` + `d467a74`). API-seeder path (seed-natural-earth.py + seed-ago-data.py) documented as canonical post-login step; demo overlay demoted to an "Alternative" section.
- **Bring-up polish** — BU-03 Apple Silicon platform-mismatch warning closed via cross-repo quickstart docs (commit `d467a74`).
- **Seeders** — SEED-02 configurable GDAL HTTP timeout, SEED-03 upstream data quality filter, SEED-04 driver-list error suppression.
- **UX discovery** — UX-01 API Keys signposted via Phase 1053 DOC-02 seeder docs (discovery requirement, not UI relocation).
- **Console hygiene** — CONSOLE-01 anonymous Search page 401-noise fixed by tightening `useAIAvailability` gate from `!!token` to `!!token && isAdmin` across all 4 dataset-detail consumers.
- **Routes** — ROUTE-01 `/admin/saml` Enterprise Feature notice (URL preserved); ROUTE-02 404 page `<title>` via `useDocumentTitle` + `pageTitle.notFound` i18n key × 4 locales; ROUTE-03 authenticated `/register` toast + redirect; ROUTE-04 `/m/{invalid-token}` console clean via `apiFetch` `expected404` opt-in.
- **Import operations** — IMPORT-02 Choose-File overlay `pointer-events-none` + `aria-hidden`; IMPORT-03 React 19 setState-during-render fix in `UploadForm`; IMPORT-04 Reupload feature (File path + Service URL path + version-bump + ID/slug preservation); IMPORT-05 Register Table empty-state framing.
- **Easy wins** — EW-01 single-compose path (`docker-compose.demo.yml` demoted to `-f` opt-in overlay); EW-02 API-seeder docs (folded into DOC-01); EW-04 `.env.example` SSL mode hardening with BU-01 root-cause note; EW-05 STAC stage-and-confirm before commit; EW-06 Register Table empty-state reframe.
- **Cross-record-type reupload guard** — HTTP 400 `_assert_compatible_record_type` blocks vector→raster, raster→vector, and any→VRT file swaps at both multipart and presigned reupload entry points.
- **Overflow kebab "More" label + tooltips** — pinned by M001-replay e2e regression test.

**Live smoke (2026-05-19):** Orchestrator-driven Playwright MCP sweep against live `localhost:8080` confirmed 23/23 reqs PASS + Service URL addendum (AGO / GeoServer WFS / OGC API / Reupload-via-URL paths). 7 candidate findings surfaced as v1013 seeds (1× P0 WFS commit failure, 1× P0 GPKG silent layer-pickup, 2× P1, 3× P2).

**Milestone close:** 23/23 reqs satisfied; 9 phases (1053-1056 in this repo + cross-repo doc PRs), 18 plans, 23 tasks. Tag `v1012` archived 2026-05-19 at commit `7262bdea`. Smoke report at `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md`.

## Recent Shipped Milestone: v1011.1 Builder Hygiene Carryover

**Shipped:** 2026-05-18

**Goal delivered:** Closed all 4 EMRG-FN findings carried forward from v1011 Phase 1051 Plan 12 (EMRG-01 triage) in a single hygiene phase. Path A REMOVE chosen for EMRG-FN-01 (mirroring v1011 INV-01 precedent at commit `6078b82a`); auto-resolution of EMRG-FN-04 was DISPROVEN at planner time (live `<SublayerConfigIndicators layer={null} />` callsite at `UnifiedStackPanel.tsx:556` remains post-Path A) — handled via docstring closure instead. Live Playwright MCP re-verify on `localhost:8080` confirmed Path A REMOVE intent matches shipped state (6/6 surface checks pass; 0 console errors).

**Delivered:**

- **EMRG-FN-01 Path A REMOVE.** `BasemapSublayerEditorScene` STROKE section + zoom range inputs + 5 dead-stub callbacks (`onStrokeColorChange` / `onStrokeWidthChange` / `onCasingColorChange` / `onCasingWidthChange` / `onZoomChange`) deleted; live opacity slider + Reset section preserved (planner caught CONTEXT.md over-broad scope, narrowed Plan 01 to STROKE + zoom only). Inline disposition comment block extended at removal site per INV-01 pattern. Commits `3629ec04` (surface deletion) + `3e48d331` (i18n cleanup, 5 keys × 4 locales = 20 entries) + `e8748d9b` (vitest cleanup + Test 14 regression pin with 5 positive-form `queryBy*` assertions) + `567c701e` (WR-01 orphan vi.mock inline fix).
- **EMRG-FN-02 orphan i18n key cleanup.** `settings.toggleWidget` removed from all 4 locales (en/de/es/fr builder.json). Commit `205e5a70`.
- **EMRG-FN-03 unused-eslint-disable removal.** 2 unused `eslint-disable-next-line react-hooks/exhaustive-deps` directives removed from `UnifiedStackPanel.tsx` at actual lines 735+776 (planner-time grep caught line drift from REQUIREMENTS-cited 679+720). ESLint clean on file. Commit `a299f5ee`.
- **EMRG-FN-04 SublayerConfigIndicators null close-out.** Docstring extension to existing Test 1 documents the live `layer={null}` contract; CONTEXT.md auto-resolution claim was wrong (planner caught + Plan 06 corrected). No production code change. Commit `06fbe98f`.
- **CTRL-01 close gate.** typecheck 0 / vitest 1979/1979 / e2e:smoke:builder 26/26 / i18n parity 2/2. CHANGELOG `[Unreleased]` v1011.1 block populated (Removed / Changed / Internal). Inline code-review fix applied (WR-01 orphan `vi.mock('../StyleColorPicker')` factory deleted; Plan 03 had explicitly deferred as "orphaned but harmless"). Local `v1011.1` tag at `567c701e` (moved from `017af020` after WR-01 fix). Commits `e1d3d093` + `017af020` (CHANGELOG backfill) + `567c701e` (WR-01).
- **Live Playwright MCP re-verify.** Orchestrator drove against 5/5-healthy `localhost:8080` stack — basemap sublayer editor: STROKE/CASING/ZOOM ABSENT ✓, opacity slider PRESENT ✓, Reset section PRESENT ✓, sublayer rows render cleanly with `layer={null}` (no artifacts) ✓; 0 console errors ✓.

**Patterns reinforced (not new):**

- **Hygiene-shape carryforward milestone** — 4 EMRG-FN findings closed in 1 phase + 7 sequential plans + 1 CTRL-01 batched close gate; same shape as v1009.1 / v1010.1 / v1010.2 / v1011 per `feedback_hygiene_milestone_pattern.md`.
- **Planner-time grep gate catches CONTEXT.md inaccuracies** — the planner caught 3 errors in CONTEXT.md before execution started (Plan 01 scope over-broad; EMRG-FN-04 auto-resolution claim wrong; EMRG-FN-03 line numbers drifted). Defending against pre-execution context drift via source-truth grep is the established pattern.
- **Post-shipping code review catches secondary findings** — even a tightly-scoped REMOVE phase produced 1 WARNING + 1 INFO; the WARNING was an orphan vi.mock block that Plan 03 explicitly deferred. Per `feedback_review_findings_inline.md`, the fix landed inline (and the tag moved) rather than waiting for v1011.2.
- **Live Playwright MCP re-verify as pre-tag gate** — orchestrator-scoped MCP verify on `localhost:8080` is the appropriate proof for REMOVE-disposition claims; vitest JSDOM-render confirms component-level absence but live MCP confirms the production page never paints the removed surface.

**Milestone close:** 5/5 requirements satisfied; single phase (1052), 7 plans, 15 commits 2026-05-18 (8 source + 7 docs/state + 1 inline review fix). Smoke gate: typecheck 0 / vitest 1979/1979 / e2e:smoke:builder 26/26 / i18n parity 2/2. Live MCP re-verify 6/6 surface checks pass. Audit: PASSED (5/5 must-haves). Tag `v1011.1` local at `567c701e`. Zero v1011.2 deferrals.

## Recent Shipped Milestone: v1011 Map Builder Polish & Bug Sweep

**Shipped:** 2026-05-18

**Goal delivered:** Closed 11 user-reported Map Builder polish/bug items (5 broken affordances, 3 small-screen layout collisions, 3 UX decisions, 1 investigation-then-decision) via Playwright MCP inspect-verify-fix loop on live `localhost:8080` stack; triaged emergent issues found in flight (EMRG-01: 0 fix-now, 4 P2-defer); resolved INV-01 DETAIL LEVEL toggle disposition (REMOVE — dead-wired since v1008).

**Delivered:**

- **BUG-01..03 — Layer affordance contract fixes.** Adapter-contract fix at fill/line/circle/heatmap-adapter.addLayers (honor `input.visible` at initial add) + defense-in-depth `syncVisibility` at every non-sync re-add caller (commit `8c6de63`). `handleRemove` gains optimistic state update + rollback pattern lifted from `handleBulkDelete` (commit `eeeb8be8`). Radix DropdownMenu rename input wins `restoreFocus` race via rAF-deferred focus + dropping `_e.preventDefault()` from `onSelect` (commit `80bddc14`).
- **UX-01..02 — Sublayer UX clarity.** Group-row expand carets meet 24×24 px hit target with Lucide ChevronRight glyph (`-mx-1` negative-margin overflow extends hit-box within locked grid; commit `278e8933`). New `SublayerConfigIndicators` pure-derivation component renders up to 4 badges (Labels/Filter/DataDriven/OpacityModified); per-sublayer opacity slider removed (commits `79b0c0c6` + `a69d00ac`).
- **UX-03 — Basemap row draggable.** `BasemapGroupRowWrapper` lifted `useDroppable` → `useSortable`; `MapBasemapConfig.basemap_position: 'top' | 'bottom'` jsonb-additive (zero backend migration); new `reorderBasemapAboveData(map, position, sourcePrefix)` map-sync helper inverts MapLibre layer order when basemap is at top; `MapBuilderPage.handleDragEnd` detects basemap drag BEFORE `arrayMove` (commit `0957cf6d`).
- **UX-04 — Map Settings widgets.** State-specific aria-labels ("Enable {{name}}" off / "Disable {{name}}" on) replace composite template + availability note paragraph. Duplicate-controls audit found 0 actual duplicates (commit `57d88d01`).
- **RESP-01..03 — Small-screen resilience.** MapLibre `NavigationControl` repositioned `position="top-right"` → `position="top-left"` (commit `391459bb`). `MapCoordReadout` docstring extension codifies cross-context `right-14` load-bearing offset (builder NavigationControl top-left ↔ viewer top-right asymmetry; commit `c6ab4fbd`). Both `<SheetContent>` instances in `MapBuilderPage.tsx` gain `showCloseButton={false}` opt-out; 8 regression tests including a NEGATIVE-CONTROL bug-shape pin (commit `0a72cb58`).
- **INV-01 — DETAIL LEVEL removed.** Investigation confirmed dead wiring since v1008. REMOVE disposition over FIX. 7 files changed (+28/-153); 6 i18n keys × 4 locales = 24 entries cleaned; new Test 13 as regression pin (commit `6078b82a`).
- **EMRG-01 — Emergent triage.** FINDINGS.md with 4 P2-defer findings (Phase 1038 sibling dead-stubs → new pending todo; 3 minor cleanups → SUMMARY cross-references); orchestrator MCP backlog appendix table aggregated for CTRL-01 (commit `60b0f536`).
- **CTRL-01 — Close gate + 2 inline fixes.** Inline gate-fix `befe6a3b` for Plan-06-introduced dnd-kit collision regression (basemap-group `useSortable` lift made it a `closestCenter` collision target during catalog drags) via `useDndContext()` + `disabled: { droppable: <derived from active.data.source> }`. RESP-02-FOLLOWUP `4f4a9917` for boundary regression at 800px (NavigationControl ↔ MapCoordReadout overlap) via `data-builder-canvas` CSS scope + 32px margin-top — ViewerMap unaffected by attribute scoping.

**Post-shipping code review (21 findings — all fixed inline):**
- **iter-1 (17 findings):** 4 CR (CR-01..04) + 9 WR (WR-01..09) + 4 IN (IN-01..04). Highlights: CR-04 stored heatmap-opacity at add-time instead of hard-coded 0.8; CR-02 suppress basemap row click during multi-selection; WR-04 use state mirror for map instance; WR-08 include `dataset_table_name` + heatmap/height fields in structuralKey.
- **iter-2 (4 findings):** 2 WR (WR-01 single-writer heatmap-opacity contract + WR-02 regression tests) + 2 IN (IN-01 rename `structuralKey` → `popupInvalidationKey` + IN-02 6-test unit coverage for CR-04 + WR-01 compounding contract).

**Milestone close:** 13/13 requirements satisfied; single phase (1051), 13 plans, 65 commits 2026-05-17 → 2026-05-18 (75 files changed, +10,314 / −372). Smoke gate: typecheck 0; vitest 1981/1981 (builder 982/982); e2e:smoke:builder 26/26; i18n parity 2/2. Live Playwright MCP re-verify 11/11 PASS + v1010.2 SF-04..08 spot-check + RESP-02-FOLLOWUP fixed inline. Audit: PASSED (derived from Phase 1051 VERIFICATION.md). Tag `v1011` local.

**Patterns established (8 new):**
- **Sortable disabled.droppable per-drag-source contract** — sortable participant invisible to collision detection ONLY during a specific drag-source context uses `disabled: { draggable: false, droppable: <derived from useDndContext().active.data.source> }` rather than conditionally registering/unregistering.
- **Stack-restart vs `down -v` decision tree** — `restart api worker frontend` if pgdata holds work AND phase touched only frontend (volume-mounted) or Python without migration; use `down -v && up -d --build` only when backend images must be recomputed OR migrations need a clean DB.
- **Resolution-by-upstream-wave** — when a prior wave's pure-positioning fix already eliminates a downstream wave's stated collision surface, the downstream wave ships docstring/cross-reference work to prevent regression rather than redundant CSS.
- **Cross-context offset contracts codified at the shared component** — for shared components used by multiple parents that diverge on a co-positioned control, the docstring at the shared component is the only place the contract survives parent refactors.
- **Defer-with-cross-reference** — when a finding is trivial enough that a separate todo would be overhead, the SUMMARY-section cross-reference is the durable tracking artifact.
- **jsonb-additive persistence** — when storage is opaque jsonb, add an optional field rather than introducing a backend migration.
- **Inline disposition documentation at removal site** — comment block immediately above the affected interface so a future maintainer who greps for the removed surface finds the WHY before WHERE.
- **Removed-feature regression pin** — delete the surface AND add a single positive-form `queryBy*` assertion that the surface stays gone; low-cost, prevents accidental cargo-cult re-introduction from sibling editor scenes.

## Recent Shipped Milestone: v1010.2 Builder Smoke Carryover

**Shipped:** 2026-05-17

**Goal delivered:** Closed all 5 v1010.1 carried-forward smoke findings (SF-04 dedupe MapLibre sources, SF-05 blob revoke timing, SF-06 anonymous pre-auth probes, SF-07 double initial thumbnail PUT, SF-08 false-positive basemap toast). Map Builder ships clean of all 2026-05-17 smoke noise.

**Delivered:**
- **SF-04 / SMOKE-08 — Dedupe MapLibre vector sources (P1).** `getSourceIdForLayer(layer)` helper in `frontend/src/components/builder/map-sync.ts:374` keys non-cluster vector sources by `dataset_table_name`; cluster sources stay per-layer via `source-cluster-{id}`. Rewired 5 call sites in `use-builder-layers.ts` + 4 in `use-layer-map-sync.ts` through the helper. Playwright MCP confirmed: 24 unique tile URLs for 2-dataset map (no per-layer duplication). Commits `cab57a32`, `c1c84cc7`.
- **SF-05 / SMOKE-09 — Defer blob URL revoke (P2).** `useEffect` cleanup in `frontend/src/components/maps/hooks/use-map-thumbnail.ts:45-50` defers `URL.revokeObjectURL()` until data change or unmount. Mirrors `use-quicklook.ts:67-74` analog. 0 `blob:` errors on post-login redirect confirmed. Commit `4473d21e`.
- **SF-06 / SMOKE-10 — Gate anonymous pre-auth probes (P2).** `useSavedSearches` gated on `!!token`; `useAIStatus` + `useEmbeddingStats` consumer-gated with `{ enabled: !!token && isAdmin }` in both `AIStatusCard.tsx` and `SettingsAITab.tsx`. 0 401-noise on anonymous `/login` confirmed. Commits `912458e8`, `aca42c99`, `d6b0b9c6`.
- **SF-07 / SMOKE-11 — Single thumbnail PUT on mount (P2).** Module-level `autoCapturedMapIds: Set<string>` + `shouldAutoCapture()` predicate at `frontend/src/components/builder/hooks/use-builder-save.ts:155, 184` survives Vite StrictMode hook unmount/remount. vitest `use-builder-save.test.ts` SF-07 case verifies double-fire is gone. Commit `37fee435`.
- **SF-08 / SMOKE-12 — Basemap toast latch (P2).** `basemapLoadedAtRef` latch at `frontend/src/components/builder/BuilderMap.tsx:91`; set on first successful style load (line 161), checked in `errorHandlerRef` at line 417 (narrowed to 3000ms save-flow window post-WR-02 fix). Preserves toast for actually-broken basemaps. vitest 3/3. Commits `9fe0b4ec`, `0f0290ba`.

**Post-shipping code review (3 BLOCKER + 4 WARNING — all fixed inline):**
- CR-01: `waitForVisibleLayerSources` polled legacy `getSourceId(layer.id)` → 5s thumbnail upload latency after dedupe (`516c9ae5`)
- CR-02: `BuilderMap.tsx:765` token-refresh `setTiles` legacy lookup → vector layers 401 ~1hr into session (`fd149688`)
- CR-03 + WR-04: `useEmbeddingStats` was ungated, even after SF-06 gated `useAIStatus` (`d6b0b9c6`)
- WR-01: `removeStaleSourcesAndLayers` companion-layer leak from dedupe-keyed source ids (`8b791a08`)
- WR-02: SF-08 latch permanent-suppression too wide → narrowed to 3000ms save-flow window (`0f0290ba`)
- WR-03: misleading comment about `autoCapturedMapIds` navigation cleanup that doesn't exist (`0451657f`)

**Milestone close:** 5/5 SMOKE-08..12 requirements satisfied; single phase (1050), 6 plans, 9 tasks. Smoke gate: typecheck 0; vitest 1913/1913 (+4 regression tests from code-fix loop); `e2e:smoke:builder` 26/26; Playwright MCP re-verify 5/5 SF surfaces + 3/3 v1010.1 regression checks against live 5/5-healthy stack. Audit: PASSED (11/11 must-haves).

**Lesson reinforced:** Post-implementation code review caught 7 secondary findings that the planner's deep_work rules didn't pre-empt — the SF-04 dedupe contract leaked outside `map-sync.ts` to 3 callers (`use-builder-save`, `BuilderMap` token-refresh, `removeStaleSourcesAndLayers`), and SF-06 gating gap missed `useEmbeddingStats` because the plan named only `useAIStatus`. The `feedback_review_findings_inline.md` "default to fixing all inline" pattern was the right call — these would have been v1010.3 carryforward otherwise.

## Recent Shipped Milestone: v1010.1 Live Playwright MCP Smoke

**Shipped:** 2026-05-17

**Goal delivered:** Fresh-stack interactive Playwright MCP smoke check against v1010's headline win surfaces caught and fixed 2 P0 + 1 P1 regressions before they shipped to users.

**Delivered:**
- **SF-01 (P0) — Bulk-delete UI completely unreachable.** Root cause: `UnifiedStackPanel`'s POL-10 outside-click guard treated mousedown inside the BulkActionBar as "outside the listbox" (`stackPanelRef` only scopes the inner `<div role="listbox">`). The bar cleared `selectedIds` on confirm-click mousedown and unmounted via the `size >= 2` gate before React's click handler could dispatch `onBulkDelete(selectedIds)`. Fix: extend guard's in-bounds check with `data-bulk-action-bar` marker; mirrors the SP-01 (Phase 1045) hatch for the Radix DropdownMenu portal. v1010 PERF-03 batched delete restored (commit `c4576717`).
- **SF-02 (P0) — Render-mode swap Line→Arrow MapLibre validation errors.** Root cause: `LayerEditorPanel`'s "Render as" chip row unsafely cast `option.id as 'points' | 'heatmap' | 'symbol' | 'cluster'` even though the underlying union is `RenderAsId`. `handleRenderModeChange` fell through to its default circle-adapter branch for `arrow`, leaking `line-cap`/`line-join` layout keys into a circle-layer addLayer call. Fix: widen prop type, drop cast, route non-circle modes through `handleRenderAsChange` + `buildRenderAsPatch()` (commit `8713b73f`).
- **SF-03 (P1) — StyleJsonDialog defective `lazy()`.** Root cause: `MapBuilderPage` rendered the dialog inside `<Suspense>` unconditionally (gated only on `id` truthy, not on `showStyleJson`). React.lazy resolved the import on mount because the component itself was mounted. Fix: gate render on `{id && showStyleJson && (...)}` — chunk now fetches on first dialog open, aligning with the other 4 lazy scenes (commit `3df84554`).
- **SF-04 (P1) — Duplicate tile sources per layer.** Deferred-with-rationale: refactor exceeds 1hr budget and touches multiple test surfaces (`swapLayerOnMap`, `removeSource`, cluster-source override, dataset token signing). Tracked as `BUILDER-PERF-DEDUPE-SOURCES` tech-debt.
- **SF-05/06/07/08 (P2 polish noise):** thumbnail blob `ERR_FILE_NOT_FOUND` after login, anonymous pre-auth probes to authed endpoints, 2× initial-load `PUT /thumbnail/`, false-positive "Basemap connection issue" toast on save — all bundled into a future hygiene sweep.

**Milestone close:** 7/7 SMOKE-0X requirements satisfied; single phase (1049), 1 plan, 11 tasks. Post-fix re-smoke verified all 3 inline fixes in the same Playwright session. Backend `bulk-delete` endpoint regression-checked via direct fetch (`200 + {deleted:[3 ids], failed:[]}`). 5/5 v1010 win surfaces confirmed working post-fix.

## Recent Shipped Milestone: v1010 Builder Performance & Code Quality

**Shipped:** 2026-05-16

**Goal delivered:** Improved Map Builder performance under load and locked in code-quality wins via an audit-first sweep, while clearing three carried-forward builder follow-ups.

**Delivered:**
- **Performance (6 axes):** MapBuilderPage entry chunk 281.76 → 233.10 KB (-17.3%) via 6 lazy-loaded editor scenes; opacity slider 100ms debounce + color picker / filter editor 200ms debounce + `coalesceFrame` rAF utility collapses paint updates to 1 MapLibre repaint per animation frame; `POST /api/maps/{id}/layers/bulk-delete` batches 50 sequential deletes into 1 HTTP call (-98%); PERF-02 hover p50=4.9ms (target ≤30ms — 6× margin); cold vite build 364ms; vitest builder 951/951 in 5.66s.
- **Code quality (24-finding audit closeout):** LayerStyleEditor.tsx 1231 → 468 LOC (-62%) via per-render-mode sub-components + RenderModeSwitch lookup-table (closes CB-07 + CD-19); `syncLayerFilter` + `setLayerProperty` helpers extracted to layer-adapters/shared.ts (closes CA-01 + CA-03); all 24 BUILDER-CODE-AUDIT findings dispositioned (P0=3 shipped, P1=14 shipped or deferred-with-rationale, P2=7 deferred).
- **Three carried-forward follow-ups (FOLLOWUP-01..03):** Invalid `popup_config` now surfaces actionable error toast with layer name + backend 422 translation (e2e round-trip test passes); Add Data modal audit shipped (13 findings; 0 P0; v1008 unified-stack alignment ALIGNED); SourcesTab `it.todo` backlog drained from 8 → 0 (9 live vitest cases shipped, backlog file deleted).
- **Closeout (CLOSE-01..02):** 7/7 smoke gates PASS — typecheck clean, vitest 1887/1887, e2e:smoke:builder 26/26, e2e:smoke:perf live, backend pytest test_maps_bulk_layers 8/8, backend ruff 0 errors, i18n parity (en/de/es/fr 781 keys); CHANGELOG.md `[Unreleased]` populated with measured numbers + Internal section referencing audit deliverables.

**Milestone close:** 17/17 requirements satisfied across phases 1046-1048 (3 phases, 12 plans). Audit: passed / GO. 11 Info-level findings deferred to future builder polish cycle as tech debt. See `.planning/milestones/v1010-ROADMAP.md` and `.planning/milestones/v1010-MILESTONE-AUDIT.md`.

## Recent Shipped Milestone: v1009.1 Builder Smoke Polish

**Shipped:** 2026-05-15

**Goal delivered:** Closed 17 non-B-01 findings from the 2026-05-15 Map Builder Playwright smoke check. B-01 (live-add maplibre sync regression) shipped ahead of milestone open at commit `85738f1c`. Restored most of the v1009 multi-select + UI/UX polish promises the smoke check exposed, plus low-cost backend / a11y hygiene wins.

**Delivered (16/18 PASS):**
- BLOCKER — BulkActionBar Group/Ungroup/Delete reachable via Lucide `MoreHorizontal` overflow popover
- MAJOR — coord readout subscribes to MapLibre `move`; shift-click range-select via `computeNextSelection` helper; "Pending preview" banner gated on deep-equal dirty state
- MINOR — duplicate Saved badge removed; TanStack 60s staleTime for ai-status; auth refresh mutex routed through `tryRefresh`; aria-pressed on visibility toggles; `/auth/login` decorator now no-trailing-slash
- POLISH — basemap eye is non-button glyph with tooltip; row hover affordance via Tailwind classes; bulk bar hides during global Settings; thumbnail PUT 500ms trailing debounce; Lucide `<Plus />` icon replaces full-width "＋"
- HOUSEKEEPING — test maps `a00b7e96-…` + `58149b92-…` deleted (DELETE 204 / GET 404 verified)
- REVIEWER — 4 cross-cutting code-review fixes applied inline (WR-02 inflightRefresh microtask race; WR-03 defensive Set copy; IN-02 redundant zoomend handler; IN-05 SP-11 docstring)

**Open followups (escalated/deferred):**
- **SP-03 / M-02 race** — B-01 fix at `85738f1c` did NOT fully close M-02. Live Playwright re-check confirms fresh-add still doesn't push source/layer into maplibre style until reload. Suspect `syncInputs` memo closure on `structuralKey`-only key OR `mapReady` timing on the second effect re-fire when tokens land. Workaround: refresh after add. Needs a quick task.
- **SP-07 first-request 404** — frontend `quicklook-cache.ts` prevents repeats but first request per session still 404s. Honest fix is a backend `has_quicklook` predicate. Needs a backend quick task.
- **SP-12 representative-fraction "1:N" pane** — MapLibre `ScaleControl` bar already on screen; the smoke checker's p-01 asked for a representative-fraction pane (small feature: cos-lat factor + UI slot in MapCoordReadout + i18n). New feature ticket if requested.

**Milestone close:** 18/18 reqs accounted for (16 PASS + 1 PARTIAL + 1 ESCALATE + 1 SKIPPED-with-rationale). 24 commits between `cf40075b..1168e91a`. Single phase (1045), 3 plans, single CTRL-01 batch gate. Tag `v1009.1` created locally.

## Recent Shipped Milestone: v1009 Map Builder v1.5 (Polish)

**Shipped:** 2026-05-15

**Goal delivered:** Polished the v1008 unified-stack Map Builder — drag-from-catalog into the stack, multi-layer selection / bulk ops, UI/UX sweep, and pre-existing builder test debt closeout.

**Delivered:**
- Drag-from-catalog-into-stack — drag a row from Add Dataset directly onto the unified stack to add a layer
- Multi-layer selection / bulk operations — shift-click / cmd-click to select multiple stack rows; bulk toggle visibility, opacity, group, ungroup, delete (note: BulkActionBar overflow clipping found in post-release smoke check + fixed in v1009.1 SP-01)
- General Map Builder UI/UX sweep — density, spacing, typography hierarchy, hover/focus states, microinteractions, component organization, information architecture, empty/error/loading states; 18 P0/P1 polish closures driven by Phase 1039 BUILDER-UX-AUDIT
- Builder test debt closeout — 5 pre-existing vitest failures fixed + `use-builder-layers.add-dataset` worker-timeout regression resolved

**Milestone close:** 25/25 POL-01..25 requirements satisfied across phases 1039-1044 (6 phases, 22 plans). Audit PASSED; 1 BLOCKER (B-01 freshLayerId wiring) found and fixed inline during audit. Smoke gate: typecheck 0 errors; vitest 799/799 + 54/54 pages; e2e:smoke:builder 25/25. Tag `v1009`. Subsequent 2026-05-15 Playwright smoke check exposed 17 follow-ups closed in v1009.1.

## Recent Shipped Milestone: v1008 Map Builder Sidebar Redesign

**Shipped:** 2026-05-14

**Goal delivered:** Re-architected the Map Builder sidebar from six fixed sections into one unified, drag-orderable layer stack with basemap-as-group, DEM-as-raster-layer, compact rows, and a side-by-side LayerEditorPanel flyout — without regressing existing maps.

**Delivered:**
- Unified drag-orderable layer stack (`UnifiedStackPanel` + `StackRow`) replacing `MapStackPanel` / `MapStackSection` / `LayerItem`.
- Basemap as a collapsible folder-group row (`BasemapGroupRow`) with sublayer expansion, plus the basemap-group editor scene flyout.
- DEM treated as a regular raster layer with `render as: image | hillshade | terrain` property, replacing the dedicated Relief section.
- 380px `LayerEditorPanel` flyout with collapsible Filter / Labels / Source sections in place of per-tab navigation; drill-down `Sheet` overlay at `<800px`.
- `⚙ Settings` affordance for terrain global config, map widgets, and projection via the `SidebarRail`.
- Saved-map normalizer that promotes legacy six-section JSON to flat-stack + group-metadata shape without regressing public/shared/embed viewers.
- Catalog-first empty state with shared `EmptyStackState` component and curated suggestions.
- Smoke-test sweep deferred at milestone close shipped post-close via quick task `260514-ajo` (rewrote 8 builder tests, deleted 4 obsolete tests, fixed `SidebarRail` event-as-`initialQuery` bug). Builder smoke is now 21/21 green and `LayerPanel.tsx` / `LayerItem.tsx` dead code removed.

**Milestone close:** 27/27 BSR-01..27 requirements satisfied across phases 1033-1038 (6 phases, 16 plans). UAT 9/9 PASS. `tech_debt` audit accepted at close.

## Recent Shipped Milestone: v1007 Release Hygiene

**Shipped:** 2026-05-12

**Goal delivered:** Close release hygiene after v1006 by proving dependency/security state, generated artifacts, stack health, smoke coverage, Playwright MCP browser health, and temporary data cleanup.

**Delivered:**
- Verified Dependabot `urllib3` alerts against `backend/pyproject.toml`, `backend/uv.lock`, `uv lock`, and `pip-audit`; local state is scanner-clean at `urllib3==2.7.0`, and stale GitHub alerts #36/#37 were dismissed with evidence.
- Ran backend ruff/format/bandit/pip-audit/full pytest coverage and frontend i18n/changed namespace/lint/typecheck/coverage.
- Regenerated `backend/openapi.json` plus Python and TypeScript SDK artifacts for the v1006 cluster tile route and shared-layer `id`.
- Fixed Docker Compose frontend health by using IPv4 loopback in the Vite healthcheck.
- Made collections smoke self-seeding and cleanup-driven instead of relying on optional seeded catalog data.
- Passed root Playwright smoke and Playwright MCP live search console verification after removing temporary UAT/smoke datasets.

**Milestone close:** 10/10 requirements satisfied in Phase 1032. Audit: passed / GO. See `.planning/milestones/v1007-ROADMAP.md` and `.planning/milestones/v1007-MILESTONE-AUDIT.md`.

## Recent Shipped Milestone: v1006 Large Dataset Cluster Scaling

**Shipped:** 2026-05-12

**Goal delivered:** Extend v1005 Point Cluster from bounded client-side GeoJSON datasets to large point datasets by adding a server-side clustered tile/source path, preserving existing saved-map and renderer controls, and adding cluster exploration interactions.

**Delivered:**
- Server-side cluster tile/source contract for large vector point datasets that reuses existing vector tile auth, embed-token, API-key, and cache patterns.
- Builder eligibility and map-sync routing that choose bounded GeoJSON clustering for small datasets, server-side cluster tiles for large datasets, and Point fallback for unsupported states.
- Unified Cluster authoring controls across bounded and server-side cluster sources with no new persisted map or layer fields.
- Cluster exploration interactions: zoom/expand on cluster activation, aggregate popup/summary, accessible pointer/keyboard/touch behavior, and clear row/legend fallback states.
- Style JSON export metadata documenting bounded/server/fallback cluster strategy while standalone output keeps a documented point/vector fallback.
- Performance and browser QA against a synthetic 6,001-feature large point dataset, including signed private server-cluster tile URLs and clean Playwright MCP console evidence.

**Milestone close:** 25/25 requirements satisfied across Phases 1027-1031. Audit: passed / GO. Focused Vitest, backend pytest, i18n, lint, build, ruff, builder smoke, and Playwright MCP live large-dataset UAT passed. See `.planning/milestones/v1006-ROADMAP.md` and `.planning/milestones/v1006-MILESTONE-AUDIT.md`.

## Recent Shipped Milestone: v1005 Builder Point Cluster Foundation

**Shipped:** 2026-05-12

**Goal delivered:** Ship Point Cluster safely for eligible point datasets by proving a bounded GeoJSON source path, preserving saved-map compatibility, and falling back cleanly when clustering is not supported.

**Delivered:**
- Eligibility rules expose Cluster only for bounded vector point datasets whose metadata and source path can be handled safely.
- Bounded GeoJSON cluster source loading works in builder, public, shared, and embed viewer contexts without replacing the vector-tile default.
- MapLibre-native cluster layers render count labels and unclustered points while preserving opacity, visibility, filter, zoom range, reorder, removal, and stale-cleanup lifecycle parity.
- Builder Cluster controls cover radius, max zoom, color, count color, and count text size using existing primitives and i18n keys.
- Existing-field renderAs writes remain under `style_config.render_mode` / `style_config.builder`, with no schema migration and no `is_3d` writes.
- Style JSON export/import preserves cluster intent metadata and uses a documented Point/vector-tile fallback for standalone styles where authenticated GeoJSON cannot be embedded.
- Viewer timing coverage ensures shared/public/embed cluster layers resync once bounded GeoJSON data arrives.

**Milestone close:** 20/20 requirements satisfied across Phases 1023-1026. Audit: passed / GO. Focused Vitest, backend pytest, i18n, lint, build, ruff, builder smoke, and Playwright MCP live save/reload/console verification passed. See `.planning/milestones/v1005-ROADMAP.md` and `.planning/milestones/v1005-MILESTONE-AUDIT.md`.

## Prior Shipped Milestone: v1004 Builder Renderer Expansion

**Shipped:** 2026-05-12

**Goal delivered:** Add the next Map Builder render modes through a deliberate renderer capability layer, shipping MapLibre-native wins first and making any deck.gl/H3/trips dependency decision explicit before implementation.

**Delivered:**
- Renderer capability registry with geometry, record type, backend, source requirement, writable-field policy, companion-layer policy, viewer support, and style JSON support metadata.
- `Arrow` as the only new v1004-visible renderAs option, scoped to vector line layers and stored in existing `style_config.render_mode` / `style_config.builder` fields.
- MapLibre icon-backed arrow companion symbol layers that follow parent visibility, opacity, filter, zoom range, reorder, stale cleanup, and removal.
- Builder style controls for arrow color, size, and spacing using existing UI primitives.
- Backend style JSON export/import round-trip and built-in sprite support for arrow renderer intent.
- ADRs deferring Cluster, Hexbin, H3, Animated path, and Point 3D extrusion until their data-shape, dependency, viewer, and saved-map contracts are explicit.

**Milestone close:** 20/20 requirements satisfied across Phases 1019-1022. Audit: passed / GO. Focused Vitest, backend pytest, i18n, lint, build, ruff, Playwright MCP browser inspection, and builder smoke passed. See `.planning/milestones/v1004-ROADMAP.md` and `.planning/milestones/v1004-MILESTONE-AUDIT.md`.

## Recent Shipped Milestone: v1003 Builder v1 Hardening

**Shipped:** 2026-05-12

**Goal delivered:** Prove and harden the v1002 Map Builder layer sidebar and Add Dataset redesign through durable browser, accessibility, and round-trip coverage without schema changes, new renderers, or new catalog/import capabilities.

**Delivered:**
- Browser-backed regression coverage for the redesigned builder shell, Map Stack row anatomy, Add Dataset modal, tablet sidebar clamp, and scoped accessibility checks.
- Duplicate-rendering coverage from both row overflow and Add Dataset modal entry points, with independently configurable sibling layers.
- RenderAs contract coverage proving v1 modes patch only existing writable fields and never write `is_3d`.
- Basemap and terrain hardening proving writes remain on `basemap_style`, `show_basemap_labels`, `basemap_config`, and `terrain_config`.
- Add Dataset state coverage for tabs, existing API filters, Add/added/another-rendering, row expansion, import routing, and basemap swap/in-use states.
- Saved-map, public-viewer, and shared-viewer compatibility coverage for duplicate renderings, zoom range, basemap config, and terrain config.

**Milestone close:** 24/24 requirements satisfied across Phases 1014-1018. Audit: passed / GO. Builder smoke, focused Vitest, scoped accessibility checks, lint, build, and Playwright MCP verification passed. See `.planning/milestones/v1003-ROADMAP.md` and `.planning/milestones/v1003-MILESTONE-AUDIT.md`.

## Recent Shipped Milestone: v1002 Layer Sidebar + Add Dataset Redesign

**Shipped:** 2026-05-12

**Goal delivered:** Redesign the Map Builder layer sidebar and Add Dataset workflow over the existing Map/MapLayer/Record/Dataset schema, with zero migrations and no new rendering capabilities.

**Delivered:**
- Frontend-only renderAs and stack view-model foundation with no persisted group model.
- Layer row redesign with drag, visibility, geometry swatch, display name, `as <renderAs>`, opacity, zoom range, overflow actions, and dataset-rendering headers.
- RenderAs mutation paths and duplicate-rendering actions over existing `layer_type`, `style_config`, `paint`, `layout`, and add-layer handlers; `is_3d` remains read-only.
- Inline basemap and terrain rows that write only `basemap_style`, `show_basemap_labels`, `basemap_config`, and `terrain_config`.
- Add Dataset modal rewrite with All/Vector/Raster/Basemap tabs, existing API filters, row expansion, Add/added/another-rendering states, basemap swap/in-use states, and ImportPage routing.
- Focused QA coverage for renderAs, grouping, duplicate renderings, basemap/terrain writes, modal states, and Playwright spec coverage for sidebar/modal browser checks.

**Milestone close:** 37/37 requirements satisfied across Phases 1008-1013. Audit: `tech_debt` because live Playwright execution was blocked at archive time by an unavailable local stack/Docker runtime. Post-archive QA on 2026-05-12 passed builder smoke, focused accessibility, lint, build, and Playwright MCP manual checks; it also landed `003a03ea` to cap persisted tablet sidebar widths while preserving desktop preferences. See `.planning/milestones/v1002-ROADMAP.md` and `.planning/milestones/v1002-MILESTONE-AUDIT.md`.

## Prior Shipped Milestone: v1001 Map Builder UI/UX Polish Sweep

**Shipped:** 2026-05-11

**Goal delivered:** Make the Map Builder feel coherent, efficient, and trustworthy across the full create/edit/style/preview/share workflow on desktop, tablet, and mobile.

**Delivered:**
- Broad workflow sweep across create/edit/style/preview/share paths, including empty/loading/error/saved/dirty states.
- Inspector and Map Stack polish that reduces density, clarifies hierarchy, and keeps layer/style/basemap/relief controls predictable.
- Save/share/public-output parity for stable layer identity and publication state.
- Auth shell, mobile sheet, touch target, copy, i18n, and basemap recovery hardening.
- Durable QA coverage for polished builder flows: focused Vitest, builder Playwright, builder/public accessibility, and builder smoke without the sidebar drag-handle flake.

**Functional reference:** Use Kepler.gl as a guide for how builder functionality should behave - especially layer workflow, filtering, interactions, map settings, and save/export semantics - but do not copy Kepler.gl's visual style. GeoLens keeps its own product design language and MapLibre-based architecture.

**Milestone close:** 38/38 requirements satisfied across Phases 1002-1007. Audit: passed. See `.planning/milestones/v1001-ROADMAP.md` and `.planning/milestones/v1001-MILESTONE-AUDIT.md`.

## Recent Backlog Completion: v1000 Map Stack (shipped 2026-05-11)

**Delivered:** Unified Map Stack UX, normalized Surface/Relief/Basemap/Data/Labels/Interactions model, persisted curated `basemap_config`, explicit z-order policy, relief/terrain presentation polish, Playwright MCP visual QA evidence, public-viewer basemap rendering parity, and authenticated public DEM metadata preservation.

- Public shared-token and authenticated map viewers now pass persisted `basemap_config` into `ViewerMap`.
- `ViewerMap` reuses the builder `applyBasemapConfigToMap` transform with the `viewer-source-` managed-source prefix after load, `style.load`, and runtime config/label changes.
- `PublicMapViewerPage.toSharedLayer` preserves `is_dem` and `dem_vertical_units` so authenticated public saved maps keep DEM relief semantics before `ViewerMap`.
- Focused verification passed: `PublicMapViewerPage`, `ViewerMap.basemap-config`, `map-stack`, and frontend lint.

## Last Milestone (this repo): v13.13 Backlog Sweep (shipped 2026-05-07)

**Delivered:** 9 phases (271-279), 130/130 requirements satisfied, ~106 source-file commits — see [milestones/v13.13-ROADMAP.md](milestones/v13.13-ROADMAP.md) and [milestones/v13.13-MILESTONE-AUDIT.md](milestones/v13.13-MILESTONE-AUDIT.md).

- **154 deferred M+L v13.12 findings reorganized into 130 REQ-IDs and cleared.** Phases were domain-grouped: DB → Docker → Security → Performance → API/Docs → Code Quality → i18n/Env → Tests → Admin/Close.
- **Hybrid-shape milestone via `/gsd-autonomous` orchestration:** ~30 parallel `gsd-executor` agent spawns; planner agents per phase via `gsd-planner`. Reused the v13.12 audit-shape but with finer-grained per-domain phases.
- **Frontend wins:** map-vendor 1052kB chunk now off-route, DatasetPage 217kB → 34kB (-84%), AttributeTable virtualized for 10k+ rows, store relocation to `src/stores/`, builder i18n complete (zoomExpression + symbol + raster + hillshade + uploadIcon translated to es/fr/de — 135 strings).
- **Backend wins:** chat_service.py 1013 LOC decomposed into 5 sub-modules behind a Phase-226-style facade. 113 broad-except sites annotated. Architecture-guard 1500-LOC cap on routers + size-budget rule for AI sub-modules. `WORKER_SHUTDOWN_TIMEOUT` and `ENV_ONLY_CONFIG` migrated from raw `os.environ.get` to Pydantic Settings. `PUBLIC_BASE_URL` soft-deprecated.
- **Security wins:** SVG sanitization (defusedxml + CSP isolation), download-scoped JWT, origin-allowlist enforcement, SSRF re-validation on COG redirect, 32-byte share-token entropy, OAuth Referrer-Policy: no-referrer, SessionMiddleware https_only (prod), structlog field redaction, embed-iframe sandbox tightened, PIL.Image.verify() thumbnail gate.
- **API wins:** `POST /maps/import` typed body (no more `additionalProperties: true`), CHANGELOG `[Unreleased]` populated for v1.1.0 readiness, README counts/badges/build-time corrected, `docs/api-style.md` documents conventions.
- **Test wins:** Backend coverage gate 58.5 → 60. Frontend coverage thresholds ratcheted up across all 4 dimensions. 6 raw `waitForTimeout` calls in E2E specs replaced with deterministic locator polling. 35 inline `pytest.skip` calls migrated to decorator form.
- **Admin wins:** ApiKey `max_length=255` lock, audit-log search rewritten to `lower(unaccent(...))` form (uses pg_trgm GIN indexes from v13.12 Alembic 0010), AdminAuditPage page-guard, server-driven enterprise-tabs registry, audit-export format dispatcher unified, MinIO image bumped + sha256-pinned, non-blocking license-checker CI job added.
- **Deferred at close (4 items):** SEC-14 (CI carve-out for pip CVE-2026-6357 — runner image still ships pip 26.0.1, retry after pip 26.1 base-image refresh); SEC-07 + CODE-05 + TEST-10 Playwright MCP UAT visual confirmations (DOM-level substitutes + reviewer commands documented).

**Known close caveats:**
- ~10 commit-message attribution orphans from parallel-agent staging races (functional state at HEAD is correct; same race pattern as v13.12 Phase 269).
- Pre-existing typecheck error in `frontend/src/components/builder/__tests__/preserve-drawing-buffer.test.ts` from v13.13 Phase 274-06 (uses `node:fs`/`node:path` without `@types/node`). Vitest at runtime works fine. Surfaced/confirmed out-of-scope by ~6 plans across the milestone.
- `test_no_catalog_imports_processing` regex false-positive on a comment line in `service_public.py:186` — pre-existing on clean main, surfaced repeatedly out-of-scope.

## Prior Shipped Milestone: v13.12 Pre-Public Security & Audit Hardening (shipped 2026-05-07)

**Delivered:** 8 phases (263-270), 32/32 requirements satisfied — see [milestones/v13.12-ROADMAP.md](milestones/v13.12-ROADMAP.md).

- **17-audit sweep dispatched and consolidated** — 193 findings (2C / 37H / 83M / 71L) classified across security, infra, API, docs, perf, code, i18n, OSS dimensions; all sourced under `.planning/audits/v13.12/`.
- **All 39 Critical+High findings remediated inline** — 2 Critical (README seed-natural-earth bug; tile SQL no per-tile LIMIT) + 37 High closed across 4 parallel remediation agents in Phases 268-269. 5 new Alembic revisions (`0008..0012`). Boundary integrity remained A+/A+/A/A throughout.
- **154 Medium+Low findings deferred to backlog** — `.planning/backlog/v13.12-medium-findings.md` (83 M) and `.planning/backlog/v13.12-low-findings.md` (71 L) with rationale + target follow-up.
- **12 ingest/export/VRT lifecycle findings deferred to backlog (2026-05-19)** — `.planning/backlog/ingest-audit-20260519-findings.md` (4 P0, 8 P1, 10 P2 from `/ingest-audit`); full report at `docs-internal/audits/ingest-audit-20260519.md`. Proposed framing: **v1014 Ingest/Export Security & Lifecycle Hardening** (4 phases). Does not overlap with in-flight v1013 scope.
- **PUBLIC-READINESS.md committed at repo root** (commit `39fcb22b`) — composite grade **A−**, recommendation **CONDITIONAL-GO** with 3 deployment-scope conditions: (1) operators regenerate `JWT_SECRET_KEY` (H-28); (2) public repo recreation per `2026-05-05-recreate-public-repo-before-launch.md` todo; (3) CHANGELOG `[Unreleased]` populated and tagged v1.1.0 (H-02 PUT thumbnail body change).
- **Hybrid-shape milestone validated** — 4 audit-dispatch phases (263-266) with 17 parallel investigation agents → 1 triage phase → 2 remediation phases with 6 parallel fix agents → 1 verification phase. Total agents-orchestrated: ~24. Pattern reusable for future audit-driven hardening milestones.
- **Race-condition notes** — 3 commit-message orphan attributions in Phase 269 (H-04, SDK regen, H-16); functional state at HEAD is correct.

**Known close caveats:**
- Distribution & supply chain (DIST-01..04: Helm + SBOM + signed images + AMI) explicitly OUT OF SCOPE for v13.12 — recommend follow-up milestone for procurement-driven adopters.
- OSS launch posture (OSS-01..04) tracked separately at `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`.
- 176 standing deferred items acknowledged at close (175 cross-milestone `quick_tasks` + 1 pending todo).

## Earlier Milestone (this repo): v13.11 Map Builder Polish & Quality Sweep (shipped 2026-05-07)

**Delivered:** 5 phases (258-262), 6 plans, 17/17 requirements satisfied — see [milestones/v13.11-ROADMAP.md](milestones/v13.11-ROADMAP.md).

- **Phase 256 UI audit closure (BUILDER-POLISH-01) shipped** — gradient preview swatch (POLISH-01 BLOCKER) lands as a `data-testid="line-gradient-preview-swatch"` div with inline `linear-gradient(to right, ...)` style, gated to canonical-gradient mode only; per-row "Color" label noise removed (POLISH-02 — `label=""` in gradient mode); Solid/Gradient toggle gains focus ring + `cursor-pointer` (POLISH-03); advanced-expression disclosure spans full panel width (POLISH-04); each stop row carries a visible `pos` prefix span (POLISH-05); stable per-stop React keys via optional `id?: string` field on builder JSONB shape (POLISH-06 — canonical paint expression byte-identity preserved per v13.9 GRAD-05/06); trash button wrapped in shadcn `<Tooltip>` (POLISH-07).
- **Copy + i18n shipped** — `advancedHint` rewritten to drop "interpolate-linear-line-progress" jargon (COPY-01); real es/fr/de translations of the 16-key `lineGradient` block (COPY-02) — no English fallbacks remain in those locales for this block.
- **Builder quality sweep shipped** — orange `bg-warning` unsaved-changes dot on the Save button when there are uncommitted edits (QUALITY-01); `cursor-pointer` added to the shadcn Button cva base (propagates everywhere) plus 17 builder file native-button updates (QUALITY-02); single unguarded `console.warn` in `map-sync.ts` wrapped in `import.meta.env.DEV` guard — runtime console clean in production (QUALITY-03); BuilderMap NavigationControl moved bottom-right → top-right matching ViewerMap convention across public/share/embed surfaces (QUALITY-04).
- **Layer visibility debug + audit shipped** — `LabelEditor.handleToggle` no longer silently no-ops when `columns[0]` is unavailable; the Switch now disables with a tooltip when no columns exist (LAYER-01). Full audit of visibility code paths across LayerItem Eye toggle, LabelEditor Switch, syncLayersToMap, ChatPanel AI tools, removeStaleSourcesAndLayers, reorderDataLayers, hillshade companion, render-mode swap, and filter-changes — no other regressions surfaced (LAYER-02).
- **Close hygiene shipped** — MEMORY.md updated for BUILDER-POLISH-01 closure with full v13.11 milestone entry (CLOSE-01); `2026-05-07-phase-256-ui-audit-blocker-backlog-gradient-preview-swatch.md` moved to `.planning/todos/done/` with frontmatter `status: closed, shipped_in: v13.11` (CLOSE-02).
- **Hybrid-shape milestone validated** — Phase 258 ran the full skill chain (smart discuss → minimal UI-SPEC → plan-phase → execute-phase → code-review with WR-01 + IN-02 fixed inline → 258-VERIFICATION.md). Phases 259-262 ran inline with focused executor agents and direct edits. Each path produced a SUMMARY with per-REQ landing notes; full CI gate (`tsc --noEmit` exit 0, `eslint` clean, `vitest run` 1183/1183) green at every commit. Mixed-shape milestones are a viable extension of the v13.10 hygiene-shape pattern.
- **Formal milestone audit passed** — [v13.11-MILESTONE-AUDIT.md](milestones/v13.11-MILESTONE-AUDIT.md) records 17/17 requirements satisfied, 5/5 phases complete, 4/4 user-facing flows verified, no orphaned requirements. Tech debt: 3 deferred items (Phase 261 visual-UAT smoke-check recommended post-deploy, Phase 258 IN-03 mode-switch edge case, Phase 258 WR-02 strict parser).

**Known close note:** Phase 261 fix addresses the most likely root cause matching the user's "Label-Layer toggle not working" symptom (silent-no-op when `dataset_column_info` is empty). If a different scenario surfaces post-deploy, capture exact reproducer + affected dataset's column info to drive a follow-up.

<details>
<summary>Earlier milestone — v13.10 GH Issues Hygiene (shipped 2026-05-07)</summary>

**Delivered:** 1 phase (257), 3 plans, 8/8 requirements satisfied — see [milestones/v13.10-ROADMAP.md](milestones/v13.10-ROADMAP.md).

- **GH issue tracker reflects shipped reality** — All 11 open issues in `geolens-io/geolens` (#50-#59 builder + #97 sequencing tracker) closed with REQ-ID-citing comments verified against v13.8 (27/27) + v13.9 (19/19) milestone audits. Tracker #97 closed last with a summary linking each child closure path.
- **CTRL-01 batch confirmation gate** — A single batch summary presented before any `gh issue close` ran; user replied `approved` and only then did the 11 mutations execute. Closure log records per-issue `gh exit` codes (all 0).
- **Spot-checks confirmed three non-obvious closures** — #51 (style export/import — v13.9 byte-for-byte round-trip E2E flow PASS), #56 (terrain — NEW-INT-01 closure trail via commit `e46b96c6` and two `TestImportStyleJsonTerrain` regression tests), #58 (line paint properties — split across v13.8 LINE-01..02 and v13.9 GRAD-01..06 with both halves explicitly cited).
- **PROJECT.md refreshed** — `Active` set to placeholder; v13.10 added to chronological shipped list; `BUILDER-POLISH-01` (Phase 256 UI polish, now this milestone) and `OPS-01` (server-side map thumbnails) explicitly named in `Out of Scope` so future planning sweeps see them.
- **Hygiene-milestone shape validated** — One phase, three plans, zero new feature code, single batch confirmation as the only user input. Single-phase milestones are a viable pattern when scope is tightly coupled audit + closure + tracker refresh.
- **Formal milestone audit passed** — [milestones/v13.10-MILESTONE-AUDIT.md](milestones/v13.10-MILESTONE-AUDIT.md) records 8/8 requirements satisfied, 11/11 GitHub issues closed, 0 LEFTOVER, 0 UNCLEAR.

</details>

<details>
<summary>Earlier milestone — v13.9 Map Builder Closeout (shipped 2026-05-06)</summary>

**Delivered:** 5 phases (252-256), 13 plans, 19/19 requirements satisfied — see [milestones/v13.9-ROADMAP.md](milestones/v13.9-ROADMAP.md).

- **Architecture-guard regressions closed** — `catalog/maps/style_json.py` tile signing now routes through `CatalogPort` (CATPORT-02/04, LAYERING-01); `catalog/maps/router.py` imports `apply_layer_diff` from the `service.py` facade (BOUND-01, LAYERING-02); `catalog/maps/service_crud.py` 651 → 423 LOC after extracting layer-diff cluster into `service_diff.py` (BOUND-02, LAYERING-03). Full 20/20 `test_layering.py` architecture-guard suite green (LAYERING-04).
- **Nyquist VALIDATION.md backfill shipped** — six new `VALIDATION.md` files cover v13.8 Phases 246-251 with executable pytest/vitest selectors + grep gates (VALID-01..06). Single reviewer-runnable command `make validate-v13-8` runs 63 checks across 6 phases with fail-fast semantics, three-tier exit codes, and pre-flight API container detection (VALID-07).
- **SDK regen warning closed** — `PUT /maps/{map_id}/thumbnail/` switched from `text/plain` to JSON body backed by `ThumbnailUploadRequest`; `make sdks` now produces zero `openapi-python-client` warnings and ships `upload_thumbnail_maps_map_id_thumbnail_put.py` for the first time (SDK-01). Hard warning gate added to `make sdks` (fails on `^WARNING parsing` line); AST-based architecture-guard test pins the route shape so CI catches regression on every pytest run (SDK-02).
- **First-class line-gradient authoring shipped** — source-side `lineMetrics: true` lazy emission via `lineGradientNeededFor()` helper with sticky lifecycle (GRAD-01); style adapter expression-identity preservation through `addLayers` + `syncPaint` regression-locked at the `===` level (GRAD-04); MapLibre style JSON export emits `lineMetrics: true` with allowlist guard for unsupported source types (GRAD-05); JSON import round-trips paint + builder intent end-to-end with byte-identical re-emission (GRAD-06).
- **Builder UI for line-gradient shipped** — `LineGradientControls` component with Solid/Gradient mode toggle, color picker per stop, position input bounded `[0,1]`, add/remove affordances, and canonical interpolate-linear-line-progress round-trip parser (GRAD-02). Raw expression editor disclosure with parse + structural validation, Apply/Cancel commit semantics, and round-trip via shared parser — canonical hydrates stops, non-canonical preserves customExpression hint (GRAD-03).
- **Visual UAT via Playwright MCP** — Phase 256 verified live against MapLibre canvas; caught a cross-component closure-capture regression in `commitStops`/`updateBuilderConfig` wiring (`6c7b5b04`), fixed inline + locked behind two regression tests. Stronger close than mechanical-only verification.
- **Formal milestone audit passed** — [milestones/v13.9-MILESTONE-AUDIT.md](milestones/v13.9-MILESTONE-AUDIT.md) records 19/19 requirements satisfied, 7/7 cross-phase integration checks WIRED, 4/4 end-to-end flows complete, Nyquist compliant.

**Known close note:** Phase 256 UI audit (18/24) surfaced 1 BLOCKER (gradient preview swatch missing from authoring panel) + 6 minor recommendations (focus rings, `w-full` disclosure button, stable React keys, repeated "Color" labels). Non-functional polish; carry into next milestone if/when builder UX is rescoped. Phase 256 SECURITY.md analyzed 4 threats (raw expression injection, XSS, persisted style, runaway expression DoS) — all closed (2 mitigated, 2 accepted). Phase 256 UI polish backlog promoted to v13.11 (BUILDER-POLISH-01).

</details>

<details>
<summary>Earlier milestone — v13.8 Map Builder Advanced Styling (shipped 2026-05-06)</summary>

**Delivered:** 6 phases (246-251), 22 plans, 27/27 requirements satisfied — see [milestones/v13.8-ROADMAP.md](milestones/v13.8-ROADMAP.md).

- **Style state foundation shipped** — `MapLayer.paint` is now MapLibre-only; builder UI flags moved to documented `style_config` with row migration. `PATCH /maps/{map_id}/layers` incremental layer diffs with stable IDs landed alongside the OpenAPI + Python/TypeScript SDK contracts.
- **Advanced styling controls shipped** — first-class raster paint controls (with reset), line gap/blur/offset (`line-gradient` deferred to v13.9), zoom expression editor for `step`/`interpolate` stops on line/circle/label/opacity, and adapter preservation of expression-valued paint.
- **DEM hillshade and terrain shipped** — raster-dem source + 6-key hillshade paint allowlist + illumination/exaggeration/color controls. Map-level terrain config persists across builder, public viewer, and shared/embed surfaces.
- **MapLibre style JSON interop shipped** — full export/import round-trip for raster, DEM hillshade, terrain block, and outline/extrusion/label companions. Sprite-backed symbol/icon layers with upload/storage/serving.
- **Map edit history shipped** — durable backend event capture for committed saves, builder right-rail History panel, OpenAPI + SDK contracts refreshed.
- **Formal re-audit passed** — [milestones/v13.8-MILESTONE-AUDIT.md](milestones/v13.8-MILESTONE-AUDIT.md) records 27/27 requirements satisfied. v13.9 closed the inherited tech debt (architecture-guard regressions, VALIDATION.md backfill, openapi-python-client warning) and the deferred `line-gradient` authoring.

</details>

<details>
<summary>Earlier milestone — v13.7 Manifest-Driven Catalog Automation (shipped 2026-05-04)</summary>

**Delivered:** 5 phases (241-245), 18 plans, 19/19 requirements satisfied — see [milestones/v13.7-ROADMAP.md](milestones/v13.7-ROADMAP.md).

- **Manifest v1 contract shipped** — `geolens.yaml` now covers stable dataset identity, vector/raster/VRT sources, metadata, and Community-safe publication intent with fixtures and compatibility tests.
- **Offline CLI workflow shipped** — `geolens init` and `geolens validate` create and validate manifests locally with deterministic exit codes, path-specific errors, and import-boundary guards.
- **Backend apply workflow shipped** — `POST /ingest/manifest/apply` reuses existing auth, upload permission, storage validation, ingest jobs, catalog metadata, search, and map-preview contracts.
- **CLI apply and adoption docs shipped** — `geolens apply` and `--dry-run` support configured API workflows, public examples, and a first-catalog Docker Compose walkthrough.
- **Formal milestone audit passed** — [milestones/v13.7-MILESTONE-AUDIT.md](milestones/v13.7-MILESTONE-AUDIT.md) records 19/19 requirements satisfied, 19/19 integration checks, 6/6 verified flows, no orphaned requirements, and no critical gaps.

**Known close note:** The v13.7 audit does not claim full backend/frontend/E2E suite success. Focused manifest gates, contract drift checks, architecture guards, and the adoption path passed; remaining third-party deprecation warnings and the CLI raw-transport follow-up are nonblocking residual risks.

</details>

<details>
<summary>Earlier milestone — v13.6 Catalog Maps/Search Service Decomposition (shipped 2026-05-04)</summary>

**Delivered:** 5 phases (236-240), 18 plans, 21/21 requirements satisfied — see [milestones/v13.6-ROADMAP.md](milestones/v13.6-ROADMAP.md).

- **Maps service facade stabilized** — `backend/app/modules/catalog/maps/service.py` is now a thin public re-export surface over focused shared, CRUD, layer, and public/share modules.
- **Search service facade stabilized** — `backend/app/modules/catalog/search/service.py` is now a thin public re-export surface over focused filter, facet, collection, semantic, dataset, and OGC record modules.
- **Boundary guards added** — private maps/search split modules cannot be imported directly by external production modules, and size-budget checks guard against facade or private-module regrowth.
- **Contract tests hardened** — brittle VRT/search source-introspection checks now assert helper/facade behavior instead of inline implementation blocks.
- **Formal milestone audit passed** — [milestones/v13.6-MILESTONE-AUDIT.md](milestones/v13.6-MILESTONE-AUDIT.md) records 21/21 requirements satisfied, 21/21 integration checks, 7/7 verified flows, no orphaned requirements, and no critical gaps.

**Known close note:** Full backend coverage and Playwright smoke are not fully green locally; Phase 240 records exact outcomes and blockers. The focused v13.6-owned maps/search backend suite and touched-module lint/format gates passed.

</details>

<details>
<summary>Earlier milestone — v13.5 Enterprise Governance Seams (shipped 2026-05-03)</summary>

**Delivered:** 4 phases (232-235), 13 plans, 16/16 requirements satisfied — see [milestones/v13.5-ROADMAP.md](milestones/v13.5-ROADMAP.md).

- **PermissionExtension** — permission checks, catalog visibility filtering, and dataset detail access now route through a first-class platform extension with overlay tests and an architecture guard.
- **WorkflowExtension** — publication status endpoints and metadata `record_status` writes now route through a workflow extension that supports custom transitions, hooks, and states.
- **Advanced-sharing contract verified** — Community keeps basic share/embed behavior while custom embed lifetimes, origin restrictions, and expiring share links are gated consistently across schema, service, UI, API/OpenAPI, and GTM docs.
- **Post-impl close gate passed** — `docs-internal/audits/post-impl-20260503-v13-5.md` records Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings.
- **Formal milestone audit passed** — [milestones/v13.5-MILESTONE-AUDIT.md](milestones/v13.5-MILESTONE-AUDIT.md) records 16/16 requirements satisfied, no orphaned requirements, and no critical gaps.

**Known close note:** Full-suite merge readiness still belongs to normal CI/full-suite validation; the close audit used focused governance and architecture checks.

</details>

<details>
<summary>Earlier milestone — v13.4 Boundary Closeout (shipped 2026-05-03)</summary>

**Delivered:** 7 phases (225, 226, 227, 228, 230, 231, 229), 23 plans, 30/30 requirements satisfied — see [milestones/v13.4-ROADMAP.md](milestones/v13.4-ROADMAP.md).

- **ProcessingPort + CatalogPort** — both directions of the catalog↔processing cycle now go through Protocol boundaries; `test_no_processing_imports_catalog` and `test_no_catalog_imports_processing` enforce the invariant.
- **AIProviderExtension + EmbeddingProviderExtension** — chat/completion and embeddings provider dispatch are extensible via platform registries, with module-level provider SDK import guards across `backend/app/processing/`.
- **SAML fixture tmp-path cleanup** — SAML overlay tests no longer dirty committed fixture files.
- **Cold publish workflows verified** — `geolens==1.0.0`, `geolens-cli==1.0.0`, and `@geolens/sdk==1.0.0` are visible from public registries.
- **Post-impl close gate passed** — `docs-internal/audits/post-impl-20260503-v13-4.md` records Boundary Integrity A+, Coupling Health A−, Seam Quality A−, no unresolved P1 findings.

**Known close note:** In-progress advanced-sharing controls were stashed before archival as `stash@{0}` and are not part of v13.4.

</details>

<details>
<summary>Earlier milestone — v13.3 Boundary A+ Cleanup (shipped 2026-05-01)</summary>

**Delivered:** 3 phases (222-224), 18 plans, 15/15 requirements satisfied — see [milestones/v13.3-ROADMAP.md](milestones/v13.3-ROADMAP.md).

- **AuditSink Protocol + 65-site chokepoint** — extensible audit-emission seam with per-sink failure isolation (`structlog.exception()` swallows + logs without breaking surrounding business operation). `audit_emit()` facade replaces 65 direct `log_action()` calls; only 7 references remain (definition site + DefaultAuditSink shim + docstrings). CI guard `test_no_log_action_calls_outside_audit_service` enforces invariant (Phase 222).
- **AWS Marketplace billing extracted** — `core/marketplace.py` deleted; `Settings.aws_marketplace_*` removed; generic `BillingExtension.on_startup()` dispatch loop in `api/main.py:184-209` with `asyncio.wait_for(timeout=10s)` + per-extension try/except. AWS Marketplace overlay subscribes via `geolens-enterprise/billing/` entry-point. Boundary Integrity grade A → **A+** (Phase 223).
- **Catalog god-module decomposed** — `backend/app/modules/catalog/datasets/domain/service.py` 1407 → 87 LOC thin re-export façade. Five cohesive sub-modules (create/query/lifecycle/metadata/relationships) each <500 LOC. 23 public symbols preserved across 47 consumer files via explicit named re-exports + `__all__`. DECOUPLE-04 architecture-guard test prevents future bypass (Phase 224).
- **SQL-safety single source of truth** — `_sql_safety.py` consolidates `SAFE_TABLE_NAME_RE` + `SAFE_COLUMN_NAME_RE` + `_safe_table_ref` (was redefined 6× pre-cleanup). Architecture guard extended to forbid external imports of the private module.
- **`IngestionResult` Pydantic model** — collapses `create_dataset` 17-kwarg signature to a single typed parameter object (with legacy-kwargs back-compat for existing test fixtures).
- **Three new architecture-guard Makefile targets** — `audit-sink-discipline`, `billing-extraction-discipline`, `catalog-domain-discipline`.

</details>

<details>
<summary>Earlier milestone — v13.2 Edition Lifecycle Hardening (shipped 2026-04-30)</summary>

**Delivered:** 2 phases (220-221), 9 plans, 7/7 requirements satisfied — see [milestones/v13.2-ROADMAP.md](milestones/v13.2-ROADMAP.md).

- **Operator runbooks for the full lifecycle** — `docs/edition-deactivation.md` (186 lines, 10 sections) for enterprise→community downgrade and `docs/edition-reactivation.md` for re-upgrade. `docs/saml.md` cross-links to the new runbook and labels `alembic downgrade -1` as the destructive path with mandatory `pg_dump` pre-step (Phase 220).
- **SAML data preservation verified** — `backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data` confirms `oauth_providers` rows + 4 `deferred=True` SAML columns + `oauth_accounts` linkages survive a registry-clear deactivation. `lifecycle` pytest marker registered + run by default in CI when overlay installed (Phase 220).
- **CI overlay install with graceful fork-PR fallback** — `.github/workflows/ci.yml` conditionally checks out `geolens-enterprise` based on `GEOLENS_ENTERPRISE_TOKEN` secret presence; pytest runs with lifecycle marker INCLUDED when available, deselected on fork PRs without secret (Phase 220).
- **Admin SAML→local conversion endpoint** — `POST /admin/users/{user_id}/convert-saml-to-local/` (audit action `user.convert_saml_to_local`) flips a SAML user to local-password in a single transaction, preserving `users.id` (every FK referencing it stays intact) and deleting only the SAML `oauth_accounts` linkage. Self-conversion blocked with 422 (Phase 221).
- **Round-trip symmetry guaranteed** — `test_deactivate_reactivate_roundtrip_preserves_saml_data` drives the registry through a full cycle and asserts losslessness across the 4 deferred SAML columns + `oauth_accounts` linkage + User row + a seeded `audit_log` row (Phase 221).

</details>

<details>
<summary>Earlier milestone — v13.1 Open-Core Separation P1 (shipped 2026-04-29)</summary>

8 phases (212-219), 30 plans, 21/21 requirements satisfied — see [milestones/v13.1-ROADMAP.md](milestones/v13.1-ROADMAP.md).

- Open-core boundary closed: `core/` no longer imports from `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py` with broadened architecture-guard (212, 213).
- `IdentityProtocol` extracted: 51 cross-domain `User` import sites retyped to `Identity`; `get_identity_extension()` hook lets enterprise overlays register custom backends without core changes (214).
- Auto-generated SDKs: Python (`pip install geolens`) + TypeScript (`@geolens/sdk`) regenerate one-shot via `make sdks`; `make sdks-check` CI gate prevents drift (215).
- `geolens` CLI MVP: Apache-2.0 standalone tool consuming only the generated SDK (zero hand-rolled HTTP); `login` (keyring + headless), `scan`, `publish`, `export stac` (216).
- SAML enterprise overlay: `geolens-enterprise` registers via entry_points with dual `AuthExtension` + `IdentityExtension`; admin UI 3-layer gated; SAML implementation lives outside core (217).
- Audit gate met: Phase 218 produced closing audit; Phase 219 closed OAuth IdP→role mapping P0 surfaced by Phase 218 via `is_enterprise()` schema + service gate; audit doc amended in place to VERIFIED (218, 219).

</details>

**Concurrent shipped work (cross-repo, prior to v13.1):**
- v14.0 Marketing Site (executed in `getgeolens.com` repo, shipped 2026-04-13).
- 999.1-999.4 backlog (3D viewer toggle, PostGIS 3D detection, GeoJSON-Z delivery endpoint, shared vector staging pipeline) — executed in **this repo** as backend/frontend work; phase artifacts remain under `.planning/phases/999.1-*..999.4-*`.

## Core Value

Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Requirements

### Validated

- ✓ Search-first catalog UI with text, spatial, temporal, and tag-based filtering — v1.0
- ✓ Dataset preview: map visualization, attribute table, metadata card, and download options — v1.0
- ✓ Ingestion pipeline: upload files (Shapefile, GeoJSON, GeoPackage, CSV) and load into PostGIS via ogr2ogr — v1.0
- ✓ Export pipeline: export datasets to GeoJSON, Shapefile, GeoPackage, CSV via ogr2ogr — v1.0
- ✓ OGC API – Features via pg_featureserv — v1.0
- ✓ Vector tile serving via pg_tileserv for map previews — v1.0
- ✓ OGC API – Records-aligned metadata/search endpoints in catalog service — v1.0
- ✓ OGC Records Part 1 conformance URIs and per-record conformsTo arrays — Phase 183
- ✓ Source organization and CRS filter controls in search UI — Phase 183
- ✓ Metadata model: keywords/tags, spatial extent, organization/owner, temporal range, CRS, row count — v1.0
- ✓ Simple local authentication (username/password) with OIDC-ready architecture — v1.0
- ✓ App-level RBAC for dataset access control — v1.0
- ✓ Dataset registry with audit logging — v1.0
- ✓ Docker Compose packaging for single-node on-prem deployment — v1.0
- ✓ Performance: sub-second search, instant tile rendering, efficient large-file ingestion — v1.0
- ✓ OGC API landing page and conformance for machine client auto-detection — v1.1
- ✓ Enriched catalog records with assets, bbox, navigation links, and OGC properties — v1.1
- ✓ Dynamic collection metadata with spatial/temporal extents and catalog summaries — v1.1
- ✓ Hypermedia pagination with next/prev links for lossless catalog traversal — v1.1
- ✓ API key authentication for machine clients — v1.1
- ✓ CQL2 text and JSON filtering with RBAC-safe query pipeline — v1.1
- ✓ Queryables and record schema endpoints for schema introspection — v1.1
- ✓ Saved search deduplication with unique constraint upsert — v1.2
- ✓ MapLibre vector tile layers render without console errors — v1.2
- ✓ Geometry type consistent uppercase casing across ingestion and display — v1.2
- ✓ OGC API links use correct public base URL from request or configuration — v1.2
- ✓ Test suite isolated on dedicated database, dev DB clean — v1.2
- ✓ Admin dashboard Storage Used shows real PostGIS consumption — v1.2
- ✓ Audit log displays username of actor for each event — v1.2
- ✓ Import UI with drag-and-drop file upload, bulk upload, and job progress tracking — v1.3
- ✓ Pre-import preview with detected columns, sample rows, CRS, geometry type, and editable metadata — v1.3
- ✓ Register existing PostGIS table through the UI — v1.3
- ✓ Ingestion error recovery with retry failed jobs and better error messages — v1.3
- ✓ Self-registration with admin approval flow and "pending approval" screen — v1.3
- ✓ Admin chooses role (viewer/editor/admin) at user approval time — v1.3
- ✓ Admin can create, edit, and delete users through the UI — v1.3
- ✓ Admin can view, create, and revoke API keys for any user — v1.3
- ✓ Admins and editors can edit dataset metadata (name, description, tags, visibility) through the UI — v1.3
- ✓ Hard delete datasets with type-to-confirm safety step — v1.3
- ✓ Per-dataset change history on dataset detail page (filtered audit log) — v1.3
- ✓ Admin dashboard Jobs tab showing all ingestion jobs across all users — v1.3
- ✓ Frontend unit tests with Vitest and React Testing Library for stores, route guards, and components — v1.4
- ✓ Structured JSON logging via structlog with request correlation IDs and dev/prod toggle — v1.4
- ✓ Request logging middleware with method, path, status code, and duration tracking — v1.4
- ✓ Database backup/restore scripts with retention rotation and environment validation — v1.4
- ✓ CI pipeline with frontend-test job and coverage reporting for both backend and frontend — v1.4
- ✓ Playwright E2E tests covering auth, search, dataset detail, admin panel, and upload flows — v1.4
- ✓ CI e2e-test job running full-stack browser tests against Docker Compose with failure artifact upload — v1.4
- ✓ Flat, multi-membership collections with name, description, and aggregated spatial/temporal extents — v1.5
- ✓ Collection management UI for admins/editors (create, edit, delete, manage dataset membership) — v1.5
- ✓ Collection landing pages with search/filter within collection — v1.5
- ✓ Collection browser page with cards showing dataset count and extent preview — v1.5
- ✓ Dataset re-upload with atomic table swap preserving identity, metadata, and memberships — v1.5
- ✓ Schema diff preview comparing old and new columns, types, and row counts before re-upload commit — v1.5
- ✓ Version history tracking for re-uploaded datasets with timestamp, user, and file/schema changes — v1.5
- ✓ Comprehensive UI/UX design guide establishing GeoLens brand identity, color palette, typography, spacing, and component patterns — v1.6
- ✓ Clean professional visual direction (Stripe/Linear style) with generous whitespace and subtle accents — v1.6
- ✓ Consistent component library — all base components (buttons, cards, inputs, badges, tables) follow the design system — v1.6
- ✓ Every page refactored to follow the guide — search, dataset detail, collections, import, admin, auth flows — v1.6
- ✓ Light mode only — v1.6
- ✓ Layer filters with visual builder (field/operator/value dropdowns), stored on MapLayer, rendered via MapLibre filter expressions — v1.9
- ✓ Per-layer labels with attribute picker, font size, color, and halo via MapLibre symbol layers — v1.9
- ✓ Data-driven styling (categorical and graduated) with Brewer color ramps for fills, lines, and circles — v1.9
- ✓ Layer drag-and-drop reordering to change draw order in the map builder — v1.9
- ✓ Feature popups showing attribute table on click with formatted values — v1.9
- ✓ Layer rename with custom display names independent of dataset name — v1.9
- ✓ Natural-language map generation from prompt with automatic dataset search and layer creation — v1.9
- ✓ Conversational AI chat for map editing (filters, styles, labels, visibility, add/remove layers) with tool calling — v1.9
- ✓ Multi-provider LLM support (Anthropic native tool_use + OpenAI-compatible API for Ollama/Groq/Together) — v1.9
- ✓ Admin AI status card with runtime enable/disable toggle persisted in DB with TTL cache — v1.9
- ✓ CLI seed script downloads all 130 Natural Earth 1:10m datasets from NACIS CDN with retry and caching — v2.0
- ✓ Three-step API ingestion (upload/preview/commit) with srid_override=4326 and job polling — v2.0
- ✓ Auto-generated human-readable names and thematic tags from Natural Earth naming conventions — v2.0
- ✓ Idempotent re-runs with catalog check, concurrent ingestion (3 parallel streams), and collection grouping — v2.0
- ✓ Service URL tab on Import page for WFS and ArcGIS Feature Service URLs — v2.1
- ✓ SSRF validation blocking private IPs and non-HTTP schemes on all remote URL requests — v2.1
- ✓ Auto-detection of WFS vs ArcGIS services with unified layer listing — v2.1
- ✓ ogrinfo-based layer preview with columns, CRS, geometry type, sample rows, and feature count — v2.1
- ✓ ogr2ogr ingestion for WFS (native driver) and ArcGIS (ESRIJSON with auto-pagination) — v2.1
- ✓ Automatic CRS reprojection to WGS84 during service import (-t_srs EPSG:4326) — v2.1
- ✓ Optional auth token forwarding (Bearer for WFS, query param for ArcGIS) — never persisted — v2.1
- ✓ Full post-processing parity: geom_4326, mercator clip, reader grants, metadata extraction, quality score — v2.1
- ✓ Native FastAPI feature-serving endpoints with paginated GeoJSON, bbox/property filtering, and RBAC — v2.2
- ✓ pg_featureserv removed from Docker stack, reducing deployment from 6 to 5 services — v2.2
- ✓ Frontend ServiceUrls and map components point to FastAPI feature endpoint — v2.2
- ✓ Human-readable slugified table names for new dataset ingestions with collision suffix handling — v2.2
- ✓ Existing UUID-named tables continue working without changes — v2.2
- ✓ Discovery endpoint scans PostGIS database for unregistered spatial tables — v2.2
- ✓ Table picker UI with multi-select checkboxes replaces text input for registering existing tables — v2.2
- ✓ Bulk-register multiple discovered tables at once with per-table error isolation — v2.2
- ✓ Editor/admin can create new empty layers by choosing geometry type and name — v2.3
- ✓ Created layers become full catalog datasets with complete post-processing pipeline — v2.3
- ✓ Draw points, lines, polygons on the map with Terra Draw toolbar (point, line, polygon, rectangle, circle, freehand modes) — v2.3
- ✓ Drawn features persist to PostGIS and appear in map tiles immediately — v2.3
- ✓ Select and move existing features, edit vertices, delete features — v2.3
- ✓ Edit attribute values on individual features via attribute form — v2.3
- ✓ Add/remove attribute columns on existing layers with validation against allowlists — v2.3
- ✓ Undo last drawing action while in draw mode (button + Ctrl+Z/Cmd+Z) — v2.3
- ✓ Vertex snapping to nearby features for precise alignment — v2.3
- ✓ Write operations (create layer, feature CRUD, schema changes) gated by RBAC — v2.3
- ✓ Dark/light mode toggle in Navbar with system color scheme detection and preference persistence — v2.4
- ✓ FOUC prevention when dark mode is active — v2.4
- ✓ Distinctive emerald brand accent color across both themes with dark mode design tokens — v2.4
- ✓ All hardcoded colors replaced with semantic tokens, MapLibre controls themed, hover states and transitions — v2.4
- ✓ Admin panel with sidebar navigation, deep-linkable routes, and dedicated Settings section — v2.4
- ✓ Existing admin functionality preserved in new layout — v2.4
- ✓ Admin manages basemap presets and custom basemaps via XYZ/TMS tile URL — v2.4
- ✓ Users see admin basemaps in picker across all map views with auto-switch on theme change — v2.4
- ✓ Admin sets default map center/zoom, map views use admin defaults — v2.4
- ✓ Self-registration and AI chat feature toggles with immediate effect — v2.4
- ✓ Provider-agnostic storage (local + S3), caching (in-memory + Redis/Valkey), managed database support with SSL — v5.0
- ✓ Presigned S3 uploads for large files, CDN tile delivery, admin infrastructure dashboard — v5.0
- ✓ Cloud deployment documentation for AWS, GCP, and DigitalOcean — v5.0
- ✓ nginx gzip compression, per-IP rate limiting, static asset caching, security headers — v6.0
- ✓ Non-root Docker containers with CI Trivy scanning and SBOM attestation — v6.0
- ✓ Route-based code splitting with React.lazy for all page components — v6.0
- ✓ Refresh token auth with proactive auto-refresh and configurable CORS — v6.0
- ✓ Magic byte file validation, zip bomb detection, admin-configurable upload limits — v6.0
- ✓ Prometheus metrics for HTTP requests, job queues, connection pools, and tile cache — v6.0
- ✓ Automated database backups with S3 off-site replication, retention, and restore validation — v6.0
- ✓ Redis circuit breaker, priority queue routing, frontend type cleanup — v6.0
- ✓ Canonical dataset detail hierarchy with single title, above-the-fold key metadata, and role-aware editable affordances — v6.1
- ✓ Segmented edit context model (Geometry/Attributes/Metadata) with dirty-switch guardrails — v6.1
- ✓ Editable vs read-only field affordances with consistent helper text on dataset detail — v6.1
- ✓ Service URL re-upload with schema diff preview, atomic swap, and identity preservation — v6.1
- ✓ Validation troubleshooting guidance and quality score freshness with cadence semantics — v6.1
- ✓ Provenance attribution on detail pages, search cards, and all mutation audit paths — v6.1
- ✓ Admin sidebar flattened with settings promoted to top-level entries — v6.1
- ✓ "Powered by GeoLens" footer link to GitHub repository — v6.1
- ✓ PersistentConfig generic class with env-var default, DB override, and ENV_ONLY kill switch — v6.2
- ✓ Centralized config registry with unified admin settings page (6 tabs) replacing scattered settings — v6.2
- ✓ Admin UI for auth token lifetimes, CORS origins, LLM provider/model, log level, and tile cache TTL — v6.2
- ✓ Granular per-role permission toggles (upload, create layers, export, edit metadata, manage collections, AI chat) — v6.2
- ✓ OAuth/OIDC provider management via admin UI (Google, Microsoft, generic OIDC) with encrypted secrets — v6.2
- ✓ OAuth/OIDC login flow with PKCE, auto-account creation, email-based account linking, and group-to-role mapping — v6.2
- ✓ Config export/import API with dry-run diff preview and merge/overwrite modes — v6.2
- ✓ Audit trail for all admin setting changes with old/new values — v6.2
- ✓ Infrastructure connectivity validation endpoint (S3, Redis, OIDC) — v6.2

- ✓ FastAPI tile gateway with ST_AsMVT replacing pg_tileserv — v7.0
- ✓ Signed tile access (HMAC URL tokens) replacing nginx auth_request — v7.0
- ✓ Procrastinate worker separated from API into its own container — v7.0
- ✓ Standalone SPA frontend (no nginx dependency) with runtime env config — v7.0
- ✓ FastAPI middleware for gzip, rate limiting, security headers (nginx removed) — v7.0
- ✓ Alembic migrate service for startup migrations — v7.0
- ✓ nginx reverse proxy removed from runtime topology — v7.0

- ✓ pgvector extension with record_embeddings table and HNSW index — v7.2
- ✓ Embedding generation pipeline via Procrastinate (ingest hook, metadata update hook, backfill command) — v7.2
- ✓ SEMANTIC_SEARCH_ENABLED admin toggle and embedding health probe in admin dashboard — v7.2
- ✓ Hybrid search combining FTS + vector results via Reciprocal Rank Fusion (RRF) — v7.2
- ✓ Frontend semantic search toggle gated by AI enabled + embeddings exist — v7.2
- ✓ AI search_datasets tool enhanced with hybrid search for better map generation and chat — v7.2
- ✓ Related datasets endpoint with overview tab card row on dataset detail page — v7.2
- ✓ Smarter keyword suggestions via embedding similarity in metadata generators — v7.2

- ✓ SQL sandbox with sqlglot AST validation enforcing single-SELECT-only queries — v8.0
- ✓ RBAC table allowlist restricting SQL queries to user-visible datasets — v8.0
- ✓ Safe SQL execution with READ ONLY transactions, 30s timeout, 1000-row cap — v8.0
- ✓ Error sanitization pipeline with generic user messages and full server-side logging — v8.0
- ✓ Text-to-SQL engine with DDL schema context and PostGIS-aware generation prompt — v8.0
- ✓ Natural language data questions answered via LLM-generated PostGIS SQL in chat — v8.0
- ✓ Narrative plain-text answers interpreting query results in chat — v8.0
- ✓ Streaming stage progression feedback during SQL query execution — v8.0
- ✓ Actionable error messages for query failures (timeout, no results, permission denied) — v8.0
- ✓ Ephemeral result layers rendering spatial query geometry as temporary GeoJSON overlays — v8.0
- ✓ Ephemeral layer dismiss UI with feature count badge and auto-zoom to results — v8.0
- ✓ PATCH endpoint for share token expiration with ownership check and audit logging — v8.2
- ✓ PATCH endpoint for embed token domain restrictions with cache invalidation — v8.2
- ✓ Inline-editable expiration and domain fields in SharePanel with toast feedback — v8.2
- ✓ Value persistence across panel reopen via query invalidation — v8.2

- ✓ Map copy/fork with RBAC-filtered layer duplication, lineage tracking, and collision-safe naming — v10.0
- ✓ Map browse page with search, sort, filter, grid/list toggle, and author attribution on cards — v10.0
- ✓ Map metadata info modal and button tray restructure in map builder — v10.0
- ✓ Dataset-to-maps cross-reference ("Used in Maps"), adaptive SVG previews, and auto-capture thumbnails — v10.0
- ✓ Raster schema foundation with record_type discriminator, raster_assets table, and Titiler Docker service — v10.0
- ✓ COG ingest pipeline with automatic conversion, metadata extraction, quicklook thumbnails, and raster-aware delete — v10.0
- ✓ RBAC-gated raster tile serving via Titiler with auth-check endpoint and credential isolation — v10.0
- ✓ Raster catalog integration with DatasetResponse raster fields, COG download, and connect URLs — v10.0
- ✓ Raster search and import UI with type filter, raster badges, quicklook thumbnails, and raster detail pages — v10.0
- ✓ Map builder raster layers with opacity control, conditional layer controls, AI awareness, and persistent layer_type — v10.0
- ✓ PostgreSQL profiling infrastructure (pg_stat_statements + auto_explain) and synthetic seed script for 1000+ datasets — v11.0
- ✓ Locust load testing suite with weighted traffic scenarios for all critical API paths — v11.0
- ✓ Baseline measurement report with p50/p95/p99 latencies under 10-user concurrent load — v11.0
- ✓ Keyset cursor pagination replacing LIMIT/OFFSET for constant-time page access — v11.0
- ✓ Redis tile cache with gzip-compressed MVT bytes and Prometheus counters — v11.0
- ✓ B-tree GID indexes on high-traffic tables and PostgreSQL memory/autovacuum tuning — v11.0
- ✓ Configurable connection pool parameters (DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE) — v11.0
- ✓ Performance regression test suite with @pytest.mark.perf markers for 5 critical endpoints — v11.0
- ✓ OGC Records Part 1 conformance URIs (record-core, record-core-query-parameters, json) at /conformance — v12.0
- ✓ Faceted search with /search/facets endpoint returning record_type, keywords, source_organization, srid groups — v12.0
- ✓ Type toggle badges with live counts (All, Vector, Raster, VRT, Collection) in search UI — v12.0
- ✓ Collections as first-class records in global search with member count badge and drill-down — v12.0
- ✓ OGC datetime interval parameter for temporal extent filtering — v12.0
- ✓ Modality-aware assets (raster records exclude vector links, vector records exclude raster links) — v12.0
- ✓ Unified assets dict with stac_assets emitted during transition period — v12.0
- ✓ Raster/VRT records include proj:epsg, proj:shape, gsd, bands with stac_extensions array — v12.0
- ✓ Publication lifecycle enum (draft/ready/internal/published) with state machine enforcement via PATCH /datasets/{id}/status — v12.0
- ✓ Asset URL security: signed URLs for STAC, proxy for local, public thumbnails for published — v12.0
- ✓ STAC 1.1 export: /stac/ catalog, /stac/items/{id}, /stac/collections/{id}, /stac/search with bbox/datetime/collections/ids — v12.0
- ✓ STAC API conformance classes declared — v12.0
- ✓ VRT generation tracking with vrt_generations table and backfill migration — v12.0
- ✓ VRT status/generations API endpoints and regeneration with advisory lock and atomic swap — v12.0
- ✓ VRT detail page Sources tab with generation history, source health, and regenerate button — v12.0
- ✓ Detail page refactored to shared skeleton with type-specific panels (Vector, Raster, VRT, Collection) — v12.0
- ✓ Keyword facet multi-select picker with search-as-you-type in FilterPanel — v12.0
- ✓ Search ranking boosts (published 2x, freshness 1.5x within 30 days) — v12.0
- ✓ All icon-only buttons have descriptive aria-labels for screen readers — v12.1
- ✓ Raster quicklook images have meaningful alt text with dataset name — v12.1
- ✓ Focus indicators visible on all interactive elements — v12.1
- ✓ Standard ErrorState/LoadingState components used consistently across all pages — v12.1
- ✓ All destructive buttons use variant="destructive" — v12.1
- ✓ Submit buttons show loading spinners when mutations are pending — v12.1
- ✓ Form spacing standardized (space-y-2 label+input, space-y-4 groups) — v12.1
- ✓ Icon sizes follow 4-tier design guide system — v12.1
- ✓ Search cards show creation date fallback for never-edited datasets — v12.1
- ✓ Quality score badge uses neutral styling (not warning amber) — v12.1
- ✓ Every page sets contextual document title for browser tabs — v12.1
- ✓ Audit log timestamps show time-of-day for same-day entries — v12.1
- ✓ Collections browse page has client-side search/filter — v12.1
- ✓ Dataset detail tabs responsive on narrow viewports — v12.1
- ✓ Mobile tab triggers meet 44px touch target minimum with scroll-snap overflow — v12.2
- ✓ Tab overflow discoverable via gradient fade and snap-x scrolling — v12.2
- ✓ Scrollable table containers keyboard-focusable with visible focus ring and role=region — v12.2
- ✓ VRT status badges use centralized WCAG AA semantic colors on light and dark themes — v12.2
- ✓ Collection metadata card uses valid dl/dt/dd semantic markup — v12.2
- ✓ Collection detail header readable on mobile without title squeeze — v12.2
- ✓ Collection page uses intentional flat card+list layout (distinct from dataset tabs) — v12.2
- ✓ Dataset detail pages have no horizontal overflow at 375px on any record type — v12.2
- ✓ Page titles keep readable width with break-words, never collapse to single-word-per-line — v12.2
- ✓ Raster mobile header H1 visible even with Download COG action present — v12.2
- ✓ Secondary actions collapse behind overflow menu at mobile breakpoint — v12.2
- ✓ VRT preview failures stop after bounded retry budget (3 errors or >50% rate) — v12.2
- ✓ VRT/raster hero always shows one of: loaded preview, loading skeleton, or error with retry — v12.2
- ✓ Raster no-tile badge appears immediately for null tile_url datasets (no 10s timeout) — v12.2
- ✓ Users can work on maps comfortably on tablet and narrow desktop widths — v12.3
- ✓ Users can open AI chat on compact tablet widths without sacrificing map workspace — v12.3
- ✓ Users can collapse builder UI without hidden controls remaining tabbable — v12.3
- ✓ Users can scan and manipulate layers through progressively disclosed controls with type cues — v12.3
- ✓ Users can understand save state and key actions without icon-only affordances — v12.3
- ✓ Users see layer-type-appropriate icons and controls for vector, raster, and VRT layers — v12.3
- ✓ Engineers can change map-builder behavior through smaller modules with shared capability model — v12.3
- ✓ `core/` no longer imports from `modules/settings/`; layering inversion broken via `AppSetting` relocation to `core/db/models.py` — v13.1
- ✓ `auth/visibility.py` removed; 23 inbound callers migrated to `catalog/authorization.py` with no behavior change — v13.1
- ✓ `IdentityProtocol` defined in `core/identity.py`; 51 cross-domain `User` import sites retyped to `Identity` — v13.1
- ✓ Extension system exposes `get_identity_extension()` typed accessor; enterprise overlays register identity backends without core changes — v13.1
- ✓ Python SDK auto-generated from `backend/openapi.json`, Apache-2.0, ready for PyPI (live publish deferred per workflow_dispatch) — v13.1
- ✓ TypeScript SDK auto-generated from `backend/openapi.json`, Apache-2.0, ready for npm (live publish deferred per workflow_dispatch) — v13.1
- ✓ `make sdks` regenerates both SDKs one-shot; `make sdks-check` CI gate prevents drift — v13.1
- ✓ SDK version pins to OpenAPI snapshot version; release process documented in `docs/sdks.md` — v13.1
- ✓ `geolens` CLI distributed as Apache-2.0 PyPI package; works against any GeoLens instance with same code path — v13.1
- ✓ `geolens login` stores token in OS keyring with `--no-keyring` headless fallback — v13.1
- ✓ `geolens scan <dir>` walks directory and reports vector/raster files without uploading — v13.1
- ✓ `geolens publish <file>` uploads via SDK and reports dataset URL — v13.1
- ✓ `geolens export stac <id>` writes STAC 1.1 JSON for raster datasets — v13.1
- ✓ CLI consumes only the generated Python SDK — zero hand-rolled HTTP imports (CI grep + tomllib gates enforce) — v13.1
- ✓ SAML implementation lives entirely in `geolens-enterprise` repo (with documented Pitfall 11 carve-out for `deferred=True` ORM scaffolding) — v13.1
- ✓ Core auth-extension hook is the only seam SAML overlay registers into; `importlib.metadata` entry_points — v13.1
- ✓ Admin UI shows SAML tab only when enterprise edition detected; community returns 404 (3-layer gating) — v13.1
- ✓ SP-initiated SAML SSO with metadata XML endpoint, signed assertion validation, JIT provisioning via `find_or_create_oauth_user()` — v13.1
- ✓ Configurable SAML attribute → role mapping via `group_claim`/`group_role_mapping`; gated by `is_enterprise()` (Phase 219); audit-logged with `SECRET_FIELDS` redaction — v13.1
- ✓ Closing audit grades meet/exceed targets: Boundary A (≥A−), Seam Quality B (≥B), OSS Surface A− (≥C) — v13.1
- ✓ Operator runbook for enterprise→community downgrade (`docs/edition-deactivation.md`, 10 sections) — v13.2
- ✓ Operator runbook for community→enterprise re-upgrade (`docs/edition-reactivation.md`) — v13.2
- ✓ `docs/saml.md` no longer presents `alembic downgrade -1` as primary deactivation path; cross-links to runbook with mandatory `pg_dump` pre-step on destructive path — v13.2
- ✓ Disabling the enterprise edition without `alembic downgrade` preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns — verified by `test_overlay_removal_preserves_saml_data` in CI — v13.2
- ✓ Destructive alembic downgrade path documented with explicit data-export prerequisite — v13.2
- ✓ Admin SAML→local conversion endpoint preserves users.id (all FK referrers intact) — `POST /admin/users/{user_id}/convert-saml-to-local/` with audit action `user.convert_saml_to_local`, allow-listed audit details (no password material), 422-blocked self-conversion — v13.2
- ✓ Round-trip symmetry test confirms 4 `deferred=True` SAML columns + `oauth_accounts` linkage + User row + seeded `audit_log` row are lossless across deactivate→reactivate cycle — `test_deactivate_reactivate_roundtrip_preserves_saml_data` in CI — v13.2
- ✓ `PermissionExtension` Protocol, Community default, typed accessor, overlay tests, and architecture guard cover action checks plus catalog visibility/detail access — v13.5
- ✓ `WorkflowExtension` Protocol, transition context, Community default, typed accessor, overlay tests, and architecture guard cover publication transitions and transition hooks — v13.5
- ✓ Dataset publication `/status/`, `/target-status/`, and metadata `record_status` writes consult `WorkflowExtension` instead of hardcoded-only state logic — v13.5
- ✓ Advanced sharing controls are gated consistently in Community vs Enterprise across schema validators, service guards, builder affordances, API/OpenAPI text, and GTM docs — v13.5
- ✓ Basic Community share/embed flows remain intact: non-expiring share links and default unrestricted 30-day embed tokens can still be created/revoked — v13.5
- ✓ v13.5 close audit records Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings — v13.5
- ✓ `catalog/maps/service.py` is split into focused service modules with a stable facade and no map-builder, layer, sharing, thumbnail, token, or public-viewer regressions — v13.6
- ✓ `catalog/search/service.py` is split into focused service modules with a stable facade and no search, facet, semantic/hybrid, OGC/STAC, AI, or collection regressions — v13.6
- ✓ Architecture guards prevent direct external imports of private maps/search split modules and keep facade/private service modules inside reviewed size budgets — v13.6
- ✓ Focused maps/search tests, lint, format checks, close-audit evidence, and formal milestone audit prove the decomposition preserved existing public behavior — v13.6
- ✓ Project-owned Pydantic deprecation warnings from the focused maps/search gate are fixed; remaining Alembic/Authlib warnings have explicit owner follow-up — v13.6
- ✓ Versioned `geolens.yaml` manifest schema covers stable dataset identity, source entries, metadata, and Community-safe publication intent with committed compatibility fixtures — v13.7
- ✓ `geolens init` and `geolens validate` provide an offline manifest workflow with deterministic exit codes, path-specific validation errors, and CLI import-boundary guards — v13.7
- ✓ Manifest apply API/service accepts typed payloads, preserves upload permission, storage/file safety, idempotency, and existing vector/raster/VRT ingest behavior — v13.7
- ✓ `geolens apply` and `--dry-run` publish or preview manifest-driven catalog changes through configured API credentials — v13.7
- ✓ Public examples and docs prove a Docker Compose to browsable catalog adoption path using local, HTTP/S3, and publication-state manifests — v13.7
- ✓ OpenAPI, generated Python/TypeScript SDKs, CI manifest gates, architecture guards, and formal close audit cover the manifest/apply surface — v13.7
- ✓ Map builders persist MapLibre-valid `paint` JSON only; private builder UI state lives in documented `style_config` with row migration — v13.8
- ✓ Map builders save only changed layers via `PATCH /maps/{map_id}/layers` with stable layer IDs preserving identity for history and future collaboration; full-replacement save retained as fallback — v13.8
- ✓ Map builders tune raster imagery (brightness/contrast/saturation/hue rotation/resampling/fade duration/opacity + reset), line styling (gap width/blur/offset, with `line-gradient` deferred), and zoom-dependent styling (`step`/`interpolate` editor for line/circle/label/opacity) through first-class controls — v13.8
- ✓ Map builders visualize DEM rasters as hillshade with illumination/exaggeration/color controls and apply persisted map-level terrain settings consistently in builder and public viewer surfaces with vertical-unit caveats — v13.8
- ✓ Map builders export/import MapLibre style documents (raster, DEM hillshade, terrain block, outline/extrusion/label companions, builder metadata round-trip) and author sprite-backed symbol/icon layers with upload/storage/serving and consolidated symbol+label adapter — v13.8
- ✓ Map builders review a durable edit history timeline in the right rail backed by committed-save event capture (actor, timestamp, target, action type, change summary) — v13.8
- ✓ Open GitHub issue tracker (`geolens-io/geolens`) reflects post-audit state — all 11 open issues (#50-#59 builder issues + #97 sequencing tracker) closed with REQ-ID-citing comments verified against v13.8 + v13.9 milestone audits; tracker #97 closed last with summary linking each child closure path — v13.10 (shipped 2026-05-07)
- ✓ Map builder line-gradient authoring panel renders a gradient preview swatch above the stop list when Gradient mode is active and the expression is canonical (POLISH-01) — v13.11 (shipped 2026-05-07)
- ✓ Map builder gradient stop rows do not render the per-row "Color" label noise (POLISH-02), Solid/Gradient toggle has visible focus ring + cursor-pointer affordances (POLISH-03), the advanced-expression disclosure button spans full panel width (POLISH-04), each stop row carries a visible `pos` prefix label (POLISH-05), stop rows use stable per-stop UUID React keys (POLISH-06 — `id` field stays in builder JSONB only, paint expression byte-identity preserved), and the trash button is wrapped in a shadcn Tooltip (POLISH-07) — v13.11
- ✓ Map builder `advancedHint` copy reads in builder-user vocabulary (no internal-implementation jargon) and the 16-key `lineGradient` i18n block is fully translated in es/fr/de — v13.11 (COPY-01..02)
- ✓ Map builder Save button shows a `bg-warning` (orange) unsaved-changes dot when there are uncommitted edits, every interactive element across builder surfaces uses `cursor-pointer`, the runtime console is clean (DEV-only diagnostics), and the zoom-control widget renders in the same screen position on builder and shared/public/embed map surfaces — v13.11 (QUALITY-01..04)
- ✓ Map builder Label-Layer toggle no longer silently no-ops when `dataset_column_info` is empty — Switch becomes disabled with a tooltip in that state; full layer-order-and-visibility audit found no other regressions across LayerItem Eye toggle, syncLayersToMap, ChatPanel AI tools, render-mode swap, hillshade companion, or filter-changes — v13.11 (LAYER-01..02)
- ✓ Redesigned Map Stack and Add Dataset modal are reliable across desktop/tablet browser flows without schema drift, console errors, or inaccessible controls — v1003 (BQA-01..05)
- ✓ Users can create and independently configure multiple renderings of the same dataset from either sidebar row actions or the Add Dataset modal — v1003 (DUP-01..05)
- ✓ Basemap and terrain controls write only existing `Map` fields and survive save/reload/public-viewer round trips — v1003 (MAPCTL-01..05, ROUND-01..03)
- ✓ Focused Vitest, Playwright builder smoke, Playwright accessibility, Playwright MCP manual checks, lint, and build are documented at milestone close — v1003 (ADDH-01..05, ROUND-04)
- ✓ Map Builder broken-affordance fixes: regular layer visibility toggle, delete layer, rename-group autofocus all dispatch correctly via adapter-contract honor of `input.visible` + defense-in-depth `syncVisibility`, optimistic-state + rollback delete, and Radix DropdownMenu rAF-deferred focus; DETAIL LEVEL disposition resolved (REMOVE — dead-wired since v1008) — v1011 (BUG-01..03, INV-01)
- ✓ Map Builder UX clarifications: 24×24 px expand caret with Lucide ChevronRight, new `SublayerConfigIndicators` pure-derivation badges (Labels / Filter / DataDriven / OpacityModified) replacing per-sublayer opacity slider, basemap row draggable via `MapBasemapConfig.basemap_position` jsonb-additive + `reorderBasemapAboveData` map-sync helper, Map Settings Widgets state-specific aria-labels with 0-duplicates audit — v1011 (UX-01..04)
- ✓ Map Builder small-screen layout resilience: NavigationControl repositioned `top-right` → `top-left` with `data-builder-canvas` CSS scope, MapCoordReadout cross-context `right-14` offset codified in docstring, `<SheetContent showCloseButton={false}>` opt-out on both Sheet wrappers + NEGATIVE-CONTROL bug-shape regression pin — v1011 (RESP-01..03)
- ✓ Emergent-findings triage + close-gate: FINDINGS.md with fix-now vs defer-with-rationale disposition; 4 P2 deferred items tracked via pending todo + SUMMARY cross-references; 21 inline code-review fixes (iter-1 17 / iter-2 4) + 2 in-flight regression fixes (CTRL-01 gate-fix `befe6a3b` + RESP-02-FOLLOWUP `4f4a9917`) shipped before tag — v1011 (EMRG-01, CTRL-01)
- ✓ EMRG-FN-01 Path A REMOVE: `BasemapSublayerEditorScene` STROKE section + zoom range inputs + 5 dead-stub callbacks deleted (mirroring INV-01 precedent); live opacity slider + Reset section preserved; 5 orphan basemapSublayer i18n keys × 4 locales removed; Test 14 regression pin added with 5 positive-form `queryBy*` assertions; inline disposition comment block at removal site — v1011.1 (EMRG-FN-01)
- ✓ EMRG-FN-02 orphan i18n key cleanup: `settings.toggleWidget` removed from all 4 locales (en/de/es/fr builder.json) — v1011.1 (EMRG-FN-02)
- ✓ EMRG-FN-03 unused-eslint-disable cleanup: 2 stale `eslint-disable-next-line react-hooks/exhaustive-deps` directives removed from `UnifiedStackPanel.tsx` (actual lines 735+776 after planner-time grep caught REQUIREMENTS-cited 679+720 line drift); ESLint clean on file — v1011.1 (EMRG-FN-03)
- ✓ EMRG-FN-04 SublayerConfigIndicators `layer={null}` closure: docstring extension to existing Test 1 documents the live callsite at `UnifiedStackPanel.tsx:556` (CONTEXT.md auto-resolution claim was wrong — planner caught + Plan 06 corrected); existing test is the regression pin — v1011.1 (EMRG-FN-04)
- ✓ CTRL-01 batched close gate + live Playwright MCP re-verify: typecheck 0 / vitest 1979/1979 / e2e:smoke:builder 26/26 / i18n parity 2/2; orchestrator-driven MCP verify on `localhost:8080` confirmed Path A REMOVE intent matches shipped state (6/6 surface checks pass, 0 console errors); CHANGELOG `[Unreleased]` v1011.1 block populated; inline code-review fix (WR-01 orphan vi.mock) applied; local `v1011.1` tag at `567c701e` — v1011.1 (CTRL-01)
- ✓ PARA-01 cascade fix (Shape A*): wrap 3 sibling `_init_tile_pool_for_tests` fixtures' `asyncpg.create_pool` in existing `_run_with_too_many_clients_retry` envelope at `test_tiles.py:152` + `test_embed_tokens.py:57` + `test_tile_signing.py:108`; regression pin `test_init_tile_pool_retries_on_transient_too_many_clients` at `test_fixture_isolation_v1020.py:1144`; `-n auto` 3-run distinct 20/8/16 → 3/2/3 (≤30 deterministic, 0 ICN frames) — v1022 (PARA-01)
- ✓ PARA-02 WR-02 closure (Shape Y2 load-bearing rationale): `_invoke_sleep_in_sync_context` retains blocking `time.sleep` with documented rationale at conftest.py:624-689 after Shape Y1 (`asyncio.run(asyncio.sleep)`) empirically failed (greenlet context has running loop); regression pin `test_engine_retry_yields_event_loop_during_backoff` at `test_fixture_isolation_v1020.py:1253` — v1022 (PARA-02)
- ✓ HYG-01 engine-retry envelope hygiene: WR-03 narrow except `(TypeError, AttributeError, InvalidRequestError)` at `_RetryingAsyncEngine.__init__` (conftest.py:842; expanded for SQLAlchemy 2.x); WR-04 listener teardown via `_RetryingAsyncEngine.dispose()` override + `event.remove(...)` at conftest.py:934-977; 3 new regression pins (`test_engine_retry_do_connect_event_handler_retries_on_transient_error` at L1391, `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` at L1557, `test_init_tile_pool_propagates_non_transient_error` at L1666) — v1022 (HYG-01)
- ✓ CLOSE-01 close-gate (degraded): sequential 3060/3 OOS/38 + `-n 4` 3059/4 OOS/38 + `-n auto` 3-run 2/3/2 distinct deterministic + 0 ICN frames; CHANGELOG `[1.5.7]` block; tags `v1022` (local) + `v1.5.7` (public) cut at SHA `48707fb1`; MILESTONES.md v1022 entry — v1022 (CLOSE-01)

### Active

_None — v1022 just shipped (degraded close). Awaiting next milestone definition via `/gsd-new-milestone`._

**v1023 carry-forward (tracked for next milestone):** CI-01-v1023 — live-verify the `pytest-parallel-isolation` CI gate on real GitHub Actions infrastructure (post-billing-resolution). v1022's CI-01 was deferred when GitHub Actions billing block prevented the first post-merge live-verify run (run 26359374410: 0/13 jobs executed at runner-allocation). Operator action: resolve billing at https://github.com/organizations/geolens-io/settings/billing → `gh run rerun 26359374410` → document GREEN evidence in v1023 follow-up phase.

### Out of Scope

- v1003 excludes new renderers: Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, and any deck.gl/Kepler renderer adoption.
- v1003 excludes persisted basemap appearance presets beyond the existing `BasemapEntry` registry; if needed later, extend `BasemapEntry` with optional default config before adding a new table.
- v1003 excludes blend mode, map timeline/cross-layer playback, recipes editor, org connector library, cross-layer filters, promote-imports-to-org workflow, cross-surface drag from Add Dataset into exact stack position, and Curated/Your imports/Public chips until an API contract exists.
- v1003 excludes any new `Map`, `MapLayer`, `Dataset`, `Record`, basemap preset, timeline, recipe, or connector schema changes.

- Persistent connector registry, scheduled mirroring, encrypted credential vault, and connector UI — still Phase 999.13 / Enterprise backlog
- Tenant scoping for the future Cloud tier — still Phase 999.6 and not needed for single-tenant self-hosted manifest apply
- Helm release / `geolens-helm` launch decision (#92) — deferred indefinitely per milestone kickoff; do not include in v13.8
- AMI distribution, SBOM/signed image pipeline, and `geolens-schemas` extraction — still separate P2 distribution/package milestones
- Enterprise-only publishing policies or approval workflows — manifests may declare Community-safe publication state, but advanced governance remains overlay scope

- New map authoring capabilities beyond this milestone, including live collaboration and time sliders — still separate future scope from advanced styling
- AI capability expansion — AI chat and map generation stay as-is until a dedicated AI milestone changes scope
- Phone-specific map-builder optimization — still separate from the tablet/desktop builder scope already shipped
- Power-user resizable/persisted sidebar widths — useful enhancement, but secondary to the default tablet/desktop shell already shipped
- New net capabilities that are not necessary for polish, including live collaboration, annotation layers, time sliders, and a full new map authoring paradigm — v1001 is a UI/UX refinement milestone over existing builder architecture.
- Server-side map thumbnails via Celery + Pillow tile compositing for API-created and multi-user maps — OPS-01 remains a separate operational milestone unless needed only for builder preview polish.
- Full STAC certification — STAC 1.1 endpoints implemented and tested, formal certification deferred
- STAC for vector datasets — STAC is raster-centric; vector records served via OGC Records
- STAC temporal model (per-asset timestamps) — awkward for vector catalogs
- Automatic VRT regeneration on source change — manual-first, webhook/auto deferred until usage patterns understood
- Cursor-based catalog pagination (GAP-STD-08) — offset pagination works for <100K records; breaking change deferred
- Real-time collaboration / editing features — catalog is read/browse/export focused
- Raster band math / custom color ramps — v13.8 adds MapLibre raster paint controls, not analytical raster processing
- Raster collections / time series — one record = one COG for MVP, collection model deferred
- PostGIS Raster (in-database raster storage) — COG-as-file is the model
- Raster nodata footprint masking — bbox polygon for MVP, precise footprint later
- Mobile-specific UI — responsive web is sufficient
- SAML/LDAP/AD integration — wire through Keycloak later, not MVP
- CQL2 advanced features (arithmetic, array functions) — basic subset sufficient for catalog use case
- Catalog federation / harvesting — single-instance on-prem deployment
- Full data versioning / snapshot rollback — version history tracks metadata; full rollback deferred
- Cursor-based catalog pagination (GAP-STD-08) — offset pagination works for <100K records; breaking change deferred
- Automatic VRT regeneration on source change — manual-first, webhook/auto deferred until usage patterns understood
- Dataset-level sharing with specific users/groups — admin RBAC sufficient for now
- Email notifications for registration approval and job completion — SMTP adds deployment complexity for on-prem
- OAuth/OIDC self-registration — local auth self-registration is right scope
- Soft delete / trash can — adds complexity, on-prem storage is finite
- Self-service role elevation — admin promotes manually, small admin count

## Context

- **Current state**: v1005 shipped native MapLibre Point Cluster for bounded eligible point datasets after v1002-v1004 hardened the schema-preserving builder sidebar, Add Dataset flow, renderer capability registry, and Line -> Arrow renderer. Full-featured GIS catalog supporting vector, raster, and VRT datasets with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, STAC 1.1 export for raster/VRT interop, publication lifecycle, VRT lifecycle management, declarative `geolens.yaml` manifests, CLI init/validate/apply automation, and i18n (en/es/fr/de). Open-core extension seams now cover identity, audit, billing, AI providers, embeddings, permissions, workflows, catalog/processing boundaries, maps/search service facades, and manifest adoption workflows.
- **Architecture**: Database-first. PostgreSQL 17 + PostGIS 3.5 is the system of record. FastAPI serves vector tiles (ST_AsMVT with signed URL tokens), raster tiles (via Titiler with RBAC-gated token endpoint), features (paginated GeoJSON with bbox/property filtering), catalog metadata, search, auth, OGC discovery, and job orchestration. Background worker runs Procrastinate ingestion tasks. Titiler serves XYZ raster tiles from COG files. Frontend is a static SPA served by nginx with reverse proxy to the API.
- **OGC Compliance**: OGC API Common Core, OGC API Records Core, OGC API Features Part 3 (Filtering/CQL2). Conformance classes declared at `/api/conformance`.
- **Users**: Mix of GIS analysts (power users), data engineers (API consumers), and non-technical staff (browsing/downloading). Search-first UI serves all three. Machine clients (QGIS, GDAL, scripts) can now consume the catalog programmatically.
- **Scale**: 130 Natural Earth 1:10m datasets imported via seed script. Synthetic seed script can populate 1000+ datasets for scale testing. Performance validated at 1000+ datasets with 10 concurrent users — search p50 < 100ms, tiles p50 < 50ms. Keyset pagination, Redis tile cache, and B-tree GID indexes ensure consistent performance at scale.
- **Deployment**: Docker Compose for local/on-prem (5 services: API, Worker, Frontend, Titiler, DB + backup sidecar). Cloud-ready with managed Postgres, S3 storage, Redis/Valkey cache. Ports: DB=5434, API=8001, Frontend=8080.
- **Frontend**: React 19 + TypeScript + Vite 7 + MapLibre GL JS 5 + TanStack Query 5 + Zustand 5 + Tailwind CSS 4 + shadcn/ui + react-dropzone + sonner.
- **Search**: PostgreSQL full-text search with tsvector generated columns (name at weight A, description at B, tags at C, column names + sample values at D) + PostGIS spatial intersection + JSONB facets. Optional pgvector semantic search with hybrid FTS+vector RRF ranking, graceful FTS fallback.
- **Documentation**: Install guide, configuration reference, and admin guide in `docs/`.

## Constraints

- **Tech stack**: Python + FastAPI backend, React frontend, PostgreSQL 17 / PostGIS 3.5, GDAL/ogr2ogr, pygeofilter
- **Standards**: OGC API Features (Part 1 + Part 3), OGC API Records (aligned subset), Mapbox Vector Tiles, CQL2
- **Deployment**: Docker Compose (on-prem) or cloud managed services (AWS/GCP/DO)
- **Auth**: Local auth + API key auth + refresh tokens + OAuth/OIDC (Google, Microsoft, generic OIDC via authlib)
- **Packaging**: Installable by other orgs — documented setup, seeded sample data, env var configuration

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Manifest schema lives in the CLI package, not backend internals | `geolens init` and `geolens validate` must work offline and stay Apache-2.0 Community-safe | ✓ Good — v13.7 schema/fixtures/validation helpers run without backend, SDK, DB, GDAL, rasterio, or Enterprise imports |
| Manifest apply reuses existing ingest/catalog contracts | Avoid a parallel ingestion stack while giving users a declarative first-catalog workflow | ✓ Good — v13.7 apply service preserves auth, upload permission, storage/file safety, idempotency, vector/raster/VRT ingest, search, and preview behavior |
| Manifest adoption is locked by examples plus generated contracts | First-catalog workflow must be both human-followable and API/SDK-visible | ✓ Good — v13.7 docs/examples, OpenAPI, Python SDK, TypeScript SDK, CI gates, and close audit cover the apply path |
| Maps/search service modules use thin public facades | Preserve stable imports for routers, AI, OGC/STAC, and tests while making implementation files small enough to maintain | ✓ Good — v13.6 facade export tests plus private-module import guards protect the contract |
| AST-based private-module guards over grep checks | Covers all Python import shapes without brittle line-pattern assumptions | ✓ Good — v13.6 guards catch direct external imports of private maps/search split modules |
| Explicit per-file size budgets for maps/search service modules | Prevents facade regrowth while allowing reviewed exceptions for known larger private modules | ✓ Good — v13.6 guard enforces thin facades and bounded private modules |
| Behavior-focused VRT/search tests over source introspection | Source checks became brittle after decomposition; helper/facade behavior is the real public contract | ✓ Good — v13.6 replaced search source-inspection assertions with contract tests |
| Record broader gate failures instead of expanding v13.6 scope | Full backend/Playwright failures were outside the owned maps/search decomposition surface | ✓ Good — Phase 240 documents exact blockers while focused v13.6-owned gates pass |
| pg_featureserv + pg_tileserv over custom serving | Eliminates custom geospatial plumbing, OGC-compliant out of the box | ✓ Good initially — pg_featureserv replaced by native FastAPI in v2.2, pg_tileserv replaced by FastAPI tile gateway (ST_AsMVT) in v7.0 |
| PostgreSQL full-text search over OpenSearch | Keeps deployment to a single stateful system, sufficient for < 50 datasets | ✓ Good — sub-second search with tsvector generated columns and GIN index |
| Local auth first, OIDC later | Simplifies MVP, avoids IdP dependency for pilots | ✓ Good — AuthProvider Protocol enables OIDC swap without downstream changes |
| ogr2ogr for ingestion/export | Battle-tested format conversion, avoids bespoke writers | ✓ Good — handles 4 formats + CRS reprojection reliably |
| Docker Compose first, Helm later | Fastest path to deployable pilot | ✓ Good — single-command deployment verified |
| React + MapLibre GL JS for frontend | Strong ecosystem, performant vector tile rendering | ✓ Good — smooth pan/zoom with geometry-aware styling |
| Procrastinate over arq/Celery for job queue | PG-native, no Redis dependency, keeps single-database architecture | ✓ Good — async task processing with no additional services |
| Schema separation (catalog + data) | Isolate metadata from user data, least-privilege for tile/feature services | ✓ Good — tile queries use geolens_reader role with data schema only |
| Nginx auth_request for OGC service RBAC | Enforces access control without modifying pg_tileserv | Superseded — replaced by signed tile URLs (HMAC) in v7.0; nginx removed from topology |
| SVG bbox preview over WebGL mini-maps | Avoids WebGL context exhaustion on search result cards | ✓ Good — lightweight, no GPU resource contention |
| pygeofilter over custom CQL2 parser | Python CQL2 parser with SQLAlchemy backend, avoids building parser from scratch | ✓ Good — full CQL2 text + JSON support with minimal code |
| CQL2 filter applied after RBAC visibility | Prevents data leakage through crafted CQL2 queries | ✓ Good — RBAC always restricts results first |
| API key auth via SHA-256 hash | Raw key shown only at creation, stored as hash for security | ✓ Good — keys inherit user roles, no separate permission model |
| Pydantic model_json_schema() for queryables | Generates JSON Schema from existing model, avoids manual schema maintenance | ✓ Good — schema stays in sync with model automatically |
| ON CONFLICT upsert for saved searches | Constraint-based dedup avoids race conditions vs check-then-insert | ✓ Good — atomic, no duplicate rows possible |
| Dedicated geolens_test database for tests | Complete isolation from dev DB, session-scoped create/migrate/drop | ✓ Good — zero test pollution in dev, clean state each run |
| EXISTS subquery for storage stat | Filter to existing tables before pg_total_relation_size, one orphan doesn't zero total | ✓ Good — resilient to dataset records referencing dropped tables |
| User status column (pending/active/rejected/suspended) | Self-registration requires approval flow states beyond boolean is_active | ✓ Good — clean state machine, distinct error messages per status |
| 403 for deactivated users (not 401) | Credentials valid but access denied — semantically correct HTTP status | ✓ Good — clear distinction between bad credentials and denied access |
| Server-side ogrinfo for import preview | Avoids shipping GDAL to browser, leverages existing ogr2ogr infrastructure | ✓ Good — reliable format detection with zero client-side dependencies |
| User metadata as JSONB on IngestJob | Flexible key-value storage for user-edited name/description/tags/CRS without schema changes | ✓ Good — extensible, no migration needed for new metadata fields |
| Staging files preserved on failure | Enables retry without re-upload by keeping uploaded file on disk | ✓ Good — retry works instantly, no bandwidth wasted |
| Promise.allSettled for bulk upload | Parallel uploads with independent failure handling per file | ✓ Good — one failed file doesn't block others |
| outerjoin for admin jobs user lookup | created_by is nullable (SET NULL on user delete), inner join would drop orphaned jobs | ✓ Good — admin sees all jobs even after user deletion |
| Vitest with jsdom + module-level MapLibre mock | MapLibre GL crashes jsdom; mock at module level avoids import errors | ✓ Good — 37 tests pass, no WebGL context needed |
| structlog with ProcessorFormatter bridge | Existing stdlib loggers produce structured output without code changes | ✓ Good — JSON/console toggle via LOG_JSON env var |
| pg_dump -Fc for backups | Custom format enables compressed backups with selective restore | ✓ Good — reliable backup/restore with retention rotation |
| Playwright at project root (not frontend/) | E2E tests span full stack, not just frontend | ✓ Good — shared storageState, single config, Makefile target |
| storageState pattern for E2E auth | Login once in setup, reuse session across all tests | ✓ Good — fast test execution, auth spec overrides for login testing |
| CI coverage flags only (not in pytest addopts) | Avoids slowing local development with coverage instrumentation | ✓ Good — local dev fast, CI gets coverage reports |
| Dual Playwright reporter in CI | GitHub annotations + HTML report for CI debugging | ✓ Good — meaningful artifact upload, annotations in PR checks |
| Compute-on-read for collection extents | Aggregate bbox/temporal from member datasets at query time | ✓ Good — matches existing patterns, no denormalization needed at current scale |
| Atomic table swap for re-upload | ogr2ogr into staging table, then RENAME in single transaction | ✓ Good — tile/feature services never see partial data, zero downtime |
| Separate reupload_file Procrastinate task | Dedicated task vs branching existing ingest_file | ✓ Good — clean separation, no regression risk to ingestion |
| Synthesized Version 1 in frontend | VersionHistory creates v1 from dataset metadata when API has no version record | ✓ Good — existing datasets show version history without backfill migration |
| /catalog/collections router prefix | Avoids collision with OGC /collections router | ✓ Good — clean namespace separation, OGC collection endpoints remain available for future |
| OKLCH color space with @theme inline | Perceptually uniform, opacity modifiers via oklch(), reactive var() references | ✓ Good — consistent status colors, smooth gradient support |
| Inter variable font via @fontsource-variable | Self-hosted, no CDN dependency, variable weight support | ✓ Good — consistent typography across all pages |
| tw-animate-css for shadcn/ui animations | Drop-in animation fix, no framer-motion overhead | ✓ Good — dialogs, tooltips, dropdowns animate correctly |
| PageShell + PageHeader shared components | Enforce consistent layout without per-page inline styles | ✓ Good — all 6 authenticated pages use shared layout |
| Centralized status-colors.ts | Single source for all status badge colors | ✓ Good — zero hardcoded hex values in component files |
| Atomic AppLayout → PageShell migration | All pages migrated in single commit to avoid inconsistent state | ✓ Good — no intermediate broken states |
| Static dataset manifest over HTML scraping | NE releases are infrequent, hardcoded list is more reliable than parsing CDN pages | ✓ Good — 130 datasets, no fragile HTML parsing |
| srid_override=4326 for all NE datasets | All Natural Earth data is WGS84, avoids CRS auto-detection failures on .prj-less ZIPs | ✓ Good — consistent ingest across all datasets |
| httpx as sole external dependency (KISS) | Removed rich/tenacity for simplicity; hand-rolled retry equivalent to tenacity | ✓ Good — minimal dependency footprint |
| asyncio.TaskGroup + Semaphore(3) concurrency | Bounded parallelism without thread pool complexity | ✓ Good — ~3x speedup, per-task exception isolation |
| Atomic cache writes via tmp+rename | Prevents half-written ZIPs on interruption | ✓ Good — safe resume after Ctrl+C |
| 409 → GET fallback for collection idempotency | Create-or-get pattern avoids duplicate collections on re-run | ✓ Good — clean idempotency without pre-check race |
| ipaddress stdlib for SSRF validation | No external dep, covers all private ranges + link-local | ✓ Good — clean security gate, frozenset scheme allowlist |
| defusedxml for WFS XML parsing | Prevents XXE/billion laughs on untrusted WFS GetCapabilities | ✓ Good — drop-in replacement for ElementTree |
| httpx for async probe requests | Already in ecosystem, async-native, follows redirects | ✓ Good — clean timeout handling, Bearer header support |
| GDAL_HTTP_HEADERS env var for WFS auth | ogr2ogr/ogrinfo subprocess inherits Bearer token without URL mutation | ✓ Good — clean separation, token stays in headers not URLs |
| ArcGIS token as query parameter | ArcGIS REST API requires `&token=` on URL, not headers | ✓ Good — matches ArcGIS convention, works for all ArcGIS endpoints |
| model_dump(exclude={"token"}) for DB safety | Prevents token from reaching user_metadata, logs, or audit | ✓ Good — single exclusion point, no token in any persistent store |
| -t_srs EPSG:4326 for all service imports | Forces reprojection at import time, avoids SRID mismatch crashes | ✓ Good — consistent geom_4326 column regardless of source CRS |
| Procrastinate task args for token passing | Token in task args is transient (not persisted after execution) | ✓ Good — no DB storage, retry requires re-import by design |
| Native FastAPI feature endpoints over pg_featureserv | Reduces service count, simplifies RBAC, eliminates nginx auth_request for features | ✓ Good — 5-service stack, RBAC in FastAPI code, zero pg_featureserv maintenance |
| ST_AsGeoJSON + to_jsonb raw SQL for feature serving | Direct PostGIS rendering avoids ORM overhead and complex geometry serialization | ✓ Good — clean GeoJSON output with bbox/property filtering, matches OGC API Features structure |
| python-slugify for table naming | ASCII transliteration, underscore separator, 60-char max | ✓ Good — human-readable PostGIS tables (us_state_capitals vs ds_a1b2c3d4e5f6) |
| Collision suffix (_2, _3) with warning propagation | Avoids unique constraint errors while informing user of name adjustment | ✓ Good — warning stored in job metadata, surfaced via toast in frontend |
| information_schema discovery for unregistered tables | Standard SQL metadata tables, LEFT JOIN catalog.datasets to find gaps | ✓ Good — discovers tables regardless of how they were loaded into PostGIS |
| Per-table error isolation in bulk register | Independent try/except + commit/rollback per table in loop | ✓ Good — one failing table does not block others |
| POINT extent guard in create_dataset | Only set extent when WKT starts with POLYGON, skip degenerate POINT extents | ✓ Good — prevents Geometry(Polygon) type mismatch crash for single-point tables |
| Terra Draw (v1.25.0) for drawing library | Only MapLibre-compatible open-source option (MIT, OSGeo) | ✓ Good — polygon/line/point/rectangle/circle/freehand modes, select mode for editing |
| Zero new backend deps for feature CRUD | PostGIS ST_GeomFromGeoJSON + SQLAlchemy text() | ✓ Good — no ORM overhead, direct GeoJSON-to-PostGIS pipeline |
| useMemo for Terra Draw React integration | Tied to map instance, not useEffect, per terra-draw#197 | ✓ Good — prevents re-render bugs with @vis.gl/react-maplibre v8 |
| useRef for onFinish/onEditFinish callbacks | Avoids stale closures without triggering event listener re-registration | ✓ Good — clean callback pattern for Terra Draw event handlers |
| Ephemeral drawing store (no persist) | Drawing state should not survive page reload | ✓ Good — zustand store without persist middleware |
| Single-to-multi geometry promotion on INSERT | Terra Draw draws single geometries, promote to Multi for PostGIS | ✓ Good — ST_Multi wraps geometry transparently |
| Snapshot-based undo over command pattern | getSnapshot/clear/addFeatures simpler than command stack | ✓ Good — clean Terra Draw integration, history resets on mode change |
| ALTER TABLE for column CRUD | Strict regex + type whitelist prevents SQL injection | ✓ Good — defense-in-depth with Pydantic validation + service layer check |
| Tile filter per-layer for edit isolation | setFilter with gid exclusion hides original during editing | ✓ Good — no source removal avoids flickering |
| shadcn/ui ThemeProvider for dark mode | Zero new dependencies, ~40 LOC, `.dark` CSS class toggle | ✓ Good — FOUC-free with blocking inline script in index.html |
| OKLCH charcoal dark mode base (0.178 0.005 285) | Cool blue undertone distinguishes from pure black, perceptually uniform | ✓ Good — distinctive dark palette |
| DropdownMenu for theme toggle (not switch) | Clean 3-way selection (light/dark/system) without ambiguity | ✓ Good — system preference detection works correctly |
| transformStyle for basemap switching | Preserves all custom layers (tiles, drawings, highlights) across setStyle() | ✓ Good — zero layer loss during theme-based basemap switch |
| Sidebar CSS with oklch (not shadcn HSL defaults) | Design token consistency with existing OKLCH color space | ✓ Good — fixed outline variant hsl() wrapper to raw var() |
| catalog.app_settings JSONB for site-wide settings | Reuse existing settings store, no new tables | ✓ Good — basemaps, map defaults, feature toggles all use same store with TTL cache |
| Public GET endpoints for basemaps/map-defaults | Public viewer needs basemaps without auth | ✓ Good — only GET is public, PUT requires admin |
| XYZ-to-StyleSpecification conversion for raster tiles | OSM/Stamen use {z}/{x}/{y} URLs not .json style specs | ✓ Good — inline StyleSpecification with type: 'raster' source |
| Legacy basemap key mapping (positron→carto-positron) | Existing maps reference old basemap keys | ✓ Good — resolveBasemapId() handles backward compatibility |
| Registration toggle DB-backed with env var fallback | New installs use env var until first admin save | ✓ Good — smooth migration from static config to dynamic settings |
| obstore for S3 over boto3 | Rust-backed, async, provider-agnostic | ✓ Good — clean async file I/O with local and S3 backends |
| nginx proxy_cache for tiles over Varnish | Zero new services, existing nginx handles it | ✓ Good — RBAC-safe caching with user ID in cache key |
| Opaque refresh tokens with DB hash over JWT refresh | Revocable, auditable, no client-side token parsing | ✓ Good — SHA-256 hash stored, rotation on each refresh |
| puremagic for magic byte detection | Pure Python, no libmagic C dependency | ✓ Good — works in all Docker environments without system packages |
| prometheus-fastapi-instrumentator | Automatic HTTP metrics with minimal code | ✓ Good — histograms, counters, and custom collectors all on /metrics |
| Supercronic sidecar for backups | No custom Dockerfile needed, cron in container | ✓ Good — configurable schedule, S3 upload, retention policies |
| Circuit breaker for Redis cache | Auto-fallback to in-memory on Redis failure | ✓ Good — 5-failure threshold, 30s cooldown, health check bypasses breaker |
| Keep pg_tileserv over Martin | Purpose-built, good RBAC via nginx auth_request | Superseded — replaced by FastAPI tile gateway (ST_AsMVT) in v7.0 for cloud-native deployment |
| Centralized buildDatasetEditCapabilities | Single role-to-field editability source for all affordances | ✓ Good — consistent editable/read-only behavior across detail surfaces |
| Segmented edit context with controlled toggle-group | Prevents accidental empty deselection, enforces single-active context | ✓ Good — clean Geometry/Attributes/Metadata switching with dirty guardrails |
| Shared _apply_reupload_swap for file and service paths | DRY atomic swap, metadata refresh, quality recompute, version insertion | ✓ Good — both re-upload sources share identical post-commit invariants |
| Request-only token forwarding for service re-upload | Never persist credentials; user must re-supply token for retry | ✓ Good — zero secret storage risk, clear ephemeral security model |
| Centralized provenance actor resolver | Single fallback/redacted/never-edited derivation for detail and search | ✓ Good — consistent attribution formatting across all surfaces |
| In-transaction provenance stamping | Metadata writes stamp updated_by atomically with content mutation | ✓ Good — no provenance gaps from partial commits |
| Flat admin sidebar with SidebarSeparator | Settings children promoted to top-level, no click-through parent group | ✓ Good — 12 items with visual grouping divider |
| PersistentConfig[T] generic with env_default_factory | Dynamic defaults via callable, preserves test compatibility | ✓ Good — 16 config instances across 6 tabs |
| Scalar config values wrapped in {"v": value} JSONB | AppSetting stores JSONB, scalars need wrapping | ✓ Good — clean round-trip for all value types |
| DynamicCORSMiddleware always added (unconditional) | Empty origins = passthrough, no conditional middleware registration | ✓ Good — hot-reloadable CORS from PersistentConfig |
| require_permission() replacing require_role() | Capability-based access control enables admin-configurable permissions | ✓ Good — ~80 endpoints migrated across 13 routers |
| Fernet key derived from JWT_SECRET_KEY via HKDF | Cryptographic separation without additional secret management | ✓ Good — OAuth client secrets encrypted at rest |
| OAuth client built fresh per request (stateless) | No cached IdP state, clean per-request isolation | ✓ Good — authlib starlette integration works cleanly |
| Config import validates role_permissions before applying | Lockout prevention — unknown keys silently skipped for forward compat | ✓ Good — safe multi-instance config transfer |
| Vector dimension 1536 default with configurable EMBEDDING_DIMS | Matches text-embedding-3-small, most common embedding model | ✓ Good — PersistentConfig allows runtime override |
| HNSW index with m=16, ef_construction=64 | Balanced insert/query performance for catalog-scale datasets | ✓ Good — sub-second similarity queries |
| Content hash dedup for embeddings | Prevents redundant API calls when metadata unchanged | ✓ Good — significant cost savings on updates |
| Non-fatal embedding hooks via try/except | Embedding generation should never block ingestion | ✓ Good — zero ingestion failures from embedding errors |
| RRF k=60 for hybrid FTS+vector fusion | Standard RRF constant, balanced weighting of FTS and vector scores | ✓ Good — relevant results for both exact and conceptual queries |
| Cosine distance threshold 0.7 (similarity >= 0.3) | Filter noise from low-similarity vector results | ✓ Good — reused for both search and related datasets |
| Over-fetch limit*3 then RBAC filter for related datasets | Ensures enough results after permission filtering | ✓ Good — consistent top-N results across roles |
| Self-hiding card pattern for related datasets | Component returns null on loading/error/empty | ✓ Good — clean UX, no skeleton or toast clutter |
| expires_at=None in PATCH body removes expiration | Matches existing ShareTokenCreateRequest pattern | ✓ Good — consistent null semantics for "never expires" |
| Reuse origin validation in EmbedTokenUpdate | Same urlparse logic as EmbedTokenCreate | ✓ Good — consistent origin normalization |
| Only active tokens can be updated | Inactive/revoked tokens return 404 on PATCH | ✓ Good — prevents stale token modification |
| EmbedTokenResponse type (without raw_token) | Non-create responses don't include the raw token | ✓ Good — clean separation of create vs list types |
| Inline editing: clickable text toggles to input | Dotted-underline hint, check-mark save button | ✓ Good — discoverable without cluttering read-only view |
| ADR-001 for v12.0 locked decisions | 8 architectural decisions documented in single ADR before implementation | ✓ Good — clear guidance for all implementation phases |
| Record type taxonomy (4 types) | collection, vector_dataset, raster_dataset, vrt_dataset as discriminator enum | ✓ Good — clean type-aware branching throughout stack |
| Publication lifecycle enum | draft/ready/internal/published with ALLOWED_TRANSITIONS state machine | ✓ Good — frontend PublishButton sequences through all states |
| Separate /stac/ router | Isolated STAC API from OGC Records, clean concern separation | ✓ Good — independent STAC conformance, no OGC Record pollution |
| Multi-group facets in single endpoint | /search/facets returns record_type + keywords + org + srid in one call | ✓ Good — single network round-trip for all facet data |
| Aliased subqueries for facet counts | RecordKeyword alias avoids SQLAlchemy auto-correlation bugs | ✓ Good — correct counts with DRY filter application |
| Type-specific detail panels | Shared skeleton dispatches to VectorDetailPanel/RasterDetailPanel/VrtDetailPanel/CollectionDetailPanel | ✓ Good — each panel owns its tabs and content |
| Sequential status mutations via mutateAsync | PublishButton loops through intermediate states to comply with state machine | ✓ Good — backend enforces one-step transitions, frontend sequences them |
| sqlglot for SQL AST validation | Parse SQL to AST, enforce single-SELECT, extract table refs | ✓ Good — rejects writes/DDL/multi-statement at AST level |
| Dataclass for ValidatedQuery over Pydantic | Lightweight internal type, no serialization needed | ✓ Good — minimal overhead for internal pipeline |
| CTE alias exclusion from table access checks | find_all(exp.CTE) extracts aliases, prevents false rejections | ✓ Good — CTEs work correctly in sandbox queries |
| Dedicated engine.connect() for sandbox execution | Avoids transaction conflicts with caller's session | ✓ Good — clean isolation with own READ ONLY transaction |
| LIMIT N+1 fetch for row cap | Extra row signals truncation without count overhead | ✓ Good — client-aware truncation flag on SandboxResult |
| Error sanitization by exception type matching | Generic user messages, full details logged via structlog | ✓ Good — no internal details leak to users |
| COG-as-file storage model | Pixels in managed file/S3 store, metadata/footprint in PostGIS | ✓ Good — avoids PostGIS Raster bloat, clean separation |
| Separate Titiler raster tile service | Internal Docker service, no external port exposure | ✓ Good — auth-unaware Titiler with credential isolation |
| record_type discriminator on datasets | NOT NULL DEFAULT 'vector_dataset', drives conditional rendering | ✓ Good — clean raster/vector branching throughout stack |
| RBAC at GeoLens API, Titiler auth-unaware | Token endpoint validates access, embeds service credential in URL | ✓ Good — browser never sees Titiler credentials |
| Separate ingest_raster Procrastinate task | Dedicated task vs branching existing ingest_file | ✓ Good — clean separation, no regression risk |
| COG conversion via subprocess with GDAL_CACHEMAX limit | Prevents OOM in worker container | ✓ Good — safe resource isolation |
| Raster layers opacity-only for MVP | No band math or color ramps | ✓ Good — ships value fast, defers complexity |
| TileToken discriminated union (Vector/Raster) | kind field gates raster vs vector code paths | ✓ Good — type-safe frontend branching |

| pg_stat_statements + auto_explain for query profiling | Database-side profiling with no application code changes | ✓ Good — 5000 max, 100ms threshold, buffers+analyze |
| Locust function-based tasks over TaskSet classes | Simpler Locust 2.x pattern, easier to maintain | ✓ Good — clean per-endpoint scenario modules |
| Weighted traffic: tiles 40%, search 30%, browse 20%, detail 10% | Reflects real usage patterns where tiles are the hot path | ✓ Good — realistic load distribution |
| Synthetic seed via NE geometry jitter oversampling | Generates varied datasets from real geometries without external data | ✓ Good — 1000+ datasets with 4 geometry types |
| Warm-up + reset before measured run | Isolates cache-warm steady-state from cold-start noise | ✓ Good — pg_stat_statements reset after warm-up |
| Export p95=1200ms as top optimization target | ogr2ogr conversion overhead dominates export latency | Pending — Phase 180 should investigate |
| decode_responses=False for binary tile cache | MVT tiles are binary, JSON decode would corrupt | ✓ Good — separate TileCacheProvider from main RedisCacheProvider |
| Cache compressed gzip bytes in tile cache | Skip re-compression on cache hits | ✓ Good — 27% p50 tile latency improvement |
| Simple try/except for tile cache degradation | Advisory cache doesn't warrant circuit breaker complexity | ✓ Good — graceful fallback when Redis unavailable |
| Keep DB_POOL_SIZE=10 default | 40% utilization under 10-user load, zero overflow | ✓ Good — validated by Prometheus evidence |
| Keep TILE_CACHE_TTL=300s | Appropriate for infrequently-changing vector data | ✓ Good — balances freshness and performance |
| aria-label={t()} on all icon buttons | i18n-ready accessibility, consistent with existing patterns | ✓ Good — 10 components updated, screen reader support |
| variant="destructive" on AlertDialogAction | Replaces inline className with shadcn semantic variant | ✓ Good — 7 dialogs standardized |
| Loader2 spinner on all submit buttons | Consistent loading feedback across all forms and dialogs | ✓ Good — 11 buttons updated |
| space-y-2 / space-y-4 form spacing contract | Eliminates per-file spacing decisions | ✓ Good — 6 form components standardized |
| 4-tier icon size system (h-3/h-4/size-8/size-10) | Reduces cognitive load for icon sizing decisions | ✓ Good — 7 off-tier icons fixed |
| useDocumentTitle hook on all pages | Centralized title management with " - GeoLens" suffix | ✓ Good — 18 pages with descriptive browser tab titles |
| formatDateTimeSmart with toDateString() comparison | Simple today/yesterday detection without date library dependency | ✓ Good — 6 test cases covering all branches |
| Client-side collection search (limit=200 fetch-all) | Small collection counts don't justify server-side search endpoint | ✓ Good — instant filter with i18n empty state |
| overflow-x-auto on TabsList for responsive tabs | CSS-only solution, no JavaScript resize observer needed | ✓ Good — 4 detail panels responsive at 400px |
| min-h-11 + snap-x on TabsList for mobile touch targets | CSS-only 44px targets with scroll-snap; no JS resize observer | ✓ Good — verified 44px at 375px viewport |
| Gradient fade overlay for tab scroll affordance | CSS-only aria-hidden div, no scroll event listener | ✓ Good — zero JS overhead, subtle UX hint |
| tabIndex=0 + role=region on Table container | Standard WAI-ARIA pattern for scrollable regions | ✓ Good — keyboard accessible in all Table consumers |
| vrtGenerationColors centralized semantic map | Single source for VRT badge colors instead of inline Tailwind | ✓ Good — WCAG AA in light and dark themes |
| dl/dt/dd for collection metadata (not table/grid) | Semantic HTML for screen readers, natural responsive reflow | ✓ Good — 5 terms render with aria-label |
| flex-col md:flex-row on DatasetDetailHeader | Mobile stacking without JS breakpoint detection | ✓ Good — no overflow at 375px on any record type |
| flex-wrap replacing flex-shrink-0 on action containers | Buttons wrap instead of squeezing title; same fix on PageHeader | ✓ Good — applies to both dataset and collection headers |
| Hero state machine (loading/loaded/error) for raster/VRT | Explicit 3-state with bounded retry budget (3 attempts) | ✓ Good — no infinite spinners or blank areas |
| useEffect ordering: id-reset before no-tile skip | Prevents stale heroState when navigating between datasets | ✓ Good — effect dependency arrays are minimal and correct |
| useBuilderLayout hook with container queries | Responsive builder without media queries; isCompact drives sidebar/chat layout | ✓ Good — single source of layout truth |
| inert attribute on collapsed sidebar (not aria-hidden) | Removes all children from tab order AND screen reader tree atomically | ✓ Good — React 19 supports inert natively |
| 3 composable hooks from MapBuilderPage | useBuilderDialogs, useBuilderLayers, useBuilderSave — 1131→481 lines | ✓ Good — each hook independently testable |
| getLayerCapabilities shared capability model | Single function returns edit/style/export capabilities per layer type | ✓ Good — eliminated 4 inline type-checking branches |
| data-testid on interactive test targets | Explicit test selectors instead of fragile DOM structure queries | ✓ Good — basemap test no longer vacuously passes |
| v1003 hardens the shipped v1002 builder surfaces before adding new renderer capabilities | The sidebar/modal rewrite changed high-frequency authoring workflows; durable browser evidence should precede Cluster/Hexbin/H3/timeline or catalog-contract expansion | ✓ Good — v1003 shipped with browser, accessibility, save/reload, and viewer compatibility evidence |
| v1005 clusters only bounded point datasets through MapLibre GeoJSON clustering | Current catalog delivery is vector-tile-first, so large datasets need server-side clustering before unconditional cluster UX | ✓ Good — shipped native Cluster safely without schema changes or new renderer dependencies |
| Style JSON preserves Cluster intent metadata with Point fallback | Standalone MapLibre style JSON cannot embed authenticated bounded GeoJSON; preserving intent keeps round-trip fidelity without broken exported maps | ✓ Good — backend export/import tests lock the policy |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-24 — started milestone v1024 ADK High Peaks Marketing-Ready. Scope: TNM/NAIP aerial attempt or documented TNM no-data fallback, NHD hydrography, expanded 46er peak data, primary + bonus 3D relief ADK maps, builder mixed raster/vector reorder, terrain DEM zoom/config reliability, builder error hygiene, and Playwright MCP map-builder smoke. Phase numbering continues from 1101. Public tag target: `v1.5.9`. Source context: `.planning/quick/260524-o57-adk-high-peaks-data/`. Previously: v1023 CI Live-Verify + OOS Hygiene Tail shipped degraded on 2026-05-24 with local/public tags `v1023` + `v1.5.8` at `892fca01`; CI-01 live GitHub Actions verification remains an external billing-block carry-forward to v1024+ but is not part of this ADK marketing-ready hard invariant.*
