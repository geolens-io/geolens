# Roadmap: GeoLens

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-02-13)
- ✅ **v1.1 Machine Readability** — Phases 9-13 (shipped 2026-02-14)
- ✅ **v1.2 QA & Polish** — Phases 14-16 (shipped 2026-02-14)
- ✅ **v1.3 Admin Control & Data Lifecycle** — Phases 17-21 (shipped 2026-02-15)
- ✅ **v1.4 Production Readiness** — Phases 22-27 (shipped 2026-02-15)
- ✅ **v1.5 Data Organization & Freshness** — Phases 28-31 (shipped 2026-02-15)
- ✅ **v1.6 UI/UX Polish** — Phases 32-35 (shipped 2026-02-15)
- ⏸️ **v1.7 Marketplace & Distribution** — Phases 36-42 (paused at Phase 40)
- ✅ **v1.8 Map Builder Core** — (shipped 2026-02-17)
- ✅ **v1.9 Map Builder AI** — (shipped 2026-02-21)
- ✅ **v2.0 Natural Earth Seed Script** — Phases 53-55 (shipped 2026-02-22)
- ✅ **v2.1 Service URL Importing** — Phases 56-60 (shipped 2026-02-23)
- ✅ **v2.2 Architecture Simplification** — Phases 61-63 (shipped 2026-02-23)
- ✅ **v2.3 Layer Creation & Editing** — Phases 64-67 (shipped 2026-02-24)
- ✅ **v2.4 Visual Identity & Admin Experience** — Phases 68-71 (shipped 2026-02-24)
- ✅ **v2.5 i18n** — (shipped 2026-02-25)
- ✅ **v2.6 Tile Architecture** — (shipped 2026-02-26)
- ✅ **v3.0 Design Overhaul** — (shipped 2026-02-28)
- ✅ **v5.0 Cloud-Ready Architecture** — (shipped 2026-03-02)
- ✅ **v6.0 Hardening & Production Readiness** — Phases 102-110 (shipped 2026-03-03)
- ✅ **v6.1 Dataset Detail UX & Provenance** — Phases 111-115 (shipped 2026-03-06)
- ✅ **v6.2 Enterprise Configuration & OAuth** — Phases 116-120 (shipped 2026-03-07)
- ✅ **v7.0 Stack Consolidation** — Phases 121-132 (shipped 2026-03-08)
- ✅ **v7.2 Semantic Search (pgvector)** — Phases 133-138 (shipped 2026-03-09)
- ✅ **v7.3 Map Page Polish** — Phases 139-143 (shipped 2026-03-09)
- ✅ **v8.0 Spatial Intelligence** — Phases 144-147 (shipped 2026-03-09)
- ✅ **v8.1 Secure Sharing & Embed Tokens** — Phases 148-151 (shipped 2026-03-10)
- ✅ **v8.2 Share Link Settings** — Phases 152-153 (shipped 2026-03-10)
- ✅ **v9.0 Cloud Marketplace Distribution** — Phases 154-160 (shipped 2026-03-11)
- ✅ **v9.1 Map Experience & Discovery** — Phases 161-164 (shipped 2026-03-11)
- ✅ **v10.0 Raster Support** — Phases 165-170 (shipped 2026-03-14)
- ✅ **v10.1 VRT Raster Mosaics** — Phases 171-177 (shipped 2026-03-15)
- ✅ **v11.0 Performance at Scale** — Phases 178-182 (shipped 2026-03-16)
- ✅ **v12.0 Record-First Discovery Architecture** — Phases 183-190 (shipped 2026-03-17)
- ✅ **v12.1 UI/UX Polish** — Phases 191-194 (shipped 2026-03-18)
- ✅ **v12.2 Record Detail Stabilization** — Phases 195-199 (shipped 2026-03-19)
- ✅ **v12.3 Map Builder Excellence** — Phases 200-205 (shipped 2026-03-21)
- ✅ **v13.0 Open-Core Pre-Release** — Phases 206-211 (shipped 2026-03-27)
- 🚀 **1.0.0 Public Release** — Version reset; backend/frontend bumped to 1.0.0 (shipped 2026-04-01)
- ✅ **v13.1 Open-Core Separation P1** — Phases 212-219 (shipped 2026-04-29) — see [archive](milestones/v13.1-ROADMAP.md)
- ✅ **v13.2 Edition Lifecycle Hardening** — Phases 220-221 (shipped 2026-04-30) — see [archive](milestones/v13.2-ROADMAP.md)
- ✅ **v13.3 Boundary A+ Cleanup** — Phases 222-224 (shipped 2026-05-01) — see [archive](milestones/v13.3-ROADMAP.md)
- ✅ **v13.4 Boundary Closeout** — Phases 225-231 (shipped 2026-05-03) — see [archive](milestones/v13.4-ROADMAP.md)
- ✅ **v13.5 Enterprise Governance Seams** — Phases 232-235 (shipped 2026-05-03) — see [archive](milestones/v13.5-ROADMAP.md)
- 🚧 **v13.6 Catalog Maps/Search Service Decomposition** — Phases 236-240 (cleanup phase planned after milestone audit)

## Phases

### v13.6 Catalog Maps/Search Service Decomposition

**Milestone goal:** Split the remaining large catalog map and search services into focused modules behind stable public façades so future map/search work can land without growing the current 1,300-line service files or regressing public API behavior.

**Scope guard:** This is an internal architecture/decomposition milestone. Preserve public API behavior, OpenAPI shape, response schemas, permissions, cache semantics, and user-facing map/search workflows. Search/maps router decomposition and new product capability remain out of scope.

- [x] **Phase 236: maps-service-decomposition** — Split `backend/app/modules/catalog/maps/service.py` behind a stable public façade while preserving map-builder, layer, sharing, thumbnail, and public-viewer behavior. (completed 2026-05-03)
- [x] **Phase 237: search-service-decomposition** — Split `backend/app/modules/catalog/search/service.py` behind a stable public façade while preserving catalog search, facets, semantic/hybrid merge, OGC record conversion, and collection behavior. (completed 2026-05-03)
- [x] **Phase 238: boundary-guards-and-contract-stabilization** — Add architecture guards and source-introspection-safe contract checks that keep maps/search façades stable and private decomposition modules bounded. (completed 2026-05-04)
- [x] **Phase 239: close-audit-and-verification** — Run focused maps/search verification, lint/format checks, and the v13.6 close audit. (completed 2026-05-04)
- [ ] **Phase 240: full-gate-and-deprecation-cleanup** — Close v13.6 audit tech debt by running broader CI-style gates and resolving or explicitly documenting remaining deprecation warnings.

21/21 v13.6 requirements mapped. 20/21 satisfied after Phase 240 Plan 01; DEBT-02 pending Phase 240 cleanup.

#### Phase 236: maps-service-decomposition

**Goal:** Decompose `backend/app/modules/catalog/maps/service.py` by concern using the Phase 224 façade pattern: keep `app.modules.catalog.maps.service` as the stable import surface, move implementation into focused sibling modules, and preserve all existing map CRUD, layer, sharing, thumbnail, token, and public-viewer behavior.

**Requirements:** MAPS-01, MAPS-02, MAPS-03, MAPS-04, MAPS-05, MAPS-06

**Depends on:** None

**Success Criteria** (what must be TRUE):
1. Existing imports from `app.modules.catalog.maps.service` continue to work for routers, AI callers, and tests without broad call-site churn.
2. Map CRUD/list/read/update/duplicate/delete behavior preserves response schemas, ownership checks, visibility rules, and layer sort order.
3. Layer add/remove behavior preserves dataset access checks, default style generation, layer type inference, and permission decisions.
4. Share tokens, shared map rendering, thumbnails, token revocation, dataset-in-use checks, and public/anonymous visibility behavior remain unchanged.
5. Focused regression tests cover map CRUD, layer round-trips, sharing, thumbnails, and public viewer access through the façade.

**Plans:**
5/5 plans complete

#### Phase 237: search-service-decomposition

**Goal:** Decompose `backend/app/modules/catalog/search/service.py` by concern while keeping `app.modules.catalog.search.service` as the stable import surface for `SearchFilters`, `search_datasets`, `get_facet_counts`, `search_collections`, OGC record helpers, and existing callers.

**Requirements:** SRCH-01, SRCH-02, SRCH-03, SRCH-04, SRCH-05, SRCH-06

**Depends on:** Phase 236 recommended only for sequencing discipline; no intentional shared behavior dependency.

**Success Criteria** (what must be TRUE):
1. Existing imports from `app.modules.catalog.search.service` continue to work for API, OGC/STAC, AI, and test callers.
2. Dataset search preserves text, spatial, temporal, tag, organization, CRS, record type, CQL2, sort, pagination, RBAC, and publication filtering behavior.
3. Facet counts, collection search, collection metadata/items, queryables, sortables, and record schema responses preserve response shapes and cache semantics.
4. OGC/STAC/AI consumers continue receiving the same record conversion, asset, theme, and time metadata contracts.
5. Semantic and hybrid search preserve embedding-provider dispatch, RRF merge behavior, fallback behavior, and actor identity enrichment.

**Plans:**
6/6 plans complete

#### Phase 238: boundary-guards-and-contract-stabilization

**Goal:** Stabilize the new maps/search service boundaries with architecture guards and contract checks so external modules import only public façades, split modules stay within an agreed size budget, existing catalog↔processing guards remain green, and any source-introspection tests target the façade plus helper modules instead of brittle inline implementation blocks.

**Requirements:** BOUND-01, BOUND-02, BOUND-03, BOUND-04

**Depends on:** Phases 236 and 237

**Success Criteria** (what must be TRUE):
1. Architecture guards fail when external modules import private maps/search decomposition modules directly.
2. Architecture guards fail when the maps/search façades grow back into god modules or private modules exceed the agreed size budget without an explicit allowlist.
3. Existing catalog/processing boundary guards still pass after the maps/search service split.
4. Source-introspection regression tests are updated to assert behavior across the façade and helper modules without coupling to inline implementation blocks.

**Plans:**
3/3 plans complete

#### Phase 239: close-audit-and-verification

**Goal:** Verify the v13.6 decomposition with focused backend test gates, ruff/format checks for touched catalog modules, and a close-gate audit that records decomposition results, requirement coverage, residual risks, and no unresolved P0/P1 findings.

**Requirements:** QUAL-01, QUAL-02, QUAL-03

**Depends on:** Phases 236, 237, 238

**Success Criteria** (what must be TRUE):
1. Focused backend verification passes for maps and search, including `test_maps`, `test_search`, hybrid search, search facets, search cache, and VRT search enrichment coverage.
2. Backend lint and format checks pass for touched catalog modules with no ruff or formatting violations.
3. A dated v13.6 close-gate audit records decomposition results, requirement coverage, residual risks, and confirms no unresolved P0/P1 findings.

**Plans:**
2/2 plans complete

#### Phase 240: full-gate-and-deprecation-cleanup

**Goal:** Close v13.6 milestone-audit tech debt by broadening verification beyond the focused maps/search backend close gate, reviewing remaining Pydantic/Alembic/Authlib deprecation warnings, and updating close evidence so the milestone can be re-audited cleanly.

**Requirements:** DEBT-01, DEBT-02

**Depends on:** Phase 239

**Success Criteria** (what must be TRUE):
1. Broader v13.6 confidence gates have exact recorded outcomes, including full backend validation, frontend validation, and Playwright smoke/E2E coverage where local prerequisites are available.
2. Any environmental blockers for broader gates are documented with the nearest equivalent command evidence and clear residual risk.
3. Existing Pydantic, Alembic, and Authlib deprecation warnings from focused backend verification are fixed or explicitly documented with owner/versioned follow-up if upstream-blocked.
4. The v13.6 audit evidence is updated to show whether the milestone can close without the prior tech-debt status.

**Gap Closure:** Closes TD-01 and TD-02 from `.planning/v13.6-MILESTONE-AUDIT.md`.

**Plans:**
1/2 plans complete

---

### Archived Phase Details — v13.5 Enterprise Governance Seams

- [x] **Phase 232: permission-extension-protocol** — Add a first-class `PermissionExtension` seam for action checks and catalog visibility filtering. (completed 2026-05-03)
- [x] **Phase 233: workflow-extension-protocol** — Add a first-class `WorkflowExtension` seam for publication lifecycle transitions and transition hooks. (completed 2026-05-03)
- [x] **Phase 234: governance-contract-verification** — Verify advanced-sharing gates and GTM/API/UI copy stay aligned after the 2026-05-03 Branch A fix. (completed 2026-05-03)
- [x] **Phase 235: post-impl-audit-v13.5** — Run the close audit and verify Seam Quality, Boundary Integrity, and Inventory Accuracy targets. (completed 2026-05-03)

16/16 v13.5 requirements satisfied. Formal milestone audit passed in `milestones/v13.5-MILESTONE-AUDIT.md`. Close-gate grades: Seam Quality A, Boundary Integrity A, Inventory Accuracy A− per `docs-internal/audits/post-impl-20260503-v13-5.md`.

---

### Archived Phase Details — v13.4 Boundary Closeout

- [x] **Phase 225: processing-port-protocol-cycle-inversion** — Invert the catalog↔processing cycle behind a `ProcessingPort` Protocol; inline architecture-guard test (COMPLETE — 2026-05-01)
- [x] **Phase 226: ai-provider-extension-protocol** — Replace hardcoded provider dispatch with `AIProviderExtension` extension lookup (COMPLETE — 2026-05-02)
- [x] **Phase 227: saml-test-fixture-tmp-path** — Stop committed SAML fixture mutation; route generator output to pytest `tmp_path` (COMPLETE — 2026-05-01)
- [x] **Phase 228: run-cold-publish-workflows** — Execute publish-sdks / publish-cli workflows end-to-end and validate install on a clean machine (COMPLETE — 2026-05-03)
- [x] **Phase 230: catalog-port-protocol-symmetric** — Invert the remaining 17-file `catalog → processing` direction behind a symmetric `CatalogPort` Protocol (lifts Coupling Health B+ → A−) (completed 2026-05-03)
- [x] **Phase 231: embedding-provider-extension-protocol** — Close the last direct provider-SDK import in `processing/` via an `EmbeddingProviderExtension` Protocol covering `processing/embeddings/helpers.py` (COMPLETE — 2026-05-03)
- [x] **Phase 229: post-impl-audit-v13.4** — Post-implementation audit gate confirming Boundary ≥ A+, Coupling ≥ A−, Seam ≥ A− (COMPLETE — 2026-05-03)

#### Phase 225: processing-port-protocol-cycle-inversion

**Goal:** Invert the 19-file two-way coupling between `backend/app/modules/catalog/*` and `backend/app/processing/*` by defining a `ProcessingPort` Protocol in `backend/app/core/` (mirror Phase 214 `IdentityProtocol` pattern). Rewire the 8 `processing/*` → `catalog/*` imports — including the AI features (`processing/ai/chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) — through Protocol-typed boundaries. Ship a default ProcessingPort implementation that preserves all existing behavior with zero functional regressions.

**Source:** `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Coupling regression: 16 → 19 files since 2026-04-30 baseline) / §7 P0 (action item #2). Promoted from Phase 999.7 on 2026-05-01.

**Requirements:** PROCESS-01, PROCESS-02, PROCESS-03, PROCESS-04, PROCESS-05

**Depends on:** Phase 224 (catalog god-module split — ✅ shipped 2026-05-01)

**Notes:** This phase **inlines** the architecture-guard test that was originally backlogged as Phase 999.11 (`test_no_processing_imports_catalog`). Adding the guard before the cycle is inverted would fail CI immediately, so the guard ships in the same phase as the inversion. Backlog item 999.11 is therefore retired (see Backlog section). The guard mirrors the AUDIT-02 invariant pattern from Phase 222.

**Success Criteria** (what must be TRUE):
1. `ProcessingPort` Protocol exists in `backend/app/core/` and exposes the catalog accessors needed by `processing/*` (mirrors the `IdentityProtocol` shape from Phase 214).
2. `grep -RE "from backend.app.modules.catalog|from app.modules.catalog" backend/app/processing/` returns zero hits — no direct cross-domain imports remain.
3. `pytest backend/tests/test_layering.py::test_no_processing_imports_catalog` passes, and intentionally adding a forbidden import causes the test to fail in CI.
4. Full backend test suite passes with the default `ProcessingPort` wired in (zero functional regressions vs. the v13.3 baseline of 2036/2036).
5. AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data exclusively through the Protocol — verifiable by the same grep guard plus a focused unit test that swaps in a fake `ProcessingPort`.

**Plans:**
- ✅ Plan 01: additive-scaffold — ProcessingPort Protocol + DefaultProcessingPort + get_processing_port() (committed 9bb12f66)
- ✅ Plan 02: migrate-top-level-imports — 8 module-level catalog imports migrated to port calls (committed 3285bfa3; 2046/2046 tests green)
- ✅ Plan 03a: migrate-deferred-imports-batch-a — 8 deferred sites in 4 files migrated; Port extended with 3 ORM class helpers (committed 49553678)
- ✅ Plan 03b: migrate-deferred-imports-batch-b — 18 deferred sites in 5 files migrated; Port extended with get_attribute_metadata_orm_class(); OQ-4 Outcome A (F401 imports removed); ingest/ ZERO catalog hits (committed e727f1d1)
- ✅ Plan 04: architecture-guard-and-seam-test — test_no_processing_imports_catalog + FakeProcessingPort seam test; D-26 negative-control verified (committed 88ff4f2a, 28eb50e5)

#### Phase 226: ai-provider-extension-protocol

**Goal:** Close the last 🔴 seam from `oc-separation-audit-20260430-b.md` by extracting AI provider dispatch into an `AIProviderExtension` Protocol on the same accessor pattern as `BillingExtension` (Phase 223) and `AuditSink` (Phase 222). Replace the hardcoded `if/elif provider == "anthropic"/"openai_compatible"` branches at `processing/ai/llm_loop.py:117,132` and `service.py:387-398` with extension lookup. Default registry maps the two community providers; overlays can register Bedrock / Vertex / Azure / vLLM via `importlib.metadata` entry_points. Ships only the seam — new provider implementations land in overlays or follow-up milestones.

**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #7 (🔴) / §7 P1. Promoted from Phase 999.10.

**Requirements:** AIEXT-01, AIEXT-02, AIEXT-03, AIEXT-04, AIEXT-05

**Depends on:** Phase 225 (sequential — both phases touch `processing/ai/`; serializing avoids merge churn and keeps the architecture-guard signal clean while the seam is being cut).

**Success Criteria** (what must be TRUE):
1. `AIProviderExtension` Protocol exists at `backend/app/platform/extensions/protocols.py` with `complete(messages, tools)` and `stream(messages, tools)` methods.
2. `DefaultAIProviderExtension` resolves the two community providers (Anthropic native, OpenAI-compatible) via the same accessor pattern as `get_billing_extension()` / `get_audit_sink()`.
3. `grep -RE "if .*provider *== *['\"](anthropic|openai_compatible)" backend/app/processing/ai/` returns zero hits after the migration; the architecture-guard test enforces this in CI.
4. Existing AI integration tests pass unchanged with the default extension wired in (no behavior delta for community users).
5. A test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file — proving the seam is genuinely extensible.

**Plans:** 4 plans

Plans:
**Wave 1**
- [x] 226-01-PLAN.md — additive-scaffold: AIProviderExtension Protocol + DefaultAnthropicProvider + DefaultOpenAICompatibleProvider + get_ai_provider(name) accessor (Wave 1, AIEXT-01/02)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 226-02-PLAN.md — caller-migration: 4 run_tool_loop callers + sql_generator + resolve_provider tuple shape; delete _loop_anthropic/_loop_openai/run_tool_loop (Wave 2, AIEXT-03)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 226-03-PLAN.md — dead-code-cleanup: remove unreferenced OpenAI-format constants + module-level client caches (Wave 3, optional cleanup; depends on Plan 02)
- [x] 226-04-PLAN.md — architecture-guard + entry-points seam test: test_no_hardcoded_ai_provider_branches + test_ai_provider_extension.py (Wave 3, AIEXT-04/05; depends on Plan 02; parallel with Plan 03)

#### Phase 227: saml-test-fixture-tmp-path

**Goal:** Stop the committed SAML fixture files from being rewritten on every `pytest` run. Refactor the session-scoped `_regenerate_saml_fixtures` autouse fixture in `backend/tests/test_saml_overlay.py` so the signed XML responses land in a pytest `tmp_path` for the test session instead of mutating `backend/tests/fixtures/saml/idp_response_*.xml.b64`. Rename the committed fixtures to `.xml.b64.template` (immutable templates) or remove them entirely; resolve the docstring's "CI fallback when pysaml2 unavailable" claim by either restoring it for real or deleting the claim.

**Source:** Surfaced during 2026-05-01 v13.3 milestone close — five SAML fixture files were perpetually showing as modified across 9 commits because every pytest invocation rewrote them in place. Promoted from Phase 999.18.

**Requirements:** TESTFIX-01, TESTFIX-02, TESTFIX-03

**Depends on:** None — independent of 225/226 (no shared files).

**Success Criteria** (what must be TRUE):
1. `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run (regression: previously always-dirty); a CI step asserts `git diff --quiet backend/tests/fixtures/saml/` post-pytest.
2. `_regenerate_saml_fixtures` writes generated XML responses to a session-scoped `tmp_path` (or session-fixture-managed temp dir); no test path writes into the tracked fixtures directory.
3. The committed `idp_response_*.xml.b64` files are either renamed to `.xml.b64.template` (and the consumers read from the template + emit to `tmp_path`) or removed, matching whichever resolution applies to the docstring's CI-fallback claim.
4. Existing SAML overlay tests (`test_saml_overlay.py`) continue to pass — `pytest backend/tests/test_saml_overlay.py -v` is green.

**Plans:** 2 plans

Plans:
**Wave 1**
- [x] 227-01-PLAN.md — restore-and-parameterize-generator: revert 5 dirty SAML fixtures to HEAD baseline (D-09); add `output_dir: Path | None = None` parameter to `generate_fixtures.main()` (D-05). Manual CLI invocation preserved. Test suite stays green; in-place autouse path unchanged. (Wave 1, TESTFIX-01)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 227-02-PLAN.md — rename-autouse-callsites-ci-guard: `git mv` 5 fixtures to `.xml.b64.template` (D-01/D-02); replace `_regenerate_saml_fixtures` autouse with `saml_response_dir` session fixture using `tmp_path_factory` (D-04/D-06); rewrite `_load_fixture_b64(name, response_dir)` with template fallback (D-03/D-07); migrate 9 callsites + 8 enclosing function signatures; add Wave 0 `test_load_fixture_b64_falls_back_to_template` unit test; insert CI guard step `Verify SAML fixtures unchanged after pytest` (D-08); update module docstring. (Wave 2, TESTFIX-01/02/03)

#### Phase 228: run-cold-publish-workflows

**Goal:** Convert the wired-but-cold `.github/workflows/publish-{sdks,cli}.yml` workflows from "wired" to "shipped" by executing them at least once end-to-end. Confirm `secrets.NPM_TOKEN` exists and PyPI uses Trusted Publishing. Validate published artifacts against the README install instructions on a clean machine: `pip install geolens`, `npm install @geolens/sdk`, `pip install geolens-cli` should each install successfully without local checkout context.

**Source:** `oc-separation-audit-20260430-b.md` §6 (WIRED — never run) / §7 P2. Promoted from Phase 999.17.

**Requirements:** PUBLISH-01, PUBLISH-02, PUBLISH-03, PUBLISH-04

**Depends on:** None — independent of 225/226/227 (publish pipeline lives entirely in `.github/workflows/` + package metadata).

**Success Criteria** (what must be TRUE):
1. `secrets.NPM_TOKEN` is confirmed present and `secrets.PYPI_TOKEN` is absent because PyPI uses Trusted Publishing, documented in the phase VERIFICATION.md.
2. `publish-sdks.yml` completes a green end-to-end run on `main` or a release tag; `geolens` is installable from PyPI and `@geolens/sdk` from npm by version.
3. `publish-cli.yml` completes a green end-to-end run; `geolens-cli` is installable from PyPI by version and `geolens --version` returns the published version on a fresh `pip install`.
4. README install instructions are validated against the published artifacts on a machine without the GeoLens checkout — all three install commands (`pip install geolens`, `npm install @geolens/sdk`, `pip install geolens-cli`) succeed.

**Plans:** 4/4 plans executed

Plans:
**Wave 1**
- [x] 228-01-PLAN.md - workflow YAML refactors: migrate publish-sdks.yml and publish-cli.yml to PyPI Trusted Publishing (uv publish --trusted-publishing automatic), add pre-flight name-availability gates, create new verify-published.yml with two Docker-based clean-machine smoke jobs (Wave 1, autonomous, PUBLISH-01/02/03/04)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 228-02-PLAN.md - credential setup checkpoint: combined out-of-band runbook (claim @geolens npm org, configure PyPI Trusted Publishing pending publishers x2, generate npm granular access token with Bypass 2FA, set NPM_TOKEN repo secret) (Wave 2, autonomous: false, PUBLISH-01)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 228-03-PLAN.md - hot publish triggers: dry-run-first cadence for publish-sdks.yml and publish-cli.yml; Python SDK `geolens==1.0.0` and CLI `geolens-cli==1.0.0` published to PyPI; `@geolens/sdk==1.0.0` verified on npm (Wave 3, autonomous: false, PUBLISH-02/03)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 228-04-PLAN.md - verify-published smoke + docs update + 228-VERIFICATION.md: verify-published.yml passed, docs/changelog aligned with final package names, consolidated phase verification written (Wave 4, autonomous, PUBLISH-04)

#### Phase 230: catalog-port-protocol-symmetric

**Goal:** Invert the remaining 17-file top-of-file `catalog → processing` import direction by defining a symmetric `CatalogPort` Protocol in `backend/app/core/` (mirror Phase 225 `ProcessingPort` shape, opposite direction). Expose processing-owned types (`RasterAsset`, `VrtGeneration`, `DatasetAsset`, ingest result schemas, OGR helpers) so `catalog/maps/service.py:25`, `catalog/layers/service.py:15-26`, `catalog/search/service.py:44-46`, `catalog/features/service.py:12`, and the 5 `catalog/datasets/api/router_*.py` modules can call into processing without import edges. Ship a `DefaultCatalogPort` that delegates to `app.processing.*` so behavior is byte-identical pre-migration.

**Source:** `docs-internal/audits/oc-separation-audit-20260502.md` §5 (decoupling rec #1) / §7 P1 (action item #5). Promoted from Phase 999.20 on 2026-05-02. The 2026-05-02 audit explicitly noted that Phase 225 only inverts the `processing → catalog` direction; the reverse (17 files) remained unchanged. This phase closes that direction.

**Requirements:** CATPORT-01, CATPORT-02, CATPORT-03, CATPORT-04, CATPORT-05

**Depends on:** Phase 225 (sequential — both phases touch `backend/app/core/` Protocol surface; serializing avoids merge churn while the symmetric Port pair is being cut). Phase 226 also recommended as a soft sequencing dep since both shipped against the same `processing/` surface.

**Notes:** Adding `test_no_catalog_imports_processing` before the migration would fail CI immediately, so the guard ships in the same phase as the inversion (mirror Phase 225's inlined-guard pattern from former 999.11). Together with Phase 225's `test_no_processing_imports_catalog`, the two guards establish the bidirectional invariant: catalog and processing can ONLY communicate through their respective Port Protocols at module-import time.

**Success Criteria** (what must be TRUE):
1. `CatalogPort` Protocol exists in `backend/app/core/catalog_port.py` and exposes the processing-owned types/helpers needed by `catalog/*` (mirrors the `ProcessingPort` shape from Phase 225, opposite direction).
2. `grep -RE "^(from|import) (backend\.)?app\.processing" backend/app/modules/catalog/` returns zero hits at module-level — no top-of-file cross-domain imports remain. Function-local deferred imports inside the catalog domain are explicitly permitted (mirror Phase 225's scoping).
3. `pytest backend/tests/test_layering.py::test_no_catalog_imports_processing` passes, and intentionally adding a forbidden top-of-file import causes the test to fail in CI.
4. Full backend test suite passes with the default `CatalogPort` wired in (zero functional regressions vs. the v13.4 baseline going into this phase).
5. `DefaultCatalogPort` delegates to `app.processing.*` via deferred imports inside method bodies (mirrors `DefaultProcessingPort` pattern from Phase 225); single-slot `get_catalog_port()` accessor lives at `backend/app/platform/extensions/__init__.py`.

**Plans:** 4/4 plans complete

Plans:
**Wave 1**
- [x] 230-01-PLAN.md — additive-scaffold: CatalogPort Protocol + DefaultCatalogPort + get_catalog_port() accessor (CATPORT-01/05)

**Wave 2**
- [x] 230-02-PLAN.md — migrate-helper-callers: dataset API, feature/layer helpers, source preview/router/STAC helper imports routed through CatalogPort (CATPORT-02/03/05)
- [x] 230-03-PLAN.md — migrate-query-callers: maps RasterAsset and search embedding query composition routed through CatalogPort (CATPORT-02/03/05)

**Wave 3**
- [x] 230-04-PLAN.md — architecture guard + verification: test_no_catalog_imports_processing, negative-control proof, 230-VERIFICATION.md (CATPORT-04)

#### Phase 231: embedding-provider-extension-protocol

**Goal:** Close the last direct provider-SDK import in `backend/app/processing/` by defining an `EmbeddingProviderExtension` Protocol at `backend/app/platform/extensions/protocols.py` and replacing the `from openai import OpenAI` at `backend/app/processing/embeddings/helpers.py:8` with extension-registry lookup (`get_embedding_provider(name)`). Ships a `DefaultOpenAIEmbeddingProvider` that preserves current behavior; overlays can register Bedrock / Vertex / Azure / Cohere via `importlib.metadata` entry_points.

**Source:** `docs-internal/audits/oc-separation-audit-20260502.md` §5 (decoupling rec #3) / §7 P1 (action item #4). Promoted from Phase 999.19 on 2026-05-02. The 2026-05-02 audit established `test_no_module_level_provider_sdk_imports_in_processing_ai` (commit 259ebc72) covering `processing/ai/`; this phase extends the invariant to `processing/embeddings/` and removes the documented carve-out from the existing guard's docstring.

**Requirements:** EMBPROV-01, EMBPROV-02, EMBPROV-03, EMBPROV-04, EMBPROV-05

**Depends on:** None — independent of Phase 225/226/230 (different file scope: `processing/embeddings/`). Can ship in parallel.

**Success Criteria** (what must be TRUE):
1. `EmbeddingProviderExtension` Protocol added at `backend/app/platform/extensions/protocols.py` exposing `embed(texts: list[str], model: str) -> list[list[float]]` (or equivalent batch-embedding shape).
2. `DefaultOpenAIEmbeddingProvider` resolves the community provider; `get_embedding_provider(name)` accessor in `backend/app/platform/extensions/__init__.py` follows the dict-shape pattern from `get_ai_provider(name)` (Phase 226).
3. `backend/app/processing/embeddings/helpers.py:8` (`from openai import OpenAI`) is removed; embedding callers route through the registry. Verifiable by `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returning zero hits.
4. The existing architecture guard `test_no_module_level_provider_sdk_imports_in_processing_ai` is **renamed/expanded** to `test_no_module_level_provider_sdk_imports_in_processing` covering both `processing/ai/` and `processing/embeddings/`. The carve-out for embeddings is removed from the docstring.
5. Existing embeddings tests pass unchanged with the default provider wired in (no behavior delta for community users); a test overlay registered via `importlib.metadata` entry_points is dispatched correctly.

**Plans:** 3/3 plans complete

Plans:
**Wave 1**
- [x] 231-01-PLAN.md — additive-scaffold: EmbeddingProviderExtension Protocol + DefaultOpenAIEmbeddingProvider (AsyncOpenAI + retry/backoff + class-level _clients cache) + get_embedding_provider(name) accessor + new tests/test_embedding_provider_extension.py with default-smoke / unknown-ValueError / entry-points-overlay-dispatch tests (Wave 1, EMBPROV-01/02/05b)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 231-02-PLAN.md — caller-migration + helpers.py deletion: migrate generate_embedding + probe_embedding_dimensions to provider dispatch (D-12 hardcoded "openai_compatible"); DELETE helpers.py:8 from openai import OpenAI + _cached_openai_clients + build_openai_client + resolve_embedding_base_url + import httpx; migrate 4 of 5 test_embedding_service.py tests to provider-boundary mocks per D-27; SC#3 binding satisfied (Wave 2, EMBPROV-03/05a/05c)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 231-03-PLAN.md — architecture-guard rename + final verification: rename test_no_module_level_provider_sdk_imports_in_processing_ai → test_no_module_level_provider_sdk_imports_in_processing (D-13); broaden pathspec to backend/app/processing/ (D-14); delete carve-out paragraph; update negative-control example to embeddings (D-15); update test_layering.py module docstring crediting Phase 231 (D-16); automated negative-control demo (Wave 3, EMBPROV-04)

#### Phase 229: post-impl-audit-v13.4

**Goal:** Run the post-implementation audit gate for v13.4 to confirm the milestone's audit-grade targets hold across the new implementation surface (Phases 225–228, 230, 231). Produce a dated `post-impl-2026MMDD-*.md` audit report; triage P1 findings either inline or via tracked deferral; re-run grades to confirm Boundary Integrity ≥ **A+** (held from v13.3), Coupling Health ≥ **A−** (Phase 225 + 230 invert both directions of the catalog↔processing cycle), and Seam Quality ≥ **A−** (Phase 226 + 231 close all Enterprise-relevant 🔴 in the AI domain).

**Source:** Mirrors the `/post-impl` close-gate pattern used at v13.2 close (`post-impl-20260430.md`) and v13.3 close (`post-impl-20260501-b.md`). Coupling target lifted from B+ → A− on 2026-05-02 after Phase 230 (CatalogPort) was promoted into v13.4 — completes the symmetric cycle inversion that Phase 225 began.

**Requirements:** PIAUDIT-01, PIAUDIT-02, PIAUDIT-03

**Depends on:** Phases 225, 226, 227, 228, 230, 231 (audits the milestone's full implementation surface).

**Success Criteria** (what must be TRUE):
1. A dated audit report exists at `docs-internal/audits/post-impl-2026MMDD-*.md` covering Phases 225–228 + 230 + 231 with the standard sections (Boundary, Coupling, Seam, OSS Surface, Findings, Grades).
2. Every P1 finding in the report is either fixed inline (commit referenced in the report) or explicitly deferred with rationale + a tracked backlog phase opened.
3. Post-audit grade re-run records Boundary Integrity ≥ **A+**, Coupling Health ≥ **A−**, Seam Quality ≥ **A−** in the report's grades table.
4. v13.4 milestone is unblocked for close — `/gsd-complete-milestone` runs without surfacing unresolved P1 findings.

**Plans:** 1/1 plan complete

Plans:
**Wave 1**
- [x] 229-01-PLAN.md — post-impl audit evidence pack: focused baseline checks, dated audit report, P1 disposition, grade table, verification artifact, and requirements/roadmap/state closeout (PIAUDIT-01/02/03)

---

<details>
<summary>✅ v13.1 Open-Core Separation P1 (Phases 212-219) — SHIPPED 2026-04-29</summary>

- [x] Phase 212: core-settings-decouple (4/4 plans) — completed 2026-04-27
- [x] Phase 213: catalog-authz-relocate (4/4 plans) — completed 2026-04-27
- [x] Phase 214: identity-protocol-extract (4/4 plans) — completed 2026-04-27
- [x] Phase 215: sdks-from-openapi (5/5 plans) — completed 2026-04-27
- [x] Phase 216: geolens-cli-mvp (6/6 plans) — completed 2026-04-27
- [x] Phase 217: auth-saml-enterprise (5/5 plans) — completed 2026-04-27
- [x] Phase 218: oc-audit-close-v13.1 (1/1 plan) — completed 2026-04-28 (PARTIAL — closed by Phase 219)
- [x] Phase 219: oc-audit-remediate-idp-mapping (1/1 plan) — completed 2026-04-29

Audit grades met: Boundary A (≥A−), Seam Quality B (≥B), OSS Surface A− (≥C). 21/21 v13.1 requirements satisfied.

</details>

<details>
<summary>✅ v13.2 Edition Lifecycle Hardening (Phases 220-221) — SHIPPED 2026-04-30</summary>

- [x] Phase 220: lifecycle-runbooks-and-preservation (6/6 plans) — completed 2026-04-30
- [x] Phase 221: lifecycle-user-continuity-and-verification (3/3 plans) — completed 2026-04-30

7/7 v13.2 requirements satisfied (LIFECYCLE-01..07). Operator runbooks for enterprise↔community lifecycle, admin SAML→local conversion endpoint, and 3 lifecycle tests (deactivate-only, conversion, deactivate→reactivate round-trip symmetry) shipped.

</details>

<details>
<summary>✅ v13.3 Boundary A+ Cleanup (Phases 222-224) — SHIPPED 2026-05-01</summary>

- [x] Phase 222: audit-sink-protocol (5/5 plans) — completed 2026-04-30
- [x] Phase 223: marketplace-billing-extraction (5/5 plans) — completed 2026-04-30
- [x] Phase 224: catalog-god-module-split (8/8 plans) — completed 2026-05-01

15/15 v13.3 requirements satisfied (AUDIT-01..05, BILLING-01..06, DECOUPLE-01..04). Audit grade movements vs v13.1 close: Boundary Integrity A → **A+** (zero 🟡 risks); Seam Quality B → **B+** (AuditSink + BillingExtension promoted to 🟢); Coupling Health B− → **B** (log_action 65→7 chokepoint sites). Overall readiness 3.39 → 3.85 (A) per `post-impl-20260501-b.md`.

</details>

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 6/9 plans executed
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### ~~Phase 999.8: PermissionExtension Protocol~~ — PROMOTED to Phase 232 (v13.5, 2026-05-03)

**Goal:** Add `PermissionExtension` Protocol at `backend/app/platform/extensions/protocols.py` with `check_permission(user, action, resource)` + `filter_visible(user, query)` hooks. Convert the hardcoded `DEFAULT_ROLE_PERMISSIONS` matrix at `backend/app/modules/auth/permissions.py:43-74` to `DefaultPermissionExtension`. Move the visibility chokepoint at `backend/app/modules/catalog/authorization.py:34` to consult the extension.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #5 (🔴) → `oc-separation-audit-20260502.md` §2 Seam #5 (🟡 — re-rated since static matrix is admin-customizable but the SQL chokepoint at `catalog/authorization.py:34` remains hardcoded). Largest residual Enterprise-relevant 🟡 in the seam set as of 2026-05-02. / §7 P2 (action item #8)
Promoted into the v13.5 Enterprise Governance Seams milestone as Phase 232 (`permission-extension-protocol`). See [v13.5 archive](milestones/v13.5-ROADMAP.md).

---

### ~~Phase 999.9: WorkflowExtension Protocol~~ — PROMOTED to Phase 233 (v13.5, 2026-05-03)

**Goal:** Add `WorkflowExtension` Protocol with `allowed_transitions()` + `on_transition(from, to, user)` hooks. Convert the hardcoded `ALLOWED_TRANSITIONS` dict at `backend/app/modules/catalog/datasets/api/router_data.py:210-215` and `_STATUS_ORDER` at `:260` to `DefaultWorkflowExtension`. No registry, no events, no approver concept exist today.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #6 (🔴) → `oc-separation-audit-20260502.md` §2 Seam #6 (🟡 — re-rated since lifecycle states + pending-account approval show the basic state-machine substrate, but no extension Protocol exists). / §7 P2 (action item #9)
Promoted into the v13.5 Enterprise Governance Seams milestone as Phase 233 (`workflow-extension-protocol`). See [v13.5 archive](milestones/v13.5-ROADMAP.md).

---

### ~~Phase 999.10: AIProviderExtension Protocol~~ — PROMOTED to Phase 226 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 226 (`ai-provider-extension-protocol`). See Archived Phase Details above.

---

### ~~Phase 999.11: test_no_processing_imports_catalog architecture guard~~ — INLINED into Phase 225 (v13.4, 2026-05-01)

Inlined into Phase 225 (`processing-port-protocol-cycle-inversion`) because adding the guard before the cycle is inverted would fail CI immediately. The guard ships in the same phase as the cycle inversion. See Archived Phase Details above.

---

### Phase 999.12: geolens.yaml catalog manifest spec (BACKLOG — P1)

**Goal:** Define and ship the `geolens.yaml` catalog manifest format (Apache-2.0) — declarative descriptor for datasets, sources, and publishing rules. Implement `geolens init` / `geolens apply` / `geolens validate` CLI commands; backend ingest path consumes the manifest. The largest unshipped open-core enabler per the strategic guidance.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — zero source-tree hits) → confirmed unchanged in `oc-separation-audit-20260502.md` §6.6 (still missing) / §7 P2 (action item #11). v13.1 close audit and v13.2 audit both flagged this as biggest unshipped OC adoption wedge.
**Estimated effort:** 2 weeks
**Why this matters:** "A new user should be able to publish a working geospatial catalog in 10 minutes — from `docker compose up` to a browsable, shareable catalog of their own data" is the GTM falsifiable adoption target. Without a declarative manifest + `apply` workflow, that target is hand-wavy.

Plans:
- [ ] TBD

---

### Phase 999.13: Persistent connector registry (BACKLOG — P2)

**Goal:** Greenfield Enterprise-tier feature — `Connector` ORM (id, type, config_jsonb, schedule, last_sync_at, owner_id) + `ConnectorAdapter` Protocol + Celery beat scheduler integration + encrypted credential vault. Distinct from current stateless probes at `backend/app/modules/catalog/sources/adapters/{wfs,arcgis,stac,ogcapi}.py`.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #8 (🔴) / §7 P2
**Estimated effort:** 2–3 weeks
**Tier:** Enterprise — stored credentials + scheduled mirroring is an explicit Enterprise paywall per `docs-internal/GTM/free-vs-enterprise.md` §6.

Plans:
- [ ] TBD

---

### Phase 999.14: Helm chart + AMI Packer pipeline (BACKLOG — P2)

**Goal:** Build a `deployment/` directory with Helm chart for K8s deployments + Packer template for AWS Marketplace AMI distribution. Phase 223 wired the `BillingExtension` for AMI metering, but there's currently no path to actually ship the AMI image to AWS Marketplace.
**Source:** `oc-separation-audit-20260430-b.md` §4 (HIGH severity — no `deployment/`, no Helm, no AMI pipeline) → confirmed unchanged in `oc-separation-audit-20260502.md` §4 (structural gap unchanged) / §7 P2 (action item #13)
**Estimated effort:** 1–2 weeks

Plans:
- [ ] TBD

---

### Phase 999.15: SBOM + signed image distribution (BACKLOG — P2)

**Goal:** Add SBOM generation (CycloneDX or SPDX) + Cosign-signed images to the deployment pipeline. Typical enterprise procurement gate.
**Source:** `oc-separation-audit-20260430-b.md` §4 finding #4 / §7 P2
**Estimated effort:** 1 week

Plans:
- [ ] TBD

---

### Phase 999.16: Extract geolens-schemas package (BACKLOG — P2)

**Goal:** Extract `backend/app/standards/{stac,ogc,dcat}/` schemas + validators into a standalone `geolens-schemas` PyPI package (Apache-2.0). Embedded today; persistent OSS-surface gap per audits since v13.1 close.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — schema/validator package not extractable) → confirmed unchanged in `oc-separation-audit-20260502.md` §6.1 (still no `schemas/` or `validators/` dir) / §7 P2 (action item #12)
**Estimated effort:** 1 week
**Unblocks:** Schema-validator OSS adoption beyond GeoLens consumers; reusable wedge for FAIR-aligned tooling.

Plans:
- [ ] TBD

---

### ~~Phase 999.17: Run cold PyPI/npm publish workflows~~ — PROMOTED to Phase 228 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 228 (`run-cold-publish-workflows`). See Archived Phase Details above.

---

### ~~Phase 999.18: SAML test fixture generator → tmp_path~~ — PROMOTED to Phase 227 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 227 (`saml-test-fixture-tmp-path`). See Archived Phase Details above.

---

### ~~Phase 999.19: EmbeddingProviderExtension Protocol~~ — PROMOTED to Phase 231 (v13.4, 2026-05-02)

Promoted into the v13.4 Boundary Closeout milestone as Phase 231 (`embedding-provider-extension-protocol`). See Archived Phase Details above.

---

### ~~Phase 999.20: Symmetric CatalogPort Protocol~~ — PROMOTED to Phase 230 (v13.4, 2026-05-02)

Promoted into the v13.4 Boundary Closeout milestone as Phase 230 (`catalog-port-protocol-symmetric`). See Archived Phase Details above. Lifts the v13.4 Coupling Health audit-grade target from B+ → A−.

---

### Phase 999.21: Split catalog/maps/service.py (BACKLOG — P2)

**Goal:** Apply the Phase 224 façade pattern to `backend/app/modules/catalog/maps/service.py` (1297 LOC). Split into ≤500-LOC sibling modules behind a thin re-export façade; add a `test_no_external_imports_of_maps_service_submodules` architecture guard.
**Source:** `oc-separation-audit-20260502.md` §5 (Catalog god-module split — next candidates) / §7 P2 (action item #7)
**Estimated effort:** 3–5 days
**Unblocks:** Future enterprise-overlay friction reduction (single largest service module after Phase 224); easier targeted code review; lays groundwork for `catalog/maps` extension seams (sharing controls, scheduled cleanup).
**Reference:** Phase 224 (catalog-god-module-split) is the textbook precedent — 1407 LOC → 87-LOC façade + 5 modules averaging 340 LOC.

Plans:
- [ ] TBD

---

### Phase 999.22: Split catalog/search/service.py (BACKLOG — P2)

**Goal:** Apply the Phase 224 façade pattern to `backend/app/modules/catalog/search/service.py` (1312 LOC). Same approach as Phase 999.21.
**Source:** `oc-separation-audit-20260502.md` §5 (Catalog god-module split — next candidates) / §7 P2 (action item #8)
**Estimated effort:** 3–5 days
**Unblocks:** Same as 999.21; also reduces friction for future search-related extension seams (e.g., a `SearchScorerExtension` for enterprise-tier custom relevance).

Plans:
- [ ] TBD

---

### ~~Phase 999.23: Share/embed token expiration gating~~ — RESOLVED, VERIFY in Phase 234 (v13.5, 2026-05-03)

**Goal:** Resolve the contract mismatch between (a) `docs-internal/GTM/pricing-to-tiers.md:42` listing "Advanced sharing controls (expiring links, domain restrictions)" as a Team-tier paid feature, and (b) the current implementation + ~20 test cases that treat these as free features in `embed_tokens/` and `catalog/maps/share/`. The 2026-05-02 oc-audit (§1) flagged this as four 🟡 boundary risks: field descriptions and one endpoint docstring claimed "(enterprise only)" while neither schema nor service actually applied the Phase-219 dual-layer gate.

**Source:** `oc-separation-audit-20260502.md` §1 (4 🟡 findings) + §7 P0 (action item #1). The audit's literal recommendation was binary: "either gate ... OR strip the misleading copy."

**Stopgap shipped:** The strip-the-copy path landed in commit `6db19582` (2026-05-02) — descriptions no longer lie, audit finding closed at the contract-drift level.

**Resolution shipped:** Branch A landed on 2026-05-03 per `docs-internal/audits/oc-separation-audit-20260503.md`: Community rejects custom embed-token lifetimes, embed domain restrictions, and expiring share links at schema and service layers; Enterprise continues to allow them; the builder UI hides expiration/domain controls in Community while preserving basic share-link revoke.

**v13.5 follow-up:** Phase 234 verified the contract stays aligned across GTM docs, API text, UI affordances, schema validators, and service guards. See [v13.5 archive](milestones/v13.5-ROADMAP.md).
