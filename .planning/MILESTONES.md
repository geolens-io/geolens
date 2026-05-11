# Milestones

## v1001 Map Builder UI/UX Polish Sweep (Shipped: 2026-05-11)

**Delivered:** A coherent builder polish sweep across workflow audit, Map Stack/inspector interactions, styling controls, save/share/public output parity, responsive/accessibility/copy hardening, and durable QA gates.

**Stats:**

- **Phases:** 6 (1002-1007)
- **Plans:** 8 / 8 complete
- **Requirements:** 38/38 satisfied (FLOW-01..06, STACK-01..06, STYLE-01..08, OUTPUT-01..06, A11Y-01..06, QA-01..06)
- **Audit:** passed / GO

**Key accomplishments:**

1. **Builder workflow audit completed** — Phase 1002 captured create, add-data, edit-layer, style, preview, save, share, public-viewer, state, and Kepler-behavior findings with evidence.
2. **Map Stack and inspector polished** — stable add-layer order, data-first empty map affordance, visible row states, and keyboard-focused inspector controls.
3. **Styling controls clarified** — visual-intent grouping, pending geometry swatches, recoverable data-driven/raster validation, scoped filter/label/popup copy, and contract-preserving tests.
4. **Output parity hardened** — public/shared/embed viewer layer identity uses stable IDs, shared-token payloads include layer IDs, and builder save/share states explain publication lag.
5. **Responsive and accessibility shell hardened** — auth route state restores user before editor chrome, mobile sheets leave more map context, touch targets meet 44px, and basemap recovery copy is localized.
6. **Durable QA gate shipped** — focused Vitest, builder Playwright, builder/public accessibility, and builder smoke pass; sidebar drag-handle flake replaced by keyboard resize coverage.

**Known deferred items at close:**

- Full `npm run e2e:smoke` core segment still has a collections Add-button seed/UI drift unrelated to builder QA; builder smoke passes directly.
- Demo-themed map smoke remains opt-in with `E2E_DEMO_SEEDED=1`.
- No broad screenshot regression gallery was created because Phase 1007 used state, ARIA, accessibility, and behavior assertions instead.

**Archives:**

- `.planning/milestones/v1001-ROADMAP.md`
- `.planning/milestones/v1001-REQUIREMENTS.md`
- `.planning/milestones/v1001-MILESTONE-AUDIT.md`

---

## v1000 Map Stack and Basemap Layer Controls (Shipped: 2026-05-11)

**Delivered:** Unified Map Stack authoring, curated basemap appearance persistence, public-viewer rendering parity, and authenticated public DEM metadata preservation.

**Stats:**

- **Phases:** 2 (1000-1001)
- **Plans:** 7 / 7 complete
- **Tasks:** 27 complete
- **Requirements:** 7/7 satisfied (MAPSTACK-01..07)
- **Audit:** `tech_debt` / `COMPLETE_WITH_TECH_DEBT_REVIEW`

**Key accomplishments:**

1. **Unified Map Stack UX shipped** — Surface, Relief, Basemap, Data, Labels, and Interactions now share one builder stack model and inspector surface.
2. **Layer-management blockers closed** — mobile layer editing, collapsed basemap disclosure hiding, filter readability, duplicate layer disambiguation, and accessible switch names are covered.
3. **Basemap appearance persisted** — nullable `basemap_config` stores curated label/road/boundary/building/tone/relief settings while preserving legacy saved-map behavior.
4. **Public viewers aligned with builder output** — shared-token and authenticated public viewers pass `basemap_config` into `ViewerMap`, which reapplies the same MapLibre transforms used by the builder.
5. **Relief semantics clarified** — DEM terrain is presented as an elevation surface, and hillshade/color/contour outputs are presented as relief overlays.
6. **Authenticated public DEM gap closed** — `PublicMapViewerPage.toSharedLayer` preserves `is_dem` and `dem_vertical_units`, with a focused positive DEM fixture test.
7. **Test-health debt fixed during closeout** — the `map-stack` test helper now carries `basemap_config`; focused public-viewer/map-stack tests pass 9/9.

**Known deferred items at close:**

- Unrelated generated SDK drift remains for dataset `tile_columns` and the `/maps/{map_id}/layers` route description.
- Visual QA evidence is screenshot-based, not a durable automated visual regression gate.
- Seeded demo-map E2E remains gated by `E2E_DEMO_SEEDED=1`.
- Full backend, frontend coverage, SDK, and E2E release gates were not rerun for this closeout.

**Tag:** `v1000`

---

## v13.13 Backlog Sweep (Shipped: 2026-05-07)

**Milestone goal:** Work through the 154 Medium+Low findings deferred from v13.12's 17-audit sweep, grouped by domain affinity, with autonomous execution and Playwright MCP UAT for frontend-touching changes.

**Stats:**

- **Phases:** 9 (271 DB, 272 Docker, 273 Security, 274 Performance, 275 API/Docs, 276 Code Quality, 277 i18n/Env, 278 Tests, 279 Admin/Close)
- **Plans:** 51 (avg 5.7 plans/phase)
- **Timeline:** 2026-05-07 (single autonomous orchestration session)
- **Commits:** ~106 source-file commits in milestone range
- **Audit:** **passed** — composite grade **A**, recommendation **GO**

**Requirements:** 130/130 satisfied — DBM-01..09, INF-01..16, SEC-01..17, PERF-01..11, API-01..14, CODE-01..14, CONF-01..15, TEST-01..10, ADMIN-01..13, CLOSE-01..05.

**Key accomplishments:**

1. **Frontend bundle wins:** map-vendor 1052kB chunk lazy-loaded off non-map routes (PERF-06); DatasetPage bundle 217kB → 34kB raw (-84%, CODE-06); AttributeTable virtualized via @tanstack/react-virtual (PERF-07); preserveDrawingBuffer dropped + capture moved to triggerRepaint+once('render') pattern (PERF-08).
2. **Backend code quality:** chat_service.py 1013 LOC decomposed into 5 sub-modules <400 LOC each behind a Phase-226 facade (CODE-02); 113 broad-except sites annotated + architecture-guard test (CODE-08); 1500-LOC cap on routers with allowlist for over-cap routers; cross-feature stores relocated to `src/stores/` (CODE-05).
3. **Security defense-in-depth:** SVG sanitization (defusedxml + CSP `default-src 'none'; sandbox`); download-scoped JWT `typ:download` ≤2min TTL; 32-byte share-token entropy; origin-allowlist enforcement; SSRF re-validation on COG redirect; SessionMiddleware https_only; OAuth Referrer-Policy: no-referrer; structlog field redaction; embed-iframe sandbox tightened; PIL.Image.verify() thumbnail gate; .env.example admin defaults emptied. 15/17 SEC-* satisfied; SEC-14 (CI pip CVE carve-out removal) deferred per safety caveat.
4. **Performance polish:** in-memory LRU tile cache fallback when Redis unset; `_bulk_fetch_dataset_metadata` parallelized via asyncio.gather; ingest 4 sequential post-COPY scans → single CTE; AI chat schema cache partitioned on `(map_id, content_hash)`; has_embeddings cache partitioned on active embedding model name; max_connections 50 → 30; tile cache Prometheus counters gain `table_name` label.
5. **API contract & docs refresh:** `POST /maps/import` typed body — OpenAPI no longer emits `additionalProperties: true`; CHANGELOG `[Unreleased]` populated with 10 new map-builder routes; README accuracy fixes (count, badge, build time, manifests/public-cog); `docs/api-style.md` documents conventions; demo cluster `getgeolens.io` → `getgeolens.com`; titiler/valkey/uv image pins bumped.
6. **i18n & env standardization:** Builder zoomExpression + symbol + raster + hillshade + uploadIcon translated to es/fr/de — 138 new strings; `WORKER_SHUTDOWN_TIMEOUT` and `ENV_ONLY_CONFIG` migrated to Pydantic Settings; `PUBLIC_BASE_URL` soft-deprecated; `VITE_API_PROXY_TARGET` legacy alias removed.
7. **Test health & coverage:** Backend `--cov-fail-under` 58.5 → 60 (actual=77%); frontend coverage thresholds ratcheted (32/27/27/32 → 41/39/37/42); 6 raw `waitForTimeout` E2E calls → polling; LayerPanel + MapTitleBar new tests; 35 inline `pytest.skip` → decorator form; 6 mock-call-count → behavior assertions; H-33 L144 fixture stabilized.
8. **Admin polish + CI hygiene:** ApiKey `max_length=255`; audit-log search rewritten to `lower(unaccent(...))` form (uses pg_trgm GIN indexes from v13.12 Alembic 0010); AdminAuditPage page-guard; server-driven enterprise-tabs registry; audit-export format dispatcher unified; register_user audit event; delete_user FK SET NULL test-locked; MinIO bumped 2025-04-22 → 2025-09-07 + sha256 digest-pinned; stale CVE-2026-4539 carve-out removed; non-blocking license-checker CI job added.

**Hybrid-shape autonomous orchestration:** 9 domain-grouped phases, each with a planner agent generating 4-8 plans + parallel executor agents per wave. ~30 total agent spawns. Closeout handled inline by orchestrator after planner agent timeout on the closeout plan. Reuses the v13.12 audit-shape with finer-grained per-domain phase boundaries.

**Race-condition notes:** ~10 commit-message orphan attributions across v13.13 (e.g., `docs(275-08)` carrying API-11 source diff) from parallel-agent staging races on a shared working tree. Functional state at HEAD is correct in every case. Same pattern as v13.12 Phase 269.

**Known close caveats:**

- **3 Playwright MCP UAT visual confirmations deferred to manual reviewer:** SEC-07 (embed iframe sandbox), CODE-05 (4-flow store-relocation), TEST-10 (5-run flake-resilience). DOM-level substitute tests landed in each case + reviewer commands documented.
- **SEC-14 deferred:** CI carve-out for pip CVE-2026-6357 retained — runner image still ships pip 26.0.1. Re-attempt after pip 26.1 base-image refresh.
- **Pre-existing test drift surfaced repeatedly out-of-scope:** `preserve-drawing-buffer.test.ts` typecheck error (Phase 274-06 commit `e8d11728`); `test_no_catalog_imports_processing` regex false-positive on a comment line. Trivial cleanup deferred.
- **Backend coverage collection drift:** `tests/test_tile_cache.py` missing `cachetools`; `tests/test_phase_272_compose.py` setup errors. Resolve before next coverage ratchet.

---

## v13.12 Pre-Public Security & Audit Hardening (Shipped: 2026-05-07)

**Milestone goal:** Run a coordinated 17-audit sweep across security, infrastructure, API contracts, documentation, code structure, performance, i18n, and OSS-surface dimensions; remediate every Critical + High finding inline; triage Medium/Low findings to a follow-up backlog with rationale; ship a `PUBLIC-READINESS.md` summary with audit grades and outstanding work before the public-release announcement.

**Stats:**

- **Phases:** 8 (263, 264, 265, 266, 267, 268, 269, 270)
- **Plans:** 17 audit dispatches + 1 triage + 39 atomic fix commits + 3 close documents
- **Timeline:** 2026-05-07 (same-day close)
- **Commits:** ~40 source-file commits in milestone range (`b1888800..edfa13b6` plus `39fcb22b` for PUBLIC-READINESS.md), 5 new Alembic revisions (`0008..0012`)

**Requirements:** 32/32 satisfied (AUDIT-01..17, TRIAGE-01..02, FIX-SEC-01, FIX-OC-01, FIX-INFRA-01, FIX-PERF-01, FIX-API-01, FIX-DOCS-01, FIX-I18N-01, FIX-BACKEND-01, FIX-FRONTEND-01, FIX-TEST-01, VERIFY-01..03)

**Findings:** 193 total — 2 Critical / 37 High / 83 Medium / 71 Low. **2/2 Critical + 37/37 High remediated inline.** 154 Medium+Low routed to backlog.

**Key accomplishments:**

1. **17-audit sweep dispatched and consolidated** — sec-audit, dep-audit, security-review, env-audit, oc-audit, docker-audit, db-audit, migration-audit, api-contract, doc-audit, admin-audit, demo-ready, perf-profile, i18n-audit, backend-audit, frontend-audit, test-audit. All 193 findings consolidated into `FINDINGS-MASTER.md` with severity classification + source-attribution + concrete-fix recommendations.
2. **Critical findings closed (2/2)** — C-01 (README seed-natural-earth bug — extended `scripts/seed-natural-earth.py` with `--username/--password` to preserve single-command UX) and C-02 (tile SQL had no per-tile feature LIMIT and only simplified at z<6; perf marker only tested z=0 — fixed via LIMIT 50000 + per-zoom simplification + new perf markers at z=0/2/4/8).
3. **Security & open-core remediation (FIX-SEC-01 + FIX-OC-01)** — 7 H closures: OAuth `redirect_uri` host-header injection (H-27), `.env.example` JWT secret rejection in validator (H-28), `.env.demo` runtime guard (H-19), manifest `local://` path traversal regex (H-29), OAuth `email_verified` gate (H-30), embed-token Origin loopback gate (H-31), Helm `JWT_SECRET_KEY` rename (H-32). Boundary integrity remained A+/A+/A/A throughout.
4. **Infrastructure remediation (FIX-INFRA-01)** — 8 H closures: 4 new Alembic revisions (`0008` refresh_tokens index, `0009` audit_logs composite indexes, `0010` pg_trgm GIN trigram indexes, `0011` HNSW vector index moved out of lazy app-code), tile pool drops to `geolens_reader` role, duplicate `backend/Dockerfile` deleted, docker-compose memory caps for 2GB VPS, `alembic check` permanently silenced for SAML overlay drift.
5. **API + docs + perf + code remediation (Phase 269)** — 23 closures: PUT thumbnail breaking change CHANGELOG (H-02), `/maps/{id}/layers` slash conflict + `/maps/icons` shadow fixed, `geolens.yaml` first-catalog flow added to README, CONTRIBUTING.md project tree + test commands synced, frontend widgets.md path fixed, PyPI/npm metadata `geolens.io` → `noreply@getgeolens.com`, public operator runbook stubs at `docs/saml.md` + `docs/edition-deactivation.md` + `docs/edition-reactivation.md`, embedding LRU cache (H-22), per-dataset tile_columns allowlist (H-23, new revision `0012`), OGC/STAC keyset cursor + max limit 200 (H-24), perf markers extended to AI/STAC/OGC/raster/ingest (H-25), dataset-domain size-budget guard (H-05), StyleJsonDialog i18n wrapping (H-20), 2 undocumented test.skip rationalized (H-33), `e2e:smoke:audit` script + 5 untracked specs (H-34), CI `e2e-test if:false` rationale documented (H-35), 3 admin-page smoke tests (H-36).
6. **Verification + close (Phase 270)** — `RE-AUDIT.md` confirms 2/2 + 37/37 closures by commit-hash inspection + 7-spot-check sample (all PASS); 0 net-new C+H regressions. `DEFERRED-FINDINGS.md` logs all 154 M+L. `PUBLIC-READINESS.md` ships at repo root (commit `39fcb22b`) with composite grade **A−** and **CONDITIONAL-GO** recommendation.

**Public-release recommendation:** **CONDITIONAL-GO** with 3 deployment-scope conditions:

1. Operators must regenerate `JWT_SECRET_KEY` via `openssl rand -hex 32` if `.env` uses the rejected example default (boot will fail otherwise — H-28)
2. Public repo recreation per `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md` (OSS-01 — separate scope)
3. Populate CHANGELOG `[Unreleased]` and tag v1.1.0 (H-02 PUT thumbnail body change is breaking)

**Hybrid-shape milestone:** 4 audit-dispatch phases (263-266) with 17 parallel investigation agents → 1 triage phase (267) with consolidation agent → 2 remediation phases (268-269) with 6 parallel fix agents (2+4) → 1 verification phase (270) with single closure agent. Total agents-orchestrated: ~24. The audit-dispatch + parallel-remediation pattern is reusable for any future audit-driven hardening milestone.

**Race-condition notes:** 3 commit-message orphan attributions in Phase 269 (H-04 labeled H-01 in `d01a19b8`; SDK regen in `0357f260` swept into H-20 staging; H-16 source change in `2024b0b6` swept into H-34 commit). Functional state at HEAD is correct; CHANGELOG attribution backfills documented.

**Known close caveats:**

- 154 M+L findings deferred via `.planning/backlog/v13.12-medium-findings.md` and `.planning/backlog/v13.12-low-findings.md`. Net unique backlog ~100-110 items after cross-audit dedupes (H-07 absorbs pg_trgm M's, H-08 absorbs HNSW M's, H-26 absorbs H-37 reservation).
- L144 E2E test in `e2e/dataset-detail.spec.ts` re-skipped with rationale + new M-finding for next test-cleanup milestone.
- H-23 admin-UI surface for `tile_columns` deferred (schema + SQL filter ship now; defaults are sensible).
- Distribution gap (Helm + SBOM + signed images + AMI) explicitly OUT OF SCOPE for v13.12 — DIST-01..04 in REQUIREMENTS.md v2 section, recommend follow-up milestone for procurement-driven adopters.

**Known deferred items at close:** 176 (175 cross-milestone `quick_tasks` carried since v13.1 + 1 pending todo `2026-05-05-recreate-public-repo-before-launch.md`) — see STATE.md `## Deferred Items`.

**Verification gates:**

- 138 + 102 + 130 + 14 perf + 17 frontend + 9 admin smoke + 21 architecture-guard tests passing across modules touched
- `make openapi-check` + `make sdks-check` exit 0; zero `WARNING parsing`
- `alembic check` clean post-`0012`
- `docker compose config --quiet` exit 0
- `npm run test:i18n` parity preserved across 4 locales

**Archives:**

- `.planning/milestones/v13.12-ROADMAP.md`
- `.planning/milestones/v13.12-REQUIREMENTS.md`
- `.planning/milestones/v13.12-MILESTONE-AUDIT.md`
- `.planning/audits/v13.12/` — 17 audit reports + FINDINGS-MASTER.md + RE-AUDIT.md + DEFERRED-FINDINGS.md
- `.planning/backlog/v13.12-medium-findings.md` (83 M)
- `.planning/backlog/v13.12-low-findings.md` (71 L)
- `PUBLIC-READINESS.md` (repo root, committed `39fcb22b`)

**Tag:** None (per repo policy 2026-05-06 — `.planning/` gitignored, milestones close locally without commits or tags. Source-file commits in main branch git history.)

---

## v13.11 Map Builder Polish & Quality Sweep (Shipped: 2026-05-07)

**Milestone goal:** Close BUILDER-POLISH-01 (Phase 256 UI audit findings) and the cheap builder-polish backlog — gradient preview swatch + 6 minor `LineGradientControls` UX gaps, advancedHint copy rewrite, real es/fr/de translation of the lineGradient block, builder-wide cursor-pointer + console-warning sweep, Save unsaved indicator, public-vs-builder zoom-control alignment, Label-Layer-toggle bug investigation with a layer-order/visibility audit, and close hygiene retiring BUILDER-POLISH-01 from the deferred ledger.

**Stats:**

- **Phases:** 5 (258, 259, 260, 261, 262)
- **Plans:** 6 (258-01, 258-02, 259-01, 260-01, 261-01, 262-01)
- **Timeline:** 2026-05-07 (same-day close)
- **Commits:** 8 milestone-scoped commits (`a3098856`, `47e72265`, `cc5a7138`, `783abb78`, `fe50961c`, `d9001e87`, `dd90b64b`, `6ef7ab0c`)

**Requirements:** 17/17 satisfied (POLISH-01..07, COPY-01..02, QUALITY-01..04, LAYER-01..02, CLOSE-01..02)

**Key accomplishments:**

1. **Phase 256 UI audit fully closed (BUILDER-POLISH-01 retired)** — gradient preview swatch BLOCKER + 6 minor findings shipped in `LineGradientControls.tsx`. Stable per-stop UUID keys land via optional `id?: string` field on the builder JSONB shape; canonical paint expression byte-identity preserved per v13.9 GRAD-05/06.
2. **EN advancedHint rewrite + es/fr/de translation** — 16-key `lineGradient` block fully translated in 3 locales, replacing English fallbacks. EN copy drops "interpolate-linear-line-progress" jargon for builder-user vocabulary.
3. **Builder quality sweep shipped** — orange `bg-warning` unsaved-changes dot on Save button; `cursor-pointer` added to shadcn Button cva base + 17 builder native-button updates; single unguarded `console.warn` wrapped in `import.meta.env.DEV`; BuilderMap zoom controls realigned to `top-right` matching ViewerMap convention.
4. **Layer visibility debug + audit** — root-caused "Label-Layer toggle not working" as a silent-no-op when `dataset_column_info` was empty (handleLabelChange normalized empty-column to null, snapping the Switch back OFF). Fixed via early bail-out + disabled Switch state. Full audit of visibility code paths (LayerItem Eye, syncLayersToMap, ChatPanel AI tools, render-mode swap, hillshade companion, filter-changes) found no other regressions.
5. **Close hygiene** — MEMORY.md updated for BUILDER-POLISH-01 closure with full v13.11 entry; Phase 256 polish-backlog todo moved to `.planning/todos/done/` with `status: closed, shipped_in: v13.11` frontmatter.
6. **Hybrid-shape milestone validated** — Phase 258 ran the full skill chain (smart discuss → plan-phase → execute-phase → code-review with WR-01 + IN-02 fixed inline → 258-VERIFICATION.md). Phases 259-262 ran inline with focused executor agents and direct edits. Each path produced a SUMMARY with per-REQ landing notes; full CI gate green at every commit. Mixed-shape milestones extend the v13.10 hygiene-shape pattern.

**Code review findings (Phase 258 only — review skipped for inline phases):** 4 warnings + 3 info (0 critical). Disposition: 3 fixed inline (WR-01 applyAdvanced nextPaint composition, WR-03 advancedText cleanup, IN-02 stop-count assertion), 1 accepted as intentional (WR-04 hydration cache length-equality defense-in-depth), 3 deferred with documented reasoning (WR-02 over-strict parser, IN-01 operator string comment, IN-03 applyAdvanced solid-mode edge case).

**Known close caveats:**

- Phase 261 fix addresses the most likely root cause matching the user's "Label-Layer toggle not working" symptom. If a different scenario surfaces post-deploy, capture exact reproducer + affected dataset's `dataset_column_info` payload to drive a follow-up.
- Visual UAT via Playwright MCP not performed during Phase 261 audit — recommended as a post-deploy smoke check.
- 2 deferred items added to the standing tech-debt ledger: Phase 258 IN-03 (applyAdvanced from solid mode leaves mode='solid'), Phase 258 WR-02 (lineGradientExpressionToStops over-strict on `['linear']` length).

**Verification gates (full CI green at every commit):**

- `npx tsc --noEmit` exit 0
- `npx eslint` clean (1 pre-existing unused-disable warning, predates v13.11)
- `npx vitest run` full suite: 130 test files / 1183 tests / 8 todo, all green
- `LineGradientControls.test.tsx`: 42/42 (29 pre-existing v13.9 invariants + 13 new `polish-0*:` tests)

**Archives:**

- `.planning/milestones/v13.11-ROADMAP.md`
- `.planning/milestones/v13.11-REQUIREMENTS.md`
- `.planning/milestones/v13.11-MILESTONE-AUDIT.md`
- `.planning/milestones/v13.11-phases/{258..262}-*/`

**Tag:** None (per repo policy — `.planning/` gitignored, milestones close locally without commits or tags. Source-file commits are in main branch git history.)

**Sibling repo check:** `~/Code/geolens-enterprise` had pre-existing unstaged work unrelated to v13.11; no enterprise-side cleanup needed.

---

## v13.10 GH Issues Hygiene (Shipped: 2026-05-07)

**Milestone goal:** Audit every open GitHub issue in `geolens-io/geolens` against shipped code and v13.8 + v13.9 milestone audits, close the stale ones, and surface any genuine leftover work as a tiny follow-up.

**Stats:**

- **Phases:** 1 (Phase 257)
- **Plans:** 3 / 3 complete (audit doc, closures, leftover capture + tracker refresh)
- **Timeline:** 2026-05-07 (same-day close)
- **Code changes:** 0 source files (markdown writes + `gh` CLI calls only)
- **External state:** 11/11 open GitHub issues in `geolens-io/geolens` closed

**Requirements:** 8/8 satisfied (AUDIT-01..02, CLOSE-01..02, LEFTOVER-01..02, TRACKER-01..02)

**Verdict distribution:** 11 CLOSED, 0 LEFTOVER, 0 UNCLEAR.

**Key accomplishments:**

1. **GH issue tracker now reflects shipped reality** — All 11 open issues (#50, #51, #52, #53, #54, #55, #56, #57, #58, #59 builder issues + #97 sequencing tracker) closed on github.com with REQ-ID-citing comments referencing v13.8 (27/27) or v13.9 (19/19) milestone audits.
2. **CTRL-01 user-confirmation gate enforced** — A single batch confirmation prompt presented before any `gh issue close` ran; user replied `approved` and only then did the 11 mutations execute. Closure log records per-issue `gh exit` codes (all 0).
3. **Tracker ordering enforced** — Tracker #97 closed LAST after all 10 child closures returned exit 0; summary comment links each child closure path so future readers can follow the trail without opening every child.
4. **Spot-checks confirmed three non-obvious closures:** #51 (style export/import — v13.9 byte-for-byte round-trip E2E flow PASS), #56 (terrain — NEW-INT-01 closure trail via commit `e46b96c6` and two `TestImportStyleJsonTerrain` regression tests), #58 (line paint properties — split across v13.8 LINE-01..02 and v13.9 GRAD-01..06 with both halves explicitly cited in the closure comment).
5. **PROJECT.md reflects post-audit state** — `[ ] v13.10` checkbox removed from Active; `### Active` set to placeholder; v13.10 added to chronological shipped list; `BUILDER-POLISH-01` (Phase 256 UI audit findings) and `OPS-01` (server-side map thumbnails) now explicitly named in PROJECT.md `### Out of Scope` so future planning sweeps can see them.
6. **Hygiene-milestone shape validated** — One phase, three plans, zero new feature code, single batch confirmation as the only user input. Single-phase milestones are a viable pattern when scope is tightly coupled audit + closure + tracker refresh.

**Known deferred items at close:** 177 (175 cross-milestone `quick_tasks` carried since v13.1 + 2 todos: `2026-05-05-recreate-public-repo-before-launch` and `2026-05-07-phase-256-ui-audit-blocker-backlog-gradient-preview-swatch` (BUILDER-POLISH-01)). Acknowledged via the standard pre-close artifact audit; logged to STATE.md `## Deferred Items`.

**Known gaps:** None at functional level. No code changes shipped (this is a hygiene milestone). No CI/full-suite work performed (no source files touched).

**Archives:**

- `.planning/milestones/v13.10-ROADMAP.md`
- `.planning/milestones/v13.10-REQUIREMENTS.md`
- `.planning/milestones/v13.10-MILESTONE-AUDIT.md`

**Tag:** None (per repo policy 2026-05-06 — `.planning/` gitignored, milestones close locally without commits or tags).

---

## v13.9 Map Builder Closeout (Shipped: 2026-05-06)

**Phases completed:** 10 phases, 13 plans, 38 tasks

**Key accomplishments:**

- Routed catalog/maps/style_json.py tile signing through CatalogPort by adding generate_tile_signature + round_tile_expiry to the Protocol, restoring the v13.4 bidirectional Port invariant that Phase 251 regressed.
- Re-routed `apply_layer_diff` through the maps `service.py` facade so `router.py` no longer imports directly from the private `service_crud.py`, restoring the Phase 236/238 BOUND-01 router-to-facade-to-CRUD layering invariant.
- Closed BOUND-02 by extracting the layer-diff/replace cluster (211 LOC) from `service_crud.py` into a new `service_diff.py` sibling, dropping `service_crud.py` from 651 to 423 LOC and landing the full 20-test architecture-guard suite (LAYERING-04 close gate) green.
- Authored three Nyquist-style VALIDATION.md files for v13.8 Phases 246, 247, and 248 mapping every shipped requirement (STYLE/SAVE/RASTER/LINE/ZOOM/DEM/TERRAIN) to executable pytest/vitest selectors plus grep/file-exists gates, all verified against current `main` at exit 0.
- Single reviewer-runnable command `make validate-v13-8` that runs all 63 v13.8 VALIDATION.md checks across Phases 246..251 end-to-end with fail-fast semantics, three-tier exit codes, and pre-flight API container detection — closes VALID-07 and converts six separately-runnable VALIDATION.md files into one auditable command.
- Switched PUT /maps/{map_id}/thumbnail/ from a text/plain body to a JSON body backed by ThumbnailUploadRequest, eliminating the openapi-python-client `WARNING parsing` line and adding the previously-skipped upload_thumbnail endpoint to the generated Python SDK.
- Added a hard warning gate to `make sdks` that fails the build on any `^WARNING parsing` line from openapi-python-client, plus an AST-based architecture-guard test that pins upload_thumbnail to a Pydantic JSON body shape — closing SDK-02 with both a build-time and a pytest-time enforcement.
- Source-side `lineMetrics: true` lazy-emission seam in `syncVectorLayer` (D-01 detection + D-02 sticky lifecycle) plus identity-level regression-lock for expression-valued `line-gradient` paint through `lineAdapter.addLayers` + `lineAdapter.syncPaint`.
- Server-side MapLibre style JSON export now emits `lineMetrics: true` on vector sources whose backing layers carry `line-gradient` paint or `style_config.builder.lineGradient` intent (D-01 detection), with an allowlist guard that drops `line-gradient` paint and logs a warning when the source type cannot support it (mirrors Phase 251 `_HILLSHADE_PAINT_KEYS` convention).
- MapLibre style imports now demonstrably round-trip `paint['line-gradient']` paint expressions and `style_config.builder.lineGradient` builder intent end-to-end (export -> import -> re-export), with byte-identical re-emission of the source-level `lineMetrics: true` flag and the per-layer paint expression. Phase 255 GRAD engine foundation (GRAD-01, GRAD-04, GRAD-05, GRAD-06) is now complete.
- Color-stops authoring UI for line-gradient with canonical interpolate-linear-line-progress round-trip parser, mode-toggling LineControls integration, and refreshed Phase 247 deferral comment.
- Raw MapLibre expression editor disclosure with parse + structural validation, Apply/Cancel commit flow, round-trip via shared parser (canonical hydrates stops; non-canonical preserves customExpression hint), and Playwright MCP visual UAT protocol document.

---

## v13.8 Map Builder Advanced Styling (Shipped: 2026-05-06)

**Milestone goal:** Make the map builder a stronger cartographic authoring surface by cleaning style persistence first, then adding advanced raster, line, zoom, DEM, symbol, interop, and edit-history workflows from GitHub milestone #1 / tracker #97.

**Stats:**

- **Phases:** 6 (246, 247, 248, 249, 250, 251)
- **Plans:** 22 / 22 complete
- **Timeline:** 2026-05-05 → 2026-05-06 (2-day burst)
- **Commits:** 29 milestone-scoped commits (`b142b228^..e46b96c6`)
- **Diff:** 121 files, +17,299 / -692

**Requirements:** 27/27 satisfied (STYLE-01..03, SAVE-01..03, RASTER-01..02, LINE-01..02, ZOOM-01..02, DEM-01..02, TERRAIN-01..03, STYLEX-01..03, SYMB-01..04, HIST-01..03)

**Key accomplishments:**

1. **Style state foundation shipped** — `MapLayer.paint` now contains only valid MapLibre paint; private builder UI flags moved to documented `style_config` with a row migration. `PATCH /maps/{map_id}/layers` accepts incremental layer diffs (added/updated/removed/reordered) with stable layer IDs; full-replacement save retained as fallback. OpenAPI + Python/TypeScript SDK contracts refreshed for `MapLayerDiffRequest`/`MapLayerPatch`.
2. **Advanced styling controls shipped** — first-class raster paint controls (brightness/contrast/saturation/hue rotation/resampling/fade duration/opacity + reset), line gap/blur/offset (with `line-gradient` explicitly deferred pending `lineMetrics` + gradient expression UI), and a zoom expression editor for `step`/`interpolate` stops on line, circle, label, and opacity properties. Adapter pipeline preserves expression-valued paint without flattening.
3. **DEM hillshade and terrain shipped** — raster-dem source emission + 6-key hillshade paint allowlist + illumination/exaggeration/color controls. Map-level terrain config persists across builder, public viewer, and shared/embed surfaces; vertical-unit caveats surfaced. Terrain source resolved by DEM dataset ID so authenticated and public surfaces see the same source.
4. **MapLibre style JSON interop shipped** — full export/import round-trip for raster, DEM hillshade, terrain block, and outline/extrusion/label companions; builder `style_config` preserved through `metadata.geolens.style_config.builder`. Sprite-backed symbol/icon layers with upload/storage/serving endpoints, builder icon picker, and consolidated symbol+label adapter (no duplicate label companion layers). Foreign style imports report unmatched parts as warnings rather than corrupting builder state.
5. **Map edit history shipped** — durable backend event capture for committed map/layer/style/config saves, `MapHistoryEntry` records (actor, timestamp, target, action type, change summary), builder right-rail History panel matching the established panel system, OpenAPI + SDK contracts refreshed.
6. **Audit-driven gap closure shipped** — Phase 251 closed all 9 functional gaps surfaced by the v13.8 milestone audit (STYLEX-01/02 export+import, INT-01/02, FLOW-01/02/03) plus NEW-INT-01 (terrain persistence at the `/maps/import` endpoint) found during the re-audit. Re-audit passed with `status: passed` and 27/27 functional+paperwork-clean coverage.

**Phase 252 disposition:** A planned `Phase 252: history-traceability-closeout` was scaffolded for HIST paperwork reconciliation and audit re-run. Its scope was absorbed into Phase 251 + inline reconciliation during the 2026-05-06 audit re-run; no Phase 252 plan/SUMMARY ever shipped, and the phase was removed from the roadmap before close.

**Known gaps:** None blocking. Inherited tech debt: no `VALIDATION.md` files exist for any v13.8 phase (Nyquist enabled but never enforced for v13.8); pre-existing `test_layering.py` failures and `openapi-python-client PUT /maps/{id}/thumbnail/` warning predate this milestone and are tracked for future remediation.

**Archives:**

- `.planning/milestones/v13.8-ROADMAP.md`
- `.planning/milestones/v13.8-REQUIREMENTS.md`
- `.planning/milestones/v13.8-MILESTONE-AUDIT.md`

**Tag:** `v13.8`

---

## v13.7 Manifest-Driven Catalog Automation (Shipped: 2026-05-04)

**Milestone goal:** Let a new organization describe datasets, sources, metadata, and publication intent in `geolens.yaml`, validate it locally, and apply it through the CLI/backend path into a browsable GeoLens catalog.

**Stats:**

- **Phases:** 5 (241, 242, 243, 244, 245)
- **Plans:** 18 / 18 complete
- **Timeline:** 2026-05-04 (same-day close)
- **Commits:** 43 milestone-scoped commits (`adf71c43^..d93843ee`)
- **Diff:** 113 files, +10,659 / -125

**Requirements:** 19/19 satisfied (MAN-01..05, CLI-01..04, INGEST-01..04, DOCS-01..02, QUAL-01..04)

**Key accomplishments:**

1. **Manifest v1 contract shipped** — `geolens.yaml` now has a backend-agnostic schema, deterministic validation helpers, good/bad fixtures, and compatibility tests for vector, raster COG, VRT, local path, URL, storage URI, metadata, and Community-safe publication intent.
2. **Offline CLI workflow shipped** — `geolens init` and `geolens validate` scaffold and validate manifests locally with deterministic exit codes, path-specific errors, remediation output, help coverage, and import-boundary guards.
3. **Backend apply workflow shipped** — `POST /ingest/manifest/apply` accepts typed manifest payloads, preserves upload permission checks, storage/file safety, idempotency, and existing ingest behavior across create/update/skip/error outcomes.
4. **CLI apply and first-catalog docs shipped** — `geolens apply` and `--dry-run` use configured API credentials, examples cover local/HTTP/S3/publication states, and docs walk from Docker Compose to a browsable catalog.
5. **Contracts and gates locked** — OpenAPI, Python SDK, TypeScript SDK, CLI docs, CI manifest gates, architecture guards, and the formal close audit passed with 19/19 requirements and 6/6 verified flows.

**Known gaps:** None blocking for v13.7. The audit explicitly does not claim full backend/frontend/E2E suite success; pre-existing third-party deprecation warnings and the CLI raw-transport follow-up are nonblocking residual risks.

**Archives:**

- `.planning/milestones/v13.7-ROADMAP.md`
- `.planning/milestones/v13.7-REQUIREMENTS.md`
- `.planning/milestones/v13.7-MILESTONE-AUDIT.md`

**Tag:** `v13.7`

---

## v13.6 Catalog Maps/Search Service Decomposition (Shipped: 2026-05-04)

**Milestone goal:** Split the remaining large catalog map and search services into focused modules behind stable public facades so future map/search work can land without regrowing the old service files or regressing public API behavior.

**Stats:**

- **Phases:** 5 (236, 237, 238, 239, 240)
- **Plans:** 18 / 18 complete
- **Timeline:** 2026-05-03 -> 2026-05-04
- **Commits:** 40 milestone-scoped commits (`044c07f6^..8128aa67`, excluding two unrelated docs/frontend commits in the raw time window)
- **Diff:** 63 owned files, +7,495 / -2,727

**Requirements:** 21/21 satisfied (MAPS-01..06, SRCH-01..06, BOUND-01..04, QUAL-01..03, DEBT-01..02)

**Key accomplishments:**

1. **Maps service decomposed behind a stable facade** — `catalog/maps/service.py` is now a thin public re-export surface over shared, CRUD, layer, and public/share modules while preserving map CRUD, layers, sharing, thumbnails, tokens, and public-viewer behavior.
2. **Search service decomposed behind a stable facade** — `catalog/search/service.py` now re-exports focused filter, facet, collection, semantic, dataset, and OGC record modules while preserving search, facets, cache, OGC/STAC/AI contracts, and semantic/hybrid behavior.
3. **Boundary and size guards added** — architecture tests prevent direct external imports of private maps/search split modules and enforce facade/private module size budgets.
4. **Brittle source-introspection tests replaced** — VRT/search coverage now asserts helper and facade behavior instead of inspecting inline implementation blocks.
5. **Close evidence passed** — the focused maps/search backend suite, touched-module ruff/format gates, v13.6 close audit, broader confidence-gate evidence, and warning cleanup are recorded; formal milestone audit passed with 21/21 requirements and 7/7 verified flows.

**Known gaps:** None blocking for v13.6. Full backend coverage and Playwright smoke are not fully green locally; exact failures/blockers are documented in Phase 240 and treated as nonblocking because the focused v13.6-owned maps/search surface passed.

**Archives:**

- `.planning/milestones/v13.6-ROADMAP.md`
- `.planning/milestones/v13.6-REQUIREMENTS.md`
- `.planning/milestones/v13.6-MILESTONE-AUDIT.md`

**Tag:** `v13.6`

---

## v13.5 Enterprise Governance Seams (Shipped: 2026-05-03)

**Milestone goal:** Turn the remaining governance-adjacent permission and workflow chokepoints into first-class extension seams so Enterprise overlays can implement advanced RBAC and approval workflows without forking core.

**Stats:**

- **Phases:** 4 (232, 233, 234, 235)
- **Plans:** 13 / 13 complete
- **Timeline:** 2026-05-03 (same-day close)
- **Commits:** 49 in milestone range (`v13.4..e57042a8`)
- **Diff:** 63 files, +5,359 / -376

**Requirements:** 16/16 satisfied (PERM-01..05, WORK-01..05, SHARE-01..03, GOVAUD-01..03)

**Key accomplishments:**

1. **PermissionExtension seam shipped** — action checks, catalog visibility filtering, and dataset detail access now route through a platform extension with Community default behavior preserved, overlay tests, and an architecture guard.
2. **WorkflowExtension seam shipped** — publication `/status/`, `/target-status/`, and metadata `record_status` writes now route through extension-defined transitions and hooks while preserving the Community lifecycle.
3. **Advanced-sharing boundary verified** — Community keeps basic share/embed behavior while custom embed lifetimes, origin restrictions, and expiring share links are gated consistently across schema, service, UI, API/OpenAPI, and GTM docs.
4. **Close audit passed** — `docs-internal/audits/post-impl-20260503-v13-5.md` records Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings.
5. **Formal milestone audit passed** — `.planning/milestones/v13.5-MILESTONE-AUDIT.md` records 16/16 requirements satisfied, no orphaned requirements, and no critical gaps.

**Known gaps:** None blocking. Full-suite merge readiness remains normal CI/full-suite work; local DB provisioning limitations are recorded as nonblocking residual risk.

**Archives:**

- `.planning/milestones/v13.5-ROADMAP.md`
- `.planning/milestones/v13.5-REQUIREMENTS.md`
- `.planning/milestones/v13.5-MILESTONE-AUDIT.md`

**Tag:** `v13.5`

---

## v13.4 Boundary Closeout (Shipped: 2026-05-03)

**Milestone goal:** Close the last open-core boundary, coupling, and provider-seam gaps from the 2026-04-30 and 2026-05-02 audits so the committed GeoLens surface is ready for the next public-launch milestone.

**Stats:**

- **Phases:** 7 (225, 226, 227, 228, 230, 231, 229)
- **Plans:** 23 / 23 complete
- **Timeline:** 2026-05-01 → 2026-05-03 (3 days)
- **Commits:** 170 in milestone range (`325a4418^..9c63a890`)
- **Diff:** 924 files, +33,593 / -18,204

**Requirements:** 30/30 satisfied (PROCESS-01..05, AIEXT-01..05, TESTFIX-01..03, PUBLISH-01..04, CATPORT-01..05, EMBPROV-01..05, PIAUDIT-01..03)

**Key accomplishments:**

1. **Bidirectional catalog/processing cycle inverted** — Phase 225 added `ProcessingPort` for processing→catalog access; Phase 230 added symmetric `CatalogPort` for catalog→processing access. Architecture guards now enforce both directions.
2. **AI and embeddings provider seams closed** — Phase 226 moved AI provider dispatch behind `AIProviderExtension`; Phase 231 moved embeddings behind `EmbeddingProviderExtension` and expanded the provider-SDK import guard across all `backend/app/processing/`.
3. **Cold publish workflows shipped** — Phase 228 verified `geolens==1.0.0`, `geolens-cli==1.0.0`, and `@geolens/sdk==1.0.0` from public registries and documented final package names.
4. **SAML fixture churn removed** — Phase 227 stopped committed SAML fixtures from mutating during tests.
5. **Post-implementation close gate passed** — Phase 229 produced `docs-internal/audits/post-impl-20260503-v13-4.md` with Boundary Integrity A+, Coupling Health A−, Seam Quality A−, and no unresolved P1 findings.

**Known gaps:** None for the committed v13.4 scope. In-progress advanced-sharing controls were stashed before milestone archival as `stash@{0}` and are not part of this milestone.

**Archives:**

- `.planning/milestones/v13.4-ROADMAP.md`
- `.planning/milestones/v13.4-REQUIREMENTS.md`

**Tag:** `v13.4`

---

## v13.3 Boundary A+ Cleanup (Shipped: 2026-05-01)

**Milestone goal:** Close the P1 architectural items from the post-v13.2 open-core audit so the repo could claim Boundary Integrity A+ and a fully overlay-capable audit/billing surface.

**Stats:**

- **Phases:** 3 (222, 223, 224)
- **Plans:** 18 / 18 complete
- **Timeline:** 2026-04-30 → 2026-05-01 (2 days)
- **Commits:** 83 in milestone range
- **Diff:** 141 files, +19,316 / -2,211

**Requirements:** 15/15 satisfied (AUDIT-01..05, BILLING-01..06, DECOUPLE-01..04)

**Key accomplishments:**

1. **AuditSink seam shipped** — 65 `log_action()` sites now route through `audit_emit()` and registered sinks with per-sink failure isolation.
2. **Marketplace billing extracted** — AWS Marketplace registration moved out of core behind `BillingExtension.on_startup()`; `core/marketplace.py` was deleted.
3. **Catalog dataset god-module decomposed** — `catalog/datasets/domain/service.py` became an 87-LOC façade over five cohesive sub-modules, with architecture guards preventing external bypass.
4. **SQL safety centralized** — shared table/column validation moved behind a single private helper module and guard.
5. **Post-implementation quality target met** — Overall readiness moved 3.39 → 3.85 (A) per `post-impl-20260501-b.md`.

**Archives:**

- `.planning/milestones/v13.3-ROADMAP.md`
- `.planning/milestones/v13.3-REQUIREMENTS.md`

**Tag:** `v13.3`

---

## v13.2 Edition Lifecycle Hardening (Shipped: 2026-04-30)

**Milestone goal:** Close the deactivation/reactivation lifecycle gap surfaced during v13.1 close-out — make enterprise→community downgrade safe and re-upgrade lossless before any paying customer hits these gaps.

**Stats:**

- **Phases:** 2 (220, 221)
- **Plans:** 9 / 9 complete (6 in 220, 3 in 221)
- **Timeline:** 2026-04-29 → 2026-04-30 (2 days)
- **Commits:** 58 in milestone range (`192fe7e1..a0758e99`)
- **Diff:** 80 files, +12,308 / -439 (incl. SDK regen + format pass)

**Requirements:** 7/7 satisfied (LIFECYCLE-01..07)

**Key accomplishments:**

1. **Operator runbooks for the full lifecycle** — `docs/edition-deactivation.md` (186 lines, 10 sections) for enterprise→community downgrade and `docs/edition-reactivation.md` for the re-upgrade. `docs/saml.md` no longer presents `alembic downgrade -1` as the primary path; it now cross-links to the new runbook and labels the destructive path as opt-in with a mandatory `pg_dump` pre-step (Phase 220, LIFECYCLE-01/02/03/05).
2. **SAML data preservation verified by integration test** — `backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data` confirms `oauth_providers` rows + 4 `deferred=True` SAML columns + `oauth_accounts` linkages survive a registry-clear deactivation. The `lifecycle` pytest marker is registered in `backend/pyproject.toml` and runs by default in CI when the geolens-enterprise overlay is installed (Phase 220, LIFECYCLE-04).
3. **CI overlay install with graceful fork-PR fallback** — `.github/workflows/ci.yml` conditionally checks out and installs `geolens-enterprise` based on `GEOLENS_ENTERPRISE_TOKEN` secret presence; pytest runs with lifecycle marker INCLUDED when overlay available, deselected on fork PRs without secret. No fork-PR breakage (Phase 220, LIFECYCLE-04 CI side).
4. **Admin SAML→local conversion endpoint** — `POST /admin/users/{user_id}/convert-saml-to-local/` (audit action `user.convert_saml_to_local`) flips a SAML user to local-password in a single transaction, preserving `users.id` (every FK referencing it stays intact) and deleting only the SAML `oauth_accounts` linkage. Self-conversion blocked with 422 (Phase 221, LIFECYCLE-06).
5. **Round-trip symmetry guaranteed** — `test_deactivate_reactivate_roundtrip_preserves_saml_data` drives the registry through a full deactivate → reactivate cycle and asserts losslessness across the 4 deferred SAML columns + `oauth_accounts` linkage + User row + a seeded `audit_log` row (Phase 221, LIFECYCLE-07).
6. **Post-impl audit + tech-debt close in same milestone** — Post-impl audit ran 2026-04-30 (`docs-internal/audits/post-impl-20260430.md`): 47 findings → 20 fixed across 5 commits (P1 resilience: GDAL info-leak sanitization, Titiler timeout, RegisterForm fieldset, embedding dim guard; admin module helper consolidation; schema tightening; frontend polish; logging). Plus 2 pre-existing phase-217 test failures fixed (`test_saml_provider_update_logs_old_new_role_mapping` missing fixture; `test_collections::test_update_collection` `MissingGreenlet` cascade across 974+ tests). Final: 2036/2036 backend tests green at 62.29% coverage; 1009 frontend tests green.

**Known deferred items at close:** 172 (see STATE.md `## Deferred Items`)

- 170 cross-milestone `quick_tasks` (carried over from v13.1; hygiene debt)
- 1 UAT gap (Phase 220 UAT-2 — lifecycle CI literal log line confirmation; local equivalent verified, CI blocked on Actions free-tier billing through 2026-04-30; reset 2026-05-01)
- 1 verification gap (Phase 220 — same UAT-2 item)

**Known gaps:** None at functional level. v13.2-MILESTONE-AUDIT.md graded `tech_debt`; all 5 tech-debt items closed inline same day (audit-action rename `auth.*` → `user.*`, frontmatter backfill, validation status flips). Local CI-equivalent gates all green at close: ruff + format + openapi snapshot + sdks drift + bandit + pytest with lifecycle marker INCLUDED + frontend lint/tsc/vitest.

**Tag:** `v13.2`

---

## v13.1 Open-Core Separation P1 (Shipped: 2026-04-29)

**Milestone goal:** Close the six P1 boundary/seam debts surfaced in the open-core audit so the open-core architecture is demonstrably ship-ready before the first paid customer. Target audit grade improvements: Boundary B → A−, Seam Quality C → B, OSS Surface D → C.

**Stats:**

- **Phases:** 8 (212 → 219; Phase 219 added mid-milestone to close P0 surfaced by Phase 218)
- **Plans:** 30 / 30 complete
- **Timeline:** 2026-04-26 → 2026-04-29 (4 days)
- **Commits:** 179 in milestone range
- **Diff:** 903 files, +163,458 / -479
  - Hand-written: 125 files, +10,143 / -413
  - Generated SDK code: 655 files, +112,074 (Python + TypeScript clients from OpenAPI)
  - Planning artifacts: 123 files, +41,241

**Audit grades (vs targets):**

| Dimension | Target | Result | Met? |
|-----------|--------|--------|------|
| Boundary Integrity | A− | A | ✅ exceeds |
| Seam Quality | B | B | ✅ |
| OSS Surface Readiness | C | A− | ✅ exceeds |

**Requirements:** 21/21 satisfied (LAYER-01..02, IDENT-01..03, OCSDK-01..04, OCCLI-01..06, SAML-08..12, AUDIT-V1)

**Key accomplishments:**

1. **Open-core boundary closed** — `core/` no longer imports from `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py` with all 23 inbound callers migrated; broadened architecture-guard test prevents regression (Phases 212, 213).
2. **IdentityProtocol extracted** — 51 cross-domain `User` import sites retyped to `Identity` Protocol; extension hook (`get_identity_extension()`) lets enterprise overlays register custom identity backends without core changes; 18-file allowlist guard enforces invariant (Phase 214).
3. **Auto-generated SDKs shipped** — Python (`pip install geolens`) + TypeScript (`@geolens/sdk`) clients regenerate from `backend/openapi.json` one-shot via `make sdks`; `make sdks-check` CI gate prevents drift; `flatten_openapi_defs.py` preprocessor resolves OpenAPI 3.1 inline `$defs` (Phase 215).
4. **`geolens` CLI MVP on PyPI** — Apache-2.0 standalone CLI (`login` keyring + headless / `scan` / `publish` / `export stac`) consuming only the generated Python SDK; zero hand-rolled HTTP imports enforced by CI grep + tomllib gates; 112 unit tests + 6 round-trip tests pass (Phase 216).
5. **SAML enterprise overlay** — `geolens-enterprise` registers via `importlib.metadata` entry_points with dual `AuthExtension` + `IdentityExtension` Protocol seams; SP-initiated SSO + JIT provisioning via existing `find_or_create_oauth_user()` + audited attribute→role mapping; admin UI 3-layer gated (`useEdition()` + sidebar filter + backend 404); SAML scaffold in core limited to documented Pitfall 11 mitigation (deferred=True ORM columns) (Phase 217).
6. **Audit gate met** — Closing audit produced at `docs-internal/audits/oc-separation-audit-v13.1-close.md` (Phase 218); OAuth IdP→role mapping P0 surfaced by audit closed by Phase 219 via `is_enterprise()` gate at schema validator + service path; audit document amended in place from BLOCKED → VERIFIED (Phase 219).

**Known deferred items at close:** 175 (see STATE.md `## Deferred Items`)

- 170 cross-cutting `quick_tasks` from earlier milestones (hygiene debt, not v13.1-specific)
- 1 UAT gap on Phase 216 (4 documented `human_needed` items: PyPI publish, OS keyring per-platform, interactive Progress UI, refresh-token retry)
- 4 verification gaps (215/216 `human_needed`; 999.2/999.4 P3 backlog)

**Known gaps:** None at functional level. v13.1-MILESTONE-AUDIT.md graded `tech_debt` due to paperwork lag (missing phase-level VERIFICATION.md × 4, draft VALIDATION.md × 6, REQUIREMENTS.md checkbox lag); all closed via paperwork pass at commit `5dfc1f8c` (2026-04-29).

**Tag:** `v13.1`

---
