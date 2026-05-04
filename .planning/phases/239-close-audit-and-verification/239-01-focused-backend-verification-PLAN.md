---
phase: 239-close-audit-and-verification
plan: "01"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/service_shared.py
  - backend/app/modules/catalog/maps/service_crud.py
  - backend/app/modules/catalog/maps/service_layers.py
  - backend/app/modules/catalog/maps/service_public.py
  - backend/app/modules/catalog/search/service.py
  - backend/app/modules/catalog/search/service_filters.py
  - backend/app/modules/catalog/search/service_facets.py
  - backend/app/modules/catalog/search/service_collections.py
  - backend/app/modules/catalog/search/service_semantic.py
  - backend/app/modules/catalog/search/service_datasets.py
  - backend/app/modules/catalog/search/service_records.py
  - backend/tests/test_maps.py
  - backend/tests/test_search.py
  - backend/tests/test_hybrid_search.py
  - backend/tests/test_search_facets.py
  - backend/tests/test_search_cache.py
  - backend/tests/test_vrt_catalog_175.py
  - backend/tests/test_layering.py
  - .planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md
autonomous: true
requirements:
  - QUAL-01
  - QUAL-02
must_haves:
  truths:
    - Focused backend maps and search regression gates pass through the public facades after the v13.6 decomposition.
    - Hybrid search, search facets, search cache, and VRT search enrichment coverage pass without weakening the behavior asserted in Phases 236-238.
    - Ruff check and ruff format --check pass for the touched catalog maps/search modules and focused regression tests.
    - Any failed gate is fixed forward in the smallest relevant catalog module or focused test, with no broad source rewrites or unrelated cleanup.
  artifacts:
    - path: .planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md
      provides: Focused backend verification and lint/format command evidence for the v13.6 close gate
  key_links:
    - from: backend/app/modules/catalog/maps/service.py
      to: backend/tests/test_maps.py
      via: Public maps facade exercised by focused map regression coverage
      pattern: "test_maps.py"
    - from: backend/app/modules/catalog/search/service.py
      to: backend/tests/test_search.py
      via: Public search facade exercised by focused dataset search coverage
      pattern: "test_search.py"
    - from: backend/app/modules/catalog/search/service.py
      to: backend/tests/test_hybrid_search.py
      via: Semantic and hybrid search contracts preserved after decomposition
      pattern: "test_hybrid_search.py"
    - from: backend/app/modules/catalog/search/service.py
      to: backend/tests/test_search_facets.py
      via: Facet response and count contracts preserved after decomposition
      pattern: "test_search_facets.py"
    - from: backend/app/modules/catalog/search/service.py
      to: backend/tests/test_search_cache.py
      via: Search cache behavior preserved after decomposition
      pattern: "test_search_cache.py"
    - from: backend/app/modules/catalog/search/service.py
      to: backend/tests/test_vrt_catalog_175.py
      via: VRT search enrichment asserted through facade/helper contracts
      pattern: "TestSearchEnrichmentVrt"
---

<objective>
Run the focused backend verification and style gates required to close v13.6.

Purpose: prove the maps/search service decomposition remains behavior-preserving under the focused regression surface and that touched catalog modules are ruff-clean and format-clean.
Output: command evidence in `239-01-SUMMARY.md`, plus narrow fix-forward patches only if a required gate fails.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
@.agents/skills/geolens-test-audit/SKILL.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/phases/236-maps-service-decomposition/236-VERIFICATION.md
@.planning/phases/237-search-service-decomposition/237-VERIFICATION.md
@.planning/phases/238-boundary-guards-and-contract-stabilization/238-VERIFICATION.md
@docs/testing-and-ci.md
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/service_crud.py
@backend/app/modules/catalog/maps/service_layers.py
@backend/app/modules/catalog/maps/service_public.py
@backend/app/modules/catalog/search/service.py
@backend/app/modules/catalog/search/service_filters.py
@backend/app/modules/catalog/search/service_facets.py
@backend/app/modules/catalog/search/service_collections.py
@backend/app/modules/catalog/search/service_semantic.py
@backend/app/modules/catalog/search/service_datasets.py
@backend/app/modules/catalog/search/service_records.py
@backend/tests/test_maps.py
@backend/tests/test_search.py
@backend/tests/test_hybrid_search.py
@backend/tests/test_search_facets.py
@backend/tests/test_search_cache.py
@backend/tests/test_vrt_catalog_175.py
@backend/tests/test_layering.py

<verification_scope>
Use the focused close-gate surface requested for Phase 239:
- `tests/test_maps.py`
- `tests/test_search.py`
- `tests/test_hybrid_search.py`
- `tests/test_search_facets.py`
- `tests/test_search_cache.py`
- `tests/test_vrt_catalog_175.py`

Use the active GeoLens Compose database on `POSTGRES_PORT=5434` when DB-backed tests need Postgres. If the DB is not running, start only the documented database dependency with `docker compose up -d --wait db` and rerun the exact failing command. Do not claim a pass from a substitute command.
</verification_scope>
</context>

<tasks>
<task type="auto">
  <name>Run focused backend maps/search regression gates</name>
  <files>backend/app/modules/catalog/maps/service.py, backend/app/modules/catalog/maps/service_shared.py, backend/app/modules/catalog/maps/service_crud.py, backend/app/modules/catalog/maps/service_layers.py, backend/app/modules/catalog/maps/service_public.py, backend/app/modules/catalog/search/service.py, backend/app/modules/catalog/search/service_filters.py, backend/app/modules/catalog/search/service_facets.py, backend/app/modules/catalog/search/service_collections.py, backend/app/modules/catalog/search/service_semantic.py, backend/app/modules/catalog/search/service_datasets.py, backend/app/modules/catalog/search/service_records.py, backend/tests/test_maps.py, backend/tests/test_search.py, backend/tests/test_hybrid_search.py, backend/tests/test_search_facets.py, backend/tests/test_search_cache.py, backend/tests/test_vrt_catalog_175.py</files>
  <action>Run the focused backend regression command exactly as the primary close gate. If it fails because the documented Compose database is not running, run `docker compose up -d --wait db` once and rerun the same pytest command. If a test fails after the environment is available, fix forward in the smallest relevant maps/search service module or focused test. Preserve public facade imports, response schemas, cache semantics, hybrid/RRF behavior, and VRT enrichment contracts documented by Phases 236-238. Do not weaken assertions, delete coverage, or rewrite unrelated modules. Record every failed command, root cause, fix, and rerun result for the summary.</action>
  <verify>
    <automated>cd backend &amp;&amp; env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q</automated>
  </verify>
  <done>The focused backend close-gate pytest command passes, or the plan is explicitly blocked with exact environment/test failure evidence and no false green claim.</done>
</task>

<task type="auto">
  <name>Run ruff check and format checks for touched catalog modules</name>
  <files>backend/app/modules/catalog/maps/service.py, backend/app/modules/catalog/maps/service_shared.py, backend/app/modules/catalog/maps/service_crud.py, backend/app/modules/catalog/maps/service_layers.py, backend/app/modules/catalog/maps/service_public.py, backend/app/modules/catalog/search/service.py, backend/app/modules/catalog/search/service_filters.py, backend/app/modules/catalog/search/service_facets.py, backend/app/modules/catalog/search/service_collections.py, backend/app/modules/catalog/search/service_semantic.py, backend/app/modules/catalog/search/service_datasets.py, backend/app/modules/catalog/search/service_records.py, backend/tests/test_maps.py, backend/tests/test_search.py, backend/tests/test_hybrid_search.py, backend/tests/test_search_facets.py, backend/tests/test_search_cache.py, backend/tests/test_vrt_catalog_175.py, backend/tests/test_layering.py</files>
  <action>Run ruff check and ruff format --check over the decomposed maps/search service modules plus the focused backend test files. If either command fails, apply the smallest style or import-order fix needed. Use `uv run ruff format` only on the exact failing files when formatting is required, then rerun both commands and the focused pytest command from Task 1 to prove no behavior was changed by the fix.</action>
  <verify>
    <automated>cd backend &amp;&amp; uv run ruff check app/modules/catalog/maps app/modules/catalog/search tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py tests/test_layering.py</automated>
    <automated>cd backend &amp;&amp; uv run ruff format --check app/modules/catalog/maps app/modules/catalog/search tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py tests/test_layering.py</automated>
  </verify>
  <done>Ruff check and format checks pass for the touched catalog maps/search modules and focused tests, with any fix-forward changes revalidated by the focused pytest close gate.</done>
</task>

<task type="auto">
  <name>Write focused verification summary</name>
  <files>.planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md</files>
  <action>Create `239-01-SUMMARY.md` using the GSD summary template. Include the exact focused pytest, ruff check, and ruff format commands; pass/fail status; any DB startup needed; every fix-forward change made; and residual warnings or limitations. If any required gate remains blocked, mark the summary blocked and name the blocker explicitly for the close audit plan.</action>
  <verify>
    <automated>test -s .planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md</automated>
    <automated>rg -n "test_maps.py|test_search.py|test_hybrid_search.py|test_search_facets.py|test_search_cache.py|test_vrt_catalog_175.py|ruff check|ruff format" .planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md</automated>
  </verify>
  <done>`239-01-SUMMARY.md` contains enough command evidence for the Phase 239 close-gate audit to decide QUAL-01 and QUAL-02.</done>
</task>
</tasks>

<verification>
- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q`
- `cd backend && uv run ruff check app/modules/catalog/maps app/modules/catalog/search tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py tests/test_layering.py`
- `cd backend && uv run ruff format --check app/modules/catalog/maps app/modules/catalog/search tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py tests/test_layering.py`
- `node /Users/ishiland/.codex/get-shit-done/bin/gsd-tools.cjs verify plan-structure .planning/phases/239-close-audit-and-verification/239-01-focused-backend-verification-PLAN.md`
</verification>

<success_criteria>
- QUAL-01 is satisfied: focused backend verification passes for maps, search, hybrid search, search facets, search cache, and VRT search enrichment coverage.
- QUAL-02 is satisfied: backend ruff and format checks pass for the touched catalog maps/search modules and focused tests.
- Any fix-forward changes are narrow, behavior-preserving, and revalidated by the focused pytest gate.
</success_criteria>

<output>
After completion, create `.planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md`.
</output>
